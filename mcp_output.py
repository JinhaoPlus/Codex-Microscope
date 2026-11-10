"""Hide named credentials in MCP presentation data, including copies in wrapper output."""
import json
import re

MASK = '[已隐藏]'
_KEYS = r'access[_-]?token|refresh[_-]?token|token|api[_-]?key|authorization|password|client[_-]?secret|private[_-]?key|secret'
FIELD = re.compile(rf'^(?:{_KEYS})$', re.I)
# Also handle serialized JSON and JS object literals within a tool's text block.
INLINE = re.compile(rf'''(?<![\w-])["']?(?:{_KEYS})["']?\s*:\s*(?P<quote>["'])(?P<value>(?:\\.|(?!(?P=quote))[^\\\r\n])*)(?P=quote)''', re.I)
URL_AUTH = re.compile(r'https?://[^/?#\s"<>@]+:(?P<value>[^/?#\s"<>@]+)@', re.I)
BEARER = re.compile(r'\bBearer\s+(?P<value>[A-Za-z0-9._~+/=-]{6,})', re.I)
URL_QUERY = re.compile(rf'[?&](?:{_KEYS})=(?P<value>[^&#\s"<>]+)', re.I)


def is_mcp_call(item):
    return any((op.get('tool') or '').startswith('mcp__') or
               str((op.get('event') or {}).get('type','')).lower() in ('mcptoolcall','dynamictoolcall')
               for op in item.get('operations',[]))


def text_rules(text):
    # Media and ordinary text dominate large responses. Only scan possible markers.
    if ':' not in text and '?' not in text and '&' not in text and ' ' not in text:
        return
    has_field=':' in text or ('=' in text and ('?' in text or '&' in text))
    if has_field:
        lowered=text.lower()
        if any(key in lowered for key in ('token','key','password','secret','authorization')):
            yield INLINE
            if '=' in text:yield URL_QUERY
    if 'bearer ' in text.lower():yield BEARER
    if '://' in text and '@' in text:yield URL_AUTH


def scrub(value):
    """Keep non-sensitive records byte-identical where possible, including raw text."""
    secrets = set()
    def visit(obj):
        if isinstance(obj,dict):
            for key, field in obj.items():
                if FIELD.fullmatch(key) and isinstance(field,str) and len(field)>=6:
                    secrets.add(field)
                visit(field)
        elif isinstance(obj,list):
            for field in obj:
                visit(field)
        elif isinstance(obj,str):
            for rule in text_rules(obj):
                for match in rule.finditer(obj):
                    secret=match['value']
                    if len(secret)>=6:
                        secrets.add(secret)
    visit(value)
    secrets.discard(MASK)
    ordered=sorted(secrets,key=len,reverse=True)
    def hide(obj):
        if isinstance(obj,dict):
            return {key:MASK if FIELD.fullmatch(key) and val is not None else hide(val) for key,val in obj.items()}
        if isinstance(obj,list):
            return [hide(v) for v in obj]
        if isinstance(obj,str):
            for rule in text_rules(obj):
                def mask_value(match):
                    start,end=match.span('value')
                    return obj[match.start():start]+MASK+obj[end:match.end()]
                obj=rule.sub(mask_value,obj)
            for secret in ordered:
                obj=obj.replace(secret,MASK)
        return obj
    return hide(value)

def visible_item(item):
    if not is_mcp_call(item):
        return item
    # _stored_raw is only consumed by visible_records. Keep its JSON intact so
    # it can be scrubbed structurally, including escaped strings and numeric fields.
    if '_stored_raw' in item:
        public = scrub({key: value for key, value in item.items() if key != '_stored_raw'})
        return {**public, '_stored_raw': item['_stored_raw']}
    return scrub(item)


def visible_records(item, records):
    if not is_mcp_call(item):return records
    parsed=[json.loads(line) for line in records]
    return [line if old==new else json.dumps(new,ensure_ascii=False) for line,old,new in zip(records,parsed,scrub(parsed))]
