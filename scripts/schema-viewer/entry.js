import React from 'react';
import {createRoot} from 'react-dom/client';
import {JsonSchemaViewer} from '@stoplight/json-schema-viewer';
import {config,dom} from '@fortawesome/fontawesome-svg-core';

// Font Awesome's global stylesheet cannot reach this isolated viewer.
config.autoAddCss=false;

export function mount(host,schema){
 const shadow=host.shadowRoot||host.attachShadow({mode:'open'});
 host.replaceChildren();shadow.replaceChildren();
 const stylesheet=document.createElement('link');stylesheet.rel='stylesheet';stylesheet.href='/vendor/schema-viewer.css';
 const icons=document.createElement('style');icons.textContent=dom.css();
 const shell=document.createElement('div');shell.className='schema-shell';
 const syncTheme=()=>{shell.dataset.theme=document.body.classList.contains('dark')?'dark':'light'};
 syncTheme();
 const observer=new MutationObserver(syncTheme);observer.observe(document.body,{attributes:true,attributeFilter:['class']});
 shadow.append(stylesheet,icons,shell);
 const root=createRoot(shell);
 if(typeof schema==='boolean'||schema&&typeof schema==='object'&&!Array.isArray(schema)&&!Object.keys(schema).length){
  root.render(React.createElement('p',null,schema===false?'此 Schema 不允许任何值。':'此 Schema 允许任意值。'));
 }else{
  root.render(React.createElement(JsonSchemaViewer,{schema,defaultExpandedDepth:2,maxRefDepth:4,disableCrumbs:true,emptyText:'没有可展示的参数，请查看原始 Schema。'}));
 }
 return ()=>{observer.disconnect();root.unmount();shadow.replaceChildren()};
}
