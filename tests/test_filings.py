"""10-K text tests on a small made-up filing — no network."""
import pytest

from finagent import edgar, filings

HTML = """
<html><head><title>10-K</title><style>p {color: red}</style></head><body>
<ix:header><ix:hidden>0000001234 hidden xbrl facts that are not part of the visible document</ix:hidden></ix:header>
<table><tr><td>Item 1.</td><td>Business</td><td>1</td></tr>
<tr><td>Item 1A.</td><td>Risk Factors</td><td>5</td></tr>
<tr><td>Item 7.</td><td>Management&#8217;s Discussion</td><td>20</td></tr></table>
<div>Item 1. Business</div>
<div>Example Corp designs and sells widgets to customers in more than forty countries around the world.</div>
<div>Products</div>
<div>Item 1A. Risk Factors</div>
<div>Supply Chain Risks</div>
<div>The Company depends on a single supplier in Asia for the main component of its widgets.</div>
<div>Example Corp | 2023 Form 10-K | 6</div>
<div>Item 1A</div>
<div>Tariffs&nbsp;and other trade measures could raise the Company&#8217;s costs   and reduce
demand for its widgets.</div>
<table><tr><td>Americas</td><td>$ 1,200</td><td>5 %</td><td>$ 1,100</td><td>4 %</td><td>$ 1,000</td><td>3 %</td><td>900</td></tr></table>
<div>Item 1B. Unresolved Staff Comments</div>
<div>None.</div>
<div>Item 7. Management's Discussion and Analysis</div>
<div>See the discussion under Item 7 of last year's report for comparisons with the earlier period.</div>
<div>Item 7 of this report continues with a discussion of liquidity and capital resources for the year.</div>
<div>Item 8. Financial Statements</div>
</body></html>
"""


def _texts(html, item):
    return filings.passages(filings.split_sections(filings.to_lines(html))[item])


def test_hidden_xbrl_and_styles_are_not_text():
    text = ' '.join(filings.to_lines(HTML))
    assert 'hidden xbrl' not in text and 'color: red' not in text


def test_section_body_is_found_past_the_table_of_contents():
    assert _texts(HTML, '1') == [
        'Example Corp designs and sells widgets to customers in more than forty countries around the world.']


def test_repeated_page_header_does_not_end_the_section():
    risk = _texts(HTML, '1A')
    assert len(risk) == 2
    assert risk[1] == ('Tariffs and other trade measures could raise the Company’s costs and reduce '
                       'demand for its widgets.')


def test_table_rows_footers_and_subheadings_are_dropped():
    risk = ' '.join(_texts(HTML, '1A'))
    assert 'Americas' not in risk and 'Form 10-K' not in risk and 'Supply Chain Risks' not in risk


def test_cross_reference_at_line_start_is_not_a_heading():
    assert len(_texts(HTML, '7')) == 2


def test_long_paragraph_is_cut_at_sentence_ends():
    sentence = 'The Company faces risks that could harm its results in many different ways. '
    chunks = filings.passages([sentence * 40])
    assert len(chunks) > 1
    assert all(len(c) <= filings.MAX_PASSAGE_CHARS and c.endswith('ways.') for c in chunks)
    assert ' '.join(chunks) == (sentence * 40).strip()


INDEX = {'name': 'Example Corp', 'filings': {
    'recent': {'form': ['8-K', '10-K', '10-Q'], 'reportDate': ['2024-01-05', '2023-12-31', '2023-09-30'],
               'accessionNumber': ['0000-24-000002', '0000-24-000001', '0000-23-000009'],
               'primaryDocument': ['a.htm', 'ex-20231231.htm', 'q.htm'],
               'filingDate': ['2024-01-06', '2024-02-01', '2023-10-20']},
    'files': [{'name': 'CIK0000001234-submissions-001.json'}]}}
OLDER = {'form': ['10-K'], 'reportDate': ['2019-12-31'], 'accessionNumber': ['0000-20-000001'],
         'primaryDocument': ['ex-20191231.htm'], 'filingDate': ['2020-02-01']}


@pytest.fixture
def fake_sec(monkeypatch, tmp_path):
    fetched = []
    monkeypatch.setattr(edgar, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(edgar, 'resolve_cik', lambda ticker: 1234)
    monkeypatch.setattr(edgar, '_get_json', lambda url, name: OLDER if 'submissions-001' in url else INDEX)

    def fetch(url):
        fetched.append(url)
        return type('Response', (), {'text': HTML})()
    monkeypatch.setattr(edgar, 'fetch', fetch)
    return fetched


def test_find_10k_picks_the_annual_report_for_the_year(fake_sec):
    found = filings.find_10k(1234, 2023)
    assert found == {'company': 'Example Corp', 'period_end': '2023-12-31', 'filed': '2024-02-01',
                     'source': 'https://www.sec.gov/Archives/edgar/data/1234/000024000001/ex-20231231.htm'}


def test_find_10k_looks_in_older_index_pages(fake_sec):
    assert filings.find_10k(1234, 2019)['period_end'] == '2019-12-31'


def test_find_10k_missing_year_is_an_error(fake_sec):
    with pytest.raises(edgar.EdgarError, match='no 10-K found for fiscal year 2021'):
        filings.find_10k(1234, 2021)


def test_load_numbers_passages_and_keeps_the_full_text(fake_sec):
    filing = filings.load('exmp', 2023)
    assert [p['id'] for p in filing['sections']['1A']] == ['EXMP-2023-1A-p001', 'EXMP-2023-1A-p002']
    assert filing['fiscal_year'] == 2023 and filing['company'] == 'Example Corp'
    assert 'Unresolved Staff Comments' in filing['text']


def test_load_is_cached_after_the_first_download(fake_sec):
    assert filings.load('EXMP', 2023) == filings.load('EXMP', 2023)
    assert len(fake_sec) == 1


def test_missing_section_error_names_what_is_available(fake_sec):
    filing = filings.load('EXMP', 2023)
    filing['sections']['7'] = []
    with pytest.raises(edgar.EdgarError, match=r"section 7 not found.*available: \['1', '1A'\]"):
        filings.section(filing, '7')
