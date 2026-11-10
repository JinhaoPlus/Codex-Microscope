import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is optional; required for syntax rendering checks')
class SyntaxRendering(unittest.TestCase):
    def test_language_selection_multiline_and_safe_fallback(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('designs/browser/app.js','utf8'),ctx={actionIcon:()=>'',toolJsonMarker:()=>'',orchestrationBody:()=>'',commandStatus:()=>({label:'执行已结束 · 退出码未记录'})};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('designs/browser/vendor/highlight.min.js','utf8'),ctx);
vm.runInContext(source.slice(source.indexOf('const esc='),source.indexOf('\n',source.indexOf('const esc=')))+'\n'+source.slice(source.indexOf('function nativeReadRange('),source.indexOf('function toolDetailBody(')),ctx);
for(const [path,language] of [['file.PY','python'],['src/a.tsx','typescript'],['view.swift','swift'],['README.md','markdown'],['data.json','json'],['settings.toml','ini'],['unknown.xyz','plaintext']])assert.equal(ctx.nativeSyntax(path)[0],language);
const lines=['"""first','second','last"""','value = 12'];
const highlighted=ctx.nativeHighlightedLines(lines,'demo.py');
assert.equal(highlighted.length,lines.length);
for(let i=0;i<3;i++)assert.match(highlighted[i],/hljs-string/);
assert.match(highlighted[3],/hljs-number/);
for(const line of highlighted)assert.equal((line.match(/<span\b/g)||[]).length,(line.match(/<\/span>/g)||[]).length);
assert.doesNotMatch(ctx.nativeHighlightedLines(['<script>alert(1)</script>'],'file.html')[0],/<script>/);
assert.equal(ctx.nativeHighlightedLines(['<script>'],'unknown.xyz')[0],'&lt;script&gt;');
assert.doesNotMatch(ctx.nativeHighlightedLines(['x'.repeat(60001)],'demo.py')[0],/hljs-/);
const preview=ctx.nativeCodePreview('x = 1\ny = 2\nz = 3\n',{path:'demo.py',start:20,limit:2});
assert.equal(preview.remaining,1);assert.equal(preview.total,3);assert.match(preview.html,/>20<\/span>/);assert.match(preview.html,/>21<\/span>/);assert.match(preview.html,/hljs-number/);
assert.doesNotMatch(ctx.nativeCodePreview('x = 1',{path:''}).html,/hljs-/);
const expanded=ctx.nativeCodePreview('x = 1\ny = 2\nz = 3\n',{path:'demo.py',limit:10});assert.equal(expanded.remaining,0);assert.equal((expanded.html.match(/hljs-number/g)||[]).length,3);
const shared=ctx.nativeActionBody({native_actions:[{type:'read',path:'app.js',cmd:"sed -n '638,655p' app.js",result_index:0}],native_results:[{action_count:2,output:'105:README search result\nconst value = 42;\n',status:'completed'}]},0);
assert.match(shared,/所属命令的合并输出/);assert.match(shared,/JavaScript/);assert.match(shared,/hljs-keyword/);assert.match(shared,/hljs-number/);assert.match(shared,/行号为输出行号/);assert.match(shared,/>1<\/span>/);assert.doesNotMatch(shared,/>638<\/span>/);
const read=(cmd,output)=>ctx.nativeActionBody({native_actions:[{type:'read',path:'notes',cmd,result_index:0}],native_results:[{action_count:1,output}]},0);
assert.match(read('tail -n 3 notes','last three'),/最后 3 行/);
assert.match(read('tail -n 3 notes','last three'),/左侧为输出行号/);
assert.match(read('tail -n +12 notes','from twelve'),/>12<\/span>/);
assert.match(read("sed -n '20,23p' notes",'from twenty'),/>20<\/span>/);
assert.match(read("sed -n '20,23p' notes | head",'unknown range'),/左侧为输出行号/);
const listed=ctx.nativeActionBody({native_actions:[{type:'list_files',cmd:'rg --files docs | head -n 2',path:'docs',output_limit:2,result_index:0}],native_results:[{action_count:1,output:'docs/a\ndocs/b'}]},0);
assert.match(listed,/标准输出最多 2 行/);assert.match(listed,/rg --files docs \| head -n 2/);assert.match(listed,/docs\/a/);
ctx.hljs=undefined;assert.equal(ctx.nativeHighlightedLines(['<b>'],'demo.py')[0],'&lt;b&gt;');
'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
