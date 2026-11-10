import json
import unittest

import server
from test_tool_operations import call, completed, event, parse


HEADER = 'Script completed\nWall time 0.1 seconds\nOutput:\n'
CELL = 'Script running with cell ID 32\nWall time 0.1 seconds\nOutput:\n'
PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9kAAAAASUVORK5CYII='


def result(identifier, parts):
    return event('response_item',dict(type='custom_tool_call_output',call_id=identifier,
        output=[dict(type='input_text',text=p) if isinstance(p,str) else p for p in parts]))


def batch():
    cmds=[f"tools.exec_command({{cmd:'cat {name}.js'}})" for name in ('one','two','three')]
    src='const r=await Promise.all(['+','.join(cmds)+",tools.view_image({path:'demo.png'})]);"
    src+="text(JSON.stringify(r.slice(0,3)));image(r[3].image_url)"
    values=[dict(output='evidence-'+str(i),exit_code=0) for i in range(3)]
    blocks=[HEADER,json.dumps(values),dict(type='input_image',image_url=PIXEL)]
    return src,blocks


def wait(identifier,cell='32'):
    return event('response_item',dict(type='function_call',name='wait',arguments=json.dumps({'cell_id':cell}),call_id=identifier))


class ExecPresentation(unittest.TestCase):
    def test_literal_files_and_ambiguous_commands_without_native_evidence(self):
        commands={'tail -n 5 notes':'读取 notes','head -n5 notes':'读取 notes','nl -ba notes':'读取 notes',
                  'rg --files docs':'列举 docs','git ls-files':'列举 文件','cat -- "./-one"':'读取 ./-one',
                  'rg --files| head':'列举 文件 · 前 10 行','rg --files "guide pages" | head -n 2':'列举 guide pages · 前 2 行'}
        for cmd,label in commands.items():
            src='text(await tools.exec_command({cmd:'+json.dumps(cmd)+'}))'
            view=parse(call(src)+result('a',[HEADER,'{"output":"example","exit_code":0}']))[0]['exec_view']
            self.assertEqual(view['label'],label)
            direct=event('response_item',dict(type='function_call',name='exec_command',arguments=json.dumps(dict(cmd=cmd)),call_id='b'))
            self.assertEqual(parse(direct)[0]['operations'][0]['summary'],'请求'+label)
        for cmd in ['rg --files | nl -ba | foo','rg --files | custom','rg --files | head -n 2 file',
                    'rg --files "docs|head"','rg --files docs\\|head','rg --files a b | head','rg --files | head -c 2',
                    'rg --files a b','git ls-files --stage','nl -ba *','tail -f notes','cat a b','cat -','head -c 3 x','rg --files $(pwd)']:
            src='text(await tools.exec_command({cmd:'+json.dumps(cmd)+'}))'
            self.assertEqual(parse(call(src))[0]['exec_view']['kind'],'run',cmd)
        native=completed(dict(type='CommandExecution',command='nl -ba notes',parsed_cmd=[dict(type='unknown',cmd='nl -ba notes')]))
        view=parse(call('text(await tools.exec_command({cmd:"nl -ba notes"}))')+native)[0]['exec_view']
        self.assertNotIn('读取',view['label'])

    def test_native_list_action_keeps_original_head_limit(self):
        cmd='rg --files docs | head -n 2'
        native=completed(dict(type='CommandExecution',command=cmd,parsed_cmd=[dict(type='list_files',cmd='rg --files docs',path='docs')]))
        item=parse(native)[0]
        row=item['exec_view']['rows'][0]
        self.assertEqual(row['label'],'列举 docs · 前 2 行')
        self.assertEqual(row['shell_action']['cmd'],cmd)
        self.assertEqual(row['shell_action']['output_limit'],2)
        self.assertEqual(item['native_actions'][0]['cmd'],'rg --files docs')

    def test_literal_batch_and_reordering(self):
        src,blocks=batch()
        item=parse(call(src)+result('a',blocks))[0]
        view=item['exec_view']
        self.assertEqual(view['consumed'],[1,2])
        self.assertEqual([r['label'] for r in view['rows']],['读取 one.js','读取 two.js','读取 three.js','查看图片 demo.png'])
        self.assertEqual(view['rows'][1]['value']['output'],'evidence-1')
        self.assertEqual(item['output_blocks'][view['rows'][3]['media_block']]['image_url'],PIXEL)
        page=json.dumps(server.page_payload([item],{}))
        for secret in (PIXEL,'evidence-0','output_blocks','return_starts'):
            self.assertNotIn(secret,page)
        for changed in (src.replace('r.slice','r.reverse().slice'),src.replace('image(r[3]','image(r[2]'), 'if(ok){'+src+'}'):
            with self.subTest(changed=changed):
                row=parse(call(changed)+result('a',blocks))[0]
                self.assertEqual(row['exec_view']['consumed'],[])
                self.assertEqual(len(row['output_blocks']),3)

    def test_parallel_array_forwarding_and_uncertain_settled_result(self):
        calls = "tools.exec_command({cmd:'cat a'}),tools.exec_command({cmd:'cat b'})"
        values = [dict(exit_code=0,output='one'),dict(exit_code=1,output='two')]
        for method in ('all','allSettled'):
            emitted = values if method=='all' else [dict(status='fulfilled',value=v) for v in values]
            code = f'text(await Promise.{method}([{calls}]))'
            view = parse(call(code)+result('a',[HEADER,json.dumps(emitted)]))[0]['exec_view']
            self.assertEqual([r['value']['output'] for r in view['rows']],['one','two'])
        emitted[0] = dict(status='rejected',reason='timeout')
        view = parse(call(code)+result('a',[HEADER,json.dumps(emitted)]))[0]['exec_view']
        self.assertEqual(view['consumed'],[])
        src=f'const r=await Promise.all([{calls}]);text(r[1]);text(r[0])'
        view=parse(call(src)+result('a',[HEADER,json.dumps(values[1]),json.dumps(values[0])]))[0]['exec_view']
        self.assertEqual([r['value']['output'] for r in view['rows']],['one','two'])

    def test_cell_links_and_multiple_returns(self):
        transcript=call("await tools.image_gen__imagegen({})")+result('a',[CELL])
        transcript+=result('a',['progress'])+wait('b')+result('b',[CELL])
        transcript+=wait('c')+result('c',[HEADER,dict(type='input_image',image_url=PIXEL)])
        transcript+=wait('d')+result('d',['unknown cell'])
        origin,first,last,orphan=parse(transcript)
        self.assertEqual(origin['cell_waits'],[1,2])
        self.assertEqual(origin['output_blocks'],[CELL,'progress'])
        self.assertEqual(origin['exec_view']['state'],'图片已返回')
        self.assertEqual(origin['cell_final'],2)
        self.assertEqual(first['cell_origin'],0)
        self.assertEqual(last['cell_origin'],0)
        self.assertEqual(last['output_blocks'][-1]['image_url'],PIXEL)
        self.assertNotIn('cell_origin',orphan)

    def test_patch_native_diff_and_partial_return(self):
        src="text(await tools.apply_patch('*** Begin Patch\\n*** Add File: new.js\\n+hello\\n*** End Patch'))"
        patch=completed(dict(type='FileChange',id='n',status='completed',changes={'new.js':dict(type='add',content='hello\n')}))
        row=parse(call(src)+patch+result('a',[HEADER,'{}']))[0]
        self.assertEqual(row['exec_view']['label'],'新增 new.js')
        self.assertEqual(len(row['exec_view']['rows']),1)
        self.assertEqual(row['native_actions'][0]['diff'],'+hello')
        self.assertEqual(parse(call(src))[0]['exec_view']['state'],'未记录结果')

    def test_partial_output_is_not_an_exit_code(self):
        src="const r=await tools.exec_command({cmd:'cat x'});text(r.output)"
        view=parse(call(src)+result('a',[HEADER,'just text']))[0]['exec_view']
        self.assertEqual(view['rows'][0]['value'],dict(output='just text',output_only=True))
        self.assertEqual(parse(call(src)+result('a',['Script failed\nWall time 0 seconds\nOutput:\n','oops']))[0]['exec_view']['state'],'编排失败')

