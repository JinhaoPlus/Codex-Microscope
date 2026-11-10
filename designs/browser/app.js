const demoMode=location.pathname==='/demo'||location.pathname==='/demo/';
const $=s=>document.querySelector(s), labels={all:'全部',app:'Codex app',cli:'Codex CLI',exec:'非交互模式',ide:'vscode',agent:'子代理',other:'未知来源'};let lastListSignature='',threads=[],cat='all',current=null,data=null,seq=0,threadLoading=false;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dialogEntryButtons=new WeakMap();
function activateDialogEntry(dialog,button){
 if(!button)return;
 const previous=dialogEntryButtons.get(dialog),bound=dialogEntryButtons.has(dialog);
 if(previous&&previous!==button)previous.setAttribute('aria-expanded','false');
 button.classList.add('dialog-entry');button.setAttribute('aria-expanded','true');button.setAttribute('aria-controls',dialog.id);
 dialogEntryButtons.set(dialog,button);
 if(!bound)dialog.addEventListener('close',()=>{dialogEntryButtons.get(dialog)?.setAttribute('aria-expanded','false');dialogEntryButtons.delete(dialog)},{once:true});
}
function usageIcon(){return uiIcon('ChartColumn','ui-icon usage-icon')}
function usageEntry(){return usageIcon()+'<span class="entry-label">用量与成本</span>'}
function threadTitle(t){
 const named=[t.name,t.title].find(v=>typeof v==='string'&&v.trim());if(named)return named.trim();
 try{const agent=JSON.parse(t.source)?.subagent;if(agent){const meta=agent.thread_spawn||{};const task=meta.agent_path?.split('/').filter(Boolean).pop();const parts=[task,meta.agent_nickname].filter(Boolean);if(parts.length)return parts.join(' · ');if(typeof agent.other==='string')return agent.other+' · '+String(t.id).slice(-8)}}catch{}
 return '未命名会话 · '+String(t.id||'').slice(-8)
}
const rawSource=v=>v==null?'未记录':v===''?'空字符串':String(v);
const date=t=>new Date(typeof t==='number'?t*1000:t).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const markdown=window.markdownit({html:false,linkify:true,breaks:false});
function localAsset(url,threadId=current){if(demoMode||!url.startsWith('/')||url.startsWith('//'))return null;return '/api/local-file?id='+encodeURIComponent(threadId)+'&path='+encodeURIComponent(decodeURIComponent(url));}
const renderLink=markdown.renderer.rules.link_open||((tokens,i,options,env,self)=>self.renderToken(tokens,i,options));
markdown.renderer.rules.link_open=(tokens,i,options,env,self)=>{const token=tokens[i],href=token.attrGet('href')||'',local=localAsset(href,env?.threadId);if(local)token.attrSet('href',local);token.attrSet('target','_blank');token.attrSet('rel','noopener noreferrer');return renderLink(tokens,i,options,env,self)};
markdown.renderer.rules.image=(tokens,i,options,env)=>{const token=tokens[i],src=token.attrGet('src')||'',alt=token.content||'图片',local=localAsset(src,env?.threadId);if(!local)return '<a target="_blank" rel="noopener noreferrer" href="'+esc(src)+'">查看图片：'+esc(alt)+'</a>';return '<button type="button" class="image-link" data-image="'+esc(local)+'" aria-label="放大图片：'+esc(alt)+'"><img class="message-image" src="'+esc(local)+'" alt="'+esc(alt)+'" loading="lazy"></button>';};
markdown.renderer.rules.table_open=()=>'<div class="table-wrap"><table>';
markdown.renderer.rules.table_close=()=>'</table></div>';
const renderFence=markdown.renderer.rules.fence;
markdown.renderer.rules.fence=(tokens,i,options,env,self)=>{
 const language=String(tokens[i].info||'').trim().split(/\s+/)[0];
 const code=renderFence(tokens,i,options,env,self);
 return language?'<div class="code-block"><div class="code-language">'+esc(language)+'</div>'+code+'</div>':code;
};
function md(s,threadId=current){return markdown.render(String(s||''),{threadId})}
function questionReplyPresentation(raw,threadId=current){
 const pattern=/<send_user_message_question_reply>\s*([\s\S]*?)\s*<\/send_user_message_question_reply>/g;
 let offset=0,found=false,html=[],text=[];
 for(const match of raw.matchAll(pattern)){
  let replies;try{replies=JSON.parse(match[1])}catch{continue}
  if(!Array.isArray(replies)||!replies.length||!replies.every(reply=>reply&&typeof reply.question==='string'&&typeof reply.answer==='string'))continue;
  const before=raw.slice(offset,match.index);
  html.push(md(before,threadId));text.push(before);
  for(const reply of replies){
   html.push('<div class="question-reply"><details class="question-prompt"><summary title="'+esc(reply.question)+'"><span>'+esc(reply.question)+'</span></summary></details><div class="question-answer">'+md(reply.answer,threadId)+'</div></div>');
   text.push(reply.question+'\n'+reply.answer);
  }
  offset=match.index+match[0].length;found=true;
 }
 if(!found)return null;
 html.push(md(raw.slice(offset),threadId));text.push(raw.slice(offset));
 return {body:text.join('\n').trim(),html:html.join(''),attachments:'',questionReply:true};
}
function userPresentation(text,threadId=current){
 const raw=String(text||''),reply=questionReplyPresentation(raw,threadId);if(reply)return reply;
 const match=raw.match(/^\s*# Files mentioned by the user:\s*([\s\S]*?)^## My request:\s*([\s\S]*)$/m);
 if(!match)return {body:raw,attachments:''};
 const files=[...match[1].matchAll(/^## (.+?): (\/[^\n]+)\s*$/gm)].map(m=>({name:m[1],path:m[2].trim()}));
 if(!files.length)return {body:raw,attachments:''};
 const body=match[2].replace(/<image\b[^>]*>[\s\S]*?<\/image>/g,'').trim();
 const attachments='<div class="user-attachments">'+files.map(file=>{
  const url=localAsset(file.path,threadId),isImage=/\.(png|jpe?g|webp|gif|avif)$/i.test(file.path);
  return '<div class="user-attachment'+(isImage?' is-image':'')+'">'+(isImage?'<button class="image-link" data-image="'+esc(url)+'" aria-label="放大图片：'+esc(file.name)+'"><img class="message-image" src="'+esc(url)+'" alt="'+esc(file.name)+'" loading="lazy"></button>':'<a class="attachment-file" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(file.name)+'</a>')+(isImage?'':'<details class="attachment-info"><summary title="'+esc(file.name)+'">'+esc(file.name)+'</summary><div>'+esc(file.path)+'</div></details>')+'</div>';
 }).join('')+'</div>';
 return {body,attachments};
}
function isContext(x){return x.kind==='context'||(x.role==='user'&&/^\s*(# AGENTS\.md instructions|<(environment_context|external_browser_tabs|external_codex_apps_open_page|permissions instructions)[\s>])/.test(x.text||''))}
function uiIcon(name,cls='ui-icon'){return (window.LUCIDE_ICONS[name]||window.LUCIDE_ICONS.Tools).replace('<svg','<svg class="'+cls+'" aria-hidden="true" focusable="false" ')}
function actionIcon(icon){
 const name=Object.hasOwn(window.LUCIDE_ICONS,icon)?icon:'Tools';
 return uiIcon(name,'action-icon').replace('<svg ','<svg data-tool-icon="'+name+'" ');
}
function timelineActions(item){
 return item.exec_view?[item.exec_view]:item.operations||[];
}
function actionSummary(items){
 const ops=items.flatMap(timelineActions);
 const icons=new Set(ops.map(op=>op.icon||'Tools'));
 const labels=[...new Set(ops.map(op=>op.label||op.action))];
 return {icon:icons.size===1?[...icons][0]:'Layers',label:labels.join('、')||'工具调用'};
}
function step(x){
 if(x.lazy&&detailCache.has(x.index))x=detailCache.get(x.index);
 const ops=x.operations||[];
 const wrapped=x.exec_view||x.envelope?.script||ops.some(op=>op.resultRef!=null);
 const rows=wrapped?ops.slice(0,1):ops;
 return rows.map((op,index)=>{
  const sourceCount=new Set(ops.map(o=>o.sourceIndex).filter(Number.isInteger)).size;
  const names=[...new Set(ops.filter(o=>Number.isInteger(o.sourceIndex)).map(o=>o.action))];
  const label=x.exec_view?[x.exec_view.label,x.exec_view.state].filter(Boolean).join(' · '):wrapped&&sourceCount>1?(names.length>1?names.join('、')+'（'+sourceCount+' 个调用）':op.summary+' 等 '+sourceCount+' 个工具调用'):op.summary;
  const operation=wrapped?'call':index;
  return `<details class="step native-action-step" data-step="${x.index}" data-operation="${operation}" data-loaded="${x.lazy?'':'true'}" data-key="op-${x.index}-${operation}"><summary title="${esc(label)}">${actionIcon(x.exec_view?.icon||op.icon)}<span class="step-label">${esc(label)}</span>${uiIcon('ChevronDown','disclosure')}</summary><div class="tool-body">${x.lazy?'':toolDetailBody(x,{dataset:{operation}})}</div></details>`;
 }).join('');
}
async function api(url){const r=await fetch(demoMode?url.replace(/^\/api\//,"/api/demo/"):url);const d=await r.json();if(!r.ok)throw Error(d.error);return d}
let listMode=localStorage.getItem('session-list-mode')==='directory'?'directory':'time';
function loadDirectoryState(key){try{const value=JSON.parse(localStorage.getItem(key));return new Set(Array.isArray(value)?value.filter(x=>typeof x==='string'):[])}catch{return new Set()}}
const closedDirectories=loadDirectoryState('closed-directories'),expandedDirectories=loadDirectoryState('expanded-directories');
function saveDirectoryState(){localStorage.setItem('closed-directories',JSON.stringify([...closedDirectories]));localStorage.setItem('expanded-directories',JSON.stringify([...expandedDirectories]))}
let archiveMode=['all','active','archived'].includes(localStorage.getItem('archive-mode'))?localStorage.getItem('archive-mode'):'all';
function directoryKey(t){return String(t.cwd||'').replace(/\\/g,'/').replace(/\/$/,'')||'/'}
function directoryName(path){return threads.find(t=>t.cwd&&directoryKey(t)===path&&t.workspace_name)?.workspace_name||path.split('/').filter(Boolean).pop()||path}
function sessionStatus(t){const status=t.status;if(!['inProgress','failed'].includes(status))return '';const label=status==='inProgress'?'运行中（本地记录）':'失败（最新一轮）';return `<span class="session-status ${status==='inProgress'?'running':'failed'}" role="img" aria-label="${label}" title="${label}">${status==='inProgress'?uiIcon('LoaderCircle','session-progress-icon').replace('<svg','<svg style="animation-delay:-'+(Date.now()%1000)+'ms"'):''}</span>`}
function sessionCard(t,compact=false){return `<button class="session ${compact?'compact-session ':''}${t.id===current?'active':''}" data-id="${esc(t.id)}" title="${esc(threadTitle(t))}"><span class="session-title"><strong>${esc(threadTitle(t))}</strong>${sessionStatus(t)}</span>${compact?'':`<small><span class="tag">${labels[t.category]}</span>${date(t.updated_at)} ${t.archived?'· 已归档':''} ${t.available===false?'· 文件缺失':''}</small><small>${esc(t.cwd)}</small>${t.originator?.trim()?'<small class="source-info">originator: '+esc(t.originator)+'</small>':''}`}</button>`}
function renderDemoList(){
 const q=$('#search').value.trim().toLowerCase(), groups=new Map();
 for(const t of threads){
  if(![t.title,t.group,t.guide,t.evidence,t.id,...t.tools].join(' ').toLowerCase().includes(q))continue;
  if(!groups.has(t.group))groups.set(t.group,[]);groups.get(t.group).push(t);
 }
 $('#demo-index-meta').textContent=threads.length+' 个合成案例 · 不执行工具';
 $('#list').innerHTML=[...groups].map(([group,cases])=>`<section class="demo-group"><h2>${esc(group)} <small>${cases.length}</small></h2>${cases.map(t=>sessionCard(t,true)).join('')}</section>`).join('')||'<p>没有匹配的案例</p>';
}
function setupDemo(){
 document.body.classList.add('demo-mode');document.title='工具案例库 · Codex Microscope';
 $('.brand strong').textContent='工具案例库';$('#title').textContent='Codex 工具调用案例库';
 $('#search').placeholder='搜索案例、工具或案例来源';$('#search').setAttribute('aria-label','搜索案例');
 const hint=document.createElement('small');hint.id='demo-index-meta';$('#search').after(hint);$('#back').textContent='案例';const returnLink=document.createElement('a');returnLink.id='demo-entry';returnLink.href='/';returnLink.textContent='返回会话浏览器';$('.sidebar-footer').prepend(returnLink);
 $('#welcome h1').textContent='工具调用怎样展示？';
 $('#welcome p').textContent='按真实日志形态重建，使用合成内容。选一个案例，查看它在会话时间线上的实际效果。';
 const a=document.createElement('a');a.className='demo-start';a.href='/demo#parallel-image';a.textContent='先看：三次读取和一张图片 →';
 $('#welcome').append(a);
}
function showDemoNote(t){
 const note=$('#demo-note');note.hidden=false;
 note.innerHTML=`<strong>${esc(t.group)} · 合成演示</strong><small>${t.evidence?'案例来源：'+esc(t.evidence):'合成边界测试'}</small>`;
}
function renderList(){
 if(demoMode){renderDemoList();return}
 lastListSignature=JSON.stringify(threads);
 const q=$('#search').value.toLowerCase();const rs=threads.filter(t=>(cat==='all'||t.category===cat)&&(archiveMode==='all'||Boolean(t.archived)===(archiveMode==='archived'))&&[threadTitle(t),t.title,t.cwd,t.id,t.name,t.source,t.originator].join(' ').toLowerCase().includes(q));
 $('#archive').textContent={all:'全部',active:'未归档',archived:'已归档'}[archiveMode];$('#archive').title='归档筛选：'+$('#archive').textContent+'；点击切换';$('#archive').setAttribute('aria-label',$('#archive').title);
 const sources=Object.entries(labels).filter(([k])=>k==='all'||threads.some(t=>t.category===k));
 $('#source-value').textContent=(cat==='all'?'全部来源':labels[cat])+' · '+(cat==='all'?threads.length:threads.filter(t=>t.category===cat).length);
 $('#source-menu').innerHTML=sources.map(([k,v])=>`<button role="menuitemradio" aria-checked="${cat===k}" data-source="${k}" tabindex="-1"><span class="source-check" aria-hidden="true">${cat===k?uiIcon('Check'):''}</span><span>${k==='all'?'全部来源':v}</span><small>${k==='all'?threads.length:threads.filter(t=>t.category===k).length}</small></button>`).join('');
 $('#list-mode').value=listMode;
 if(listMode==='time'){$('#list').innerHTML=rs.map(t=>sessionCard(t)).join('')||'<p>没有匹配的会话</p>';return}
 const groups=new Map();for(const t of rs){const key=t.cwd?directoryKey(t):'';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(t)}
 const names=new Map();for(const key of groups.keys()){const name=directoryName(key);names.set(name,(names.get(name)||0)+1)}
 $('#list').innerHTML=[...groups].map(([key,items])=>{
 const name=key?directoryName(key):'未记录目录',closed=closedDirectories.has(key)&&!q,expanded=expandedDirectories.has(key)||Boolean(q),shown=expanded?items:items.slice(0,5);
 // Keep a selected conversation visible even when it is older than the preview.
 const selected=items.find(t=>t.id===current);if(!expanded&&selected&&!shown.includes(selected))shown.push(selected);
 return `<section class="directory-group"><div class="directory-row"><button class="directory-heading" data-directory="${esc(key)}" aria-expanded="${!closed}" title="${esc(key||name)}">${uiIcon(closed?'Folder':'FolderOpen')}<span>${esc(name)}${names.get(name)>1?'<small>'+esc(key)+'</small>':''}</span><span class="directory-count">${items.length}</span>${uiIcon('ChevronDown','directory-chevron')}</button><button class="directory-usage dialog-entry" aria-expanded="false" aria-controls="usage-dialog" data-directory-usage="${esc(key)}" title="用量与成本 · ${esc(name)}" aria-label="查看 ${esc(name)} 的用量与成本">${usageEntry()}</button></div>${closed?'':`<div class="directory-sessions">${shown.map(t=>sessionCard(t,true)).join('')}${items.length>5&&!q?`<button class="directory-more" data-directory-more="${esc(key)}">${expanded?'收起':'展开显示 · '+(items.length-shown.length)+' 条'}</button>`:''}</div>`}</section>`
 }).join('')||'<p>没有匹配的会话</p>';
}

async function refresh(){try{threads=await api('/api/threads');renderList()}catch(e){$('#list').textContent=e.message}}
function durationLabel(ms){const seconds=Math.round(ms/1000);if(seconds<60)return seconds+' 秒';const minutes=Math.floor(seconds/60),rest=seconds%60;return minutes+' 分'+(rest?' '+rest+' 秒':'')}
const effortLevels=['none','minimal','low','medium','high','xhigh','max','ultra'];
function effortIndicator(value){
 const level=effortLevels.indexOf(String(value).toLowerCase());
 const fraction=level/(effortLevels.length-1);
 const arc='M3.34 19a10 10 0 1 1 17.32 0';
 const fill=level>0?`<path class="gauge-fill" d="${arc}" pathLength="100" stroke-dasharray="${fraction*100} 100"/>`:'';
 const needle=level>=0?`<path class="gauge-needle" d="m12 14 4-4" transform="rotate(${195+240*fraction} 12 14)"/>`:'';
 const icon=uiIcon('Gauge','effort-gauge').replace('<path d="m12 14 4-4" />',needle).replace('<path d="'+arc+'" />','<path class="gauge-track" d="'+arc+'"/>'+fill);
 return `<span class="turn-effort" title="本轮强度">${icon}${esc(value)}</span>`;
}
function turnHeading(x){
 const turn=data.turns?.find(t=>t.turn_id===x.turn_id),context=x.turn_context||{};
 const time=turn?.started_at||context.time||x.time;
 const canInspect=Boolean(context.available&&x.turn_id);
 const modelInfo=[context.model?`<span class="turn-model" title="${canInspect?'查看本轮配置':'本轮模型'}">${esc(context.model)}</span>`:'',context.effort?effortIndicator(context.effort).replace('title="本轮强度"',canInspect?'title="查看本轮配置"':'title="本轮强度"'):''].join('');
 const configuration=canInspect?`<button type="button" class="turn-configuration dialog-entry" data-turn-context="${esc(x.turn_id)}" aria-expanded="false" aria-controls="context-panel" aria-haspopup="dialog" title="查看本轮配置" aria-label="${esc('查看本轮配置'+(modelInfo?'：'+[context.model,context.effort].filter(Boolean).join('，'):''))}">${modelInfo||'<span>本轮配置</span>'}</button>`:modelInfo?`<span class="turn-configuration">${modelInfo}</span>`:'';
 const meta=[time?`<time>${esc(date(time))}</time>`:'',configuration].filter(Boolean).join('<span class="turn-meta-separator" aria-hidden="true">·</span>');
 const timing=turn?.duration_ms!=null&&turn.duration_ms>=0?`<details class="turn-timing"><summary>用时 ${durationLabel(turn.duration_ms)} ${uiIcon('ChevronDown','disclosure')}</summary><div>开始：${turn.started_at?date(turn.started_at):'未记录'}<br>结束：${turn.completed_at?date(turn.completed_at):'未记录'}<br>记录状态：${esc(turn.status)}</div></details>`:'';
 return `<div class="turn-heading"><div class="turn-header-row"><div class="turn-metadata">${meta}</div>${x.turn_id?`<button class="turn-context-link turn-usage-link dialog-entry" aria-expanded="false" aria-controls="usage-dialog" data-usage-turn="${esc(x.turn_id)}" title="本轮用量与成本" aria-label="查看本轮用量与成本" aria-haspopup="dialog">${usageEntry()}</button>`:''}</div>${timing}</div>`;
}
function renderMessages(){
 if(!data)return;let html=[],group=[],assistantOpen=false,shown=0,activeTurn=null;
 const flush=()=>{
  if(!group.length)return;
  const steps=group.map(step).join('');
  const operationCount=group.reduce((count,item)=>count+(item.exec_view?.count||item.operations?.length||1),0);
  if(operationCount===1||(group.length===1&&group[0].envelope?.script))html.push(steps);
  else{const summary=actionSummary(group);html.push(`<details class="activity activity-group" data-key="group-${group[0].index}"><summary title="${operationCount} 项操作">${actionIcon(summary.icon)}<span class="activity-label">${esc(summary.label)}</span>${uiIcon('ChevronDown','disclosure')}</summary><div class="activity-steps">${steps}</div></details>`)}
  group=[];
 };
 const closeAssistant=()=>{flush();if(assistantOpen){html.push('</section>');assistantOpen=false}};
 for(const x of data.items){
  const context=isContext(x),user=x.role==='user'&&!context;
  if(x.turn_id&&activeTurn&&x.turn_id!==activeTurn)closeAssistant();
  if(x.turn_id)activeTurn=x.turn_id;
  if(user)closeAssistant();
  if(context||x.kind==='reasoning')continue;
  shown++;
  if(['tool','reasoning'].includes(x.kind)){group.push(x);continue}
  flush();if(context){html.push(step(x));continue}
  const presentation=user?userPresentation(x.text):{body:x.text,attachments:''};const body=presentation.html??md(presentation.body);
  if(user){const long=!presentation.questionReply&&String(presentation.body).length>1400;const content=long?'<details class="long-message"><summary>查看完整请求</summary><div class="content">'+body+'</div></details><p class="request-preview">'+esc(String(presentation.body).slice(0,240))+'…</p>':'<div class="content">'+body+'</div>';html.push(`<section data-anchor="item-${x.index}" class="message user${presentation.attachments?' user-with-attachments':''}${presentation.questionReply?' user-question-reply':''}"><div class="by"><time>${x.time?date(x.time):''}</time></div>${presentation.attachments}${presentation.attachments?(presentation.body?'<div class="user-text-bubble">'+content+'</div>':''):content}</section>`);continue}
  if(!assistantOpen){html.push(`<section data-anchor="item-${x.index}" class="message assistant">${turnHeading(x)}`);assistantOpen=true}
  html.push(`<div class="content assistant-part">${body}</div>`);
 }
 closeAssistant();$('#messages').innerHTML=relationLinks()+(data.has_more?'<button class="load-older" id="load-older">加载更早的对话</button>':'')+html.join('')||'<p class="empty">没有匹配的消息</p>';buildMessageNavigation();$('#end').textContent=`已显示 ${shown} 条记录${data.skipped?' · '+data.skipped+' 行尚未完整写入或无法解析':''}${data.history_warning?' · '+data.history_warning:''}`
}
let findOpen=localStorage.getItem('conversation-find-open')==='true';
function setFindOpen(open,focus=true){findOpen=open;localStorage.setItem('conversation-find-open',String(open));$('#controls').hidden=!open;$('#toggle-find').setAttribute('aria-expanded',String(open));$('#toggle-find').setAttribute('aria-label',open?'收起会话查找':'展开会话查找');if(open&&focus)$('#insearch').focus()}
$('#toggle-find').innerHTML=uiIcon('Search');$('#close-find').innerHTML=uiIcon('X');
$('#find-prev').innerHTML=uiIcon('ArrowUp');$('#find-next').innerHTML=uiIcon('ArrowDown');
$('.source-chevron').innerHTML=uiIcon('ChevronDown');
$('.list-mode-chevron').innerHTML=uiIcon('ChevronDown');
$('#toggle-find').onclick=()=>setFindOpen($('#controls').hidden);
$('#close-find').onclick=()=>{setFindOpen(false);$('#toggle-find').focus()};
let searchHits=[],searchIndex=-1,searchTimer;
function updateFindStatus(){const count=searchHits.length;$('#find-status').textContent=$('#insearch').value?(count?`${searchIndex+1} / ${count}`:'无匹配'):'';$('#find-prev').disabled=$('#find-next').disabled=!count}
function jumpToHit(direction=1){
 if(!searchHits.length)return;
 searchHits[searchIndex]?.classList.remove('current-hit');searchIndex=(searchIndex+direction+searchHits.length)%searchHits.length;
 const hit=searchHits[searchIndex];for(let parent=hit.parentElement;parent&&parent!==$('#messages');parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
 hit.classList.add('current-hit');hit.scrollIntoView({block:'center',behavior:'instant'});updateFindStatus();
}
function findInConversation(){
 clearTimeout(searchTimer);searchTimer=null;const root=$('#messages');
 root.querySelectorAll('mark.search-hit').forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent)));root.normalize();searchHits=[];searchIndex=-1;
 const query=$('#insearch').value;if(!query){updateFindStatus();return}
 // Match literal text, never HTML, and leave the full conversation in place.
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(node){return node.parentElement.closest('.content,pre,.step summary')&&!node.parentElement.closest('.request-preview,.by')?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT}});
 const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
 const pattern=new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'giu');
 for(const node of nodes){const text=node.nodeValue;pattern.lastIndex=0;const matches=[...text.matchAll(pattern)];if(!matches.length)continue;const fragment=document.createDocumentFragment();let offset=0;
 for(const match of matches){fragment.append(document.createTextNode(text.slice(offset,match.index)));const mark=document.createElement('mark');mark.className='search-hit';mark.textContent=match[0];fragment.append(mark);searchHits.push(mark);offset=match.index+match[0].length}
 fragment.append(document.createTextNode(text.slice(offset)));node.replaceWith(fragment)}
 if(searchHits.length)jumpToHit(1);else updateFindStatus();
}
$('#find-prev').onclick=()=>{if(searchTimer)findInConversation();jumpToHit(-1)};
$('#find-next').onclick=()=>{if(searchTimer)findInConversation();jumpToHit(1)};
$('#insearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(searchTimer)findInConversation();else jumpToHit(e.shiftKey?-1:1)}if(e.key==='Escape'){$('#insearch').value='';findInConversation()}};
new ResizeObserver(entries=>{document.documentElement.style.setProperty('--conversation-header-height',entries[0].target.getBoundingClientRect().height+'px')}).observe(document.querySelector('main>header'));
async function openThread(id){threadLoading=true;const n=++seq;searchRequest++;detailCache.clear();revisionState=null;pendingLive=false;$('#new-messages').hidden=true;current=id;data=null;messageNav.hidden=true;messageNav.innerHTML='';messageNavTargets=[];$('#context').hidden=true;document.body.classList.add('reading');$('#welcome').hidden=true;$('#controls').hidden=true;$('#toggle-find').hidden=true;$('#messages').textContent='正在读取会话…';$('#end').textContent='';renderList();try{const [d,rev]=await Promise.all([api('/api/thread?id='+encodeURIComponent(id)),api('/api/revision?id='+encodeURIComponent(id))]);if(n!==seq)return;data=d;document.dispatchEvent(new Event('thread-loaded'));revisionState=rev;$('#context').hidden=false;if(demoMode)showDemoNote(d.thread);const fullTitle=threadTitle(d.thread);$('#title').textContent=fullTitle.split('\n')[0].slice(0,100)+(fullTitle.split('\n')[0].length>100?'…':'');$('#title').title=fullTitle;document.querySelector('main').scrollTop=0;$('#toggle-find').hidden=false;setFindOpen(findOpen,false);$('#insearch').value='';renderMessages();findInConversation();requestAnimationFrame(()=>{if(n!==seq)return;const main=document.querySelector('main');main.scrollTop=demoMode?0:main.scrollHeight;updateMessageNavigation()});history.replaceState(null,'','#'+id)}catch(e){if(n===seq)$('#messages').textContent=e.message}finally{if(n===seq)threadLoading=false}}
function closeSourceMenu(restoreFocus=false){$('#source-menu').hidden=true;$('#filters').setAttribute('aria-expanded','false');if(restoreFocus)$('#filters').focus()}
function openSourceMenu(){const menu=$('#source-menu');menu.hidden=false;$('#filters').setAttribute('aria-expanded','true');(menu.querySelector('[aria-checked="true"]')||menu.querySelector('button'))?.focus()}
$('#filters').onclick=()=>$('#source-menu').hidden?openSourceMenu():closeSourceMenu(true);
$('#filters').onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();openSourceMenu()}};
$('#source-menu').onclick=e=>{const option=e.target.closest('[data-source]');if(!option)return;cat=option.dataset.source;closeSourceMenu(true);renderList()};
$('#source-menu').onkeydown=e=>{const options=[...$('#source-menu').querySelectorAll('button')],i=options.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?options.length-1:(i+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;options[next]?.focus()}if(e.key==='Escape'){e.preventDefault();closeSourceMenu(true)}};
document.addEventListener('pointerdown',e=>{if(!e.target.closest('.source-select'))closeSourceMenu()});
document.addEventListener('focusin',e=>{if(!e.target.closest('.source-select'))closeSourceMenu()});
$('#list').onclick=e=>{const b=e.target.closest('[data-id]');if(b){openThread(b.dataset.id);return}const d=e.target.closest('[data-directory]'),m=e.target.closest('[data-directory-more]');if(d){const k=d.dataset.directory;closedDirectories.has(k)?closedDirectories.delete(k):closedDirectories.add(k);saveDirectoryState();renderList()}if(m){const k=m.dataset.directoryMore;expandedDirectories.has(k)?expandedDirectories.delete(k):expandedDirectories.add(k);saveDirectoryState();renderList()}};$('#list-mode').onchange=e=>{listMode=e.target.value;localStorage.setItem('session-list-mode',listMode);renderList()};$('#search').oninput=renderList;$('#archive').onclick=()=>{archiveMode={all:'active',active:'archived',archived:'all'}[archiveMode];localStorage.setItem('archive-mode',archiveMode);renderList()};$('#insearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(searchWholeConversation,250)};$('#context').onclick=openContextPanel;$('#refresh').onclick=async()=>{await refresh();if(current)openThread(current)};$('#back').onclick=()=>document.body.classList.remove('reading');$('#theme').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('dark',document.body.classList.contains('dark'))};if(localStorage.getItem('dark')==='true')document.body.classList.add('dark');if(demoMode){setupDemo();window.addEventListener('hashchange',()=>{if(location.hash)openThread(location.hash.slice(1))})}refresh().then(()=>{if(location.hash)openThread(location.hash.slice(1))});

document.addEventListener('error',e=>{if(e.target.matches?.('.message-image')){const note=document.createElement('span');note.className='image-unavailable';note.textContent='图片无法读取 · '+e.target.alt;e.target.replaceWith(note)}},true);

const imageViewer=document.createElement('dialog');imageViewer.className='image-viewer';imageViewer.innerHTML='<button class="image-close" aria-label="关闭图片">'+uiIcon('X')+'</button><img alt=""><p></p>';document.body.append(imageViewer);
function openMessageImage(e){const b=e.target.closest('[data-image]');if(!b)return;const img=b.querySelector('img');if(!img)return;imageViewer.querySelector('img').src=b.dataset.image;imageViewer.querySelector('img').alt=img.alt;imageViewer.querySelector('p').textContent=img.alt;imageViewer.showModal()}
$('#messages').addEventListener('click',openMessageImage);
imageViewer.querySelector('button').onclick=()=>imageViewer.close();imageViewer.addEventListener('click',e=>{if(e.target===imageViewer)imageViewer.close()});imageViewer.addEventListener('close',()=>imageViewer.querySelector('img').removeAttribute('src'));

const contextPanel=document.createElement('dialog');contextPanel.className='context-panel';contextPanel.id='context-panel';contextPanel.setAttribute('aria-labelledby','context-heading');contextPanel.innerHTML='<div class="context-panel-head"><div><h2 id="context-heading">环境与上下文</h2><p>这段会话使用的环境和指令</p></div><button class="context-fullscreen" aria-label="全屏显示环境与上下文" aria-pressed="false">'+uiIcon('Expand')+'<span>全屏</span></button><button class="context-close" aria-label="关闭环境与上下文">'+uiIcon('X')+'</button></div><div class="context-panel-layout"><div class="context-panel-body"></div><nav class="context-nav" aria-label="环境与上下文快捷导航"></nav></div>';document.body.append(contextPanel);
contextPanel.querySelector('.context-close').onclick=()=>contextPanel.close();
function setContextFullscreen(full){
 contextPanel.classList.toggle('is-fullscreen',full);
 const button=contextPanel.querySelector('.context-fullscreen');
 button.innerHTML=uiIcon(full?'Collapse':'Expand')+'<span>'+(full?'还原':'全屏')+'</span>';
 button.setAttribute('aria-pressed',String(full));
 button.setAttribute('aria-label',(full?'还原':'全屏显示')+contextPanel.querySelector('h2').textContent+(full?'侧栏':''));
 button.title=button.getAttribute('aria-label');
}
setContextFullscreen(localStorage.getItem('context-fullscreen')==='true');
contextPanel.querySelector('.context-fullscreen').onclick=()=>{const full=!contextPanel.classList.contains('is-fullscreen');setContextFullscreen(full);localStorage.setItem('context-fullscreen',String(full));hideToolDefinition()};contextPanel.addEventListener('click',e=>{if(e.target===contextPanel)contextPanel.close()});
function contextField(text,tag){const m=text.match(new RegExp('<'+tag+'>([\\s\\S]*?)</'+tag+'>','g'));if(!m?.length)return '';return m[m.length-1].replace(new RegExp('^<'+tag+'>|</'+tag+'>$','g'),'').trim()}
function schemaPreview(schema){
 return '<div class="schema-viewer-host"><p class="context-note" role="status">正在加载 Schema 查看器…</p></div><details class="schema-raw"><summary>查看原始 Schema</summary><pre class="context-json">'+esc(JSON.stringify(schema,null,2))+'</pre></details>';
}
function contextToolDetail(item){
 const tool=item.function&&typeof item.function==='object'?item.function:item;
 const schemaKeys=['parameters','input_schema','inputSchema','schema'];
 const fields=schemaKeys.filter(key=>Object.hasOwn(tool,key));
 const format=Object.hasOwn(tool,'format');
 const schemas=fields.map(key=>'<section class="tool-input-schema tool-schema-section"><h4>入参 Schema <code>'+esc(key)+'</code></h4>'+schemaPreview(tool[key])+'</section>').join('');
 const input=schemas||(format?'<section class="tool-input-schema"><h4>入参格式 <code>format</code></h4><p class="context-note">此工具使用自定义输入格式，记录未提供 JSON Schema。</p>'+contextValue({format:tool.format})+'</section>':'<section class="tool-input-schema tool-schema-section"><h4>入参 Schema</h4><p class="context-note">记录未提供入参 Schema；不能据此判断工具没有入参。</p></section>');
 const rest=Object.fromEntries(Object.entries(tool).filter(([key])=>key!=='description'&&!fields.includes(key)&&!(format&&key==='format')));
 const detail=tool===item?rest:{...item,function:rest};
 // Tool definitions preserve source key order; always read their description last.
 let descriptions='';
 if(tool!==item&&Object.hasOwn(item,'description')){delete detail.description;descriptions+=contextValue({description:item.description})}
 if(Object.hasOwn(tool,'description'))descriptions+=contextValue({description:tool.description});
 return '<div class="tool-definition-meta">'+contextValue(detail)+'</div>'+input+(descriptions?'<div class="tool-definition-description">'+descriptions+'</div>':'');
}
function contextTools(value){
 const rows=[];
 const visit=(items,namespace='')=>{for(const item of items){if(!item||typeof item!=='object')continue;
  if(item.type==='namespace'&&Array.isArray(item.tools)){visit(item.tools,[namespace,item.name].filter(Boolean).join('.'));continue}
  const tool=item.function||item;rows.push({name:tool.name||item.type||'未命名',namespace,type:item.type||'function',detail:item,description:tool.description||item.description||''});
 }};visit(value);
 if(!rows.length)return '<p class="context-note">没有工具定义</p>';
 return '<div class="context-tools-scroll"><table class="context-tools"><thead><tr><th>工具</th><th>类型</th><th>说明</th></tr></thead><tbody>'+rows.map(t=>'<tr><td><button class="tool-definition" data-tool-json="'+esc(JSON.stringify(t.detail))+'" aria-expanded="false" aria-label="查看 '+esc([t.namespace,t.name].filter(Boolean).join('.'))+' 的定义">'+(t.namespace?'<small>'+esc(t.namespace)+'</small>':'')+'<span>'+esc(t.name)+'</span></button><template class="tool-definition-content"><h3>'+esc([t.namespace,t.name].filter(Boolean).join('.'))+'</h3>'+contextToolDetail(t.detail)+'</template></td><td>'+esc(t.type)+'</td><td><span class="tool-description">'+esc(t.description.split('\n').find(v=>v.trim())||'—')+'</span></td></tr>').join('')+'</tbody></table></div>';
}
function contextValue(value){
 let parsed=value;if(typeof value==='string'){try{parsed=JSON.parse(value)}catch{}}
 if(Array.isArray(parsed)||(parsed&&typeof parsed==='object'&&!Object.keys(parsed).length))return '<pre class="context-json">'+esc(JSON.stringify(parsed,null,2))+'</pre>';
 const leaf=v=>typeof v==='string'?'<div class="content context-string">'+md(v)+'</div>':v!==null&&typeof v==='object'?'<pre class="context-json">'+esc(JSON.stringify(v,null,2))+'</pre>':'<code class="context-scalar">'+esc(JSON.stringify(v))+'</code>';
 if(parsed&&typeof parsed==='object'&&Array.isArray(parsed.tools)){
  const compact=['type','id','role'].filter(key=>parsed[key]!=null&&typeof parsed[key]!=='object');
  const meta='<div class="context-inline-meta">'+compact.map(key=>'<span class="context-inline-field" title="'+esc(String(parsed[key]))+'"><span>'+key+'</span><code>'+esc(String(parsed[key]))+'</code></span>').join('')+'</div>';
  const remaining=Object.entries(parsed).filter(([key])=>key!=='tools'&&!compact.includes(key));
  return meta+contextTools(parsed.tools)+(remaining.length?'<dl class="context-fields">'+remaining.map(([key,v])=>'<dt>'+esc(key)+'</dt><dd>'+leaf(v)+'</dd>').join('')+'</dl>':'');
 }
 if(parsed!==null&&typeof parsed==='object')return '<dl class="context-fields">'+Object.entries(parsed).map(([key,v])=>'<dt>'+esc(key)+'</dt><dd>'+(key==='tools'&&Array.isArray(v)?contextTools(v):leaf(v))+'</dd>').join('')+'</dl>';
 return leaf(parsed);
}
function contextStamp(record){
 const time=record.time;
 return time?'<time datetime="'+esc(time)+'" title="'+esc(time)+'">'+esc(time)+'</time>':'<span class="context-note">时间未记录</span>';
}
function contextEntry(record,ordinal,title,body,id='context-record-'+ordinal){
 return '<article class="context-entry" data-record-order="'+ordinal+'"><header class="context-entry-meta"><span class="context-role">'+esc(record.role||'context')+'</span><span class="context-entry-title">'+esc(title)+'</span>'+contextStamp(record)+'<button class="context-collapse-top" aria-expanded="true" aria-controls="'+id+'">收起全文</button></header><div id="'+id+'" class="context-record context-preview">'+contextValue(body)+'</div><button hidden class="context-expand" aria-expanded="false" aria-controls="'+id+'">展开全文</button></article>';
}
function contextSection(title,body,note=''){
 return body?'<section class="context-section"><h3>'+esc(title)+'</h3>'+(note?'<p class="context-note">'+esc(note)+'</p>':'')+body+'</section>':'';
}
function contextEnvironment(fields){
 return '<dl class="context-environment">'+fields.filter(([,v])=>v!=null&&v!=='').map(([label,value,source])=>'<div class="environment-field'+(typeof value==='object'||String(value).length>48||label==='工作目录'?' is-wide':'')+'"><dt>'+esc(label)+'</dt><dd>'+contextValue(value)+(source?'<small class="context-field-source">'+esc(source)+'</small>':'')+'</dd></div>').join('')+'</dl>';
}
function contextRecordCategory(raw){
 // Only classify complete, recognized records. Mixed or unknown records stay intact.
 let parsed;try{parsed=JSON.parse(raw)}catch{}
 if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed)&&Array.isArray(parsed.tools)&&Object.keys(parsed).every(key=>['type','id','role','tools'].includes(key)))return ['tools','工具定义'];
 const wrapper=raw.trim().match(/^<([\w-]+(?: instructions)?)\b[^>]*>[\s\S]*<\/\1>$/);
 if(wrapper){
  // Reject multiple adjacent blocks, even when they use the same wrapper.
  const tag=wrapper[1],closing='</'+tag+'>';
  if(raw.trim().indexOf(closing)!==raw.trim().length-closing.length)return ['instructions','混合或未分类记录'];
  if(tag==='environment_context')return ['environment','环境记录'];
  if(tag==='permissions instructions')return ['permissions','权限记录'];
  if(['external_browser_tabs','external_codex_apps_open_page','app-context'].includes(tag))return ['background',tag==='app-context'?'应用背景':'当时打开的页面'];
 }
 return ['instructions',/^\s*# AGENTS\.md instructions/.test(raw)?'项目指令 · AGENTS.md':'指令与背景记录'];
}
function contextPresentation(d){
 const records=(d.contextItems||d.items).filter(isContext),thread=d.thread;
 const buckets={environment:[],permissions:[],instructions:[],tools:[],background:[]};
 records.forEach((record,i)=>{const raw=String(record.text||''),[category,title]=contextRecordCategory(raw);buckets[category].push(contextEntry(record,i+1,title,raw))});
 // Summaries cite the record they came from; source records remain intact below.
 const latestTag=tag=>{
  for(let i=records.length-1;i>=0;i--){
   const raw=String(records[i].text||'');
   const env=raw.match(/<environment_context>[\s\S]*?<\/environment_context>/g)?.join('\n')||'';
   const value=contextField(env,tag);
   if(value)return [value,'环境记录 · '+(records[i].time||'时间未记录')];
  }
  return [];
 };
 const cwd=latestTag('cwd');
 const env=[['工作目录',cwd[0]||thread.cwd,cwd[0]?cwd[1]:'会话索引'],['模型',thread.model,'会话索引'],...Object.entries({shell:'命令行',timezone:'时区',current_date:'环境日期'}).map(([tag,label])=>[label,...latestTag(tag)])];
 let output=contextSection('环境概览',contextEnvironment(env),'各字段取最后可读记录或会话索引，可能来自不同时刻。下方按类型分区，分区内保持原始顺序。');
 if(buckets.environment.length)output+='<details class="context-source-records"><summary>环境记录 · '+buckets.environment.length+' 条（原始顺序）</summary>'+buckets.environment.join('')+'</details>';
 // Extract only explicit environment/permission tags; never infer access from prose.
 const permissionFields=new Map();
 records.forEach((record,i)=>{
  const raw=String(record.text||''),category=contextRecordCategory(raw)[0];
  const scope=category==='permissions'?raw:(raw.match(/<environment_context>[\s\S]*?<\/environment_context>/g)||[]).join('\n');
  const source=(category==='permissions'?'权限记录':'环境记录')+' · '+(record.time||'时间未记录');
  const profile=[...scope.matchAll(/<permission_profile\b[^>]*\btype="([^"]+)"[^>]*>/g)].at(-1)?.[1];
  const sandbox=contextField(scope,'sandbox_mode');
  const blocks=[...scope.matchAll(/<workspace_roots>([\s\S]*?)<\/workspace_roots>/g)];
  if(profile)permissionFields.set('权限配置',['权限配置',profile,source]);
  if(sandbox)permissionFields.set('沙箱模式',['沙箱模式',sandbox,source]);
  if(blocks.length)permissionFields.set('工作区范围',['工作区范围',[...blocks.at(-1)[1].matchAll(/<root>([^<]+)<\/root>/g)].map(m=>m[1]),source]);
 });
 const permissionSummary=permissionFields.size?contextEnvironment([...permissionFields.values()]):'';
 output+=contextSection('权限与访问范围',permissionSummary+buckets.permissions.join(''),permissionSummary?'字段可能来自不同记录；完整环境记录和混合记录仍在原所属分区保留。':'');
 output+=contextSection('指令与背景',buckets.instructions.join(''));
 output+=contextSection('工具定义',buckets.tools.join(''));
 output+=contextSection('附加背景',buckets.background.join(''));
 const meta=contextEnvironment([['启动程序',thread.originator],['来源标记',thread.source],['Token 用量（会话索引）',thread.tokens_used],['会话 ID',thread.id]]);
 const raw=records.length?'<details class="context-raw"><summary>原始记录 · '+records.length+' 条（原始顺序）</summary>'+records.map((r,i)=>'<div class="context-raw-record"><div class="context-entry-meta">'+contextStamp(r)+'</div><pre>'+esc(JSON.stringify(r,null,2))+'</pre></div>').join('')+'</details>':'<p class="context-note">没有可读取的上下文记录。</p>';
 output+=contextSection('记录信息与原文',meta+raw,'下方保留全部上下文记录及其原始顺序，包括重复内容。');
 return output;
}
const turnFieldGroups=[
 ['本轮概览',{model:'模型',effort:'强度',collaboration_mode:'协作模式',cwd:'工作目录',current_date:'日期',timezone:'时区'}],
 ['权限与访问范围',{workspace_roots:'工作区根目录',approval_policy:'审批策略',approvals_reviewer:'审批方',sandbox_policy:'沙箱策略',permission_profile:'权限配置',active_permission_profile:'当前权限配置',file_system_sandbox_policy:'文件系统沙箱'}],
 ['本轮附加指令',{developer_instructions:'开发者指令',user_instructions:'用户指令'}],
 ['其他设置',{disabled_plugin_ids:'禁用插件',multi_agent_mode:'多代理模式',multi_agent_version:'多代理版本',personality:'个性设置',summary:'摘要设置',realtime_active:'实时模式'}]
];
function collaborationParts(value){
 if(!value||typeof value!=='object'||Array.isArray(value))return {overview:value};
 const overview={},other={};
 for(const [key,item] of Object.entries(value)){if(key==='mode')overview[key]=item;else if(key!=='settings')other[key]=item}
 const settings=value.settings;
 let instructions;
 if(settings&&typeof settings==='object'&&!Array.isArray(settings)){
  const rest={};
  for(const [key,item] of Object.entries(settings)){
   if(['model','reasoning_effort'].includes(key))overview[key]=item;
   else if(key==='developer_instructions')instructions={value:item};
   else rest[key]=item;
  }
  if(Object.keys(rest).length||!Object.keys(settings).length)other.settings=rest;
 }else if(Object.hasOwn(value,'settings'))other.settings=settings;
 return {overview,other,instructions};
}
function turnField(key,label,value){
 const detail=['effort','reasoning_effort'].includes(key)&&typeof value==='string'&&value.trim()?effortIndicator(value):contextValue(value);
 const fieldLabel='<span title="'+esc(key)+'">'+esc(label)+'</span>';
 if((value!==null&&typeof value==='object')||String(value).length>140)return '<div class="turn-context-field is-wide"><details><summary>'+fieldLabel+'</summary><div class="turn-field-value">'+detail+'</div></details></div>';
 return '<div class="turn-context-field'+(key==='cwd'?' is-wide':'')+'"><dt>'+fieldLabel+'</dt><dd>'+detail+'</dd></div>';
}
function collaborationPresentation(value){
 const parts=collaborationParts(value),overview=parts.overview;
 if(!overview||typeof overview!=='object'||Array.isArray(overview))return turnField('collaboration_mode','协作模式',overview);
 const labels={mode:'协作模式',model:'协作模型',reasoning_effort:'协作强度'};
 if(!Object.keys(value).length)return turnField('collaboration_mode','协作模式',value);
 return Object.entries(overview).map(([key,item])=>turnField(key,labels[key]||key,item)).join('');
}
function turnSnapshot(record,ordinal=1){
 const fields=record.payload,parts=collaborationParts(fields.collaboration_mode);
 const known=new Set([...turnFieldGroups.flatMap(([,labels])=>Object.keys(labels)),'turn_id','root_turn_id']);
 const extras=Object.keys(fields).filter(key=>!known.has(key));
 return turnFieldGroups.map(([heading,labels])=>{
  let rows=Object.entries(labels).filter(([key])=>Object.hasOwn(fields,key)).map(([key,label])=>{
   if(key==='collaboration_mode')return collaborationPresentation(fields[key]);
   if(heading==='本轮附加指令')return '';
   return turnField(key,label,fields[key]);
  }).join('');
  if(heading==='本轮附加指令'){
   rows=Object.keys(fields).map(key=>{
    if(key==='collaboration_mode'&&parts.instructions)return contextEntry(record,ordinal,'协作模式附加指令',parts.instructions.value,'turn-'+ordinal+'-collaboration-instructions');
    return Object.hasOwn(labels,key)?contextEntry(record,ordinal,labels[key],fields[key],'turn-'+ordinal+'-'+key):'';
   }).join('');
   return contextSection(heading,rows);
  }
  if(heading==='其他设置'){
   if(parts.other&&Object.keys(parts.other).length)rows+=turnField('collaboration_mode','协作模式其他字段',parts.other);
   rows+=extras.map(key=>turnField(key,key,fields[key])).join('');
  }
  return contextSection(heading,rows?'<dl class="turn-context-grid">'+rows+'</dl>':'');
 }).join('');
}
function turnPresentation(records){
 if(!records.length)return '<p class="context-note">未找到本轮配置记录。</p>';
 const latest=records.at(-1),n=records.length;
 let output='<div class="context-snapshot-stamp">'+contextStamp(latest)+'<span>本轮最后一份记录</span></div>'+turnSnapshot(latest,n);
 if(n>1)output+=contextSection('更早的快照',records.slice(0,-1).map((r,i)=>'<details class="context-history"><summary>'+contextStamp(r)+'</summary>'+turnSnapshot(r,i+1)+contextEnvironment([['轮次 ID',r.payload.turn_id],['根轮次 ID',r.payload.root_turn_id]])+'</details>').join(''),'按原始记录顺序排列，未按时间重新排序。');
 return output+contextSection('记录信息与原文',contextEnvironment([['轮次 ID',latest.payload.turn_id],['根轮次 ID',latest.payload.root_turn_id]])+'<details class="context-raw"><summary>原始记录 · '+n+' 份快照（原始顺序）</summary><pre>'+esc(JSON.stringify(records,null,2))+'</pre></details>');
}
let contextRequest=0;
$('#messages').addEventListener('click',event=>{
 const button=event.target.closest('[data-turn-context]');
 if(button)openContextPanel(button.dataset.turnContext);
});
async function openContextPanel(target){
 if(!data)return;
 const turn=typeof target==='string'?target:null,id=current,request=++contextRequest;
 const body=contextPanel.querySelector('.context-panel-body');
 contextPanel.classList.toggle('is-turn-context',Boolean(turn));
 contextPanel.querySelector('h2').textContent=turn?'本轮配置':'环境与上下文';
 contextPanel.querySelector('.context-close').setAttribute('aria-label',turn?'关闭本轮配置':'关闭环境与上下文');
 contextPanel.querySelector('.context-nav').setAttribute('aria-label',turn?'本轮配置快捷导航':'环境与上下文快捷导航');
 setContextFullscreen(contextPanel.classList.contains('is-fullscreen'));
 contextPanel.querySelector('.context-panel-head p').textContent=turn?'当前这一轮记录的配置快照':'这段会话使用的环境和指令';
 body.textContent='正在读取…';buildContextNavigation();
 if(!contextPanel.open)contextPanel.showModal();
 activateDialogEntry(contextPanel,turn?document.querySelector('[data-turn-context="'+CSS.escape(turn)+'"]'):$('#context'));
 try{
  const query=new URLSearchParams({id,view:turn?'turn-context':'context'});
  if(turn)query.set('turn',turn);
  const result=await api('/api/thread?'+query);
  if(request!==contextRequest||current!==id||!contextPanel.open)return;
  body.innerHTML=turn?turnPresentation(result.records):contextPresentation({...data,contextItems:result.items});
 }catch(error){if(request===contextRequest)body.textContent=error.message;return}
 body.scrollTop=0;buildContextNavigation();
 updateContextPreviews();
}
function updateContextPreviews(){
 for(const entry of contextPanel.querySelectorAll('.context-entry')){
  if(!entry.getClientRects().length)continue;
  const preview=entry.querySelector('.context-preview');
  if(preview.querySelector('.context-tools'))entry.classList.add('has-tools');
  const truncated=preview.scrollHeight>preview.clientHeight+2;
  if(!entry.classList.contains('is-expanded'))entry.classList.toggle('is-truncated',truncated);
  entry.querySelector('.context-expand').hidden=!entry.classList.contains('is-truncated');
 }
}
contextPanel.addEventListener('toggle',event=>{
 if(!event.target.matches('.context-history,.context-source-records'))return;
 updateContextPreviews();buildContextNavigation();
},true);
contextPanel.addEventListener('click',e=>{const button=e.target.closest('.context-expand,.context-collapse-top');if(!button)return;const entry=button.closest('.context-entry');const expanded=!entry.classList.contains('is-expanded');const bottom=entry.querySelector('.context-expand');bottom.setAttribute('aria-expanded',String(expanded));bottom.textContent=expanded?'收起全文':'展开全文';entry.classList.toggle('is-expanded',expanded);if(!expanded)entry.scrollIntoView({block:'nearest'})});

function toolDefinitionJsonButton(){return '<button class="tool-definition-json" aria-haspopup="dialog" aria-label="查看工具定义的原始 JSON" title="查看原始 JSON">JSON</button>'}
let toolJsonDialog=null;
function openToolDefinitionJson(){
 if(!activeTool||toolJsonDialog?.open)return;
 clearTimeout(toolHideTimer);
 const raw=JSON.stringify(JSON.parse(activeTool.dataset.toolJson),null,2);
 const dialog=document.createElement('dialog');dialog.className='raw-record-dialog tool-definition-json-dialog';dialog.setAttribute('aria-label','工具定义 · 原始 JSON');
 dialog.innerHTML='<header><strong>工具定义 · 原始 JSON</strong><button class="copy-tool-json">复制</button><button class="close-tool-json" aria-label="关闭原始 JSON">'+uiIcon('X')+'</button></header><pre tabindex="0"></pre>';
 dialog.querySelector('pre').textContent=raw;
 dialog.querySelector('.close-tool-json').onclick=()=>dialog.close();
 dialog.querySelector('.copy-tool-json').onclick=async event=>{const button=event.currentTarget;try{await navigator.clipboard.writeText(raw);button.textContent='已复制'}catch{button.textContent='复制失败'}};
 dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});
 dialog.addEventListener('close',()=>{
  dialog.remove();if(toolJsonDialog===dialog)toolJsonDialog=null;clearTimeout(toolHideTimer);
  if(activeTool?.isConnected&&contextPanel.open&&!toolFullscreen.open){showToolDefinition(activeTool);toolPopover.querySelector('.tool-definition-json').focus()}
 },{once:true});
 document.body.append(dialog);toolJsonDialog=dialog;dialog.showModal();
}
const toolPopover=document.createElement('div');toolPopover.className='tool-definition-popover';toolPopover.hidden=true;toolPopover.setAttribute('role','region');toolPopover.setAttribute('aria-label','工具定义详情');contextPanel.append(toolPopover);
const toolFullscreen=document.createElement('dialog');toolFullscreen.className='tool-definition-fullscreen';toolFullscreen.setAttribute('aria-label','工具定义详情');toolFullscreen.innerHTML='<div class="tool-definition-head"><strong>工具定义详情</strong>'+toolDefinitionJsonButton()+'<button class="tool-definition-restore" aria-label="还原工具详情浮层">'+uiIcon('Collapse')+'<span>还原</span></button><button class="tool-definition-close" aria-label="关闭工具详情">'+uiIcon('X')+'</button></div><div class="tool-definition-body" tabindex="0"></div>';contextPanel.append(toolFullscreen);
let schemaViewerModule,schemaViewerRequest=0;
const schemaViewerCleanups=[];
function clearSchemaViewers(){schemaViewerRequest++;for(const cleanup of schemaViewerCleanups.splice(0))cleanup()}
async function mountSchemaViewers(){
 const request=++schemaViewerRequest;
 const hosts=[...toolFullscreen.querySelectorAll('.schema-viewer-host')];
 if(!hosts.length)return;
 try{
  schemaViewerModule??=import('/vendor/schema-viewer.js').catch(error=>{schemaViewerModule=null;throw error});
  const viewer=await schemaViewerModule;
  if(request!==schemaViewerRequest||!toolFullscreen.open)return;
  for(const host of hosts){
   const raw=host.parentElement.querySelector('.schema-raw pre');
   try{schemaViewerCleanups.push(viewer.mount(host,JSON.parse(raw.textContent)))}
   catch{(host.shadowRoot||host).textContent='Schema 无法展示，请查看下方原始 Schema。';host.classList.add('context-note')}
  }
 }catch{if(request===schemaViewerRequest&&toolFullscreen.open)for(const host of hosts)host.textContent='Schema 查看器加载失败，请查看下方原始 Schema。'}
}
let activeTool=null,toolHideTimer,returningToolFocus=false;
function returnToolFocus(button){returningToolFocus=true;button?.focus();returningToolFocus=false}
function hideToolDefinition(){clearTimeout(toolHideTimer);if(toolJsonDialog?.open)toolJsonDialog.close();toolPopover.hidden=true;if(activeTool)activeTool.setAttribute('aria-expanded','false');activeTool=null;if(toolFullscreen.open)toolFullscreen.close()}
function showToolDefinition(button){if(toolFullscreen.open||toolJsonDialog?.open)return;clearTimeout(toolHideTimer);if(activeTool&&activeTool!==button)activeTool.setAttribute('aria-expanded','false');activeTool=button;button.setAttribute('aria-expanded','true');toolPopover.innerHTML='<div class="tool-definition-head">'+toolDefinitionJsonButton()+'<button class="tool-definition-expand" aria-label="全屏显示工具详情">'+uiIcon('Expand')+'<span>全屏</span></button><button class="tool-definition-close" aria-label="关闭工具详情">'+uiIcon('X')+'</button></div>'+button.nextElementSibling.innerHTML;toolPopover.hidden=false;positionToolDefinition(button);
}
function positionToolDefinition(button){
 const r=button.getBoundingClientRect(),width=Math.min(560,innerWidth-24);toolPopover.style.width=width+'px';toolPopover.style.left=Math.max(12,Math.min(r.left,innerWidth-width-12))+'px';const height=Math.min(420,innerHeight-32);toolPopover.style.maxHeight=height+'px';toolPopover.style.top=Math.max(12,Math.min(r.bottom+6,innerHeight-height-12))+'px';
}
toolFullscreen.querySelector('.tool-definition-restore').onclick=()=>toolFullscreen.close();
toolFullscreen.querySelector('.tool-definition-close').onclick=()=>{const button=activeTool;hideToolDefinition();returnToolFocus(button)};
toolFullscreen.addEventListener('close',()=>{clearSchemaViewers();if(activeTool?.isConnected&&contextPanel.open){showToolDefinition(activeTool);toolPopover.querySelector('.tool-definition-expand').focus()}});
contextPanel.addEventListener('pointerover',e=>{const b=e.target.closest('.tool-definition');if(b&&e.pointerType==='mouse')showToolDefinition(b)});
contextPanel.addEventListener('pointerout',e=>{if(!toolFullscreen.open&&!toolJsonDialog?.open&&e.target.closest('.tool-definition')&&!e.relatedTarget?.closest('.tool-definition,.tool-definition-popover'))toolHideTimer=setTimeout(hideToolDefinition,200)});
toolPopover.addEventListener('pointerenter',()=>clearTimeout(toolHideTimer));toolPopover.addEventListener('pointerleave',()=>{if(!toolFullscreen.open&&!toolJsonDialog?.open&&!toolPopover.contains(document.activeElement))toolHideTimer=setTimeout(hideToolDefinition,200)});
contextPanel.addEventListener('focusin',e=>{const b=e.target.closest('.tool-definition');if(b&&!returningToolFocus)showToolDefinition(b)});
contextPanel.addEventListener('click',e=>{
 if(e.target.closest('.tool-definition-json')){openToolDefinitionJson();return}
 if(toolFullscreen.contains(e.target))return;
 const b=e.target.closest('.tool-definition');if(b){showToolDefinition(b);return}
 if(e.target.closest('.tool-definition-expand')){clearTimeout(toolHideTimer);toolFullscreen.querySelector('.tool-definition-body').innerHTML=activeTool.nextElementSibling.innerHTML;toolPopover.hidden=true;toolFullscreen.showModal();toolFullscreen.querySelector('.tool-definition-body').scrollTop=0;mountSchemaViewers();return}
 if(e.target.closest('.tool-definition-close')||!e.target.closest('.tool-definition-popover'))hideToolDefinition();
});
contextPanel.addEventListener('keydown',e=>{if(e.key==='Escape'&&!toolPopover.hidden){e.preventDefault();e.stopPropagation();const button=activeTool;hideToolDefinition();returnToolFocus(button)}});
contextPanel.addEventListener('close',hideToolDefinition);contextPanel.querySelector('.context-panel-body').addEventListener('scroll',()=>{if(!toolFullscreen.open&&!toolJsonDialog?.open)hideToolDefinition()});window.addEventListener('resize',()=>{if(!toolFullscreen.open&&!toolJsonDialog?.open&&activeTool&&!toolPopover.hidden)positionToolDefinition(activeTool)});

let contextNavTargets=[];
function buildContextNavigation(){
 const body=contextPanel.querySelector('.context-panel-body');
 contextNavTargets=[...body.querySelectorAll('.context-section > h3,.context-entry,.context-raw,.context-source-records > summary,.context-history > summary')].filter(target=>{
  for(let parent=target.parentElement;parent&&parent!==body;parent=parent.parentElement){if(parent.matches('details:not([open])')&&target!==parent.querySelector(':scope > summary'))return false}
  return true;
 });
 contextPanel.querySelector('.context-nav').innerHTML=contextNavTargets.map((target,i)=>{
  target.id='context-anchor-'+i;
  const entry=target.matches('.context-entry');
  const label=entry?(target.querySelector('.context-entry-title')?.textContent|| (target.querySelector('.context-tools')?'工具定义':target.querySelector('.context-record h1,.context-record h2,.context-record h3')?.textContent)||target.querySelector('.context-record')?.textContent.trim().split('\n').find(v=>v.trim())||'上下文记录'):target.matches('.context-raw')?'原始记录':target.textContent;
  const role=entry?target.querySelector('.context-role')?.textContent:'';
  const text=[role,label.slice(0,110)].filter(Boolean).join(' · ');
  return '<button class="context-nav-mark'+(entry?'':' is-section')+'" data-context-anchor="'+i+'" aria-label="'+esc(text)+'" aria-controls="'+target.id+'"><span class="context-nav-tick"></span><span class="nav-caption">'+esc(label)+'</span><span class="context-nav-label">'+esc(text)+'</span></button>';
 }).join('');updateContextNavigation();
}
function updateContextNavigation(){
 const body=contextPanel.querySelector('.context-panel-body');const top=body.getBoundingClientRect().top+32;
 let active=0;contextNavTargets.forEach((target,i)=>{if(target.getBoundingClientRect().top<=top)active=i});
 contextPanel.querySelectorAll('.context-nav-mark').forEach((button,i)=>{if(i===active){const changed=!button.hasAttribute('aria-current');button.setAttribute('aria-current','location');if(changed){const nav=button.parentElement;nav.scrollTop=Math.max(0,button.offsetTop-nav.offsetTop-nav.clientHeight/2)}}else button.removeAttribute('aria-current')});
}
contextPanel.querySelector('.context-nav').addEventListener('click',e=>{const button=e.target.closest('[data-context-anchor]');if(!button)return;const target=contextNavTargets[Number(button.dataset.contextAnchor)];if(!target)return;hideToolDefinition();target.scrollIntoView({block:'start',behavior:'instant'});updateContextNavigation()});
contextPanel.querySelector('.context-panel-body').addEventListener('scroll',updateContextNavigation,{passive:true});

const messageNav=document.createElement('nav');messageNav.className='context-nav message-nav';messageNav.setAttribute('aria-label','会话快捷导航');messageNav.hidden=true;document.body.append(messageNav);
let messageNavTargets=[],messageNavFrame=0;
function buildMessageNavigation(){
 messageNavTargets=[...document.querySelectorAll('#messages > .message.user')];
 if(!messageNavTargets.length)messageNavTargets=[...document.querySelectorAll('#messages > .message.assistant')];
 messageNav.innerHTML=messageNavTargets.map((target,i)=>{
  target.id='message-anchor-'+i;
  const text=(target.querySelector('.content')?.textContent||target.querySelector('.request-preview')?.textContent||'会话记录').trim().replace(/\s+/g,' ');
  const question=text.includes('My request:')?text.split('My request:').slice(1).join('My request:').trim():text;
  const label=(i+1)+'. '+question.slice(0,160);
  let reply=target.nextElementSibling,answer='';
  while(reply&&!reply.matches('.message.user')){if(reply.matches('.message.assistant')){answer=[...reply.querySelectorAll('.assistant-part')].map(p=>p.textContent.trim()).filter(Boolean).pop()||'';if(answer)break}reply=reply.nextElementSibling}
  const preview='<strong class="nav-preview-title">'+esc(question.slice(0,200))+'</strong>'+(answer?'<span class="nav-preview-answer">'+esc(answer.replace(/\s+/g,' ').slice(0,300))+'</span>':'');
  return '<button class="context-nav-mark" data-message-anchor="'+i+'" aria-label="'+esc(label)+'" aria-controls="'+target.id+'"><span class="context-nav-tick"></span><span class="nav-caption">'+esc(label)+'</span><span class="context-nav-label">'+preview+'</span></button>';
 }).join('');messageNav.hidden=!messageNavTargets.length;updateMessageNavigation();
}
function updateMessageNavigation(){
 const top=document.querySelector('main > header').getBoundingClientRect().bottom+24;let active=0;
 messageNavTargets.forEach((target,i)=>{if(target.getBoundingClientRect().top<=top)active=i});
 messageNav.querySelectorAll('button').forEach((button,i)=>{if(i===active){const changed=!button.hasAttribute('aria-current');button.setAttribute('aria-current','location');if(changed){const nav=button.parentElement;nav.scrollTop=i===messageNavTargets.length-1?nav.scrollHeight:Math.max(0,button.offsetTop-nav.offsetTop-nav.clientHeight/2)}}else button.removeAttribute('aria-current')});
}
messageNav.addEventListener('click',e=>{const button=e.target.closest('[data-message-anchor]');if(!button)return;const target=messageNavTargets[Number(button.dataset.messageAnchor)];if(!target)return;const main=document.querySelector('main'),header=main.querySelector('header');main.scrollTo({top:main.scrollTop+target.getBoundingClientRect().top-header.getBoundingClientRect().bottom-16,behavior:'instant'});updateMessageNavigation()});
document.querySelector('main').addEventListener('scroll',()=>{if(messageNavFrame)return;messageNavFrame=requestAnimationFrame(()=>{messageNavFrame=0;updateMessageNavigation()})},{passive:true});
window.addEventListener('resize',updateMessageNavigation);

function positionNavigationPreview(event){
 const button=event.target.closest('.context-nav-mark');if(!button)return;
 const card=button.querySelector('.context-nav-label');if(!card)return;
 const r=button.getBoundingClientRect(),width=Math.min(360,innerWidth-64);
 card.style.width=width+'px';card.style.right='auto';card.style.left=Math.max(12,r.left-width-12)+'px';
 card.style.top=Math.max(12,Math.min(r.top+r.height/2-card.offsetHeight/2,innerHeight-card.offsetHeight-12))+'px';
}
for(const nav of [messageNav,contextPanel.querySelector('.context-nav')]){nav.addEventListener('pointerover',positionNavigationPreview);nav.addEventListener('focusin',positionNavigationPreview)}

const sessionSidebar=document.querySelector('body > aside');
const sidebarResize=document.createElement('div');sidebarResize.className='sidebar-resize';sidebarResize.tabIndex=0;sidebarResize.setAttribute('role','separator');sidebarResize.setAttribute('aria-orientation','vertical');sidebarResize.setAttribute('aria-label','调整会话列表宽度');sidebarResize.title='拖拽调整宽度，双击还原；方向键微调';sessionSidebar.append(sidebarResize);
let sidebarPreferred=Number(localStorage.getItem('sidebar-width'))||300;
function setSidebarWidth(width,save=false){
 const max=Math.min(600,Math.max(240,innerWidth-380));const value=Math.round(Math.max(240,Math.min(max,width)));
 sessionSidebar.style.width=value+'px';sidebarResize.setAttribute('aria-valuemin','240');sidebarResize.setAttribute('aria-valuemax',String(max));sidebarResize.setAttribute('aria-valuenow',String(value));
 if(save){sidebarPreferred=value;localStorage.setItem('sidebar-width',String(value))}
}
setSidebarWidth(sidebarPreferred);
let sidebarDrag=null;
sidebarResize.addEventListener('pointerdown',e=>{if(e.button!==0||innerWidth<=700)return;e.preventDefault();sidebarDrag={id:e.pointerId,start:e.clientX,width:sessionSidebar.getBoundingClientRect().width};sidebarResize.setPointerCapture(e.pointerId);document.body.classList.add('resizing-sidebar')});
sidebarResize.addEventListener('pointermove',e=>{if(sidebarDrag&&e.pointerId===sidebarDrag.id)setSidebarWidth(sidebarDrag.width+e.clientX-sidebarDrag.start)});
function finishSidebarResize(e){if(!sidebarDrag||e.pointerId!==sidebarDrag.id)return;setSidebarWidth(sessionSidebar.getBoundingClientRect().width,true);sidebarDrag=null;document.body.classList.remove('resizing-sidebar');if(sidebarResize.hasPointerCapture(e.pointerId))sidebarResize.releasePointerCapture(e.pointerId)}
sidebarResize.addEventListener('pointerup',finishSidebarResize);sidebarResize.addEventListener('pointercancel',finishSidebarResize);sidebarResize.addEventListener('lostpointercapture',finishSidebarResize);
sidebarResize.addEventListener('dblclick',()=>setSidebarWidth(300,true));
sidebarResize.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const width=sessionSidebar.getBoundingClientRect().width;setSidebarWidth(e.key==='Home'?240:e.key==='End'?600:width+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?40:10),true)});
window.addEventListener('resize',()=>setSidebarWidth(sidebarPreferred));

