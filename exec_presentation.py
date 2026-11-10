"""Read-only presentation of code-mode calls. Never evaluate recorded JavaScript."""
import json
import re
import shlex

import tool_operations as tools
import tool_icons
from message_i18n import legacy, msg


WAIT = {'wait', 'functions.wait'}
HEADER = re.compile(r'^Script (completed|failed|terminated|running with cell ID ([\w.-]+))\r?\nWall time [^\n]*\r?\nOutput:\r?\n?')
LABEL_KEYS = {'read': 'tools.exec.label.read', 'search': 'tools.exec.label.search',
              'list_files': 'tools.exec.label.list', 'edit': 'tools.exec.label.edit'}
EXEC_STATUS_STATE = {
    'completed_image': 'tools.exec.state.imageReturned',
    'completed_text': 'tools.exec.state.resultReturned',
    'terminated': 'tools.exec.state.terminated',
    'failed': 'tools.exec.state.failed',
    'aborted': 'tools.exec.state.aborted',
    'wait_interrupted': 'tools.exec.state.waitInterrupted',
    'pending': 'tools.exec.state.pending',
    'retrieve_failed': 'tools.exec.state.retrieveFailed',
}
WAIT_STATE_KEYS = {'completed': 'tools.exec.waitCompleted', 'aborted': 'tools.exec.waitUserAbort'}
ROW_STATE_KEYS = {'running': 'tools.exec.state.pending', 'failed': 'tools.exec.state.failed',
                  'terminated': 'tools.exec.state.terminated', 'aborted': 'tools.exec.state.aborted',
                  'no_result': 'tools.exec.noResult'}


def label_presentation(key, **params):
    text = legacy(key, **params)
    message = msg(key, **params)
    # Action keys are intentionally short labels; their raw subject is separate.
    if key in ('tools.exec.label.read', 'tools.exec.label.edit', 'tools.exec.verb.add',
               'tools.exec.verb.delete', 'tools.exec.label.search', 'tools.action.runCommand'):
        subject = params.get('path') or params.get('detail') or params.get('cmd')
        if subject:
            message = {'join': [message, subject.strip() if isinstance(subject, str) else subject], 'separator': ' '}
    return {'label_key': key, 'label_params': params, 'label': text[:250], 'label_message': message}


def state_presentation(key):
    return {'state_key': key, 'state': legacy(key)}

def record_return(call, value):
    """Keep notification boundaries and media; the transcript owns the original bytes."""
    parts = value if isinstance(value, list) else [value]
    blocks = call.setdefault('output_blocks', [])
    call.setdefault('return_starts', []).append(len(blocks))
    for block in parts:
        if isinstance(block, dict) and block.get('type') in ('input_image','image'):
            blocks.append({'type':'image', 'image_url':block.get('image_url')})
        elif isinstance(block, dict) and block.get('type') in ('input_audio','audio'):
            url=block.get('audio_url')
            mime=re.match(r'^data:(audio/[a-z0-9.+-]+);',url,re.I) if isinstance(url,str) else None
            blocks.append({'type':'audio', 'mimeType':mime[1] if mime else None})
        elif isinstance(block, dict) and isinstance(block.get('text'), str):
            blocks.append(block['text'])
        else:
            blocks.append(block if isinstance(block,str) else json.dumps(block,ensure_ascii=False))

def return_info(item):
    blocks = item.get('output_blocks', [])
    headers = []
    starts=item.get('return_starts', [])
    for index,end in zip(starts,[*starts[1:],len(blocks)]):
        if index >= end or not isinstance(blocks[index],str):
            continue
        match = HEADER.match(blocks[index])
        if match:
            headers.append((index, match))
    return headers

def cell_status(head):
    """Only the first block of a tool return can carry a lifecycle marker."""
    if not isinstance(head,str):
        return '', None
    match=HEADER.match(head)
    if match:
        return ('running',match[2]) if match[2] else (match[1],None)
    if re.fullmatch(r'aborted by user(?: after [0-9]+(?:\.[0-9]+)?s)?',head.strip()):
        return 'aborted', None
    return '', None


def wait_cell(item):
    args=tools.decode(item.get('text',''))
    cell=args.get('cell_id') if isinstance(args,dict) else None
    if type(cell) not in (str,int) or cell=='':
        return None
    return str(cell)


