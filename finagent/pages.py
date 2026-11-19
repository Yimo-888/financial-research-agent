"""
HTML for the evidence UI (served by ui.py, or saved with `finagent --html`).

Evidence page: the answer on the left, where every number, quote and passage
citation is a link to the tool call that backs it on the right; anything
unbacked is marked in red. Report page: a comparison table from report.py.

Standard library only: pages are built as strings, and the answer's Markdown
is rendered by the few rules below (headings, lists, tables, bold, links).
Everything that came from the model or the SEC is escaped.
"""
import html
import json
import re

from . import report

_URL = re.compile(r'https?://[^\s<>()\[\]]+[^\s<>()\[\].,;:]')
_LIST_ITEM = re.compile(r'(?:[-*•]|\d+\.)\s+')
_HEADING = re.compile(r'#{1,6}\s+')

CSS = """
:root { --bg:#f6f5f1; --card:#fff; --ink:#1d1f23; --soft:#666b74; --line:#dddad2;
        --ok:#17694a; --ok-bg:#e3f3ea; --bad:#a1261d; --bad-bg:#fbe3e0; --link:#1f4f99; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181c; --card:#1f2227; --ink:#e8e6e1; --soft:#9a9fa8; --line:#343840;
          --ok:#7fd3ad; --ok-bg:#16382b; --bad:#ff9d94; --bad-bg:#4a1d19; --link:#9dbdf2; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--ink);
       font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1280px; margin:0 auto; }
a { color:var(--link); }
h1 { font-size:1.35rem; margin:0 0 4px; } h2 { font-size:1rem; margin:0 0 12px; }
h3 { font-size:1rem; margin:1.1em 0 .3em; }
.soft { color:var(--soft); font-size:.875rem; }
.cols { display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,1fr); gap:20px; margin-top:16px; }
@media (max-width: 900px) { .cols { grid-template-columns:minmax(0,1fr); } }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px;
        margin-bottom:12px; scroll-margin-top:12px; overflow-wrap:anywhere; }
.card:target, .passage:target { outline:2px solid var(--link); }
.chips { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 0; }
.chip { border-radius:999px; padding:2px 10px; font-size:.8125rem; border:1px solid var(--line); }
.ok { color:var(--ok); } .bad { color:var(--bad); }
.chip.ok, .mark.ok { background:var(--ok-bg); } .chip.bad, .mark.bad { background:var(--bad-bg); }
.mark { border-radius:4px; padding:0 2px; text-decoration:none; }
a.mark { border-bottom:1px solid currentColor; } .mark.bad { font-weight:600; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; font-size:.875rem; font-variant-numeric:tabular-nums; }
th, td { border-bottom:1px solid var(--line); padding:5px 10px; text-align:left; vertical-align:top; }
td.num, th.num { text-align:right; white-space:nowrap; }
code, pre { font:.8125rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { white-space:pre-wrap; margin:8px 0 0; max-height:320px; overflow:auto; }
.passage { border-left:3px solid var(--line); padding:2px 0 2px 10px; margin:10px 0; font-size:.9rem;
           scroll-margin-top:12px; }
.tag { font:.75rem ui-monospace, Menlo, monospace; color:var(--soft); display:block; }
details { margin-top:8px; } summary { cursor:pointer; color:var(--soft); font-size:.875rem; }
form { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; }
textarea, input { font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px;
                  background:var(--card); color:var(--ink); }
textarea { flex:1 1 420px; min-height:64px; }
button { font:inherit; padding:8px 16px; border-radius:8px; border:1px solid var(--ink);
         background:var(--ink); color:var(--bg); cursor:pointer; }
label { display:grid; gap:4px; font-size:.875rem; color:var(--soft); }
"""

_esc = html.escape


def _layout(title, body):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{CSS}</style></head>'
            f'<body><main>{body}</main></body></html>')


def _link(url, text=None):
    return f'<a href="{_esc(url)}" rel="noreferrer">{_esc(text or url)}</a>'


