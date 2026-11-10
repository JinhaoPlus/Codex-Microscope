import React from 'react';
// Preserve the official renderer and layout. Use native controls for the two
// combiner pickers: Mosaic's old focus scopes retain shadow-root Event targets
// across animation frames, where those targets become null after dispatch.
export * from './node_modules/@stoplight/mosaic/core.esm.js';

const schemaTypeAria=()=>(typeof globalThis!=='undefined'&&globalThis.t?globalThis.t('accessibility.schemaSelectType'):'Select type');

export const Select=React.forwardRef(function Select({options=[],value,defaultValue,onChange,triggerTextPrefix='',isDisabled,...props},ref){
 return React.createElement('select',{
  ref,className:'schema-native-select','aria-label':props['aria-label']||schemaTypeAria(),
  value:value??defaultValue,disabled:isDisabled,
  onChange:event=>{const index=Number(event.target.value);onChange?.(options[index]?.value)},
 },options.map((option,index)=>React.createElement('option',{key:index,value:index,disabled:option.isDisabled},triggerTextPrefix+(option.label??option.title??String(option.value)))));
});

export function Menu({items=[],'aria-label':label}){
 const [selected,setSelected]=React.useState(0);
 return React.createElement('select',{
  className:'schema-native-select','aria-label':label||schemaTypeAria(),value:selected,
  onChange:event=>{const index=Number(event.target.value);setSelected(index);items[index]?.onPress?.()},
 },items.map((item,index)=>React.createElement('option',{key:item.id??index,value:index},item.title)));
}
