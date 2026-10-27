from finagent import edgar

# Synthetic companyfacts payload (numbers are made up), shaped like the real API.
FACTS = {
    'cik': 1234,
    'entityName': 'Example Corp',
    'facts': {'us-gaap': {
        'SalesRevenueNet': {'units': {'USD': [
            # Old concept, FY2017 — only source for that year.
            {'start': '2016-10-01', 'end': '2017-09-30', 'val': 90, 'accn': '0000-17-000001',
             'fy': 2017, 'fp': 'FY', 'form': '10-K', 'filed': '2017-11-01'},
            # Old concept also reports 2018, but the newer concept wins.
            {'start': '2017-10-01', 'end': '2018-09-30', 'val': 999, 'accn': '0000-18-000001',
             'fy': 2018, 'fp': 'FY', 'form': '10-K', 'filed': '2018-11-01'},
        ]}},
        'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': [
            {'start': '2017-10-01', 'end': '2018-09-30', 'val': 100, 'accn': '0000-18-000002',
             'fy': 2018, 'fp': 'FY', 'form': '10-K', 'filed': '2018-11-01'},
            # Same period repeated in the next 10-K, restated — latest filing wins.
            {'start': '2017-10-01', 'end': '2018-09-30', 'val': 101, 'accn': '0000-19-000001',
             'fy': 2019, 'fp': 'FY', 'form': '10-K', 'filed': '2019-11-01'},
            {'start': '2018-10-01', 'end': '2019-09-28', 'val': 120, 'accn': '0000-19-000001',
             'fy': 2019, 'fp': 'FY', 'form': '10-K', 'filed': '2019-11-01'},
            # A quarter inside a 10-K, and a 10-Q: both must be ignored.
            {'start': '2019-07-01', 'end': '2019-09-28', 'val': 30, 'accn': '0000-19-000001',
             'fy': 2019, 'fp': 'FY', 'form': '10-K', 'filed': '2019-11-01'},
            {'start': '2019-10-01', 'end': '2020-09-30', 'val': 7, 'accn': '0000-20-000009',
             'fy': 2020, 'fp': 'Q3', 'form': '10-Q', 'filed': '2020-08-01'},
        ]}},
        'Assets': {'units': {'USD': [
            {'end': '2019-09-28', 'val': 500, 'accn': '0000-19-000001',
             'fy': 2019, 'fp': 'FY', 'form': '10-K', 'filed': '2019-11-01'},
        ]}},
        'EarningsPerShareDiluted': {'units': {'USD/shares': [
            {'start': '2018-10-01', 'end': '2019-09-28', 'val': 2.5, 'accn': '0000-19-000001',
             'fy': 2019, 'fp': 'FY', 'form': '10-K', 'filed': '2019-11-01'},
        ]}},
    }},
}


def test_revenue_merges_concepts_and_takes_latest_filing():
    values = edgar.annual_values(FACTS, 'revenue')
    assert {y: v['value'] for y, v in values.items()} == {2017: 90, 2018: 101, 2019: 120}
    assert values[2018]['concept'] == 'RevenueFromContractWithCustomerExcludingAssessedTax'
    assert values[2018]['source'] == 'https://www.sec.gov/Archives/edgar/data/1234/000019000001/'


def test_balance_sheet_metric_uses_instant_values():
    values = edgar.annual_values(FACTS, 'total_assets')
    assert values[2019]['value'] == 500
    assert values[2019]['period_start'] is None


def test_per_share_unit():
    values = edgar.annual_values(FACTS, 'eps_diluted')
    assert values[2019]['value'] == 2.5
    assert values[2019]['unit'] == 'USD/shares'


def test_unknown_metric_is_an_error():
    try:
        edgar.annual_values(FACTS, 'ebitda')
    except edgar.EdgarError as exc:
        assert 'unknown metric' in str(exc)
    else:
        raise AssertionError('expected EdgarError')


def test_lookup_prefers_exact_ticker(monkeypatch):
    tickers = {
        '0': {'cik_str': 1, 'ticker': 'APLE', 'title': 'Apple Hospitality REIT'},
        '1': {'cik_str': 2, 'ticker': 'AAPL', 'title': 'Apple Inc.'},
    }
    monkeypatch.setattr(edgar, '_get_json', lambda url, name: tickers)
    assert edgar.lookup_company('aapl')[0]['name'] == 'Apple Inc.'
    assert [m['ticker'] for m in edgar.lookup_company('apple')] == ['APLE', 'AAPL']
