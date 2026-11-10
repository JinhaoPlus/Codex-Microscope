import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is optional')
class UsageCostChart(unittest.TestCase):
    def test_cost_scale_missing_estimates_and_partial_coverage(self):
        script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const zh=JSON.parse(fs.readFileSync('designs/browser/locales/zh-CN.json','utf8'));
function t(key,params={}){let value=zh[key];if(value&&typeof value==='object'){const count=params.count;value=count===1&&value.one?value.one:value.other??value.one??key;}if(!value)value=key;return String(value).replace(/\{(\w+)\}/g,(_,n)=>String(params[n]??''));}
function tp(key,count,params={}){return t(key,{...params,count});}
const source=fs.readFileSync('designs/browser/token-usage.js','utf8');
const storage={};
function formatNumber(value,options={}){return Number(value).toLocaleString('en-US',options);}
const ctx={usageData:null,usageDay:'',usageCompact:String,usageNumber:String,usageExactNumber:String,tokenBreakdown:()=>'',formatNumber,window:{addEventListener:()=>{}},localStorage:{getItem:k=>storage[k]??null,setItem:(k,v)=>{storage[k]=v},removeItem:k=>{delete storage[k]}},I18n:{ready:Promise.resolve()},esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),t,tp};vm.createContext(ctx);
vm.runInContext(source.slice(0,source.indexOf('let usageDialog'))+'\n'+source.slice(source.indexOf('function usageBucketCost('),source.indexOf('// A calendar stays'))+'\n'+source.slice(source.indexOf('function usageCostHeading('),source.indexOf('function usageCoveragePercent(')),ctx);
const pricing={basis:'api',unit:'USD'};
const bucket=(total,value,rated=total,unrated=0)=>({label:'2026-11-06',total,tokens:{input:total},cost:{value,rated_tokens:rated,unrated_tokens:unrated}});
const render=(buckets,p=pricing)=>{ctx.usageData={buckets,pricing:p};return ctx.usageSVG()};
const points=html=>[...html.matchAll(/<circle\b[^>]*class="usage-point[^>]*>/g)].map(m=>Number(m[0].match(/\bcy="([^"]+)/)[1]));
let html=render([bucket(100,2),bucket(100,8)]),positions=points(html);
assert.equal(positions.length,2);assert.ok(positions[0]>positions[1],'equal token totals must still show different costs');
positions=points(render([bucket(100,4),bucket(1000,4)]));assert.equal(positions[0],positions[1],'equal costs must ignore token height');
html=render([bucket(100,2),bucket(100,null,0,100),bucket(100,8)]);
assert.equal(points(html).length,2);assert.doesNotMatch(html,/class="usage-line/,'missing costs must break the line');assert.match(ctx.usageCostTrendNote(),/断线处未估算/);
html=render([bucket(100,2,50,50),bucket(100,8)]);assert.match(html,/usage-line is-partial/);assert.match(html,/usage-point is-partial/);assert.match(ctx.usageCostTrendNote(),/空心点/);
html=render([bucket(100,null,0,100)]);assert.equal(points(html).length,0);assert.match(html,/未估算/);assert.match(html,/<rect /,'token bars remain when costs are unknown');
html=render([bucket(100,null)],{basis:'purchase',unit:'',credit_rule:null});assert.equal(points(html).length,0);assert.match(ctx.usageCostTrendNote(),/设置换算规则/);
assert.equal(ctx.usageBucketCost(bucket(100,0),pricing),0);assert.equal(ctx.usageBucketCost(bucket(0,null,0),pricing),0);
for(const value of [null,-1,Infinity,NaN])assert.equal(ctx.usageBucketCost(bucket(100,value),pricing),null);
assert.match(ctx.estimatedCostLabel(bucket(100,1e-15).cost,pricing,true),/e-15/);
assert.notEqual(ctx.usageCostAxisNumber(1e-12),'0');assert.notEqual(ctx.usageCostAxisNumber(.00001),'0');
html=render([bucket(100,1)],{basis:'credits',unit:'credits'});assert.match(html,/消耗 · credits/);assert.doesNotMatch(html,/USD/);
ctx.usageDay='2026-11-06';html=render([{...bucket(100,1),label:'13:00'}]);assert.match(html,/data-usage-hour="13:00"/);assert.match(html,/小时 Token/);
assert.doesNotMatch(render([]),/<svg/);
// Sparse records must not create ramps across the navigator's zero padding.
const dayMs=86400000,last=Date.parse('2026-11-10'),count=30;
ctx.usageData={buckets:[{label:'2026-11-05',total:100}]};
const overview=ctx.usageOverviewSVG({last,count});
const outline=overview.match(/points="([^"]+)"/)[1].split(' ').map(pair=>pair.split(',').map(Number));
const daily=outline.slice(2,-2);
assert.equal(daily.length,30);
assert.equal(daily.filter(([,y])=>y<34).length,1);
assert.equal(daily[24][1],2);
assert.equal(daily[23][1],34);assert.equal(daily[25][1],34);
assert.ok(Math.abs(daily[24][0]-((24.5)/30*1000))<.01);
ctx.usageData={buckets:[{label:'2026-10-12',total:100},{label:'2026-11-10',total:50}]};
const edge=ctx.usageOverviewSVG({last,count}).match(/points="([^"]+)"/)[1].split(' ').slice(2,-2).map(pair=>pair.split(',').map(Number));
assert.equal(edge[0][1],2);assert.equal(edge[29][1],18);assert.equal(edge[1][1],34);assert.equal(edge[28][1],34);
ctx.usageData={buckets:[{label:'2026-11-05',total:0}]};
assert.doesNotMatch(ctx.usageOverviewSVG({last,count}),/NaN|Infinity/);
'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
