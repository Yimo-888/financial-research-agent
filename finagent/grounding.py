"""
Passage-grounding guardrail: the text counterpart of number tracing.

A statement about what a filing says must rest on a passage a tool returned.
Two things can be checked mechanically, and both are:
  - a cited passage id like [AAPL-2023-1A-p017] must be one a tool returned;
  - a quotation must appear word for word in a returned passage.

A quote that passes is real filing text, so the numbers inside it are exempt
from number tracing (`strip_grounded`). Outside quotes, numbers still have to
come from get_financials or calculate.
"""
import re

MIN_QUOTE_WORDS = 4       # shorter quotes are terms ("net sales"), not evidence
PASSAGE_ID = re.compile(r'\b[A-Z][A-Z.]*-\d{4}-\d{1,2}[A-C]?-p\d+\b')
_QUOTE = re.compile(r'[“"]([^“”"]+)[”"]')
_ELLIPSIS = re.compile(r'\.\.\.|…')
# Markdown emphasis, [e]dit brackets, and every quote mark: a nested “term”
# is usually rewritten as 'term' inside a quotation.
_IGNORED = re.compile(r'[*_\[\]"“”\'‘’]')


def _normalize(text):
    """Lowercase words with markup, quote marks and spacing differences removed."""
    return ' '.join(_IGNORED.sub('', text).lower().split()).strip(' .,;:')


def quotes(answer):
    """Quotations in `answer` long enough to count as evidence."""
    return [q.strip() for q in _QUOTE.findall(answer) if len(q.split()) >= MIN_QUOTE_WORDS]


def appears_in(quote, texts):
    """True if every part of `quote` (parts are separated by an ellipsis) is
    found word for word in one of `texts`."""
    parts = [p for p in map(_normalize, _ELLIPSIS.split(quote)) if p]
    haystacks = [_normalize(t) for t in texts]
    return bool(parts) and all(any(part in h for h in haystacks) for part in parts)


def passages_in(tool_results, found=None):
    """{passage id: text} for every passage anywhere inside the tool results."""
    found = {} if found is None else found
    if isinstance(tool_results, dict):
        if isinstance(tool_results.get('id'), str) and isinstance(tool_results.get('text'), str):
            found[tool_results['id']] = tool_results['text']
        tool_results = list(tool_results.values())
    if isinstance(tool_results, (list, tuple)):
        for item in tool_results:
            passages_in(item, found)
    return found


def trace(answer, tool_results, question=''):
    """Every quote and citation in `answer` as {kind, text, start, end,
    passage}; `passage` is the id it rests on, None if there is none, or
    'question' for words quoted back from the user."""
    known = passages_in(tool_results)
    found = [{'kind': 'citation', 'text': m[0], 'start': m.start(), 'end': m.end(),
              'passage': m[0] if m[0] in known else None}
             for m in PASSAGE_ID.finditer(answer)]
    for m in _QUOTE.finditer(answer):
        if len(m[1].split()) < MIN_QUOTE_WORDS:
            continue
        passage = next((pid for pid, text in known.items() if appears_in(m[1], [text])), None)
        if passage is None and appears_in(m[1], [*known.values()]):
            passage = next(iter(known))          # parts of the quote span passages
        if passage is None and appears_in(m[1], [question]):
            passage = 'question'
        found.append({'kind': 'quote', 'text': m[1].strip(), 'start': m.start(), 'end': m.end(),
                      'passage': passage})
    return found


def ungrounded(answer, tool_results, question=''):
    """Problems as short strings: unknown passage ids and unverifiable quotes."""
    loose = [t for t in trace(answer, tool_results, question) if t['passage'] is None]
    return list(dict.fromkeys(
        f'[{t["text"]}] is not a passage any tool returned' if t['kind'] == 'citation'
        else f'"{t["text"]}" is not in any retrieved passage' for t in loose))


def strip_grounded(answer, tool_results):
    """`answer` with passage ids and verified quotes blanked out, for number
    tracing. Same length as `answer`, so positions carry over."""
    for t in trace(answer, tool_results):
        if t['passage']:
            answer = answer[:t['start']] + ' ' * (t['end'] - t['start']) + answer[t['end']:]
    return answer
