import json,sqlite3,os,argparse,re,html,hashlib,time,sys,threading
from contextlib import closing, nullcontext
from functools import lru_cache
import native_events
import exec_presentation as exec_ui
import mcp_output
import pricing
import tool_operations as classification
from token_usage import report as usage_report
from session_io import open_rollout,resolve_rollout,cached_history,stamp
from urllib.parse import unquote, urlencode
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).parent
HOME=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
class DatabaseUnavailable(RuntimeError):pass

def read_sql(path,query,params=()):
 # Always close, including failed queries. URI quoting preserves spaces, # and ?.
 for attempt in range(3):
  try:
   with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
    c.row_factory=sqlite3.Row
    return c.execute(query,params).fetchall()
  except sqlite3.OperationalError as exc:
   if not any(value in str(exc).lower() for value in ('unable to open','locked','busy')):raise
   if attempt<2:time.sleep(.15*(attempt+1));continue
   print(f'Database read failed: {Path(path).name}: {exc}; exists={Path(path).exists()}; readable={os.access(path,os.R_OK)}; code={getattr(exc,"sqlite_errorname",None)}',file=sys.stderr,flush=True)
   raise DatabaseUnavailable(f'暂时无法读取 {Path(path).name}，正在等待恢复。请确认 Codex 数据目录可访问。') from exc

HISTORY_CACHE = {}
HISTORY_LOCK = threading.RLock()
HISTORY_FAILURE = {'home': None, 'retry_after': 0}
def history_warning():
 with HISTORY_LOCK:
  unavailable = HISTORY_FAILURE['home'] == str(HOME) and HISTORY_FAILURE['retry_after'] > time.monotonic()
 return '状态与耗时数据库暂不可用，已保留可读取的会话内容。' if unavailable else None

def history_sql(query, params=(), required=False):
 path = HOME/'thread_history_1.sqlite'
 key = (str(HOME), query, tuple(params))
 with HISTORY_LOCK:
  cached = HISTORY_CACHE.get(key)
  if history_warning():
   if required and cached is None:raise DatabaseUnavailable('备用正文数据库暂不可用，请稍后重试。')
   return cached if cached is not None else []
  if not path.is_file():return cached if cached is not None else []
  try:
   result = read_sql(path, query, params)
  except (DatabaseUnavailable, sqlite3.OperationalError) as error:
   HISTORY_FAILURE.update(home=str(HOME), retry_after=time.monotonic()+5)
   if required and cached is None:raise DatabaseUnavailable('备用正文数据库暂不可用，请稍后重试。') from error
   return cached if cached is not None else []
  HISTORY_FAILURE.update(home=None, retry_after=0)
  HISTORY_CACHE[key] = result
  # Backup message bodies can be large. Keep only a few per-session results.
  if len(HISTORY_CACHE)>32:
   del HISTORY_CACHE[next(iter(HISTORY_CACHE))]
  return result

def workspace_names():
 # Use explicit local project roots only; never infer membership from ancestors.
 try:
  state=json.loads((HOME/'.codex-global-state.json').read_text())
 except (OSError,ValueError):return {}
 projects=state.get('local-projects') if isinstance(state,dict) else None
 if not isinstance(projects,dict):return {}
 names={}
 for project in projects.values():
  if not isinstance(project,dict):continue
  name,roots=project.get('name'),project.get('rootPaths')
  if not isinstance(name,str) or not name.strip() or not isinstance(roots,list):continue
  for root in roots:
   if isinstance(root,str) and root:
    key=root.replace('\\','/').removesuffix('/') or '/'
    names.setdefault(key,set()).add(name.strip())
 return {root:next(iter(labels)) for root,labels in names.items() if len(labels)==1}

def rows():
 databases=sorted(HOME.glob('state_*.sqlite'),key=lambda p:p.stat().st_mtime)
 if not databases:raise DatabaseUnavailable('未找到 Codex 会话索引，请确认 CODEX_HOME 指向已有的数据目录。')
 names=workspace_names()
 result=[dict(r) for r in read_sql(databases[-1],'select id,title,name,source,originator,cwd,updated_at,archived,model,tokens_used,rollout_path from threads order by updated_at desc')]
 for row in result:
  key=str(row.get('cwd') or '').replace('\\','/').removesuffix('/')
  row['workspace_name']=names.get(key or '/') if row.get('cwd') else None
 return result
def latest_statuses():
 result=history_sql("select thread_id,status from (select thread_id,status,row_number() over (partition by thread_id order by rollout_ordinal desc) as rank from thread_turns) where rank=1")
 return {} if history_warning() else dict(result)
def category(r):
 s=r['source'];o=(r['originator'] or '').lower()
 if 'subagent' in s:return 'agent'
 if s=='exec':return 'exec'
 if s=='cli':return 'cli'
 if 'desktop' in o:return 'app'
 if s=='vscode':return 'ide'
 return 'other'
