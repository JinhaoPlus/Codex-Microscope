import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
import server


class OptionalHistory(unittest.TestCase):
    def setUp(self):
        server.HISTORY_CACHE.clear()
        server.HISTORY_FAILURE.update(home=None, retry_after=0)

    def test_rollout_and_list_survive_history_database_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            rollout = home/'rollout.jsonl'
            rollout.write_text(json.dumps({'type':'response_item','payload':{
                'type':'message','role':'assistant','content':'readable response'}})+'\n')
            (home/'thread_history_1.sqlite').touch()
            rows = [dict(id='demo', title='Test', name=None, source='cli', originator='codex_cli',
                         cwd='/example', updated_at=1, archived=0, model='example', tokens_used=0,
                         rollout_path=str(rollout))]
            class QuietHandler(server.Handler):
                def log_message(self, *args):
                    pass
            with patch.object(server,'HOME',home), patch.object(server,'rows',side_effect=lambda:[dict(r) for r in rows]), patch.object(server,'read_sql',side_effect=server.DatabaseUnavailable('temporary failure')) as read:
                http = server.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
                worker = threading.Thread(target=http.serve_forever, daemon=True)
                worker.start()
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                base='http://127.0.0.1:'+str(http.server_port)
                try:
                    listing=json.load(opener.open(base+'/api/threads'))
                    self.assertTrue(listing[0]['available'])
                    detail=json.load(opener.open(base+'/api/thread?id=demo'))
                    self.assertEqual(detail['items'][0]['text'],'readable response')
                    self.assertIsNotNone(detail['history_warning'])
                    json.load(opener.open(base+'/api/revision?id=demo'))
                    self.assertEqual(read.call_count,1)
                finally:
                    http.shutdown()
                    http.server_close()
                    worker.join()

    def test_cached_metadata_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'HOME',Path(directory)):
            (Path(directory)/'thread_history_1.sqlite').touch()
            with patch.object(server,'read_sql',return_value=[('cached',)]):
                self.assertEqual(server.history_sql('query'),[('cached',)])
            with patch.object(server,'read_sql',side_effect=server.DatabaseUnavailable('temporary failure')):
                self.assertEqual(server.history_sql('query'),[('cached',)])
                self.assertTrue(server.history_warning())
                with self.assertRaises(server.DatabaseUnavailable):
                    server.history_sql('uncached body',required=True)
            server.HISTORY_FAILURE['retry_after']=0
            with patch.object(server,'read_sql',return_value=[('fresh',)]):
                self.assertEqual(server.history_sql('query'),[('fresh',)])
                self.assertIsNone(server.history_warning())


if __name__=='__main__':
    unittest.main()
