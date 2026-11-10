"""Read-only presentation of code-mode calls. Never evaluate recorded JavaScript."""
import json
import re
import shlex

import tool_operations as tools
import tool_icons


WAIT = {'wait', 'functions.wait'}
HEADER = re.compile(r'^Script (completed|failed|terminated|running with cell ID ([\w.-]+))\r?\nWall time [^\n]*\r?\nOutput:\r?\n?')
LABELS = {'read':'读取', 'search':'搜索', 'list_files':'列举', 'edit':'修改文件'}

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
                item['cell_link_note']=('此编号对应多条未结束的调用，无法确定来源。' if candidates
                                        else '等待发出时没有可关联的运行单元。')
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
                        item['exec_view']['state']='图片已返回' if has_image else '结果已返回'
                    else:
                        item['exec_view']['state']={'terminated':'编排已终止','failed':'编排失败','aborted':'用户中止'}[status]
            continue
        cell=wait_cell(item)
        index=item.get('cell_origin')
        if index is None or owners.get(cell)!={index}:
            continue
        origin=items[index]
        if status=='aborted':
            # A cancelled wait ends this request; the underlying cell can still
            # be polled later. No final return or process exit is established.
            origin['exec_view']['state']='等待被中断 · cell 最终状态未记录'
        elif status=='running':
            if yielded_cell==cell:
                origin['exec_view']['state']='待取回'
        else:
            owners[cell].remove(index)
            origin['cell_final']=item['index']
            if status=='completed':
                image=any(isinstance(b,dict) and b.get('type')=='image' for b in blocks[start:end])
                origin['exec_view']['state']='图片已返回' if image else '结果已返回'
            else:
                origin['exec_view']['state']='编排已终止' if status=='terminated' else '取回失败'


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
    if kind=='edit':
        verb = {'add':'新增','delete':'删除'}.get(action.get('change'),'修改文件')
        if action.get('old_path'):
            return '移动 '+action['old_path']+' → '+action['path']
        return verb+' '+action.get('path','文件')
    if kind=='search':
        return '搜索 '+(action.get('query') or action.get('cmd') or '')
    if kind=='list_files':
        label='列举 '+(action.get('path') or '文件')
        if 'output_limit' in action:
            label+=' · 前 '+str(action['output_limit'])+' 行'
        return label
    return LABELS.get(kind,'运行命令')+' '+(action.get('path') or action.get('name') or action.get('cmd') or '')

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
                label=native_label(action)
                op.update(shell_action=action,icon=tool_icons.file_action(action),action=LABELS[action['type']],summary='请求'+label if item.get('output') is None else label)


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
        labels = [native_label(actions[j]) for j in ids if actions[j]['type'] in LABELS]
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
        generic='运行命令'+(' '+brief if brief else '')
        label = '、'.join(labels) or generic
        kind=actions[ids[0]]['type'] if ids else 'run'
        if inferred:
            label,kind=native_label(inferred),inferred['type']
        elif patch and not ids:
            label,kind='修改文件','edit'
        if result.get('status')=='failed' and (patch or any(actions[j]['type']=='edit' for j in ids)):
            label = '尝试'+label+' · 写入失败'
        if result.get('source')=='unified_exec_interaction':
            label='后台终端交互'
            kind='session'
        elif result.get('source')=='user_shell':
            label='用户'+generic
        row={'native':index,'actions':ids,'label':label[:250],'kind':kind}
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
        row = {'op':pos,'label':op['summary'],'kind':op['kind'],'icon':op.get('icon') or tool_icons.operation(op)}
        args=op.get('arguments')
        action=shell_action(args.get('cmd')) if op['kind']=='run' and isinstance(args,dict) else None
        if action:
            row.update(label=native_label(action),kind=action['type'],icon=tool_icons.file_action(action),shell_action=action)
        if op.get('tool') in WAIT:
            args=op.get('arguments')
            cell=args.get('cell_id') if isinstance(args,dict) else None
            requested_stop=isinstance(args,dict) and args.get('terminate') is True
            row['label']=('请求终止编排' if requested_stop else '等待编排返回')+(' · cell '+str(cell) if cell is not None else '')
        if pos in forwarded and not op.get('event'):
            block,value = forwarded[pos]
            if isinstance(value,dict) and value.get('type')=='image':
                row['media_block'] = block
            else:
                row['value'] = value
                if (op.get('tool') or '').startswith('mcp__'):
                    receipt=tools.decode(value) if isinstance(value,str) else value
                    if isinstance(receipt,dict) and (receipt.get('isError') is True or receipt.get('error') is not None):
                        row['label']+=' · 服务返回错误'
            owned.add(pos)
        if pos not in forwarded and op.get('tool') and not op.get('event') and op.get('tool') not in WAIT:
            row['label']='请求'+row['label']
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
            row['label']+=' · 无新增输出'
    states={'running':'待取回','failed':'编排失败','terminated':'编排已终止','aborted':'用户中止'}
    if tools.identity(item) in WAIT:
        states.update(completed='等待已完成',aborted='等待被用户中断')
    state=''
    for start in item.get('return_starts',[]):
        blocks=item['output_blocks']
        status,_=cell_status(blocks[start] if start<len(blocks) else None)
        if status:
            state=states.get(status,'')
    if item.get('output') is None and not item.get('standalone_native'):
        state='未记录结果'
    if len(rows)==1:
        label = rows[0]['label']
    else:
        labels = list(dict.fromkeys(row['label'].split(' ')[0] for row in rows))
        label = '、'.join(labels)+' · '+str(len(rows))+' 项'
    if len(rows)==1 and sources and not sources[0].get('tool') and re.fullmatch(
            r'const (\w+) = ALL_TOOLS \. filter .+ ; text \( \1 \)',forwarding_shape(item.get('text',''))):
        label='查找可用工具'
        rows[0]['icon']='ListFilter'
    return {'rows':rows,'label':label,'icon':tool_icons.combine(row['icon'] for row in rows),'kind':rows[0]['kind'] if rows else 'other',
            'count':len(rows),'state':state,'consumed':sorted(consumed),
            'headers':{str(i):m.end() for i,m in headers}}

def summary(view):
    return {k:view[k] for k in ('label','kind','icon','count','state')}
