// Optional browser regression checks. API responses are synthetic; live sessions are never read.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const {chromium} = require('./schema-viewer/node_modules/playwright-core');
const base = process.env.I18N_TEST_URL || 'http://localhost:4318';
const browserPath = process.env.I18N_TEST_BROWSER;
const root = require('node:path').resolve(__dirname, '..');
const reports = JSON.parse(execFileSync(process.env.I18N_TEST_PYTHON || 'python3', ['-c', `
import json,tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pricing,token_usage
with tempfile.TemporaryDirectory() as directory, patch.object(pricing,'LOCAL',Path(directory)/'prices'):
 home=Path(directory);path=home/'synthetic';path.write_text('synthetic')
 pricing.configure({'basis':'api','source':'litellm'})
 pricing.save_json(pricing.LOCAL/'litellm.json',{'data':{'gpt-example':{'litellm_provider':'openai','input_cost_per_token':.000002,'cache_read_input_token_cost':.000001,'output_cost_per_token':.00001}}})
 events=[]
 for days in range(35):
  stamp=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
  events.append({'time':stamp,'turn':'turn-'+str(days),'turn_number':35-days,'summary':'Synthetic request','cwd':'/demo','model':'gpt-example','tier':'standard','request_input':100,'tokens':{'input':90,'cached':10,'cache_write':0,'output':15,'reasoning':5}})
 rows=[{'id':'synthetic','title':'Synthetic session','cwd':'/demo','rollout_path':str(path)}]
 query={'scope':['all'],'dimension':['directory'],'timezone':['UTC']}
 with patch.object(token_usage,'events_for',return_value=events):
  full=token_usage.report(rows,home,query)
  hourly=token_usage.report(rows,home,{**query,'day':[full['calendar_today']]})
 print(json.dumps({'full':full,'hourly':hourly,'pricing':pricing.status()}))
`], {cwd: root, encoding: 'utf8'}));
const rawText = 'Original user text / 用户原文 <script>not executable</script>';
const thread = {id: 'synthetic', title: 'Synthetic session', source: 'cli', category: 'cli', cwd: '/demo', updated_at: 1};
const detail = {thread, items: [{kind: 'message', role: 'user', text: rawText, index: 0}], turns: [], relations: {children: []}, has_more: false, skipped: 0, start: 0};

