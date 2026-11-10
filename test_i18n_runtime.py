"""Regression checks for the real locale runtime and locale validation gates."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location('locale_check', ROOT / 'scripts/check_locales.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser runtime checks')
class LocaleRuntime(unittest.TestCase):
    def test_actual_runtime_fallback_descriptors_locale_matching_and_attributes(self):
        script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const base='designs/browser/locales/';
const read=name=>JSON.parse(fs.readFileSync(base+name+'.json','utf8'));
const source=fs.readFileSync('designs/browser/i18n.js','utf8');
class Element {
 constructor(tag='DIV'){this.tagName=tag;this.attrs={};this.children=[];this.style={};this.textContent='';}
 setAttribute(k,v){this.attrs[k]=v}getAttribute(k){return this.attrs[k]??null}
 appendChild(v){this.children.push(v)}querySelector(){return null}
 addEventListener(){}
}
async function load({stored='en',languages=['en-US'],modify=()=>{},fail=[]}={}){
 const docs={'manifest':read('manifest'),'en':read('en'),'zh-CN':read('zh-CN')};modify(docs);
 const main=new Element('MAIN'),nodes=[],warnings=[];
 const doc={currentScript:{src:'http://localhost/i18n.js'},documentElement:{},body:main,
  querySelector:()=>main,querySelectorAll:()=>nodes,createElement:tag=>new Element(tag.toUpperCase())};
 const ctx={document:doc,location:{href:'http://localhost/',reload(){}},navigator:{languages},Intl,Date,URL,
  localStorage:{getItem:()=>stored,setItem(){},removeItem(){}},console:{warn:v=>warnings.push(v)},
  fetch:async url=>{const name=url.split('/').at(-1).replace('.json','');return {ok:!fail.includes(name),status:404,json:async()=>docs[name]}}};
 vm.createContext(ctx);vm.runInContext(source,ctx);let error;try{await ctx.I18n.ready}catch(e){error=e}
 return {ctx,nodes,warnings,main,error};
}
(async()=>{
 const {ctx,nodes,warnings}=await load({modify:docs=>{
  docs.en['test.empty']='';docs['zh-CN']['test.empty']='fallback';
  docs.en['test.plural']={one:'',other:''};docs['zh-CN']['test.plural']={other:'fallback {count}'};
 }});
 assert.equal(ctx.I18n.formatDuration(65000),'1 min 5 sec');
 assert.equal(ctx.I18n.formatDuration(119000),'1 min 59 sec');
 assert.equal(ctx.I18n.formatDuration(125000),'2 min 5 sec');
 assert.equal(ctx.t('test.empty'),'fallback');assert.equal(ctx.tp('test.plural',1),'fallback 1');
 ctx.t('test.empty');assert.equal(warnings.filter(v=>v.includes('test.empty')).length,1);
 assert.equal(ctx.t('test.absent'),'[missing:test.absent]');
 const desc={key:'tools.exec.requestPrefix',params:{label:{join:[{key:'tools.action.readFile'},'<raw-path>'],separator:' '}}};
 assert.equal(ctx.I18n.renderMessage(desc),ctx.t('tools.exec.requestPrefix',{label:ctx.t('tools.action.readFile')+' <raw-path>'}));
 assert.equal(ctx.I18n.renderMessage({join:['literal Chinese 原文',{key:'common.close'}],separator_key:'tools.activityGroupSep'}),'literal Chinese 原文'+ctx.t('tools.activityGroupSep')+'Close');
 assert.equal(ctx.I18n.renderMessage({key:'test.empty',suffixes:[' <raw>']}),'fallback <raw>');
 const img=new Element('IMG');img.attrs={'data-i18n':'accessibility.brandAlt','data-i18n-attr':'alt'};nodes.push(img);
 const forbidden=new Element();forbidden.attrs={'data-i18n':'common.close','data-i18n-attr':'onclick'};nodes.push(forbidden);
 ctx.I18n.applyTranslations(ctx.document);assert.equal(img.attrs.alt,'Codex Microscope');assert.equal(forbidden.attrs.onclick,undefined);
 const french=await load({stored:null,languages:['FR_ca'],modify:docs=>{
  docs.manifest.locales.fr={name:'Français',aliases:['fr'],intl:'fr',dir:'ltr',enabled:true};docs.fr=docs.en;
 }});assert.equal(french.ctx.I18n.getLocale(),'fr');
 const region=await load({stored:'EN_us'});assert.equal(region.ctx.I18n.getLocale(),'en');
 const fallback=await load({fail:['en']});assert.equal(fallback.ctx.I18n.getLocale(),'zh-CN');assert.equal(fallback.ctx.t('common.close'),'关闭');
 const optionalFallback=await load({fail:['zh-CN']});assert.equal(optionalFallback.ctx.t('common.close'),'Close');
 const failed=await load({fail:['manifest']});assert.ok(failed.error);assert.ok(failed.ctx.I18n.loadFailed);
 assert.match(failed.main.children[0].children[0].textContent,/Unable to load/);
 assert.match(failed.main.children[0].children.at(-1).textContent,/Retry/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LocaleValidation(unittest.TestCase):
    def fixture(self, directory):
        locale_dir = Path(directory)
        meta = {'glossary': {}, 'keys': {
            'test.message': {'params': [], 'plural': False},
            'test.duration': {'params': [{'name': 'minutes'}, {'name': 'seconds'}], 'plural': True},
        }}
        docs = {
            'manifest': {'default': 'zh-CN', 'fallback': 'zh-CN', 'locales': {
                'en': {'enabled': True, 'plurals': ['one', 'other']},
                'zh-CN': {'enabled': True, 'plurals': ['other']},
            }},
            'messages.meta': meta,
            'en': {'test.message': 'Close', 'test.duration': {
                'one': '{minutes} min {seconds} sec', 'other': '{minutes} min {seconds} sec'}},
        }
        docs['zh-CN'] = {'test.message': '关闭', 'test.duration': {'other': '{minutes} 分 {seconds} 秒'}}
        for name, doc in docs.items():
            (locale_dir / (name + '.json')).write_text(json.dumps(doc))
        return locale_dir

    def check(self, directory):
        with patch.object(CHECK, 'LOCALES', directory), \
             patch.object(CHECK, 'check_public_files'), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return CHECK.main()

    def test_each_enabled_language_and_each_plural_branch_must_be_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.assertEqual(self.check(root), 0)
            path = root / 'en.json'; messages = json.loads(path.read_text())
            del messages['test.message']; path.write_text(json.dumps(messages))
            self.assertEqual(self.check(root), 1)
            root = self.fixture(directory); messages = json.loads(path.read_text())
            messages['test.duration']['one'] = '1 min 1 sec'; path.write_text(json.dumps(messages))
            self.assertEqual(self.check(root), 1)

    def test_duplicate_keys_and_unsupported_translation_content_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'duplicate.json'; path.write_text('{"key":1,"key":2}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                CHECK.load_json(path)
            for value in ('关闭', '<b>Close</b>', '%s reading', 'Characters %1$d'):
                with self.subTest(value=value):
                    root = self.fixture(directory); path = root / 'en.json'
                    messages = json.loads(path.read_text()); messages['test.message'] = value
                    path.write_text(json.dumps(messages)); self.assertEqual(self.check(root), 1)


if __name__ == '__main__':
    unittest.main()
