import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is optional; required for frontend parser checks')
class SearchRendering(unittest.TestCase):
    def test_search_formats_highlights_and_escaping(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('designs/browser/app.js','utf8');
vm.runInThisContext(source.slice(source.indexOf('function nativeSearchHighlight('),source.indexOf('function nativeActionBody(')));
global.esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
assert.deepEqual(nativeSearchRecords('70:hello\n77:123:value\n',{path:'app.js'},'rg -n query app.js').records,[{path:'app.js',line:70,text:'hello'},{path:'app.js',line:77,text:'123:value'}]);
assert.equal(nativeSearchRecords('src/app.js:22:hello\nsrc/view.js:3:other',{},'rg -n hello src').records[1].path,'src/view.js');
assert.equal(nativeSearchRecords('app.js:20:4:hello',{},'rg --column -n hello .').records[0].text,'hello');
assert.equal(nativeSearchRecords('rg: invalid pattern',{},'rg -n [ .'),null);
assert.equal(nativeSearchRecords('file.js\nother.js\n',{},'rg -l query .').filesOnly,true);
assert.equal(nativeSearchRecords('file.js:1:hit',{},'rg -L -n hit .').filesOnly,false);
assert.equal(nativeSearchRecords('file.js\n',{},'grep -L hit .').filesOnly,true);
assert.equal(nativeSearchRecords('app.js\n22:hit\n',{},'rg --heading -n hit .').records[0].path,'app.js');
assert.equal(nativeSearchRecords(JSON.stringify({type:'match',data:{path:{text:'app.js'},line_number:3,lines:{text:'hit\n'}}}),{},'rg --json hit .').records[0].line,3);
assert.equal(nativeSearchRecords('not valid json',{},'rg --json hit .'),null);
assert.match(nativeSearchHighlight('const Foo = "<script>"','Foo|<script>'),/<mark>Foo<\/mark>/);
assert.doesNotMatch(nativeSearchHighlight('<script>','<script>'),/<script>/);
assert.equal(nativeSearchHighlight('aaaaa','(a+)+$'),'aaaaa');
assert.equal(nativeSearchHighlight('ALPHA','alpha','rg -i alpha'),'<mark>ALPHA</mark>');
assert.equal(nativeSearchHighlight('alpha|beta','alpha|beta','rg -F "alpha|beta"'),'<mark>alpha|beta</mark>');
'''
        result=subprocess.run([shutil.which('node'),'-e',script],cwd=Path(__file__).parent,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
