"""Synthetic context records: ordering, provenance, and lossless grouping."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is optional')
class ContextOrganization(unittest.TestCase):
    def test_record_order_provenance_and_turn_field_preservation(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const zh=JSON.parse(fs.readFileSync('designs/browser/locales/zh-CN.json','utf8'));
function t(key,params={}){let value=zh[key];if(value&&typeof value==='object'){const count=params.count;value=count===1&&value.one?value.one:value.other??value.one??key;}if(!value)value=key;return String(value).replace(/\{(\w+)\}/g,(_,n)=>String(params[n]??''));}
function tp(key,count,params={}){return t(key,{...params,count});}
const source=fs.readFileSync('designs/browser/app.js','utf8');
const ctx={isContext:r=>r.kind==='context',effortIndicator:v=>`<span>${v}</span>`,t,tp};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('const esc='),source.indexOf('\n',source.indexOf('const esc=')))+'\nfunction md(s){return esc(s)}\n'+source.slice(source.indexOf('function contextField('),source.indexOf('let contextRequest=')),ctx);
const record=(text,time='2026-01-01T12:00:00Z')=>({kind:'context',role:'developer',text,time});
const tool=JSON.stringify({type:'message',tools:[{name:'search',parameters:{type:'object'}}]});
const records=[
 record('<environment_context><cwd>/project/first</cwd><shell>zsh</shell><permission_profile type="read-only"/><workspace_roots><root>/project</root></workspace_roots></environment_context>'),
 record('Repeated instruction'),record(tool),record('<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>'),
 record('Repeated instruction','2026-01-01T11:00:00Z'), // deliberately out of timestamp order
 record('<permissions instructions>Recorded access policy</permissions instructions>'),
 record('<environment_context><cwd>/project/last</cwd></environment_context>'),
 record('Mixed instructions\n'+tool),
 record('<external_browser_tabs>https://example.test/</external_browser_tabs>\nKeep this instruction'),
 record('Missing timestamp',null),
];
const original=JSON.stringify(records);
const html=ctx.contextPresentation({contextItems:records,thread:{id:'synthetic',model:'test-model',originator:'test',cwd:'/fallback'}});
const grouped=html.slice(0,html.indexOf('<details class="context-raw">'));
const headings=['环境概览','权限与访问范围','指令与背景','工具定义','附加背景','记录信息与原文'].map(x=>html.indexOf('<h3>'+x+'</h3>'));
assert.ok(headings.every((x,i)=>x>=0&&(!i||x>headings[i-1])));
assert.equal((grouped.match(/Repeated instruction/g)||[]).length,2);
assert.ok(grouped.indexOf('data-record-order="2"')<grouped.indexOf('data-record-order="5"'));
assert.ok(grouped.includes('2026-01-01T11:00:00Z'));
assert.match(grouped,/时间未记录/);
assert.match(grouped,/环境记录 · 2026-01-01T12:00:00Z/);
assert.doesNotMatch(html,/(?:记录|快照) #\d|记录序号|context-record-order/);
assert.match(grouped,/\/project\/last/);
assert.match(grouped,/read-only/);
assert.match(grouped,/page_id/); // page metadata is not replaced with a URL-only summary
assert.equal(ctx.contextRecordCategory(records[7].text)[0],'instructions');
assert.equal(ctx.contextRecordCategory(records[8].text)[0],'instructions');
assert.equal(ctx.contextRecordCategory('<environment_context>A</environment_context><environment_context>B</environment_context>')[0],'instructions');
const raw=html.slice(html.indexOf('<details class="context-raw">'));
let last=-1;
for(let i=0;i<records.length;i++){
 const encoded=JSON.stringify(records[i],null,2).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const pos=raw.indexOf(encoded,last+1);assert.ok(pos>last);last=pos;
}
assert.equal(JSON.stringify(records),original);
const snapshots=[
 {time:'2026-01-01T12:00:00Z',payload:{turn_id:'t',model:'older'}},
 {time:'2026-01-01T11:00:00Z',payload:{turn_id:'t',model:'second'}},
 {time:'2026-01-01T13:00:00Z',payload:{turn_id:'t',root_turn_id:'root',model:'latest',effort:'high',collaboration_mode:{mode:'plan',settings:{model:'nested',reasoning_effort:'high',developer_instructions:'LONG COLLABORATION INSTRUCTIONS',unknown_setting:{a:1}}},developer_instructions:'TOP INSTRUCTIONS',cwd:'/project',sandbox_policy:{type:'read-only'},disabled_plugin_ids:[],unknown_field:false}},
];
const before=JSON.stringify(snapshots),turn=ctx.turnPresentation(snapshots);
const latest=turn.slice(0,turn.indexOf('<h3>更早的快照</h3>'));
const labels=['本轮概览','权限与访问范围','本轮附加指令','其他设置'];
let previous=-1;for(const label of labels){const pos=latest.indexOf('<h3>'+label+'</h3>');assert.ok(pos>previous);previous=pos}
assert.ok(latest.indexOf('LONG COLLABORATION INSTRUCTIONS')>latest.indexOf('<h3>本轮附加指令</h3>'));
assert.ok(latest.indexOf('LONG COLLABORATION INSTRUCTIONS')<latest.indexOf('TOP INSTRUCTIONS'));
assert.match(latest,/unknown_setting/);assert.match(latest,/unknown_field/);assert.match(latest,/>false</);
assert.doesNotMatch(turn,/(?:记录|快照) #\d|context-record-order/);assert.match(latest,/2026-01-01T13:00:00Z/);
const history=turn.slice(turn.indexOf('<h3>更早的快照</h3>'));
assert.ok(history.indexOf('2026-01-01T12:00:00Z')<history.indexOf('2026-01-01T11:00:00Z'));
assert.ok(turn.indexOf('<h3>记录信息与原文</h3>')>turn.indexOf('<h3>更早的快照</h3>'));
assert.equal(JSON.stringify(snapshots),before);
for(const value of [null,{},[],{settings:{}},{settings:null},{settings:{developer_instructions:null}}]){
 const rendered=ctx.turnPresentation([{time:null,payload:{turn_id:'empty',collaboration_mode:value}}]);
 assert.match(rendered,/协作/);assert.match(rendered,/时间未记录/);
}
'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
