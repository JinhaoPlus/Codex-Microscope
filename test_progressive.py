import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
from session_io import CACHE, resolve_rollout, open_rollout


def record(payload, typ='response_item'):
    return json.dumps({'type': typ, 'payload': payload})+'\n'


class ProgressiveHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/'sample.jsonl'
        CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_invalidates_for_append_and_replacement(self):
        self.path.write_text(record({'type':'message','role':'user','content':'first'}))
        self.assertEqual(server.history(self.path)[0][0]['text'], 'first')
        with self.path.open('a') as f:f.write(record({'type':'message','role':'assistant','content':'second'}))
        self.assertEqual(len(server.history(self.path)[0]), 2)
        replacement=self.root/'replacement'
        replacement.write_text(record({'type':'message','role':'user','content':'other'}))
        replacement.replace(self.path)
        self.assertEqual(server.history(self.path)[0][0]['text'], 'other')

    def test_pages_cover_history_and_defer_large_tool_body(self):
        items=[{'kind':'context','text':'policy'}]
        for n in range(21):
            items.extend([{'kind':'message','role':'user','text':str(n)}, {'kind':'tool','name':'exec','text':json.dumps({'cmd':'echo hello','code':'x'*5000}),'output':'unique-tail '+('x'*10000)}, {'kind':'message','role':'assistant','text':'answer'}])
        page=server.page_payload(items,{})
        self.assertTrue(page['has_more'])
        self.assertEqual(sum(x.get('role')=='user' for x in page['items']),8)
        self.assertTrue(all('output' not in x for x in page['items'] if x['kind']=='tool'))
        collected=page['items']
        while page['has_more']:
            page=server.page_payload(items,{'before':[str(page['start'])]})
            collected=page['items']+collected
        self.assertEqual([x['index'] for x in collected],list(range(1,len(items))))
        self.assertEqual(json.loads(collected[1]['text'])['cmd'],'echo hello')
        self.assertEqual(server.page_payload(items,{'item':['2']})['item']['output'],items[2]['output'])
        self.assertEqual(server.page_payload(items,{'view':['context']})['items'],[items[0]])
        result=server.page_payload(items,{'q':['unique-tail']})
        self.assertFalse(result['has_more'])
        self.assertEqual(result['items'][1]['output'],items[2]['output'])
        from message_i18n import I18nError
        with self.assertRaises(I18nError):server.page_payload(items,{'item':['-1']})

    @unittest.skipUnless(shutil.which('zstd'), 'zstd CLI unavailable')
    def test_compressed_sibling_magic_and_corruption(self):
        raw=record({'id':'child','parent_thread_id':'parent'},'session_meta')+record({'type':'message','role':'user','content':'hello'})
        self.path.write_text(raw)
        expected=server.history(self.path)
        compressed=Path(str(self.path)+'.zst')
        subprocess.run(['zstd','-q',str(self.path),'-o',str(compressed)],check=True)
        self.path.unlink()
        self.assertEqual(resolve_rollout(self.path),compressed)
        self.assertEqual(server.history(self.path),expected)
        with patch.object(server,'HOME',self.root):
            self.assertEqual(server.parent_id({'source':'cli','rollout_path':str(self.path)}),'parent')
        # Magic-based detection works even when the extension is plain JSONL.
        compressed.rename(self.path)
        self.assertEqual(server.history(self.path),expected)
        self.path.write_bytes(b'\x28\xb5\x2f\xfd broken frame')
        from message_i18n import SessionIOError
        with self.assertRaises(SessionIOError):
            with open_rollout(self.path) as f:list(f)

    def test_parent_relations_use_ids_not_titles(self):
        for name,parent in [('p',None),('c','p'),('unrelated',None)]:
            (self.root/(name+'.jsonl')).write_text(record({'id':name,'parent_thread_id':parent},'session_meta'))
        rows=[{'id':name,'title':'identical title','source':'cli','rollout_path':str(self.root/(name+'.jsonl'))} for name in ('p','c','unrelated')]
        with patch.object(server,'HOME',self.root),patch.object(server,'rows',return_value=rows):
            self.assertEqual([r['id'] for r in server.relations('p')['children']],['c'])
            self.assertEqual(server.relations('c')['parent']['id'],'p')
        source=json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':'p','agent_path':'/root/worker'}}})
        self.assertEqual(server.parent_id({'source':source,'rollout_path':str(self.root/'absent')}),'p')

if __name__=='__main__':unittest.main()