def text(v):
 if isinstance(v,str):return v
 if isinstance(v,list):return '\n'.join(text(x) for x in v)
 if isinstance(v,dict):
  if v.get('type') in ('audio','input_audio'):return '[音频]'
  return v.get('text') or ('[图片]' if 'image' in v.get('type','') else json.dumps(v,ensure_ascii=False))
 return str(v)
def history(path):
 return cached_history(path,parse_history)[:2]
def native_actions(item):
 actions=item.get('parsed_cmd',item.get('commandActions',[]))
 if not isinstance(actions,list):return []
 normalized=[]
 for action in actions:
  if not isinstance(action,dict) or not isinstance(action.get('type'),str):continue
  fields={key:action[key] for key in ('name','path','query') if isinstance(action.get(key),str)}
  fields['type']='list_files' if action['type']=='listFiles' else action['type']
  cmd=action.get('cmd',action.get('command'))
  if isinstance(cmd,str):fields['cmd']=cmd
  normalized.append(fields)
 return normalized
def native_command(item):
 command=item.get('command','')
 if isinstance(command,list):
  return command[-1] if len(command)>=3 and command[-2] in ('-c','-lc') else ' '.join(str(v) for v in command)
 return command if isinstance(command,str) else ''
def native_file_actions(item):
 changes=item.get('changes',{})
 if isinstance(changes,dict):entries=changes.items()
 elif isinstance(changes,list):entries=((change.get('path'),change) for change in changes if isinstance(change,dict))
 else:return []
 actions=[]
 for path,change in entries:
  if not isinstance(path,str) or not isinstance(change,dict):continue
  kind=change.get('type',change.get('kind'))
  info=kind if isinstance(kind,dict) else change
  destination=info.get('move_path') or info.get('movePath') or change.get('move_path') or change.get('movePath')
  action=dict(type='edit',path=path,name=Path(path).name)
  if isinstance(destination,str) and destination:
   action.update(path=destination,name=Path(destination).name,old_path=path)
  if isinstance(kind,dict):
   kind=kind.get('type')
  if kind in ('add','delete'):
   action['change']=kind
   # The DB projection calls the full file contents "diff" for an add/delete.
   content=change.get('content',change.get('diff'))
   if isinstance(content,str):
    lines=content.splitlines()
    sign='+' if kind=='add' else '-'
    action.update(diff='\n'.join(sign+line for line in lines),additions=len(lines) if kind=='add' else 0,deletions=len(lines) if kind=='delete' else 0)
  diff=change.get('unified_diff',change.get('diff')) if kind not in ('add','delete') else change.get('unified_diff')
  if isinstance(diff,str):
   if isinstance(destination,str) and destination and isinstance(change.get('kind'),dict):
    diff=diff.removesuffix('\n\nMoved to: '+destination)
   added=removed=0;in_hunk=False
   for line in diff.splitlines():
    if line.startswith('@@'):in_hunk=True;continue
    if line.startswith('diff --git '):in_hunk=False;continue
    if not in_hunk and line.startswith(('+++ ','--- ')):continue
    added+=line.startswith('+');removed+=line.startswith('-')
   action.update(additions=added,deletions=removed,diff=diff)
  actions.append(action)
 return actions
def attach_native_result(target,item,actions):
 result_index=len(target.setdefault('native_results',[]))
 output=item.get('aggregated_output',item.get('aggregatedOutput'))
 if output is None and ('stdout' in item or 'stderr' in item):output='\n'.join(value for value in (item.get('stdout'),item.get('stderr')) if isinstance(value,str) and value)
 result=dict(command=native_command(item),cwd=item.get('cwd'),status=item.get('status'),exit_code=item.get('exit_code',item.get('exitCode')),output=output,action_count=len(actions))
 if str(item.get('type','')).lower()=='filechange':result['type']='file_change'
 if isinstance(item.get('source'),str):
  source=item['source']
  result['source']={'userShell':'user_shell','unifiedExecStartup':'unified_exec_startup','unifiedExecInteraction':'unified_exec_interaction'}.get(source,source)
 for key,alternate in [('process_id','processId'),('interaction_input','interactionInput'),('duration_ms','durationMs')]:
  value=item.get(key,item.get(alternate))
  if value is not None:result[key]=value
 duration=item.get('duration')
 if 'duration_ms' not in result and isinstance(duration,dict) and all(type(duration.get(k)) is int for k in ('secs','nanos')):
  result['duration_ms']=duration['secs']*1000+duration['nanos']//1_000_000
 target['native_results'].append(result)
 target.setdefault('native_actions',[]).extend({**action,'result_index':result_index} for action in actions)
