import json
import unittest

import server
from demo_cases import lines
from contextlib import nullcontext


class McpPresentation(unittest.TestCase):
    def test_secret_is_masked_across_native_and_flattened_copies(self):
        secret = 'demo-fixture-value'
        records = lines('mcp-protected')
        self.assertTrue(any(secret in line for line in records))
        items, _, _ = server.parse_rollout(nullcontext(records))
        case = next(x for x in items if x['kind']=='tool')
        detail = server.page_payload(items,{'item':[str(case['index'])]})['item']
        self.assertNotIn(secret,json.dumps(detail))
        result = detail['operations'][0]['event']['result']
        self.assertEqual(result['content'][0]['text'],'issued [已隐藏]')
        self.assertEqual(result['structuredContent']['token'],'[已隐藏]')
        _,raw = server.demo_response('/api/demo/thread',{'id':['mcp-protected'],'item':[str(case['index'])],'raw':['1']})
        self.assertNotIn(secret,json.dumps(raw))
        self.assertIn('[已隐藏]',raw['records'][0])

    def test_direct_media_survives_detail_only(self):
        records=[{'type':'response_item','payload':p} for p in [
            dict(type='function_call',name='mcp__demo__media',call_id='m',arguments='{}'),
            dict(type='function_call_output',call_id='m',output=[
                dict(type='input_text',text='intro'),dict(type='input_image',image_url='data:image/png;base64,YWJj')])]]
        items,_,_=server.parse_rollout(nullcontext(map(json.dumps,records)))
        self.assertNotIn('image_url',json.dumps(server.page_payload(items,{})))
        detail=server.page_payload(items,{'item':['0']})['item']
        self.assertEqual([x['type'] for x in detail['mcp_output']],['input_text','input_image'])
