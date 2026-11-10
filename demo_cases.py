"""Invented rollout records for the offline case gallery. Nothing here runs a logged command."""
import base64
import json
import re
import struct
import zlib


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def record(kind, **fields):
    return dict(type=kind, payload=fields)


def response(kind, **fields):
    return record('response_item', type=kind, **fields)


def native(item_type, **fields):
    return record('event_msg', type='item_completed', item=dict(type=item_type, **fields))


def message(text):
    return response('message', role='user', content=[dict(type='input_text', text=text)])


def picture():
    # Tiny original colour chart; the demo never needs the local-file endpoint.
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    rows = b''.join(b'\0' + b''.join(bytes((20+x, 65+y*2, 170 if x//24%2 else 110))
                                     for x in range(144)) for y in range(64))
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>2I5B',144,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    return dict(type='input_image',image_url='data:image/png;base64,'+base64.b64encode(png).decode())


DONE = 'Script completed\nWall time 0.1 seconds\nOutput:\n'
CELL = 'Script running with cell ID 32\nWall time 0.1 seconds\nOutput:\n'
FAIL = 'Script failed\nWall time 0.1 seconds\nOutput:\n'
IMG = picture()


def returned(id, *blocks):
    return response('custom_tool_call_output', call_id=id, output=[
        dict(type='input_text',text=x) if isinstance(x,str) else x for x in blocks])


def script(src, *blocks, events=(), id='a'):
    return [response('custom_tool_call', name='exec', input=src, call_id=id), *events,
            *([returned(id,*blocks)] if blocks else [])]


def direct(name, args, result=None, id='a', namespace=None):
    call=response('function_call',name=name,arguments=dump(args),call_id=id)
    if namespace:call['payload']['namespace']=namespace
    return [call,*([response('function_call_output',call_id=id,output=result if isinstance(result,str) else dump(result))]
                   if result is not None else [])]


def invocation(name,args):
    return 'tools.'+name+'('+dump(args)+')'


def wrapped(name,args,result,id='a'):
    return script('text(await '+invocation(name,args)+')', DONE, dump(result), id=id)


def command(cmd, actions, output, code=0):
    result=dict(output=output,exit_code=code,wall_time_seconds=0.1)
    ev=native('CommandExecution',command=cmd,parsed_cmd=actions,exit_code=code,
              aggregated_output=output,status='completed' if not code else 'failed')
    return script('text(await '+invocation('exec_command',dict(cmd=cmd))+')',DONE,dump(result),events=[ev])


CASES = {}


def case(id,group,title,guide,source,events):
    names=set()
    for event in events:
        payload=event['payload']
        if 'name' in payload:
            names.add('.'.join(filter(None,[payload.get('namespace'),payload['name']])))
        names.update(re.findall(r'\btools\.(\w+)',payload.get('input','')))
        if 'item' in payload:
            item=payload['item']
            names.add(item['type'])
            if item.get('server'):names.add(item['server']+'.'+item['tool'])
    CASES[id]=(dict(id=id,title=title,group=group,guide=guide,evidence=source,tools=sorted(names)),events)


X='exec · 编排与结果'; F='命令、文件与终端'; B='其他内建工具'; M='外部 MCP · 通用展示'; E='补充边界'
reads=[invocation('exec_command',dict(cmd='cat '+p)) for p in ('intro.md','theme.css','one.txt two.txt')]
case('parallel-image',X,'三次读取和一张图片','展开四个动作：前三项返回文本，最后一项返回色卡。第三条命令读取两个文件，只产生一份输出。',
     '合成协议案例',script('const r=await Promise.all(['+','.join(reads+[invocation('view_image',dict(path='palette.png'))])+']);text(JSON.stringify(r.slice(0,3)));image(r[3].image_url)',DONE,dump([dict(exit_code=0,output=v) for v in ('Project brief','color: teal','one\ntwo')]),IMG))
case('sequential',X,'两条串行命令，只打印第二个结果','第二步的目录来自第一步。只有打包结果被打印，不能据此给第一步填退出码。',
     '合成协议案例',script('const a=await tools.exec_command({cmd:"mktemp -d"});const b=await tools.exec_command({cmd:"tar -cf "+a.output.trim()+"/site.tar site"});text(b)',DONE,dump(dict(output='created site.tar',exit_code=0))))
# Synthetic fixture: a long static heredoc, a native result and a
# forwarded envelope with transport fields. These strings are never executed.
long_python = """python3 - <<'PY'
import unittest


def compact_title(value):
    lines = value.strip().splitlines()
    if len(lines) > 1:
        return "Run script"
    return value.strip()


def format_output(value):
    return value.rstrip()


class PresentationTests(unittest.TestCase):
    def test_multiline(self):
        source = "first line" + chr(10) + "second line"
        self.assertEqual(compact_title(source), "Run script")

    def test_short_command(self):
        self.assertEqual(compact_title("git status"), "git status")

    def test_output(self):
        self.assertEqual(format_output("OK  "), "OK")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        PresentationTests
    )
    runner = unittest.TextTestRunner(verbosity=1)
    runner.run(suite)
PY"""
long_output = "...\nRan 3 tests in 0.012s\n\nOK\n"
long_source = "text(await tools.exec_command({cmd:`"+long_python+"`}))"
case('long-script',X,'长脚本与短输出','编排源码仍在最前。标题统一为运行命令；命令源码默认折叠，可复制全文。短输出只展示一次，附加的原始回包字段折叠保留。',
     '合成长命令与短输出案例',script(long_source,DONE,dump(dict(chunk_id='demo-chunk',wall_time_seconds=1.951,exit_code=0,original_token_count=25,output=long_output)),
     events=[native('CommandExecution',command=long_python,parsed_cmd=[dict(type='unknown',cmd=long_python)],aggregated_output=long_output,exit_code=0,duration_ms=1951,status='completed')]))
case('script-languages',E,'不同语言的脚本与短命令','Python、JavaScript 和 Shell 多行命令、python3 check.py 与 git status 都显示运行命令，仅源码预览方式不同。最后一条脚本显示实际非零退出码。',None,
     direct('exec_command',dict(cmd="python3 - <<'PY'\nprint('ready')\nPY"),dict(output='ready',exit_code=0),id='py')+
     wrapped('exec_command',dict(cmd="node <<'JS'\nconst state = 'ready';\nconsole.log(state);\nJS"),dict(output='ready',exit_code=0,wall_time_seconds=.25),id='js')+
     direct('exec_command',dict(cmd='python3 check.py'),dict(output='checks passed',exit_code=0),id='file')+
     wrapped('exec_command',dict(cmd='git status --short'),dict(output=' M example.txt',exit_code=0),id='short')+
     wrapped('exec_command',dict(cmd="printf 'checking\\n'\nexit 2"),dict(output='checking',exit_code=2),id='sh'))
case('late-command',X,'命令事件晚于 exec 回包','先记录 exec 请求和回包，再记录 CommandExecution。页面合并成同一次调用；JSON 日志原文保留三条记录的顺序。',
     '本轮关联排查：回包先于原生命令事件（合成重建）',
     wrapped('exec_command',dict(cmd='printf ready'),dict(output='ready',exit_code=0))+
     [native('CommandExecution',command='printf ready',aggregated_output='ready',exit_code=0,status='completed',id='late-result')])
case('unlinked-command',E,'无法关联的独立执行记录','前面的调用执行另一条命令。独立事件保留实际输出，注明未找到关联调用；不把事件类型当作工具名。',None,
     wrapped('exec_command',dict(cmd='printf first'),dict(output='first',exit_code=0))+
     [native('CommandExecution',command='printf orphan',aggregated_output='orphan',exit_code=0,status='completed',id='orphan-result')])
case('ambiguous-late-command',E,'重复命令，晚到事件不猜归属','同一轮有两次相同命令。晚到事件没有外层调用 ID，保持独立；不能因为第二次更近就合并。',None,
     wrapped('exec_command',dict(cmd='printf ready'),dict(output='ready',exit_code=0),id='first')+
     wrapped('exec_command',dict(cmd='printf ready'),dict(output='ready',exit_code=0),id='second')+
     [native('CommandExecution',command='printf ready',aggregated_output='ready',exit_code=0,status='completed',id='ambiguous-result')])
case('partial-arguments',X,'动态工作目录与固定命令','workdir 来自 load，仍保留固定 cmd。原生事件在回包之前，归入原调用；页面注明未静态解析的字段，不编造工作目录。',
     '合成协议案例',
     script('text(await tools.exec_command({workdir:load("repo"),cmd:"printf ready"}))',DONE,dump(dict(output='ready',exit_code=0)),
            events=[native('CommandExecution',command='printf ready',cwd='/demo/project',aggregated_output='ready',exit_code=0,status='completed')]))
process_source='const repo="/demo/project";store("repo",repo);text(await Promise.allSettled([tools.exec_command({cmd:`printf "${repo}"`}),tools.exec_command({cmd:"printf other"})]))'
case('process-origin',X,'进程编号补足动态命令归属','第一项命令参数含模板插值，保持未知。启动回包的 session_id 与晚到事件的 process_id 相同，归入第一项；第二项不会被并入第一项，启动回包仍可查。',
     '合成协议案例',
     script(process_source,DONE,dump([dict(status='fulfilled',value=dict(session_id=72,output='starting')),dict(status='fulfilled',value=dict(exit_code=0,output='other'))]))+
     [native('CommandExecution',command='printf "/demo/project"',process_id='72',aggregated_output='/demo/project',exit_code=0,status='completed')])
case('unicode-command',X,'Unicode 转义命令','源码里的 Unicode 转义按字符串规则解码，和晚到的实际命令逐字符匹配，不执行源码。',
     '合成协议案例',
     script(r'text(await tools.exec_command({cmd:`printf "hello\u0020world"`}))',DONE,dump(dict(output='hello world',exit_code=0)))+
     [native('CommandExecution',command='printf "hello world"',aggregated_output='hello world',exit_code=0,status='completed')])
case('process-reused',E,'进程编号复用，不猜归属','两条启动回包记录相同的 session_id。即使事件带相同 process_id，也不能按最近调用合并。',None,
     script('text(await tools.exec_command({cmd:firstCommand}))',DONE,dump(dict(session_id=72,output='first started')),id='first')+
     script('text(await tools.exec_command({cmd:secondCommand}))',DONE,dump(dict(session_id=72,output='second started')),id='second')+
     [native('CommandExecution',command='printf ready',process_id='72',aggregated_output='ready',exit_code=0,status='completed')])
case('directory',X,'查询工具目录','输出是候选工具名，名字出现在目录里不代表调用发生。',
     '合成协议案例',script('const names=ALL_TOOLS.filter(x=>x.name.includes("image")).map(x=>x.name);text(names)',DONE,dump(['view_image','image_gen__imagegen'])))
case('script-error',X,'编排脚本报错','先看语法错误，再打开编排源码。没有终端进程退出码。','合成协议案例',script('text(await tools.exec_command({',FAIL,'SyntaxError: Unexpected end of input'))
case('missing',X,'只有请求，没有回包','缺失结果不代表仍在运行，也不代表失败。','合成协议案例',script('text(await tools.exec_command({cmd:"pwd"}))'))
case('aborted',X,'请求被中断','查看实际中断文字；不能由此推断被调用的命令已退出。','合成协议案例',script('text(await tools.exec_command({cmd:"make preview"}))','aborted by user'))
case('output-only',E,'脚本只打印 stdout','看到文本，但没有记录退出码。',None,script('const r=await tools.exec_command({cmd:"cat note.txt"});text(r.output)',DONE,'Field notes'))
gen=script('await tools.image_gen__imagegen({prompt:"draw a colour chart"})',CELL)
wait=lambda id: direct('wait',dict(cell_id='32'),id=id)
case('cell-image',X,'跨 cell 等待图片','从等待行跳回发起行，再查看实际返回的图片；中间的进度不覆盖先前回包。',
     '合成协议案例',gen+[returned('a','progress: preparing chart')]+wait('b')+[returned('b',CELL)]+wait('c')+[returned('c',DONE,IMG)])
case('cell-stop',X,'请求终止，实际收到完成回包','展开 wait：请求含 terminate，返回头却是 Script completed。两处分别记录请求和结果。','合成协议案例',
     script('text(await tools.exec_command({cmd:"make preview"}))',CELL)+
     direct('wait',dict(cell_id='32',terminate=True),id='b')+
     [response('function_call_output',call_id='b',output=[dict(type='input_text',text=DONE),dict(type='input_text',text='Preview finished')])])
case('long-read',F,'读取指定行，继续展开','查看请求行号以及 24 行之后的内容。文本和行数均为合成。',
     '合成协议案例',command("sed -n '10,60p' notes.txt",[dict(type='read',path='notes.txt',cmd="sed -n '10,60p' notes.txt")],'\n'.join('Entry '+str(i) for i in range(10,61))))
case('shared-read',F,'一次命令读取多个文件','分别打开两个读取操作，核对两处均说明输出是合并的。','合成协议案例',
     command('cat one.md two.md',[dict(type='read',path=p,cmd='cat '+p) for p in ('one.md','two.md')],'First paragraph\nSecond paragraph'))
case('list-files',F,'列出目录','文件名来自 ls 的实际返回。','合成协议案例',command('ls docs',[dict(type='list_files',path='docs',cmd='ls docs')],'intro.md\nnotes.md'))
for id,title,path,stdout,code,ref in [
    ('search-hits','搜索命中：文件和行号','src','src/a.css:3:color: teal\nsrc/b.css:8:color: blue',0,'合成协议案例'),
    ('search-empty','搜索无匹配','src','',1,'合成协议案例'),
    ('search-error','搜索失败：目录不存在','missing','rg: missing: No such file or directory',2,'合成协议案例')]:
    cmd='rg -n color '+path
    case(id,F,title,'比较匹配行、空输出和错误；rg 的退出码 1 和 2 含义不同。',ref,command(cmd,[dict(type='search',query='color',path=path,cmd=cmd)],stdout,code))
patch='*** Begin Patch\n*** Add File: intro.md\n+Welcome\n*** Update File: old.md\n*** Move to: notes.md\n@@\n-before\n+after\n*** Delete File: draft.md\n*** End Patch'
case('patch',F,'同一补丁：新增、修改并移动、删除','逐文件展开 diff；实际变更来自 FileChange，即使外层回包只有空对象。',
     '合成协议案例',
     script('text(await tools.apply_patch('+dump(patch)+'))',DONE,'{}',events=[native('FileChange',status='completed',changes={
         'intro.md':dict(type='add',content='Welcome\n'),'old.md':dict(type='update',move_path='notes.md',unified_diff='@@ -1 +1 @@\n-before\n+after'),'draft.md':dict(type='delete',content='Draft\n')})]))
case('patch-error',F,'补丁未能应用','有尝试写入的 diff，也有失败原因，没有文件已修改的证据。','合成协议案例',
     script('text(await tools.apply_patch('+dump(patch)+'))',DONE,'Failed to write file old.md',events=[native('FileChange',status='failed',changes={'old.md':dict(type='update',unified_diff='@@ -1 +1 @@\n-before\n+after')})]))
case('terminal',F,'终端会话：轮询、输入、中断','依次查看 session 17 的空输入、yes 和 Ctrl-C；退出码只在最后一次返回中出现。','合成协议案例',
     wrapped('exec_command',dict(cmd='make preview'),dict(output='waiting',session_id=17))+
     sum([wrapped('write_stdin',dict(session_id=17,chars=chars),value,id) for chars,value,id in [
         ('',dict(output='Continue?',session_id=17),'b'),('yes\n',dict(output='working',session_id=17),'c'),('\x03',dict(output='^C',exit_code=130),'d')]],[]))
polls=[invocation('write_stdin',dict(session_id=n,chars='')) for n in (17,18,19)]
case('mixed-terminal',X,'轮询三个终端并运行诊断','对照三个会话和一条新命令；其中一项没有可继续读取的会话。',
     '合成协议案例',script('text(await Promise.all(['+','.join(polls+[invocation('exec_command',dict(cmd='pwd'))])+']))',DONE,
     dump([dict(session_id=17,output='building'),dict(output='unknown session 18'),dict(exit_code=0,output='done'),dict(exit_code=0,output='demo')])))
case('web',B,'网页：搜索、打开、查找和点击','复合查询使用示例域名；未能逐项归属的内容保留为共享结果。',
     '合成协议案例',
     direct('run',dict(search_query=[dict(q='field notes')]),'Field notes (https://example.org/notes)',namespace='web')+
     wrapped('web__run',dict(open=[dict(ref_id='source0')],find=[dict(ref_id='source0',pattern='notes')],click=[dict(ref_id='source0',id=1)]),dict(text='Example excerpt: field notes.'),'b'))
case('view-error',E,'图片路径不可读','路径保留，错误保留，不展示替代图片。',None,wrapped('view_image',dict(path='missing.png'),dict(error='File not found')))
case('generation-error',B,'参考图编辑失败','查看参考图参数；失败没有具体原因时，不为它补写原因。','合成协议案例',
     wrapped('image_gen__imagegen',dict(prompt='Repaint chart',referenced_image_paths=['chart.png']),dict(status='failed',result=None,savedPath=None)))
case('plan',B,'更新计划的前后两次记录','同一个步骤从进行中变为完成；每次工具详情保留当时的清单。','合成协议案例',
     sum([direct('update_plan',dict(plan=[dict(step='检查目录',status=s),dict(step='编写说明',status=t)]),'Plan updated',i) for i,s,t in [('a','in_progress','pending'),('b','completed','in_progress')]],[]))
case('goal',B,'目标：创建、查看、标记完成','先看已有目标造成的创建冲突，再看查询快照和更新回执。','合成协议案例',
     wrapped('create_goal',dict(objective='整理示例'),dict(error='An unfinished goal already exists'))+wrapped('get_goal',{},dict(status='active',objective='整理示例'),'b')+wrapped('update_goal',dict(status='complete'),dict(status='complete'),'c'))
case('questions',B,'同步已回答，异步只确认提交','对照选项、回答和 accepted；后者不代表用户选过某个答案。','合成协议案例',
     direct('request_user_input',dict(questions=[dict(id='format',header='格式',question='输出格式？',options=[dict(label='表格',description='便于比较'),dict(label='列表',description='便于阅读')])]),dict(answers=dict(format=dict(answers=['表格']))))+
     direct('request_user_input_async',dict(questions=[dict(title='选哪种配色？',options=['青色','蓝色'])]),dict(accepted=True),'b'))
case('clock',B,'读取时间、等待完成、等待被打断','比较请求时长和真实经过的时长（此处数值为合成）。','合成协议案例',
     wrapped('clock__curr_time',{},dict(current_time='2030-01-01 00:00:00 UTC'))+direct('sleep',dict(duration_ms=15000),dict(elapsed_ms=15000),'b','clock')+
     direct('sleep',dict(duration_ms=15000),dict(elapsed_ms=3000,interrupted=True),'c','clock'))
case('agents',B,'子代理：派发、通信、查看、等待和中断','按顺序翻看六种操作，等待超时和中断回执各自独立。','合成协议案例',
     sum([direct(n,args,out,str(i),'collaboration') for i,(n,args,out) in enumerate([
         ('spawn_agent',dict(task_name='review',message='检查示例'),dict(task_name='/root/review')),
         ('followup_task',dict(target='review',message='补充目录'),dict(queued=True)),
         ('send_message',dict(target='review',message='已准备好'),''),('list_agents',{},dict(agents=['review'])),
         ('wait_agent',dict(timeout_ms=10000),dict(timed_out=True)),('interrupt_agent',dict(target='review'),dict(previous_status='running'))])],[]))
case('mcp-forbidden',M,'外层脚本完成，服务返回 403','打开 GitHub 操作，对照脚本状态和服务错误；没有创建真实 PR。','合成协议案例',
     wrapped('mcp__codex_apps__github_create_pull_request',dict(title='Sample change'),dict(isError=True,content=[dict(type='text',text='403 Forbidden')])))
case('mcp-pending',M,'调用完成，服务仍为 pending','原生 MCP 事件与服务的业务状态分属两层。','合成协议案例',
     [native('McpToolCall',server='demo-deploy',tool='inspect',status='completed',arguments=dict(id='preview'),result=dict(content=[dict(type='text',text='{"status":"pending"}')]))])
case('mcp-image',M,'外部工具返回文字和截图','打开图文混合的回包；色卡替代真实截图。','合成协议案例',
     script('const r=await tools.mcp__cua_repl__js({code:"snapshot"});text("Preview");image(r.content[0])',DONE,'Preview',IMG))
case('mcp-empty',E,'空数组、空返回和缺失回包','三条样例只改变结果形态；不能把缺失的回包渲染成“没有数据”。',None,
     direct('mcp__sample__list',{},[])+direct('mcp__sample__list',{},'','b')+direct('mcp__sample__list',{},None,'c'))
case('ambiguous',E,'重排结果或部分 Promise 被拒绝','即使调用数和返回数一样，也不能把共享输出强行分配到操作。',
     None,script('const r=await Promise.all(['+','.join(reads[:2])+']);text(r.reverse())',DONE,dump([dict(output='second'),dict(output='first')]))+
     script('text(await Promise.allSettled(['+','.join(reads[:2])+']))',DONE,dump([dict(status='fulfilled',value=dict(output='first')),dict(status='rejected',reason='timeout')]),id='b'))
case('unknown',E,'动态工具名与纯计算','两种没有固定工具名的脚本；只有明确的输出可作证。',None,
     script('const n="lookup";text(await tools[n]({}))',DONE,'demo result')+script('text(6*7)',DONE,'42',id='b'))
case('paged-cell',E,'等待与发起行分属两页','等待行在默认的最近八轮。点击来源可加载较早一页，返回后仍能查看图片。',None,
     gen+[event for n in range(1,10) for event in (record('turn_context',turn_id='turn-'+str(n)),message('中间轮次 '+str(n)))]+wait('b')+[returned('b',DONE,IMG)])


# Direct (older) protocols use different envelopes from their JS-wrapped counterparts.
case('direct-shell',F,'直接终端调用：启动与取回','观察没有 JS 外层的命令与续接。保留返回中的替代字符，不尝试修复未知文字。',
     '合成协议案例',
     direct('exec_command',dict(cmd='make preview'),dict(output='started',session_id=12))+
     direct('write_stdin',dict(session_id=12,chars=''),dict(exit_code=0,output='result: �'),'b'))
case('direct-patch',F,'直接提交补丁','自由格式请求里是一份补丁，原生事件中才有可核对的文件变更。','合成协议案例',
     [response('custom_tool_call',name='apply_patch',input='*** Begin Patch\n*** Add File: index.md\n+Contents\n*** End Patch',call_id='a'),
      native('FileChange',status='completed',changes={'index.md':dict(type='add',content='Contents\n')}),
      returned('a','Success. Updated the following files:\nA index.md')])
case('goal-direct',B,'直接更新目标','检查预算字段；完成操作与实际交付是两条不同的证据。','合成协议案例',
     direct('update_goal',dict(status='complete'),dict(status='complete',tokens_used=420,elapsed_seconds=55)))
case('agents-errors',B,'代理派发受限、目标不存在','一条是容量错误，一条是目标错误；均不能当作已送达。','合成协议案例',
     direct('followup_task',dict(target='helper',message='检查'), 'agent limit reached',namespace='collaboration')+
     direct('send_message',dict(target='absent',message='检查'),'agent not found','b','collaboration'))
case('web-media',B,'网页图片查询与 PDF 截页','搜索结果保留来源；PDF 请求保留页号，示例页图来自合成色卡。',
     '合成协议案例',
     wrapped('web__run',dict(image_query=[dict(q='colour chart')]),dict(results=[dict(title='Colour chart',url='https://example.org/chart')]))+
     script('const r=await tools.web__run({screenshot:[{ref_id:"doc0",pageno:1}]});image(r.content[0])',DONE,IMG,id='b'))
case('direct-cua',M,'计算机操作：完成摘要与环境重置','两次都是直接 MCP 请求；完成摘要和重置回执有不同含义。',
     '合成协议案例',
     direct('js',dict(completion_summary='检查了图表'),'Completed',namespace='mcp__cua_repl')+
     direct('js_reset',{},'JS kernel reset','b','mcp__cua_repl'))
case('desktop-mcp',M,'桌面服务：排队与结构化依赖','queued 仅表示已请求打开。第二条展示工作区依赖，不需要访问本机文件。',
     '合成协议案例',
     direct('open_in_codex',dict(path='demo.md'),dict(status='queued'),namespace='mcp__codex_app')+
     direct('load_workspace_dependencies',{},dict(runtime='python',libraries=['example']),'b','mcp__codex_app'))
case('orphan',X,'单独出现的工具返回','原始记录只有结果，不根据相邻动作补造请求。','合成协议案例',
     [response('function_call_output',call_id='unpaired',output='heartbeat')])
case('empty-exit',E,'终端成功退出但没有输出','这次明确记录了退出码 0；空 stdout 是有效的结果。',None,
     wrapped('exec_command',dict(cmd='true'),dict(exit_code=0,output='')))
case('cell-unresolved',E,'仍在运行和来源不明的等待','cell 32 未收到最终结果；另一个 cell 的回包不能补给它。',None,
     gen+direct('wait',dict(cell_id='99'),'unknown cell 99','b'))
case('invalid-name',X,'尝试调用不存在的工具','源码保留历史拼写；TypeError 是编排错误，不是补丁已经应用。','合成协议案例',
     script('text(await tools.apply_patch_patch("*** Begin Patch"))',FAIL,'TypeError: tools.apply_patch_patch is not a function'))
case('conditional',X,'条件分支中的两个工具','编排里写到了两个工具，只有一份返回；不能断言两个分支都执行了。',
     '合成协议案例',script('if(flag){text(await tools.exec_command({cmd:"cat intro.md"}))}else{text(await tools.exec_command({cmd:"pwd"}))}',DONE,'project notes'))
case('native-web',B,'原生网页事件提供来源','点开查看来源标题、地址和摘录；这些字段来自网页事件。',
     '合成协议案例',script('text(await tools.web__run({search_query:[{q:"field notes"}]}))',DONE,'One source',events=[
         native('Extension',kind='web.search',action=dict(type='search',queries=['field notes']),results=[
             dict(type='text_result',title='Field notes',domain='example.org',url='https://example.org/notes',snippet='A synthetic excerpt.',ref_id='source0')])]))
case('native-image',B,'只有原生图片路径','只有路径，没有图块；不应显示一张猜测的图片。','合成协议案例',
     [native('ImageView',path='palette.png')])


case('mcp-blocks',E,'MCP 内容块：图片、音频、资源和未知类型','按原序查看内容。第一张是有效色卡，第二张损坏。资源 URI 只显示文字。',None,
     [native('McpToolCall',server='demo',tool='inspect',status='completed',arguments={},
             result=dict(content=[
                 dict(type='text',text='Sample palette'),
                 dict(type='image',mimeType='image/png',data=IMG['image_url'].split(',',1)[1]),
                 dict(type='image',mimeType='image/png',data='YWJj'),
                 dict(type='audio',mimeType='audio/wav',data='YWJj'),
                 dict(type='resource',resource=dict(uri='demo://notes',mimeType='text/plain',text='Example note')),
                 dict(type='resource_link',uri='file:///demo/private.txt',name='notes'),
                 dict(type='sample_extension',message='<tag>')],
                 structuredContent=dict(status='pending')))])
case('mcp-protected',M,'MCP 结构化字段：凭据遮盖','展开结果及 JSON：状态和仓库名可读，凭据字段及其回显统一遮盖。','合成协议案例',
     [native('McpToolCall',server='demo',tool='credential',status='completed',arguments=dict(project='example'),
             result=dict(content=[dict(type='text',text='issued demo-fixture-value')],
                         structuredContent=dict(repository='example',token='demo-fixture-value')))])
case('mcp-status',E,'MCP 快照：进行中、完成无结果、失败无详情','三个状态均没有结果内容；用上一次记录时的状态分别表达。',None,
     [native('McpToolCall',server='demo',tool='observe',id='r'+str(i),status=status,arguments={},result=None)
      for i,status in enumerate(['inProgress','completed','failed'])])

def wait_return(id,*blocks):
    return response('function_call_output',call_id=id,output=[dict(type='input_text',text=b) for b in blocks])


case('cell-terminated',E,'终止请求收到已终止回包','Script terminated 确认编排结束；终止前的输出仍保留在等待行。',None,
     script('text(await tools.exec_command({cmd:"make preview"}))',CELL)+
     direct('wait',dict(cell_id='32',terminate=True),id='b')+
     [wait_return('b',DONE.replace('completed','terminated'),'Partial preview')])
case('wait-interrupted',X,'用户中断这一次等待','打开等待回包，区分用户中断等待和终止后台运行单元。','合成协议案例',
     script('text(await tools.exec_command({cmd:"make preview"}))',CELL)+
     direct('wait',dict(cell_id='32'),'aborted by user after 26.0s','b'))
case('cell-reuse',E,'运行单元编号再次出现','第一个 cell 32 已完成。后面两个发起调用同时占用编号 32，最后的等待没有唯一来源。',None,
     script('text(await tools.exec_command({cmd:"make first"}))',CELL)+wait('b')+[wait_return('b',DONE,'First result')]+
     script('text(await tools.exec_command({cmd:"make second"}))',CELL,id='c')+
     script('text(await tools.exec_command({cmd:"make third"}))',CELL,id='d')+wait('e')+[wait_return('e',DONE,'Unassigned result')])
case('quiet-poll',E,'两次轮询都没有新输出','第一次还带会话号，第二次带退出码 0。静默轮询仍可查看原始记录。',None,
     wrapped('write_stdin',dict(session_id=17,chars=''),dict(session_id=17,output=''))+
     direct('write_stdin',dict(session_id=17),'Wall time: 0.001 seconds\nProcess exited with code 0\nOutput:\n','b'))

case('native-web-legacy',B,'旧式网页事件：来源与页内查找','打开调用可看到原生 WebSearch 返回的来源，页内查找缺少 URL 时只显示关键词。',
     '合成协议案例',
     script('text(await tools.web__run({search_query:[{q:"field notebook"}]}))',DONE,'One source',
            events=[native('WebSearch',id='web-a',query='field notebook',action=dict(type='search',query='field notebook'),
                           results=[dict(type='text_result',title='Notes index',url='https://example.org/notes',snippet='A synthetic source.')])])+
     [native('WebSearch',id='web-b',action=dict(type='find_in_page',pattern='notebook'),results=[])])
case('native-dynamic',X,'动态工具失败，另一条命令有输出','工具身份和参数匹配后，动态失败与随后成功的命令归到各自操作。外层只打印共享文字。',
     '合成协议案例',
     script('await tools.codex_app__read_thread_terminal({});text((await tools.exec_command({cmd:"pwd"})).output)',
            DONE,'demo',events=[
                native('DynamicToolCall',id='dynamic',namespace='codex_app',tool='read_thread_terminal',arguments={},
                       status='failed',success=False,duration=dict(secs=0,nanos=9000000),
                       content_items=[dict(type='input_text',text='No terminal for this example')]),
                native('CommandExecution',id='shell',command='pwd',status='completed',exit_code=0,aggregated_output='demo',
                       parsed_cmd=[dict(type='unknown',cmd='pwd')])]))
case('native-generation',X,'生图原生事件在 wait 中返回','展开 wait 查看图片、修订提示词和保存路径。唯一相同的返回图块把原生事件关联到等待调用。',
     '合成协议案例',
     gen+wait('b')+[native('Extension',kind='image_gen.generation',id='generation',status='completed',result=IMG['image_url'].split(',',1)[1],
                          revisedPrompt='Draw a colour chart',savedPath='palette.png',transparentBackground=False),
                   returned('b',DONE,IMG)])
case('native-agents',B,'代理请求、活动与等待快照','启动和等待事件使用各自请求的 ID；稍后的完成活动独立显示。等待工具的快照与子任务最终状态分开。',
     '合成协议案例',
     direct('spawn_agent',dict(task_name='review',message='检查示例'),id='a',namespace='collaboration')+
     [native('SubAgentActivity',id='a',kind='started',agent_thread_id='sample-agent',agent_path='/root/review'),
      response('function_call_output',call_id='a',output='{"task_name":"/root/review"}')]+
     direct('wait_agent',dict(timeout_ms=10000),id='b',namespace='collaboration')+
     [native('CollabAgentToolCall',id='b',tool='wait',status='completed',receiver_thread_ids=['sample-agent'],
             agents_states={'sample-agent':dict(status='running')}),
      response('function_call_output',call_id='b',output='{"timed_out":true}'),
      native('SubAgentActivity',id='finish',kind='completed',agent_thread_id='sample-agent',agent_path='/root/review')])

case('shell-forms',F,'只有命令文本：读取、列目录与未知管道','对照尾部读取、列文件和含未知程序的管道。只有能确认的命令形态会得到专用标题。',
     '合成协议案例',
     wrapped('exec_command',dict(cmd='tail -n 2 guide.md'),dict(exit_code=0,output='Appendix A\nAppendix B'))+
     wrapped('exec_command',dict(cmd='rg --files docs'),dict(exit_code=0,output='docs/guide.md'),'b')+
     wrapped('exec_command',dict(cmd='git ls-files docs'),dict(exit_code=0,output='docs/guide.md'),'c')+
     wrapped('exec_command',dict(cmd='rg --files docs | head -n 2'),dict(exit_code=0,output='docs/intro.md\ndocs/guide.md'),'d')+
     wrapped('exec_command',dict(cmd='rg --files | custom_filter'),dict(exit_code=127,output='custom_filter: command not found'),'e'))

# Database rows retain commandActions and camelCase status fields until the normal DB projection.
db_title='数据库回放：读取与列目录共用输出'
db_guide='一条命令记录含 read 和 listFiles 两个动作。展开看共同输出，点 JSON → 日志原文，核对数据库字段。'
CASES['database-actions']=(
    dict(id='database-actions',title=db_title,group=F,guide=db_guide,evidence='主历史库 #351',
         tools=['commandExecution','listFiles','read'],record_format='database'),
    [dict(type='userMessage',text=db_guide),
     dict(type='commandExecution',id='combined',command="sed -n '1,2p' notes.md && find docs -type f",
          commandActions=[dict(type='read',command="sed -n '1,2p' notes.md",path='notes.md',name='notes.md'),
                          dict(type='listFiles',command='find docs -type f',path='docs')],
          aggregatedOutput='First note\nSecond note\ndocs/guide.md',exitCode=0,status='completed',
          source='unifiedExecStartup',durationMs=120)])

case('exec-audio',E,'编排依次返回文字、音频、文字','音频占位保留返回顺序和媒体格式。',None,
     script('text("start");audio(makeClip());text("finished")',DONE,'start',
            dict(type='input_audio',audio_url='data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA=='),'finished'))


def catalog():
    return [meta for meta,_ in CASES.values()]


def lines(id):
    meta,events=CASES[id]
    if meta.get('record_format')=='database':return [dump(event) for event in events]
    events=[record('turn_context',turn_id='turn-0'),message(meta['guide']),*events]
    return [dump(dict(timestamp='2030-01-01T00:00:%02dZ'%i,**ev)) for i,ev in enumerate(events)]