def parse_history(path):
 return parse_rollout(open_rollout(path))

def recorded_commands(call):
 # Only static arguments from known command tools, never a source substring.
 return [op['arguments'].get('cmd',op['arguments'].get('command'))
         for op in classification.source_operations(call)
         if op.get('tool') in ('exec_command','functions.exec_command')
         and isinstance(op.get('arguments'),dict)
         and isinstance(op['arguments'].get('cmd',op['arguments'].get('command')),str)]

def command_context_conflicts(call,native,source_index=None):
 ops=classification.source_operations(call)
 if source_index is not None:ops=ops[source_index:source_index+1]
 command=native_command(native)
 args=[op.get('arguments') for op in ops if op.get('tool') in ('exec_command','functions.exec_command')]
 if source_index is not None and args:
  known=args[0].get('cmd',args[0].get('command')) if isinstance(args[0],dict) else None
  if isinstance(known,str) and command and known!=command:return True
 for arg in args:
  if not isinstance(arg,dict):continue
  if source_index is None and arg.get('cmd',arg.get('command'))!=command:continue
  cwd=arg.get('workdir');actual=native.get('cwd')
  if isinstance(cwd,str) and isinstance(actual,str) and os.path.isabs(cwd) and os.path.isabs(actual):
   if os.path.normpath(cwd)!=os.path.normpath(actual):return True
 return False

def command_event_target(native,explicit,turn,call_ids,command_calls,pending,open_calls,process_calls):
 command=native_command(native)
 if explicit:
  matches=call_ids.get((turn,explicit),[])
  return (matches[0],None) if len(matches)==1 else (None,'ambiguous_id' if matches else 'unknown_id')
 # An interaction or manually run command is not a fresh exec_command request.
 if native.get('source') in ('user_shell','userShell','unified_exec_interaction','unifiedExecInteraction'):
  return None,'independent_source'
 process=exec_ui.process_key(native.get('process_id',native.get('processId')))
 origins=process_calls.get((turn,process),[]) if turn is not None and process is not None else []
 if origins:
  if len(origins)!=1:return None,'ambiguous_process'
  target,pos=origins[0]
  if command_context_conflicts(target,native,pos):return None,'conflicting_process'
  if any(exec_ui.process_key(r.get('process_id'))==process for r in target.get('native_results',[])):
   return None,'already_linked'
  return target,None
 matches=command_calls.get((turn,command),[]) if command else []
 if matches:
  if len(matches)!=1:return None,'ambiguous_command'
  target=matches[0]
  if command_context_conflicts(target,native):return None,'conflicting_cwd'
  if any(result.get('command')==command for result in target.get('native_results',[])):
   return None,'already_linked'
  active=any(call is target for call in open_calls.values())
  if turn is None and not active:return None,'missing_turn'
  return target,None
 # No late-call fallback. A known, different literal command is contradictory
 # evidence even when there is only one active call.
 if len(pending)==1 and not recorded_commands(pending[0]):return pending[0],None
 return None,'ambiguous_pending' if len(pending)>1 else 'no_matching_call'

