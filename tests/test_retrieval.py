"""Ranking and disclosure-diff tests on made-up passages — no network."""
import pytest

from finagent import edgar, filings, retrieval, tools


def _p(pid, text):
    return {'id': pid, 'text': text}


RISK_2023 = [
    _p('EX-2023-1A-p001', 'The Company depends on a single supplier in Asia for its main component.'),
    _p('EX-2023-1A-p002', 'Tariffs and other trade measures could raise costs and reduce demand.'),
    _p('EX-2023-1A-p003', 'A pandemic could close the stores and offices the Company operates.'),
]
RISK_2024 = [
    _p('EX-2024-1A-p001', 'The Company depends on a single supplier in Asia for its main component.'),
    _p('EX-2024-1A-p002', 'Tariffs, export controls and other trade measures could raise costs and reduce demand.'),
    _p('EX-2024-1A-p003', 'Artificial intelligence features may produce inaccurate or harmful output.'),
]
BUSINESS = [_p('EX-2024-1-p001', 'The Company designs and sells widgets through its own stores.')]


def _filing(year, risk):
    return {'ticker': 'EX', 'company': 'Example Corp', 'fiscal_year': year,
            'period_end': f'{year}-12-31', 'filed': f'{year + 1}-02-01',
            'source': f'https://sec.example/{year}.htm', 'text': '',
            'sections': {'1': BUSINESS, '1A': risk, '7': []}}


@pytest.fixture(autouse=True)
def fake_filings(monkeypatch):
    by_year = {2023: _filing(2023, RISK_2023), 2024: _filing(2024, RISK_2024)}

    def load(ticker, year):
        if year not in by_year:
            raise edgar.EdgarError(f'no 10-K found for fiscal year {year}')
        return by_year[year]
    monkeypatch.setattr(filings, 'load', load)


def test_rank_puts_the_passage_sharing_rare_words_first():
    texts = [p['text'] for p in RISK_2024]
    assert retrieval.rank('artificial intelligence risk', texts)[0] == 2


def test_rank_matches_plural_and_singular():
    assert retrieval.rank('suppliers', [p['text'] for p in RISK_2023]) == [0]


def test_rank_returns_nothing_when_no_word_matches():
    assert retrieval.rank('cryptocurrency', [p['text'] for p in RISK_2023]) == []


def test_search_returns_cited_passages_with_filing_source():
    found = retrieval.search_filing('EX', 2024, 'trade tariffs export controls', '1A')
    assert found['passages'][0] == {**RISK_2024[1], 'section': 'Risk Factors'}
    assert found['source'] == 'https://sec.example/2024.htm' and found['fiscal_year'] == 2024


def test_search_without_a_section_covers_all_sections():
    found = retrieval.search_filing('EX', 2024, 'stores widgets')
    assert found['passages'][0]['id'] == 'EX-2024-1-p001'
    assert found['passages'][0]['section'] == 'Business'


def test_search_unknown_section_is_an_error():
    with pytest.raises(edgar.EdgarError, match="unknown section '9'"):
        retrieval.search_filing('EX', 2024, 'anything', '9')


def test_diff_sorts_passages_into_unchanged_revised_added_removed():
    changes = retrieval.diff(RISK_2023, RISK_2024)
    assert changes['unchanged'] == 1
    assert changes['revised'] == [(RISK_2024[1], RISK_2023[1])]
    assert changes['added'] == [RISK_2024[2]]
    assert changes['removed'] == [RISK_2023[2]]


def test_diff_of_identical_sections_reports_no_changes():
    changes = retrieval.diff(RISK_2023, RISK_2023)
    assert changes == {'added': [], 'removed': [], 'revised': [], 'unchanged': 3}


def test_diff_against_an_empty_year_is_all_added():
    assert retrieval.diff([], RISK_2024)['added'] == RISK_2024


def test_compare_filings_reports_counts_passages_and_both_sources():
    result = retrieval.compare_filings('EX', '1A', 2023, 2024)
    assert (result['unchanged_count'], result['added_count'],
            result['removed_count'], result['revised_count']) == (1, 1, 1, 1)
    assert result['added'] == [RISK_2024[2]]
    assert result['revised'] == [{'new': RISK_2024[1], 'old': RISK_2023[1]}]
    assert result['from']['source'].endswith('2023.htm') and result['to']['source'].endswith('2024.htm')


def test_compare_filings_query_filters_the_listed_passages_not_the_counts():
    result = retrieval.compare_filings('EX', '1A', 2023, 2024, query='pandemic')
    assert result['added'] == [] and result['removed'] == [RISK_2023[2]]
    assert result['added_count'] == 1


def test_compare_filings_missing_section_is_an_error():
    with pytest.raises(edgar.EdgarError, match='section 7 not found'):
        retrieval.compare_filings('EX', '7', 2023, 2024)


def test_tool_returns_errors_instead_of_raising():
    assert tools.run_tool('search_filing', {'ticker': 'EX', 'year': 2020, 'query': 'x'}) == {
        'error': 'no 10-K found for fiscal year 2020'}
    assert tools.run_tool('search_filing', {'ticker': 'EX', 'year': 2024, 'query': 'cryptocurrency'}) == {
        'error': "no passage matches 'cryptocurrency'"}
    assert tools.run_tool('compare_filings', {'ticker': 'EX', 'section': '1A', 'from_year': 2023}) == {
        'error': "missing argument 'to_year'"}


def test_tool_search_result_reaches_the_model_shape():
    found = tools.run_tool('search_filing', {'ticker': 'EX', 'year': 2023, 'query': 'supplier', 'section': '1A'})
    assert [p['id'] for p in found['passages']] == ['EX-2023-1A-p001']
