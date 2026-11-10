const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
const base=(process.env.SCHEMA_TEST_URL||'http://127.0.0.1:4318').replace(/\/$/,'');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.SCHEMA_TEST_BROWSER,headless:true});
 try{for(const width of [1280,390]){
  const page=await browser.newPage({viewport:{width,height:820},hasTouch:width===390});page.setDefaultTimeout(12000);
  const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
  await page.goto(base+'/demo');await page.locator('#list .session').first().waitFor({state:'attached'});
  await page.evaluate(()=>{
   const schema={type:'object',properties:{query:{type:'string',description:'Search **query**\n\nMore details\n\n![image](https://example.invalid/image.png) <img src=x onerror="window.schemaXss=1">',minLength:1},options:{type:'object',description:'Search options',properties:{limit:{type:'integer',default:0,minimum:0},enabled:{type:'boolean',default:false}},required:['limit']},count:{$ref:'#/definitions/count'},choice:{oneOf:[{type:'string',title:'Text'},{type:'integer',title:'Number'}]},tags:{type:'array',items:{type:'string'}}},required:['query'],definitions:{count:{type:'integer',description:'Resolved reference',minimum:0}}};
   contextPanel.querySelector('.context-panel-body').innerHTML=contextTools([{type:'function',name:'synthetic_lookup',description:'Synthetic tool description',parameters:schema}]);contextPanel.showModal();
  });
  const tool=page.locator('.tool-definition');await tool.focus();await tool.press('Enter');
  assert.equal(await page.locator('.tool-definition-popover .tool-schema-section').isVisible(),false);
  const originalDefinition=JSON.parse(await tool.getAttribute('data-tool-json'));
  const checkOriginalJson=async parent=>{
   await parent.getByRole('button',{name:'查看工具定义的原始 JSON',exact:true}).click();
   const dialog=page.getByRole('dialog',{name:'工具定义 · 原始 JSON',exact:true});await dialog.waitFor();
   assert.deepEqual(JSON.parse(await dialog.locator('pre').innerText()),originalDefinition);
   assert.equal(await dialog.locator('script').count(),0);
   await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
   assert.ok(await parent.isVisible());
  };
  await checkOriginalJson(page.locator('.tool-definition-popover'));

  assert.ok(!requests.some(u=>u.includes('/vendor/schema-viewer.')));
  await page.getByRole('button',{name:'全屏显示工具详情',exact:true}).click();
  const host=page.locator('.tool-definition-fullscreen .schema-viewer-host');await host.locator('.JsonSchemaViewer').waitFor();
  await host.getByText('Resolved reference',{exact:true}).waitFor();
  await checkOriginalJson(page.locator('.tool-definition-fullscreen'));

  await host.getByText('Show all...', {exact:true}).click();await host.getByText('More details',{exact:false}).waitFor();await host.getByText('options',{exact:true}).click();assert.equal(await host.getByText('limit',{exact:true}).isVisible(),false);await host.getByText('options',{exact:true}).click();await host.getByText('limit',{exact:true}).waitFor();await host.locator('select').selectOption('1');assert.equal(await host.locator('select').inputValue(),'1');

  assert.equal(await page.evaluate(()=>window.schemaXss),undefined);
  assert.equal(await host.locator('img,iframe,script').count(),0);
  assert.ok(requests.every(u=>u.startsWith(base+'/')));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.evaluate(()=>document.body.classList.add('dark'));await page.waitForTimeout(100);
  await page.getByRole('button',{name:'还原工具详情浮层'}).click();await page.locator('.tool-definition-fullscreen').waitFor({state:'hidden'});await page.locator('.tool-definition-popover').waitFor({state:'visible'});
  assert.equal(await host.locator('.JsonSchemaViewer').count(),0);
  await page.getByRole('button',{name:'全屏显示工具详情',exact:true}).click();await host.locator('.JsonSchemaViewer').waitFor();
  await page.keyboard.press('Escape');await page.locator('.tool-definition-fullscreen').waitFor({state:'hidden'});
  assert.equal(await page.locator('.context-panel').evaluate(e=>e.open),true);
  await page.locator('.tool-definition-popover').waitFor({state:'visible'});
  await page.evaluate(()=>{hideToolDefinition();contextPanel.querySelector('.context-panel-body').innerHTML=contextTools([{name:'root_union',parameters:{anyOf:[{type:'object',title:'First',properties:{first:{type:'string'}}},{type:'object',title:'Second',properties:{second:{type:'integer'}}}]}}])});
  await tool.focus();await tool.press('Enter');await page.getByRole('button',{name:'全屏显示工具详情',exact:true}).click();
  await host.getByText('first',{exact:true}).waitFor();await host.getByRole('combobox',{name:'Pick a type'}).selectOption('1');await host.getByText('second',{exact:true}).waitFor();
  await page.getByRole('button',{name:'还原工具详情浮层'}).click();await page.locator('.tool-definition-fullscreen').waitFor({state:'hidden'});
  await page.waitForTimeout(100);assert.deepEqual(errors,[]);
  console.log(width,'OK');await page.close();
 }}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