def _text(text):
    """Escaped text with bare URLs turned into links."""
    parts, pos = [], 0
    for m in _URL.finditer(text):
        parts += [_esc(text[pos:m.start()]), _link(m[0])]
        pos = m.end()
    return ''.join(parts) + _esc(text[pos:])


def _mark(mark, text):
    target = (f'#p-{mark["passage"]}' if mark['passage']
              else f'#step-{mark["step"] + 1}' if mark['step'] is not None else None)
    css = f'mark {mark["kind"]} {"ok" if mark["ok"] else "bad"}'
    if target:
        return f'<a class="{css}" href="{_esc(target)}" title="{_esc(mark["note"])}">{_esc(text)}</a>'
    return f'<span class="{css}" title="{_esc(mark["note"])}">{_esc(text)}</span>'


def _inline(answer, start, end, marks):
    """answer[start:end] as HTML: marks become links, **bold** becomes <strong>."""
    parts, pos = [], start
    for mark in marks:
        if mark['end'] <= pos or mark['start'] >= end:
            continue
        cut = max(mark['start'], pos)
        parts += [_text(answer[pos:cut]), _mark(mark, answer[cut:min(mark['end'], end)])]
        pos = min(mark['end'], end)
    pieces = (''.join(parts) + _text(answer[pos:end])).split('**')
    if len(pieces) % 2 == 0:                    # unpaired ** — leave as typed
        return '**'.join(pieces)
    return ''.join(p if i % 2 == 0 else f'<strong>{p}</strong>' for i, p in enumerate(pieces))


def answer_html(answer, marks):
    """The answer's Markdown as HTML, line by line, with evidence marks."""
    out, block, offset = [], None, 0

    def switch(to):
        nonlocal block
        if block != to:
            out.append({'ul': '</ul>', 'table': '</table></div>'}.get(block, ''))
            out.append({'ul': '<ul>', 'table': '<div class="scroll"><table>'}.get(to, ''))
            block = to

    for line in answer.split('\n'):
        text = line.strip()
        start = offset + len(line) - len(line.lstrip())
        end = start + len(text)
        offset += len(line) + 1
        if not text:
            switch(None)
        elif text.startswith('|'):
            switch('table')
            if set(text) <= set('|-: '):        # the |---|---| row under the header
                continue
            tag = 'th' if out[-1].endswith('<table>') else 'td'     # first row is the header
            cells, pos = [], start + 1
            for cell in text.strip('|').split('|'):
                cells.append(f'<{tag}>{_inline(answer, pos, pos + len(cell), marks)}</{tag}>')
                pos += len(cell) + 1
            out.append(f'<tr>{"".join(cells)}</tr>')
        elif m := _LIST_ITEM.match(text):
            switch('ul')
            out.append(f'<li>{_inline(answer, start + m.end(), end, marks)}</li>')
        elif m := _HEADING.match(text):
            switch(None)
            out.append(f'<h3>{_inline(answer, start + m.end(), end, marks)}</h3>')
        else:
            switch(None)
            out.append(f'<p>{_inline(answer, start, end, marks)}</p>')
    switch(None)
    return ''.join(out)


def _passage(passage, label, shown):
    # An id may be returned by several steps; only the first gets the anchor.
    pid = passage['id']
    anchor = '' if pid in shown else f' id="p-{_esc(pid)}"'
    shown.add(pid)
    return (f'<div class="passage"{anchor}><span class="tag">{_esc(label + pid)}</span>'
            f'{_esc(passage["text"])}</div>')


