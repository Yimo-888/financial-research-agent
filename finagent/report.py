"""
Comparison report: companies × metrics for one fiscal year, as a structured
table with a source link behind every figure. Built without the model, so
there is nothing to hallucinate:

    python -m finagent.report AAPL MSFT GOOGL --year 2023
    python -m finagent.report KO PEP --year 2023 --json

Reported cells come from EDGAR and keep their period and filing link. Derived
cells (margins, growth) are computed by the calculator from an expression that
stays on the cell, so a reader can redo any of them. A cell that cannot be
filled says why instead of being left blank or guessed.
"""
import argparse
import json
import re

from . import edgar
from .calculator import CalculatorError, calculate

LABELS = {
    'revenue': 'Revenue', 'cost_of_revenue': 'Cost of revenue', 'gross_profit': 'Gross profit',
    'operating_income': 'Operating income', 'net_income': 'Net income',
    'eps_diluted': 'Diluted EPS', 'operating_cash_flow': 'Operating cash flow',
    'total_assets': 'Total assets', 'total_liabilities': 'Total liabilities',
    'stockholders_equity': "Stockholders' equity",
}
# Derived column -> (label, calculator expression). {metric} is this year's
# reported value, {metric_prior} the year before.
DERIVED = {
    'revenue_growth': ('Revenue growth', '({revenue} - {revenue_prior}) / {revenue_prior} * 100'),
    'gross_margin': ('Gross margin', '{gross_profit} / {revenue} * 100'),
    'operating_margin': ('Operating margin', '{operating_income} / {revenue} * 100'),
    'net_margin': ('Net margin', '{net_income} / {revenue} * 100'),
}
DEFAULT_COLUMNS = ['revenue', 'operating_income', 'net_income',
                   'revenue_growth', 'gross_margin', 'operating_margin', 'net_margin']


def _reported(facts, name, year):
    """One reported cell. `name` is a metric, or metric_prior for the year before."""
    metric, prior = (name[:-len('_prior')], True) if name.endswith('_prior') else (name, False)
    year = year - 1 if prior else year
    value = edgar.annual_values(facts, metric).get(year)
    if value is None:
        return {'error': f'no {metric} reported for fiscal {year}'}
    return {k: value[k] for k in ('value', 'unit', 'period_start', 'period_end', 'source')}


def _derived(facts, expression, year):
    inputs = {name: _reported(facts, name, year) for name in re.findall(r'{(\w+)}', expression)}
    missing = [cell['error'] for cell in inputs.values() if 'error' in cell]
    if missing:
        return {'error': '; '.join(missing)}
    filled = expression.format(**{name: cell['value'] for name, cell in inputs.items()})
    try:
        return {'value': calculate(filled), 'unit': '%', 'expression': filled,
                'sources': sorted({cell['source'] for cell in inputs.values()})}
    except CalculatorError as exc:
        return {'error': f'{exc} in {filled}'}


def _row(ticker, year, columns):
    try:
        facts = edgar.company_facts(edgar.resolve_cik(ticker))
        cells = {c: _derived(facts, DERIVED[c][1], year) if c in DERIVED else _reported(facts, c, year)
                 for c in columns}
    except Exception as exc:          # one bad ticker must not sink the report
        return {'ticker': ticker.upper(), 'error': str(exc) or type(exc).__name__}
    ends = [cell['period_end'] for cell in cells.values() if cell.get('period_end')]
    return {'ticker': ticker.upper(), 'company': facts.get('entityName'),
            'period_end': max(ends, default=None), 'cells': cells}


def build(tickers, year, columns=None):
    """The report as plain data: {year, columns, rows}. Never raises for a
    company or a cell; unknown columns are a caller error and do raise."""
    columns = list(columns or DEFAULT_COLUMNS)
    unknown = [c for c in columns if c not in DERIVED and c not in edgar.METRICS]
    if unknown:
        raise ValueError(f'unknown columns {unknown}; choose from {sorted([*DERIVED, *edgar.METRICS])}')
    return {
        'year': year,
        'columns': [{'key': c, 'label': DERIVED[c][0] if c in DERIVED else LABELS[c]} for c in columns],
        'rows': [_row(t, year, columns) for t in tickers],
    }


def _scaled(value, divisor):
    # Display conversions are derived numbers too, so they use the calculator.
    return calculate(f'{value} / {divisor}')


def format_value(cell):
    """A cell's value as text: "$383.29B", "$6.13", "44.1%"."""
    value = cell['value']
    if cell['unit'] == '%':
        return f'{value:.1f}%'
    sign = '-' if value < 0 else ''
    for divisor, suffix in ((10**9, 'B'), (10**6, 'M')):
        if cell['unit'] == 'USD' and abs(value) >= divisor:
            return f'{sign}${abs(_scaled(value, divisor)):,.2f}{suffix}'
    return f'{sign}${abs(value):,.2f}'


def render_markdown(report):
    """Table, then numbered sources, calculations, and reasons for gaps."""
    columns = report['columns']
    lines = [f'## Fiscal {report["year"]} comparison', '',
             '| Company | Period end | ' + ' | '.join(c['label'] for c in columns) + ' |',
             '|---|---|' + '---:|' * len(columns)]
    sources, calculations, gaps = [], [], []

    def note(source):
        if source not in sources:
            sources.append(source)
        return f'[{sources.index(source) + 1}]'

    for row in report['rows']:
        if 'error' in row:
            lines.append(f'| {row["ticker"]} | n/a |' + ' n/a |' * len(columns))
            gaps.append(f'{row["ticker"]}: {row["error"]}')
            continue
        texts = []
        for column in columns:
            cell = row['cells'][column['key']]
            if 'error' in cell:
                texts.append('n/a')
                gaps.append(f'{row["ticker"]} {column["label"].lower()}: {cell["error"]}')
            elif 'expression' in cell:
                texts.append(format_value(cell))
                calculations.append(f'{row["ticker"]} {column["label"].lower()}: '
                                    f'`{cell["expression"]}` = {cell["value"]:.4f}')
            else:
                texts.append(f'{format_value(cell)} {note(cell["source"])}')
        lines.append(f'| {row["company"]} ({row["ticker"]}) | {row["period_end"] or "n/a"} | '
                     + ' | '.join(texts) + ' |')

    lines += ['', 'Fiscal year = the calendar year the period ends in; '
                  'period ends differ between companies.']
    for title, items in (('Sources (SEC 10-K filings)', [f'[{i}] {s}' for i, s in enumerate(sources, 1)]),
                         ('Calculations', calculations), ('Not available', gaps)):
        if items:
            lines += ['', f'**{title}**', ''] + [f'- {item}' for item in items]
    return '\n'.join(lines)


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(prog='finagent.report')
    parser.add_argument('tickers', nargs='+')
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--columns', nargs='+', default=None,
                        help=f'any of: {" ".join([*edgar.METRICS, *DERIVED])}')
    parser.add_argument('--json', action='store_true', help='print the structured report')
    args = parser.parse_args()
    try:
        report = build(args.tickers, args.year, args.columns)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2) if args.json else render_markdown(report))


if __name__ == '__main__':
    main()