def parse_rollout(stream):
 session_boundaries=[]
 items=[];calls={};open_calls={};native_ids=set();bad=0;turn_id=None;turn_contexts={};snapshots={}
 call_ids={};command_calls={};process_calls={}
 with stream as f:
  for line_no,line in enumerate(f,1):
   try:o=json.loads(line)
   except ValueError:bad+=1;continue
   p=o.get('payload',{});typ=p.get('type','');entry={'time':o.get('timestamp'),'kind':typ}
   if o.get('type')=='session_meta':
    session_boundaries.append(line_no)
    calls.clear();open_calls.clear();native_ids.clear();turn_id=None
    call_ids.clear();command_calls.clear();process_calls.clear()
   if o.get('type')=='turn_context':
    turn_id=p.get('turn_id',turn_id)
    if p.get('turn_id'):
     snapshots.setdefault(turn_id,[]).append({'time':o.get('timestamp'),'payload':p})
    if turn_id:turn_contexts[turn_id]={'model':p.get('model'),'effort':p.get('effort'),'time':o.get('timestamp')}
   if o.get('type')=='event_msg' and typ=='task_started':turn_id=p.get('turn_id',turn_id)
   entry['turn_id']=turn_id
   if o.get('type')=='event_msg' and typ=='item_completed':
    native=p.get('item',{})
    if not isinstance(native,dict):continue
    native=native_events.normalize(native)
    native_type=str(native.get('type','')).lower()
    actions=native_file_actions(native) if native_type=='filechange' else native_actions(native) if native_type=='commandexecution' else []
    is_event = native_type in ('mcptoolcall','imageview') or bool(native.get('native_family'))
    if is_event or native_type in ('commandexecution','filechange'):
     identifier=native.get('id')
     event_turn=p.get('turn_id',turn_id)
     event_key=(event_turn,native_type,native.get('kind'),native.get('agentThreadId'),identifier)
     if identifier and event_key in native_ids:continue
     if identifier:native_ids.add(event_key)
     pending=[call for call in open_calls.values() if call.get('turn_id')==p.get('turn_id',turn_id)]
     explicit = p.get('call_id') or native.get('call_id') or native.get('callId')
     if explicit and is_event and 'call_id' not in native:
      native={**native,'call_id':explicit}
     if is_event and not explicit and identifier in open_calls:explicit=identifier
     reason=None
     if native_type=='commandexecution':
      command_pending=[call for call in pending if re.search(r'exec|command|shell',call.get('name') or '',re.I)]
      target,reason=command_event_target(native,explicit,event_turn,call_ids,command_calls,command_pending,open_calls,process_calls)
     elif explicit:
      target = open_calls.get(explicit)
      if target is not None and target.get('turn_id') != p.get('turn_id',turn_id):target=None
     elif is_event:
      matches=[call for call in pending for op in classification.source_operations(call) if classification.event_matches(op,native)]
      target=matches[0] if len(matches)==1 else None
     else:
      pending=[call for call in pending if re.search(r'exec|command|shell|apply_patch',call.get('name') or '',re.I)]
      command=native_command(native)
      matches=[call for call in pending if (command and (command in call['text'] or json.dumps(command,ensure_ascii=False)[1:-1] in call['text'])) or (native_type=='filechange' and any(action['path'] in call['text'] for action in actions))]
      target=matches[0] if len(matches)==1 else pending[0] if len(pending)==1 else None
     if target is None:
      target=dict(entry,kind='tool',name='',text='',standalone_native=True,
                  record_type='native_event',native_type=native.get('type'),association_reason=reason or 'unlinked_event')
      if not explicit and native.get('native_family')=='generation' and isinstance(native.get('result'),str) and native['result']:
       target['_image_candidates']=[
        owner for owner in pending if classification.identity(owner) in exec_ui.WAIT
        or any(native_events.same_direct_kind(op.get('tool'),native) for op in classification.source_operations(owner))]
      items.append(target)
     target.setdefault('_raw_lines',[]).append(line_no)
     if is_event:target.setdefault('tool_events',[]).append(native)
     else:
      attach_native_result(target,native,actions)
      if native_type=='commandexecution' and not target.get('standalone_native'):
       pid=exec_ui.process_key(native.get('process_id',native.get('processId')))
       origins=process_calls.get((event_turn,pid),[]) if event_turn is not None and pid is not None else []
       if len(origins)==1 and origins[0][0] is target:
        target['native_results'][-1].update(source_index=origins[0][1],association='process_id')
    continue
   if o.get('type')!='response_item':continue
   if typ=='message':
    role=p.get('role');entry.update(role=role,text=text(p.get('content',[])))
    if role not in ('user','assistant'):entry['kind']='context'
   elif typ in ('function_call','custom_tool_call'):
    entry.update(kind='tool',record_type='tool_call',call_id=p.get('call_id'),name=p.get('name'),text=text(p.get('arguments',p.get('input',''))),output=None)
    if p.get('namespace'):entry['namespace']=p['namespace']
    entry['_raw_lines']=[line_no]
    calls[p.get('call_id')]=entry;open_calls[p.get('call_id')]=entry
    call_ids.setdefault((turn_id,p.get('call_id')),[]).append(entry)
    for command in recorded_commands(entry):command_calls.setdefault((turn_id,command),[]).append(entry)
   elif typ in ('function_call_output','custom_tool_call_output'):
    result=text(p.get('output',''))
    if p.get('call_id') in calls:
     call=calls[p['call_id']]
     call['_raw_lines'].append(line_no)
     if classification.identity(call) in classification.WRAPPERS | exec_ui.WAIT:
      exec_ui.record_return(call,p.get('output',''))
      call.setdefault('_return_lines',[]).append(line_no)
      call['output']=result if call['output'] is None else call['output']+'\n'+result
     else:
      call['output']=result
      if classification.identity(call).startswith('mcp__') and isinstance(p.get('output'),(dict,list)):
       call['mcp_output']=p['output']
     for pos,pid in exec_ui.process_receipts(call):
      origins=process_calls.setdefault((call.get('turn_id'),pid),[])
      if not any(owner is call and source==pos for owner,source in origins):origins.append((call,pos))
     open_calls.pop(p['call_id'],None);continue
    entry.update(kind='tool',name='工具结果',text=result,_raw_lines=[line_no])
   elif typ=='reasoning':
    summary=text(p.get('summary',[]))
    if not summary:continue
    entry.update(kind='reasoning',text=summary)
   else:
    entry.update(kind='context',text=json.dumps(p,ensure_ascii=False))
   items.append(entry)
 items=native_events.bind_returned_images(items)
 for index,item in enumerate(items):
  item['index']=index
  context=turn_contexts.get(item.get('turn_id'))
  if item.get('kind')=='tool':
   classification.describe(item)
   exec_ui.describe_execution(item)
  if context:item['turn_context']=dict(context,available=item['turn_id'] in snapshots)
 exec_ui.link_waits(items,session_boundaries)
 return [mcp_output.visible_item(item) for item in items],bad,snapshots
