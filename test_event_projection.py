from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from test_tool_operations import call,completed,event,parse


def direct(name,args,id='a',namespace=None):
    return event('response_item',dict(type='function_call',name=name,call_id=id,arguments=json.dumps(args),namespace=namespace))


def output(id,*blocks):
    return event('response_item',dict(type='function_call_output',call_id=id,output=list(blocks)))


class EventProjection(unittest.TestCase):
    def test_dynamic_result_stays_on_matching_request_or_separate_if_ambiguous(self):
        source='await tools.codex_app__inspect({target:"a"}); await tools.exec_command({cmd:"pwd"})'
        native=dict(type='DynamicToolCall',namespace='codex_app',tool='inspect',id='inner',arguments={'target':'a'},
                    content_items=[{'type':'input_text','text':'terminal unavailable'}],
                    status='failed',success=False,duration=dict(secs=0,nanos=9000000))
        items=parse(call(source)+completed(native)+completed(native)+output('a','container ended'))
        self.assertEqual(len(items),1)
        op=items[0]['operations'][0]
        self.assertEqual(op['evidence'],['script','native'])
        self.assertEqual(op['event']['durationMs'],9)
        self.assertIn('失败',op['summary'])
        self.assertNotIn('terminal unavailable',json.dumps(server.page_payload(items,{})))
        ambiguous=parse(call(source)+call(source,'b')+completed(native))
        self.assertEqual(len(ambiguous),3)
        self.assertTrue(ambiguous[-1]['standalone_native'])
        both=source+';await tools.codex_app__inspect({target:"a"})'
        self.assertTrue(parse(call(both)+completed(native))[-1]['standalone_native'])

    def test_web_match_and_explicit_id_keep_clock_agent_requests_and_activity_distinct(self):
        web=dict(type='WebSearch',id='search',query='notes',action={'type':'search','queries':['notes']},results=[dict(title='Source')])
        merged=parse(call('await tools.web__run({search_query:[{q:"notes"}]})')+completed(web))
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['operations'][0]['event']['results'],web['results'])
        record=direct('sleep',dict(duration_ms=100),namespace='clock')+completed(dict(type='Extension',kind='clock.sleep',id='a',durationMs=100))+output('a','early wake')
        record+=direct('spawn_agent',dict(task_name='sample'),id='b',namespace='collaboration')
        record+=completed(dict(type='SubAgentActivity',id='b',kind='started',agent_thread_id='child',agent_path='/root/example'))
        record+=output('b','dispatched')
        record+=completed(dict(type='SubAgentActivity',id='finish',kind='completed',agent_thread_id='child'))
        items=parse(record)
        self.assertEqual([(i['name'],i['operations'][0]['event']['native_family']) for i in items],
                         [('sleep','sleep'),('spawn_agent','agent_activity'),('','agent_activity')])
        self.assertEqual(items[0]['output'],'early wake')
        self.assertIn('/root/example',items[1]['operations'][0]['summary'])

    def test_image_return_matches_exact_bytes_once_and_does_not_cross_unknown_id(self):
        generate=dict(type='Extension',kind='image_gen.generation',id='generated',result='aGVsbG8=',status='completed')
        owner=direct('wait',dict(cell_id='24'))
        image=dict(type='input_image',image_url='data:image/png;base64,aGVsbG8=')
        matched=parse(owner+completed(generate)+output('a',image))
        self.assertEqual(len(matched),1)
        self.assertTrue(matched[0]['tool_events'][0]['matched_return_image'])
        self.assertEqual(len(matched[0]['_raw_lines']),3)
        self.assertNotIn('aGVsbG8=',json.dumps(server.page_payload(matched,{})))
        # Identical images in two open waits do not establish a unique owner.
        ambiguous=parse(owner+direct('wait',dict(cell_id='25'),'b')+completed(generate)+output('b',image)+output('a',image))
        self.assertTrue(ambiguous[2]['standalone_native'])
        orphan=parse(owner+completed(dict(generate,call_id='missing'))+output('a',image))
        self.assertTrue(orphan[-1]['standalone_native'])

    def test_database_event_fields_project_without_heavy_preview_data(self):
        events=[
            dict(type='sleep',durationMs=15),
            dict(type='imageGeneration',status='failed',failure={'message':'engine failed'},result=None),
            dict(type='webSearch',action={'type':'findInPage','pattern':'example'},results=[]),
            dict(type='dynamicToolCall',namespace='codex_app',tool='inspect',arguments={},success=True,contentItems=[dict(type='inputText',text='evidence-body')]),
            dict(type='subAgentActivity',kind='interrupted',agentThreadId='child',agentPath='/root/sample'),
            dict(type='collabAgentToolCall',tool='wait',status='completed',receiverThreadIds=['child'],agentsStates={'child':{'status':'running'}})
        ]
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'HOME',Path(tmp)):
            with closing(sqlite3.connect(Path(tmp)/'thread_history_1.sqlite')) as db,db:
                db.execute('create table thread_items(thread_id text,item_json text,created_at_ms int,turn_id text,rollout_ordinal int)')
                db.executemany('insert into thread_items values(?,?,?,?,?)', [('a',json.dumps(e),1,'t',i) for i,e in enumerate(events)])
            items=server.stored_history('a')
        self.assertEqual([i['operations'][0]['event']['native_family'] for i in items],
                         ['sleep','generation','web','dynamic','agent_activity','agent_call'])
        self.assertNotIn('evidence-body',json.dumps(server.page_payload(items,{})))
        self.assertIn('evidence-body',json.dumps(server.page_payload(items,{'item':['3']})))
