"""UI routing tests: the model and EDGAR are faked, no socket is opened."""
from finagent import agent, report, ui
from finagent.agent import AgentResult


def test_home_page_has_both_forms():
    status, page = ui.respond('GET', '/', {})
    assert status == 200 and 'action="/ask"' in page and 'action="/report"' in page


def test_ask_runs_the_agent_and_shows_the_evidence(monkeypatch):
    asked = []
    monkeypatch.setattr(agent, 'run', lambda q: asked.append(q) or AgentResult(answer='No data.'))
    status, page = ui.respond('POST', '/ask', {'question': '  Apple revenue?  '})
    assert status == 200 and asked == ['Apple revenue?']
    assert '<h1>Apple revenue?</h1>' in page and 'No data.' in page


def test_ask_must_be_a_post_so_a_link_cannot_spend_the_api_key(monkeypatch):
    monkeypatch.setattr(agent, 'run', lambda q: 1 / 0)
    assert ui.respond('GET', '/ask', {'question': 'Apple revenue?'})[0] == 404


def test_empty_question_is_not_sent_to_the_model(monkeypatch):
    monkeypatch.setattr(agent, 'run', lambda q: 1 / 0)
    assert ui.respond('POST', '/ask', {'question': '   '})[0] == 404


def test_agent_failure_is_shown_not_raised(monkeypatch):
    def boom(question):
        raise RuntimeError('no API key')
    monkeypatch.setattr(agent, 'run', boom)
    status, page = ui.respond('POST', '/ask', {'question': 'Apple revenue?'})
    assert status == 500 and 'RuntimeError: no API key' in page


def test_report_page_links_sources_and_shows_expressions(monkeypatch):
    built = []
    cell = {'value': 1_000_000_000, 'unit': 'USD', 'period_start': '2023-01-01',
            'period_end': '2023-12-31', 'source': 'https://www.sec.gov/f/'}
    rep = {'year': 2023,
           'columns': [{'key': 'revenue', 'label': 'Revenue'}, {'key': 'net_margin', 'label': 'Net margin'},
                       {'key': 'gross_margin', 'label': 'Gross margin'}],
           'rows': [{'ticker': 'AAA', 'company': 'Alpha', 'period_end': '2023-12-31', 'cells': {
                        'revenue': cell,
                        'net_margin': {'value': 20.0, 'unit': '%', 'expression': '2 / 10 * 100'},
                        'gross_margin': {'error': 'no gross_profit reported for fiscal 2023'}}},
                    {'ticker': 'ZZZ', 'error': 'unknown ticker: ZZZ'}]}
    monkeypatch.setattr(report, 'build', lambda tickers, year: built.append((tickers, year)) or rep)
    status, page = ui.respond('GET', '/report', {'tickers': 'aaa, zzz', 'year': '2023'})
    assert status == 200 and built == [(['aaa', 'zzz'], 2023)]
    assert '<a href="https://www.sec.gov/f/" title="2023-01-01 → 2023-12-31">$1.00B</a>' in page
    assert 'title="2 / 10 * 100 = 20.0000">20.0%</td>' in page
    assert 'title="no gross_profit reported for fiscal 2023">n/a</td>' in page
    assert 'unknown ticker: ZZZ' in page


def test_report_with_a_bad_year_is_an_error_page():
    status, page = ui.respond('GET', '/report', {'tickers': 'AAA', 'year': 'soon'})
    assert status == 500 and 'ValueError' in page


def test_unknown_path_is_404():
    assert ui.respond('GET', '/admin', {})[0] == 404
