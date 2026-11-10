from html.parser import HTMLParser
import threading
import unittest
import urllib.request
import server


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and (src := dict(attrs).get('src')):
            self.sources.append(src)


class StaticAssets(unittest.TestCase):
    def test_page_scripts_are_served_by_production_handler(self):
        class QuietHandler(server.Handler):
            def log_message(self, *args):
                pass

        http = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        worker = threading.Thread(target=http.serve_forever, daemon=True)
        worker.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = 'http://127.0.0.1:' + str(http.server_port)
        try:
            with opener.open(base + '/', timeout=5) as response:
                parser = ScriptSources()
                parser.feed(response.read().decode())
            self.assertIn('/vendor/highlight.min.js', parser.sources)
            for src in parser.sources + ['/vendor/schema-viewer.js', '/vendor/schema-viewer.css']:
                with self.subTest(src=src), opener.open(base + src, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.headers['Content-Type'].startswith('text/css' if src.endswith('.css') else 'text/javascript'))
                    self.assertEqual(response.read(), (server.ROOT / 'designs/browser' / src.lstrip('/')).read_bytes())
        finally:
            http.shutdown()
            http.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
