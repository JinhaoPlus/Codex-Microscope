import json
import threading
import unittest
import urllib.request
from unittest.mock import patch
import server


class UsageStream(unittest.TestCase):
    def test_progress_arrives_before_calculation_completes(self):
        proceed=threading.Event()
        def calculate(rows,home,query,on_progress):
            on_progress(0,2)
            if not proceed.wait(3):raise RuntimeError('test timed out')
            on_progress(2,2)
            return {'total':7}
        class QuietHandler(server.Handler):
            def log_message(self,*args):pass
        with patch.object(server,'rows',return_value=[]),patch.object(server,'usage_report',side_effect=calculate):
            http=server.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
            worker=threading.Thread(target=http.serve_forever,daemon=True)
            worker.start()
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('http://127.0.0.1:'+str(http.server_port)+'/api/usage?stream=1',timeout=5) as response:
                    self.assertEqual(response.headers['Content-Type'],'application/x-ndjson; charset=utf-8')
                    self.assertEqual(json.loads(response.readline()),dict(type='progress',completed=0,total=2))
                    self.assertFalse(proceed.is_set())
                    proceed.set()
                    self.assertEqual(json.loads(response.readline()),dict(type='progress',completed=2,total=2))
                    self.assertEqual(json.loads(response.readline()),dict(type='result',data={'total':7}))
                    self.assertEqual(response.read(),b'')
            finally:
                proceed.set();http.shutdown();http.server_close();worker.join()


if __name__=='__main__':unittest.main()