def _result_html(step, shown):
    result = step['result']
    if 'error' in result:
        return f'<p class="bad">Error: {_esc(str(result["error"]))}</p>'
    if step['tool'] == 'calculate':
        return f'<p><code>{_esc(result["expression"])}</code> = <strong>{_esc(str(result["result"]))}</strong></p>'
    parts = []
    if 'values' in result:
        rows = ''.join(
            f'<tr><td>{v.get("fiscal_year")}</td><td class="num">{v["value"]:,}</td>'
            f'<td>{_esc(v.get("unit", ""))}</td>'
            f'<td>{_esc(v.get("period_start") or "")} → {_esc(v.get("period_end") or "")}</td>'
            f'<td>{_link(v["source"], "filing") if v.get("source") else ""}</td></tr>'
            for v in result['values'])
        parts.append(f'<p class="soft">{_esc(str(result.get("company") or ""))} · '
                     f'{_esc(str(result.get("metric") or ""))}</p><div class="scroll"><table>'
                     f'<tr><th>FY</th><th class="num">Value</th><th>Unit</th><th>Period</th><th>Source</th></tr>'
                     f'{rows}</table></div>')
    if 'added_count' in result:
        parts.append(f'<p class="soft">{_esc(result["section"])}, fiscal {result["from"]["fiscal_year"]} → '
                     f'{result["to"]["fiscal_year"]}: {result["unchanged_count"]} unchanged, '
                     f'{result["added_count"]} added, {result["removed_count"]} removed, '
                     f'{result["revised_count"]} revised · {_link(result["from"]["source"], "earlier 10-K")} · '
                     f'{_link(result["to"]["source"], "later 10-K")}</p>')
        groups = ([('added · ', p) for p in result['added']] + [('removed · ', p) for p in result['removed']]
                  + [pair for r in result['revised'] for pair in (('revised, now · ', r['new']),
                                                                 ('revised, before · ', r['old']))])
        parts += [_passage(p, label, shown) for label, p in groups]
    if 'passages' in result:
        parts.append(f'<p class="soft">{_esc(str(result.get("company")))} fiscal {result.get("fiscal_year")} '
                     f'10-K · {_link(result["source"], "filing")}</p>')
        parts += [_passage(p, p.get('section', '') + ' · ', shown) for p in result['passages']]
    return ''.join(parts)


def _step_html(number, step, shown):
    args = ', '.join(f'{k}={json.dumps(v)}' for k, v in (step['arguments'] or {}).items())
    raw = json.dumps(step['result'], indent=2, default=str)
    return (f'<div class="card" id="step-{number}"><span class="tag">step {number}</span>'
            f'<strong>{_esc(step["tool"])}</strong> <code>{_esc(args)}</code>'
            f'{_result_html(step, shown)}'
            f'<details><summary>raw tool result</summary><pre>{_esc(raw)}</pre></details></div>')


def _chips(ev):
    words = {'number': 'numbers traced', 'quote': 'quotes verified', 'citation': 'citations found'}
    chips = []
    for kind, counts in ev['checked'].items():
        if counts['total']:
            css = 'ok' if counts['ok'] == counts['total'] else 'bad'
            chips.append(f'<span class="chip {css}">{counts["ok"]}/{counts["total"]} {words[kind]}</span>')
    if ev['stopped'] != 'answered':
        chips.append(f'<span class="chip bad">{_esc(ev["stopped"])}</span>')
    chips.append(f'<span class="chip">{len(ev["steps"])} tool calls · {ev["model_calls"]} model calls · '
                 f'{ev["tokens"]:,} tokens</span>')
    return f'<div class="chips">{"".join(chips)}</div>'


def _drafts_html(drafts):
    if not drafts:
        return ''
    items = ''.join(
        f'<p class="soft">Flagged: {_esc(", ".join(d["untraced"] + d.get("ungrounded", [])))}</p>'
        f'<pre>{_esc(d["answer"])}</pre>' for d in drafts)
    return (f'<details class="card"><summary>The guardrail sent {len(drafts)} draft(s) back '
            f'before this answer</summary>{items}</details>')


ASK_FORM = ('<form method="post" action="/ask"><textarea name="question" required '
            'placeholder="e.g. What was Apple\'s gross margin in fiscal 2023?">{question}</textarea>'
            '<button>Ask</button></form>')
REPORT_FORM = ('<form method="get" action="/report"><label>Tickers<input name="tickers" required '
               'value="{tickers}" placeholder="AAPL MSFT GOOGL"></label><label>Fiscal year'
               '<input name="year" type="number" required value="{year}" style="width:7em"></label>'
               '<button>Compare</button></form>')


