"""
SEC EDGAR client — the agent's only source of financial numbers.

Two public endpoints, no API key:
  https://www.sec.gov/files/company_tickers.json          ticker/name -> CIK
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
                                                          every XBRL fact a
                                                          company has filed

SEC fair-access rules: every request must send a User-Agent naming you and a
contact address (SEC_USER_AGENT in .env), and stay under 10 requests/second.
Responses are cached on disk so repeated questions and eval runs don't hit
the SEC again.

Annual values come from 10-K filings only. A "fiscal year" here is the
calendar year the reporting period ENDS in — right for most companies, but a
retailer whose year ends in early February calls that year the PRIOR one, so
every value carries its exact period start/end for the agent to state.
"""
import json
import os
import time
from datetime import date
from pathlib import Path

import requests

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
FILING_URL = 'https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/'

CACHE_DIR = Path(os.environ.get('FINAGENT_CACHE_DIR', '.cache'))
MIN_REQUEST_GAP = 0.15          # seconds; keeps us well under 10 req/s

# Friendly metric name -> XBRL concepts, in priority order. Companies switch
# concepts over time (Apple reported SalesRevenueNet until 2018, then
# RevenueFromContractWithCustomerExcludingAssessedTax), so values are merged
# per period, earlier concepts winning.
METRICS = {
    'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax',
                'Revenues', 'SalesRevenueNet'],
    'cost_of_revenue': ['CostOfRevenue', 'CostOfGoodsAndServicesSold'],
    'gross_profit': ['GrossProfit'],
    'operating_income': ['OperatingIncomeLoss'],
    'net_income': ['NetIncomeLoss'],
    'eps_diluted': ['EarningsPerShareDiluted'],
    'operating_cash_flow': ['NetCashProvidedByUsedInOperatingActivities'],
    'total_assets': ['Assets'],
    'total_liabilities': ['Liabilities'],
    'stockholders_equity': ['StockholdersEquity'],
}
# Balance-sheet items are a snapshot on one date, not a flow over a year.
INSTANT_METRICS = {'total_assets', 'total_liabilities', 'stockholders_equity'}


class EdgarError(Exception):
    pass


_last_request = 0.0


def _get_json(url, cache_name):
    cached = CACHE_DIR / cache_name
    if cached.exists():
        return json.loads(cached.read_text())

    agent = os.environ.get('SEC_USER_AGENT')
    if not agent:
        raise EdgarError('SEC_USER_AGENT is not set (e.g. "Your Name you@example.com")')

    global _last_request
    wait = MIN_REQUEST_GAP - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, headers={'User-Agent': agent}, timeout=30)
    _last_request = time.monotonic()
    if resp.status_code == 404:
        raise EdgarError(f'not found: {url}')
    resp.raise_for_status()

    data = resp.json()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data))
    return data


def lookup_company(query, limit=5):
    """Exact ticker match first, then company names containing the query."""
    rows = _get_json(TICKERS_URL, 'company_tickers.json').values()
    q = query.strip().lower()
    exact = [r for r in rows if r['ticker'].lower() == q]
    by_name = [r for r in rows if q in r['title'].lower() and r not in exact]
    return [{'ticker': r['ticker'], 'cik': r['cik_str'], 'name': r['title']}
            for r in (exact + by_name)[:limit]]


def resolve_cik(ticker):
    matches = [m for m in lookup_company(ticker) if m['ticker'].lower() == ticker.lower()]
    if not matches:
        raise EdgarError(f'unknown ticker: {ticker}')
    return matches[0]['cik']


def company_facts(cik):
    return _get_json(FACTS_URL.format(cik=cik), f'facts_{cik}.json')


def _is_annual(fact, instant):
    if fact.get('form') != '10-K':
        return False
    if instant:
        return 'start' not in fact and fact.get('fp') == 'FY'
    if 'start' not in fact:
        return False
    days = (date.fromisoformat(fact['end']) - date.fromisoformat(fact['start'])).days
    return 350 <= days <= 380           # 52/53-week years are 364 or 371 days


def annual_values(facts, metric):
    """{fiscal_year: value dict} for one metric, from a companyfacts payload.

    A period appears in several 10-Ks (each filing repeats prior years as
    comparatives, and restatements change them); the most recently filed
    value wins.
    """
    if metric not in METRICS:
        raise EdgarError(f'unknown metric {metric!r}; choose from {sorted(METRICS)}')
    instant = metric in INSTANT_METRICS
    gaap = facts.get('facts', {}).get('us-gaap', {})
    cik = facts.get('cik')

    by_year = {}
    for concept in METRICS[metric]:
        units = gaap.get(concept, {}).get('units', {})
        unit = 'USD' if 'USD' in units else 'USD/shares'
        series = units.get(unit, [])
        latest = {}
        for f in series:
            if not _is_annual(f, instant):
                continue
            year = int(f['end'][:4])
            if year not in latest or f['filed'] > latest[year]['filed']:
                latest[year] = f
        for year, f in latest.items():
            if year in by_year:          # a higher-priority concept already has it
                continue
            by_year[year] = {
                'fiscal_year': year,
                'value': f['val'],
                'unit': unit,
                'period_start': f.get('start'),
                'period_end': f['end'],
                'concept': concept,
                'filed': f['filed'],
                'source': FILING_URL.format(cik=cik, accn=f['accn'].replace('-', '')),
            }
    return by_year


def get_financials(ticker, metric, start_year=None, end_year=None):
    cik = resolve_cik(ticker)
    facts = company_facts(cik)
    values = annual_values(facts, metric)
    years = sorted(y for y in values
                   if (start_year is None or y >= start_year)
                   and (end_year is None or y <= end_year))
    return {
        'company': facts.get('entityName'),
        'ticker': ticker.upper(),
        'metric': metric,
        'values': [values[y] for y in years],
    }