def link_waits(items,session_boundaries=()):
    # An exec may yield only after another request was logged. Replay physical
    # record order within this rollout, never transcript display order.
    owners={}
    events=[(line,None,None,None) for line in session_boundaries]
    for item in items:
        name=tools.identity(item)
        if not item.get('exec_view') or name not in tools.WRAPPERS | WAIT:
            continue
        if name in WAIT:
            events.append((item['_raw_lines'][0],item,None,None))
        starts=item.get('return_starts',[])
        ends=[*starts[1:],len(item.get('output_blocks',[]))]
        for line,start,end in zip(item.get('_return_lines',[]),starts,ends):
            events.append((line,item,start,end))

    session_start=0
    for line,item,start,end in sorted(events,key=lambda event:event[0]):
        if item is None:
            owners.clear()
            session_start=line
            continue
        if item['_raw_lines'][0]<session_start:
            continue
        is_wait=tools.identity(item) in WAIT
        if start is None:
            candidates=owners.get(wait_cell(item),set())
            if len(candidates)==1:
                origin=items[next(iter(candidates))]
                item['cell_origin']=origin['index']
                origin['cell_waits'].append(item['index'])
            elif wait_cell(item) is not None:
                link_key = 'tools.exec.cellAmbiguous' if candidates else 'tools.exec.cellNoOrigin'
                item['cell_link_note'] = legacy(link_key)
                item['cell_link_note_key'] = link_key
                item['cell_link_message'] = msg(link_key)
            continue
        blocks=item['output_blocks']
        status,yielded_cell=cell_status(blocks[start] if start<end else None)
        if not status:
            continue
        if not is_wait:
            index=item['index']
            if status=='running':
                owners.setdefault(yielded_cell,set()).add(index)
                item['cell_id']=yielded_cell
                item.setdefault('cell_waits',[])
            else:
                candidates=owners.get(item.get('cell_id'),set())
                if index in candidates:
                    candidates.remove(index)
                    if status=='completed':
                        has_image=any(isinstance(b,dict) and b.get('type')=='image' for b in blocks[start:end])
                        state_key = EXEC_STATUS_STATE['completed_image' if has_image else 'completed_text']
                        item['exec_view'].update(state_presentation(state_key))
                    else:
                        item['exec_view'].update(state_presentation(EXEC_STATUS_STATE[status]))
            continue
        cell=wait_cell(item)
        index=item.get('cell_origin')
        if index is None or owners.get(cell)!={index}:
            continue
        origin=items[index]
        if status=='aborted':
            # A cancelled wait ends this request; the underlying cell can still
            # be polled later. No final return or process exit is established.
            origin['exec_view'].update(state_presentation(EXEC_STATUS_STATE['wait_interrupted']))
        elif status=='running':
            if yielded_cell==cell:
                origin['exec_view'].update(state_presentation(EXEC_STATUS_STATE['pending']))
        else:
            owners[cell].remove(index)
            origin['cell_final']=item['index']
            if status=='completed':
                image=any(isinstance(b,dict) and b.get('type')=='image' for b in blocks[start:end])
                state_key = EXEC_STATUS_STATE['completed_image' if image else 'completed_text']
                origin['exec_view'].update(state_presentation(state_key))
            else:
                key = EXEC_STATUS_STATE['terminated'] if status=='terminated' else EXEC_STATUS_STATE['retrieve_failed']
                origin['exec_view'].update(state_presentation(key))


def forwarding_shape(source, receipt=False):
    """Replace only complete tools.foo(literal) calls in a tiny allowlist grammar."""
    tokens = [m.group() for m in tools.TOKEN.finditer(source)
              if not m.group().isspace() and not m.group().startswith(('//','/*'))]
    if receipt:
        # Harmless, literal-only setup can precede an exact result emission.
        # This does not resolve variables in command arguments or run store().
        bindings=set()
        while tokens:
            try:
                if tokens[:1]==['const'] and tools.IDENT.fullmatch(tokens[1]) and tokens[2]=='=':
                    if tokens[1] in ('tools','text','store','JSON','Promise','image'):return ''
                    value,end=tools.literal(tokens,3)
                    if not isinstance(value,str) or tokens[end]!=';':break
                    if tokens[1] in bindings:return ''
                    bindings.add(tokens[1]);tokens=tokens[end+1:];continue
                if tokens[:2]==['store','(']:
                    key,end=tools.literal(tokens,2)
                    if (not isinstance(key,str) or tokens[end]!=',' or tokens[end+1] not in bindings
                            or tokens[end+2:end+4]!=[')',';']):break
                    tokens=tokens[end+4:];continue
            except (IndexError,ValueError,RecursionError,TypeError):return ''
            break
    shape = []
    i = 0
    while i < len(tokens):
        if tokens[i:i+2] == ['tools','.'] and tokens[i+3:i+4] == ['(']:
            try:
                if receipt:
                    end=tools.expression_end(tokens,i+4,{')',','})
                    if end==i+4 or 'tools' in tokens[i+4:end]:return ''
                else:_, end = tools.literal(tokens,i+4)
                if tokens[end] != ')':
                    return ''
            except (IndexError,ValueError,RecursionError,TypeError):
                return ''
            shape.append('@')
            i = end+1
        else:
            # Whitespace between tokens matters (e.g. const r vs constr).
            shape.append(tokens[i])
            i += 1
    return ' '.join(shape).removesuffix(' ;')

