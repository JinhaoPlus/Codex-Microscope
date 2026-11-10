"""Late native events enrich requests without inventing or guessing calls."""
import json
import unittest
from contextlib import nullcontext

import server
from test_tool_operations import call, completed, event, parse
from test_exec_presentation import result, HEADER


def request(cmd='echo ready', id='a'):
    return call('text(await tools.exec_command({cmd:'+json.dumps(cmd)+'}))',id)


def returned(id='a'):
    return result(id,[HEADER,json.dumps(dict(output='ready',exit_code=0))])


def native(cmd='echo ready', **fields):
    return completed(dict(type='CommandExecution',command=cmd,aggregated_output='ready',exit_code=0,**fields))


class LateCommandEvents(unittest.TestCase):
    def test_late_event_attaches_to_returned_request_and_preserves_raw_order(self):
        items=parse(request()+returned()+native())
        self.assertEqual(len(items),1)
        item=items[0]
        self.assertEqual(item['record_type'],'tool_call')
        self.assertEqual(item['name'],'exec')
        self.assertEqual(item['_raw_lines'],[2,3,4])
        self.assertEqual(item['native_results'][0]['output'],'ready')
        self.assertEqual(len(item['exec_view']['rows']),1)
        self.assertNotIn('native_results',server.page_payload(items,{})['items'][0])
        self.assertEqual(server.page_payload(items,{'item':['0']})['item']['native_results'][0]['exit_code'],0)

    def test_another_open_call_does_not_capture_late_event(self):
        items=parse(request()+returned()+request('echo later','b')+native())
        self.assertEqual(len(items),2)
        self.assertIn('native_results',items[0])
        self.assertNotIn('native_results',items[1])

    def test_duplicate_commands_and_duplicate_call_sites_are_ambiguous(self):
        inputs=[request()+returned()+request(id='b'),
                request()+returned()+request(id='b')+returned('b'),
                call('text(await Promise.all([tools.exec_command({cmd:"echo ready"}),tools.exec_command({cmd:"echo ready"})]))')+returned()]
        for content in inputs:
            with self.subTest(content=content):
                items=parse(content+native())
                self.assertTrue(items[-1]['standalone_native'])
                self.assertEqual(items[-1]['association_reason'],'ambiguous_command')
                self.assertTrue(all('native_results' not in i for i in items[:-1]))

    def test_explicit_id_can_disambiguate_but_unknown_or_reused_id_cannot(self):
        before=request()+returned()+request(id='b')+returned('b')
        items=parse(before+native(call_id='a'))
        self.assertEqual(len(items),2)
        self.assertIn('native_results',items[0])
        self.assertNotIn('native_results',items[1])
        for content,event_fields,reason in [(request()+returned(),{'call_id':'missing'},'unknown_id'),
                                          (request()+returned()+request(),{'call_id':'a'},'ambiguous_id')]:
            items=parse(content+native(**event_fields))
            self.assertEqual(items[-1]['association_reason'],reason)

    def test_no_cross_turn_session_or_unknown_turn_late_fallback(self):
        before=request()+returned()
        content=before+event('turn_context',{'turn_id':'next'})+event('event_msg',dict(type='item_completed',turn_id='next',item=dict(type='CommandExecution',command='echo ready')))
        self.assertTrue(parse(content)[-1]['standalone_native'])
        content=before+event('session_meta',{})+event('turn_context',{'turn_id':'t'})+native()
        self.assertTrue(parse(content)[-1]['standalone_native'])
        content=request()+returned()+event('event_msg',{'type':'item_completed','item':dict(type='CommandExecution',command='echo ready')})
        items=server.parse_rollout(nullcontext(content.splitlines()))[0]
        self.assertEqual(items[-1]['association_reason'],'missing_turn')

    def test_substrings_dynamic_arguments_and_conflicting_pending_are_not_late_matches(self):
        contents=[request('echo ready and more')+returned(),
                  call('const cmd="echo ready";text(await tools.exec_command({cmd}))')+returned(),
                  request('echo different')]
        for content in contents:
            items=parse(content+native())
            self.assertTrue(items[-1]['standalone_native'])
        # The existing active-call fallback is retained for unknown arguments.
        self.assertEqual(len(parse(call('text(await tools.exec_command({cmd:dynamic}))')+native())),1)

    def test_existing_native_result_is_not_overwritten_or_reused(self):
        items=parse(request()+native(id='first')+returned()+native(id='second'))
        self.assertEqual(len(items),2)
        self.assertEqual(items[-1]['association_reason'],'already_linked')
        self.assertEqual(len(items[0]['native_results']),1)
        self.assertEqual(len(parse(request()+returned()+native(id='same')+native(id='same'))),1)

    def test_native_event_identity_is_separate_in_rollout_and_database(self):
        for items in [parse(native()),server.project_stored_rows([(json.dumps(dict(type='commandExecution',command='echo ready')),0,'t')])]:
            item=items[0]
            self.assertEqual(item['record_type'],'native_event')
            self.assertEqual(item['name'],'')
            self.assertEqual(item['native_type'].lower(),'commandexecution')
            self.assertIn('运行命令',item['exec_view']['label'])
            self.assertNotIn('CommandExecution',item['exec_view']['label'])


if __name__=='__main__':unittest.main()
