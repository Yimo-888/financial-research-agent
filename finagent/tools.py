"""
The tools the model may call: their JSON schemas (what the model sees) and
one dispatcher (what actually runs). A tool never raises into the agent loop
— failures come back as {"error": ...} so the model can try something else.
"""
from . import edgar, filings, retrieval
from .calculator import CalculatorError, calculate

TEXT_TOOLS = {'search_filing', 'compare_filings'}
_SECTION = {'type': 'string', 'enum': sorted(filings.SECTIONS),
            'description': '1 = Business, 1A = Risk Factors, 7 = Management\'s Discussion and Analysis'}

TOOL_SPECS = [
    {
        'name': 'lookup_company',
        'description': 'Find a US-listed company by ticker or by part of its name. '
                       'Returns ticker, SEC CIK number and official name.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Ticker (e.g. "AAPL") or name (e.g. "apple")'},
            },
            'required': ['query'],
        },
    },
    {
        'name': 'get_financials',
        'description': 'Annual values of one financial metric from the company\'s 10-K '
                       'filings at the SEC, with the exact reporting period and a source '
                       'link for each year. fiscal_year is the calendar year the period ends in.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'ticker': {'type': 'string'},
                'metric': {'type': 'string', 'enum': sorted(edgar.METRICS)},
                'start_year': {'type': 'integer'},
                'end_year': {'type': 'integer'},
            },
            'required': ['ticker', 'metric'],
        },
    },
    {
        'name': 'calculate',
        'description': 'Evaluate an arithmetic expression (numbers, + - * / ** and '
                       'parentheses). Use it for EVERY derived number: margins, growth '
                       'rates, differences, unit conversions.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'expression': {'type': 'string', 'description': 'e.g. "(383285000000 - 394328000000) / 394328000000 * 100"'},
            },
            'required': ['expression'],
        },
    },
    {
        'name': 'search_filing',
        'description': 'Search the text of a company\'s 10-K for one fiscal year and return '
                       'the best-matching passages, each with an id to cite. Use it for what '
                       'the company SAYS (risks, business, strategy, explanations) — not for '
                       'financial figures, which come from get_financials.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'ticker': {'type': 'string'},
                'year': {'type': 'integer', 'description': 'Calendar year the fiscal period ends in'},
                'query': {'type': 'string', 'description': 'Words likely to appear in the passage, '
                                                           'e.g. "supply chain single-source suppliers"'},
                'section': {**_SECTION, 'description': _SECTION['description'] + '. Omit to search all three.'},
            },
            'required': ['ticker', 'year', 'query'],
        },
    },
    {
        'name': 'compare_filings',
        'description': 'What changed in one 10-K section between two fiscal years: counts of '
                       'unchanged, added, removed and revised passages, and the passages '
                       'themselves (revised ones as new/old pairs). Give a query to focus on a topic.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'ticker': {'type': 'string'},
                'section': _SECTION,
                'from_year': {'type': 'integer'},
                'to_year': {'type': 'integer'},
                'query': {'type': 'string', 'description': 'Optional topic, e.g. "artificial intelligence"'},
            },
            'required': ['ticker', 'section', 'from_year', 'to_year'],
        },
    },
]


def run_tool(name, args):
    """Run one tool call. `args` is the tool_use block's input dict."""
    args = args or {}
    try:
        if name == 'lookup_company':
            matches = edgar.lookup_company(args['query'])
            return {'matches': matches} if matches else {'error': f'no company matches {args["query"]!r}'}
        if name == 'get_financials':
            return edgar.get_financials(args['ticker'], args['metric'],
                                        args.get('start_year'), args.get('end_year'))
        if name == 'calculate':
            return {'expression': args['expression'], 'result': calculate(args['expression'])}
        if name == 'search_filing':
            found = retrieval.search_filing(args['ticker'], args['year'], args['query'], args.get('section'))
            return found if found['passages'] else {'error': f'no passage matches {args["query"]!r}'}
        if name == 'compare_filings':
            return retrieval.compare_filings(args['ticker'], args['section'], args['from_year'],
                                             args['to_year'], args.get('query'))
    except KeyError as exc:
        return {'error': f'missing argument {exc}'}
    except (edgar.EdgarError, CalculatorError) as exc:
        return {'error': str(exc)}
    except Exception as exc:          # network trouble etc. — let the model decide
        return {'error': f'{type(exc).__name__}: {exc}'}
    return {'error': f'unknown tool {name!r}'}