def stored_ids():
 return {r[0] for r in history_sql('select distinct thread_id from thread_items')}
def stored_history(id):
 p=HOME/'thread_history_1.sqlite'
 if not p.exists():return []
 rows=history_sql('select item_json,created_at_ms,turn_id from thread_items where thread_id=? order by rollout_ordinal',(id,),required=True)
 return project_stored_rows(rows)

def project_stored_rows(rows):
 items=[]
 for raw,ts,turn_id in rows:
  v=json.loads(raw);t=v.get('type');e={'time':ts/1000,'turn_id':turn_id,'kind':'tool','name':v.get('tool',t)}
  if t in ('userMessage','agentMessage','plan'):
   e.update(kind='message',role='user' if t=='userMessage' else 'assistant',text=v.get('text') or text(v.get('content',[])))
  elif t=='reasoning':
   summary=text(v.get('summary',[]))
   if not summary:continue
   e.update(kind='reasoning',text=summary)
  elif t=='commandExecution':
   e.update(standalone_native=True,name='commandExecution',text=v.get('command',''),output=v.get('aggregatedOutput'))
   attach_native_result(e,v,native_actions(v))
  elif t=='fileChange':
   e.update(standalone_native=True,name='fileChange',text='')
   attach_native_result(e,v,native_file_actions(v))
  elif native_events.family(v):
   e.update(text='',standalone_native=True,tool_events=[native_events.normalize(v)])
  elif t in ('imageView','ImageView','mcpToolCall','McpToolCall'):
   e.update(text='',standalone_native=True,tool_events=[dict(v,type='ImageView' if t.lower()=='imageview' else 'McpToolCall')])
  else:e.update(text=json.dumps(v,ensure_ascii=False,indent=2))
  if e.get('kind')=='tool':
   if e.get('standalone_native'):
    e.update(record_type='native_event',native_type=t,name='',association_reason='database_record')
   else:e['record_type']='tool_call'
   classification.describe(e)
   exec_ui.describe_execution(e)
   e['_stored_raw']=raw
  items.append(mcp_output.visible_item(e))
 return items
def stored_turns(id):
 p=HOME/'thread_history_1.sqlite'
 if not p.exists():return []
 return [dict(r) for r in history_sql('select turn_id,status,started_at,completed_at,duration_ms from thread_turns where thread_id=? order by rollout_ordinal',(id,))]
def referenced_files(items):
 result=set()
 for item in items:
  if item.get('kind')!='message':continue
  raw_text=item.get('text','')
  if item.get('role')=='user' and raw_text.lstrip().startswith('# Files mentioned by the user:'):
   header=raw_text.split('## My request:',1)[0]
   for attached in re.finditer(r'^## .+?: (/[^\n]+)\s*$',header,re.M):
    result.add(str(Path(attached.group(1).strip()).resolve()))
  for match in re.finditer(r'\]\(\s*(?:<([^>]+)>|([^\s]+?))\s*\)',item.get('text','')):
   raw=unquote(match.group(1) or match.group(2))
   raw=re.sub(r':\d+(?::\d+)?$','',raw)
   if raw.startswith('/') and not raw.startswith('//'):result.add(str(Path(raw).resolve()))
 return result
def context_item(item):
 return item.get('kind')=='context' or (item.get('role')=='user' and re.match(r'\s*(# AGENTS\.md instructions|<(environment_context|external_browser_tabs|external_codex_apps_open_page|permissions instructions)[\s>])',item.get('text','')))
def raw_tool_records(item,path):
 if '_stored_raw' in item:return mcp_output.visible_records(item,[item['_stored_raw']])
 wanted=set(item.get('_raw_lines',[]))
 if not wanted:return []
 records=[]
 with open_rollout(path) as lines:
  for index,line in enumerate(lines,1):
   if index in wanted:
    records.append(line.rstrip('\r\n'));wanted.remove(index)
    if not wanted:break
 return mcp_output.visible_records(item,records)

