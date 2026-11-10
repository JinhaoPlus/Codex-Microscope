import json
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import pricing


class SourcePricing(unittest.TestCase):
    def test_single_rule_persists_replaces_and_migrates_active_legacy_rule(self):
        rule = dict(currency='USD',amount='20',credits='100')
        with tempfile.TemporaryDirectory() as directory, patch.object(pricing, 'LOCAL', Path(directory)):
            pricing.save_json(pricing.LOCAL/'settings.json',dict(credit_rules=[dict(id='old',**rule),dict(id='other',**{**rule,'amount':'30'})],credit_rule_id='old'))
            self.assertEqual(pricing.preferences()['credit_rule'],rule)
            self.assertNotIn('credit_rules',pricing.preferences())
            edited = {**rule, 'amount':'25'}
            pricing.configure(dict(basis='purchase',credit_rule=edited))
            self.assertEqual(pricing.preferences()['credit_rule'], edited)
            self.assertEqual(pricing.Estimator().metadata()['unit'], 'USD')
            invalid = [dict(credit_rules=[rule]),dict(credit_rule=[rule,rule])]
            for key,value in [('amount','0'),('amount','-1'),('amount','NaN'),('credits','Infinity'),('credits',True),('currency','CNY'),('amount','1e-13')]:
                invalid.append(dict(credit_rule={**rule,key:value}))
            for update in invalid:
                with self.subTest(update=update),self.assertRaises(ValueError):
                    pricing.configure(update)
                self.assertEqual(pricing.preferences()['credit_rule'],edited)
            pricing.configure(dict(credit_rule=None))
            self.assertIsNone(pricing.Estimator().metadata()['credit_rule'])

    def test_purchase_conversion_retains_credits_and_does_not_invent_money(self):
        cost = pricing.empty_cost()
        pricing.add_cost(cost, Decimal('33'), None, 650000)
        rule = dict(id='test', name='测试', currency='CNY', amount='8', credits='80')
        converted = pricing.cost_json(cost, dict(basis='purchase',credit_rule=rule))
        self.assertEqual(converted['value'], 3.3)
        self.assertEqual(converted['credits'], 33)
        self.assertEqual(converted['rated_tokens'], 650000)
        missing = pricing.cost_json(cost, dict(basis='purchase',credit_rule=None))
        self.assertIsNone(missing['value'])
        self.assertEqual(missing['credits'], 33)
        self.assertEqual(pricing.cost_json(cost)['value'], 33)

    def test_only_recorded_rates_and_tiers_are_used(self):
        settings = dict(pricing.DEFAULTS, basis='api')
        snapshot = {'data': {'example': {'litellm_provider': 'openai',
                    'input_cost_per_token': .000002, 'cache_read_input_token_cost': .0000001,
                    'output_cost_per_token': .00001}}}
        event = {'model': 'example', 'tier': 'standard', 'request_input': 100,
                 'tokens': dict(input=50, cached=50, cache_write=0, output=8, reasoning=2)}
        amount, reason = pricing.quote(event, settings, snapshot)
        self.assertEqual(amount, Decimal('.000205'))
        self.assertIsNone(reason)
        for field, value in [('model', 'missing'), ('tier', 'fast'), ('tier', None), ('request_input', None)]:
            self.assertIsNone(pricing.quote({**event, field:value}, settings, snapshot)[0])
        event['tokens']['cache_write'] = 10
        self.assertIsNone(pricing.quote(event, settings, snapshot)[0])

    def test_modelsdev_units_and_recorded_context_tier(self):
        settings = dict(pricing.DEFAULTS, basis='api', source='modelsdev')
        data = {'data': {'openai': {'models': {'example': {'cost': {
            'input': 2, 'output': 10, 'cache_read': .1,
            'tiers': [{'tier': {'type':'context', 'size':272000}, 'input':4, 'output':15, 'cache_read':.2}]
        }}}}}}
        event = dict(model='example', tier='standard', request_input=300000,
                     tokens=dict(input=100, cached=0, cache_write=0, output=10, reasoning=0))
        self.assertEqual(pricing.quote(event, settings, data)[0], Decimal('.00055'))

    def test_official_credits_table_and_no_invented_multiplier(self):
        html = """<table><tr><th>Credits per 1M tokens</th></tr>
        <tr><td>GPT-Example</td><td>50 credits</td><td>2.5 credits</td><td>250 credits</td></tr>
        <tr><td>Fast mode uses 2x the Standard rate</td></tr></table>"""
        parsed = pricing.credit_prices(html)
        self.assertEqual(parsed['models']['gpt-example']['cached'], 2.5)
        event = dict(model='gpt-example', tier='fast', tokens=dict(input=100, cached=0, cache_write=10, output=8, reasoning=2))
        amount, _ = pricing.quote(event, dict(pricing.DEFAULTS,basis='credits'), {'data': parsed})
        self.assertEqual(amount, Decimal('.016'))
        event['tier'] = 'ultrafast'
        self.assertIsNone(pricing.quote(event, dict(pricing.DEFAULTS,basis='credits'), {'data': parsed})[0])
        with self.assertRaises(ValueError):
            pricing.credit_prices('changed page format')

    def test_local_cache_survives_failed_refresh_and_preferences_persist(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pricing, 'LOCAL', Path(directory)):
            original = {'data': {'example': 1}, 'sha256': 'previous'}
            pricing.save_json(Path(directory)/'litellm.json', original)
            pricing.configure({'basis':'credits', 'source':'modelsdev'})
            self.assertEqual(pricing.preferences()['basis'], 'purchase')
            with patch.object(pricing, 'download_prices', side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    pricing.refresh('litellm')
            self.assertEqual(pricing.snapshot('litellm'), original)
            with self.assertRaises(ValueError):
                pricing.configure({'input_price':123})
            with self.assertRaises(ValueError):
                pricing.refresh('https://example.com/arbitrary-url')

    def test_curl_download_ignores_config_and_restricts_https(self):
        def run(args, **kwargs):
            self.assertEqual(args[:2], ['synthetic-curl', '--disable'])
            self.assertEqual(args[args.index('--proto') + 1], '=https')
            self.assertEqual(args[args.index('--proto-redir') + 1], '=https')
            self.assertNotIn('--insecure', args)
            self.assertNotIn('-k', args)
            self.assertIn('--fail', args)
            self.assertIn('--max-filesize', args)
            self.assertEqual(kwargs['timeout'], 30)
            kwargs['stdout'].write(b'{"synthetic":true}')
            return subprocess.CompletedProcess(args, 0, stderr=b'')
        with patch.object(pricing.sys, 'platform', 'synthetic'), \
             patch.object(pricing.shutil, 'which', return_value='synthetic-curl'), \
             patch.object(pricing.subprocess, 'run', side_effect=run):
            self.assertEqual(pricing.download_prices('https://example.test/prices'), b'{"synthetic":true}')

    def test_curl_failures_preserve_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pricing, 'LOCAL', Path(directory)), \
             patch.object(pricing.sys, 'platform', 'synthetic'), \
             patch.object(pricing.shutil, 'which', return_value='synthetic-curl'):
            original = {'data': {'example': 1}, 'sha256': 'previous'}
            pricing.save_json(pricing.LOCAL/'litellm.json', original)
            for code in (22, 60, 63):
                with self.subTest(code=code), patch.object(pricing.subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], code, stderr=b'synthetic failure')):
                    with self.assertRaises((OSError, ValueError)):
                        pricing.refresh('litellm')
                    self.assertEqual(pricing.snapshot('litellm'), original)
            with patch.object(pricing.subprocess, 'run', side_effect=subprocess.TimeoutExpired('curl', 30)):
                with self.assertRaisesRegex(OSError, '超时'):
                    pricing.refresh('litellm')
                self.assertEqual(pricing.snapshot('litellm'), original)

    def test_missing_curl_and_invalid_download_do_not_replace_cache(self):
        with patch.object(pricing.shutil, 'which', return_value=None), \
             patch.object(pricing.Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(OSError, '需要系统 curl'):
                pricing.download_prices('https://example.test/prices')
        with tempfile.TemporaryDirectory() as directory, patch.object(pricing, 'LOCAL', Path(directory)):
            original = {'sha256': 'previous'}
            pricing.save_json(pricing.LOCAL/'litellm.json', original)
            with patch.object(pricing, 'download_prices', return_value=b'not json'):
                with self.assertRaises(ValueError):
                    pricing.refresh('litellm')
                self.assertEqual(pricing.snapshot('litellm'), original)


if __name__ == '__main__':
    unittest.main()
