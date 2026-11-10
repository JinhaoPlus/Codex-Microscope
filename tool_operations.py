"""Classify recorded tools without running session code. Native evidence stays per operation."""
import json
import re
import shlex
import native_events
import tool_icons
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


def classify(tool, args):
    fields = args if isinstance(args, dict) else {}
    if tool in ('exec_command', 'functions.exec_command'):
        cmd = fields.get('cmd') or fields.get('command') or ''
        return 'run', '运行命令', short_command(cmd)
    if tool in ('write_stdin', 'functions.write_stdin'):
        # Codex TUI UnifiedExecInteractionCell distinguishes empty stdin from input.
        chars = fields.get('chars', '') if isinstance(args, dict) else None
        action = '后台终端交互'
        if isinstance(chars,str):
            action = {'':'等待后台终端','\x03':'请求中断后台终端'}.get(chars,'向后台终端输入')
        return 'session', action, f"· 会话 {fields['session_id']}" if fields.get('session_id') is not None else ''
    if tool in ('view_image', 'functions.view_image'):
        path = fields.get('path')
        filename = re.split(r'[/\\]', path)[-1] if isinstance(path, str) else ''
        return 'image', '查看图片', re.sub(r'[\r\n\t]', ' ', filename)
    builtin_labels = {'clock__curr_time':'读取时间', 'image_gen__imagegen':'生成或编辑图片',
                      'list_mcp_resources':'列出资源', 'list_mcp_resource_templates':'列出资源模板',
                      'read_mcp_resource':'读取资源', 'get_goal':'查看目标',
                      'create_goal':'创建目标', 'update_goal':'更新目标'}
    if tool in builtin_labels:
        return 'other', builtin_labels[tool], ''
    if tool in ('web__run', 'web.run', 'mcp__codex_apps__search_service_web_run'):
        queries = fields.get('search_query')
        if isinstance(queries, list):
            return 'web', '网页搜索', f'{len(queries)} 条查询'
        return 'web', '网页工具', '、'.join(k for k in fields if k != 'response_length')
    if tool in ('apply_patch', 'functions.apply_patch', 'fileChange'):
        return 'edit', '修改文件', ''
    if (tool or '').startswith(('mcp__cua_repl.', 'mcp__cua_repl__')):
        return 'browser', '电脑操作', fields.get('title') or fields.get('completion_summary') or ''
    file_tools = {'read_file': ('read','读取文件'), 'readfile': ('read','读取文件'),
                  'write_file': ('edit','写入文件'), 'edit_file': ('edit','修改文件')}
    if tool in file_tools:
        kind, label = file_tools[tool]
        return kind, label, fields.get('path') or fields.get('file_path') or ''
    if (tool or '').removeprefix('collaboration.') in ('spawn_agent', 'wait_agent', 'send_message', 'list_agents', 'followup_task', 'interrupt_agent'):
        return 'agent', '子代理工具', tool
    if (tool or '').startswith('mcp__'):
        service, _, name = tool[5:].partition('__')
        identity_label = service + (' · ' + name if name else '')
        title = fields.get('title')
        return 'other', identity_label, title.strip() if isinstance(title,str) else ''
    return 'other', tool or '工具类型未确认', ''


def operation(tool, args, evidence):
    kind, action, detail = classify(tool, args)
    op=dict(tool=tool, kind=kind, action=action, summary=(action+' '+str(detail)).strip()[:250],
            arguments=dict(args) if isinstance(args,PartialArguments) else args, evidence=[evidence])
    if isinstance(args,PartialArguments) and args.unknown:op['unknown_arguments']=list(args.unknown)
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
        if is_quiet_poll(op,op.get('returned',item['output'])):
            op['summary']+=' · 无新增输出'
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


def event_operation(event):
    if event.get('type') in ('imageView','ImageView'):
        return operation('view_image', {'path':image_path(event.get('path'))}, 'native')
    if event.get('type') == 'McpToolCall':
        op=operation('mcp__'+str(event.get('server'))+'__'+str(event.get('tool')),event.get('arguments'),'native')
        result=event.get('result')
        if event.get('error') is not None or event.get('status')=='failed' or (isinstance(result,dict) and result.get('isError') is True):
            op['summary']+=' · 失败'
        elif event.get('status') in ('inProgress','in_progress'):
            op['summary']+=' · 上次记录时仍在运行'
        return op
    family=native_events.family(event)
    if family=='web':
        args=event.get('action') if isinstance(event.get('action'),dict) else {}
        label={'search':'网页搜索','openPage':'打开网页','findInPage':'页内查找'}.get(args.get('type'),'网页操作')
        subject=args.get('pattern') or args.get('url') or args.get('query') or event.get('query')
        if not subject and isinstance(args.get('queries'),list):
            subject=' · '.join(q for q in args['queries'] if isinstance(q,str))
        tool,kind='web__run','web'
    elif family=='dynamic':
        tool=native_events.dynamic_name(event)
        args,kind=event.get('arguments'),'other'
        label=tool.replace('__',' · ') or '动态工具'
        subject='失败' if event.get('success') is False or event.get('status')=='failed' else ''
    elif family=='sleep':
        tool,kind,label,args='clock.sleep','other','等待时钟',{}
        duration=event.get('durationMs')
        subject=f'{duration} ms' if duration is not None else ''
    elif family=='generation':
        tool,kind,label,args='image_gen__imagegen','image','生成图片',{}
        subject={'completed':'已完成','failed':'失败','inProgress':'处理中'}.get(event.get('status'),'')
    elif family=='agent_activity':
        tool,kind,args='SubAgentActivity','agent',{}
        label=native_events.AGENT_LABELS.get(event.get('kind'),'子任务活动')
        subject=event.get('agentPath') or event.get('agentThreadId')
    else:
        tool=native_events.COLLAB_ACTIONS.get(event.get('tool'),event.get('tool'))
        kind,args='agent',{}
        label=native_events.TOOL_LABELS.get(tool,'代理工具 '+str(tool or ''))
        targets=event.get('receiverThreadIds')
        subject=f'{len(targets)} 个目标' if isinstance(targets,list) else ''
    op=operation(tool,args,'native')
    op.update(kind=kind,action=label,summary=(label+' '+str(subject or '')).strip()[:250])
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
            op.update(action=native['action'], summary=native['summary'],kind=native['kind'])
        else:
            op = native
            ops.append(op)
        op['event'] = event

    merged = list(ops)
    for index, result in enumerate(item.get('native_results', [])):
        merged.append(dict(operation(None,None,'native'),kind='run',action='执行结果',
                           summary=('执行结果 '+' '.join((result.get('command') or '').split())).strip()[:250],resultRef=index))
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
            op.update(kind='search', search=dict(type='search',cmd=cmd,query=words[0],path=words[1]), action='搜索内容', summary=('搜索内容 '+words[0]+' · '+words[1])[:250])
    if not merged and identity(item) in WRAPPERS:
        return [dict(operation(None, None, 'script'), action='编排脚本', summary='编排脚本')]
    return merged or [operation(None, None, 'script')]


def summaries(ops):
    keys = ('tool','kind','action','summary','resultRef','sourceIndex','evidence','icon')
    return [{k:op[k] for k in keys if k in op} for op in ops]


def describe(item):
    """Add the shared view model to a complete record, before pagination."""
    ops = operations(item)
    for op in ops:
        op['icon']=tool_icons.operation(op)
    tool = identity(item)
    wrapped = tool in WRAPPERS and not any('direct' in op['evidence'] for op in ops)
    item.update(operations=ops, envelope={'tool': tool, 'script': wrapped})
    return item