def page_payload(items,q):
 # Indexes refer to the original append-only transcript, including context.
 for index,item in enumerate(items):item['index']=index
 if q.get('view')==['context']:return {'items':[x for x in items if context_item(x)]}
 if 'item' in q:
  index=int(q['item'][0])
  if not 0<=index<len(items):raise ValueError('执行记录不存在')
  item=items[index]
  if item.get('kind')=='tool' and 'operations' not in item:item=classification.describe(dict(item))
  return {'item':{k:v for k,v in item.items() if k not in ('_raw_lines','_stored_raw','_return_lines')}}
 boundaries=[i for i,x in enumerate(items) if x.get('role')=='user' and not context_item(x)]
 if not boundaries or boundaries[0]!=0:boundaries.insert(0,0)
 end=min(len(items),max(0,int(q.get('before',[str(len(items))])[0])))
 default_start=([i for i in boundaries if i<end][-8:] or [0])[0]
 start=max(0,int(q['start'][0])) if 'start' in q else default_start
 if start>=end:start=default_start
 query=q.get('q',[''])[0].casefold()
 if query:start=0;end=len(items)
 visible=[]
 for index in range(start,end):
  item=items[index]
  if context_item(item):continue
  copy=dict(item)
  if item.get('kind')=='tool':
   # Small preview only; full input/output travels on explicit expansion.
   if 'operations' not in copy:classification.describe(copy)
   ops=copy['operations']
   copy['operations']=classification.summaries(ops)
   copy.pop('tool_events',None)
   raw=item.get('text','')
   copy['text']=raw[:1000]
   if len(raw)>1000:
    try:
     args=json.loads(raw)
     if isinstance(args,dict):copy['text']=json.dumps({k:v[:500] if isinstance(v,str) else v for k,v in args.items() if k in ('title','description','completion_summary','cmd','command','query','url','path','file_path','prompt','code')},ensure_ascii=False)
    except ValueError:pass
   if 'exec_view' in copy:copy['exec_view']=exec_ui.summary(copy['exec_view'])
   copy.pop('return_starts',None)
   copy.pop('native_actions',None)
   copy.pop('native_results',None)
   copy.pop('output',None);copy.pop('output_blocks',None);copy.pop('mcp_output',None);copy['lazy']=True
   if query:
    contents=[raw,str(item.get('output') or ''),json.dumps(ops,ensure_ascii=False,default=str),json.dumps(item.get('native_results',[]),ensure_ascii=False,default=str)]
    if any(query in str(value).casefold() for value in contents):copy=dict(item,operations=ops)
  copy.pop('_raw_lines',None);copy.pop('_stored_raw',None);copy.pop('_return_lines',None)
  visible.append(copy)
 return {'items':visible,'start':start,'end':end,'total':len(items),'has_more':start>0}
def parent_id(row):
 return cached_parent(row.get('source') or '',str(HOME.resolve()),stamp(row['rollout_path']))
@lru_cache(maxsize=4096)
def cached_parent(raw_source,root,version):
 try:
  source=json.loads(raw_source or '{}')
  meta=source.get('subagent',{}).get('thread_spawn',{})
  if meta.get('parent_thread_id'):return meta['parent_thread_id']
 except (ValueError,AttributeError,TypeError):pass
 p=Path(version[0]).resolve()
 if not p.is_relative_to(HOME.resolve()) or not p.exists():return None
 try:
  with open_rollout(p) as f:
   first=json.loads(next(f,'{}')).get('payload',{})
  if first.get('parent_thread_id'):return first['parent_thread_id']
  source=first.get('source',{})
  if isinstance(source,dict):return source.get('subagent',{}).get('thread_spawn',{}).get('parent_thread_id')
 except (OSError,ValueError,RuntimeError,AttributeError,TypeError):pass
 return None
def relations(id):
 rs=rows();current=next((r for r in rs if r['id']==id),{})
 parent=parent_id(current) if current else None
 def brief(r):
  result={k:r.get(k) for k in ('id','title','name','source')}
  try:result['task_path']=json.loads(r.get('source') or '{}').get('subagent',{}).get('thread_spawn',{}).get('agent_path')
  except (ValueError,AttributeError,TypeError):pass
  return result
 return {'parent':next((brief(r) for r in rs if r['id']==parent),None),'children':[brief(r) for r in rs if r['id']!=id and parent_id(r)==id]}
def revision(id):
 rs=rows()
 summary=[(r['id'],r['updated_at'],r['title'],r['archived']) for r in rs]
 history_stamp=stamp(HOME/'thread_history_1.sqlite')
 wal_stamp=stamp(HOME/'thread_history_1.sqlite-wal')
 current=next((r for r in rs if r['id']==id),None)
 digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()[:20]
 turns=stored_turns(id) if current else None
 warning=history_warning()
 return {'list':digest([summary,history_stamp,wal_stamp,warning]),'thread':digest([stamp(current['rollout_path']) if current else None,turns,warning])}

