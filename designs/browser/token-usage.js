// Recorded token analytics. All charts are local SVG with keyboard-accessible drilldown.
/* global t, tp, formatNumber, formatDate, I18n */
let tokenTypes=[],heatMetrics=[];
function initTokenTypes(){tokenTypes=[['input',t('usage.type.input'),'#66849b'],['cached',t('usage.type.cached'),'#a7bac8'],['cache_write',t('usage.type.cacheWrite'),'#cfb17c'],['output',t('usage.type.output'),'#698b76'],['reasoning',t('usage.type.reasoning'),'#b6c7bc']];}
let usageDialog,usageButton,usageGlobalButton,priceSettingsDialog,priceSettingsButton;
let usageScope = 'session';
let usageScopeId = '';
let usageDirectory = '';
let usageDimension = 'session';
let usageSelected = '';
let usageDay = '';
let usageWindowOffset = 0;
let usageWindowDays = 30;
let usageSort = 'total';
let usageSortDirection = 'desc';
let usageData = null;
let usageRequest = 0;
const usageExactNumber = number => formatNumber(Number(number),{maximumFractionDigits:12});
const usageNumber = number => Number(number)>=1000?formatNumber(Number(number)/1000,{maximumFractionDigits:1})+'K':formatNumber(Number(number),{maximumFractionDigits:1});
const usageCompact = usageNumber;
const usageTotal = tokens => tokenTypes.reduce((total,[key])=>total+(tokens[key]||0),0);
function tokenBreakdown(tokens,precise=false){
 const total = usageTotal(tokens);
 return tokenTypes.filter(([key])=>tokens[key]).map(([key,label])=>t('usage.breakdownPart',{label,count:precise?usageExactNumber(tokens[key]):usageNumber(tokens[key]),percent:(100*tokens[key]/total).toFixed(1)})).join(t('usage.breakdownSep')) || '0 token';
}
function tokenStack(tokens){
 const total = usageTotal(tokens);
 let offset = 0;
 const segments = tokenTypes.map(([key,,color])=>{
  const width = total ? 100*(tokens[key]||0)/total : 0;
  const segment = '<rect x="'+offset+'" y="0" width="'+width+'" height="12" fill="'+color+'"/>';
  offset += width;
  return segment;
 }).join('');
 return '<svg class="usage-stack" viewBox="0 0 100 12" preserveAspectRatio="none" role="img" aria-label="'+esc(tokenBreakdown(tokens))+'"><title>'+esc(tokenBreakdown(tokens,true))+'</title>'+segments+'</svg>';
}
async function openUsage(options = {}){
 usageSort='total';usageSortDirection='desc';
 usageScope = options.scope || 'session';
 usageScopeId = usageScope === 'all' ? '' : (options.scopeId ?? current ?? '');
 if(usageScope === 'session' && !usageScopeId)return;
 const thread = threads.find(thread=>thread.id===usageScopeId);
 usageDirectory = options.directory ?? thread?.cwd ?? '';
 usageDimension = {all:'directory',directory:'session',session:'turn'}[usageScope];
 usageSelected = options.selected || '';
 usageDay = '';
 usageWindowOffset = 0;
 usageWindowDays = 30;
 if(!usageDialog.open)usageDialog.showModal();
 activateDialogEntry(usageDialog,options.opener);
 await loadUsage();
}
let usageAbort=null;
function usageLoading(){
 return '<div class="usage-loading" role="status"><span class="usage-loading-spinner" aria-hidden="true">'+uiIcon('LoaderCircle')+'</span><strong>'+t('usage.loadingTitle')+'</strong><span class="usage-loading-detail">'+t('usage.loadingReading')+'</span><div class="usage-loading-track" role="progressbar" aria-label="'+t('usage.loadingProgressAria')+'"><span></span></div><small>'+t('usage.loadingHint')+'</small></div>';
}
function updateUsageProgress(progress){
 const loading=usageDialog.querySelector('.usage-loading');if(!loading)return;
 const completed=Math.max(0,progress.completed),total=Math.max(0,progress.total);
 loading.querySelector('.usage-loading-detail').textContent=completed===total?t('usage.scanSummarizing'):tp('usage.scanProgress',total,{completed,total});
 const track=loading.querySelector('.usage-loading-track');
 track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax',String(total||1));track.setAttribute('aria-valuenow',String(completed));
 track.querySelector('span').style.transform='scaleX('+(total?completed/total:0)+')';
}
async function streamedUsage(query,signal,onProgress){
 query.set('stream','1');
 const response=await fetch('/api/usage?'+query,{signal});
 if(!response.ok){const error=await response.json();throw Error(apiMessage(error)||t('usage.requestFailed'))}
 const reader=response.body.getReader(),decoder=new TextDecoder();
 let buffer='',result;
 const consume=line=>{
  if(!line.trim())return;
  const event=JSON.parse(line);
  if(event.type==='progress')onProgress(event);
  else if(event.type==='error')throw Error(apiMessage(event));
  else if(event.type==='result')result=event.data;
 };
 try{
  while(true){
   const {done,value}=await reader.read();buffer+=decoder.decode(value,{stream:!done});
   let newline;while((newline=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,newline));buffer=buffer.slice(newline+1)}
   if(done)break;
  }
  consume(buffer);
  if(!result)throw Error(t('usage.streamInterrupted'));
  return result;
 }finally{reader.releaseLock()}
}