class CellLifecycle(unittest.TestCase):
    def test_audio_block_keeps_its_place_without_copying_encoded_payload(self):
        block=dict(type='input_audio',audio_url='data:audio/wav;base64,cHJpdmF0ZQ==')
        item=parse(call('text("before");audio(clip);text("after")')+result('a',[HEADER,'before',block,'after']))[0]
        self.assertEqual(item['output_blocks'],[HEADER,'before',{'type':'audio','mimeType':'audio/wav'},'after'])
        self.assertNotIn('cHJpdmF0ZQ',item['output'])
        self.assertNotIn('output_blocks',server.page_payload([item],{})['items'][0])

    def test_terminated_partial_return_closes_origin_before_id_reuse(self):
        terminated=HEADER.replace('completed','terminated')
        src=call('text(1)')+result('a',[CELL])+wait('b')+result('b',[terminated,'partial'])
        src+=call('text(2)','c')+result('c',[CELL])+wait('d')+result('d',[HEADER,'new result'])
        first,stop,second,done=parse(src)
        self.assertEqual((first['cell_waits'],first['cell_final'],first['exec_view']['state']),([1],1,'编排已终止'))
        self.assertEqual((stop['cell_origin'],stop['exec_view']['state'],stop['output_blocks'][-1]),(0,'编排已终止','partial'))
        self.assertEqual((second['cell_waits'],done['cell_origin']),([3],2))

    def test_wait_interruption_does_not_invent_terminal_cell_or_hide_later_completion(self):
        src=call('text(1)')+result('a',[CELL])+wait('b')+result('b',['aborted by user after 26.0s'])
        origin,interrupted=parse(src)
        self.assertNotIn('cell_final',origin)
        self.assertIn('最终状态未记录',origin['exec_view']['state'])
        self.assertEqual(interrupted['exec_view']['state'],'等待被用户中断')
        origin,_,last=parse(src+wait('c')+result('c',[HEADER,'done']))
        self.assertEqual((origin['cell_waits'],origin['cell_final'],last['cell_origin']),([1,2],2,0))
        # An interrupted exec (rather than the wait) ends its own association.
        origin,unlinked=parse(call('text(1)')+result('a',[CELL])+result('a',['aborted by user'])+wait('b'))
        self.assertEqual(origin['exec_view']['state'],'用户中止')
        self.assertNotIn('cell_origin',unlinked)

    def test_physical_order_live_collisions_and_session_boundaries(self):
        src=call('text(1)')+wait('early')+result('a',[CELL])
        src+=call('text(2)','c')+result('c',[CELL])+wait('collision')
        src+=result('a',[HEADER,'first done'])+wait('unique')+result('unique',[HEADER,'second done'])
        first,early,second,collision,unique=parse(src)
        self.assertNotIn('cell_origin',early)
        self.assertNotIn('cell_origin',collision)
        self.assertIn('无法确定来源',collision['cell_link_note'])
        self.assertEqual((first['cell_waits'],second['cell_waits'],unique['cell_origin']),([],[4],2))
        src=call('text(1)')+result('a',[CELL])+event('session_meta',dict(id='other-thread'))
        origin,waiter=parse(src+wait('b')+result('b',[HEADER,'orphan']))
        self.assertEqual(origin['cell_waits'],[])
        self.assertNotIn('cell_origin',waiter)

    def test_only_a_return_header_identifies_state_and_its_own_media(self):
        src=call('text(1)')+result('a',[CELL])+wait('b')
        # A later notification on the same call must not supply an image to the earlier final return.
        origin,waiter=parse(src+result('b',[HEADER,'Script terminated'])+result('b',[dict(type='input_image',image_url=PIXEL)]))
        self.assertEqual(origin['exec_view']['state'],'结果已返回')
        self.assertEqual(waiter['exec_view']['state'],'等待已完成')
        _,waiter=parse(src+result('b',['aborted by user is ordinary text']))
        self.assertNotIn('中断',waiter['exec_view']['state'])

    def test_quiet_polls_distinguish_running_exit_and_unknown_args(self):
        src='text(await tools.write_stdin({session_id:4,chars:""}))'
        for body in [dict(output='',session_id=4),dict(output='',exit_code=0),dict(output='error',exit_code=2),dict(exit_code=0)]:
            item=parse(call(src)+result('a',[HEADER,json.dumps(body)]))[0]
            self.assertEqual('无新增输出' in item['exec_view']['label'],body.get('output')=='')
        ops=server.classification
        old=dict(name='write_stdin',text='{"session_id":4}',output='Wall time: 0.01 seconds\nProcess running with session ID 4\nOutput:\n')
        row=ops.source_operations(old)[0]
        self.assertEqual(row['returned']['session_id'],4)
        self.assertNotIn('exit_code',row['returned'])
        self.assertIn('无新增输出',row['summary'])
        for chars in ['\x03','\n','\x03y']:
            op=ops.operation('write_stdin',dict(session_id=4,chars=chars),'direct')
            self.assertEqual('中断' in op['action'],chars=='\x03')
            self.assertFalse(ops.is_quiet_poll(op,{'output':''}))
        self.assertFalse(ops.is_quiet_poll(ops.operation('write_stdin',None,'script'),{'output':''}))