def demo_response(path,q):
 import demo_cases
 if path=='/api/demo/threads':return 200,demo_cases.catalog()
 identifier=q.get('id',[''])[0]
 if identifier not in demo_cases.CASES:return 404,{'error':'示例不存在'}
 if path=='/api/demo/revision':return 200,{'list':'demo','thread':identifier}
 if path!='/api/demo/thread':return 404,{'error':'未知演示接口'}
 lines=demo_cases.lines(identifier)
 is_database=demo_cases.CASES[identifier][0].get('record_format')=='database'
 if is_database:
  items=project_stored_rows((line,1893456000000+n*1000,'turn-0') for n,line in enumerate(lines))
  bad,snapshots=0,{}
 else:items,bad,snapshots=parse_rollout(nullcontext(lines))
 if q.get('view')==['turn-context']:return 200,{'records':snapshots.get(q.get('turn',[''])[0],[])}
 if 'item' in q and q.get('raw')==['1']:
  index=int(q['item'][0])
  if not 0<=index<len(items) or items[index]['kind']!='tool':raise ValueError('工具记录不存在')
  if is_database:return 200,{'records':raw_tool_records(items[index],None)}
  return 200,{'records':mcp_output.visible_records(items[index],[lines[n-1] for n in items[index]['_raw_lines']])}
 payload=page_payload(items,q)
 if 'item' not in q and 'view' not in q:
  payload.update(thread=demo_cases.CASES[identifier][0],turns=[],relations={'children':[]},skipped=bad)
 return 200,payload