async function loadUsage(){
 const request = ++usageRequest;
 usageAbort?.abort();usageAbort=new AbortController();
 const signal=usageAbort.signal;
 hideUsageTooltip();
 const body = usageDialog.querySelector('.usage-body');
 body.setAttribute('aria-busy','true');
 body.innerHTML=usageLoading();
 renderUsageBreadcrumb();
 try{
  const query = new URLSearchParams({scope:usageScope, scope_id:usageScopeId, dimension:usageDimension, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Singapore'});
  if(usageSelected)query.set('selected',usageSelected);
  if(usageDay)query.set('day',usageDay);
  const result=await streamedUsage(query,signal,progress=>{if(request===usageRequest&&usageDialog.open)updateUsageProgress(progress)});
  if(request!==usageRequest||!usageDialog.open)return;
  usageData = result;
  if(usageScope==='session'&&!usageDirectory)usageDirectory=result.scope_directory;
  renderUsageBreadcrumb();
  renderUsage();
 }catch(error){
  if(error.name!=='AbortError'&&request===usageRequest)body.innerHTML='<p>'+esc(error.message)+'</p><button class="usage-retry">'+t('usage.retry')+'</button>';
 }finally{if(request===usageRequest)body.setAttribute('aria-busy','false')}
}
function usageBucketCost(bucket,pricing){
 if(!bucket)return null;
 if(pricing?.basis==='purchase'&&!pricing.credit_rule)return null;
 if(!bucket.total)return 0;
 const cost=bucket.cost;
 if(!cost?.rated_tokens||cost.value==null)return null;
 const value=Number(cost.value);
 return Number.isFinite(value)&&value>=0?value:null;
}
function usageCostAxisNumber(value){
 if(!value)return '0';
 if(value>=1000)return usageCompact(value);
 return value<.000001?value.toExponential(1):formatNumber(value,{maximumSignificantDigits:3});
}
// The API supplies consecutive local date labels between the first and last record.
function usageTrendWindow(){
 const {buckets,calendar_today}=usageData;
 if(usageDay||!buckets.length)return {buckets};
 const dayMs=86400000;
 const first=Date.parse(buckets[0].label);
 const last=Math.max(Date.parse(calendar_today),Date.parse(buckets[buckets.length-1].label));
 const count=Math.max(30,(last-first)/dayMs+1);
 const size=Math.min(count,usageWindowDays),max=count-size;
 const offset=Math.min(usageWindowOffset,max);
 const start=last-(offset+size-1)*dayMs;
 const visible=Array.from({length:size},(_,i)=>{
  const date=start+i*dayMs;
  return buckets[(date-first)/dayMs]||{label:new Date(date).toISOString().slice(0,10),tokens:{},total:0};
 });
 return {buckets:visible,count,size,offset,last,range:t('usage.rangeTo',{start:visible[0].label,end:visible[size-1].label})};
}
function usageTrendControl(view){
 if(!view.range)return '';
 return '<div class="usage-window"><div><span class="usage-window-range">'+view.range+'</span>'+
  '<button class="usage-window-reset" '+(!view.offset&&view.size===30?'disabled':'')+'>'+t('usage.windowReset')+'</button></div>'+
  '<div class="usage-overview"><div class="usage-window-slider"></div></div>'+
  '<small>'+t('usage.windowHint')+'</small></div>';
}
function usageOverviewSVG(view){
 const dayMs=86400000,origin=view.last-(view.count-1)*dayMs;
 const byDay=new Map(usageData.buckets.map(bucket=>[bucket.label,bucket.total]));
 // The navigator can include padding before the first record and after the
 // last one. Plot those days too, rather than drawing a ramp across the gap.
 const totals=Array.from({length:view.count},(_,index)=>byDay.get(new Date(origin+index*dayMs).toISOString().slice(0,10))||0);
 const peak=totals.reduce((max,total)=>Math.max(max,total),1);
 const points=totals.map((total,index)=>((index+.5)/view.count*1000).toFixed(2)+','+(34-32*total/peak).toFixed(2));
 return '<svg aria-hidden="true" viewBox="0 0 1000 36" preserveAspectRatio="none"><polygon points="0,36 0,34 '+points.join(' ')+' 1000,34 1000,36"/></svg>';
}
function mountUsageNavigator(view){
 const slider=usageDialog.querySelector('.usage-window-slider');
 if(!slider)return;
 const dayMs=86400000,origin=view.last-(view.count-1)*dayMs;
 const dateAt=index=>formatDate(new Date(origin+index*dayMs),{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'});
 slider.insertAdjacentHTML('beforebegin',usageOverviewSVG(view));
 const end=view.count-view.offset;
 const api=noUiSlider.create(slider,{start:[end-view.size,end],range:{min:0,max:view.count},
  step:1,margin:1,connect:true,behaviour:'tap-drag',animate:false,
  handleAttributes:[{'aria-label':t('usage.handleStartAria')},{'aria-label':t('usage.handleEndAria')}]});
 const handles=slider.querySelectorAll('[role="slider"]');
 api.on('update',(_values,_handle,values)=>{
  const [start,end]=values.map(Math.round);
  handles[0].setAttribute('aria-valuetext',dateAt(start));
  handles[1].setAttribute('aria-valuetext',dateAt(end-1));
  const days=end-start,offset=view.count-end;
  if(days===usageWindowDays&&offset===usageWindowOffset)return;
  usageWindowDays=days;usageWindowOffset=offset;
  const next=usageTrendWindow();
  hideUsageTooltip();
  usageDialog.querySelector('.usage-window-range').textContent=next.range;
  usageDialog.querySelector('.usage-window-reset').disabled=!offset&&days===30;
  usageDialog.querySelector('.usage-chart-scroll').outerHTML=usageSVG(next.buckets);
  usageDialog.querySelector('.usage-chart-note').textContent=usageCostTrendNote(next.buckets);
 });
 usageDialog.querySelector('.usage-window-reset').onclick=()=>api.set([view.count-30,view.count]);
}
function usageCostTrendNote(buckets=usageData.buckets){
 const pricing=usageData.pricing;
 if(!buckets.length)return '';
 let note=t('usage.trendNote.base',{unit:pricing?.unit?' '+pricing.unit:''});
 if(pricing?.basis==='purchase'&&!pricing.credit_rule)return note+t('usage.trendNote.needRule');
 if(buckets.some(bucket=>usageBucketCost(bucket,pricing)==null))note+=t('usage.trendNote.breaks');
 if(buckets.some(bucket=>usageBucketCost(bucket,pricing)!=null&&bucket.cost?.unrated_tokens>0))note+=t('usage.trendNote.partial');
 return note;
}
function usageSVG(buckets=usageData.buckets){
 const pricing=usageData.pricing;
 if(!buckets.length)return '<p class="context-note">'+t('usage.chart.empty')+'</p>';
 const height=228,top=26,bottom=36;
 const max=Math.max(1,...buckets.map(bucket=>bucket.total));
 const costs=buckets.map(bucket=>usageBucketCost(bucket,pricing));
 const knownCosts=costs.filter(value=>value!=null),hasCosts=knownCosts.length>0;
 const maxCost=Math.max(0,...knownCosts)||1;
 const left=Math.max(48,usageCompact(max).length*6+12),right=Math.max(64,usageCostAxisNumber(maxCost).length*6+16);
 const body=typeof usageDialog==='undefined'?null:usageDialog.querySelector('.usage-body');
 const bodyStyle=body?getComputedStyle(body):null;
 const availableWidth=body?body.clientWidth-parseFloat(bodyStyle.paddingLeft)-parseFloat(bodyStyle.paddingRight):0;
 const width=(usageDay?Math.max(600,availableWidth,buckets.length*32+left+right):Math.max(260,availableWidth)),plotRight=width-right;
 const plotWidth=plotRight-left,plotHeight=height-top-bottom,step=plotWidth/buckets.length;
 const y=value=>top+plotHeight*(1-value/max),costY=value=>top+plotHeight*(1-value/maxCost);
 let elements='<text class="usage-axis-title" x="'+left+'" y="12">Token</text><text class="usage-axis-title usage-cost-axis" x="'+plotRight+'" y="12" text-anchor="end">'+esc(pricing?.unit?t('usage.axis.withUnit',{label:pricing?.basis==='credits'?t('usage.axis.spend'):t('usage.axis.cost'),unit:pricing.unit}):(pricing?.basis==='credits'?t('usage.axis.spend'):t('usage.axis.cost')))+'</text>';
 for(let level=0;level<=4;level++){
  const value=max*level/4;
  elements+='<line x1="'+left+'" x2="'+plotRight+'" y1="'+y(value)+'" y2="'+y(value)+'" class="usage-gridline"/><text x="'+(left-6)+'" y="'+(y(value)+3)+'" text-anchor="end">'+usageCompact(Math.round(value))+'</text>';
  if(hasCosts)elements+='<text class="usage-cost-axis" x="'+(plotRight+8)+'" y="'+(y(value)+3)+'">'+esc(usageCostAxisNumber(maxCost*level/4))+'</text>';
 }
 if(!hasCosts)elements+='<text class="usage-cost-axis" x="'+(plotRight+8)+'" y="'+(top+12)+'">'+t('usage.axis.unrated')+'</text>';
 buckets.forEach((bucket,index)=>{
  const x=left+step*(index+.5),barWidth=Math.min(26,step*.75);
  let used=0,shape='';
  tokenTypes.forEach(([key,,color])=>{
   const value=bucket.tokens[key]||0;
   if(value)shape+='<rect x="'+(x-barWidth/2)+'" y="'+y(used+value)+'" width="'+barWidth+'" height="'+Math.max(.5,plotHeight*value/max)+'" fill="'+color+'"/>';
   used+=value;
  });
  const costLabel=costs[index]==null?estimatedCostLabel(bucket.cost,pricing,true):bucket.total?estimatedCostLabel(bucket.cost,pricing,true):'0'+(pricing?.unit?' '+pricing.unit:'');
  elements+='<g role="button" tabindex="0" '+(!usageDay?'data-usage-day':'data-usage-hour')+'="'+esc(bucket.label)+'" aria-label="'+esc(t('usage.barAria',{label:bucket.label,total:usageNumber(bucket.total),breakdown:tokenBreakdown(bucket.tokens),costHeading:usageCostHeading(pricing),cost:costLabel}))+'">'+shape+'<rect class="usage-hit" x="'+(x-step/2)+'" y="'+top+'" width="'+step+'" height="'+plotHeight+'"/></g>';
  const label=usageDay?bucket.label.slice(0,2):bucket.label.slice(5);
  if(index%Math.max(1,Math.ceil(32/step))===0)elements+='<text x="'+x+'" y="'+(height-12)+'" text-anchor="middle">'+esc(label)+'</text>';
 });
 costs.forEach((value,index)=>{
  if(value==null)return;
  const x=left+step*(index+.5),partial=buckets[index].cost?.unrated_tokens>0;
  if(index>0&&costs[index-1]!=null){
   const partialSegment=partial||buckets[index-1].cost?.unrated_tokens>0;
   elements+='<path class="usage-line'+(partialSegment?' is-partial':'')+'" aria-hidden="true" d="M'+(x-step)+' '+costY(costs[index-1])+'L'+x+' '+costY(value)+'"/>';
  }
  elements+='<circle cx="'+x+'" cy="'+costY(value)+'" r="3" class="usage-point'+(partial?' is-partial':'')+'" aria-hidden="true"/>';
 });
 return '<div class="usage-chart-scroll"><svg viewBox="0 0 '+width+' '+height+'" width="'+width+'" height="228" role="group" aria-label="'+t('usage.chartAria',{grain:usageDay?t('usage.grain.hour'):t('usage.grain.day'),costHeading:usageCostHeading(pricing)})+'">'+elements+'</svg></div>';
}
function resizeUsageTrend(){
 if(!usageDialog)return;
 const chart=usageDialog.querySelector('.usage-chart-scroll');
 if(usageDialog.open&&chart&&usageData){hideUsageTooltip();chart.outerHTML=usageSVG(usageTrendWindow().buckets)}
}
window.addEventListener('resize',()=>requestAnimationFrame(resizeUsageTrend));
// A calendar stays at daily granularity while the trend below drills into hours.
let usageHeatMetric=localStorage.getItem('usage-heat-metric')||'cost';
let usageHeatYear=null;

function heatValue(bucket){
 if(!bucket)return 0;
 if(usageHeatMetric==='cost')return usageBucketCost(bucket,usageData?.pricing);
 return usageHeatMetric==='total'?bucket.total:bucket.tokens[usageHeatMetric]||0;
}
function heatLabel(bucket){
 if(usageHeatMetric==='cost'){
  if(!bucket||!bucket.total)return t('usage.heat.noUsage');
  return estimatedCostLabel(bucket.cost,usageData.pricing,true);
 }
 return usageExactNumber(heatValue(bucket)||0)+' token';
}
function usageHeatmap(){
 if(usageDay)return usageHourlyHeatmap();
 const daily=usageData.daily||[],today=usageData.calendar_today||new Date().toISOString().slice(0,10);
 const latest=Math.max(Number(today.slice(0,4)),...daily.map(bucket=>Number(bucket.label.slice(0,4))));
 const earliest=Math.min(latest,...daily.map(bucket=>Number(bucket.label.slice(0,4))));
 usageHeatYear=Math.max(earliest,Math.min(latest,usageHeatYear??latest));
 if(!heatMetrics.some(([key])=>key===usageHeatMetric))usageHeatMetric='cost';
 const year=usageHeatYear,byDay=new Map(daily.map(bucket=>[bucket.label,bucket]));
 const yearBuckets=daily.filter(bucket=>bucket.label.startsWith(year+'-'));
 const max=Math.max(0,...yearBuckets.map(bucket=>heatValue(bucket)||0));
 const start=new Date(Date.UTC(year,0,1)),end=new Date(Date.UTC(year+1,0,1));
 const offset=start.getUTCDay(),days=Math.round((end-start)/86400000),columns=Math.ceil((offset+days)/7),step=16,left=30;
 let cells='',months='';
 for(let i=0;i<days;i++){
  const date=new Date(start.getTime()+i*86400000),key=date.toISOString().slice(0,10),column=Math.floor((offset+i)/7),row=(offset+i)%7;
  const bucket=byDay.get(key),value=heatValue(bucket),partial=usageHeatMetric==='cost'&&bucket?.cost?.unrated_tokens>0&&bucket.cost.rated_tokens>0;
  const level=value==null?'unknown':value>0?Math.min(4,Math.ceil(value/max*4)):0;
  const label=key+' · '+heatLabel(bucket)+(partial?t('usage.heat.partialSuffix'):'');
  const future=key>today;
  cells+='<g'+(!future?' role="button" tabindex="0" data-usage-day="'+key+'"':'')+' class="heat-day'+(future?' is-future':'')+'" aria-label="'+esc(label)+'"><rect x="'+(left+column*step)+'" y="'+(24+row*step)+'" width="12" height="12" rx="2" class="heat-level-'+level+(partial?' heat-partial':'')+(key===usageDay?' is-selected':'')+'"/></g>';
  if(date.getUTCDate()===1)months+='<text x="'+(left+column*step)+'" y="13">'+formatDate(date,{month:'short',timeZone:'UTC'})+'</text>';
 }
 const metricLabel=heatMetrics.find(([key])=>key===usageHeatMetric)[1];
 return '<section class="usage-heatmap" aria-label="'+t('usage.heat.dailyAria')+'"><div class="heat-heading"><h3>'+t('usage.heat.dailyTitle')+'</h3><details class="heat-metric"><summary>'+esc(metricLabel)+uiIcon('ChevronDown','inline-icon')+'</summary><div>'+heatMetrics.map(([key,label])=>'<button data-heat-metric="'+key+'" aria-pressed="'+(usageHeatMetric===key)+'">'+esc(label)+'</button>').join('')+'</div></details><div class="heat-year"><button data-heat-year="'+(year-1)+'" aria-label="'+t('usage.heat.prevYear')+'" '+(year<=earliest?'disabled':'')+'>'+uiIcon('ChevronLeft')+'</button><span>'+year+'</span><button data-heat-year="'+(year+1)+'" aria-label="'+t('usage.heat.nextYear')+'" '+(year>=latest?'disabled':'')+'>'+uiIcon('ChevronRight')+'</button></div></div><div class="heat-scroll"><svg width="'+(left+columns*step)+'" height="140" role="group" aria-label="'+t('usage.heat.yearAria',{year,metric:metricLabel})+'">'+'<defs><pattern id="heat-unknown-pattern" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="4" fill="var(--bg)"/><path d="M0 4L4 0" stroke="var(--line)" stroke-width="2"/></pattern></defs>'+months+[[t('usage.heat.weekday.mon'),1],[t('usage.heat.weekday.wed'),3],[t('usage.heat.weekday.fri'),5]].map(([label,row])=>'<text x="2" y="'+(34+row*step)+'">'+label+'</text>').join('')+cells+'</svg></div><div class="heat-footer"><span class="heat-inspect" role="status">'+t('usage.heat.inspectDay')+'</span><span class="heat-scale">'+t('usage.heat.scaleLess')+' '+[0,1,2,3,4].map(level=>'<i class="heat-level-'+level+'"></i>').join('')+' '+t('usage.heat.scaleMore')+(usageHeatMetric==='cost'?'<i class="heat-level-unknown"></i> '+t('usage.heat.scaleUnrated'):'')+'</span></div><p class="heat-caption">'+t('usage.heat.captionDay')+(max?t('usage.heat.captionMax',{value:usageHeatMetric==='cost'?usageExactNumber(max)+' '+(usageData.pricing?.unit||'USD'):usageNumber(max)+' token'}):'')+(usageHeatMetric==='cost'?t('usage.heat.captionPartial'):'')+'</p></section>';
}
function usageHourlyHeatmap(){
 const buckets=usageData.buckets,maximum=Math.max(0,...buckets.map(bucket=>heatValue(bucket)||0));
 const metricLabel=heatMetrics.find(([key])=>key===usageHeatMetric)?.[1]||t('usage.heat.metricFallback');
 const cells=buckets.map(bucket=>{
  const value=heatValue(bucket),level=value==null?'unknown':value>0?Math.min(4,Math.ceil(value/maximum*4)):0;
  const partial=usageHeatMetric==='cost'&&bucket.cost?.unrated_tokens>0&&bucket.cost.rated_tokens>0;
  const label=usageDay+' '+bucket.label+' · '+heatLabel(bucket)+(partial?t('usage.heat.partialSuffix'):'');
  return '<button class="heat-hour" data-usage-hour="'+esc(bucket.label)+'" aria-label="'+esc(label)+'"><i class="heat-level-'+level+(partial?' heat-hour-partial':'')+'" aria-hidden="true"></i><span>'+esc(bucket.label)+'</span></button>';
 }).join('');
 return '<section class="usage-heatmap" aria-label="'+t('usage.heat.hourlyAria')+'"><div class="heat-heading"><h3>'+t('usage.heat.hourlyTitle')+'</h3><details class="heat-metric"><summary>'+esc(metricLabel)+uiIcon('ChevronDown','inline-icon')+'</summary><div>'+heatMetrics.map(([key,label])=>'<button data-heat-metric="'+key+'" aria-pressed="'+(usageHeatMetric===key)+'">'+esc(label)+'</button>').join('')+'</div></details><span class="heat-date">'+esc(usageDay)+'</span></div><div class="heat-hours" role="group" aria-label="'+t('usage.heat.hoursAria',{day:usageDay,metric:metricLabel})+'">'+cells+'</div><div class="heat-footer"><span class="heat-inspect" role="status">'+t('usage.heat.inspectHour')+'</span><span class="heat-scale">'+t('usage.heat.scaleLess')+' '+[0,1,2,3,4].map(level=>'<i class="heat-level-'+level+'"></i>').join('')+' '+t('usage.heat.scaleMore')+(usageHeatMetric==='cost'?'<i class="heat-level-unknown"></i> '+t('usage.heat.scaleUnrated'):'')+'</span></div><p class="heat-caption">'+t('usage.heat.captionHour')+(maximum?t('usage.heat.captionMax',{value:usageHeatMetric==='cost'?usageExactNumber(maximum)+' '+(usageData.pricing?.unit||'USD'):usageNumber(maximum)+' token'}):'')+(usageHeatMetric==='cost'?t('usage.heat.captionPartial'):'')+'</p></section>';
}

function refreshUsageHeatmap(){
 hideUsageTooltip();
 const current=usageDialog.querySelector('.usage-heatmap');if(current)current.outerHTML=usageHeatmap();
}
let usageTooltip,usageTooltipTarget=null;
function hideUsageTooltip(){if(usageTooltip)usageTooltip.hidden=true;usageTooltipTarget=null}
function tooltipNumber(value){
 const n=Number(value||0),unit=n>=1e9?'B':n>=1e6?'M':n>=1e3?'K':'',scale={B:1e9,M:1e6,K:1e3}[unit]||1;
 return formatNumber(n/scale,{maximumFractionDigits:unit?1:0})+unit;
}
function cacheHitStats(tokens={}){
 const cached=tokens.cached||0,input=(tokens.input||0)+cached+(tokens.cache_write||0);
 return {cached,input,label:usageCoveragePercent(cached,input,2)};
}
function cacheHitSummary(tokens){
 const hit=cacheHitStats(tokens);
 return '<div class="usage-cache-hit"><span>'+t('usage.cacheHit')+'</span><b>'+esc(hit.label)+'</b><small title="'+esc(t('usage.cacheHitRatio',{cached:usageExactNumber(hit.cached),input:usageExactNumber(hit.input)}))+'">'+t('usage.cacheHitRatio',{cached:usageNumber(hit.cached),input:usageNumber(hit.input)})+'</small></div>';
}
function cacheHitTooltip(tokens){
 const hit=cacheHitStats(tokens);
 return '<div class="usage-tooltip-cache"><div><span>'+t('usage.cacheHit')+'</span><b>'+esc(hit.label)+'</b></div><small>'+t('usage.cacheHitRatio',{cached:usageExactNumber(hit.cached),input:usageExactNumber(hit.input)})+'</small></div>';
}

function showUsageTooltip(target,event){
 if(!target||!usageData)return;
 const isHour=target.hasAttribute('data-usage-hour'),key=isHour?target.dataset.usageHour:target.dataset.usageDay;
 const bucket=(isHour?usageData.buckets:usageData.daily||[]).find(item=>item.label===key)||{total:0,tokens:{},cost:null};
 const label=isHour?usageDay+' '+key:key;
 usageTooltipTarget=target;
 usageTooltip.innerHTML='<div class="usage-tooltip-date">'+esc(label)+'</div><div class="usage-tooltip-total"><span>'+t('usage.tooltip.total')+'</span><strong>'+tooltipNumber(bucket.total)+'</strong></div><div class="usage-tooltip-exact">'+usageExactNumber(bucket.total)+' token</div><div class="usage-tooltip-price"><span>'+esc(usageCostHeading(usageData.pricing))+'</span><b>'+esc(bucket.total?estimatedCostLabel(bucket.cost,usageData.pricing,true):'—')+'</b></div>'+cacheHitTooltip(bucket.tokens)+'<div class="usage-tooltip-types">'+tokenTypes.filter(([key])=>bucket.tokens[key]).map(([key,name,color])=>'<div><span><svg width="7" height="7" aria-hidden="true"><rect width="7" height="7" rx="1" fill="'+color+'"/></svg>'+name+'</span><b>'+tooltipNumber(bucket.tokens[key])+'</b><small>'+(100*bucket.tokens[key]/bucket.total).toFixed(1)+'%</small></div>').join('')+'</div>'+(!bucket.total?'<p>'+t('usage.heat.noUsage')+'</p>':'')+(bucket.cost?.unrated_tokens?'<p>'+(bucket.cost.rated_tokens?t('usage.tooltip.partialCost'):t('usage.tooltip.unratedCost'))+'</p>':'')+(!isHour?'<button data-usage-day="'+key+'">'+t('usage.tooltip.viewHours')+' '+uiIcon('ChevronRight','inline-icon')+'</button>':'');
 usageTooltip.hidden=false;
 const box=target.getBoundingClientRect(),tip=usageTooltip.getBoundingClientRect();
 const x=event?.clientX??box.x+box.width/2,y=event?.clientY??box.bottom;
 usageTooltip.style.left=Math.max(8,Math.min(x+14,window.innerWidth-tip.width-8))+'px';
 usageTooltip.style.top=Math.max(8,Math.min(y+14,window.innerHeight-tip.height-8))+'px';
}
const usageChartTarget=event=>event.target.closest('.heat-hour,.heat-day[role="button"],.usage-chart-scroll [data-usage-day],.usage-chart-scroll [data-usage-hour]');

function renderUsageBreadcrumb(){
 const crumb=(scope,id,label,active=false)=>'<button data-usage-scope="'+scope+'" data-scope-id="'+esc(id)+'" '+(active?'aria-current="page"':'')+' title="'+esc(label)+'">'+esc(label)+'</button>';
 const thread=threads.find(thread=>thread.id===usageScopeId);
 let html=crumb('all','',t('usage.crumb.all'),usageScope==='all');
 if(usageScope!=='all'){
  const directory=usageScope==='directory'?usageScopeId:usageDirectory;
  html+=uiIcon('ChevronRight','breadcrumb-chevron')+crumb('directory',directory,directory?directoryName(directory):t('navigation.unnamedDirectory'),usageScope==='directory');
  if(usageScope==='session'){
   html+=uiIcon('ChevronRight','breadcrumb-chevron')+crumb('session',usageScopeId,thread?threadTitle(thread):(usageData?.scope_label||t('usage.crumb.session')),!usageSelected);
   if(usageSelected){
    const turn=usageData?.groups.find(group=>group.id===usageSelected);
    const label=turn?usageGroupLabel(turn):t('usage.crumb.turn');
    html+=uiIcon('ChevronRight','breadcrumb-chevron')+'<span class="usage-current-turn" aria-current="page" title="'+esc(turn?usageGroupLabel(turn):t('usage.crumb.turnTitle'))+'">'+esc(label)+'</span>';
   }
  }
 }
 usageDialog.querySelector('.usage-breadcrumb').innerHTML=html;
 $('#usage-title').textContent=usageSelected?t('usage.title.turn'):{all:t('usage.title.all'),directory:t('usage.title.directory'),session:t('usage.title.session')}[usageScope];
}
function modelBreakdown(d){
 if(!d.models?.length)return '';
 const rows=d.models.map(row=>'<tr><th scope="row">'+esc(row.model||t('usage.models.unrecorded'))+'</th><td>'+esc(usageExactNumber(row.total))+'</td><td title="'+esc(estimatedCostLabel(row.cost,d.pricing,true))+'">'+esc(estimatedCostLabel(row.cost,d.pricing,false,false))+'</td></tr>').join('');
 return '<section class="usage-models"><h3>'+t('usage.models.title')+'</h3><table><thead><tr><th>'+t('usage.models.colModel')+'</th><th>'+t('usage.models.colTotal')+'</th><th>'+esc(usageCostHeading(d.pricing))+'</th></tr></thead><tbody>'+rows+'</tbody></table></section>';
}
function renderUsage(){
 hideUsageTooltip();
 const d=usageData,selected=d.groups.find(group=>group.id===usageSelected);
 const view=usageTrendWindow();
 const groups=(usageSelected?d.groups.filter(group=>group.id===usageSelected):[...d.groups]).sort(compareUsageGroups);
 usageDialog.querySelector('.usage-body').innerHTML=
 (usageSelected?'<div class="usage-turn-filter"><span title="'+esc(selected?usageGroupTooltip(selected):t('usage.filter.unrecorded'))+'">'+esc(selected?usageGroupLabel(selected):t('usage.filter.unrecorded'))+'</span><button class="usage-clear-turn">'+t('usage.filter.clearTurn')+'</button></div>':'')+
 (usageDay?'<div class="usage-date-filter"><button class="usage-days">'+t('usage.filter.allDates')+'</button>'+uiIcon('ChevronRight','breadcrumb-chevron')+'<span>'+esc(usageDay)+'</span></div>':'')+
 '<div class="usage-summary"><div><span>'+(usageDay?t('usage.summary.totalDay',{day:usageDay}):t('usage.summary.totalAll'))+'</span><strong title="'+esc(usageExactNumber(d.total)+' token')+'">'+(usageSelected&&!selected?t('common.unrecorded'):usageNumber(d.total))+'</strong></div>'+tokenStack(d.tokens)+'</div>'+
 cacheHitSummary(d.tokens)+pricingSummary(d)+modelBreakdown(d)+usageHeatmap()+'<div class="usage-legend">'+tokenTypes.map(([key,label,color])=>'<span><svg width="8" height="8" aria-hidden="true"><rect width="8" height="8" fill="'+color+'"/></svg>'+label+' <b title="'+esc(usageExactNumber(d.tokens[key])+' token')+'">'+usageNumber(d.tokens[key])+'</b></span>').join('')+'<span class="usage-cost-legend"><svg width="18" height="8" aria-hidden="true"><path d="M1 4h16" stroke="currentColor" stroke-width="2"/><circle cx="9" cy="4" r="2.5" fill="currentColor"/></svg>'+t('usage.legend.costLine',{heading:usageCostHeading(d.pricing)})+'</span></div>'+
 '<div class="usage-chart-heading"><span>'+ (usageDay?t('usage.chart.headingHour',{day:usageDay}):t('usage.chart.headingDay'))+'</span><small>'+t('usage.chart.sub',{heading:usageCostHeading(d.pricing)})+'</small></div>'+
 usageSVG(view.buckets)+usageTrendControl(view)+'<p class="usage-chart-note">'+esc(usageCostTrendNote(view.buckets))+'</p><p class="usage-inspect" role="status"></p>'+
 '<p class="usage-coverage">'+t('usage.coverage.base',{timezone:d.timezone})+(d.missing_sessions?tp('usage.coverage.missingSessions',d.missing_sessions,{count:d.missing_sessions}):'')+(d.undated_tokens?t('usage.coverage.undated',{tokens:usageNumber(d.undated_tokens)}):'')+'</p>'+
 '<div class="usage-group-heading"><span>'+t('usage.groups.heading',{dimension:{turn:t('usage.dim.turn'),session:t('usage.dim.session'),directory:t('usage.dim.directory')}[usageDimension]})+'</span><input type="search" class="usage-filter" aria-label="'+t('usage.filter.aria')+'" placeholder="'+t('usage.filter.placeholder')+'"></div>'+
 '<div class="usage-table-wrap"><table class="usage-table'+(usageDimension==='turn'?' usage-turn-table':'')+'"><thead><tr>'+(usageDimension==='turn'?usageSortHeader('turn',t('usage.dim.turn')):'')+'<th class="usage-scope">'+(usageDimension==='turn'?t('usage.table.requestSummary'):t('usage.table.scope'))+'</th>'+usageSortHeader('total',t('usage.table.total'))+usageSortHeader('cost',usageCostHeading(d.pricing))+'<th class="usage-type">'+t('usage.table.share')+'</th></tr></thead><tbody>'+groups.map(group=>'<tr>'+(usageDimension==='turn'?'<td class="usage-round">'+(group.turn_number??'—')+'</td>':'')+'<td class="usage-scope"><button data-usage-group="'+esc(group.id)+'" title="'+esc(usageGroupTooltip(group))+'" aria-pressed="'+(group.id===usageSelected)+'">'+usageGroupContent(group)+'</button></td><td class="usage-token">'+usageMetric(group.total,usageNumber(group.total),'token',usageExactNumber(group.total)+' token')+'</td><td class="usage-cost">'+usageMetric(group.cost?.rated_tokens?group.cost.value:null,estimatedCostLabel(group.cost,d.pricing,false,false),'cost',estimatedCostLabel(group.cost,d.pricing,true))+'</td><td class="usage-type">'+tokenStack(group.tokens)+'</td></tr>').join('')+'</tbody></table></div>'+
 '<p class="context-note">'+(usageScope==='directory'?t('usage.note.directory'):'')+t('usage.note.methodology')+'</p>';
 mountUsageNavigator(view);
 updateUsageMetricBars();
}
function usageMetric(value,label,type,preciseLabel=label){
 const numeric=value!=null&&Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;
 return '<div class="usage-metric" data-usage-metric="'+type+'" data-value="'+(numeric??'')+'" data-precise-label="'+esc(preciseLabel)+'" title="'+esc(preciseLabel)+'">'+(numeric!=null?'<span class="usage-metric-fill" aria-hidden="true"></span>':'')+'<span class="usage-metric-label">'+esc(label)+'</span></div>';
}
function updateUsageMetricBars(){
 const rows=[...usageDialog.querySelectorAll('.usage-table tbody tr')].filter(row=>!row.hidden);
 for(const type of ['token','cost']){
  const metrics=rows.flatMap(row=>[...row.querySelectorAll('[data-usage-metric="'+type+'"]')]).filter(metric=>metric.dataset.value!=='');
  const maximum=Math.max(0,...metrics.map(metric=>Number(metric.dataset.value)));
  for(const metric of metrics){
   const proportion=maximum>0?100*Number(metric.dataset.value)/maximum:0;
   metric.querySelector('.usage-metric-fill').style.width=proportion+'%';
   metric.title=t('usage.metric.listMax',{label:metric.dataset.preciseLabel,pct:proportion.toFixed(1)});
  }
 }
}
function compareUsageGroups(a,b){
 const value=group=>usageSort==='cost'?(group.cost?.rated_tokens?group.cost.value:null):group[usageSort==='turn'?'turn_number':'total'];
 const av=value(a),bv=value(b);
 if(av==null||bv==null)return av==null?(bv==null?a.id.localeCompare(b.id):1):-1;
 return (av-bv)*(usageSortDirection==='asc'?1:-1)||a.id.localeCompare(b.id);
}
function usageSortHeader(field,label){
 const active=usageSort===field;
 const next=active?(usageSortDirection==='asc'?'desc':'asc'):(field==='turn'?'asc':'desc');
 const action=t('usage.table.sort',{label,direction:next==='asc'?t('usage.table.sortAsc'):t('usage.table.sortDesc')});
 return '<th class="'+(field==='turn'?'usage-round':field==='cost'?'usage-cost':'usage-token')+'" aria-sort="'+(active?(usageSortDirection==='asc'?'ascending':'descending'):'none')+'"><button data-usage-sort="'+field+'" title="'+action+'" aria-label="'+action+'">'+label+uiIcon(active?(usageSortDirection==='asc'?'ArrowUp':'ArrowDown'):'ChevronDown','usage-sort-icon'+(active?' is-active':''))+'</button></th>';
}
function filterUsageGroups(value){
 const query=value.toLowerCase();
 usageDialog.querySelectorAll('.usage-table tbody tr').forEach(row=>{row.hidden=!(row.textContent+' '+(row.querySelector('[data-usage-group]')?.title||'')).toLowerCase().includes(query)});
 updateUsageMetricBars();
}
function usageGroupLabel(group){
 if(group.label_key)return t(group.label_key,group.label_params||{});
 if(usageDimension==='directory'){
  const path=String(group.id||'').replace(/\\/g,'/').replace(/\/+$/,'');
  return path.split('/').filter(Boolean).pop()||(group.id==='/'?t('usage.group.root'):group.label);
 }
 if(usageDimension==='turn')return (group.turn_number?tp('usage.group.turnN',group.turn_number,{n:group.turn_number}):t('usage.group.unlinkedTurn'))+' · '+(group.summary||(group.time?date(group.time):t('usage.group.noDialog')));
 return group.label;
}
function usageGroupTooltip(group){
 if(usageDimension==='directory')return group.id||group.label;
 return usageGroupLabel(group)+(usageDimension==='turn'?'\n'+(group.time?date(group.time)+'\n':'')+t('usage.group.modelLine',{models:group.models?.join(' / ')||t('common.unrecorded')})+'\n'+t('usage.group.turnIdLine',{id:group.turn_id||t('common.unrecorded')}):'');
}
function usageGroupContent(group){
 if(usageDimension!=='turn')return esc(usageGroupLabel(group));
 return '<span class="usage-turn-title">'+esc(group.summary||(group.time?date(group.time):t('usage.group.noDialog')))+'</span><small class="usage-turn-meta"><span class="usage-turn-model" title="'+esc(group.models?.join(' / ')||t('usage.group.modelUnrecorded'))+'">'+esc(group.models?.join(' / ')||t('usage.group.modelUnrecorded'))+'</span><span>'+esc(group.time?date(group.time):t('usage.group.timeUnrecorded'))+(group.summary_source==='reply'?t('usage.group.replySummary'):'')+'</span></small>';
}
function wireUsageUi(){
usageDialog.addEventListener('pointerover',event=>{
 const cell=event.target.closest('.heat-day,.heat-hour');if(cell)usageDialog.querySelector('.heat-inspect').textContent=cell.getAttribute('aria-label');
});
usageDialog.addEventListener('focusin',event=>{
 const cell=event.target.closest('.heat-day,.heat-hour');if(cell)usageDialog.querySelector('.heat-inspect').textContent=cell.getAttribute('aria-label');
});

usageTooltip=document.createElement('div');
usageTooltip.className='usage-tooltip';usageTooltip.id='usage-chart-tooltip';usageTooltip.hidden=true;usageTooltip.setAttribute('role','tooltip');usageDialog.append(usageTooltip);

usageDialog.addEventListener('pointerover',event=>{const target=usageChartTarget(event);if(target)showUsageTooltip(target,event);else if(!event.target.closest('.usage-tooltip'))hideUsageTooltip()});
usageDialog.addEventListener('focusin',event=>{const target=usageChartTarget(event);if(target)showUsageTooltip(target);else if(!event.target.closest('.usage-tooltip'))hideUsageTooltip()});
usageDialog.addEventListener('pointerleave',hideUsageTooltip);
usageDialog.addEventListener('scroll',()=>{if(usageTooltipTarget===document.activeElement)showUsageTooltip(usageTooltipTarget);else hideUsageTooltip()},true);
usageDialog.addEventListener('keydown',event=>{if(event.key==='Escape'&&!usageTooltip.hidden){event.preventDefault();event.stopPropagation();hideUsageTooltip()}});


 usageButton.onclick=()=>openUsage({opener:usageButton});
 usageGlobalButton.onclick=()=>openUsage({scope:'all',opener:usageGlobalButton});
 document.addEventListener('thread-loaded',()=>{usageButton.disabled=!data});
document.addEventListener('click',event=>{
 const directory=event.target.closest('[data-directory-usage]');
 if(directory)openUsage({scope:'directory',scopeId:directory.dataset.directoryUsage,opener:directory});
});
usageDialog.querySelector('.usage-close').onclick=()=>usageDialog.close();
usageDialog.querySelector('.usage-refresh').onclick=loadUsage;
usageDialog.addEventListener('close',()=>{usageRequest++;usageAbort?.abort();hideUsageTooltip()});
usageDialog.addEventListener('input',event=>{
 if(!event.target.matches('.usage-filter'))return;
 filterUsageGroups(event.target.value);
});
usageDialog.addEventListener('click',event=>{
 const heatMetric=event.target.closest('[data-heat-metric]'),heatYear=event.target.closest('[data-heat-year]');
 if(heatMetric){usageHeatMetric=heatMetric.dataset.heatMetric;localStorage.setItem('usage-heat-metric',usageHeatMetric);refreshUsageHeatmap();usageDialog.querySelector('.heat-metric summary').focus({preventScroll:true});return}
 if(heatYear){usageHeatYear=Number(heatYear.dataset.heatYear);refreshUsageHeatmap();return}
 if(event.target.closest('[data-open-price-settings]')){priceSettingsButton.click();return}
 const sort=event.target.closest('[data-usage-sort]');
 if(sort){
  const field=sort.dataset.usageSort,body=usageDialog.querySelector('.usage-body'),scroll=body.scrollTop,filter=usageDialog.querySelector('.usage-filter').value;
  usageSortDirection=usageSort===field?(usageSortDirection==='asc'?'desc':'asc'):(field==='turn'?'asc':'desc');usageSort=field;
  renderUsage();usageDialog.querySelector('.usage-filter').value=filter;filterUsageGroups(filter);body.scrollTop=scroll;
  usageDialog.querySelector('[data-usage-sort="'+field+'"]').focus({preventScroll:true});return;
 }
 const scope=event.target.closest('[data-usage-scope]');
 if(scope){openUsage({scope:scope.dataset.usageScope,scopeId:scope.dataset.scopeId,directory:usageDirectory});return}
 const group=event.target.closest('[data-usage-group]');
 if(group){
  if(usageScope==='all')openUsage({scope:'directory',scopeId:group.dataset.usageGroup});
  else if(usageScope==='directory')openUsage({scope:'session',scopeId:group.dataset.usageGroup,directory:usageScopeId});
  else{usageWindowOffset=0;usageWindowDays=30;usageSelected=group.dataset.usageGroup;usageDay='';loadUsage()}
  return;
 }
 const day=event.target.closest('[data-usage-day]');
 if(day){
  if(event.pointerType==='touch'&&!event.target.closest('.usage-tooltip')){showUsageTooltip(day,event);return}
  hideUsageTooltip();usageDay=day.dataset.usageDay;loadUsage();return
 }
 const hour=event.target.closest('[data-usage-hour]');
 if(hour){
  if(event.pointerType==='touch'||hour.matches('.heat-hour')){showUsageTooltip(hour,event);return}
  const bucket=usageData.buckets.find(item=>item.label===hour.dataset.usageHour);
  usageDialog.querySelector('.usage-inspect').textContent=bucket.label+' · '+usageNumber(bucket.total)+' token · '+tokenBreakdown(bucket.tokens)+' · '+estimatedCostLabel(bucket.cost,usageData.pricing);
  return;
 }
 if(event.target.closest('.usage-days')){usageDay='';loadUsage()}
 if(event.target.closest('.usage-clear-turn')){usageWindowOffset=0;usageWindowDays=30;usageSelected='';usageDay='';loadUsage()}
 if(event.target.closest('.usage-retry'))loadUsage();
});
usageDialog.addEventListener('keydown',event=>{
 const target=event.target.closest('[data-usage-day],[data-usage-hour]');
 if(target&&['Enter',' '].includes(event.key)){event.preventDefault();target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
});
 $('#messages').addEventListener('click',event=>{
  const turn=event.target.closest('[data-usage-turn]');
  if(turn)openUsage({selected:current+'/'+turn.dataset.usageTurn,opener:turn});
 });
}

// Price preferences and raw-source snapshots are stored by the local service.
function addUsageFullscreen(dialog,label,storageKey){
 const button=document.createElement('button');
 button.className='usage-fullscreen';
 button.setAttribute('aria-pressed','false');
 const update=full=>{
  dialog.classList.toggle('is-fullscreen',full);
  button.innerHTML=uiIcon(full?'Collapse':'Expand')+'<span>'+(full?t('common.collapse'):t('common.fullscreen'))+'</span>';
  button.setAttribute('aria-pressed',String(full));
  button.setAttribute('aria-label',t('pricing.fullscreenAria',{action:full?t('common.collapse'):t('common.expand'),label}));
  button.title=button.getAttribute('aria-label');
 };
 update(localStorage.getItem(storageKey)==='true');
 button.onclick=()=>{const full=!dialog.classList.contains('is-fullscreen');update(full);localStorage.setItem(storageKey,String(full));if(dialog===usageDialog)requestAnimationFrame(resizeUsageTrend)};
 dialog.querySelector('.usage-header').insertBefore(button,dialog.querySelector('.usage-close,.price-close'));
}
let priceState = null;
let priceBusy = false;
let creditRuleDraft = null;
async function pricePost(path, value){
 const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value)});
 const result = await response.json();
 if(!response.ok)throw Error(apiMessage(result));
 return result;
}
function priceChoices(key, choices){
 return '<div class="price-choices" role="group">'+choices.map(([value,label])=>'<button data-price-key="'+key+'" data-price-value="'+value+'" aria-pressed="'+(priceState.settings[key]===value)+'">'+label+'</button>').join('')+'</div>';
}
function creditRulesMarkup(settings){
 const draft=creditRuleDraft||settings.credit_rule||{amount:'',credits:''};
 return '<section class="credit-conversion"><h3>'+t('pricing.creditTitle')+'</h3><p class="context-note">'+t('pricing.creditNote')+'</p>'+
 '<form class="credit-rule-form"><div class="credit-rule-fields"><label>'+t('pricing.creditAmount')+'<input name="rule_amount" type="number" min="0.000000000001" max="1000000000000" step="any" inputmode="decimal" value="'+esc(draft.amount)+'" placeholder="'+t('pricing.creditAmountPh')+'" required></label><label>'+t('pricing.creditCredits')+'<input name="rule_credits" type="number" min="0.000000000001" max="1000000000000" step="any" inputmode="decimal" value="'+esc(draft.credits)+'" placeholder="'+t('pricing.creditCreditsPh')+'" required></label></div><div class="credit-rule-actions"><button type="submit">'+t('pricing.creditSave')+'</button></div></form></section>';
}
function showPriceSettings(message = ''){
 const settings=priceState.settings;
 const isApi=settings.basis==='api';
 const note=isApi?t('pricing.note.api'):settings.basis==='purchase'?t('pricing.note.purchase'):t('pricing.note.credits');
 const body=priceSettingsDialog.querySelector('.price-settings-body');
 body.innerHTML='<section><h3>'+t('pricing.basisTitle')+'</h3>'+priceChoices('basis',[['api',t('pricing.basis.api')],['purchase',t('pricing.basis.purchase')]])+
 '<p class="context-note">'+note+'</p></section>'+
 (settings.basis==='purchase'?creditRulesMarkup(settings):'')+
 (isApi?'<section><h3>'+t('pricing.sourceTitle')+'</h3>'+priceChoices('source',[['litellm','LiteLLM'],['modelsdev','models.dev']])+'</section>':'')+
 '<section><h3>'+t('pricing.missingTierTitle')+'</h3>'+priceChoices('missing_tier',[['unrated',t('pricing.missingTier.unrated')],['standard',t('pricing.missingTier.standard')]])+'</section>'+
 '<section><h3>'+t('pricing.cacheTitle')+'</h3><p class="context-note">'+t('pricing.cacheNote')+'</p>'+
 Object.entries(priceState.sources).filter(([source])=>source===(isApi?settings.source:'credits')).map(([source,info])=>'<article class="price-cache"><div><strong>'+esc({litellm:'LiteLLM',modelsdev:'models.dev',credits:'OpenAI Codex credits'}[source])+'</strong><button data-price-sync="'+source+'">'+t('pricing.cache.refresh')+'</button></div><p>'+(info.fetched_at?t('pricing.cache.syncedAt',{time:formatDate(info.fetched_at)}):t('pricing.cache.never'))+'</p><a href="'+esc(info.url)+'" target="_blank" rel="noopener noreferrer">'+t('pricing.cache.viewSource')+' '+uiIcon('ExternalLink','inline-icon')+'</a>'+(info.sha256?'<code title="'+t('pricing.cache.shaTitle')+'">'+esc(info.sha256)+'</code>':'')+'</article>').join('')+'</section>'+
 '<p class="price-feedback" role="status">'+esc(message)+'</p>';
 body.querySelectorAll('button,input').forEach(control=>control.disabled=priceBusy);
}
async function persistPriceChange(value,{sync=false,message=t('pricing.saved')}={}){
 if(priceBusy)return false;
 priceBusy=true;showPriceSettings(sync?t('pricing.downloading'):t('pricing.saving'));
 let success=false,feedback=message;
 try{priceState=await pricePost(sync?'/api/pricing/refresh':'/api/pricing/settings',value);success=true}
 catch(error){feedback=error.message}
 finally{priceBusy=false;showPriceSettings(feedback)}
 if(success&&usageDialog.open)loadUsage();
 return success;
}
function wirePriceSettings(){
 priceSettingsButton.onclick=async()=>{
  priceSettingsDialog.querySelector('.price-settings-body').textContent=t('pricing.loadingSettings');
  if(!priceSettingsDialog.open)priceSettingsDialog.showModal();
  activateDialogEntry(priceSettingsDialog,priceSettingsButton);
  try{priceState=await api('/api/pricing');showPriceSettings()}
  catch(error){priceSettingsDialog.querySelector('.price-settings-body').textContent=error.message}
 };
 priceSettingsDialog.querySelector('.price-close').onclick=()=>priceSettingsDialog.close();
 priceSettingsDialog.addEventListener('input',event=>{
  const form=event.target.closest('.credit-rule-form');if(form)creditRuleDraft=readCreditRuleDraft(form);
 });
 priceSettingsDialog.addEventListener('submit',async event=>{
  if(!event.target.matches('.credit-rule-form'))return;
  event.preventDefault();if(priceBusy)return;
  creditRuleDraft=readCreditRuleDraft(event.target);
  if(await persistPriceChange({basis:'purchase',credit_rule:creditRuleDraft},{message:t('pricing.ruleSaved')})){
   creditRuleDraft=null;showPriceSettings(t('pricing.ruleSaved'));
  }
 });
 priceSettingsDialog.addEventListener('click',async event=>{
  if(priceBusy)return;
  const option=event.target.closest('[data-price-key]'),sync=event.target.closest('[data-price-sync]');
  if(option||sync)await persistPriceChange(sync?{source:sync.dataset.priceSync}:{[option.dataset.priceKey]:option.dataset.priceValue},{sync:Boolean(sync),message:sync?t('pricing.cacheUpdated'):t('pricing.saved')});
 });
}
function readCreditRuleDraft(form){
 return {currency:'USD',amount:form.elements.namedItem('rule_amount').value,credits:form.elements.namedItem('rule_credits').value};
}
function startUsageUi(){
 initTokenTypes();
 heatMetrics=[['cost',t('usage.heat.metric.cost')],['total',t('usage.heat.metric.total')],...tokenTypes.map(([key,label])=>[key,label])];
 usageDialog=document.createElement('dialog');
 usageDialog.className='usage-drawer';
 usageDialog.id='usage-dialog';
 usageDialog.setAttribute('aria-labelledby','usage-title');
 usageDialog.innerHTML=`<header class="usage-header"><h2 id="usage-title">${t('usage.title')}</h2><button class="usage-close" aria-label="${t('usage.closeAria')}">${uiIcon('X')}</button></header>
<div class="usage-toolbar"><nav class="usage-breadcrumb" aria-label="${t('usage.breadcrumbAria')}"></nav><button class="usage-refresh" title="${t('usage.refreshAria')}" aria-label="${t('usage.refreshAria')}">${uiIcon('Reload')}</button></div>
<div class="usage-body" aria-live="polite"></div>`;
 document.body.append(usageDialog);
 usageButton=document.createElement('button');
 usageButton.innerHTML=usageEntry();
 usageButton.title=t('usage.sessionButtonTitle');
 usageButton.setAttribute('aria-label',t('usage.sessionButtonAria'));
 usageButton.disabled=!data;
 usageButton.className='usage-launch dialog-entry';
 usageButton.setAttribute('aria-expanded','false');
 usageButton.setAttribute('aria-controls','usage-dialog');
 document.querySelector('main>header').append(usageButton);
 usageGlobalButton=document.createElement('button');
 usageGlobalButton.className='usage-global dialog-entry';
 usageGlobalButton.setAttribute('aria-expanded','false');
 usageGlobalButton.setAttribute('aria-controls','usage-dialog');
 usageGlobalButton.innerHTML=usageEntry();
 usageGlobalButton.title=t('usage.globalButtonTitle');
 usageGlobalButton.setAttribute('aria-label',t('usage.globalButtonAria'));
 document.querySelector('.sidebar-footer').append(usageGlobalButton);
 priceSettingsDialog=document.createElement('dialog');
 priceSettingsDialog.className='price-settings';
 priceSettingsDialog.id='price-settings-dialog';
 priceSettingsDialog.setAttribute('aria-labelledby','price-settings-title');
 priceSettingsDialog.innerHTML='<header class="usage-header"><h2 id="price-settings-title">'+t('pricing.settingsTitle')+'</h2><button class="price-close" aria-label="'+t('pricing.closeAria')+'">'+uiIcon('X')+'</button></header><div class="price-settings-body"></div>';
 document.body.append(priceSettingsDialog);
 priceSettingsButton=document.createElement('button');
 priceSettingsButton.textContent=t('pricing.settingsTitle');
 priceSettingsButton.className='dialog-entry';
 priceSettingsButton.setAttribute('aria-expanded','false');
 priceSettingsButton.setAttribute('aria-controls','price-settings-dialog');
 usageDialog.querySelector('.usage-header').insertBefore(priceSettingsButton,usageDialog.querySelector('.usage-close'));
 addUsageFullscreen(usageDialog,t('usage.title'),'usage-fullscreen');
 addUsageFullscreen(priceSettingsDialog,t('pricing.settingsTitle'),'price-settings-fullscreen');
 wireUsageUi();
 wirePriceSettings();
}
window.__appStarted=window.__appStarted||I18n.ready;
window.__usageStarted=window.__appStarted.then(startUsageUi);
function usageCostHeading(pricing){
 if(pricing?.basis==='credits')return t('pricing.heading.credits');
 return pricing?.unit?t('pricing.heading.costUnit',{unit:pricing.unit}):pricing?.basis==='purchase'?t('pricing.heading.cost'):t('pricing.heading.costUsd');
}
function estimatedCostLabel(cost, pricing, precise=false, withUnit=true){
 if(pricing?.basis==='purchase'&&!pricing.credit_rule)return t('pricing.needRule');
 if(!cost||!cost.rated_tokens||cost.value==null)return t('pricing.unrated');
 const value=Number(cost.value),small=!precise&&value>0&&value<.01;
 if(!Number.isFinite(value)||value<0)return t('pricing.unrated');
 const number=precise?(value>0&&value<1e-12?value.toExponential(3):usageExactNumber(value)):value>=1000?usageNumber(value):formatNumber(value,{maximumFractionDigits:2});
 return (small?'<':'')+(withUnit&&pricing.unit==='USD'?'$':'')+(small?'0.01':number)+(withUnit&&pricing.unit&&pricing.unit!=='USD'?' '+pricing.unit:'')+(cost.unrated_tokens?t('pricing.partialSuffix'):'');
}
function usageCoveragePercent(part,total,precision=1){
 if(!total)return '—';
 if(!part)return '0%';
 if(part>=total)return '100%';
 const percent=100*part/total;
 const minimum=10**(-precision);
 return percent<minimum?'<'+minimum+'%':percent>100-minimum?'>'+ (100-minimum)+'%':formatNumber(percent,{maximumFractionDigits:precision})+'%';
}
function pricingSummary(d){
 if(!d.pricing)return '';
 const cost=d.cost,rule=d.pricing.credit_rule;
 const conversion=d.pricing.basis==='purchase'?'<p><b title="'+esc(usageExactNumber(cost.credits||0)+' credits')+'">'+t('pricing.summary.expectedCredits',{credits:usageNumber(cost.credits||0)})+'</b></p>'+(rule?'<p>'+t('pricing.summary.rule',{amount:rule.amount,currency:rule.currency,credits:rule.credits})+'</p>':'<p>'+t('pricing.summary.setRule')+' <button data-open-price-settings>'+t('pricing.summary.setRuleBtn')+'</button></p>'):'';
 const reasons=Object.entries(cost.reasons).map(([reason,tokens])=>t(reason)+' · '+usageNumber(tokens)+' token').join('; ');
 return '<section class="usage-price-summary"><div><span>'+ ({api:t('pricing.summary.api'),credits:t('pricing.summary.credits'),purchase:t('pricing.summary.purchase')}[d.pricing.basis])+'</span><strong title="'+esc(estimatedCostLabel(cost,d.pricing,true))+'">'+esc(estimatedCostLabel(cost,d.pricing))+'</strong></div>'+conversion+'<p>'+(d.pricing.basis==='purchase'?t('pricing.summary.metered',{pct:usageCoveragePercent(cost.rated_tokens,d.total)}):t('pricing.summary.rated',{pct:usageCoveragePercent(cost.rated_tokens,d.total)}))+' · '+usageNumber(cost.rated_tokens)+' / '+usageNumber(d.total)+' token'+(cost.unrated_tokens?t('pricing.summary.unratedShare',{pct:usageCoveragePercent(cost.unrated_tokens,d.total),tokens:usageNumber(cost.unrated_tokens)}):'')+'</p><p><a href="'+esc(d.pricing.url)+'" target="_blank" rel="noopener noreferrer">'+esc(d.pricing.source)+'</a>'+(d.pricing.fetched_at?t('pricing.summary.cachedAt',{time:formatDate(d.pricing.fetched_at)}):t('pricing.summary.refreshHint'))+(d.pricing.missing_tier==='standard'?t('pricing.summary.standardFallback'):'')+'</p>'+
 (reasons?'<details><summary>'+t('pricing.summary.reasons')+'</summary><p>'+esc(reasons)+'</p></details>':'')+'<p class="usage-cost-basis-note">'+t('pricing.summary.basisNote')+'</p></section>';
}
