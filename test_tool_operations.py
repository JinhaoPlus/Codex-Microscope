import json
import tempfile
import unittest
from pathlib import Path

import server
import tool_operations as ops


def event(kind, payload):
    return json.dumps(dict(type=kind, payload=payload))+'\n'


def call(source, identifier='a'):
    return event('response_item', dict(type='custom_tool_call', name='exec', input=source, call_id=identifier))


def completed(item):
    return event('event_msg', dict(type='item_completed', turn_id='t', item=item))


def parse(content):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'synthetic.jsonl'
        path.write_text(event('turn_context', {'turn_id':'t'})+content)
        return server.parse_history(path)[0]


class Operations(unittest.TestCase):
    def test_backtick_shell_command_preserves_result_forwarding(self):
        command = "git diff --stat; git status --short; sed -n '1,260p' demo.py"
        def row(template):
            return ops.operations(dict(name='exec', text=(
                'text(await tools.exec_command({cmd:' + template + ',max_output_tokens:4300}))'
            )))[0]
        op = row('`' + command + '`')
        self.assertEqual(op['arguments'], dict(cmd=command, max_output_tokens=4300))
        self.assertEqual(row(r'`echo \${HOME}\nls`')['arguments']['cmd'], 'echo ${HOME}\nls')
        for template in ['`echo ${computed}`', r'`echo \xZZ`', '`unterminated']:
            op=row(template)
            self.assertNotIn('cmd',op['arguments'] or {})
            if op['arguments'] is not None:self.assertIn('cmd',op['unknown_arguments'])

    def test_long_mixed_script_preserves_siblings_and_lazy_payload(self):
        source = "/*"+'p'*1200+"*/\nawait tools.exec_command({cmd:'cat demo'}); text(await tools.web__run({search_query:[{q:'first'},{q:'second'}]}));"
        web = dict(type='Extension',kind='web.search',id='w',action=dict(type='search',queries=['first','second']),results=[dict(title='unique result')])
        shell = dict(type='CommandExecution',id='s',command='cat demo',parsed_cmd=[dict(type='read',path='demo')],exit_code=0,aggregated_output='unique output')
        items=parse(call(source)+completed(web)+completed(shell))
        full=server.page_payload(items,{'item':['0']})['item']['operations']
        page=server.page_payload(items,{})['items'][0]
        self.assertEqual([o['kind'] for o in full], ['run','web','run'])
        self.assertEqual(page['operations'], ops.summaries(full))
        self.assertNotIn('unique result',json.dumps(page))
        self.assertNotIn('unique output',json.dumps(page))
        self.assertLessEqual(len(page['text']),1000)
        self.assertEqual(full[1]['event']['results'],web['results'])

    def test_ambiguous_events_stay_independent(self):
        src="await tools.web__run({search_query:[{q:'same'}]})"
        items=parse(call(src)+call(src,'b')+completed(dict(type='Extension',kind='web.search',action=dict(type='search',queries=['same']),results=[])))
        self.assertEqual(len(items),3)
        self.assertTrue(items[2]['standalone_native'])
        self.assertNotIn('event',items[0]['operations'][0])

    def test_json_original_uses_only_this_calls_source_lines_in_log_order(self):
        records=[call('tools.exec_command({cmd:"demo"})'),call('unrelated','b'),
                 completed(dict(type='CommandExecution',call_id='a',command='demo',id='n')),
                 event('response_item',dict(type='custom_tool_call_output',call_id='a',output='done'))]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.jsonl'
            path.write_text(event('turn_context',{'turn_id':'t'})+''.join(records))
            items=server.parse_history(path)[0]
            self.assertEqual(server.raw_tool_records(items[0],path),[records[n].rstrip() for n in (0,2,3)])
            self.assertNotIn('_raw_lines',server.page_payload(items,{'item':['0']})['item'])

    def test_output_blocks_are_independent_and_lazy(self):
        src='text(await tools.write_stdin({session_id:8}));text((await tools.exec_command({cmd:"demo"})).output)'
        blocks=['Script completed\nWall time 1 seconds\nOutput:\n','{"exit_code":0,"output":"done"}','a\nb','']
        for values in [blocks, blocks[:1], blocks+['extra'], list(reversed(blocks))]:
            result=event('response_item',dict(type='custom_tool_call_output',call_id='a',
                         output=[dict(type='input_text',text=v) for v in values]))
            items=parse(call(src)+result)
            self.assertEqual(items[0]['output_blocks'],values)
            self.assertTrue(all('returned' not in op for op in items[0]['operations']))
            self.assertNotIn('output_blocks',server.page_payload(items,{})['items'][0])

    def test_native_arrays_keep_separate_rows_with_hex_escape(self):
        src=r'text(await tools.exec_command({cmd:`echo \x41`}))'
        native=dict(type='CommandExecution', id='s', command='echo A', exit_code=0,
                    aggregated_output='A', parsed_cmd=[dict(type='unknown',cmd='echo A')])
        rows=parse(call(src)+completed(native))[0]['operations']
        self.assertEqual(rows[0]['arguments']['cmd'],'echo A')
        self.assertEqual([o.get('nativeIndex') for o in rows],[None,None])
        self.assertEqual([o.get('resultRef') for o in rows],[None,0])

    def test_independent_order_with_unequal_lengths_and_no_match(self):
        item=dict(name='exec',text='await tools.exec_command({cmd:"A"});await tools.exec_command({cmd:"B"})',
                  native_actions=[dict(type='read',path='z',result_index=1),dict(type='read',path='x'),
                                  dict(type='edit',path='y',result_index=0)],
                  native_results=[dict(command='B',output='first'),dict(command='A',output='second')])
        rows=ops.operations(item)
        self.assertEqual([o['summary'] for o in rows],['运行命令 A','运行命令 B','执行结果 B','执行结果 A'])
        self.assertTrue(all('nativeIndex' not in row for row in rows))


    def test_session_and_image_summaries_preserve_static_evidence(self):
        source = '''await tools.write_stdin({session_id:17}); await tools["view_image"]({path:"dir/demo.png"});
                    await tools.write_stdin({session_id:id,chars:input}); await tools.view_image({path:computed})'''
        rows = parse(call(source))[0]['operations']
        self.assertEqual([row['summary'] for row in rows], ['等待后台终端 · 会话 17','查看图片 demo.png','后台终端交互','查看图片'])
        self.assertEqual(ops.operations(dict(name='view_image',namespace='functions',text='{"path":"x.png"}'))[0]['kind'],'image')

    def test_cli_image_event_and_terminal_input(self):
        img = dict(type='ImageView',id='img',path='file:///demo/images/a%20b.png')
        row = parse(call('image(await tools.view_image({path:"/demo/images/a b.png"}))')+completed(img))[0]['operations']
        self.assertEqual(len(row),1)
        self.assertEqual((row[0]['summary'],row[0]['evidence']),('查看图片 a b.png',['script','native']))
        self.assertEqual(parse(completed(img))[0]['operations'][0]['arguments']['path'],'/demo/images/a b.png')
        for chars, key in [('', 'tools.action.sessionWait'), ('\n', 'tools.action.sessionInput')]:
            self.assertEqual(ops.classify('write_stdin', dict(session_id=7, chars=chars))[1], key)

    def test_parallel_inputs_preserve_order(self):
        source='text(await Promise.allSettled(["one","two"].map(cmd=>tools.exec_command({cmd}))))'
        self.assertEqual([o['arguments']['cmd'] for o in ops.operations(dict(name='exec',text=source))],['one','two'])

    def test_legacy_command_header_is_bound_to_direct_tool(self):
        output='Chunk ID: ab12\nWall time: 0.2 seconds\nProcess exited with code 2\nOriginal token count: 4\nOutput:\nProcess exited with code 0'
        item=dict(name='exec_command',text='{"cmd":"demo"}',output=output)
        result=ops.operations(item)[0]['returned']
        self.assertEqual((result['exit_code'],result['output']),(2,'Process exited with code 0'))
        self.assertNotIn('returned',ops.operations(dict(item,output='log\n'+output))[0])

    def test_dynamic_and_quoted_calls_and_namespaces(self):
        raw="""// tools.web__run({})
        const s="tools.exec_command({cmd:'fake'})";
        tools[choose()]({}); await tools.exec_command({cmd:dynamic});"""
        rows=ops.operations(dict(name='exec',text=raw))
        self.assertEqual([o['tool'] for o in rows],[None,'exec_command'])
        self.assertIsNone(rows[0]['arguments'])
        self.assertEqual(rows[1]['arguments'],{})
        self.assertEqual(rows[1]['unknown_arguments'],['cmd'])
        for namespace,kind in [('mcp__cua_repl','browser'),('mcp__node_repl','other')]:
            item=dict(namespace=namespace,name='js',text='{"code":"example"}')
            self.assertEqual(ops.operations(item)[0]['kind'],kind)
