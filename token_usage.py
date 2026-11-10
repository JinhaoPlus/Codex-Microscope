"""Read recorded model usage without counting cached/reasoning tokens twice."""
import json
import re
import threading
from pricing import Estimator, empty_cost, add_cost, cost_json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from session_io import open_rollout, resolve_rollout, stamp

TYPES = ('input', 'cached', 'cache_write', 'output', 'reasoning')
COUNTERS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
            'output_tokens', 'reasoning_output_tokens')
CACHE = {}
LOCK = threading.Lock()


def counters(value):
    if not isinstance(value, dict) or 'input_tokens' not in value or 'output_tokens' not in value:
        return None
    return {key: max(0, int(value.get(key) or 0)) for key in COUNTERS}


def split_usage(value):
    cached = min(value['cached_input_tokens'], value['input_tokens'])
    written = min(value['cache_write_input_tokens'], value['input_tokens'] - cached)
    reasoning = min(value['reasoning_output_tokens'], value['output_tokens'])
    return dict(zip(TYPES, (value['input_tokens'] - cached - written, cached, written,
                            value['output_tokens'] - reasoning, reasoning)))


def message_excerpt(value):
    if isinstance(value, list):
        value = '\n'.join(part.get('text', '') for part in value if isinstance(part, dict) and isinstance(part.get('text'), str))
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if re.match(r'^(# AGENTS\.md instructions|<(environment_context|external_browser_tabs|external_codex_apps_open_page|permissions instructions)[\s>])', value):
        return ''
    if value.startswith('# Files mentioned by the user:') and '## My request:' in value:
        value = value.split('## My request:', 1)[1]
    reply = re.fullmatch(r'\s*<send_user_message_question_reply>([\s\S]*)</send_user_message_question_reply>\s*', value)
    if reply:
        try:
            answers = json.loads(reply[1])
            value = '；'.join(str(item.get('answer', '')) for item in answers if isinstance(item, dict)) if isinstance(answers, list) else ''
        except ValueError:
            return ''
    value = re.sub(r'<image\b[^>]*>[\s\S]*?</image>', '', value)
    value = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', value)
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    value = re.sub(r'(\*\*|__|~~|`+)(.*?)\1', r'\2', value, flags=re.S)
    value = re.sub(r'\s+', ' ', value).strip().lstrip('#>*- `')
    return value[:180] + ('…' if len(value) > 180 else '')


def scan(path):
    events = []
    previous = None
    turn = None
    cwd = ''
    model = None
    tier = None
    seen = set()
    turns = {}
    pending_request = ''
    def remember_turn(identifier, timestamp):
        if identifier:
            return turns.setdefault(identifier, {'number': len(turns) + 1, 'time': timestamp, 'request': '', 'reply': ''})
        return None
    with open_rollout(path) as stream:
        for line in stream:
            if not any(tag in line[:250] for tag in ('"turn_context"', '"token_count"', '"task_started"', '"thread_settings_applied"', '"message"', '"user_message"', '"agent_message"')):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get('payload') or {}
            if record.get('type') == 'turn_context':
                turn = payload.get('turn_id', turn)
                meta = remember_turn(turn, record.get('timestamp'))
                if meta and pending_request:
                    meta['request'] = meta['request'] or pending_request
                    pending_request = ''
                cwd = payload.get('cwd', cwd)
                model = payload.get('model', model)
                continue
            role = None
            if record.get('type') == 'response_item' and payload.get('type') == 'message':
                role = payload.get('role')
            elif record.get('type') == 'event_msg':
                role = {'user_message': 'user', 'agent_message': 'assistant'}.get(payload.get('type'))
            if role in ('user', 'assistant'):
                excerpt = message_excerpt(payload.get('content', payload.get('message', payload.get('text', ''))))
                meta = remember_turn(turn, record.get('timestamp'))
                if excerpt and meta:
                    key = 'request' if role == 'user' else 'reply'
                    if not meta[key] or (role == 'assistant' and payload.get('phase') == 'final_answer'):
                        meta[key] = excerpt
                elif excerpt and role == 'user':
                    pending_request = pending_request or excerpt
                continue
            if record.get('type') != 'event_msg':
                continue
            if payload.get('type') == 'thread_settings_applied':
                settings = payload.get('thread_settings') or {}
                raw_tier = settings.get('service_tier')
                tier = {'priority': 'fast', 'default': 'standard'}.get(raw_tier, raw_tier)
                model = settings.get('model', model)
                continue
            if payload.get('type') == 'task_started':
                turn = payload.get('turn_id', turn)
                meta = remember_turn(turn, record.get('timestamp'))
                if meta and pending_request:
                    meta['request'] = meta['request'] or pending_request
                    pending_request = ''
                continue
            if payload.get('type') != 'token_count' or not isinstance(payload.get('info'), dict):
                continue
            info = payload['info']
            total = counters(info.get('total_token_usage'))
            last = counters(info.get('last_token_usage'))
            if total is not None:
                signature = tuple(total.values())
                if signature in seen:
                    continue
                seen.add(signature)
                if previous is not None and all(total[k] >= previous[k] for k in COUNTERS):
                    usage = {k: total[k] - previous[k] for k in COUNTERS}
                else:
                    # Forks can inherit cumulative totals. Only attribute the last call.
                    usage = last
                previous = total
            else:
                # No cumulative counter means repeated status events cannot be deduplicated reliably.
                continue
            if usage is None:
                continue
            parts = split_usage(usage)
            if sum(parts.values()):
                events.append({'time': record.get('timestamp'), 'turn': turn,
                               'cwd': cwd, 'model': model, 'tier': tier,
                               'request_input': last['input_tokens'] if last else None, 'tokens': parts})
    for event in events:
        meta = turns.get(event['turn'], {})
        event.update(turn_number=meta.get('number'), turn_time=meta.get('time'),
                     summary=meta.get('request') or meta.get('reply') or '',
                     summary_source='request' if meta.get('request') else 'reply' if meta.get('reply') else None)
    return events


