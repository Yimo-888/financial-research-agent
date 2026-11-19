"""
Evidence for one agent run: every number, quote and citation in the answer,
linked to the tool call that backs it — or marked as unbacked.

This is the same tracing the guardrails do, kept as data so the UI (ui.py)
can show it instead of only acting on it. Nothing here calls the model.
"""
from .grounding import passages_in, strip_grounded, trace
from .guardrails import trace_numbers


def _step_of_passage(steps):
    """{passage id: index of the first step that returned it}."""
    first = {}
    for i, step in enumerate(steps):
        for pid in passages_in(step['result']):
            first.setdefault(pid, i)
    return first


def marks(answer, steps, question=''):
    """Spans of `answer` to highlight, in order, never overlapping. Each is
    {kind, start, end, ok, step, passage, note}: `step` is the index of the
    backing tool call (None if unbacked), `passage` a passage id for text."""
    results = [s['result'] for s in steps]
    home = _step_of_passage(steps)
    found = []
    for t in trace(answer, results, question):
        ok = t['passage'] is not None
        cited = t['passage'] if t['passage'] in home else None
        note = ('your own words, quoted back' if t['passage'] == 'question'
                else f'found word for word in {cited}' if ok and t['kind'] == 'quote'
                else 'returned by a tool' if ok
                else 'not in any retrieved passage' if t['kind'] == 'quote'
                else 'no tool returned this passage')
        found.append({'kind': t['kind'], 'start': t['start'], 'end': t['end'], 'ok': ok,
                      'step': home.get(cited), 'passage': cited, 'note': note})
    for n in trace_numbers(strip_grounded(answer, results), results):
        ok = n['source'] is not None
        note = (f'traced to step {n["source"] + 1} ({steps[n["source"]]["tool"]})' if ok
                else 'not traced to any tool result')
        found.append({'kind': 'number', 'start': n['start'], 'end': n['end'], 'ok': ok,
                      'step': n['source'], 'passage': None, 'note': note})

    found.sort(key=lambda m: (m['start'], -m['end']))
    kept = []
    for mark in found:              # a number inside an unverified quote: keep the quote
        if not kept or mark['start'] >= kept[-1]['end']:
            kept.append(mark)
    return kept


def build(question, result):
    """Everything the evidence page shows, as plain data."""
    found = marks(result.answer, result.steps, question)
    return {
        'question': question,
        'answer': result.answer,
        'marks': found,
        'steps': result.steps,
        'drafts': result.drafts,
        'stopped': result.stopped,
        'model_calls': result.model_calls,
        'tokens': result.prompt_tokens + result.completion_tokens,
        'checked': {kind: {'ok': sum(m['ok'] for m in found if m['kind'] == kind),
                           'total': sum(m['kind'] == kind for m in found)}
                    for kind in ('number', 'quote', 'citation')},
    }
