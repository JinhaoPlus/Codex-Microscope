import json
import unittest

import exec_presentation as presentation
import tool_operations as ops
from test_tool_operations import call, completed, event, parse
from test_exec_presentation import result, HEADER


def native(command='echo ready',process='42',**extra):
    return completed(dict(type='CommandExecution',command=command,process_id=process,
                          status='completed',aggregated_output='ready',exit_code=0,**extra))


def receipt(id='a',process=42):
    return result(id,[HEADER,json.dumps(dict(session_id=process,output='starting'))])


def request(cmd='dynamic',id='a'):
    return call('text(await tools.exec_command({cmd:'+cmd+'}))',id)


class PartialCommandArguments(unittest.TestCase):
    def test_fixed_cmd_survives_unknown_sibling_without_fabricated_workdir(self):
        for workdir in ['load("repo")','repo','pick({name:"repo"})']:
            source='text(await tools.exec_command({workdir:'+workdir+',cmd:"echo ready",max_output_tokens:12}))'
            item=parse(call(source)+native())[0]
            op=item['operations'][0]
            self.assertEqual(op['arguments'],{'cmd':'echo ready','max_output_tokens':12})
            self.assertEqual(op['unknown_arguments'],['workdir'])
            self.assertEqual(item['exec_view']['rows'][0]['unknown_arguments'],['workdir'])
            self.assertEqual(len(item['exec_view']['rows']),1)

    def test_computed_overridden_getter_and_aliased_arguments_remain_unknown(self):
        for arg in ['{cmd:"echo ready",...options}','{...options,cmd:"echo ready"}',
                    '{cmd:"echo ready",cmd:other}','{[key]:value,cmd:"echo ready"}',
                    '{get workdir(){return directory},cmd:"echo ready"}',
                    'options','{cmd:"echo ready",workdir}']:
            source='text(await tools.exec_command('+arg+'))'
            op=ops.source_operations(dict(name='exec',text=source))[0]
            self.assertIsNone(op['arguments'],arg)
        op=ops.source_operations(dict(name='exec',text='tools.exec_command({cmd:"echo "+suffix,workdir:"/workspace"})'))[0]
        self.assertEqual(op['unknown_arguments'],['cmd'])
        self.assertNotIn('cmd',op['arguments'])

    def test_unicode_escapes_use_js_order_and_never_create_tool_calls(self):
        values={r'`echo \u0020`':'echo  ',r'`echo \\\u0020`':'echo \\ ',
                r'"\uD83D\uDE00"':'😀',r"'\u{1F600}'":'😀',
                r'`\x41\u0042\u{43}`':'ABC',r'`\${value}`':'${value}',
                r'`tools.exec_command({cmd:"fake"})`':'tools.exec_command({cmd:"fake"})'}
        for token,value in values.items():self.assertEqual(ops.literal([token],0)[0],value,token)
        for token in [r'`\uZZZZ`',r'`\u12`',r'`\u{110000}`',r'`\u{}`',
                      r'`\uD800`',r'`\uDC00`',r'`\uD800X`',r'`\uD800\uD800`',r'`\01`',r'`\xZZ`',r'`${value}`']:
            with self.assertRaises(ValueError,msg=token):ops.literal([token],0)
        source=r'text(await tools.exec_command({cmd:`echo \u0020tools.exec_command({})`}))'
        self.assertEqual(len(ops.script_calls(source)),1)
        item=parse(call(source)+native('echo  tools.exec_command({})'))[0]
        self.assertEqual(len(item['native_results']),1)

    def test_static_cwd_conflict_is_not_a_command_match(self):
        source='text(await tools.exec_command({cmd:"echo ready",workdir:"/workspace/one"}))'
        items=parse(call(source)+native(cwd='/workspace/two'))
        self.assertEqual(items[-1]['association_reason'],'conflicting_cwd')


