"""The API describes product text without localizing or rewriting log data."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import demo_cases
import exec_presentation
import message_i18n
import server


@unittest.skipUnless(shutil.which('node'), 'Node.js is required to exercise the real locale renderer')
class BackendMessages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        messages = {}
        for case in demo_cases.catalog():
            identifier = case['id']
            page = server.demo_response('/api/demo/thread', {'id': [identifier]})[1]
            cls.cases[identifier] = page
            messages[identifier] = [item['exec_view']['label_message'] if item.get('exec_view') else
                                   op['summary_message'] for item in page['items'] if item['kind'] == 'tool'
                                   for op in ([{}] if item.get('exec_view') else item['operations'])]
        cls.labels = cls.render(messages)

    @staticmethod
    def render(messages):
        script = r"""
const fs=require('node:fs'),vm=require('node:vm');
const ctx={Intl,Date,URL,location:{href:'http://localhost/'},navigator:{languages:['en-US']},
 localStorage:{getItem:()=> 'en'},console,
 document:{currentScript:{src:'http://localhost/i18n.js'},documentElement:{}},
 fetch:async url=>({ok:true,json:async()=>JSON.parse(fs.readFileSync('designs/browser'+url,'utf8'))})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('designs/browser/i18n.js','utf8'),ctx);
ctx.I18n.ready.then(()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(input).map(([key,values])=>
  [key,values.map(v=>ctx.I18n.renderMessage(v))]))));
}).catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps(messages),
                                text=True, capture_output=True, cwd=Path(__file__).parent, check=True)
        return json.loads(result.stdout)

    def test_generated_summaries_are_english_in_all_synthetic_cases(self):
        for identifier, labels in self.labels.items():
            for label in labels:
                with self.subTest(case=identifier, label=label):
                    # The CUA fixture contains a logged completion summary in
                    # Chinese. It is data, and must stay exactly as recorded.
                    product_text = label.replace('检查了图表', '') if identifier == 'direct-cua' else label
                    self.assertNotRegex(product_text, r'[\u3400-\u9fff]|\[missing:|\{\w+\}')
        self.assertIn('检查了图表', ' '.join(self.labels['direct-cua']))
        parallel = self.labels['parallel-image'][0]
        self.assertIn('intro.md', parallel)
        self.assertIn('theme.css', parallel)
        self.assertIn('palette.png', parallel)
        self.assertIn('4', parallel)
        self.assertIn('17', ' '.join(self.labels['terminal']))
        self.assertIn('No new output', ' '.join(self.labels['quiet-poll']))
        failure = self.labels['patch-error'][0]
        self.assertEqual(failure.lower().count('write failed'), 1)

    def test_list_limit_and_raw_subjects_survive_translation(self):
        raw_path = '原文/<file>.md'
        descriptors = [exec_presentation.native_label(dict(type='read', path=raw_path))['label_message'],
                       exec_presentation.native_label(dict(type='list_files', path='docs', output_limit=2))['label_message'],
                       exec_presentation.native_label(dict(type='list_files'))['label_message']]
        labels = self.render({'labels': descriptors})['labels']
        self.assertIn(raw_path, labels[0])
        self.assertIn('docs', labels[1])
        self.assertIn('2', labels[1])
        self.assertNotRegex(labels[2], r'[\u3400-\u9fff]')

    def test_only_generated_multimodal_placeholders_are_translated(self):
        raw = 'Literal user text: [图片] 原文'
        content = [dict(type='input_text', text=raw), dict(type='input_image', image_url='data:image/png;base64,AA==')]
        descriptor = server.text_message(content)
        self.assertEqual(self.render({'message': [descriptor]})['message'][0], raw + '\n[Image]')
        self.assertEqual(content[0]['text'], raw)
        self.assertEqual(server.text_message(raw), raw)

    def test_unknown_error_keeps_diagnostic_without_claiming_not_found(self):
        error = message_i18n.i18n_error(ValueError('synthetic diagnostic'))
        self.assertEqual(error['message']['key'], 'errors.unexpected')
        self.assertEqual(error['details']['diagnostic'], 'synthetic diagnostic')


if __name__ == '__main__':
    unittest.main()
