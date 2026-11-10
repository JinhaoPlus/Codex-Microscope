import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node required for frontend execution checks')
class CommandRendering(unittest.TestCase):
    def test_execution_evidence_and_safe_literal_inputs(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('designs/browser/app.js','utf8');
const ctx={actionIcon:()=>'',toolJsonMarker:()=>'',parsedInput:x=>{try{return JSON.parse(x.text)}catch{return null}}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('const esc='),source.indexOf('\n',source.indexOf('const esc=')))+'\n'+source.slice(source.indexOf('function commandReturn('),source.indexOf('async function hydrateStep(')),ctx);
const wrapped=(text,result)=>({name:'exec',text,output:'Script completed\nWall time 1 seconds\nOutput:\n'+JSON.stringify(result)});
const direct={name:'exec_command',text:'{"cmd":"verify"}',output:'{"exit_code":0,"output":"done"}'};
const render=(x,op,limit=24)=>ctx.toolDetailBody({...x,operations:[op]},{dataset:{operation:'0'}},limit);
const op={kind:'run',tool:'exec_command',action:'运行命令',evidence:['script'],arguments:{cmd:'verify'},passthrough:true};
const pending=wrapped('text(await tools.exec_command({cmd:"verify"}))',{session_id:42,output:''});
const batch={...pending,envelope:{script:true},output_blocks:['wrapper','first block','second block']};
assert.doesNotMatch(render(batch,op),/结果未确认|尚无可确认|first block/);
const mixed={...batch,operations:[{kind:'session',action:'等待后台终端',tool:'write_stdin',arguments:{session_id:42},evidence:['script']},{kind:'image',action:'查看图片',tool:'view_image',arguments:{path:'<demo>.png'},evidence:['script']}]};
mixed.exec_view={rows:mixed.operations.map((op,i)=>({op:i,label:op.action})),headers:{},consumed:[]};
const mixedHTML=ctx.toolDetailBody(mixed,{dataset:{operation:'call'}});
const sections=['编排脚本','等待后台终端','查看图片','first block','second block'].map(label=>mixedHTML.indexOf(label));
assert.ok(sections.every((position,i)=>position>=0&&(!i||position>sections[i-1])));
assert.match(mixedHTML,/<details class="command-orchestration" open><summary>编排脚本/);
assert.match(mixedHTML,/执行会话[\s\S]*?42/);assert.match(mixedHTML,/文件路径[\s\S]*?&lt;demo&gt;.png/);
assert.equal((mixedHTML.match(/first block/g)||[]).length,1);
assert.doesNotMatch(mixedHTML,/<demo>/);
const matched={...batch,operations:[op,{resultRef:0}],native_results:[{command:'verify',exit_code:0,output:'native body'}],native_actions:[],exec_view:{rows:[{native:0,actions:[],label:'运行命令 verify'}]}};
const call=item=>ctx.toolDetailBody(item,{dataset:{operation:'call'}});
assert.match(call(matched),/native body/);
assert.doesNotMatch(call(matched),/调用参数中的命令/);
assert.match(ctx.execBlock({type:'image',image_url:'https://example.invalid/track'},24),/缺少可预览/);
assert.doesNotMatch(ctx.execBlock({type:'image',image_url:'https://example.invalid/track'},24),/<img/);
const outputs=ctx.orderedOutputBody(batch,24);
assert.ok(outputs.indexOf('first block')<outputs.indexOf('second block'));
assert.equal((outputs.match(/class="ordered-output-block"/g)||[]).length,3);
assert.doesNotMatch(outputs,/命令结果未确认/);
assert.equal(ctx.commandStatus({exit_code:null}).label,'命令结果未确认');
assert.equal(ctx.commandStatus({exit_code:'0'}).label,'命令结果未确认');
assert.equal(ctx.commandStatus({exit_code:0}).label,'已完成');
assert.match(ctx.commandStatus({exit_code:2}).label,/退出码 2/);
const folded=ctx.shellSource("node <<'JS'\nconsole.log('<script>');\nJS",'命令');
assert.match(folded,/<details class="command-source-details"><summary>命令源码/);
assert.match(folded,/JavaScript · 3 行/);assert.doesNotMatch(folded,/<script>/);
assert.doesNotMatch(ctx.shellSource('git status','命令'),/command-source-details/);
assert.doesNotMatch(ctx.outputPreview('done',24),/native-line-number/);
const rawHTML=ctx.orderedOutputBody({output_blocks:['{"output":"done","chunk_id":"transport"}'],exec_view:{}},24);
assert.match(rawHTML,/<details class="raw-output-details"><summary>/);
assert.doesNotMatch(rawHTML,/本次调用的输出/);
const long={...direct,output:JSON.stringify({exit_code:0,output:Array.from({length:30},(_,i)=>'line '+i).join('\n')})};
assert.match(render(long,{...op,evidence:['direct']}),/余 6 行/);
assert.doesNotMatch(render(long,{...op,evidence:['direct']},224),/余 6 行/);
const web={kind:'web',action:'网页搜索',evidence:['native'],arguments:{search_query:[{q:'one'}]},event:{results:[{title:'<img>',url:'javascript:void(0)',snippet:'<script>'}]}};
const webHTML=render(pending,web);
assert.match(webHTML,/网页结果/);assert.match(webHTML,/&lt;img&gt;/);assert.doesNotMatch(webHTML,/href="javascript|<img>|<script>|运行命令结果/);
vm.runInContext(fs.readFileSync('designs/browser/vendor/highlight.min.js','utf8'),ctx);
assert.ok(ctx.hljs.getLanguage('bash'));
vm.runInContext(source.slice(source.indexOf('function toolRecordTable('),source.indexOf('function nativeReadRange(')),ctx);
const jsCode='const message = "<script>";\n// check code\nconsole.log(message);';
for(const name of ['js','mcp__cua_repl.js','mcp__node_repl__js']){
 const table=ctx.toolRecordTable({name,text:JSON.stringify({code:jsCode,title:'Example'}),output:'{"code":"result text"}'});
 assert.match(table,/tool-js-code/);assert.match(table,/hljs-keyword/);assert.match(table,/hljs-comment/);assert.match(table,/&lt;script&gt;/);assert.doesNotMatch(table,/<script>/);assert.equal((table.match(/language-javascript/g)||[]).length,1);
}
assert.doesNotMatch(ctx.toolRecordTable({name:'another_tool',text:JSON.stringify({code:jsCode})}),/tool-js-code/);

const shell={name:'exec_command',text:JSON.stringify({cmd:'echo "$HOME"\n# shell comment\nprintf "%s\\n" "<script>"'}),output:'{"exit_code":0,"output":"done"}'};
const shellHTML=render(shell,{...op,arguments:JSON.parse(shell.text),evidence:['direct']});
assert.match(shellHTML,/language-bash/);assert.match(shellHTML,/hljs-built_in/);assert.match(shellHTML,/hljs-variable/);assert.match(shellHTML,/hljs-comment/);assert.match(shellHTML,/&lt;script&gt;/);assert.doesNotMatch(shellHTML,/<script>/);

const jsItem=wrapped('const result = await tools.exec_command({cmd:"echo \\"<script>\\"",yield_time_ms:1000});\n// collect result\ntext(result);',{exit_code:0});
const jsHTML=ctx.orchestrationBody(jsItem);
assert.match(jsHTML,/language-javascript/);assert.match(jsHTML,/hljs-keyword/);assert.match(jsHTML,/hljs-comment/);assert.match(jsHTML,/hljs-number/);assert.match(jsHTML,/&lt;script&gt;/);assert.doesNotMatch(jsHTML,/<script>/);
assert.doesNotMatch(ctx.orchestrationBody(direct),/language-javascript/);
ctx.hljs=undefined;
assert.match(render(shell,{...op,arguments:JSON.parse(shell.text)}),/&lt;script&gt;/);
assert.match(ctx.orchestrationBody(jsItem),/&lt;script&gt;/);

'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