$('#refresh').innerHTML=uiIcon('Reload');$('#refresh').setAttribute('aria-label','刷新会话');
$('#theme').innerHTML=uiIcon('ColorTheme');$('#theme').title='切换深浅色';$('#back').innerHTML=uiIcon('ChevronLeft')+'<span>会话</span>';
$('#context').innerHTML=uiIcon('Layers')+'<span class="entry-label">上下文</span>';
$('#context').title='环境与上下文';
$('#context').setAttribute('aria-label','环境与上下文');
$('#context').classList.add('dialog-entry');$('#context').setAttribute('aria-expanded','false');$('#context').setAttribute('aria-controls','context-panel');
$('#welcome .mark').innerHTML='<img src="/assets/microscope.png" alt="Codex Microscope">';


// Detail payloads and updates are scoped to the selected thread.
const detailCache=new Map();let searchRequest=0,revisionState=null,pendingLive=false,loadingOlder=false,updatingLive=false;
const newMessages=document.createElement('button');newMessages.id='new-messages';newMessages.hidden=true;newMessages.textContent='有新消息 · 跳到最新';document.querySelector('main').append(newMessages);
function relationLinks(){const r=data?.relations;if(!r)return '';const links=[...(r.parent?[['主会话',r.parent]]:[]),...(r.children||[]).map(t=>['子代理',t])];return links.length?'<nav class="session-relations" aria-label="关联会话">'+links.map(([label,t])=>`<button aria-haspopup="dialog" data-thread-link="${esc(t.id)}">${label} · ${esc(threadTitle(t))}</button>`).join('')+'</nav>':''}
function toolJsonMarker(){return '<button type="button" class="raw-record-button" aria-haspopup="dialog" aria-label="查看这条执行记录的完整 JSON">JSON</button>'}
function commandReturn(x,wrapped=false){
 let raw=x.output;if(raw==null)return null;if(typeof raw==='object')return raw;
 if(wrapped){const match=String(raw).match(/^Script completed\r?\nWall time [^\n]+\r?\nOutput:\r?\n([\s\S]*)$/);if(!match)return null;raw=match[1]}
 try{const result=JSON.parse(raw);return result&&typeof result==='object'&&!Array.isArray(result)?result:null}catch{return null}
}
function actionLabel(label,state=''){
 let text=String(label||''),suffix='';
 if(state&&text.endsWith(' · '+state)){suffix=' · '+state;text=text.slice(0,-suffix.length)}
 const match=text.match(/^((?:请求|用户)?运行命令) (.+)$/s);
 return (match?esc(match[1])+' <code class="command-inline">'+esc(match[2])+'</code>':esc(text))+esc(suffix);
}
function callButtons(item){
 const count=item.native_results?.length||0;
 const results=count?'<button type="button" class="inner-results-button" aria-haspopup="dialog">返回结果 · '+count+'</button>':'';
 return '<span class="call-buttons">'+results+toolJsonMarker()+'</span>';
}
function innerResultCard(record,index){
 const output=record.output==null?'未记录输出':record.output===''?'无输出':printable(record.output);
 const card=document.createElement('li');
 card.innerHTML='<div class="inner-result-heading"><strong>结果 '+(index+1)+'</strong><span>'+esc(commandStatus(record).label)+'</span></div>'+
  shellSource(record.command,'命令源码')+commandFields({cwd:record.cwd,session_id:record.session_id})+
  '<h4>输出</h4><pre></pre>';
 card.lastElementChild.textContent=output;
 return card;
}
function callName(item){
 if(item.record_type==='native_event'||item.standalone_native)return '<span class="call-name">'+(item.native_results?.length?'独立执行记录':'独立事件记录')+'</span>';
 return item.name?'<span class="call-name"><code>'+esc(item.name)+'</code></span>':'';
}
function associationNote(item){
 if(!item.standalone_native)return '';
 const reasons={ambiguous_process:'同一进程编号存在多个启动来源，未猜测归属。',conflicting_process:'进程编号对应的调用与已记录命令或工作目录冲突。',conflicting_cwd:'调用参数与执行事件的工作目录冲突，未合并。',database_record:'来自数据库的执行记录，未记录对应工具请求。',ambiguous_command:'同一命令存在多个候选调用，未猜测归属。',ambiguous_id:'调用 ID 对应多条记录，未猜测归属。',unknown_id:'记录中的调用 ID 未找到同轮请求。',already_linked:'候选调用已有同命令执行记录，未重复关联。',missing_turn:'缺少轮次信息，未关联已返回的调用。',ambiguous_pending:'存在多个待返回调用，无法确认归属。',no_matching_call:'未找到可确认关联的工具调用。',independent_source:'这是一条独立的命令执行或终端交互记录。',unlinked_event:'未找到可确认关联的工具调用。'};
 return '<p class="context-note association-note">'+esc(reasons[item.association_reason]||reasons.unlinked_event)+'</p>';
}
function commandStatus(result){
 const code=result?.exit_code,hasCode=typeof code==='number'&&Number.isInteger(code);
 if(hasCode)return {label:code===0?'已完成':'已退出 · 退出码 '+code,failed:code!==0};
 if(result?.status==='declined')return {label:'执行请求被拒绝',failed:false};
 if(result?.status==='failed')return {label:'执行失败',failed:true};
 if(result?.session_id!=null)return {label:'命令仍在运行（本次返回时）',failed:false};
 if(['inProgress','in_progress'].includes(result?.status))return {label:'命令进行中',failed:false};
 if(result?.output_only&&result.status!=='completed')return {label:'仅记录输出 · 退出码未记录',failed:false};
 return {label:result?.status==='completed'?'执行已结束 · 退出码未记录':'命令结果未确认',failed:false};
}
function commandFields(object){
 return '<dl class="native-parameters">'+Object.entries(object).filter(([,v])=>v!=null).map(([key,value])=>'<div><dt>'+esc(({name:'工具',call_id:'调用 ID',turn_id:'轮次 ID',time:'记录时间',index:'记录序号（从 0 开始）',command:'命令',process_id:'进程标识',duration_ms:'耗时（毫秒）',model:'模型',effort:'推理力度',workdir:'工作目录',cwd:'工作目录',yield_time_ms:'返回等待（ms）',max_output_tokens:'输出上限（token）',session_id:'执行会话',chars:'输入字符',path:'文件路径',wall_time_seconds:'本次等待（秒）',original_token_count:'截断前输出（token）',chunk_id:'输出块',exit_code:'退出码'})[key]||key)+'</dt><dd>'+esc(typeof value==='string'?value:JSON.stringify(value,null,2))+'</dd></div>').join('')+'</dl>';
}
function orchestrationBody(x,limit=24){
 const wrapped=x.envelope?.script??/^(?:functions\.)?exec$/.test(x.name||'');
 if(wrapped){
  const lines=String(x.text||'').split('\n');
  const script=nativeHighlightedLines(lines,'orchestration.js').join('\n');
  return '<div class="exec-source"><details class="command-orchestration" open><summary>编排脚本 <small>JS · '+lines.length+' 行</small></summary><pre tabindex="0" aria-label="JavaScript 编排脚本" class="native-code-view orchestration-code"><code class="language-javascript">'+script+'</code></pre></details>'+callButtons(x)+'</div>';
 }
 const metadata=commandFields({name:x.name,call_id:x.call_id,turn_id:x.turn_id,time:x.time,index:x.index,model:x.turn_context?.model,effort:x.turn_context?.effort});
 return '<details class="native-original command-orchestration"><summary>原始工具调用 · '+esc(x.name||'工具')+'</summary><p class="context-note">保留原始输入与工具返回。</p>'+metadata+'<div class="by">工具输入</div><pre>'+esc(x.text||'')+'</pre><div class="by">工具返回</div><pre>'+esc(x.output??'尚未返回')+'</pre></details>';
}
function toolRecordTable(x){
 const leaf=value=>'<pre>'+esc(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre>';
 const objectFields=(object,highlightCode=false)=>'<dl class="tool-value-fields">'+Object.entries(object).map(([key,item])=>{
  const code=highlightCode&&key==='code'&&typeof item==='string';
  const wide=code||item!==null&&typeof item==='object'||key.length>24||typeof item==='string'&&(item.length>80||item.includes('\n'));
  return '<div'+(wide?' class="is-wide"':'')+'><dt title="'+esc(key)+'">'+esc(key)+'</dt><dd>'+(code?'<pre class="native-code-view tool-js-code" aria-label="工具代码，JavaScript 语法高亮"><code class="language-javascript">'+nativeHighlightedLines(item.split('\n'),'tool.js').join('\n')+'</code></pre>':Array.isArray(item)?arrayList(item):leaf(item))+'</dd></div>';
 }).join('')+'</dl>';
 const arrayList=items=>items.length?'<ol class="tool-value-array">'+items.map(item=>'<li>'+(Array.isArray(item)?arrayList(item):item&&typeof item==='object'?objectFields(item):leaf(item))+'</li>').join('')+'</ol>':leaf('[]');
 const valueCell=(value,highlightCode=false)=>{
  let parsed=value;if(typeof value==='string'){try{parsed=JSON.parse(value)}catch{}}
  if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed)&&Object.keys(parsed).length)return objectFields(parsed,highlightCode);
  if(Array.isArray(parsed))return arrayList(parsed);
  return leaf(parsed);
 };
 const fieldLabels={name:'工具',text:'调用参数',output:'工具返回',native_results:'原生执行结果'};
 const orderedKeys=['text','output','name','native_results'].filter(key=>Object.hasOwn(x,key));
 const rows=orderedKeys.map(key=>{const value=x[key];return '<tr><th scope="row" title="'+esc(key)+'">'+esc(fieldLabels[key]||key)+'</th><td>'+valueCell(value,key==='text'&&/(?:^|[._])js$/.test(x.name||''))+'</td></tr>'}).join('');
 let related='';if(/spawn_agent/.test(x.name||'')){let result;try{result=JSON.parse(x.output)}catch{}const child=result&&(threads.find(t=>t.id===result.agent_id)||(data.relations?.children||[]).find(t=>t.task_path&&t.task_path===result.task_name));if(child)related='<button class="tool-worker-link" aria-haspopup="dialog" data-thread-link="'+esc(child.id)+'">查看子代理 · '+esc(threadTitle(child))+'</button>'}
 return '<section class="tool-record"><table class="tool-record-table"><tbody>'+rows+'</tbody></table>'+related+'</section>';
}
function nativeReadRange(command){
 const raw=String(command||'').trim();
 // Only a single literal file operand proves that the output starts at a file line.
 const file=String.raw`(?:[^\s'"-][^\s'"]*|"[^"]+"|'[^']+')`;
 if(/[;&|<>$`\n*?]/.test(raw))return {label:'由读取命令决定',start:null};
 const sed=raw.match(new RegExp(`^sed\\s+-n\\s+['"]?(\\d+)(?:,(\\d+))?p['"]?\\s+(?:--\\s+)?${file}$`));
 if(sed)return {label:'第 '+sed[1]+(sed[2]?'–'+sed[2]:'')+' 行',start:Number(sed[1])};
 const edge=raw.match(new RegExp(`^(head|tail)\\s+(?:(?:-n\\s*|-)(\\+?\\d+)\\s+)?(?:--\\s+)?${file}$`));
 if(edge){
  const count=edge[2]||'10';
  if(edge[1]==='tail'&&count.startsWith('+'))return {label:'从第 '+count.slice(1)+' 行起',start:Math.max(1,Number(count))};
  return {label:(edge[1]==='head'?'前 ':'最后 ')+count+' 行',start:edge[1]==='head'?1:null};
 }
 if(new RegExp(`^cat\\s+(?:--\\s+)?${file}$`).test(raw))return {label:'全文',start:1};
 return {label:'由读取命令决定',start:null};
}
function nativeSyntax(path){
 const filename=String(path||'').split(/[\\/]/).pop().toLowerCase(),extension=filename.split('.').pop();
 const languages={js:['javascript','JavaScript'],mjs:['javascript','JavaScript'],cjs:['javascript','JavaScript'],jsx:['javascript','JSX'],ts:['typescript','TypeScript'],mts:['typescript','TypeScript'],cts:['typescript','TypeScript'],tsx:['typescript','TSX'],py:['python','Python'],pyw:['python','Python'],css:['css','CSS'],scss:['scss','SCSS'],html:['xml','HTML'],htm:['xml','HTML'],xml:['xml','XML'],svg:['xml','SVG'],json:['json','JSON'],md:['markdown','Markdown'],swift:['swift','Swift'],rs:['rust','Rust'],sh:['bash','Shell'],bash:['bash','Shell'],zsh:['bash','Shell'],yaml:['yaml','YAML'],yml:['yaml','YAML'],toml:['ini','TOML'],ini:['ini','INI'],c:['c','C'],h:['c','C'],cpp:['cpp','C++'],hpp:['cpp','C++'],m:['objectivec','Objective-C'],mm:['objectivec','Objective-C++'],go:['go','Go'],java:['java','Java'],kt:['kotlin','Kotlin'],sql:['sql','SQL'],rb:['ruby','Ruby']};
 return languages[extension]||['plaintext','Text'];
}
function nativeLanguage(path){return nativeSyntax(path)[1]}
function nativeHighlightedLines(lines,path){
 const plain=()=>lines.map(line=>esc(line||' ')),language=nativeSyntax(path)[0],source=lines.join('\n');
 if(language==='plaintext'||source.length>60000||!globalThis.hljs?.getLanguage(language))return plain();
 try{
  const highlighted=hljs.highlight(source,{language,ignoreIllegals:true}).value,stack=[];
  // A token can span lines. Balance its spans in each row without losing its state.
  return highlighted.split('\n').map(line=>{
   const prefix=stack.join('');for(const match of line.matchAll(/<span\b[^>]*>|<\/span>/g)){if(match[0]==='</span>')stack.pop();else stack.push(match[0])}
   return prefix+(line||' ')+'</span>'.repeat(stack.length);
  });
 }catch{return plain()}
}
function nativeCodePreview(text,{start=1,limit=24,diff=false,path='',label='读取输出',numbered=true}={}){
 const lines=String(text).split('\n');if(lines.at(-1)==='')lines.pop();
 const shown=lines.slice(0,limit),highlighted=diff?null:nativeHighlightedLines(shown,path);let oldLine=1,newLine=1,inHunk=false;
 const rows=shown.map((line,index)=>{
  if(!diff)return '<div class="native-code-row'+(numbered?'':' unnumbered')+'">'+(numbered?'<span class="native-line-number" aria-hidden="true">'+(start+index)+'</span>':'')+'<code>'+highlighted[index]+'</code></div>';
  const hunk=line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(hunk){oldLine=Number(hunk[1]);newLine=Number(hunk[2]);inHunk=true}
  if(line.startsWith('@@'))inHunk=true;
  const meta=line.startsWith('@@')||(!inHunk&&/^(?:diff |index |--- |\+\+\+ )/.test(line))||line.startsWith('\\');
  if(meta)return '<div class="native-diff-meta">'+esc(line)+'</div>';
  const add=line.startsWith('+'),remove=line.startsWith('-'),before=add?'':oldLine++,after=remove?'':newLine++;
  return '<div class="native-diff-row '+(add?'is-add':remove?'is-remove':'')+'"><span class="native-line-number" aria-hidden="true">'+before+'</span><span class="native-line-number" aria-hidden="true">'+after+'</span><span class="native-diff-sign">'+(add?'+':remove?'−':' ')+'</span><code>'+esc((add||remove||line.startsWith(' ')?line.slice(1):line)||' ')+'</code></div>';
 }).join('');
 return {html:'<div class="native-code-view'+(diff?' native-diff-view':'')+'" tabindex="0" aria-label="'+esc(diff?'文件差异，旧行号与新行号':label)+'">'+(rows||'<p class="context-note">输出为空</p>')+'</div>',total:lines.length,remaining:Math.max(0,lines.length-limit)};
}
function nativeOutput(x,source){
 if(source)return typeof source.output==='string'?source.output:null;
 if(x.output==null)return null;
 try{const parsed=JSON.parse(x.output);if(typeof parsed.output==='string')return parsed.output}catch{}
 return /^(?:functions\.)?exec$/.test(x.name||'')?null:String(x.output);
}
function nativeSearchHighlight(text,query,command=''){
 const fixed=/(?:^|\s)(?:-[A-Za-z]*F[A-Za-z]*|--fixed-strings)(?:\s|$)/.test(command);
 const terms=(fixed?[query]:String(query||'').split('|')).filter(term=>term&&term.length<=128&&(fixed||!/[.*+?{}()[\]\\^$]/.test(term))).slice(0,32);
 const ignoreCase=/(?:^|\s)(?:-[A-Za-z]*i[A-Za-z]*|--ignore-case)(?:\s|$)/.test(command)||(/(?:^|\s)(?:-S|--smart-case)(?:\s|$)/.test(command)&&!/[A-Z]/.test(query));
 const original=String(text),haystack=ignoreCase?original.toLowerCase():original;let offset=0,html='',matches=0;
 while(offset<original.length&&terms.length&&matches<128){
  let start=-1,length=0;
  for(const term of terms){const at=haystack.indexOf(ignoreCase?term.toLowerCase():term,offset);if(at>=0&&(start<0||at<start||(at===start&&term.length>length))){start=at;length=term.length}}
  if(start<0)break;
  html+=esc(original.slice(offset,start))+'<mark>'+esc(original.slice(start,start+length))+'</mark>';offset=start+length;matches++;
 }
 return html+esc(original.slice(offset));
}
function nativeSearchRecords(output,action,command=''){
 const lines=String(output).replace(/\x1b\[[0-9;]*m/g,'').split(/\r?\n/).filter(line=>line.trim());
 if(!lines.length)return {records:[],filesOnly:false};
 const records=[];
 if(/(?:^|\s)--json(?:\s|$)/.test(command)){
  try{for(const line of lines){const event=JSON.parse(line);if(!['begin','end','summary','match','context'].includes(event.type))return null;if(event.type!=='match')continue;const data=event.data,text=data?.lines?.text?.replace(/\r?\n$/,'');if(typeof data?.path?.text!=='string'||!Number.isInteger(data.line_number)||typeof text!=='string'||text.includes('\n'))return null;records.push({path:data.path.text,line:data.line_number,text})}}catch{return null}
  return {records,filesOnly:false};
 }
 const filesOnly=/(?:^|\s)(?:-[A-Za-z]*l[A-Za-z]*|--files|--files-with-matches|--files-without-match)(?:\s|$)/.test(command)||(/^\s*(?:\S*\/)?grep\s/.test(command)&&/(?:^|\s)-[A-Za-z]*L[A-Za-z]*(?:\s|$)/.test(command));
 if(filesOnly){if(lines.some(line=>/^(?:rg|grep|find|error|warning):/i.test(line)))return null;return {records:lines.map(path=>({path,line:null,text:''})),filesOnly:true}}
 let heading='';const column=/(?:^|\s)(?:--column|--vimgrep)(?:\s|$)/.test(command),headingMode=/(?:^|\s)--heading(?:\s|$)/.test(command);
 for(const line of lines){
  const single=line.match(/^(\d+):(.*)$/),full=single?null:line.match(/^(.+?):(\d+):(.*)$/);
  if(full||single){
   const path=full?full[1]:heading||action.path||'搜索范围',number=Number(full?full[2]:single[1]);let text=full?full[3]:single[2];
   if(column){const at=text.match(/^\d+:(.*)$/);if(!at)return null;text=at[1]}
   const scopeOnly=!full&&!heading&&(!action.path||!/(?:\.[^/]+$|(?:^|\/)(?:Makefile|Dockerfile|LICENSE)$)/.test(action.path));
   records.push({path,line:number,text,...(scopeOnly?{scopeOnly:true}:{})});
  }else if(headingMode&&!/^(?:rg|grep|error|warning):/i.test(line))heading=line;
  else return null;
 }
 return {records,filesOnly:false};
}
function nativeSearchBody(x,index,limit=24){
 const action=x.native_actions[index],source=x.native_results?.[action.result_index],command=action.cmd||action.command||source?.command||'',output=nativeOutput(x,source);
 const shared=source?source.action_count>1:(x.native_actions?.length||0)>1;
 const parsed=output!=null&&!shared?nativeSearchRecords(output,action,command):null;
 const noMatches=!shared&&output!=null&&!output.trim()&&Number(source?.exit_code)===1&&/^\s*(?:rg|grep)\s/.test(command);
 const failed=!noMatches&&(source?.status==='failed'||(source?.exit_code!=null&&Number(source.exit_code)!==0));

 const field=(name,value)=>value?'<div><dt>'+esc(name)+'</dt><dd>'+esc(value)+'</dd></div>':'';
 const parameters=field('搜索内容',action.query||'未记录')+field('搜索范围',action.path||'工作目录')+field('工作目录',typeof source?.cwd==='string'?source.cwd.replace(/^file:\/\//,''):'')+field('命令',command);
 let results='',remaining=0;
 if(parsed&&!failed&&(parsed.records.length||noMatches||source?.exit_code===0)){
  const groups=new Map();for(const record of parsed.records){if(!groups.has(record.path))groups.set(record.path,[]);groups.get(record.path).push(record)}
  const statistics=parsed.filesOnly?groups.size+' 个文件':parsed.records.length+' 行匹配 · '+(parsed.records.some(record=>record.scopeOnly)?'按搜索范围展示':groups.size+' 个文件');
  results='<div class="native-result-heading"><h4>搜索结果</h4><small>'+statistics+'</small></div>';
  if(!parsed.records.length)results+='<p class="native-search-empty">没有匹配结果</p>';
  else{
   const shown=parsed.records.slice(0,limit),visible=new Map();remaining=Math.max(0,parsed.records.length-limit);
   for(const record of shown){if(!visible.has(record.path))visible.set(record.path,[]);visible.get(record.path).push(record)}
   results+='<div class="native-search-results" tabindex="0" aria-label="搜索匹配结果">'+[...visible].map(([path,records])=>'<section class="native-search-file"><div class="native-search-file-heading" title="'+esc(path)+'">'+actionIcon('BookOpen')+'<strong>'+esc(path)+'</strong>'+(parsed.filesOnly?'':'<small>'+groups.get(path).length+' 行</small>')+'</div>'+(parsed.filesOnly?'':records.map(record=>'<div class="native-code-row native-search-match"><span class="native-line-number" aria-label="第 '+record.line+' 行">'+record.line+'</span><code>'+nativeSearchHighlight(record.text,action.query,command)+'</code></div>').join(''))+'</section>').join('')+'</div>';
  }
 }else{
  results='<div class="native-result-heading"><h4>'+(shared?'所属命令的合并输出':'搜索输出')+'</h4><small>Text</small></div>';
  if(shared)results+='<p class="native-shared-note">同一命令包含多项操作，保留合并输出，不按搜索结果拆分。</p>';
  else if(output&& !failed)results+='<p class="native-shared-note">保留原始格式，未推断匹配行数。</p>';
  if(output==null)results+='<p class="context-note">尚未记录搜索输出。</p>';
  else{const preview=nativeCodePreview(output,{limit});remaining=preview.remaining;results+=preview.html}
 }
 const more=remaining?'<button data-native-more="'+(limit+200)+'">'+(remaining>200?'再显示 200 项':'展开余下 '+remaining+' 项')+'</button>':'',collapse=limit>24?'<button data-native-more="24">收起内容</button>':'';
 return '<dl class="native-parameters">'+parameters+'</dl>'+results+'<div class="native-preview-actions">'+more+collapse+'</div>';

}

function nativeActionBody(x,index,limit=24,sharedFeedback=false,icon){
 if(x.native_actions?.[index]?.type==='search')return nativeSearchBody(x,index,limit);
 const action=x.native_actions?.[index];if(!action)return '';
 const source=x.native_results?.[action.result_index],isEdit=action.type==='edit',shared=source?source.action_count>1:(x.native_actions?.length||0)>1;
 const command=action.cmd||action.command||(source?.action_count===1?source.command:'')||'',range=nativeReadRange(command),output=nativeOutput(x,source);
 const field=(name,value)=>value?'<div><dt>'+esc(name)+'</dt><dd>'+esc(value)+'</dd></div>':'';
 if(action.type==='list_files'){
  const limitLabel=Number.isInteger(action.output_limit)?'标准输出最多 '+action.output_limit+' 行':'';
  const scope=field('范围',action.path||'未指定路径')+field('工作目录',source?.cwd)+field('输出范围',limitLabel)+field('命令',command);
  return '<dl class="native-parameters">'+scope+'</dl><div class="native-result-heading"><h4>列举结果</h4></div>'+outputPreview(output,limit);
 }
 const parameters=field('文件',action.path||action.name||'未记录')+field(isEdit?'操作':'读取范围',isEdit?'修改文件':range.label)+field('工作目录',typeof source?.cwd==='string'?source.cwd.replace(/^file:\/\//,''):'')+field('命令',command);
 let result='',remaining=0;
 if(isEdit){
  const counts=Number.isFinite(action.additions)&&Number.isFinite(action.deletions)?'<span class="native-io-delta"><b class="native-added">+'+action.additions+'</b> <b class="native-deleted">−'+action.deletions+'</b></span>':'';
  result='<div class="native-result-heading">'+(icon?actionIcon(icon):'')+'<h4>'+(source?.status==='failed'?'尝试的文件变更':'文件变更')+'</h4>'+counts+'</div>';
  if(typeof action.diff==='string'){
   const preview=nativeCodePreview(action.diff,{limit,diff:true});remaining=preview.remaining;
   result+=preview.html;
  }else result+='<p class="context-note">原生日志未记录文件 diff，可展开原始调用查看。</p>';
  if(output!=null&&!sharedFeedback)result+='<details class="native-feedback" data-key="native-feedback-'+x.index+'-'+index+'"><summary>执行反馈'+(source?.exit_code!=null?' · 退出码 '+esc(source.exit_code):'')+'</summary><pre>'+esc(output||'输出为空')+'</pre></details>';
 }else{
  const heading=shared?(source?'所属命令的合并输出':'所属调用的合并输出'):'读取结果';
  result='<div class="native-result-heading"><h4>'+heading+'</h4><small>'+esc(nativeLanguage(action.path||action.name))+'</small></div>';
  if(shared)result+='<p class="native-shared-note">包含同一调用的多项操作输出，未按文件拆分；按当前文件类型着色，行号为输出行号。</p>';
  else if(range.start==null&&output!=null)result+='<p class="native-shared-note">左侧为输出行号。</p>';
  if(output!=null){const preview=nativeCodePreview(output,{start:shared?1:range.start??1,limit,path:action.path||action.name});remaining=preview.remaining;result+=preview.html}
  else result+='<p class="context-note">尚未记录读取输出。</p>';
 }
 const more=remaining?'<button data-native-more="'+(limit+200)+'">'+(remaining>200?'再显示 200 行':'展开余下 '+remaining+' 行')+'</button>':'';
 const collapse=limit>24?'<button data-native-more="24">收起内容</button>':'';
 return '<dl class="native-parameters">'+parameters+'</dl>'+result+'<div class="native-preview-actions">'+more+collapse+'</div>';

}

function printable(value){
 return typeof value==='string'?value:JSON.stringify(value,null,2);
}
function operationOutput(item,op){
 if(op.event)return op.event.error??op.event.result??op.event.results;
 if(op.returned)return op.returned;
 if(op.evidence.includes('direct'))return item.output;
 return null;
}
function outputPreview(output,limit){
 if(output==null)return '<p class="context-note">尚无可确认的输出。</p>';
 const preview=nativeCodePreview(printable(output),{limit,label:'工具输出',numbered:false});
 const more=preview.remaining?`<button data-native-more="${limit+200}">展开更多输出（余 ${preview.remaining} 行）</button>`:'';
 const less=limit>24?'<button data-native-more="24">收起内容</button>':'';
 return preview.html+'<div class="native-preview-actions">'+more+less+'</div>';
}
function shellSource(command,label){
 if(typeof command!=='string')return '';
 const lines=command.split(/\r?\n/),multiline=/[\r\n]/.test(command.trim()),folded=multiline||command.length>160;
 const head=command.trim().split(/\r?\n/)[0];
 const language=/^(?:\S*\/)?python[\d.]*\s/.test(head)?'Python':/^(?:\S*\/)?(?:node|nodejs|deno|bun)\s/.test(head)?'JavaScript':'Shell';
 const code=nativeHighlightedLines(lines,'command.sh').join('\n');
 const body='<pre tabindex="0" class="native-code-view command-source"><code class="language-bash">'+code+'</code></pre>';
 const copy='<button type="button" class="copy-command" data-command="'+esc(JSON.stringify(command))+'" aria-label="复制完整命令源码">复制</button>';
 if(folded)return '<div class="command-source-wrap"><details class="command-source-details"><summary>命令源码 <small>· '+language+' · '+lines.length+' 行</small></summary>'+body+'</details>'+copy+'</div>';
 return '<div class="command-source-wrap"><div class="command-source-heading">'+esc(label||'命令源码')+copy+'</div>'+body+'</div>';
}
function commandTiming(result){
 const seconds=Number.isFinite(result?.duration_ms)?result.duration_ms/1000:result?.wall_time_seconds;
 return Number.isFinite(seconds)?' · '+Number(seconds.toFixed(2))+' 秒':'';
}
function sessionContent(op,result,limit,inputOnly,raw){
 const knownArgs=op.arguments!=null&&typeof op.arguments==='object';
 const {chars,...fields}=knownArgs?op.arguments:{};
 let html=commandFields(fields);
 if(typeof chars==='string'&&chars.length){
  const input=chars==='\x03'?'Ctrl-C':JSON.stringify(chars);
  html+='<details class="native-feedback"><summary>输入内容</summary><pre>'+esc(input)+'</pre></details>';
 }
 if(inputOnly)return html;
 if(result&&typeof result==='object'){
  const returnedId=result.session_id===fields.session_id?null:result.session_id;
  html+=commandFields({session_id:returnedId,wall_time_seconds:result.wall_time_seconds,chunk_id:result.chunk_id,original_token_count:result.original_token_count});
 }
 const output=result&&Object.hasOwn(result,'output')?result.output:raw;
 if(output===''){
  const polled=knownArgs&&(chars===undefined||chars==='');
  return html+'<p class="context-note">'+(polled?'此次轮询没有新增输出。':'此次交互返回空输出。')+'</p>';
 }
 return html+'<div class="native-result-heading"><h4>此次终端返回</h4></div>'+outputPreview(output,limit);
}
function shellContent(op,result,limit,inputOnly=false,raw=null){
 if(op.kind==='session')return sessionContent(op,result,limit,inputOnly,raw);
 const args=op.arguments||{};
 const {cmd,command,...parameters}=typeof args==='object'?args:{};
 const source=result?.command||cmd||command;
 const code=shellSource(source,'命令源码');
 const fields={...parameters,...(result?.cwd?{cwd:result.cwd}:{})};
 const metadata={session_id:result?.session_id};
 return unknownArgumentsNote(op)+(code||(op.kind==='run'?'<p class="context-note">命令参数见原始调用。</p>':''))+(Object.values(fields).some(v=>v!=null)?commandFields(fields):'')+(inputOnly?'':'<div class="native-result-heading"><h4>输出</h4></div>'+commandFields(metadata)+outputPreview(result?.output,limit));
}
function unknownArgumentsNote(op){
 const fields=op.unknown_arguments;
 return fields?.length?'<p class="context-note unknown-arguments">未静态解析的调用参数：'+fields.map(esc).join('、')+'。原始表达式见调用源码。</p>':'';
}
function webContent(op,output,limit){
 const args=op.arguments;
 const queries=Array.isArray(args?.search_query)?args.search_query.map(row=>row?.q):args?.queries;
 let html='';
 if(Array.isArray(queries)&&queries.every(query=>typeof query==='string')){
  html='<h4>搜索参数</h4><ol class="web-queries">'+queries.map(query=>'<li>'+esc(query)+'</li>').join('')+'</ol>';
  const {search_query,queries:nativeQueries,...rest}=args;
  if(Object.keys(rest).length)html+=commandFields(rest);
  if(Array.isArray(search_query)&&search_query.some(row=>row&&Object.keys(row).some(key=>key!=='q')))html+=commandFields({search_query});
 }else if(args!=null)html+=commandFields(args);
 if(!Array.isArray(op.event?.results))return html+(output==null?'':outputPreview(output,limit));
 const rows=op.event.results.slice(0,limit);
 html+='<div class="native-result-heading"><h4>网页结果</h4></div>';
 for(const row of rows){
  if(!row||typeof row!=='object'||(!row.title&&!row.url)){html+='<pre>'+esc(printable(row))+'</pre>';continue}
  const title=esc(row.title||row.url);
  html+='<div class="web-result">'+(/^https?:\/\//i.test(row.url||'')?'<a target="_blank" rel="noopener noreferrer" href="'+esc(row.url)+'">'+title+'</a>':title)+(row.domain?' <small>'+esc(row.domain)+'</small>':'')+(row.snippet?'<p>'+esc(row.snippet)+'</p>':'')+'</div>';
 }
 const remaining=op.event.results.length-rows.length;
 return html+(remaining?`<button data-native-more="${limit+24}">展开余下结果（${remaining} 条）</button>`:'')+(limit>24?'<button data-native-more="24">收起内容</button>':'');
}
function execBlock(value,limit){
 if(value?.type==='audio')return mcpContentBlock(value,limit);
 if(value?.type==='image'){
  const url=value.image_url;
  return typeof url==='string'&&/^data:image\/(?:png|jpeg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(url)
   ?'<img class="exec-image" loading="lazy" alt="工具返回的图片" src="'+esc(url)+'">'
   :'<p class="context-note">记录包含图片，缺少可预览的内嵌内容。</p>';
 }
 return outputPreview(value,limit);
}
function mcpContentBlock(block,limit){
 if(typeof block==='string')return outputPreview(block,limit);
 if(!block||typeof block!=='object')return outputPreview(block,limit);
 if(['text','input_text','output_text'].includes(block.type)&&typeof block.text==='string'){
  return block.text===''?'<small>空文本</small>':outputPreview(block.text,limit);
 }
 if(['image','input_image'].includes(block.type)){
  const mime=block.mimeType??block.mime_type;
  const url=block.image_url??(typeof mime==='string'&&typeof block.data==='string'?'data:'+mime+';base64,'+block.data:null);
  return execBlock({type:'image',image_url:url},limit);
 }
 if(['audio','input_audio'].includes(block.type)){
  return '<p class="mcp-media-note">'+actionIcon('Music')+'音频'+(block.mimeType?' · '+esc(block.mimeType):'')+'</p>';
 }
 if(block.type==='resource'||block.type==='resource_link'){
  const resource=block.type==='resource'?block.resource:block;
  if(typeof resource?.uri==='string'){
   const title=block.type==='resource'?'嵌入资源':'资源链接';
   const body=typeof resource.text==='string'?outputPreview(resource.text,limit):
     typeof resource.blob==='string'?'<small>二进制内容</small>':'';
   return '<div class="mcp-resource"><small>'+actionIcon('Link')+title+'</small><code>'+esc(resource.uri)+'</code>'+body+'</div>';
  }
 }
 return '<details class="tool-json-view"><summary>查看内容块'+(typeof block.type==='string'?' · '+esc(block.type):'')+'</summary>'+outputPreview(block,limit)+'</details>';
}

function mcpBlocks(blocks,limit){
 if(!blocks.length)return '<p class="context-note">返回内容为空列表。</p>';
 return '<div class="mcp-blocks">'+blocks.map(block=>'<div>'+mcpContentBlock(block,limit)+'</div>').join('')+'</div>';
}

function mcpDetail(item,op,raw,limit){
 // Direct MCP, a confirmed exec forwarding, and a native event all share this view.
 const event=op.event?.type?.toLowerCase()==='mcptoolcall'?op.event:null;
 let result=event?event.result:raw;
 if(typeof result==='string'&&/^[\s]*[\[{]/.test(result)){
  try{result=JSON.parse(result)}catch{/* Keep the original text on parse failure. */}
 }
 const status=event?.status;
 const error=event?.error??result?.error;
 const refused=result?.isError===true||result?.is_error===true;
 const failed=status==='failed'||error!=null||refused;
 const labels={completed:'调用完成',failed:'调用失败',inProgress:'上次记录时仍在运行',in_progress:'上次记录时仍在运行'};
 const badges=[labels[status]||status,refused?'服务返回错误':null].filter(Boolean);
 if(error!=null&&!badges.length)badges.push('服务返回错误');
 let duration=event?.durationMs;
 if(duration==null&&Number.isInteger(event?.duration?.secs)&&Number.isInteger(event.duration.nanos)){
  duration=event.duration.secs*1000+Math.floor(event.duration.nanos/1_000_000);
 }
 if(Number.isFinite(duration)&&duration>=0)badges.push(duration+' ms');
 const name=event?event.server+' · '+event.tool:op.tool;
 const output=[];
 if(error!=null)output.push(outputPreview(error,limit));
 if(result==null&&error==null){
  output.push('<p class="context-note">'+(status==='completed'?'调用完成，未记录结果内容。':status==='failed'?'调用失败，未记录错误详情。':op.evidence?.includes('script')?'没有可单独归给此操作的回包。':'未记录返回内容。')+'</p>');
 }else if(result===''){
  output.push('<p class="context-note">返回为空字符串。</p>');
 }else if(Array.isArray(result)){
  output.push(mcpBlocks(result,limit));
 }else if(result!=null&&typeof result==='object'&&('content' in result||'structuredContent' in result||'structured_content' in result)){
  if(Array.isArray(result.content))output.push(mcpBlocks(result.content,limit));
  else if(result.content!=null)output.push(outputPreview(result.content,limit));
  const structured=result.structuredContent??result.structured_content;
  if(structured!=null)output.push('<details class="tool-json-view" open><summary>结构化结果</summary>'+outputPreview(structured,limit)+'</details>');
  if(!output.length)output.push('<p class="context-note">未记录结果内容。</p>');
 }else if(result!=null&&(error==null||Object.keys(result).some(key=>key!=='error'))){
  output.push(outputPreview(result,limit));
 }
 const controls=item.envelope?.script?'':toolJsonMarker();
 const badge=badges.length?'<small class="native-io-status'+(failed?' is-failed':'')+'">'+esc(badges.join(' · '))+'</small>':'';
 const argumentsView=op.arguments!=null&&Object.keys(Object(op.arguments)).length?
  '<details class="tool-json-view"><summary>调用参数</summary>'+outputPreview(op.arguments,limit)+'</details>':'';
 return '<section class="mcp-detail"><header class="native-io-header">'+actionIcon(op.icon)+'<strong>'+esc(name)+'</strong>'+badge+controls+'</header>'+output.join('')+argumentsView+'</section>';
}
function orderedOutputBody(item,limit){
 const blocks=item.output_blocks??(item.output==null?[]:[item.output]);
 const view=item.exec_view||{},consumed=new Set(view.consumed||[]);
 const parts=[];
 for(const [i,block] of blocks.entries()){
  if(consumed.has(i))continue;
  // Header lengths are counted in Python characters; protocol headers are ASCII.
  const offset=view.headers?.[i];
  const value=offset?block.slice(offset):block;
  if(offset&&!value)continue;
  let structured=false;
  if(typeof value==='string'){try{const parsed=JSON.parse(value);structured=parsed!==null&&typeof parsed==='object'&&!Array.isArray(parsed)&&Object.hasOwn(parsed,'output')&&['exit_code','session_id','chunk_id','wall_time_seconds'].some(key=>Object.hasOwn(parsed,key))}catch{}}
  const content=execBlock(value,limit);
  parts.push('<div class="ordered-output-block">'+(structured?'<details class="raw-output-details"><summary>结构化返回 · 查看原始字段</summary>'+content+'</details>':content)+'</div>');
 }
 return parts.length?'<section class="call-output">'+(parts.every(part=>part.includes('class="raw-output-details"'))?'':'<h4>本次调用的输出</h4>')+parts.join('')+'</section>':'';
}
function execOperation(label,content,status='',icon){
 const statusText=status?'<small>'+esc(status)+'</small>':'';
 return '<section class="exec-operation"><div class="exec-row-heading">'+actionIcon(icon)+'<h4>'+actionLabel(label)+'</h4>'+statusText+'</div>'+content+'</section>';
}
function nativeExecRow(item,row,limit){
 const result=item.native_results[row.native],actions=row.actions.map(i=>item.native_actions[i]);
 const edits=actions.length&&actions.every(a=>a.type==='edit');
 let content='';
 if(result.source==='unified_exec_interaction'){
  content=commandFields({command:result.command,process_id:result.process_id});
  if(result.interaction_input==null)content+='<small>本次终端输入未记录。</small>';
  else content+='<details class="native-feedback"><summary>终端输入</summary><pre>'+esc(result.interaction_input||'空输入')+'</pre></details>';
  content+=outputPreview(result.output,limit);
 }else if(row.shell_action){
  content=nativeActionBody({native_actions:[{...row.shell_action,result_index:0}],native_results:[{...result,action_count:1}]},0,limit);
 }else if(edits||actions.length===1&&['read','search','list_files'].includes(actions[0].type)){
  const sharedFeedback=edits&&actions.length>1;
  content=row.actions.map((i,n)=>nativeActionBody(item,i,limit,sharedFeedback,sharedFeedback?row.action_icons?.[n]:null)).join('');
  if(sharedFeedback&&result.output)content+='<h4>本次修改的反馈</h4>'+outputPreview(result.output,limit);
 }else if(result.type==='file_change'){
  content='<p class="context-note">未记录具体文件变更。</p>';
  if(result.output!=null)content+=outputPreview(result.output,limit);
 }else{
  content=shellSource(result.command,'命令源码');
  if(actions.length<=1)content+='<h4>输出</h4>';
  if(actions.length>1){
   const verbs={read:'读取',list_files:'列举',search:'搜索',unknown:'命令'};
   const lines=actions.map((action,n)=>'<div><dt>'+actionIcon(row.action_icons?.[n])+esc(verbs[action.type]||action.type)+'</dt><dd>'+esc(action.cmd||action.path||action.query||'未记录')+'</dd></div>');
   content+='<dl class="native-parameters">'+lines.join('')+'</dl><h4>同一命令的合并输出 · '+actions.length+' 项操作</h4>';
  }
  content+=outputPreview(result.output,limit);
 }
 const status=commandStatus(result).label;
 const timing=commandTiming(result);
 return execOperation(row.label,unknownArgumentsNote(row)+content,status+timing,row.icon);
}
function cellLinks(item){
 const notes=[];
 if(item.cell_id!=null)notes.push('首次返回运行单元 '+item.cell_id);
 if(item.cell_link_note)notes.push(item.cell_link_note);
 const links=[];
 if(item.cell_origin!=null)links.push([item.cell_origin,'查看发起调用']);
 for(const [i,target] of (item.cell_waits||[]).entries()){
  links.push([target,target===item.cell_final?'查看最终返回':'查看等待记录'+(item.cell_waits.length>1?' '+(i+1):'')]);
 }
 return notes.map(note=>'<p class="context-note">'+esc(note)+'</p>').join('')+links.map(([index,label])=>'<button type="button" class="cell-link" data-cell-target="'+Number(index)+'">'+label+'</button>').join('');
}
function execDetail(item,limit){
 const view=item.exec_view;
 const rows=view.rows.map(row=>{
  if(row.native!=null)return nativeExecRow(item,row,limit);
  const op=item.operations[row.op];
  if(!op)return '';
  if(!Object.hasOwn(row,'value')&&row.media_block==null){
   if(['wait','functions.wait'].includes(op.tool))return op.arguments?commandFields(op.arguments):'';
   if(!op.tool)return '';
   return toolDetailBody(item,{dataset:{operation:String(row.op)}},limit);
  }
  const value=row.media_block==null?row.value:item.output_blocks[row.media_block];
  if(op.tool?.startsWith('mcp__'))return mcpDetail(item,op,value,limit);
  const result=typeof value==='string'?commandReturn({output:value}):value;
  let content,status='';
  if(['run','session','search'].includes(op.kind)&&result&&typeof result==='object'&&!Array.isArray(result)){
   if(row.shell_action||op.search){
    const action=row.shell_action||op.search;
    const reads={native_actions:[{...action,result_index:0}],native_results:[{...result,action_count:1}]};
    content=nativeActionBody(reads,0,limit);
   }else content=shellContent(op,result,limit,false);
   if(result.exit_code!=null||result.session_id!=null||result.output_only)status=commandStatus(result).label+commandTiming(result);
  }else{
   content=(op.arguments==null?'':commandFields(typeof op.arguments==='object'?op.arguments:{input:op.arguments}))+execBlock(value,limit);
  }
  return execOperation(row.label,content,status,row.icon);
 }).join('');
 const output=item.standalone_native&&item.native_results?.length?'':orderedOutputBody(item,limit);
 const failed=view.state==='编排失败';
 if(!item.envelope?.script){
  return '<div class="native-io call-detail"><div class="call-actions">'+callName(item)+callButtons(item)+'</div>'+associationNote(item)+cellLinks(item)+rows+output+'</div>';
 }
 const operations='<div class="exec-rows">'+rows+'</div>';
 return '<div class="native-io call-detail exec-detail">'+orchestrationBody(item)+cellLinks(item)
  +(failed?output+operations:operations+output)+'</div>';
}
function recordedImage(data,limit){
 if(typeof data!=='string'||!data)return '';
 let url=data;
 if(!data.startsWith('data:')){
  const signature=[['iVBORw0KGgo','png'],['/9j/','jpeg'],['R0lGOD','gif'],['UklGR','webp']].find(([prefix])=>data.startsWith(prefix));
  if(!signature)return '<p class="context-note">记录包含图像数据，格式不可预览。</p>';
  url='data:image/'+signature[1]+';base64,'+data;
 }
 return execBlock({type:'image',image_url:url},limit);
}
function nativeEventBody(item,op,limit){
 const event=op.event;
 const fields={},family=event.native_family;
 let body='';
 if(family==='web'){
  body=webContent(op,null,limit);
  if(Array.isArray(event.results)&&!event.results.length)body+='<p class="context-note">结果列表为空。</p>';
 }else if(family==='dynamic'){
  fields['工具']=op.tool;
  fields['耗时（毫秒）']=event.durationMs;
  fields['调用状态']=event.status;
  fields['成功回执']=event.success;
  if(Array.isArray(event.content_items)){
   body=mcpBlocks(event.content_items.map(block=>{
    const type={inputText:'input_text',inputImage:'input_image',inputAudio:'input_audio'}[block?.type];
    return type?{...block,type,image_url:block.imageUrl??block.image_url}:block;
   }),limit);
  }else{
   const msg=['inProgress','in_progress'].includes(event.status)?'上次记录时仍在运行。':'未记录返回内容。';
   body='<p class="context-note">'+msg+'</p>';
  }
  if(event.arguments!=null)body+='<details class="tool-json-view"><summary>调用参数</summary>'+outputPreview(event.arguments,limit)+'</details>';
 }else if(family==='sleep'){
  fields['请求等待（毫秒）']=event.durationMs;
 }else if(family==='generation'){
  fields['修订提示词']=event.revisedPrompt;
  fields['透明背景']=event.transparentBackground;
  fields['保存路径']=event.savedPath;
  if(event.failure!=null)body=outputPreview(event.failure,limit);
  else if(event.status==='failed')body='<p class="context-note">未记录具体失败原因。</p>';
  if(event.matched_return_image)body+='<small>图片见本次调用的返回。</small>';
  else body+=recordedImage(event.result,limit);
 }else if(family==='agent_activity'){
  fields['子任务']=event.agentPath;fields['子会话 ID']=event.agentThreadId;
  fields['模型']=event.model;fields['推理力度']=event.reasoningEffort;
  if(event.agentThreadId&&threads.some(t=>t.id===event.agentThreadId)){
   body='<button type="button" class="tool-worker-link" data-thread-link="'+esc(event.agentThreadId)+'">查看子会话</button>';
  }
 }else if(family==='agent_call'){
  fields['发起会话']=event.senderThreadId;
  fields['目标会话']=event.receiverThreadIds;fields['目标代理']=event.receiverAgents;
  fields['任务']=event.prompt;fields['模型']=event.model;fields['推理力度']=event.reasoningEffort;
  if(event.agentsStates!=null)body='<h4>本次返回的代理状态</h4>'+outputPreview(event.agentsStates,limit);
 }
 // A tool return can record different information than the native item,
 // e.g. elapsed time or a wait timeout. Preserve both sources.
 if(op.evidence.includes('direct')&&item.output!=null){
  body+='<details class="tool-json-view"><summary>调用回包</summary>'+outputPreview(item.output,limit)+'</details>';
 }
 return commandFields(fields)+body;
}
function toolDetailBody(item,step,limit=24){
 if(step.dataset.operation==='call'){
  if(item.exec_view?.rows)return execDetail(item,limit);
  if(item.envelope?.script){
   const inputs=item.operations.map((op,operation)=>op.resultRef==null?toolDetailBody(item,{dataset:{operation}},limit):'').join('');
   return '<div class="native-io call-detail exec-detail">'+orchestrationBody(item)+inputs+orderedOutputBody(item,limit)+'</div>';
  }
  const inputs=[];
  for(const [operation,op] of item.operations.entries()){
   if(op.resultRef==null)inputs.push(toolDetailBody(item,{dataset:{operation}},limit));
   else if(item.standalone_native){
    const record=item.native_results[op.resultRef];
    inputs.push(shellSource(record.command,'命令源码')+outputPreview(record.output,limit));
   }
  }
  return '<div class="native-io call-detail"><div class="call-actions">'+callName(item)+callButtons(item)+'</div>'+inputs.join('')+'</div>';
 }
 const op=item.operations?.[Number(step.dataset.operation)];
 if(!op)return '<p class="context-note">操作记录不可用。</p>';
 if(!op.event?.native_family&&(op.tool?.startsWith('mcp__')||op.event?.type?.toLowerCase()==='mcptoolcall')){
  const raw=op.evidence?.includes('direct')&&Object.hasOwn(item,'mcp_output')?item.mcp_output:operationOutput(item,op);
  return mcpDetail(item,op,raw,limit);
 }
 const raw=operationOutput(item,op);
 const shell=op.search||['session','run'].includes(op.kind);
 const result=shell?commandReturn({output:raw}):null;
 const inputOnly=(item.envelope?.script||item.native_results?.length)&&!op.event&&!op.evidence.includes('direct');
 let status=shell&&!inputOnly?commandStatus(result):null;
 if(status)status.label+=commandTiming(result);
 let content;
 if(op.event?.native_family)content=nativeEventBody(item,op,limit);
 else if(op.shell_action&&!inputOnly){
  const record={...result,action_count:1};
  content=nativeActionBody({...item,native_results:[record],native_actions:[{...op.shell_action,result_index:0}]},0,limit);
  if(result==null&&raw!=null)content+=outputPreview(raw,limit);
 }else if(op.search&&!inputOnly){
  const searchItem={...item,native_results:[{...result,action_count:1}],native_actions:[{...op.search,result_index:0}]};
  content=shellSource(op.search.cmd,'命令源码')+nativeSearchBody(searchItem,0,limit);
  if(result?.exit_code===1&&result?.output==='')status={label:'无匹配'};
 }else if(shell)content=shellContent(op,result,limit,inputOnly,raw);
 else if(op.kind==='image')content=(op.arguments?.path?commandFields({path:op.arguments.path}):'<p class="context-note">图片路径未记录为固定值。</p>')+(raw==null?'':outputPreview(raw,limit));
 else if(op.kind==='web')content=webContent(op,raw,limit);
 else if(op.kind==='edit'&&typeof op.arguments==='string'&&op.arguments.startsWith('*** Begin Patch')){
  content='<pre class="patch-diff">'+op.arguments.split('\n').map(line=>'<span class="diff-line '+(line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':'diff-file')+'">'+esc(line)+'\n</span>').join('')+'</pre>'+(inputOnly?'':outputPreview(raw,limit));
 }else{
  const fields={name:op.tool||op.action,text:op.arguments};
  if(raw!=null)fields.output=printable(raw);
  content=toolRecordTable(fields);
 }
 if(typeof op.event?.status==='string'){
  const labels={completed:'已完成',failed:'失败',inProgress:'进行中',in_progress:'进行中'};
  status={label:labels[op.event.status]||op.event.status,failed:op.event.status==='failed'};
 }
 if(op.event?.native_family==='dynamic'&&op.event.success===false)status={label:'失败',failed:true};
 const badge=status?'<span class="native-io-status'+(status.failed?' is-failed':'')+'">'+esc(status.label)+'</span>':'';
 const outer=item.standalone_native||item.envelope?.script||item.native_results?.length?'':orchestrationBody(item);
 const notice=/Warning: truncated output|tokens truncated|output (?:was )?truncated/i.test(item.output||'')?'<p class="tool-notice">原始工具输出已被截断。</p>':'';
 const grouped=item.envelope?.script||item.native_results?.length;
 const title=grouped&&item.operations.length===1?'':actionIcon(op.icon)+'<strong>'+esc(op.action)+'</strong>';
 const controls=(grouped?'':callName(item))+title+badge+(grouped?'':toolJsonMarker());
 const header=controls?'<header class="native-io-header">'+controls+'</header>':'';
 return '<section class="'+(grouped?'call-input':'native-io')+' command-execution">'+header+content+notice+'</section>'+outer;
}

async function hydrateStep(el){
 const id=current,n=seq,index=Number(el.dataset.step),body=el.querySelector('.tool-body');
 if(el.dataset.loaded||el.dataset.loading)return;el.dataset.loading='true';
 try{
  let item=detailCache.get(index);if(!item){const r=await api('/api/thread?id='+encodeURIComponent(id)+'&item='+index);if(n!==seq||!el.isConnected)return;item=r.item;detailCache.set(index,item);while(detailCache.size>12)detailCache.delete(detailCache.keys().next().value)}
  if(n!==seq||!el.isConnected)return;body.innerHTML=toolDetailBody(item,el);el.dataset.loaded='true';
 }catch(e){if(el.isConnected)body.innerHTML='<p>'+esc(e.message)+'</p><button class="retry-tool">重试</button>'}finally{delete el.dataset.loading}
}
$('#messages').addEventListener('click',async event=>{
 const link=event.target.closest('[data-cell-target]');
 if(!link)return;
 const target=Number(link.dataset.cellTarget),n=seq;
 try{
  if(target<data.start){
   const older=await api('/api/thread?'+new URLSearchParams({id:current,start:target,before:data.start}));
   if(n!==seq)return;
   const shown=new Set(data.items.map(item=>item.index));
   data.items=[...older.items.filter(item=>!shown.has(item.index)),...data.items].sort((a,b)=>a.index-b.index);
   data.start=Math.min(data.start,older.start);data.has_more=data.start>0;renderMessages();
  }
  const step=$('#messages').querySelector('[data-step="'+target+'"]');
  if(!step)return;
  for(let el=step;el;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
  await hydrateStep(step);
  if(n===seq&&step.isConnected){step.querySelector('summary')?.focus({preventScroll:true});step.scrollIntoView({block:'center'})}
 }catch(error){if(n===seq)link.textContent='跳转失败 · '+error.message}
});
$('#messages').addEventListener('click',async event=>{
 const button=event.target.closest('.raw-record-button,.inner-results-button');
 if(!button)return;
 event.preventDefault();
 const itemIndex=Number(button.closest('[data-step]').dataset.step);
 const inner=button.matches('.inner-results-button');
 const threadId=current;
 const title=inner?'返回结果':'执行记录 · 完整 JSON';
 const dialog=document.createElement('dialog');
 dialog.className='raw-record-dialog native-code-view';
 dialog.setAttribute('aria-label',title);
 dialog.innerHTML='<header><strong>'+title+'</strong>'+(inner?'':'<button class="copy-json" disabled>复制</button>')+'<button class="close-json">关闭</button></header><pre tabindex="0">正在读取…</pre>';
 document.body.append(dialog);
 const pre=dialog.querySelector('pre'),copy=dialog.querySelector('.copy-json');
 dialog.querySelector('.close-json').onclick=()=>dialog.close();
 dialog.addEventListener('close',()=>dialog.remove(),{once:true});
 dialog.showModal();
 try{
  const item=detailCache.get(itemIndex)??(await api('/api/thread?'+new URLSearchParams({id:current,item:itemIndex}))).item;
  if(inner){
   const list=document.createElement('ol');
   list.className='inner-result-list';
   item.native_results.forEach((record,index)=>list.append(innerResultCard(record,index)));
   pre.replaceWith(list);
   return;
  }
  const parsed=JSON.stringify(item,null,2);
  const tabs=document.createElement('div');
  tabs.className='record-selector';
  tabs.innerHTML='<button aria-pressed="true">解析详情</button><button aria-pressed="false">日志原文</button>';
  pre.before(tabs);
  let selectedText=parsed,rawRecords=null,selection=0;
  function showText(value){
   selectedText=value;
   const code=document.createElement('code');
   code.className='language-json';code.textContent=value;pre.replaceChildren(code);
   // Avoid spending seconds highlighting inline media or very large stack traces.
   if(value.length<=100_000&&globalThis.hljs?.getLanguage('json'))hljs.highlightElement(code);
   copy.disabled=false;copy.textContent='复制';
  }
  showText(parsed);
  tabs.onclick=async event=>{
   const index=[...tabs.children].indexOf(event.target);
   if(index<0)return;
   const request=++selection;
   [...tabs.children].forEach((tab,n)=>tab.setAttribute('aria-pressed',String(n===index)));
   if(index===0){showText(parsed);return}
   pre.textContent='正在读取…';copy.disabled=true;
   try{
    rawRecords??=api('/api/thread?'+new URLSearchParams({id:threadId,item:itemIndex,raw:1}));
    const {records}=await rawRecords;
    if(request!==selection||!dialog.open)return;
    if(records.length)showText(records.join('\n'));
    else pre.textContent='没有可读取的原始记录。';
   }catch(error){rawRecords=null;if(request===selection)pre.textContent=error.message}
  };
  copy.onclick=async()=>{
   try{await navigator.clipboard.writeText(selectedText);copy.textContent='已复制'}
   catch{const range=document.createRange();range.selectNodeContents(pre);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);copy.textContent='已选中，请手动复制'}
  };
 }catch(error){pre.textContent=error.message}
});
$('#messages').addEventListener('error',event=>{
 const img=event.target;
 if(img.matches?.('img.exec-image')){
  const note=document.createElement('small');note.className='mcp-media-note';
  note.textContent='图片数据无法解码。';img.replaceWith(note);
 }
},true);
$('#messages').addEventListener('toggle',e=>{if(e.target.matches('.step[data-step]')&&e.target.open)hydrateStep(e.target)},true);
$('#messages').addEventListener('click',async e=>{
 const button=e.target.closest('.copy-command');if(!button)return;
 const text=JSON.parse(button.dataset.command);
 try{await navigator.clipboard.writeText(text);button.textContent='已复制'}
 catch{
  const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();
  let copied=false;try{copied=document.execCommand('copy')}catch{}area.remove();
  if(copied)button.textContent='已复制';
  else{
   const wrap=button.closest('.command-source-wrap'),details=wrap.querySelector('details');if(details)details.open=true;
   const range=document.createRange();range.selectNodeContents(wrap.querySelector('code'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
   button.textContent='已选中，请手动复制';
  }
 }
});
$('#messages').addEventListener('click',e=>{
 const button=e.target.closest('[data-native-more]');
 if(!button)return;
 const step=button.closest('[data-step]'),index=Number(step.dataset.step);
 const item=detailCache.get(index)||data.items.find(x=>x.index===index&&!x.lazy);
 if(!item)return;
 const main=document.querySelector('main'),top=step.getBoundingClientRect().top;
 const body=step.querySelector('.tool-body');
 const disclosureStates=[...body.querySelectorAll('details')].map(el=>el.open);
 const sourceScroll=body.querySelector('.orchestration-code')?.scrollTop;
 body.innerHTML=toolDetailBody(item,step,Number(button.dataset.nativeMore));
 body.querySelectorAll('details').forEach((el,i)=>{if(i<disclosureStates.length)el.open=disclosureStates[i]});
 if(sourceScroll)body.querySelector('.orchestration-code').scrollTop=sourceScroll;
 main.scrollTop+=step.getBoundingClientRect().top-top;
});
$('#messages').addEventListener('click',e=>{const link=e.target.closest('[data-thread-link]');if(link)openAgentPreview(link.dataset.threadLink,link);if(e.target.closest('#load-older'))loadOlder();if(e.target.closest('.retry-tool'))hydrateStep(e.target.closest('.step'))});
function captureReading(){
 const main=document.querySelector('main'),top=main.querySelector('header').getBoundingClientRect().bottom;
 const anchor=[...$('#messages').querySelectorAll('[data-anchor]')].find(el=>el.getBoundingClientRect().bottom>top);
 return {anchor:anchor?.dataset.anchor,offset:anchor?.getBoundingClientRect().top,scroll:main.scrollTop,open:[...$('#messages').querySelectorAll('details[open]')].map(el=>el.dataset.key||el.closest('[data-anchor]')?.dataset.anchor).filter(Boolean)};
}
function restoreReading(snapshot){
 for(const key of snapshot.open){const el=$('#messages').querySelector('[data-key="'+key+'"]')||$('#messages').querySelector('[data-anchor="'+key+'"] details');if(el)el.open=true}
 const main=document.querySelector('main'),anchor=snapshot.anchor&&$('#messages').querySelector('[data-anchor="'+snapshot.anchor+'"]');
 main.scrollTop=anchor?main.scrollTop+anchor.getBoundingClientRect().top-snapshot.offset:snapshot.scroll;
}
async function loadOlder(){
 if(loadingOlder||agentPreview.open||!data?.has_more)return;loadingOlder=true;const id=current,n=seq;const button=$('#load-older');if(button){button.disabled=true;button.textContent='正在读取…'}
 try{const older=await api('/api/thread?id='+encodeURIComponent(id)+'&before='+data.start);if(n!==seq)return;const snap=captureReading();const shown=new Set(data.items.map(item=>item.index));data.items=[...older.items.filter(item=>!shown.has(item.index)),...data.items].sort((a,b)=>a.index-b.index);data.start=Math.min(data.start,older.start);data.has_more=data.start>0;renderMessages();restoreReading(snap)}catch(e){$('#end').textContent=e.message}finally{loadingOlder=false;const button=$('#load-older');if(button){button.disabled=false;button.textContent='加载更早的对话'}}
}
async function searchWholeConversation(){
 clearTimeout(searchTimer);searchTimer=null;const request=++searchRequest,n=seq,query=$('#insearch').value;
 if(!query){findInConversation();return}$('#find-status').textContent='正在查找…';
 try{const result=await api('/api/thread?id='+encodeURIComponent(current)+'&q='+encodeURIComponent(query));if(n!==seq||request!==searchRequest||query!==$('#insearch').value)return;data={...data,...result};renderMessages();findInConversation()}catch(e){if(n===seq)$('#find-status').textContent=e.message}
}
// Enter waits for server-backed search too, so unloaded history is never omitted.
$('#insearch').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(searchTimer)searchWholeConversation();else jumpToHit(e.shiftKey?-1:1)}if(e.key==='Escape'){$('#insearch').value='';searchRequest++;findInConversation()}};
$('#find-prev').onclick=()=>searchTimer?searchWholeConversation():jumpToHit(-1);
$('#find-next').onclick=()=>searchTimer?searchWholeConversation():jumpToHit(1);
function nearBottom(){const main=document.querySelector('main');return main.scrollHeight-main.scrollTop-main.clientHeight<150}
function syncNewMessageNotice(){newMessages.hidden=!pendingLive||nearBottom()}
async function updateLive(forceBottom=false){
 if(updatingLive||!data)return;updatingLive=true;const n=seq,id=current,start=data.start,request=searchRequest,follow=forceBottom||nearBottom();
 try{
  const fresh=await api('/api/thread?id='+encodeURIComponent(id)+'&start='+start);if(n!==seq||data.start!==start||searchRequest!==request)return;
  if(agentPreview.open){pendingLive=true;syncNewMessageNotice();return}
  const snap=captureReading();detailCache.clear();data={...data,...fresh};renderMessages();restoreReading(snap);
  if(follow){const main=document.querySelector('main');main.scrollTop=main.scrollHeight}
  pendingLive=false;newMessages.hidden=true;
 }catch(e){if(n===seq){pendingLive=true;syncNewMessageNotice();$('#end').textContent='更新失败，稍后会重试：'+e.message}}finally{updatingLive=false}
}
newMessages.onclick=()=>{searchRequest++;$('#insearch').value='';searchHits=[];searchIndex=-1;updateFindStatus();updateLive(true)};
let polling=false;
async function pollChanges(){
 if(polling||document.hidden)return;polling=true;const n=seq;
 try{
  const rev=await api('/api/revision?id='+encodeURIComponent(current||''));if(n!==seq)return;
  if(!revisionState||rev.list!==revisionState.list){
   const latest=await api('/api/threads');if(n!==seq)return;
   threads=latest;
  }
  if(lastListSignature!==JSON.stringify(threads)&&$('#source-menu').hidden&&!document.querySelector('aside').contains(document.activeElement)){const scroll=$('#list').scrollTop;renderList();$('#list').scrollTop=scroll}
  if(data&&(pendingLive||!revisionState||rev.thread!==revisionState.thread)){
   if(!agentPreview.open&&nearBottom()&&!$('#insearch').value&&!$('#messages').querySelector('details[open]'))await updateLive();
   else{pendingLive=true;syncNewMessageNotice()}
  }
  if(current&&!data&&!threadLoading){await openThread(current);return}
  revisionState=rev;
 }catch{}finally{polling=false}
}
if(!demoMode){setInterval(pollChanges,3000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollChanges()})}
// Late image sizing should follow the bottom only while the user is following it.
let followImages=true;document.querySelector('main').addEventListener('scroll',()=>{followImages=nearBottom();syncNewMessageNotice();if(document.querySelector('main').scrollTop<120&&!$('#insearch').value)loadOlder();if(pendingLive&&!agentPreview.open&&followImages&&!$('#insearch').value&&!$('#messages').querySelector('details[open]'))updateLive()},{passive:true});
$('#messages').addEventListener('load',e=>{if(e.target.tagName==='IMG'&&followImages){const main=document.querySelector('main');main.scrollTop=main.scrollHeight}},true);

// Preview associated sessions without changing the current transcript or URL.
const agentPreview=document.createElement('dialog');
agentPreview.className='agent-preview';agentPreview.setAttribute('aria-labelledby','agent-preview-title');
agentPreview.innerHTML='<div class="agent-preview-head"><div><span id="agent-preview-kind">关联会话</span><h2 id="agent-preview-title">会话预览</h2></div><button class="agent-preview-close" aria-label="关闭会话预览">'+uiIcon('X')+'</button></div><div class="agent-preview-body" aria-live="polite"></div><div class="agent-preview-footer"><span>关闭预览即可继续当前阅读</span><button class="agent-preview-open">打开完整会话 '+uiIcon('ArrowRight')+'</button></div>';
document.body.append(agentPreview);
let previewRequest=0,previewTarget=null,previewOpener=null;
function previewContent(d,id){
 const t=d.thread,latest=d.turns?.at(-1),messages=d.items.filter(x=>x.kind==='message'&&!isContext(x)&&['user','assistant'].includes(x.role));
 const lastContext=[...d.items].reverse().find(x=>x.turn_context)?.turn_context||{};
 const status=latest?.status||threads.find(x=>x.id===id)?.status;
 const statusName={completed:'已完成',inProgress:'运行中',failed:'失败',interrupted:'已中断'}[status]||status||'未记录';
 const fields=[['状态',statusName],['最近模型',lastContext.model||t.model],['最近更新',t.updated_at?date(t.updated_at):null],['目录',t.cwd]];
 const compact=fields.filter(([k,v])=>k!=='目录'&&v!=null&&v!=='').map(([k,v])=>'<span title="'+esc(k)+'">'+esc(v)+'</span>').join('');
 const overview='<details class="agent-preview-info"><summary><span class="agent-preview-facts">'+compact+'</span><span class="agent-preview-info-label">详情</span>'+uiIcon('ChevronDown','disclosure')+'</summary><dl class="agent-preview-meta">'+fields.filter(([,v])=>v!=null&&v!=='').map(([label,value])=>'<div'+(label==='目录'?' class="wide"':'')+'><dt>'+label+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl></details>';
 const excerpts=messages.slice(-6).map(x=>{
  const user=x.role==='user',presentation=user?userPresentation(x.text,id):{body:x.text,attachments:''};
  const raw=String(presentation.body||''),short=raw.length>2400;
  return '<section class="agent-preview-message"><div class="agent-preview-by"><span>'+(user?'用户请求':'Codex')+'</span>'+(x.time?'<time>'+esc(date(x.time))+'</time>':'')+'</div>'+presentation.attachments+'<div class="content">'+(presentation.html??md(short?raw.slice(0,2400)+'\n\n…':raw,id))+'</div>'+(short?'<p class="context-note">内容较长，打开完整会话可继续查看。</p>':'')+'</section>';
 }).join('');
 const tools=d.items.filter(x=>x.kind==='tool').slice(-4);
 const actions=tools.length?'<details class="agent-preview-actions"><summary>最近执行</summary>'+tools.flatMap(x=>timelineActions(x).map(op=>'<div title="'+esc(op.label||op.summary)+'">'+actionIcon(op.icon)+'<span>'+esc(op.label||op.summary)+'</span></div>')).join('')+'</details>':'';
 return overview+(excerpts||'<p class="context-note">最近记录中暂无可展示的对话。</p>')+actions+(d.has_more||messages.length>6?'<p class="context-note">以上为最近消息摘录，打开完整会话可浏览全部记录。</p>':'');
}
async function openAgentPreview(id,opener){
 const request=++previewRequest;previewTarget=id;previewOpener=opener;
 const t=threads.find(t=>t.id===id),parent=data?.relations?.parent?.id===id;
 agentPreview.querySelector('#agent-preview-kind').textContent=parent?'主会话概况':'子代理概况';
 agentPreview.querySelector('h2').textContent=t?threadTitle(t):'会话预览';
 const body=agentPreview.querySelector('.agent-preview-body');body.innerHTML='<p class="context-note">正在读取会话概况…</p>';body.setAttribute('aria-busy','true');
 if(!agentPreview.open)agentPreview.showModal();body.scrollTop=0;
 try{const d=await api('/api/thread?id='+encodeURIComponent(id));if(request!==previewRequest||!agentPreview.open)return;agentPreview.querySelector('h2').textContent=threadTitle(d.thread);body.innerHTML=previewContent(d,id);body.scrollTop=0}
 catch(e){if(request===previewRequest&&agentPreview.open)body.innerHTML='<p class="context-note">暂时无法读取预览：'+esc(e.message)+'</p><button class="agent-preview-retry">重试</button>'}
 finally{if(request===previewRequest)body.removeAttribute('aria-busy')}
}
agentPreview.querySelector('.agent-preview-close').onclick=()=>agentPreview.close();
agentPreview.querySelector('.agent-preview-open').onclick=()=>{const id=previewTarget;agentPreview.close();if(id)openThread(id)};
agentPreview.addEventListener('click',e=>{if(e.target===agentPreview){const r=agentPreview.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)agentPreview.close()}if(e.target.closest('.agent-preview-retry'))openAgentPreview(previewTarget,previewOpener)});
agentPreview.addEventListener('click',openMessageImage);
agentPreview.addEventListener('close',()=>{previewRequest++;previewTarget=null;if(previewOpener?.isConnected)previewOpener.focus({preventScroll:true});previewOpener=null});
