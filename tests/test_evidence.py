"""Evidence linking and page rendering tests — no network, no model."""
from finagent import evidence, pages
from finagent.agent import AgentResult

STEPS = [
    {'tool': 'get_financials', 'arguments': {'ticker': 'AAPL', 'metric': 'revenue'},
     'result': {'company': 'Apple Inc.', 'metric': 'revenue', 'values': [
         {'fiscal_year': 2023, 'value': 383285000000, 'unit': 'USD', 'period_start': '2022-09-25',
          'period_end': '2023-09-30', 'source': 'https://www.sec.gov/Archives/edgar/data/1/2/'}]}},
    {'tool': 'calculate', 'arguments': {'expression': '169148000000 / 383285000000 * 100'},
     'result': {'expression': '169148000000 / 383285000000 * 100', 'result': 44.1311}},
    {'tool': 'search_filing', 'arguments': {'ticker': 'AAPL', 'year': 2023, 'query': 'supply'},
     'result': {'company': 'Apple Inc.', 'fiscal_year': 2023, 'source': 'https://www.sec.gov/x.htm',
                'passages': [{'id': 'AAPL-2023-1A-p007', 'section': 'Risk Factors',
                              'text': 'The Company depends on outsourcing partners located in Asia.'}]}},
]
ANSWER = ('Revenue was **$383.3 billion** and gross margin 44.1%, though some say 52%.\n'
          'Apple "depends on outsourcing partners located in Asia" [AAPL-2023-1A-p007], '
          'not on "a single factory in one country" [AAPL-2023-1A-p099].')


def _marks():
    return {ANSWER[m['start']:m['end']]: m for m in evidence.marks(ANSWER, STEPS)}


def test_number_is_linked_to_the_step_that_produced_it():
    marks = _marks()
    assert marks['$383.3 billion']['step'] == 0 and marks['44.1%']['step'] == 1
    assert marks['44.1%']['note'] == 'traced to step 2 (calculate)'


def test_untraced_number_is_marked_bad():
    start = ANSWER.index('52%')
    assert _marks()['52%'] == {'kind': 'number', 'start': start, 'end': start + 3, 'ok': False,
                               'step': None, 'passage': None, 'note': 'not traced to any tool result'}


def test_verified_quote_and_citation_point_at_the_passage():
    marks = _marks()
    quote = marks['"depends on outsourcing partners located in Asia"']
    assert quote['ok'] and quote['passage'] == 'AAPL-2023-1A-p007' and quote['step'] == 2
    assert marks['AAPL-2023-1A-p007']['ok']


def test_unverified_quote_and_unknown_citation_are_marked_bad():
    marks = _marks()
    assert not marks['"a single factory in one country"']['ok']
    assert marks['AAPL-2023-1A-p099']['note'] == 'no tool returned this passage'


def test_marks_are_ordered_and_do_not_overlap():
    found = evidence.marks(ANSWER + ' He said "the margin was 99% last year".', STEPS)
    assert all(a['end'] <= b['start'] for a, b in zip(found, found[1:]))
    # The 99% sits inside an unverified quote: one bad mark, not two.
    assert [m['kind'] for m in found][-1] == 'quote'


def test_build_counts_what_was_checked():
    result = AgentResult(answer=ANSWER, steps=STEPS, model_calls=4, prompt_tokens=900, completion_tokens=100)
    ev = evidence.build('Apple?', result)
    assert ev['checked'] == {'number': {'ok': 2, 'total': 3}, 'quote': {'ok': 1, 'total': 2},
                             'citation': {'ok': 1, 'total': 2}}
    assert ev['tokens'] == 1000


def _page(answer=ANSWER, **kwargs):
    result = AgentResult(answer=answer, steps=STEPS, **kwargs)
    return pages.evidence_page(evidence.build('Apple <b>margins</b>?', result))


def test_page_links_traced_number_and_flags_untraced_one():
    page = _page()
    assert '<a class="mark number ok" href="#step-1" title="traced to step 1 (get_financials)">$383.3 billion</a>' in page
    assert '<span class="mark number bad" title="not traced to any tool result">52%</span>' in page
    assert '<strong><a class="mark number ok"' in page          # bold wraps the mark


def test_page_links_quote_to_a_passage_anchor_that_exists():
    page = _page()
    assert 'href="#p-AAPL-2023-1A-p007"' in page
    assert page.count('id="p-AAPL-2023-1A-p007"') == 1 and page.count('id="step-') == 3


def test_page_escapes_model_and_user_text():
    page = _page(answer='<script>alert(1)</script> Revenue was $383.3 billion.')
    assert '<script>' not in page and '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert '<h1>Apple &lt;b&gt;margins&lt;/b&gt;?</h1>' in page


def test_page_shows_drafts_the_guardrail_sent_back():
    page = _page(drafts=[{'answer': 'Revenue was $500 billion.', 'untraced': ['$500 billion'], 'ungrounded': []}])
    assert 'sent 1 draft(s) back' in page and 'Flagged: $500 billion' in page


def test_page_shows_tool_errors():
    steps = [{'tool': 'calculate', 'arguments': {'expression': '1 / 0'}, 'result': {'error': 'division by zero'}}]
    page = pages.evidence_page(evidence.build('?', AgentResult(answer='No.', steps=steps)))
    assert 'Error: division by zero' in page


def test_markdown_table_list_heading_and_links_render():
    html = pages.answer_html('## Sources\n\n- https://www.sec.gov/a/b/.\n\n| FY | Revenue |\n|---|---|\n| 2023 | big |', [])
    assert '<h3>Sources</h3>' in html
    assert '<ul><li><a href="https://www.sec.gov/a/b/" rel="noreferrer">https://www.sec.gov/a/b/</a>.</li></ul>' in html
    assert '<table><tr><th> FY </th><th> Revenue </th></tr><tr><td> 2023 </td><td> big </td></tr></table>' in html


def test_mark_inside_a_table_cell_keeps_its_position():
    answer = '| Metric | Value |\n|---|---|\n| Revenue | $383.3 billion |'
    html = pages.answer_html(answer, evidence.marks(answer, STEPS))
    assert '<td> <a class="mark number ok" href="#step-1"' in html and '$383.3 billion</a> </td>' in html