def forwarded_results(item, ops, headers, receipt=False):
    """Recognize exact forwarding shapes. All other outputs stay shared."""
    blocks = item.get('output_blocks', [])
    if len(headers)!=1 or len(item.get('return_starts',[]))!=1 or headers[0][1][1]!='completed':
        return {}
    shape = forwarding_shape(item['text'],receipt=receipt)
    if not shape or not ops:
        return {}
    start, match = headers[0]
    first = start if blocks[start][match.end():].strip() else start+1
    payload = blocks[first:]
    if first==start:
        payload = [blocks[start][match.end():], *blocks[start+1:]]
    if len(ops)==1 and len(payload)==1:
        direct = {'text ( await @ )','text ( JSON . stringify ( await @ ) )'}
        bound = re.fullmatch(r'const (\w+) = await @ ; text \( (?:JSON \. stringify \( \1 \)|\1) \)',shape)
        if shape in direct or bound:
            return {0:(first,payload[0])}
        if (shape=='text ( ( await @ ) . output )' or
                re.fullmatch(r'const (\w+) = await @ ; text \( \1 \. output \)',shape)):
            return {0:(first,{'output':payload[0],'output_only':True})}
        if ops[0].get('kind')=='image' and (shape=='image ( ( await @ ) . image_url )' or
                re.fullmatch(r'const (\w+) = await @ ; image \( \1 \. image_url \)',shape)):
            return {0:(first,payload[0])}
    return batch_forwarding(shape, ops, first, payload)


def process_key(value):
    if type(value) is int and value>=0:return str(value)
    if isinstance(value,str) and re.fullmatch(r'\d{1,12}',value):return str(int(value))
    return None


def process_receipts(item):
    """Only exec_command startup receipts with a proven returned-value origin."""
    ops=tools.source_operations(item)
    if tools.identity(item) in tools.WRAPPERS:
        mapped=forwarded_results(item,ops,return_info(item),receipt=True)
    elif len(ops)==1:
        mapped={0:(0,ops[0].get('returned',item.get('output')))}
    else:return []
    receipts=[]
    for pos,(_,value) in mapped.items():
        if ops[pos].get('tool') not in ('exec_command','functions.exec_command'):continue
        obj=tools.decode(value) if isinstance(value,str) else value
        if not isinstance(obj,dict) or obj.get('exit_code') is not None or not isinstance(obj.get('output'),str):continue
        key=process_key(obj.get('session_id'))
        if key is not None:receipts.append((pos,key))
    return receipts


