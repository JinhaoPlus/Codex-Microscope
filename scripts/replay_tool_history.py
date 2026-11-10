"""Read-only replay of local rollouts through the list, detail and HTML renderers.

Usage: python3 scripts/replay_tool_history.py [--before ISO-UTC] ROLLOUT ...
Print counts and record indices only; logs stay local. No log JS is evaluated.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server

RENDER = r"""
const vm=require('node:vm'),fs=require('node:fs'),src=fs.readFileSync('designs/browser/app.js','utf8');
const c={actionIcon:()=>'',toolJsonMarker:()=>'',threads:[],data:{}};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('const esc='),src.indexOf('\n',src.indexOf('const esc=')))+'\n'+src.slice(src.indexOf('function commandReturn('),src.indexOf('async function hydrateStep(')),c);
let totals={calls:0,operations:0,shell:0,unknown:0,blocks:0}, kinds={};
require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
 const [file,i]=JSON.parse(line), ops=i.operations;
 totals.calls++;totals.operations+=ops.length;
 const check=(v,msg)=>{if(!v)throw Error('rollout '+file+' item '+i.index+': '+msg)};
 check(ops.length,'no operation');
 for(const [field,ref] of [['native_results','resultRef']]){
  (i[field]||[]).forEach((_,n)=>check(ops.some(op=>op[ref]===n),field+' missing'));
 }
 for(const event of i.tool_events||[]){
  check(ops.some(o=>o.event&&JSON.stringify(o.event)===JSON.stringify(event)),'native event missing');
 }
 if(i.native_actions?.length||i.native_results?.length){
  const html=c.toolDetailBody(i,{dataset:{operation:'call'}},24);
  check(!html.includes('data-action-index='),'unexpected native action row');
  check(!html.includes('data-result-index='),'unexpected native result row');
 }
 if(i.envelope?.script){
  const expected=i.output_blocks??(i.output==null?[]:[i.output]);
  const html=c.toolDetailBody(i,{dataset:{operation:'call'}},24);
  const shared=expected.filter((block,index)=>!i.exec_view?.consumed?.includes(index)
   && !(i.exec_view?.headers?.[index] && typeof block==='string' && block.length===i.exec_view.headers[index]));
  check((html.match(/class="ordered-output-block"/g)||[]).length===shared.length,'missing shared return block');
  for(const row of i.exec_view?.rows||[]){
   if(row.media_block!=null)check(expected[row.media_block]?.type==='image','missing image source');
  }
  check(html.includes('command-orchestration'),'missing script');
  totals.blocks+=expected.length;
 }
 for(let n=0;n<ops.length;n++){
  const op=ops[n],html=c.toolDetailBody(i,{dataset:{operation:String(n)}},24);
  const mcp=html.includes('class="mcp-detail"');
  check(mcp||html.includes('command-execution'),'missing detail');
  if(!mcp&&!i.envelope?.script&&!i.standalone_native&&!i.native_results?.length&&!i.native_actions?.length)check(html.includes('command-orchestration'),'missing original');
  kinds[op.kind]=(kinds[op.kind]||0)+1;
  if(op.resultRef!=null||op.search||['run','session'].includes(op.kind)){
   totals.shell++;
   if(html.includes('>命令结果未确认<')){
    totals.unknown++;
    console.log('unconfirmed',file,i.index,n,i.output==null?'awaiting return':'inspect result');
   }
  }
 }
}).on('close',()=>console.log(JSON.stringify({totals,kinds})));
"""

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', help='include tool calls recorded before this UTC timestamp')
    parser.add_argument('rollouts', type=Path, nargs='+')
    args = parser.parse_args()
    proc = subprocess.Popen(['node','-e',RENDER],cwd=ROOT,stdin=subprocess.PIPE,text=True)
    with proc.stdin as pipe:
        for file_no, path in enumerate(args.rollouts, 1):
            items, *_ = server.parse_history(path)
            page = server.page_payload(items, {'start':['0']})
            for summary in page['items']:
                if summary.get('kind')!='tool' or (args.before and summary['time']>=args.before):
                    continue
                ix=summary['index']
                item=server.page_payload(items, {'item':[str(ix)]})['item']
                if summary['operations']!=server.classification.summaries(item['operations']):
                    raise ValueError(f'rollout {file_no} item {ix}: summary and detail differ')
                pipe.write(json.dumps([file_no,item])+'\n')
    return proc.wait()

if __name__=='__main__':
    sys.exit(main())