def evidence_page(ev):
    """One run: answer with marks on the left, the tool trail on the right."""
    shown = set()
    steps = ''.join(_step_html(n, s, shown) for n, s in enumerate(ev['steps'], 1))
    return _layout('Evidence · ' + ev['question'][:60], (
        f'<p class="soft"><a href="/">← New question</a></p><h1>{_esc(ev["question"])}</h1>{_chips(ev)}'
        f'<div class="cols"><section><div class="card"><h2>Answer</h2>'
        f'{answer_html(ev["answer"], ev["marks"])}</div>{_drafts_html(ev["drafts"])}'
        f'<p class="soft">Highlighted text is checked against the tool results: green links jump to '
        f'the evidence, red has none. Not investment advice.</p></section>'
        f'<section><h2>Research trail</h2>{steps or "<p class=soft>No tool was called.</p>"}'
        f'</section></div>'))


def _report_cell(cell):
    if 'error' in cell:
        return f'<td class="num soft" title="{_esc(cell["error"])}">n/a</td>'
    text = _esc(report.format_value(cell))
    if 'expression' in cell:
        return f'<td class="num" title="{_esc(cell["expression"])} = {cell["value"]:.4f}">{text}</td>'
    title = f'{cell.get("period_start") or ""} → {cell["period_end"]}'
    return f'<td class="num"><a href="{_esc(cell["source"])}" title="{_esc(title)}">{text}</a></td>'


def report_page(rep):
    """A comparison report: reported cells link to the filing, derived cells
    show their calculator expression on hover and in the list below."""
    head = ''.join(f'<th class="num">{_esc(c["label"])}</th>' for c in rep['columns'])
    rows, notes = [], []
    for row in rep['rows']:
        if 'error' in row:
            rows.append(f'<tr><td>{_esc(row["ticker"])}</td><td colspan="{len(rep["columns"]) + 1}" '
                        f'class="bad">{_esc(row["error"])}</td></tr>')
            continue
        rows.append(f'<tr><td>{_esc(str(row["company"]))} ({_esc(row["ticker"])})</td>'
                    f'<td>{_esc(row["period_end"] or "n/a")}</td>'
                    + ''.join(_report_cell(row['cells'][c['key']]) for c in rep['columns']) + '</tr>')
        for column in rep['columns']:
            cell = row['cells'][column['key']]
            label = f'{row["ticker"]} {column["label"].lower()}'
            if 'expression' in cell:
                notes.append(f'<li>{_esc(label)}: <code>{_esc(cell["expression"])}</code> = {cell["value"]:.4f}</li>')
            elif 'error' in cell:
                notes.append(f'<li class="soft">{_esc(label)}: {_esc(cell["error"])}</li>')
    tickers = ' '.join(r['ticker'] for r in rep['rows'])
    return _layout(f'Fiscal {rep["year"]} comparison', (
        f'<p class="soft"><a href="/">← Home</a></p><h1>Fiscal {rep["year"]} comparison</h1>'
        f'<p class="soft">Reported figures link to the 10-K they come from. Derived figures are '
        f'computed by the calculator; the expressions are listed below. Fiscal year = the calendar '
        f'year the period ends in.</p>'
        f'<div class="card scroll"><table><tr><th>Company</th><th>Period end</th>{head}</tr>'
        f'{"".join(rows)}</table></div>'
        f'<div class="card"><h2>Calculations and gaps</h2><ul>{"".join(notes)}</ul></div>'
        f'<div class="card">{REPORT_FORM.format(tickers=_esc(tickers), year=rep["year"])}</div>'))


def home_page(error=''):
    return _layout('Financial Research Agent', (
        '<h1>Financial Research Agent</h1><p class="soft">Answers from SEC filings, with the '
        'evidence behind every number and quote. Not investment advice.</p>'
        + (f'<p class="bad">{_esc(error)}</p>' if error else '')
        + f'<div class="card"><h2>Ask a question</h2>{ASK_FORM.format(question="")}'
          '<p class="soft">A run takes 10–60 seconds and uses your API key.</p></div>'
        + f'<div class="card"><h2>Compare companies</h2>{REPORT_FORM.format(tickers="", year="")}'
          '<p class="soft">Built straight from SEC data, without the model.</p></div>'))