def batch_forwarding(shape, ops, first, blocks):
    # Bind the exact Promise input list to an identifier. Only literal indexed
    # emissions, slices and complete-array emissions can claim result blocks.
    promise = r'await Promise \. (all|allSettled) \( \[ (@(?: , @)*)(?: ,)? \] \)'
    inline = re.fullmatch(r'text \( '+promise+r' \)',shape)
    bound = re.fullmatch(r'const (\w+) = ('+promise+r') ; (.+)',shape)
    if inline:
        method, calls = inline.groups()
        variable, emissions = 'batch', ['text ( batch )']
    elif bound:
        variable, _, method, calls, tail = bound.groups()
        emissions = tail.split(' ; ')
    else:
        return {}
    if calls.count('@')!=len(ops) or len(emissions)!=len(blocks):
        return {}
    name = re.escape(variable)
    mapped = {}
    for offset,(code,block) in enumerate(zip(emissions,blocks)):
        image = re.fullmatch(r'image \( '+name+r' \[ (\d{1,6}) \] \. image_url \)',code)
        if image:
            pos = int(image[1])
            if (method!='all' or pos>=len(ops) or ops[pos]['kind']!='image'
                    or not isinstance(block,dict) or block.get('type')!='image' or pos in mapped):
                return {}
            mapped[pos] = (first+offset,block)
            continue
        printed = re.fullmatch(r'text \( JSON \. stringify \( (.+) \) \)|text \( (.+) \)',code)
        if not printed or not isinstance(block,str):
            return {}
        expr = printed[1] or printed[2]
        selected = re.fullmatch(name+r' \[ (\d{1,6}) \]',expr)
        sliced = re.fullmatch(name+r' \. slice \( (\d{1,6}) , (\d{1,6}) \)',expr)
        values = tools.decode(block)
        if selected:
            indices = [int(selected[1])]
            values = [values if values is not None else block]
        elif sliced:
            indices = range(int(sliced[1]),min(len(ops),int(sliced[2])))
        elif expr==variable:
            indices = range(len(ops))
        else:
            return {}
        if not isinstance(values,list) or len(values)!=len(indices):
            return {}
        for pos,value in zip(indices,values):
            if pos>=len(ops) or pos in mapped:
                return {}
            if method=='allSettled':
                if not isinstance(value,dict) or value.get('status')!='fulfilled' or 'value' not in value:
                    return {}
                value = value['value']
            mapped[pos] = (first+offset,value)
    return mapped


def native_label(action):
    kind = action.get('type')
    if kind == 'edit':
        if action.get('old_path'):
            return label_presentation('tools.exec.verb.move', old=action['old_path'], new=action['path'])
        verb_key = {'add': 'tools.exec.verb.add', 'delete': 'tools.exec.verb.delete'}.get(action.get('change'), 'tools.exec.label.edit')
        path = action.get('path', legacy('tools.exec.defaultFile'))
        base = label_presentation(verb_key, path=path)
        if not action.get('path'):
            base['label_message'] = {'join': [msg(verb_key), msg('tools.exec.defaultFile')], 'separator': ' '}
        return base
    if kind == 'search':
        query = action.get('query') or action.get('cmd') or ''
        return label_presentation('tools.exec.searchPrefix', query=query)
    if kind == 'list_files':
        path = action.get('path') or legacy('tools.exec.defaultFile')
        base = label_presentation('tools.exec.listPrefix', path=path)
        if not action.get('path'):
            base['label_message'] = msg('tools.exec.listPrefix', path=msg('tools.exec.defaultFile'))
        if 'output_limit' in action:
            limit = legacy('tools.exec.listLimit', count=action['output_limit'])
            base['label'] = (base['label'] + ' ' + limit.strip())[:250]
            base['label_params'] = {**base['label_params'], 'count': action['output_limit']}
            base['label_key'] = 'tools.exec.listPrefix'
            base['list_limit_key'] = 'tools.exec.listLimit'
            base['label_message'] = {'join': [base['label_message'], msg('tools.exec.listLimit', count=action['output_limit'])], 'separator': ' '}
        return base
    suffix = action.get('path') or action.get('name') or action.get('cmd') or ''
    key = LABEL_KEYS.get(kind, 'tools.action.runCommand')
    if key == 'tools.exec.label.read':
        path = suffix or legacy('tools.exec.defaultFile')
        base = label_presentation(key, path=path)
        if not suffix:
            base['label_message'] = {'join': [msg(key), msg('tools.exec.defaultFile')], 'separator': ' '}
        return base
    detail = (' ' + suffix) if suffix else ''
    return label_presentation(key, path=suffix, cmd=suffix, detail=detail)


def native_label_text(action):
    return native_label(action)['label']


