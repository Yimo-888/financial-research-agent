"""Comparison report tests on made-up companyfacts payloads — no network."""
import pytest

from finagent import edgar, report


def _fact(year, val, instant=False):
    fact = {'end': f'{year}-12-31', 'val': val, 'accn': f'0000-{year % 100}-000001',
            'fy': year, 'fp': 'FY', 'form': '10-K', 'filed': f'{year + 1}-02-01'}
    return fact if instant else {'start': f'{year}-01-01', **fact}


def _facts(cik, name, **series):
    """series: XBRL concept -> {year: value}."""
    return {'cik': cik, 'entityName': name, 'facts': {'us-gaap': {
        concept: {'units': {'USD': [_fact(y, v) for y, v in by_year.items()]}}
        for concept, by_year in series.items()}}}


COMPANIES = {
    'AAA': _facts(1, 'Alpha Inc.', Revenues={2022: 800_000_000, 2023: 1_000_000_000},
                  GrossProfit={2023: 400_000_000}, OperatingIncomeLoss={2023: 250_000_000},
                  NetIncomeLoss={2023: 200_000_000}),
    # No gross profit and no prior-year revenue; a net loss.
    'BBB': _facts(2, 'Beta Corp', Revenues={2023: 50_000_000},
                  OperatingIncomeLoss={2023: -5_000_000}, NetIncomeLoss={2023: -10_000_000}),
}


@pytest.fixture(autouse=True)
def fake_edgar(monkeypatch):
    def resolve(ticker):
        if ticker.upper() not in COMPANIES:
            raise edgar.EdgarError(f'unknown ticker: {ticker}')
        return ticker.upper()
    monkeypatch.setattr(edgar, 'resolve_cik', resolve)
    monkeypatch.setattr(edgar, 'company_facts', lambda cik: COMPANIES[cik])


def _cells(rep, ticker):
    return next(r for r in rep['rows'] if r['ticker'] == ticker)['cells']


def test_reported_cell_keeps_period_and_source():
    cell = _cells(report.build(['AAA'], 2023), 'AAA')['revenue']
    assert cell == {'value': 1_000_000_000, 'unit': 'USD', 'period_start': '2023-01-01',
                    'period_end': '2023-12-31',
                    'source': 'https://www.sec.gov/Archives/edgar/data/1/000023000001/'}


def test_derived_cell_carries_the_expression_the_calculator_ran():
    cells = _cells(report.build(['AAA'], 2023), 'AAA')
    assert cells['gross_margin']['expression'] == '400000000 / 1000000000 * 100'
    assert cells['gross_margin']['value'] == 40
    assert cells['revenue_growth']['expression'] == '(1000000000 - 800000000) / 800000000 * 100'
    assert cells['revenue_growth']['value'] == 25


def test_derived_values_go_through_the_calculator(monkeypatch):
    seen = []
    monkeypatch.setattr(report, 'calculate', lambda e: seen.append(e) or 1.0)
    report.build(['AAA'], 2023, ['net_margin'])
    assert seen == ['200000000 / 1000000000 * 100']


def test_derived_cell_lists_the_filings_behind_its_inputs():
    growth = _cells(report.build(['AAA'], 2023), 'AAA')['revenue_growth']
    assert growth['sources'] == ['https://www.sec.gov/Archives/edgar/data/1/000022000001/',
                                 'https://www.sec.gov/Archives/edgar/data/1/000023000001/']


def test_missing_input_makes_the_cell_an_error_not_a_number():
    cells = _cells(report.build(['BBB'], 2023), 'BBB')
    assert cells['gross_margin'] == {'error': 'no gross_profit reported for fiscal 2023'}
    assert cells['revenue_growth'] == {'error': 'no revenue reported for fiscal 2022'}
    assert cells['net_margin']['value'] == -20


def test_unknown_ticker_becomes_an_error_row_and_the_rest_still_builds():
    rep = report.build(['AAA', 'ZZZ'], 2023)
    assert rep['rows'][1] == {'ticker': 'ZZZ', 'error': 'unknown ticker: ZZZ'}
    assert 'cells' in rep['rows'][0]


def test_division_by_zero_is_reported_in_the_cell(monkeypatch):
    monkeypatch.setitem(COMPANIES, 'CCC', _facts(3, 'Gamma', Revenues={2023: 0}, NetIncomeLoss={2023: 5}))
    cell = _cells(report.build(['CCC'], 2023, ['net_margin']), 'CCC')['net_margin']
    assert cell == {'error': 'division by zero in 5 / 0 * 100'}


def test_unknown_column_is_rejected():
    with pytest.raises(ValueError, match='ebitda'):
        report.build(['AAA'], 2023, ['ebitda'])


@pytest.mark.parametrize('cell, text', [
    ({'value': 383_285_000_000, 'unit': 'USD'}, '$383.29B'),
    ({'value': -10_000_000, 'unit': 'USD'}, '-$10.00M'),
    ({'value': 6.13, 'unit': 'USD/shares'}, '$6.13'),
    ({'value': 44.1311, 'unit': '%'}, '44.1%'),
])
def test_format_value(cell, text):
    assert report.format_value(cell) == text


def test_markdown_has_table_sources_calculations_and_gaps():
    text = report.render_markdown(report.build(['AAA', 'BBB', 'ZZZ'], 2023))
    assert '| Alpha Inc. (AAA) | 2023-12-31 | $1.00B [1] | $250.00M [1] | $200.00M [1] | 25.0% | 40.0% | 25.0% | 20.0% |' in text
    assert '| Beta Corp (BBB) | 2023-12-31 | $50.00M [2] | -$5.00M [2] | -$10.00M [2] | n/a | n/a | -10.0% | -20.0% |' in text
    assert '- [1] https://www.sec.gov/Archives/edgar/data/1/000023000001/' in text
    assert '- AAA gross margin: `400000000 / 1000000000 * 100` = 40.0000' in text
    assert '- BBB gross margin: no gross_profit reported for fiscal 2023' in text
    assert '- ZZZ: unknown ticker: ZZZ' in text
