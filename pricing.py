"""Public-source price snapshots, local preferences, and recorded-call estimates."""
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

LOCAL = Path(__file__).parent / '.local' / 'pricing'
SOURCES = {
    'litellm': 'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json',
    'modelsdev': 'https://models.dev/api.json',
    'credits': 'https://learn.chatgpt.com/docs/pricing.md',
}
DEFAULTS = {'source': 'litellm', 'basis': 'purchase', 'missing_tier': 'unrated',
            'credit_rule': None}
LOCK = threading.RLock()


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def preferences():
    saved = read_json(LOCAL / 'settings.json', {})
    settings = {**DEFAULTS, **saved}
    # Older versions exposed credits as a separate, unconverted display mode.
    if settings['basis'] == 'credits':
        settings['basis'] = 'purchase'
    if 'credit_rule' not in saved:
        settings['credit_rule'] = next((rule for rule in settings.get('credit_rules', []) if rule['id'] == settings.get('credit_rule_id')), None)
    if settings.get('credit_rule'):
        settings['credit_rule'] = {key:settings['credit_rule'][key] for key in ('currency','amount','credits')}
    settings.pop('credit_rules', None)
    settings.pop('credit_rule_id', None)
    return settings


def configure(value):
    allowed = {'source': ('litellm', 'modelsdev'), 'basis': ('api', 'credits', 'purchase'),
               'missing_tier': ('unrated', 'standard')}
    if not isinstance(value, dict) or any(key not in {*allowed, 'credit_rule'} for key in value):
        raise ValueError('无效的价格设置')
    if any(key in value and value[key] not in choices for key, choices in allowed.items()):
        raise ValueError('无效的价格设置')
    value = dict(value)
    if value.get('basis') == 'credits':
        value['basis'] = 'purchase'
    if 'credit_rule' in value:
        value['credit_rule'] = validate_credit_rule(value['credit_rule'])
    with LOCK:
        settings = {**preferences(), **value}
        save_json(LOCAL / 'settings.json', settings)
    return status()


def validate_credit_rule(rule):
    if rule is None:
        return None
    if not isinstance(rule, dict) or set(rule) != {'currency', 'amount', 'credits'}:
        raise ValueError('换算规则只需支付金额和获得 credits')
    if rule['currency'] != 'USD':
        raise ValueError('换算金额仅使用 USD')
    normalized = {'currency': 'USD'}
    for key in ('amount', 'credits'):
        raw = rule[key]
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)) or len(str(raw)) > 40:
            raise ValueError('金额和 credits 应为正数')
        try:
            number_value = Decimal(str(raw))
        except InvalidOperation as error:
            raise ValueError('金额和 credits 应为正数') from error
        if not number_value.is_finite() or number_value <= 0 or number_value > Decimal('1e12') or number_value.as_tuple().exponent < -12:
            raise ValueError('金额和 credits 应为正数，最多 12 位小数且不超过 1 万亿')
        normalized[key] = format(number_value, 'f')
    return normalized


def active_credit_rule(settings):
    return settings.get('credit_rule')


class CreditTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.cells = []
        if tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            if self.cells is not None:
                self.cells.append(''.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None


def credit_prices(text):
    # Parse only the explicitly identified official credit token-rate table.
    for table in re.findall(r'<table\b[^>]*>.*?</table>', text, re.S):
        if 'Credits per 1M tokens' not in table:
            continue
        parser = CreditTable()
        parser.feed(table)
        models = {}
        for row in parser.rows:
            if len(row) != 4 or not row[0].startswith('GPT-'):
                continue
            numbers = [re.fullmatch(r'([\d,.]+)\s+credits', cell) for cell in row[1:]]
            if all(numbers):
                model = row[0].lower().replace(' ', '-')
                models[model] = dict(zip(('input', 'cached', 'output'),
                                        [float(match[1].replace(',', '')) for match in numbers]))
        if not models:
            raise ValueError('官方 credits 表未解析到模型，保留已有缓存')
        # Multipliers are accepted only when explicitly returned in the source.
        speed = {}
        for name in ('Fast', 'Ultrafast'):
            match = re.search(name + r' mode uses\s+(\d+(?:\.\d+)?)x', table)
            if match:
                speed[name.lower()] = float(match[1])
        return {'models': models, 'speed': speed}
    raise ValueError('官方 credits 页面格式发生变化，保留已有缓存')


def validate(source, data):
    if source == 'litellm':
        candidates = [value for value in data.values() if isinstance(value, dict) and value.get('litellm_provider') == 'openai']
        if not any('input_cost_per_token' in value for value in candidates):
            raise ValueError('接口未返回 OpenAI 单价，保留已有缓存')
    if source == 'modelsdev' and not data.get('openai', {}).get('models'):
        raise ValueError('接口未返回 OpenAI 模型，保留已有缓存')


def refresh(source):
    if source not in SOURCES:
        raise ValueError('未知价格源')
    request = urllib.request.Request(SOURCES[source], headers={'User-Agent': 'CodexSessions/1'})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(24 * 1024 * 1024 + 1)
    if len(raw) > 24 * 1024 * 1024:
        raise ValueError('价格响应超出大小限制')
    data = credit_prices(raw.decode()) if source == 'credits' else json.loads(raw)
    validate(source, data)
    snapshot = {'url': SOURCES[source], 'fetched_at': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(raw).hexdigest(), 'data': data}
    with LOCK:
        save_json(LOCAL / (source + '.json'), snapshot)
    return status()


def snapshot(source):
    return read_json(LOCAL / (source + '.json'), {})


def status():
    sources = {}
    for source, url in SOURCES.items():
        cached = snapshot(source)
        sources[source] = {'url': url, 'fetched_at': cached.get('fetched_at'),
                           'sha256': cached.get('sha256')}
    return {'settings': preferences(), 'sources': sources}


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return Decimal(str(value))
    return None


def quote(event, settings, cached):
    if not cached:
        return None, '价格尚未缓存'
    model = event.get('model')
    if not model:
        return None, '模型未记录'
    tier = event.get('tier')
    if tier is None:
        if settings['missing_tier'] == 'standard':
            tier = 'standard'
        else:
            return None, '速度档位未记录'
    tokens = event['tokens']
    data = cached['data']
    if settings['basis'] in ('credits', 'purchase'):
        rates = data.get('models', {}).get(model)
        if not rates:
            return None, 'credits 模型价格未收录'
        if tier in ('standard', 'default'):
            multiplier = Decimal(1)
        else:
            multiplier = number(data.get('speed', {}).get(tier))
            if multiplier is None:
                return None, 'credits 档位价格未收录'
        quantities = {'input': tokens['input'] + tokens['cache_write'], 'cached': tokens['cached'],
                      'output': tokens['output'] + tokens['reasoning']}
    else:
        request_input = event.get('request_input')
        if request_input is None:
            return None, '调用输入长度未记录'
        long_context = request_input > 272000
        if settings['source'] == 'litellm':
            entry = data.get(model)
            if not isinstance(entry, dict) or entry.get('litellm_provider') != 'openai':
                return None, 'OpenAI 模型价格未收录'
            suffix = {'standard': '', 'default': '', 'fast': '_priority',
                      'flex': '_flex', 'ultrafast': '_ultrafast', 'batch': '_batches'}.get(tier)
            if suffix is None:
                return None, '档位价格未收录'
            quantities = {'input': tokens['input'], 'cached': tokens['cached'],
                          'output': tokens['output'] + tokens['reasoning']}
            # Cache-write retention is not present in our logs, so do not pick a duration.
            if tokens['cache_write']:
                return None, '缓存写入时长未记录'
            keys = {'input': 'input_cost_per_token', 'cached': 'cache_read_input_token_cost',
                    'output': 'output_cost_per_token'}
            rates = {key: entry.get(base + ('_above_272k_tokens' if long_context else '') + suffix)
                     for key, base in keys.items()}
            scale = Decimal(1)
        else:
            if tier not in ('standard', 'default'):
                return None, '此价格源未提供该档位'
            cost = data.get('openai', {}).get('models', {}).get(model, {}).get('cost')
            if not cost:
                return None, 'OpenAI 模型价格未收录'
            if long_context:
                cost = next((row for row in cost.get('tiers', []) if row.get('tier', {}).get('size') == 272000), {})
            rates = {'input': cost.get('input'), 'cached': cost.get('cache_read'), 'output': cost.get('output')}
            if tokens['cache_write']:
                return None, '缓存写入时长未记录'
            quantities = {'input': tokens['input'], 'cached': tokens['cached'],
                          'output': tokens['output'] + tokens['reasoning']}
            scale = Decimal(1000000)
    if settings['basis'] in ('credits', 'purchase'):
        scale = Decimal(1000000)
    else:
        multiplier = Decimal(1)
    total = Decimal(0)
    for key, quantity in quantities.items():
        if not quantity:
            continue
        rate = number(rates.get(key))
        if rate is None:
            return None, '所需单价缺失'
        total += quantity * rate * multiplier / scale
    return total, None


class Estimator:
    def __init__(self):
        self.settings = preferences()
        source = 'credits' if self.settings['basis'] in ('credits', 'purchase') else self.settings['source']
        self.cached = snapshot(source)
        self.source = source

    def metadata(self):
        rule = active_credit_rule(self.settings)
        unit = (rule['currency'] if rule else '') if self.settings['basis'] == 'purchase' else 'credits' if self.settings['basis'] == 'credits' else 'USD'
        return {'basis': self.settings['basis'], 'unit': unit, 'credit_rule': rule if self.settings['basis'] == 'purchase' else None,
                'source': self.source, 'url': SOURCES[self.source],
                'fetched_at': self.cached.get('fetched_at'), 'sha256': self.cached.get('sha256'),
                'missing_tier': self.settings['missing_tier']}

    def calculate(self, event):
        return quote(event, self.settings, self.cached)


def empty_cost():
    return {'value': Decimal(0), 'rated_tokens': 0, 'unrated_tokens': 0, 'reasons': {}}


def add_cost(target, amount, reason, total):
    if amount is None:
        target['unrated_tokens'] += total
        target['reasons'][reason] = target['reasons'].get(reason, 0) + total
    else:
        target['rated_tokens'] += total
        target['value'] += amount


def cost_json(value, pricing=None):
    result = {**value, 'value': float(value['value'])}
    if pricing and pricing.get('basis') == 'purchase':
        result['credits'] = float(value['value'])
        rule = pricing.get('credit_rule')
        result['value'] = float(value['value'] * Decimal(rule['amount']) / Decimal(rule['credits'])) if rule else None
    return result
