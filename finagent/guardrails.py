"""
Number-tracing guardrail: every number in the final answer must match a
number some tool actually returned. A number the model typed from memory, or
computed in its head, is flagged — the agent then gets one chance to fix it
(use `calculate`, or drop it).

Matching is unit-aware: "$383.3 billion" matches a tool value of
383285000000, and "44.1%" matches a calculator result of 44.13 or 0.4413.
A number is allowed to be off by the rounding its own precision implies
(383.3 billion covers 383.25–383.35 billion) or 0.5%, whichever is larger.
"""
import re

SCALES = {
    'trillion': 1e12, 't': 1e12,
    'billion': 1e9, 'b': 1e9, 'bn': 1e9,
    'million': 1e6, 'm': 1e6, 'mm': 1e6,
    'thousand': 1e3, 'k': 1e3,
}
REL_TOLERANCE = 0.005

_ISO_DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
_URL = re.compile(r'https?://\S+')
_CONSTANT = re.compile(r'\d+(?:\.\d+)?')
_NUMBER = re.compile(
    r'(?<![\w.])(?P<sign>[-−])?(?P<dollar>\$)?'
    r'(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?'
    r'(?:\s*(?P<word>trillion|billion|million|thousand|percent)\b'
    r'|(?P<sym>%|bn|mm|[TBMK])(?![A-Za-z]))?',
    re.IGNORECASE,
)


def extract_numbers(text):
    """Numbers in `text` worth checking, as dicts with raw-scale `value`,
    `tolerance`, the original `text` and where it `start`s and `end`s. Skips
    dates, URLs, years and small bare counts ("3 years", "2 companies")."""
    # Blank out with equal-length spaces so positions still refer to `text`.
    for pattern in (_ISO_DATE, _URL):
        text = pattern.sub(lambda m: ' ' * len(m[0]), text)
    found = []
    for m in _NUMBER.finditer(text):
        unit = (m['word'] or m['sym'] or '').lower()
        decimals = m['dec'] or ''
        num = float(m['int'].replace(',', '') + decimals)
        if not (m['dollar'] or unit or decimals) and (num < 100 or 1900 <= num <= 2100):
            continue
        percent = unit in ('%', 'percent')
        scale = 1.0 if percent else SCALES.get(unit, 1.0)
        sign = -1 if m['sign'] else 1
        half_step = 0.5 * 10 ** -(len(decimals) - 1 if decimals else 0)
        found.append({
            'text': m.group(0).strip(),
            'start': m.start(),
            'end': m.end(),
            'value': sign * num * scale,
            'tolerance': half_step * scale,
            'percent': percent,
            'scale': scale,
            'bare': not (m['dollar'] or unit),
        })
    return found


def collect_tool_numbers(obj, out=None):
    """Every int/float anywhere inside a (nested) tool result."""
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_tool_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_tool_numbers(v, out)
    return out


def _matches(claim, known):
    # (value, tolerance) readings of the claim; "44.1%" may be stored as 44.13
    # or as the fraction 0.4413.
    readings = [(claim['value'], claim['tolerance'])]
    if claim['percent']:
        readings.append((claim['value'] / 100, claim['tolerance'] / 100))
    for target in known:
        for value, precision in readings:
            tol = max(precision, REL_TOLERANCE * abs(target))
            # Compare magnitudes: "a net loss of $2.1 billion" is written
            # without the minus sign the filing value carries.
            if abs(abs(value) - abs(target)) <= tol:
                return True
    return False


def mentions_value(answer, expected):
    """True if any number in `answer` matches `expected` (used by the eval)."""
    return any(_matches(c, [expected]) for c in extract_numbers(answer))


def _unscaled(claim):
    # "$33.9 billion" from calculate("(a - b) / 1000000000") = 33.948: the
    # model already divided by the scale it then wrote out in words.
    return {**claim, 'value': claim['value'] / claim['scale'],
            'tolerance': claim['tolerance'] / claim['scale']}


def _from_calculation(claim, result):
    """Ways a claim can come from one calculate result besides equalling it."""
    if 'expression' not in result or 'result' not in result:
        return False
    # Only calculator results can be pre-scaled; EDGAR values are raw dollars.
    if claim['scale'] != 1 and _matches(_unscaled(claim), [result['result']]):
        return True
    # A formula written out in the answer ("… × 100") repeats constants the
    # model typed into the calculator. Bare numbers only: "$100 billion" is a
    # financial claim and must match a value.
    constants = [float(n) for n in _CONSTANT.findall(result['expression'].replace(',', ''))]
    return claim['bare'] and claim['value'] in constants


def _source_ids(obj, out=None):
    """Digit runs in every `source` link inside a tool result: the company's
    SEC number and the filing's accession number. An answer may repeat them."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        if isinstance(obj.get('source'), str):
            out.update(float(n) for n in re.findall(r'\d+', obj['source']))
        obj = list(obj.values())
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _source_ids(item, out)
    return out


def trace_numbers(answer, tool_results):
    """Every checked number as {text, start, end, source}; `source` is the
    index of the first tool result it traces to, or None."""
    traced = []
    for claim in extract_numbers(answer):
        source = next((i for i, result in enumerate(tool_results)
                       if _matches(claim, collect_tool_numbers(result))
                       or _from_calculation(claim, result)
                       or (claim['bare'] and claim['value'] in _source_ids(result))), None)
        traced.append({'text': claim['text'], 'start': claim['start'], 'end': claim['end'],
                       'source': source})
    return traced


def untraced_numbers(answer, tool_results):
    return [n['text'] for n in trace_numbers(answer, tool_results) if n['source'] is None]
