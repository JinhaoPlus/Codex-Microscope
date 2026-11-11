// Capture the real UI using reconstructed sessions built from repository evidence.
// Every /api/** request is fulfilled locally; never read the user's live sessions.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('./schema-viewer/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const base = (process.env.README_CAPTURE_URL || 'http://127.0.0.1:4318').replace(/\/$/, '');
const output = path.join(root, 'docs/images');
const fixtures = JSON.parse(execFileSync(process.env.README_CAPTURE_PYTHON || 'python3',
 [path.join(__dirname, 'readme_fixtures.py')], {cwd: root, encoding: 'utf8'}));

(async () => {
 const browser = await chromium.launch({headless: true, executablePath: process.env.README_CAPTURE_BROWSER});
 try {
  for (const locale of ['en', 'zh-CN']) {
   const fixture = fixtures[locale];
   assert.ok(fixture && Array.isArray(fixture.threads) && fixture.threads.length);
   assert.ok(fixture.page?.thread?.id && Array.isArray(fixture.hero_steps) && fixture.hero_steps.length);
   const page = await browser.newPage({viewport: {width: 1440, height: 960}, locale, deviceScaleFactor: 1});
   const imageFile = name => path.join(output, name + '-' + locale + '.png');
   const errors = [], unexpectedApi = [], apiRequests = [], failedResources = [];
   page.on('requestfailed', request => failedResources.push({url: request.url(), failure: request.failure()?.errorText}));
   page.on('response', response => {if(!response.ok())failedResources.push({url: response.url(), status: response.status()})});
   page.on('pageerror', error => errors.push(error.message));
   await page.addInitScript(locale => localStorage.setItem('ui-locale', locale), locale);
   await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    apiRequests.push(url.pathname);
    let value;
    if (url.pathname === '/api/threads') value = fixture.threads;
    else if (url.pathname === '/api/revision') value = {list: 'readme-reconstruction', thread: 'readme-reconstruction'};
    else if (url.pathname === '/api/thread') {
     const item = url.searchParams.get('item');
     if (url.searchParams.get('view') === 'context') value = Array.isArray(fixture.context) ? {items: fixture.context} : fixture.context;
     else if (item != null) value = (url.searchParams.get('raw') === '1' ? fixture.raw : fixture.details)?.[item];
     else value = fixture.page;
    } else if (url.pathname === '/api/usage') value = {type: 'result', data: fixture.usage};
    if (value == null) {
     unexpectedApi.push(url.pathname + url.search);
     await route.fulfill({status: 404, contentType: 'application/json', body: JSON.stringify({error: 'No README fixture for this API request'})});
     return;
    }
    await route.fulfill({contentType: url.pathname === '/api/usage' ? 'application/x-ndjson' : 'application/json', body: JSON.stringify(value) + '\n'});
   });
   await page.goto(base + '/#' + encodeURIComponent(fixture.page.thread.id));
   await page.evaluate(() => window.__usageStarted);
   assert.ok(await page.locator('.message.user').count());
   await page.evaluate(() => {
    followImages = false;
    document.querySelectorAll('#messages details.activity-group').forEach(group => { group.open = true; });
    document.querySelectorAll('#messages details.step').forEach(step => { step.open = false; });
   });
   for (const index of fixture.hero_steps) {
    const steps = page.locator('#messages details.step[data-step="' + index + '"]');
    assert.ok(await steps.count(), 'Missing hero step ' + index);
    for (const step of await steps.all()) {
     await step.locator(':scope > summary').click();
     await step.waitFor({state: 'visible'});
     await page.waitForFunction(element => element.dataset.loaded === 'true', await step.elementHandle());
    }
   }
   assert.deepEqual(await page.locator('#messages details.step[open]').evaluateAll(steps => [...new Set(steps.map(step => Number(step.dataset.step)))].sort((a,b) => a-b)), [...new Set(fixture.hero_steps)].sort((a,b) => a-b));
   // Collapse only the optional orchestration source through its ordinary control;
   // the native diff and actual test output remain fully available below.
   for(const index of fixture.hero_steps){
    const source=page.locator('#messages details.step[data-step="'+index+'"] details.command-orchestration[open] > summary');
    for(const summary of await source.all())await summary.click();
   }
   await page.waitForFunction(() => [...document.querySelectorAll('.message-image,.exec-image')].every(image => image.complete));
   // The first diff and final verification output are the focus of the hero.
   // Scroll the real transcript; do not replace or shorten its source/output.
   await page.setViewportSize({width: 1440, height: 1440});
   await page.evaluate(index => {
    const main=document.querySelector('main'),step=document.querySelector('#messages details.step[data-step="'+index+'"]');
    const header=main.querySelector('header').getBoundingClientRect();
    main.scrollTop+=step.getBoundingClientRect().top-header.bottom-12;
   },fixture.hero_steps[0]);
   await page.waitForTimeout(100);
   fs.mkdirSync(output, {recursive: true});
   const verificationStep=page.locator('#messages details.step[data-step="'+fixture.hero_steps.at(-1)+'"]');
   const verificationOutput=verificationStep.getByText(/Ran \d+ tests? in/).last();
   assert.equal(await verificationOutput.count(),1,'The actual test result must be present');
   await page.screenshot({path: imageFile('tool-execution')});
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:960});
    const numbers=await page.locator('.native-diff-row .native-line-number').evaluateAll(nodes=>nodes.filter(node=>/^\d{3,}$/.test(node.textContent.trim())).map(node=>{
     const style=getComputedStyle(node),box=node.getBoundingClientRect();
     return {value:node.textContent.trim(),nowrap:style.whiteSpace==='nowrap',fits:node.scrollWidth<=node.clientWidth,height:box.height,lineHeight:parseFloat(style.lineHeight)};
    }));
    assert.ok(numbers.length,'Expected real three-digit hunk line numbers');
    assert.ok(numbers.every(number=>number.nowrap&&number.fits&&number.height<=number.lineHeight*1.1),'Diff line numbers must remain on one line at '+width+'px: '+JSON.stringify(numbers));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   }
   await page.setViewportSize({width: 1440, height: 960});

   await page.evaluate(async () => {
    await openUsage({scope: 'all'});
    const body = usageDialog.querySelector('.usage-body'), heatmap = body.querySelector('.usage-heatmap');
    body.scrollTop = heatmap.offsetTop - body.offsetTop - 16;
   });
   assert.equal(await page.locator('.usage-overview polygon').count(), 1);
   await page.screenshot({path: imageFile('usage-and-cost')});
   await page.locator('#usage-dialog .usage-close').click();

   // Use the same context endpoint and rendering path as the ordinary app.
   await page.evaluate(() => openContextPanel());
   await page.locator('.context-tools .tool-definition').first().waitFor();
   await page.screenshot({path: imageFile('context-inspection')});
   const tool = page.locator('.tool-definition').filter({has: page.locator('span', {hasText: /^exec_command$/})}).first();
   assert.equal(await tool.count(), 1, 'Real exec_command definition is required');
   await tool.scrollIntoViewIfNeeded();
   await tool.focus();
   await tool.press('Enter');
   await page.getByRole('button', {name: await page.evaluate(() => t('context.toolDefExpandAria')), exact: true}).click();
   const host = page.locator('.tool-definition-fullscreen .schema-viewer-host');
   await host.locator('.JsonSchemaViewer').waitFor();
   await page.waitForFunction(() => !!document.querySelector('.tool-definition-fullscreen .schema-viewer-host')?.shadowRoot?.querySelector('link')?.sheet);
   await page.waitForTimeout(100);
   // Collapse the real nested permission object through the viewer's own UI.
   // This keeps cmd, sandbox permissions, tty and workdir in the same frame.
   const permissions=host.locator('[data-test="property-name-additional_permissions"]');
   await permissions.click();
   await host.locator('[data-test="property-name-network"]').waitFor({state:'hidden'});
   await page.setViewportSize({width:1440,height:1200});
   await page.evaluate(() => {document.querySelector('.tool-definition-fullscreen .tool-definition-body').scrollTop=0});
   assert.ok(await host.locator('[data-test="property-name-cmd"]').isVisible());
   assert.ok(await host.locator('[data-test="property-name-workdir"]').isVisible());
   for(const name of ['cmd','sandbox_permissions','tty','workdir']){
    const box=await host.locator('[data-test="property-name-'+name+'"]').boundingBox();
    assert.ok(box&&box.y>=0&&box.y+box.height<=1200,name+' must appear in the Schema screenshot');
   }
   await page.screenshot({path: imageFile('tool-schema')});
   assert.deepEqual(failedResources, []);
   assert.deepEqual(unexpectedApi, []);
   assert.ok(!apiRequests.some(name => name.startsWith('/api/demo/')));
   assert.deepEqual(errors, []);
   console.log(locale + ': captured four README images from repository-backed reconstructed sessions.');
   await page.close();
  }
 } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