def events_for(path):
    version = stamp(path)
    with LOCK:
        cached = CACHE.get(str(path))
        if cached and cached[0] == version:
            return cached[1]
    result = scan(path)
    if version == stamp(path):
        with LOCK:
            CACHE[str(path)] = (version, result)
    return result


def empty():
    return dict.fromkeys(TYPES, 0)


def add(target, values):
    for key in TYPES:
        target[key] += values[key]


def report(rows, home, query, on_progress=None):
    scope = query.get('scope', ['all'])[0]
    scope_id = query.get('scope_id', [''])[0]
    if scope not in ('all', 'directory', 'session') or (scope == 'session' and not scope_id):
        raise ValueError('无效的统计范围')
    scope_thread = next((row for row in rows if row['id'] == scope_id), None) if scope == 'session' else None
    dimension = query.get('dimension', ['session'])[0]
    if dimension not in ('session', 'turn', 'directory'):
        raise ValueError('未知统计维度')
    try:
        zone = ZoneInfo(query.get('timezone', ['Asia/Singapore'])[0])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError('无法识别统计时区') from error
    selected = query.get('selected', [''])[0]
    day = query.get('day', [''])[0]
    if day:
        datetime.strptime(day, '%Y-%m-%d')
    groups, buckets, daily, models = {}, {}, {}, {}
    estimator = Estimator()
    pricing_metadata = estimator.metadata()
    selected_cost = empty_cost()
    bucket_costs = {}
    all_tokens, selected_tokens = empty(), empty()
    missing = 0
    undated = 0
    included, candidates = set(), []
    for thread in rows:
        if scope == 'session' and thread['id'] != scope_id:
            continue
        if thread['id'] in included:
            continue
        included.add(thread['id'])
        candidates.append(thread)
    for index, thread in enumerate(candidates):
        if on_progress:
            on_progress(index, len(candidates))
        path = resolve_rollout(thread['rollout_path']).resolve()
        if not path.is_relative_to(home.resolve()) or not path.is_file():
            missing += scope != 'directory' or (thread.get('cwd') or '') == scope_id
            continue
        try:
            events = events_for(path)
        except (OSError, ValueError, RuntimeError):
            missing += scope != 'directory' or (thread.get('cwd') or '') == scope_id
            continue
        if not events:
            missing += scope != 'directory' or (thread.get('cwd') or '') == scope_id
        for event in events:
            directory = event['cwd'] or thread.get('cwd') or ''
            if scope == 'directory' and directory != scope_id:
                continue
            turn = event['turn']
            key = {'session': thread['id'], 'directory': directory,
                   'turn': thread['id'] + '/' + (turn or 'unassigned')}[dimension]
            title = thread.get('name') or thread.get('title') or thread['id']
            label = directory or '未记录目录' if dimension == 'directory' else title
            group = groups.setdefault(key, {'id': key, 'label': label, 'thread_id': thread['id'],
                                           'turn_id': turn if dimension == 'turn' else None,
                                           'turn_number': event.get('turn_number') if dimension == 'turn' else None,
                                           'summary': event.get('summary', '') if dimension == 'turn' else '',
                                           'summary_source': event.get('summary_source') if dimension == 'turn' else None,
                                           'time': (event.get('turn_time') or event['time']) if dimension == 'turn' else event['time'], 'models': [], 'tokens': empty(), 'cost': empty_cost()})
            model = event.get('model')
            if dimension == 'turn' and isinstance(model, str) and model and model not in group['models']:
                group['models'].append(model)
            amount, reason = estimator.calculate(event)
            event_total = sum(event['tokens'].values())
            add_cost(group['cost'], amount, reason, event_total)
            add(group['tokens'], event['tokens'])
            add(all_tokens, event['tokens'])
            if selected and selected != key:
                continue
            try:
                local = datetime.fromisoformat(event['time'].replace('Z', '+00:00')).astimezone(zone)
            except (ValueError, AttributeError, TypeError):
                undated += event_total
                if day:
                    continue
                local = None
            else:
                date_key = local.strftime('%Y-%m-%d')
                daily_bucket = daily.setdefault(date_key, {'tokens': empty(), 'cost': empty_cost()})
                add(daily_bucket['tokens'], event['tokens'])
                add_cost(daily_bucket['cost'], amount, reason, event_total)
                if day and date_key != day:
                    continue
            add(selected_tokens, event['tokens'])
            add_cost(selected_cost, amount, reason, event_total)
            model_name = model if isinstance(model, str) and model.strip() else None
            if model_name not in models:
                models[model_name] = {'model': model_name, 'tokens': empty(), 'cost': empty_cost()}
            model_group = models[model_name]
            add(model_group['tokens'], event['tokens'])
            add_cost(model_group['cost'], amount, reason, event_total)
            if local is None:
                continue
            bucket_key = local.strftime('%H:00' if day else '%Y-%m-%d')
            add(buckets.setdefault(bucket_key, empty()), event['tokens'])
            add_cost(bucket_costs.setdefault(bucket_key, empty_cost()), amount, reason, event_total)
    if on_progress:
        on_progress(len(candidates), len(candidates))
    if day:
        keys = [f'{hour:02}:00' for hour in range(24)]
    elif buckets:
        first, last = sorted(buckets)[0], sorted(buckets)[-1]
        start = datetime.strptime(first, '%Y-%m-%d')
        count = (datetime.strptime(last, '%Y-%m-%d') - start).days
        keys = [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(count + 1)]
    else:
        keys = []
    for group in (*groups.values(), *models.values()):
        group['total'] = sum(group['tokens'].values())
        group['cost'] = cost_json(group['cost'], pricing_metadata)
    return {'scope': scope, 'scope_id': scope_id,
            'scope_label': (scope_thread.get('name') or scope_thread.get('title') or scope_id) if scope_thread else scope_id,
            'scope_directory': (scope_thread.get('cwd') or '') if scope_thread else scope_id if scope == 'directory' else '',
            'pricing': pricing_metadata, 'cost': cost_json(selected_cost, pricing_metadata), 'dimension': dimension, 'timezone': str(zone), 'day': day, 'selected': selected,
            'tokens': selected_tokens, 'total': sum(selected_tokens.values()),
            'all_total': sum(all_tokens.values()), 'missing_sessions': missing, 'undated_tokens': undated,
            'calendar_today': datetime.now(zone).strftime('%Y-%m-%d'),
            'daily': [{'label': key, 'tokens': value['tokens'], 'total': sum(value['tokens'].values()),
                       'cost': cost_json(value['cost'], pricing_metadata)} for key, value in sorted(daily.items())],
            'models': sorted(models.values(), key=lambda group: group['total'], reverse=True),
            'groups': sorted(groups.values(), key=lambda group: group['total'], reverse=True),
            'buckets': [{'label': key, 'tokens': buckets.get(key, empty()),
                         'cost': cost_json(bucket_costs.get(key, empty_cost()), pricing_metadata),
                         'total': sum(buckets.get(key, {}).values())} for key in keys]}