(async () => {
 const browser = await chromium.launch({headless: true, ...(browserPath ? {executablePath: browserPath} : {})});
 try {
  for (const locale of ['zh-CN', 'en']) for (const width of [1280, 390]) {
   const page = await browser.newPage({viewport: {width, height: 850}, locale});
   const errors = [];
   page.on('pageerror', error => errors.push(error.message));
   await page.addInitScript(locale => {if(localStorage.getItem('ui-locale')==null)localStorage.setItem('ui-locale', locale)}, locale);
   await page.route('**/locales/*.json', async route => {
    await new Promise(resolve => setTimeout(resolve, 75));
    await route.continue();
   });
   await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const body = url.pathname === '/api/threads' ? [thread]
     : url.pathname === '/api/revision' ? {list: 'synthetic', thread: 'synthetic'}
     : url.pathname === '/api/thread' ? detail
     : url.pathname === '/api/usage' ? {type: 'result', data: url.searchParams.has('day') ? reports.hourly : reports.full}
     : url.pathname === '/api/pricing' ? reports.pricing
     : {};
    await route.fulfill({contentType: url.pathname === '/api/usage' ? 'application/x-ndjson' : 'application/json', body: JSON.stringify(body) + '\n'});
   });
   await page.goto(base + '/#synthetic');
   await page.evaluate(() => window.__usageStarted);
   assert.equal(await page.locator('#usage-dialog').count(), 1);
   assert.equal(await page.evaluate(() => heatMetrics.length), 7);
   assert.equal(await page.locator('.message.user .content').innerText(), rawText);
   assert.equal(await page.locator('.message.user script').count(), 0);
   assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('*')].flatMap(element => [...element.attributes].map(attribute => attribute.value)).filter(value => value.includes('[missing:'))), []);
   assert.equal(await page.locator('.brand-icon').getAttribute('alt'), 'Codex Microscope');
   assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
   await page.evaluate(() => openAgentPreview('synthetic', null));
   assert.equal(await page.locator('.agent-preview').evaluate(element => element.open), true);
   assert.equal(await page.locator('.agent-preview .content').innerText(), rawText);
   await page.locator('.agent-preview-close').click();
   assert.equal(await page.locator('.agent-preview').evaluate(element => element.open), false);
   await page.evaluate(() => openAgentPreview('synthetic', null));
   await page.locator('.agent-preview-open').click();
   assert.equal(await page.locator('.agent-preview').evaluate(element => element.open), false);
   await page.evaluate(() => openUsage({scope: 'all'}));
   assert.equal(await page.locator('#usage-dialog .usage-heatmap').count(), 1);
   assert.equal(await page.locator('#usage-dialog [data-heat-metric]').count(), 7);
   assert.equal(await page.locator('#usage-dialog .usage-chart-scroll svg').count(), 1);
   assert.equal(await page.locator('#usage-dialog [role="slider"]').count(), 2);
   const dateAria = await page.locator('#usage-dialog [role="slider"]').first().getAttribute('aria-valuetext');
   assert.ok(dateAria && !dateAria.includes('[missing:'));
   assert.equal(await page.locator('#usage-dialog .usage-table tbody tr').count(), 1);
   assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
   await page.locator('#usage-dialog .usage-header').getByRole('button', {name: await page.evaluate(() => t('pricing.settingsTitle')), exact: true}).click();
   await page.locator('#price-settings-dialog .price-cache').first().waitFor();
   assert.equal(await page.locator('#price-settings-dialog').evaluate(element => element.open), true);
   await page.locator('#price-settings-dialog .price-close').click();
   await page.evaluate(async () => {usageDay=usageData.calendar_today;await loadUsage()});
   assert.equal(await page.locator('#usage-dialog .heat-hour').count(), 24);
   assert.equal(await page.locator('#usage-dialog .usage-chart-scroll [data-usage-hour]').count(), 24);
   assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
   await page.locator('#usage-dialog .usage-close').click();
   const messages = await page.evaluate(async () => {
    const originalFetch = window.fetch, result = {};
    try {
     window.fetch = async () => new Response(JSON.stringify({type: 'error', error: '旧中文统计错误', message: {key: 'usage.unknownDimension', params: {}}}) + '\n');
     try { await streamedUsage(new URLSearchParams(), undefined, () => {}); } catch (error) { result.stream = error.message; }
     window.fetch = async () => new Response(JSON.stringify({error: '旧中文价格错误', message: {key: 'pricing.err.unknownSource', params: {}}}), {status: 400});
     try { await pricePost('/api/pricing/settings', {}); } catch (error) { result.price = error.message; }
     result.expectedStream = t('usage.unknownDimension'); result.expectedPrice = t('pricing.err.unknownSource');
     result.description = fieldText({summary: '旧中文摘要', summary_message: {key: 'tools.exec.requestPrefix', params: {label: {join: [{key: 'tools.action.runCommand', params: {}}, 'printf ready'], separator: ' '}}}});
     result.rawParams = messageText({join: [{key: 'tools.action.readFile', params: {}}, '中文路径.txt'], separator: ' '});
     result.duration = I18n.formatDuration(65000);
     return result;
    } finally { window.fetch = originalFetch; }
   });
   assert.equal(messages.stream, messages.expectedStream); assert.equal(messages.price, messages.expectedPrice);
   assert.ok(!messages.description.includes('旧中文摘要'));
   assert.ok(messages.description.includes('printf ready'));
   assert.ok(messages.rawParams.includes('中文路径.txt'));
   if (locale === 'en') assert.equal(messages.duration, '1 min 5 sec');
   const turnHtml=await page.evaluate(() => turnPresentation([{type:'turn_context',payload:{turn_id:'synthetic-turn',model:'gpt-example',effort:'high',cwd:'/demo'}}]));
   assert.ok(!turnHtml.includes('[missing:'));
   for(const nextLocale of [locale==='en'?'zh-CN':'en',locale]){
    if(width===390)await page.locator('#back').click();
    await Promise.all([page.waitForEvent('load'),page.locator('#locale-select').selectOption(nextLocale)]);
    await page.evaluate(() => window.__usageStarted);
    assert.equal(await page.evaluate(() => I18n.getLocale()),nextLocale);
    assert.equal(new URL(page.url()).hash,'#synthetic');
   }
   const headers = (await page.request.get(base + '/')).headers();
   const csp = headers['content-security-policy'];
   assert.ok(csp.includes("script-src 'self'") && !csp.includes("'unsafe-inline'"));
   const directoryHtml = fs.readFileSync(require('node:path').join(root, 'designs/browser/local-directory.html'), 'utf8')
    .replace('{{dirname}}', 'synthetic').replace('{{abspath}}', '/demo').replace('{{links}}', '<li>fixture.txt</li>');
   await page.route('**/synthetic-directory-review', route => route.fulfill({contentType: 'text/html', headers: {'Content-Security-Policy': csp}, body: directoryHtml}));
   const cspErrors=[];
   page.on('console', event => {if(event.type()==='error' && /Content Security Policy|violates.*directive/i.test(event.text()))cspErrors.push(event.text())});
   await page.goto(base + '/synthetic-directory-review');
   await page.waitForFunction(() => document.querySelector('[data-i18n="context.localFilePageNote"]').textContent.length > 0);
   assert.equal(await page.title(), await page.evaluate(() => t('context.localFilePageTitle')));
   assert.equal(await page.locator('[data-i18n="context.localFilePageNote"]').innerText(), await page.evaluate(() => t('context.localFilePageNote')));
   assert.equal(await page.evaluate(() => getComputedStyle(document.body).marginTop), '32px');
   assert.deepEqual(cspErrors, []);
   assert.deepEqual(errors, []);
   console.log(locale, width, 'OK: startup, usage, preview, descriptions, errors, raw content and directory CSP');
   await page.close();
  }
 } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
