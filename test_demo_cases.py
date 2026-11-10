import json
import unittest
from unittest.mock import patch

import demo_cases
import server


class Gallery(unittest.TestCase):
    def test_long_script_retains_source_and_transport_fields_without_long_title(self):
        _,page=server.demo_response('/api/demo/thread',{'id':['long-script']})
        row=next(i for i in page['items'] if i['kind']=='tool')
        self.assertEqual(row['exec_view']['label'],'运行命令')
        _,detail=server.demo_response('/api/demo/thread',{'id':['long-script'],'item':[str(row['index'])]})
        item=detail['item']
        self.assertGreater(len(item['native_results'][0]['command'].splitlines()),30)
        self.assertEqual(item['native_results'][0]['output'],demo_cases.long_output)
        self.assertIn('demo-chunk',item['output'])
        _,variants=server.demo_response('/api/demo/thread',{'id':['script-languages']})
        tools=[i for i in variants['items'] if i['kind']=='tool']
        labels=[i['exec_view']['label'] if 'exec_view' in i else i['operations'][0]['summary'] for i in tools]
        self.assertEqual(labels,['运行命令','运行命令','运行命令 python3 check.py','运行命令 git status --short','运行命令'])

    def test_gallery_is_independent_of_live_history_and_raw_records_match(self):
        with patch.object(server,'open_rollout',side_effect=AssertionError('read live rollout')), \
             patch.object(server,'rows',side_effect=AssertionError('read live index')):
            status,cases=server.demo_response('/api/demo/threads',{})
            self.assertEqual(status,200)
            for case in cases:
                id=case['id']
                with self.subTest(id=id):
                    q={'id':[id]}
                    _,page=server.demo_response('/api/demo/thread',q)
                    self.assertEqual(page['skipped'],0)
                    self.assertEqual(page['thread'],case)
                    first=next(it for it in page['items'] if it['kind']=='tool')
                    self.assertTrue(first['lazy'])
                    detail={**q,'item':[str(first['index'])]}
                    _,full=server.demo_response('/api/demo/thread',detail)
                    _,raw=server.demo_response('/api/demo/thread',{**detail,'raw':['1']})
                    self.assertEqual(first['name'],full['item']['name'])
                    self.assertTrue(raw['records'])
                    for line in raw['records']:self.assertIn('commandActions' if case.get('record_format')=='database' else 'payload',json.loads(line))
            self.assertEqual(server.demo_response('/api/demo/thread',{'id':['real-id']})[0],404)
            self.assertEqual(server.demo_response('/api/demo/local-file',{'id':[cases[0]['id']]})[0],404)

    def test_all_audited_direct_tool_identities_have_examples(self):
        names=set()
        for case in demo_cases.catalog():
            if case.get('record_format')=='database':continue
            for line in demo_cases.lines(case['id']):
                item=json.loads(line)['payload']
                if item.get('type') in ('custom_tool_call','function_call'):
                    names.add('.'.join(filter(None,[item.get('namespace'),item['name']])))
        audited=set('exec wait exec_command write_stdin apply_patch web.run mcp__cua_repl.js mcp__cua_repl.js_reset mcp__codex_app.open_in_codex mcp__codex_app.load_workspace_dependencies request_user_input request_user_input_async clock.sleep update_plan update_goal'.split())
        audited.update('collaboration.'+name for name in 'spawn_agent followup_task send_message wait_agent list_agents interrupt_agent'.split())
        self.assertFalse(audited-names)

    def test_paged_fixture_has_real_jump_across_page_boundary(self):
        q={'id':['paged-cell']}
        _,recent=server.demo_response('/api/demo/thread',q)
        wait=recent['items'][-1]
        self.assertTrue(recent['has_more'])
        self.assertLess(wait['cell_origin'],recent['start'])
        _,source=server.demo_response('/api/demo/thread',{**q,'item':[str(wait['cell_origin'])]})
        self.assertEqual(source['item']['cell_final'],wait['index'])
