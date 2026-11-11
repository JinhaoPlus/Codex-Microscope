"""Build synthetic README walkthroughs with verified public-code evidence.

Run with Python 3.10+ from any directory. JSON is written to stdout; no Codex
history, account settings or service is read or modified. The conversation,
timestamps, paths and usage events are invented. Commands read this checkout,
and the displayed patch is the public change in commit 81886c7, not a new edit.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pricing
import server
import token_usage


PUBLIC_COMMIT = '81886c7'
SOURCE = 'designs/browser/token-usage.js'
WORKSPACE = '/workspace/Codex-Microscope'
NOTES = '/workspace/Project-notes'
BASE_TIME = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)
DAY = datetime(2026, 11, 10, tzinfo=timezone.utc)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def check_public_text(value):
    """Reject local machine identifiers or credential-shaped output before export."""
    text = str(value)
    forbidden = [str(ROOT), '/Users/', '/private/var/', '/var/folders/',
                 r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
                 r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
                 r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}',
                 r'\bAKIA[A-Z0-9]{16}\b']
    for pattern in forbidden:
        if re.search(re.escape(pattern) if pattern.startswith('/') else pattern, text):
            raise ValueError('Command output contains a private path or credential-shaped value')
    return text


def run_public_command(arguments, display=None):
    started = time.monotonic()
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, timeout=60)
    stdout, stderr = check_public_text(result.stdout), check_public_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f'Public evidence command failed: {display or arguments[0]}\n{stdout}{stderr}')
    return {'cmd': display or ' '.join(arguments), 'output': stdout + stderr,
            'exit_code': result.returncode, 'wall_time_seconds': round(time.monotonic() - started, 3)}


def public_evidence():
    search = run_public_command(['rg', '-n', 'function usageOverviewSVG|const totals=Array.from', SOURCE])
    text = (ROOT / SOURCE).read_text()
    lines = text.splitlines()
    start = next(index + 1 for index, line in enumerate(lines) if line.startswith('function usageOverviewSVG('))
    end = min(start + 18, len(lines))
    read = run_public_command(['sed', '-n', f'{start},{end}p', SOURCE],
                              f"sed -n '{start},{end}p' {SOURCE}")
    diff = run_public_command(['git', 'diff', PUBLIC_COMMIT + '^', PUBLIC_COMMIT, '--', SOURCE])
    if not diff['output'].startswith('diff --git ') or '+function usageOverviewSVG(' not in diff['output']:
        raise ValueError('Expected public sparse-overview patch is unavailable')
    tests = run_public_command([sys.executable, '-m', 'unittest', '-q', 'test_usage_chart'],
                               'python3 -m unittest -q test_usage_chart')
    if not re.search(r'Ran \d+ tests? in ', tests['output']) or not re.search(r'\nOK\s*$', tests['output']):
        raise ValueError('Usage-chart test output did not confirm success')
    return {'search': search, 'read': read, 'read_range': [start, end], 'diff': diff, 'tests': tests}


class Walkthrough:
    def __init__(self):
        self.records = []
        self.tick = 0

    def add(self, kind, payload):
        stamp = BASE_TIME + timedelta(seconds=self.tick)
        self.tick += 4
        record = {'type': kind, 'timestamp': stamp.isoformat().replace('+00:00', 'Z'), 'payload': payload}
        self.records.append(record)

    def message(self, role, text):
        self.add('response_item', {'type': 'message', 'role': role,
                                  'content': [{'type': 'input_text' if role != 'assistant' else 'output_text', 'text': text}]})

    def command(self, identifier, evidence, actions):
        args = {'cmd': evidence['cmd'], 'workdir': WORKSPACE, 'max_output_tokens': 12000}
        self.add('response_item', {'type': 'function_call', 'name': 'exec_command',
                                  'call_id': identifier, 'arguments': encoded(args)})
        self.add('event_msg', {'type': 'item_completed', 'call_id': identifier,
                              'item': {'type': 'CommandExecution', 'id': identifier,
                                       'command': evidence['cmd'], 'cwd': WORKSPACE,
                                       'parsed_cmd': actions, 'status': 'completed',
                                       'exit_code': evidence['exit_code'], 'aggregated_output': evidence['output'],
                                       'duration_ms': round(evidence['wall_time_seconds'] * 1000)}})
        self.add('response_item', {'type': 'function_call_output', 'call_id': identifier,
                                  'output': encoded({key: value for key, value in evidence.items() if key != 'cmd'})})


def thread_rows(language):
    zh = language == 'zh-CN'
    rows = [
        ('readme-usage-fix', '修复日期范围预览中的三角形' if zh else 'Fix the date-range preview', WORKSPACE, 'Codex Microscope', 'vscode', 'Codex Desktop'),
        ('readme-language-menu', '让语言菜单更清晰' if zh else 'Refine the language menu', WORKSPACE, 'Codex Microscope', 'cli', 'codex_cli'),
        ('readme-tool-notes', '说明工具输出的来源与边界' if zh else 'Document tool-result provenance', NOTES, '项目笔记' if zh else 'Project notes', 'vscode', 'Codex Desktop'),
    ]
    result = []
    for index, (identifier, title, cwd, workspace_name, source, originator) in enumerate(rows):
        updated = int((BASE_TIME - timedelta(hours=index * 3)).timestamp())
        result.append({'id': identifier, 'title': title, 'name': '', 'cwd': cwd,
                       'workspace_name': workspace_name, 'source': source, 'originator': originator,
                       'updated_at': updated, 'created_at': updated - 300, 'archived': False,
                       'model': 'gpt-6.1-sol' if index != 1 else 'gpt-6-astra',
                       'status': 'completed', 'available': True,
                       'category': 'app' if source == 'vscode' else 'cli'})
    return result


def rollout(language, evidence, tools):
    zh = language == 'zh-CN'
    walk = Walkthrough()
    walk.add('session_meta', {'id': 'readme-usage-fix', 'cwd': WORKSPACE, 'originator': 'codex_cli',
                              'readme_provenance': 'Reconstructed conversation; public source and test evidence; no private session data.'})
    walk.message('developer', '# AGENTS.md instructions\n\nUse synthetic records in tests. Keep SQLite read-only.\nBind the service to 127.0.0.1. Do not execute commands from session logs.')
    walk.message('developer', '<environment_context>\n<cwd>' + WORKSPACE + '</cwd>\n<shell>zsh</shell>\n<current_date>2026-11-10</current_date>\n<timezone>Asia/Singapore</timezone>\n</environment_context>')
    walk.message('developer', encoded({'tools': tools}))
    walk.add('event_msg', {'type': 'task_started', 'turn_id': 'readme-turn-inspect'})
    walk.message('user', '只有一天有用量时，日期范围预览会拉出一个大三角形。帮我检查公开补丁，并确认空白日期是否归零。' if zh else
                 'The date-range preview turns into a large triangle when only one day has activity. Review the public fix and check that empty days stay at zero.')
    walk.add('turn_context', {'turn_id': 'readme-turn-inspect', 'cwd': WORKSPACE,
                              'model': 'gpt-6.1-sol', 'effort': 'high', 'approval_policy': 'on-request',
                              'sandbox_policy': {'type': 'workspace-write'}, 'date': '2026-11-10', 'timezone': 'Asia/Singapore'})
    walk.message('assistant', '我先检查预览的坐标生成，再对照公开提交 `81886c7`。这里的对话是重建示例，源码、diff 和测试输出来自当前公开仓库。' if zh else
                 "I'll inspect how the preview builds its points, then compare public commit `81886c7`. This is a reconstructed walkthrough; the source, diff and test output come from the public checkout.")
    walk.command('readme-search', evidence['search'], [{'type': 'search', 'query': 'function usageOverviewSVG|const totals=Array.from', 'path': SOURCE, 'cmd': evidence['search']['cmd']}])
    walk.command('readme-read', evidence['read'], [{'type': 'read', 'path': SOURCE, 'cmd': evidence['read']['cmd'],
                                                 'start_line': evidence['read_range'][0], 'end_line': evidence['read_range'][1]}])
    walk.message('assistant', '问题出在坐标只覆盖有记录的日期，折线跨过了前后的空白。补丁改为遍历整个可见日期范围，缺失日期补零；当天的点仍落在对应日期的中心。' if zh else
                 'The old points covered only recorded dates, so the outline ramped across the empty padding. The fix visits every visible date, fills missing dates with zero, and keeps each point centered on its day.')
    # These records reconstruct the already committed patch so the production
    # parser can retain its call/event association and render native diff lines.
    # Nothing here executes apply_patch or writes to the public source checkout.
    diff_hunks = evidence['diff']['output'][evidence['diff']['output'].index('@@'):]
    patch_text = '*** Begin Patch\n*** Update File: ' + SOURCE + '\n' + diff_hunks + '*** End Patch'
    walk.add('response_item', {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'readme-public-patch',
                              'input': 'text(await tools.apply_patch(' + encoded(patch_text) + '))',
                              'readme_provenance': 'Reconstructed request from the public committed diff; not executed.'})
    walk.add('event_msg', {'type': 'item_completed', 'call_id': 'readme-public-patch', 'item': {
        'type': 'FileChange', 'id': 'readme-public-diff', 'status': 'completed',
        'changes': {SOURCE: {'type': 'update', 'unified_diff': diff_hunks}},
        'aggregated_output': 'Public commit 81886c7. Reconstructed FileChange event; no patch was applied.',
        'readme_provenance': {'commit': PUBLIC_COMMIT, 'command': evidence['diff']['cmd'], 'reconstructed_event': True},
    }})
    walk.add('response_item', {'type': 'custom_tool_call_output', 'call_id': 'readme-public-patch',
                              'output': 'Script completed\nWall time 0.0 seconds\nOutput:\n{}',
                              'readme_provenance': 'Reconstructed completion for the existing public patch.'})
    walk.add('event_msg', {'type': 'task_started', 'turn_id': 'readme-turn-verify'})
    walk.message('user', '也验证一下记录落在范围两端、完全没有用量时的表现。不要只看单日案例。' if zh else
                 'Also check activity at both ends of the range and a range with no usage, not just the single-day case.')
    walk.add('turn_context', {'turn_id': 'readme-turn-verify', 'cwd': WORKSPACE,
                              'model': 'gpt-6.1-sol', 'effort': 'high', 'date': '2026-11-10', 'timezone': 'Asia/Singapore'})
    walk.message('assistant', '测试会覆盖单日峰值、范围两端的活动、空白日期以及零用量。我会实际运行图表回归测试，保留原始结果。' if zh else
                 "The regression covers a single-day spike, activity at both range edges, empty dates and zero usage. I'll run the chart test and retain its actual result.")
    walk.command('readme-tests', evidence['tests'], [{'type': 'unknown', 'cmd': evidence['tests']['cmd']}])
    walk.message('assistant', '图表回归测试通过。单日峰值两侧保持零基线，首尾日期对齐，零用量不会产生 `NaN` 或 `Infinity`。这里只验证公开补丁，没有修改任何会话或文件。' if zh else
                 'The chart regression passed. Empty dates stay on the baseline around the single-day spike, edge dates align correctly, and zero usage produces neither `NaN` nor `Infinity`. This verifies the public fix without changing any session or source file.')
    return walk


def usage_events(thread_index):
    """Invented work patterns, never real account usage or an actual invoice."""
    rng = random.Random(8188607 + thread_index)
    result = []
    first = DAY - timedelta(days=59)
    for day_index in range(60):
        day = first + timedelta(days=day_index)
        active = .82 if day.weekday() < 5 else .18
        if thread_index == 0 and day_index < 12:
            active *= .3
        if thread_index == 1 and (day_index < 28 or day_index > 48):
            active *= .16
        if thread_index == 2 and day_index % 7 not in (1, 3, 4):
            active *= .25
        if rng.random() > active and not (thread_index == 0 and day_index in (0, 59)):
            continue
        peak = 2.8 if day_index in (19, 34, 47, 56) else 1
        sessions = rng.randint(3, 8) if thread_index != 2 else rng.randint(1, 3)
        for call in range(sessions):
            hour = rng.choice([1, 2, 5, 6, 7, 8, 10, 11, 12])
            timestamp = day + timedelta(hours=hour, minutes=rng.randrange(60))
            total_input = int(rng.randint(9000, 48000) * peak)
            cache_ratio = rng.uniform(.28, .55) if call == 0 else rng.uniform(.68, .94)
            cached = int(total_input * cache_ratio)
            output = int(rng.randint(600, 3400) * peak)
            reasoning = int(output * rng.uniform(.22, .58))
            probability_astra = .28 if day_index in (19, 34, 47, 56) else .10 if thread_index == 0 else .18
            model = 'gpt-6-astra' if rng.random() < probability_astra else 'gpt-6.1-sol'
            result.append({'time': timestamp.isoformat().replace('+00:00', 'Z'),
                           'turn': f'readme-{thread_index}-{day_index}-{call}', 'cwd': WORKSPACE if thread_index < 2 else NOTES,
                           'model': model, 'tier': 'standard', 'request_input': total_input,
                           'tokens': {'input': total_input - cached, 'cached': cached, 'cache_write': 0,
                                      'output': output - reasoning, 'reasoning': reasoning},
                           'turn_number': len(result) + 1, 'turn_time': timestamp.isoformat(),
                           'summary': '', 'summary_source': None})
    return sorted(result, key=lambda item: item['time'])


def usage_report(rows, rates):
    with tempfile.TemporaryDirectory(prefix='microscope-readme-') as directory:
        home = Path(directory).resolve()
        price_home = home / 'pricing'; price_home.mkdir()
        snapshot_data = encoded(rates['data']).encode()
        (price_home / 'settings.json').write_text(encoded({'basis': 'api', 'source': 'litellm', 'missing_tier': 'unrated'}))
        (price_home / 'litellm.json').write_text(encoded({
            'url': rates['source'], 'fetched_at': rates['observed_date'] + 'T00:00:00+00:00',
            'sha256': hashlib.sha256(snapshot_data).hexdigest(), 'data': rates['data'],
        }))
        local_rows, by_path = [], {}
        for index, row in enumerate(rows):
            path = home / (row['id'] + '.jsonl'); path.touch()
            local_rows.append({**row, 'rollout_path': str(path)})
            by_path[path] = usage_events(index)
        with patch.object(pricing, 'LOCAL', price_home), patch.object(token_usage, 'events_for', side_effect=lambda path: by_path[path]):
            report = token_usage.report(local_rows, home, {'scope': ['all'], 'dimension': ['directory'], 'timezone': ['Asia/Singapore']})
        # The chart endpoint's wall-clock "today" is stabilized for repeatable docs.
        # Usage and all cost totals above are still calculated by the production report.
        report['calendar_today'] = DAY.strftime('%Y-%m-%d')
        return report


def language_payload(language, evidence, tool_fixture, rates):
    rows = thread_rows(language)
    walk = rollout(language, evidence, tool_fixture['tools'])
    lines = [encoded(record) for record in walk.records]
    items, bad, snapshots = server.parse_rollout(io.StringIO('\n'.join(lines) + '\n'))
    if bad:
        raise ValueError('Synthetic README records failed production parsing')
    details, raw = {}, {}
    for item in items:
        if item.get('kind') == 'tool':
            index = str(item['index'])
            details[index] = server.page_payload(items, {'item': [index]})
            raw[index] = {'records': [lines[line - 1] for line in item.get('_raw_lines', [])]}
    rows[0]['updated_at'] = int(datetime.fromisoformat(walk.records[-1]['timestamp'].replace('Z', '+00:00')).timestamp())
    turns = []
    for identifier in ('readme-turn-inspect', 'readme-turn-verify'):
        started = next(record['timestamp'] for record in walk.records
                       if record['payload'].get('type') == 'task_started' and record['payload'].get('turn_id') == identifier)
        completed = max(item['time'] for item in items if item.get('turn_id') == identifier)
        milliseconds = int((datetime.fromisoformat(completed.replace('Z', '+00:00')) -
                            datetime.fromisoformat(started.replace('Z', '+00:00'))).total_seconds() * 1000)
        turns.append({'turn_id': identifier, 'status': 'completed', 'started_at': started,
                      'completed_at': completed, 'duration_ms': milliseconds})
    page = server.page_payload(items, {'start': ['0']})
    page.update(thread=rows[0], skipped=0, relations={'parent': None, 'children': []}, history_warning=None, turns=turns)
    diff_index = next(item['index'] for item in items if item.get('call_id') == 'readme-public-patch')
    test_index = next(item['index'] for item in items if item.get('call_id') == 'readme-tests')
    context = server.page_payload(items, {'view': ['context']})['items']
    return {'threads': rows, 'page': page, 'details': details, 'raw': raw, 'context': context,
            'usage': usage_report(rows, rates), 'hero_steps': [diff_index, test_index],
            'turn_context': snapshots,
            'provenance': {'conversation': 'Synthetic reconstruction, not a captured user conversation.',
                           'change': 'https://github.com/JinhaoPlus/Codex-Microscope/commit/81886c7',
                           'commands': 'Read-only commands executed against the public checkout; test uses the running Python interpreter.',
                           'tools': tool_fixture['source'], 'rates': rates['source'],
                           'rates_observed_date': rates['observed_date'], 'rates_source_sha256': rates['source_sha256'],
                           'usage': 'Seeded synthetic activity; API-equivalent estimates from recorded public rates, not actual billing.'}}


def main():
    tools = json.loads((ROOT / 'docs/fixtures/codex-shell-tools.json').read_text())
    rates = json.loads((ROOT / 'docs/fixtures/readme-price-rates.json').read_text())
    evidence = public_evidence()
    payload = {language: language_payload(language, evidence, tools, rates) for language in ('en', 'zh-CN')}
    result = encoded(payload)
    check_public_text(result)
    print(result)


if __name__ == '__main__':
    main()