def shell_action(command):
    """Recognize literal file commands and the specific rg --files | head pipeline."""
    if not isinstance(command,str) or re.search(r'[;&<>$`\r\n\x00*?\[\]{}()#!~]', command):
        return None
    first,pipe,last=command.partition('|')
    try:
        words=shlex.split(first)
    except ValueError:
        return None
    if not words:
        return None
    program,*args=words
    if pipe:
        head=re.fullmatch(r'[ \t]*head(?:[ \t]+-n[ \t]+([0-9]{1,9}))?[ \t]*',last)
        if not head or words[:2]!=['rg','--files'] or len(words)>3:
            return None
        action={'type':'list_files','cmd':command,'output_limit':int(head[1] or 10)}
        if len(words)==3:
            directory=words[2]
            if not directory or directory.startswith('-'):
                return None
            action['path']=directory
        return action
    kind='read'
    if program in ('ls','rg','git'):
        kind='list_files'
        prefix={'ls':[], 'rg':['--files'], 'git':['ls-files']}[program]
        if args[:len(prefix)]!=prefix:
            return None
        args=args[len(prefix):]
    elif program=='sed':
        if len(args)<2 or args[0]!='-n' or not re.fullmatch(r'[1-9]\d*(?:,[1-9]\d*)?p',args[1]):
            return None
        args=args[2:]
    elif program in ('head','tail'):
        if args[:1]==['-n'] and len(args)>=2 and re.fullmatch(r'\+?\d+' if program=='tail' else r'\d+',args[1]):
            args=args[2:]
        elif args and re.fullmatch(r'-\d+|-n\d+',args[0]):
            args=args[1:]
    elif program=='nl':
        if args[:1]==['-ba']:
            args=args[1:]
    elif program!='cat':
        return None
    after_options=args[:1]==['--']
    if after_options:
        args=args[1:]
    if not args and kind=='list_files':
        return {'type':kind,'cmd':command}
    if len(args)!=1 or not args[0] or args[0]=='-' or (not after_options and args[0].startswith('-')):
        return None
    return {'type':kind,'cmd':command,'path':args[0]}

def describe_execution(item):
    if item['envelope']['script'] or tools.identity(item) in WAIT or item.get('native_results'):
        item['exec_view']=build_view(item)
        return
    # Older rollouts call exec_command directly rather than through the JS tool.
    for op in item['operations']:
        args=op.get('arguments')
        if op['kind']=='run' and 'direct' in op['evidence'] and isinstance(args,dict):
            action=shell_action(args.get('cmd'))
            if action:
                presented = native_label(action)
                label = presented['label']
                action_key = LABEL_KEYS[action['type']]
                summary = legacy('tools.exec.requestPrefix', label=label) if item.get('output') is None else label
                op.update(shell_action=action, icon=tool_icons.file_action(action), action_key=action_key,
                          action=legacy(action_key), summary=summary, summary_key=action_key,
                          label_key=presented.get('label_key'), label_params=presented.get('label_params'))
                op['summary_message'] = msg('tools.exec.requestPrefix', label=presented['label_message']) if item.get('output') is None else presented['label_message']
                op['action_message'] = msg(action_key)


