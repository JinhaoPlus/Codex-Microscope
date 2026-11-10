"""Classify recorded tools without running session code. Native evidence stays per operation."""
import json
import re
import shlex
import native_events
import tool_icons
from message_i18n import legacy, msg
from urllib.parse import unquote

# A deliberately limited JS lexer. Strings, comments, templates and regular
# expressions are opaque: their contents cannot introduce tool calls.
TOKEN = re.compile(r"""\s+|//[^\n]*|/\*[\s\S]*?(?:\*/|$)|"(?:\\[\s\S]|[^"\\])*(?:"|$)|'(?:\\[\s\S]|[^'\\])*(?:'|$)|`(?:\\[\s\S]|[^`\\])*(?:`|$)|/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\n\\\[])+/[a-z]*|[a-zA-Z_$][\w$]*|-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?|[\s\S]""")
IDENT = re.compile(r'[a-zA-Z_$][\w$]*$')
WRAPPERS = {'exec', 'functions.exec'}


def decode(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return None


def static_string(token):
    """Decode a JS string, never evaluate an interpolation or expression."""
    quote=token[0]
    if len(token)<2 or token[-1]!=quote:raise ValueError
    body=token[1:-1].replace('\r\n','\n').replace('\r','\n')
    escapes={'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f','v':'\v',
             '`':'`','$':'$','\\':'\\','"':'"',"'":"'",'\n':''}
    parts=[];pos=0
    while pos<len(body):
        char=body[pos]
        if char=='\\':
            pos+=1
            if pos>=len(body):raise ValueError
            char=body[pos];pos+=1
            if char in ('u','x'):
                if char=='u' and body[pos:pos+1]=='{':
                    end=body.find('}',pos+1)
                    digits=body[pos+1:end] if end>=0 else ''
                    if not re.fullmatch(r'[0-9a-fA-F]{1,6}',digits):raise ValueError
                    pos=end+1
                else:
                    length=4 if char=='u' else 2
                    digits=body[pos:pos+length]
                    if len(digits)!=length or not re.fullmatch(r'[0-9a-fA-F]+',digits):raise ValueError
                    pos+=length
                point=int(digits,16)
                if point>0x10ffff:raise ValueError
                parts.append(chr(point))
            elif char=='0' and not body[pos:pos+1].isdigit():parts.append('\0')
            elif char in escapes:parts.append(escapes[char])
            else:raise ValueError
        else:
            if char==quote or (quote!='`' and char=='\n') or (quote=='`' and body[pos:pos+2]=='${'):raise ValueError
            parts.append(char);pos+=1
    # Python strings must not retain isolated UTF-16 surrogates in API output.
    return ''.join(parts).encode('utf-16-le','surrogatepass').decode('utf-16-le')


def expression_end(tokens,start,stops):
    """Find a top-level delimiter; opaque string/regex tokens are never inspected."""
    stack=[];pairs={'(':')','[':']','{':'}'}
    for pos in range(start,len(tokens)):
        token=tokens[pos]
        if not stack and token in stops:return pos
        if token in pairs:stack.append(pairs[token])
        elif token in (')',']','}'):
            if not stack or stack.pop()!=token:raise ValueError
    raise ValueError


class PartialArguments(dict):
    def __init__(self,known,unknown):
        super().__init__(known)
        self.unknown=unknown


def partial_arguments(tokens,start):
    """Keep independent literal fields, but never guess through spreads/overrides."""
    if tokens[start]!='{':raise ValueError
    known={};unknown=[];seen=set();pos=start+1
    while tokens[pos]!='}':
        key=tokens[pos]
        if not IDENT.fullmatch(key):key,_=literal(tokens,pos)
        if not isinstance(key,str) or key in seen or tokens[pos+1]!=':':raise ValueError
        seen.add(key);pos+=2
        end=expression_end(tokens,pos,{',','}'})
        if end==pos:raise ValueError
        try:
            value,after=literal(tokens,pos)
            if after!=end:raise ValueError
            known[key]=value
        except (ValueError,IndexError,RecursionError):unknown.append(key)
        pos=end
        if tokens[pos]==',':pos+=1
    return PartialArguments(known,unknown),pos+1


def literal(tokens, pos, depth=0):
    if depth > 32:
        raise ValueError
    token = tokens[pos]
    if token in ('{', '['):
        obj = {} if token == '{' else []
        end = '}' if token == '{' else ']'
        pos += 1
        while tokens[pos] != end:
            if isinstance(obj, dict):
                key = tokens[pos]
                if not IDENT.fullmatch(key):
                    key, _ = literal(tokens, pos, depth+1)
                if not isinstance(key, str) or key in obj or tokens[pos+1] != ':':
                    raise ValueError
                obj[key], pos = literal(tokens, pos+2, depth+1)
            else:
                value, pos = literal(tokens, pos, depth+1)
                obj.append(value)
            if tokens[pos] == end:
                break
            if tokens[pos] != ',':
                raise ValueError
            pos += 1
        return obj, pos+1
    if token.startswith(('`', '"', "'")):
        return static_string(token),pos+1
    return json.loads(token), pos+1


def script_calls(source):
    tokens = [m.group() for m in TOKEN.finditer(source)
              if not m.group().isspace() and not m.group().startswith(('//', '/*'))]
    calls = []
    for pos, token in enumerate(tokens):
        if token != 'tools' or pos and tokens[pos-1] == '.':
            continue
        if tokens[pos+1:pos+2] == ['[']:
            try:
                name, end = literal(tokens, pos+2)
                if not isinstance(name, str) or tokens[end:end+2] != [']', '(']:
                    raise ValueError
                start = end+2
            except (ValueError, IndexError, RecursionError):
                calls.append((None, None))
                continue
        elif tokens[pos+1:pos+2] == ['.'] and tokens[pos+3:pos+4] == ['('] and IDENT.fullmatch(tokens[pos+2]):
            name, start = tokens[pos+2], pos+4
        else:
            continue
        try:
            args, end = literal(tokens, start)
            if tokens[end] != ')':
                raise ValueError
        except (ValueError, IndexError, RecursionError):
            args = None
            if name=='exec_command':
                try:
                    args,end=partial_arguments(tokens,start)
                    if tokens[end]!=')':raise ValueError
                except (ValueError,IndexError,RecursionError):args=None
        calls.append((name, args))
    ts = tokens[:-1] if tokens[-1:] == [';'] else tokens
    prefix = ['await','Promise','.','allSettled','(','[']
    # Only expand a literal string array and a literal options object with
    # the callback's parameter in the cmd field. No JS execution.
    if ts[:8]==['text','(']+prefix and len(calls)==1 and calls[0][0]=='exec_command':
        try:
            cmds,end=literal(ts,7)
            start=end+5
            if (not isinstance(cmds,list) or not cmds or not all(isinstance(c,str) for c in cmds)
                or ts[end:start]!=['.','map','(','cmd','='] or
                ts[start:start+6]!=['>','tools','.','exec_command','(','{'] or
                ts[start+6]!='cmd' or ts[start+7] not in (',','}')):
                raise ValueError
            options,k=literal(ts[:start+6]+['cmd',':','null']+ts[start+7:],start+5)
            if ts[k-2:]!=[')',')',')',')']:
                raise ValueError
            return [('exec_command',dict(options,cmd=cmd)) for cmd in cmds]
        except (ValueError, IndexError, RecursionError):
            pass
    return calls


def identity(item):
    name = item.get('name', '')
    ns = item.get('namespace')
    if ns and not name.startswith(ns):
        return ns + ('__' if ns.startswith('mcp__') else '.') + name
    return name


def image_path(value):
    # Core ImageView stores a file URI; older/app-server records may store a path.
    if isinstance(value,str) and value.startswith('file:///'):
        path = unquote(value[7:])
        if re.match(r'^/[A-Za-z]:/', path):
            return path[1:].replace('/', chr(92))
        return path
    return value


def short_command(command):
    if not isinstance(command,str):return ''
    command=command.strip()
    return command if len(command)<=160 and '\n' not in command and '\r' not in command else ''


BUILTIN_ACTION_KEYS = {
    'clock__curr_time': 'tools.action.readTime',
    'image_gen__imagegen': 'tools.action.imageGen',
    'list_mcp_resources': 'tools.action.listResources',
    'list_mcp_resource_templates': 'tools.action.listResourceTemplates',
    'read_mcp_resource': 'tools.action.readResource',
    'get_goal': 'tools.action.getGoal',
    'create_goal': 'tools.action.createGoal',
    'update_goal': 'tools.action.updateGoal',
}
FILE_TOOL_KEYS = {
    'read_file': ('read', 'tools.action.readFile'),
    'readfile': ('read', 'tools.action.readFile'),
    'write_file': ('edit', 'tools.action.writeFile'),
    'edit_file': ('edit', 'tools.action.editFile'),
}
SESSION_ACTION_KEYS = {
    '': 'tools.action.sessionWait',
    '\x03': 'tools.action.sessionInterrupt',
}


def operation_summary(action_key, summary_params):
    clean = {k: v for k, v in summary_params.items() if not str(k).startswith('_')}
    text = legacy(action_key, **clean)
    for suffix_key in summary_params.get('_suffix_keys', ()):
        text += legacy(suffix_key, **summary_params)
    return text.strip()[:250]


def operation_fields(kind, action_key, summary_params):
    clean = {k: v for k, v in summary_params.items() if not str(k).startswith('_')}
    return dict(
        kind=kind,
        action_key=action_key,
        summary_key=action_key,
        summary_params=dict(summary_params),
        action=legacy(action_key, **clean),
        summary=operation_summary(action_key, summary_params),
    )


def operation_message(op):
    """Keep UI semantics separate from raw subjects and legacy Chinese labels."""
    key = op.get('summary_key') or op.get('action_key')
    if not key:
        return op.get('summary', '')
    params = op.get('summary_params') or {}
    clean = {k: v for k, v in params.items() if not str(k).startswith('_')}
    base = msg(key, **clean)
    subject = clean.get('detail') or clean.get('filename') or clean.get('path') or clean.get('cmd') or ''
    if clean.get('status_key'):
        subject = msg(clean['status_key'])
    elif isinstance(subject, str):
        subject = subject.strip()
    parts = [base]
    if subject and key != 'tools.action.agentToolFallback':
        parts.append(subject)
    parts.extend(msg(suffix, **clean) for suffix in params.get('_suffix_keys', ()))
    return {'join': parts, 'separator': ' '}


def classify(tool, args):
    fields = args if isinstance(args, dict) else {}
    if tool in ('exec_command', 'functions.exec_command'):
        cmd = fields.get('cmd') or fields.get('command') or ''
        brief = short_command(cmd)
        detail = (' ' + brief) if brief else ''
        return 'run', 'tools.action.runCommand', {'detail': detail, 'cmd': brief}
    if tool in ('write_stdin', 'functions.write_stdin'):
        chars = fields.get('chars', '') if isinstance(args, dict) else None
        action_key = 'tools.action.sessionInteract'
        if isinstance(chars, str):
            action_key = SESSION_ACTION_KEYS.get(chars, 'tools.action.sessionInput')
        summary_params = {}
        if fields.get('session_id') is not None:
            summary_params['sessionId'] = fields['session_id']
            summary_params['_suffix_keys'] = ('tools.action.sessionSuffix',)
        return 'session', action_key, summary_params
    if tool in ('view_image', 'functions.view_image'):
        path = fields.get('path')
        filename = re.split(r'[/\\]', path)[-1] if isinstance(path, str) else ''
        clean = re.sub(r'[\r\n\t]', ' ', filename)
        return 'image', 'tools.action.viewImage', {'filename': clean}
    if tool in BUILTIN_ACTION_KEYS:
        return 'other', BUILTIN_ACTION_KEYS[tool], {}
    if tool in ('web__run', 'web.run', 'mcp__codex_apps__search_service_web_run'):
        queries = fields.get('search_query')
        if isinstance(queries, list):
            return 'web', 'tools.action.webSearch', {
                'count': len(queries),
                '_suffix_keys': ('tools.action.webSearchQueries',),
            }
        return 'web', 'tools.action.webTool', {'detail': '、'.join(k for k in fields if k != 'response_length')}
    if tool in ('apply_patch', 'functions.apply_patch', 'fileChange'):
        return 'edit', 'tools.action.editFile', {}
    if (tool or '').startswith(('mcp__cua_repl.', 'mcp__cua_repl__')):
        detail = fields.get('title') or fields.get('completion_summary') or ''
        return 'browser', 'tools.action.computer', {'title': detail, 'detail': detail}
    if tool in FILE_TOOL_KEYS:
        kind, action_key = FILE_TOOL_KEYS[tool]
        detail = fields.get('path') or fields.get('file_path') or ''
        return kind, action_key, {'path': detail, 'detail': detail}
    if (tool or '').removeprefix('collaboration.') in ('spawn_agent', 'wait_agent', 'send_message', 'list_agents', 'followup_task', 'interrupt_agent'):
        return 'agent', 'tools.action.agentTool', {'tool': tool, 'detail': tool}
    if (tool or '').startswith('mcp__'):
        service, _, name = tool[5:].partition('__')
        detail = service + (' · ' + name if name else '')
        title = fields.get('title')
        if isinstance(title, str) and title.strip():
            detail = (detail + ' ' + title.strip()).strip()
        return 'other', 'tools.action.dynamicTool', {'identity': detail, 'detail': detail}
    return 'other', 'tools.action.unknownType', {'detail': tool or ''}


def operation(tool, args, evidence):
    kind, action_key, summary_params = classify(tool, args)
    op = dict(tool=tool, arguments=dict(args) if isinstance(args, PartialArguments) else args, evidence=[evidence],
              **operation_fields(kind, action_key, summary_params))
    if isinstance(args, PartialArguments) and args.unknown:
        op['unknown_arguments'] = list(args.unknown)
    return op


def is_quiet_poll(op, result):
    """A poll can have no new text whether the process exited or is still running."""
    args=op.get('arguments')
    if op.get('kind')!='session' or not isinstance(args,dict) or args.get('chars','')!='':
        return False
    if isinstance(result,str):
        result=decode(result)
    return isinstance(result,dict) and result.get('output')==''


def source_operations(item):
    name = identity(item)
    raw = item.get('text') or ''
    legacy = decode(raw) if name in WRAPPERS and raw.lstrip().startswith('{') else None
    if isinstance(legacy, dict) and isinstance(legacy.get('cmd'), str):
        return [operation('exec_command', legacy, 'direct')]
    if name in WRAPPERS:
        return [dict(operation(tool, args, 'script'), sourceIndex=index)
                for index,(tool,args) in enumerate(script_calls(raw))]
    args = decode(raw)
    op = operation(name, raw if args is None else args, 'direct')
    if op['kind'] in ('run', 'session') and isinstance(item.get('output'), str):
        old = re.fullmatch(
            r'(?:Chunk ID: ([0-9a-fA-F]+)\r?\n)?Wall time: ([0-9]+(?:\.[0-9]+)?) seconds\r?\n'
            r'(?:Process exited with code (-?\d+)\r?\n)?(?:Process running with session ID (\d+)\r?\n)?'
            r'(?:Original token count: (\d+)\r?\n)?Output:\r?\n([\s\S]*)',item['output'])
        if old and (old[3] is not None or old[4] is not None):
            result=dict(wall_time_seconds=float(old[2]),output=old[6])
            if old[1] is not None:
                result['chunk_id']=old[1]
            for key,group in [('exit_code',3),('session_id',4),('original_token_count',5)]:
                if old[group] is not None:
                    result[key]=int(old[group])
            op['returned']=result
        if is_quiet_poll(op, op.get('returned', item['output'])):
            suffix = tuple(op['summary_params'].get('_suffix_keys', ())) + ('tools.action.noNewOutput',)
            op['summary_params']['_suffix_keys'] = suffix
            op['summary'] = operation_summary(op['action_key'], op['summary_params'])
    return [op]


def web_match(args, event):
    if not isinstance(args, dict):
        return False
    action = event.get('action')
    if not isinstance(action, dict):
        return False
    def values(key, field):
        rows = args.get(key)
        return [r.get(field) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if action.get('type') == 'search':
        queries = action.get('queries') or [action.get('query') or event.get('query')]
        return bool(queries) and all(isinstance(q,str) and q for q in queries) and queries == values('search_query', 'q')
    if action.get('type') == 'openPage':
        return bool(action.get('url')) and action['url'] in values('open', 'ref_id')
    if action.get('type') == 'findInPage' and isinstance(args.get('find'),list):
        return bool(action.get('pattern')) and any(isinstance(row,dict) and row.get('pattern')==action['pattern'] and (not action.get('url') or row.get('ref_id')==action['url']) for row in args['find'])
    return False


def event_matches(op, event):
    if event.get('type') in ('imageView','ImageView'):
        args = op.get('arguments')
        return op['kind']=='image' and isinstance(args, dict) and isinstance(event.get('path'), str) and args.get('path')==image_path(event['path'])
    family=native_events.family(event)
    if family=='web':
        return op['kind']=='web' and web_match(op['arguments'], event)
    if family:
        args=op.get('arguments')
        if not native_events.same_direct_kind(op.get('tool'),event):
            return False
        if family=='generation':
            return event.get('matched_return_image') is True
        if family=='dynamic':
            return args is not None and args==event.get('arguments')
        if family=='sleep':
            return isinstance(args,dict) and args.get('duration_ms') is not None and args['duration_ms']==event.get('durationMs')
        # Generated prompts may be revised. A matching tool name or nearby
        # request alone is insufficient to attach a generation or agent activity.
        return False
    tool = 'mcp__'+str(event.get('server'))+'__'+str(event.get('tool'))
    return (op['tool'] or '').replace('.', '__') == tool and op['arguments'] == event.get('arguments')


WEB_NATIVE_KEYS = {
    'search': 'tools.action.webSearch',
    'openPage': 'tools.action.openPage',
    'findInPage': 'tools.action.findInPage',
}
GENERATION_STATUS_KEYS = {
    'completed': 'tools.action.status.completed',
    'failed': 'tools.action.status.failed',
    'inProgress': 'tools.action.status.inProgress',
}


def event_operation(event):
    if event.get('type') in ('imageView', 'ImageView'):
        return operation('view_image', {'path': image_path(event.get('path'))}, 'native')
    if event.get('type') == 'McpToolCall':
        op = operation('mcp__' + str(event.get('server')) + '__' + str(event.get('tool')), event.get('arguments'), 'native')
        result = event.get('result')
        suffix = ()
        if event.get('error') is not None or event.get('status') == 'failed' or (isinstance(result, dict) and result.get('isError') is True):
            suffix = ('tools.action.failedSuffix',)
        elif event.get('status') in ('inProgress', 'in_progress'):
            suffix = ('tools.action.wasRunningSuffix',)
        if suffix:
            op['summary_params']['_suffix_keys'] = tuple(op['summary_params'].get('_suffix_keys', ())) + suffix
            op['summary'] = operation_summary(op['action_key'], op['summary_params'])
        return op
    family = native_events.family(event)
    summary_params = {}
    if family == 'web':
        args = event.get('action') if isinstance(event.get('action'), dict) else {}
        action_key = WEB_NATIVE_KEYS.get(args.get('type'), 'tools.action.webOp')
        subject = args.get('pattern') or args.get('url') or args.get('query') or event.get('query')
        if not subject and isinstance(args.get('queries'), list):
            subject = ' · '.join(q for q in args['queries'] if isinstance(q, str))
        tool, kind = 'web__run', 'web'
        summary_params['detail'] = subject or ''
    elif family == 'dynamic':
        tool = native_events.dynamic_name(event)
        args = event.get('arguments')
        kind = 'other'
        action_key = 'tools.action.dynamicTool'
        identity = tool.replace('__', ' · ') if tool else ''
        summary_params['identity'] = identity
        summary_params['detail'] = identity
        if event.get('success') is False or event.get('status') == 'failed':
            summary_params['_suffix_keys'] = ('tools.action.failedSuffix',)
    elif family == 'sleep':
        tool, args, kind = 'clock.sleep', {}, 'other'
        action_key = 'tools.action.waitClock'
        duration = event.get('durationMs')
        summary_params['detail'] = f'{duration} ms' if duration is not None else ''
    elif family == 'generation':
        tool, args, kind = 'image_gen__imagegen', {}, 'image'
        action_key = 'tools.action.generateImage'
        status = event.get('status')
        status_key = GENERATION_STATUS_KEYS.get(status)
        if status_key:
            summary_params['detail'] = legacy(status_key)
            summary_params['status_key'] = status_key
    elif family == 'agent_activity':
        tool, args, kind = 'SubAgentActivity', {}, 'agent'
        kind_key = event.get('kind')
        action_key = native_events.AGENT_LABEL_KEYS.get(kind_key, 'tools.action.agentActivity')
        subject = event.get('agentPath') or event.get('agentThreadId')
        summary_params['detail'] = (' ' + str(subject)) if subject else ''
    else:
        tool = native_events.COLLAB_ACTIONS.get(event.get('tool'), event.get('tool'))
        kind, args = 'agent', {}
        action_key = native_events.TOOL_LABEL_KEYS.get(tool, 'tools.action.agentToolFallback')
        if action_key == 'tools.action.agentToolFallback':
            summary_params['tool'] = str(tool or '')
        targets = event.get('receiverThreadIds')
        if isinstance(targets, list):
            summary_params['count'] = len(targets)
            summary_params['_suffix_keys'] = ('tools.action.targetsCount',)
    op = operation(tool, args, 'native')
    if family:
        op.update(**operation_fields(kind, action_key, summary_params))
    return op


def operations(item):
    standalone = item.get('standalone_native')
    ops = [] if standalone else source_operations(item)
    for event in item.get('tool_events', []):
        matches = [o for o in ops if 'native' not in o['evidence'] and event_matches(o,event)]
        native = event_operation(event)
        if item.get('call_id') and item['call_id'] in (event.get('id'),event.get('call_id'),event.get('callId')):
            direct = [o for o in ops if 'direct' in o['evidence'] and (
                native_events.same_direct_kind(o['tool'],event) or
                (event.get('type') in ('ImageView','imageView') and o['kind']=='image'))]
            if len(direct)==1:
                matches = direct
        if len(matches) == 1 and 'event' not in matches[0]:
            op = matches[0]
            if op['kind']=='image':
                args = op.get('arguments')
                op['arguments'] = {**(args if isinstance(args,dict) else {}), **native['arguments']}
            op['evidence'].append('native')
            op.update(
                action=native['action'],
                summary=native['summary'],
                kind=native['kind'],
                action_key=native.get('action_key'),
                summary_key=native.get('summary_key'),
                summary_params=native.get('summary_params'),
            )
        else:
            op = native
            ops.append(op)
        op['event'] = event

    merged = list(ops)
    for index, result in enumerate(item.get('native_results', [])):
        cmd = ' '.join((result.get('command') or '').split()).strip()
        params = {'detail': cmd[:250], 'command': cmd[:250]}
        merged.append(dict(
            operation(None, None, 'native'),
            kind='run',
            action_key='tools.action.execResult',
            summary_key='tools.action.execResult',
            summary_params=params,
            action=legacy('tools.action.execResult'),
            summary=operation_summary('tools.action.execResult', params),
            resultRef=index,
        ))
    for op in merged:
        if op['kind'] != 'run' or 'native' in op['evidence']:
            continue
        args = op.get('arguments')
        cmd = args.get('cmd') if isinstance(args, dict) else None
        if not isinstance(cmd,str) or not cmd.startswith(('rg ', 'grep ')) or re.search(r'[;&|<>$`\n]',cmd):
            continue
        try:
            words = shlex.split(cmd)
        except ValueError:
            continue
        words = words[1:]
        while words and words[0] in ('-n','--line-number','-i','--ignore-case','-S','--smart-case','-F'):
            words.pop(0)
        if len(words)==2 and all(w and not w.startswith('-') for w in words):
            params = {'query': words[0], 'path': words[1], 'detail': words[0] + ' · ' + words[1]}
            op.update(
                kind='search',
                search=dict(type='search', cmd=cmd, query=words[0], path=words[1]),
                action_key='tools.action.searchContent',
                summary_key='tools.action.searchContent',
                summary_params=params,
                action=legacy('tools.action.searchContent'),
                summary=operation_summary('tools.action.searchContent', {**params, 'detail': params['detail'][:250]}),
            )
    if not merged and identity(item) in WRAPPERS:
        orch = operation_fields('other', 'tools.action.orchestration', {})
        return [dict(operation(None, None, 'script'), **orch)]
    return merged or [operation(None, None, 'script')]


def summaries(ops):
    keys = ('tool', 'kind', 'action', 'action_key', 'summary', 'summary_key', 'summary_params',
            'summary_message', 'action_message', 'resultRef', 'sourceIndex', 'evidence', 'icon')
    return [{k: op[k] for k in keys if k in op} for op in ops]


def describe(item):
    """Add the shared view model to a complete record, before pagination."""
    ops = operations(item)
    for op in ops:
        op['icon']=tool_icons.operation(op)
        op['summary_message'] = operation_message(op)
        op['action_message'] = msg(op['action_key'], **(op.get('summary_params') or {})) if op.get('action_key') else op.get('action', '')
        if item.get('name_key') and op.get('tool') == item.get('name'):
            op['summary_message'] = op['action_message'] = msg(item['name_key'])
    tool = identity(item)
    wrapped = tool in WRAPPERS and not any('direct' in op['evidence'] for op in ops)
    item.update(operations=ops, envelope={'tool': tool, 'script': wrapped})
    return item