class Handler(BaseHTTPRequestHandler):
 def stream_usage(self,query):
  records=rows()
  self.send_response(200)
  self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
  self.send_header('Cache-Control','no-store')
  self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Connection','close')
  self.end_headers();self.close_connection=True
  def emit(value):
   self.wfile.write((json.dumps(value,ensure_ascii=False)+'\n').encode());self.wfile.flush()
  last=[0]
  def progress(completed,total):
   now=time.monotonic()
   if completed in (0,total) or now-last[0]>=.15:
    emit(dict(type='progress',completed=completed,total=total));last[0]=now
  try:
   result=usage_report(records,HOME,query,on_progress=progress)
   emit(dict(type='result',data=result))
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception as error:
   try:emit(dict(type='error',error=str(error)))
   except (BrokenPipeError,ConnectionResetError):pass
 def send(self,status,data,mime='application/json'):
  b=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(b)
 def do_POST(self):
  host=self.headers.get('Host','')
  if host.split(':')[0] not in ('localhost','127.0.0.1'):return self.send(403,{'error':'仅允许 localhost 访问'})
  origin=self.headers.get('Origin')
  if origin and origin not in ('http://'+host,):return self.send(403,{'error':'拒绝跨站设置请求'})
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'需要 JSON 请求'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length<1 or length>16384:return self.send(413,{'error':'请求大小不合法'})
   value=json.loads(self.rfile.read(length))
   if self.path=='/api/pricing/settings':return self.send(200,pricing.configure(value))
   if self.path=='/api/pricing/refresh':return self.send(200,pricing.refresh(value.get('source')))
   return self.send(404,{'error':'未找到设置'})
  except (ValueError,TypeError,AttributeError) as error:return self.send(400,{'error':str(error)})
  except Exception as error:return self.send(502,{'error':'同步失败，已有缓存已保留：'+str(error)})
 def do_GET(self):
  if self.headers.get('Host','').split(':')[0] not in ('localhost','127.0.0.1'):return self.send(403,{'error':'仅允许 localhost 访问'})
  u=urlparse(self.path)
  try:
   if u.path in ('/demo','/demo/'):
    markup=(ROOT/'designs/browser/index.html').read_text().replace('<script defer src="/token-usage.js"></script>','')
    return self.send(200,markup.encode(),'text/html; charset=utf-8')
   if u.path.startswith('/api/demo/'):return self.send(*demo_response(u.path,parse_qs(u.query)))
   if u.path=='/api/pricing':return self.send(200,pricing.status())
   if u.path=='/api/usage':
    query=parse_qs(u.query)
    if query.get('stream')==['1']:return self.stream_usage(query)
    return self.send(200,usage_report(rows(),HOME,query))
   if u.path=='/api/revision':return self.send(200,revision(parse_qs(u.query).get('id',[''])[0]))
   if u.path=='/api/threads':
    rs=rows();saved=stored_ids();statuses=latest_statuses()
    for r in rs:r['status']=statuses.get(r['id']);r['category']=category(r);r['available']=True if resolve_rollout(r['rollout_path']).is_file() or r['id'] in saved else (None if history_warning() else False);r.pop('rollout_path',None)
    return self.send(200,rs)
   if u.path=='/api/thread':
    id=parse_qs(u.query).get('id',[''])[0];r=next((x for x in rows() if x['id']==id),None)
    if not r:return self.send(404,{'error':'会话不存在'})
    p=resolve_rollout(r.pop('rollout_path')).resolve()
    if not p.is_relative_to(HOME.resolve()):return self.send(403,{'error':'记录位于数据目录之外'})
    q=parse_qs(u.query)
    if q.get('view')==['turn-context']:
     records=cached_history(p,parse_history)[2].get(q.get('turn',[''])[0],[]) if p.is_file() else []
     return self.send(200,{'records':records})
    its,bad=history(p) if p.exists() else (stored_history(id),0)
    if not its:return self.send(404,{'error':'没有可读取的会话内容'})
    q=parse_qs(u.query)
    if 'item' in q and q.get('raw')==['1']:
     index=int(q['item'][0])
     if not 0<=index<len(its) or its[index].get('kind')!='tool':raise ValueError('工具记录不存在')
     return self.send(200,{'records':raw_tool_records(its[index],p)})
    payload=page_payload(its,q)
    if 'item' not in q and 'view' not in q:payload.update(thread=r,skipped=bad,turns=stored_turns(id),relations=relations(id),history_warning=history_warning())
    return self.send(200,payload)
   if u.path=='/api/local-file':
    q=parse_qs(u.query);id=q.get('id',[''])[0];r=next((x for x in rows() if x['id']==id),None)
    if not r:return self.send(404,{'error':'会话不存在'})
    rollout=resolve_rollout(r['rollout_path']).resolve()
    if not rollout.is_relative_to(HOME.resolve()):return self.send(403,{'error':'记录位于数据目录之外'})
    items=history(rollout)[0] if rollout.is_file() else stored_history(id)
    allowed=referenced_files(items)
    raw=re.sub(r':\d+(?::\d+)?$','',q.get('path',[''])[0]);p=Path(raw).resolve()
    if str(p) not in allowed:return self.send(403,{'error':'仅允许访问此会话明确引用的文件'})
    if not p.exists():return self.send(404,{'error':'原文件已移动或不存在'})
    if p.is_dir():
     children=[Path(v) for v in sorted(allowed) if Path(v).is_relative_to(p) and Path(v)!=p]
     links=''.join('<li><a href="/api/local-file?'+html.escape(urlencode({'id':id,'path':str(v)}))+'">'+html.escape(str(v.relative_to(p)))+'</a></li>' for v in children)
     page='<meta charset="utf-8"><title>会话引用的目录</title><h2>'+html.escape(p.name)+'</h2><p>'+html.escape(str(p))+'</p><p>仅列出这段会话明确引用的文件。</p><ul>'+links+'</ul>'
     return self.send(200,page.encode(),'text/html; charset=utf-8')
    if not p.is_file() or p.stat().st_size>32*1024*1024:return self.send(413,{'error':'文件过大或不是普通文件'})
    mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.avif':'image/avif','.txt':'text/plain; charset=utf-8','.md':'text/plain; charset=utf-8','.json':'text/plain; charset=utf-8','.py':'text/plain; charset=utf-8','.js':'text/plain; charset=utf-8','.html':'text/plain; charset=utf-8'}.get(p.suffix.lower(),'application/octet-stream')
    return self.send(200,p.read_bytes(),mime)
   files={'/vendor/nouislider.min.js':('vendor/nouislider.min.js','text/javascript; charset=utf-8'),'/vendor/nouislider.min.css':('vendor/nouislider.min.css','text/css; charset=utf-8'),'/vendor/schema-viewer.js':('vendor/schema-viewer.js','text/javascript; charset=utf-8'),'/vendor/schema-viewer.css':('vendor/schema-viewer.css','text/css; charset=utf-8'),'/vendor/highlight.min.js':('vendor/highlight.min.js','text/javascript; charset=utf-8'),'/assets/microscope.png':('assets/microscope.png','image/png'),'/vendor/lucide-icons.js':('vendor/lucide-icons.js','text/javascript; charset=utf-8'),'/vendor/markdown-it.min.js':('vendor/markdown-it.min.js','text/javascript; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/token-usage.js':('token-usage.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
   if u.path not in files:return self.send(404,{'error':'Not found'})
   file,mime=files[u.path];return self.send(200,(ROOT/'designs/browser'/file).read_bytes(),mime)
  except DatabaseUnavailable as e:return self.send(503,{'error':str(e)})
  except ValueError as e:return self.send(400,{'error':str(e)})
  except FileNotFoundError:return self.send(404,{'error':'会话记录文件不可用'})
  except Exception as e:return self.send(500,{'error':str(e)})
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--port',type=int,default=4318);args=a.parse_args();print(f'http://localhost:{args.port}',flush=True);ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
