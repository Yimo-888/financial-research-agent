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
_NUMBER = re.compile(
    r'(?<![\w.])(?P<sign>[-−])?(?P<dollar>\$)?'
    r'(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?'
    r'(?:\s*(?P<word>trillion|billion|million|thousand|percent)\b'
    r'|(?P<sym>%|bn|mm|[TBMK])(?![A-Za-z]))?',
    re.IGNORECASE,
)


def extract_numbers(text):
    """Numbers in `text` worth checking, as dicts with raw-scale `value`,
    `tolerance` and the original `text`. Skips dates, URLs, years and small
    bare counts ("3 years", "2 companies")."""
    text = _URL.sub(' ', _ISO_DATE.sub(' ', text))
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
            'value': sign * num * scale,
            'tolerance': half_step * scale,
            'percent': percent,
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


def untraced_numbers(answer, tool_results):
    known = []
    for result in tool_results:
        collect_tool_numbers(result, known)
    return [c['text'] for c in extract_numbers(answer) if not _matches(c, known)]
