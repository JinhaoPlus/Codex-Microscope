import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is optional')
class ContextToolDefinitions(unittest.TestCase):
    def test_schema_variants_custom_format_and_missing_metadata(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('designs/browser/app.js','utf8');
const ctx={md:s=>s};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('const esc='),source.indexOf('\n',source.indexOf('const esc=')))+'\n'+source.slice(source.indexOf('function schemaPreview('),source.indexOf('function contextPresentation(')),ctx);
for(const key of ['parameters','input_schema','inputSchema','schema']){
 const definition={name:'lookup',description:'Long description', [key]:{type:'object',properties:{query:{type:'string'}},required:['query']}};
 for(const item of [definition,{type:'function',function:definition}]){
  const html=ctx.contextToolDetail(item);
  assert.match(html,/入参 Schema/);assert.ok(html.indexOf('query')<html.indexOf('Long description'));
  assert.equal((html.match(/&quot;required&quot;/g)||[]).length,1);
 }
}
const nested=ctx.schemaPreview({type:'object',properties:{unsafe:{type:'string',description:'<script>alert(1)</script>'}},required:['unsafe']});
assert.match(nested,/schema-viewer-host/);assert.match(nested,/查看原始 Schema/);
assert.doesNotMatch(nested,/<script>/);assert.match(nested,/&lt;script&gt;/);
assert.match(ctx.schemaPreview(false),/>false<\/pre>/);
const custom=ctx.contextToolDetail({type:'custom',name:'patch',format:{type:'grammar',definition:'start: <input>'}});
assert.match(custom,/入参格式/);assert.match(custom,/未提供 JSON Schema/);assert.match(custom,/&lt;input&gt;/);
assert.match(ctx.contextToolDetail({name:'missing'}),/不能据此判断工具没有入参/);
assert.match(ctx.contextToolDetail({name:'empty',parameters:{}}),/<pre class="context-json">\{\}<\/pre>/);
assert.match(ctx.contextTools([{type:'namespace',name:'sample',tools:[{name:'lookup',parameters:{type:'object'}}]}]),/入参 Schema/);
'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
