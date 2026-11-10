import React from 'react';
let markdown;
function parser(){
 if(markdown)return markdown;
 markdown=window.markdownit({html:false,linkify:true});
 // Descriptions are untrusted log data. Images must not cause network requests.
 markdown.renderer.rules.image=(tokens,index)=>markdown.utils.escapeHtml(tokens[index].content||'图片');
 const link=markdown.renderer.rules.link_open||((tokens,index,options,env,self)=>self.renderToken(tokens,index,options));
 markdown.renderer.rules.link_open=(tokens,index,options,env,self)=>{tokens[index].attrSet('target','_blank');tokens[index].attrSet('rel','noopener noreferrer');return link(tokens,index,options,env,self)};
 return markdown;
}
// Keep the official viewer, but reuse our HTML-disabled Markdown renderer.
export function MarkdownViewer({markdown:source='',parseOptions,style,className,...props}){
 const Paragraph=parseOptions?.components?.p;
 if(Paragraph)return React.createElement(Paragraph,null,React.createElement('span',{dangerouslySetInnerHTML:{__html:parser().renderInline(String(source))}}));
 return React.createElement('div',{style,className,...props,dangerouslySetInnerHTML:{__html:parser().render(String(source))}});
}