def build_view(item):
    ops = item['operations']
    sources = [op for op in ops if op.get('resultRef') is None]
    headers = return_info(item)
    forwarded = forwarded_results(item,sources,headers) if item['envelope']['script'] else {}
    actions = item.get('native_actions',[])
    results = item.get('native_results',[])
    rows = []
    matches = {}
    for index, result in enumerate(results):
        group = [a for a in actions if a.get('result_index')==index]
        candidates = []
        bound=result.get('source_index')
        if isinstance(bound,int) and 0<=bound<len(sources):
            matches.setdefault(bound,[]).append(index)
            continue
        for pos, op in enumerate(sources):
            args = op.get('arguments')
            if result.get('command') and isinstance(args,dict) and args.get('cmd')==result['command']:
                candidates.append(pos)
            elif op.get('kind')=='edit' and isinstance(args,str) and group:
                paths = set(re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$',args,re.M))
                if all(a.get('path') in paths or a.get('old_path') in paths for a in group):
                    candidates.append(pos)
        if len(candidates)==1:
            matches.setdefault(candidates[0],[]).append(index)
    used = set()
    def append_native(index,source=None):
        ids = [j for j,a in enumerate(actions) if a.get('result_index')==index]
        labels = [native_label_text(actions[j]) for j in ids if actions[j]['type'] in LABEL_KEYS]
        label_keys = [native_label(actions[j]) for j in ids if actions[j]['type'] in LABEL_KEYS]
        result = results[index]
        patch=result.get('type')=='file_change'
        inferred = None if ids or patch or result.get('source')=='unified_exec_interaction' else shell_action(result.get('command'))
        if len(ids)==1 and actions[ids[0]]['type']=='list_files':
            # The native list action may omit the output-limiting stage from its cmd.
            original=shell_action(result.get('command'))
            if original and 'output_limit' in original:
                inferred={**original,**actions[ids[0]],'cmd':result['command']}
        command=result.get('command') or ''
        brief=tools.short_command(command)
        generic = legacy('tools.action.runCommand', detail=brief, cmd=brief)
        label = '、'.join(labels) or generic
        label_key = 'tools.action.runCommand'
        label_params = {'detail': brief, 'cmd': brief}
        label_message = {'join': [entry['label_message'] for entry in label_keys], 'separator_key': 'tools.activityGroupSep'} if label_keys else label_presentation(label_key, **label_params)['label_message']
        kind=actions[ids[0]]['type'] if ids else 'run'
        if inferred:
            presented = native_label(inferred)
            label, label_key, label_params = presented['label'], presented['label_key'], presented['label_params']
            label_message = presented['label_message']
            kind = inferred['type']
        elif patch and not ids:
            label, label_key, kind = legacy('tools.action.editFile'), 'tools.action.editFile', 'edit'
            label_message = msg(label_key)
        if result.get('status')=='failed' and (patch or any(actions[j]['type']=='edit' for j in ids)):
            label = legacy('tools.exec.tryWriteFail', label=label)
            label_key = 'tools.exec.tryWriteFail'
            label_params = {'label': label}
            label_message = msg(label_key, label=label_message)
        if result.get('source')=='unified_exec_interaction':
            label = legacy('tools.action.sessionInteract')
            label_key = 'tools.action.sessionInteract'
            kind='session'
            label_message = msg(label_key)
        elif result.get('source')=='user_shell':
            label = legacy('tools.exec.userRun', label=generic)
            label_key = 'tools.exec.userRun'
            label_params = {'label': generic}
            label_message = msg(label_key, label=label_presentation('tools.action.runCommand', detail=brief)['label_message'])
        row={'native':index,'actions':ids,'label':label[:250],'label_key':label_key,'label_params':label_params,'label_message':label_message,'kind':kind}
        if source and source.get('unknown_arguments'):row['unknown_arguments']=source['unknown_arguments']
        action_icons=[tool_icons.file_action(actions[j]) for j in ids]
        row['action_icons']=action_icons
        if result.get('source')=='unified_exec_interaction':
            row['icon']=tool_icons.terminal_input(result.get('interaction_input'))
        elif inferred:
            row['icon']=tool_icons.file_action(inferred)
        elif action_icons:
            row['icon']=tool_icons.combine(action_icons,'FileDiff' if patch else 'Layers')
        else:
            row['icon']='FileDiff' if patch else 'Terminal'
        if inferred:row['shell_action']=inferred
        rows.append(row)
        used.add(index)
    owned = set()
    for pos, op in enumerate(sources):
        if pos in matches and len(matches[pos])==1:
            append_native(matches[pos][0],sources[pos])
            # Only hide a forwarded result if it duplicates the native payload.
            if pos in forwarded:
                _, value = forwarded[pos]
                result = results[matches[pos][0]]
                obj = tools.decode(value) if isinstance(value,str) else value
                if (isinstance(obj,dict) and 'output' in obj and
                        all(result.get(k)==v for k,v in obj.items())):
                    owned.add(pos)
            continue
        if not op.get('tool') and 'sourceIndex' not in op and results:
            continue
        row = {'op':pos,'label':op['summary'],'label_message':op.get('summary_message') or tools.operation_message(op),'kind':op['kind'],'icon':op.get('icon') or tool_icons.operation(op)}
        args=op.get('arguments')
        action=shell_action(args.get('cmd')) if op['kind']=='run' and isinstance(args,dict) else None
        if action:
            presented = native_label(action)
            row.update(label=presented['label'], label_key=presented['label_key'], label_params=presented['label_params'],
                       label_message=presented['label_message'],
                       kind=action['type'], icon=tool_icons.file_action(action), shell_action=action)
        if op.get('tool') in WAIT:
            args=op.get('arguments')
            cell=args.get('cell_id') if isinstance(args,dict) else None
            requested_stop=isinstance(args,dict) and args.get('terminate') is True
            wait_key = 'tools.exec.waitTerminate' if requested_stop else 'tools.exec.waitReturn'
            row['label'] = legacy(wait_key, cell=cell or '')
            row['label_key'] = wait_key
            row['label_params'] = {'cell': cell} if cell is not None else {}
            row['label_message'] = msg(wait_key)
            if cell is not None:
                row['label'] += ' · cell ' + str(cell)
                row['label_message'] = {'join': [row['label_message'], ' · cell ' + str(cell)], 'separator': ''}
        if pos in forwarded and not op.get('event'):
            block,value = forwarded[pos]
            if isinstance(value,dict) and value.get('type')=='image':
                row['media_block'] = block
            else:
                row['value'] = value
                if (op.get('tool') or '').startswith('mcp__'):
                    receipt=tools.decode(value) if isinstance(value,str) else value
                    if isinstance(receipt,dict) and (receipt.get('isError') is True or receipt.get('error') is not None):
                        row['label'] += legacy('tools.exec.serviceError')
                        row.setdefault('label_suffix_keys', []).append('tools.exec.serviceError')
            owned.add(pos)
        if pos not in forwarded and op.get('tool') and not op.get('event') and op.get('tool') not in WAIT:
            row['label_key'] = 'tools.exec.requestPrefix'
            row['label_params'] = {'label': row['label']}
            row['label_message'] = msg('tools.exec.requestPrefix', label=row['label_message'])
            row['label'] = legacy('tools.exec.requestPrefix', label=row['label'])
        rows.append(row)
    for index in range(len(results)):
        if index not in used:
            append_native(index)
    # A single printed array can contain several results. Hide the shared block
    # only when every element in it has been accounted for.
    consumed = {block for block,_ in forwarded.values()
                if all(pos in owned for pos,(other,_) in forwarded.items() if other==block)}
    for row in rows:
        pos = row.get('op')
        if pos in forwarded and forwarded[pos][0] not in consumed:
            row.pop('value',None)
            row.pop('media_block',None)
    for row in rows:
        pos=row.get('op')
        if pos is not None and tools.is_quiet_poll(sources[pos],row.get('value')):
            row['label'] += legacy('tools.action.noNewOutput')
            row.setdefault('label_suffix_keys', []).append('tools.action.noNewOutput')
    state_key = ''
    status_map = dict(ROW_STATE_KEYS)
    if tools.identity(item) in WAIT:
        status_map.update(completed=WAIT_STATE_KEYS['completed'], aborted=WAIT_STATE_KEYS['aborted'])
    state = ''
    for start in item.get('return_starts',[]):
        blocks=item['output_blocks']
        status,_=cell_status(blocks[start] if start<len(blocks) else None)
        if status and status in status_map:
            state_key = status_map[status]
            state = legacy(state_key)
    if item.get('output') is None and not item.get('standalone_native'):
        state_key = ROW_STATE_KEYS['no_result']
        state = legacy(state_key)
    for row in rows:
        if row.get('label_suffix_keys'):
            row['label_message'] = {'join': [row['label_message'], *(msg(key) for key in row['label_suffix_keys'])], 'separator': ' '}
    if len(rows)==1:
        label = rows[0]['label']
        view_label_key = rows[0].get('label_key')
        view_label_params = rows[0].get('label_params', {})
        view_label_message = rows[0]['label_message']
    else:
        unique = list(dict.fromkeys(row['label'] for row in rows))
        label = legacy('tools.exec.multiLabel', labels='、'.join(unique), count=len(rows))
        view_label_key = 'tools.exec.multiLabel'
        view_label_params = {'labels': '、'.join(unique), 'count': len(rows)}
        descriptors = list({json.dumps(row['label_message'], sort_keys=True): row['label_message'] for row in rows}.values())
        view_label_message = msg('tools.exec.multiLabel', labels={'join': descriptors, 'separator_key': 'tools.activityGroupSep'}, count=len(rows))
    if len(rows)==1 and sources and not sources[0].get('tool') and re.fullmatch(
            r'const (\w+) = ALL_TOOLS \. filter .+ ; text \( \1 \)',forwarding_shape(item.get('text',''))):
        label = legacy('tools.exec.findTools')
        view_label_key = 'tools.exec.findTools'
        view_label_params = {}
        view_label_message = msg(view_label_key)
        rows[0]['icon']='ListFilter'
    view = {'rows':rows,'label':label,'label_key':view_label_key,'label_params':view_label_params,'label_message':view_label_message,
            'icon':tool_icons.combine(row['icon'] for row in rows),'kind':rows[0]['kind'] if rows else 'other',
            'count':len(rows),'state':state,'state_key':state_key,'consumed':sorted(consumed),
            'headers':{str(i):m.end() for i,m in headers}}
    return view

def summary(view):
    return {k:view[k] for k in ('label','label_key','label_params','label_message','kind','icon','count','state','state_key') if k in view}