class ProcessOrigins(unittest.TestCase):
    def test_dynamic_command_receipt_binds_the_specific_inner_operation(self):
        source='const repo="/workspace";store("repo",repo);text(await Promise.allSettled([tools.exec_command({cmd:`echo ${repo}`}),tools.exec_command({cmd:"echo other"})]))'
        returned=[dict(status='fulfilled',value=dict(session_id=42,output='starting')),
                  dict(status='fulfilled',value=dict(exit_code=0,output='other'))]
        item=parse(call(source)+result('a',[HEADER,json.dumps(returned)])+native('echo /workspace'))[0]
        self.assertEqual(item['native_results'][0]['source_index'],0)
        self.assertEqual(item['native_results'][0]['association'],'process_id')
        self.assertEqual(len(item['exec_view']['rows']),2)
        self.assertEqual(item['exec_view']['rows'][0]['native'],0)
        self.assertEqual(item['operations'][0]['unknown_arguments'],['cmd'])
        self.assertNotIn('cmd',item['operations'][0]['arguments'])

    def test_polling_is_not_a_startup_origin(self):
        poll=event('response_item',dict(type='function_call',name='write_stdin',call_id='p',arguments=json.dumps(dict(session_id=42))))
        poll_return=event('response_item',dict(type='function_call_output',call_id='p',output=json.dumps(dict(session_id=42,output='progress'))))
        items=parse(request()+receipt()+poll+poll_return+native())
        self.assertEqual(len(items),2)
        self.assertIn('native_results',items[0]);self.assertNotIn('native_results',items[1])
        self.assertTrue(parse(poll+poll_return+native())[-1]['standalone_native'])

    def test_reused_session_ids_conflicts_and_finished_events_stay_independent(self):
        items=parse(request()+receipt()+request(id='b')+receipt('b')+native())
        self.assertEqual(items[-1]['association_reason'],'ambiguous_process')
        for source in ['text(await tools.exec_command({cmd:"echo other"}))',
                       'text(await tools.exec_command({cmd:dynamic,workdir:"/workspace/one"}))']:
            items=parse(call(source)+receipt()+native(cwd='/workspace/two'))
            self.assertEqual(items[-1]['association_reason'],'conflicting_process')
        items=parse(request()+receipt()+native(id='first')+native(id='second'))
        self.assertEqual(items[-1]['association_reason'],'already_linked')

    def test_no_provenance_in_shared_text_or_mutated_results(self):
        for source in ['await tools.exec_command({cmd:dynamic});text({session_id:42,output:"fake"})',
                       'const r=await tools.exec_command({cmd:dynamic});r.session_id=42;text(r)',
                       'if(ok){text(await tools.exec_command({cmd:dynamic}))}',
                       'const text="shadow";text(await tools.exec_command({cmd:dynamic}))',
                       'text(await tools.exec_command({cmd:await tools.exec_command({cmd:"nested"})}))']:
            items=parse(call(source)+receipt()+native())
            self.assertTrue(items[-1]['standalone_native'],source)

    def test_no_process_association_across_turns_or_sessions(self):
        started=request()+receipt()
        other_turn=event('turn_context',{'turn_id':'other'})+event('event_msg',dict(type='item_completed',turn_id='other',item=dict(type='CommandExecution',command='echo ready',process_id='42')))
        self.assertTrue(parse(started+other_turn)[-1]['standalone_native'])
        self.assertTrue(parse(started+event('session_meta',{})+event('turn_context',{'turn_id':'t'})+native())[-1]['standalone_native'])

    def test_unrecognized_or_non_startup_receipts_do_not_supply_process_id(self):
        for value in [dict(session_id=True,output='x'),dict(session_id=42,output='x',exit_code=0),dict(session_id=42),[dict(session_id=42,output='x')]]:
            item=parse(request()+result('a',[HEADER,json.dumps(value)]))[0]
            self.assertEqual(presentation.process_receipts(item),[])


if __name__=='__main__':unittest.main()
