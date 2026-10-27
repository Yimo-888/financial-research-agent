"""
The tools the model may call: their JSON schemas (what the model sees) and
one dispatcher (what actually runs). A tool never raises into the agent loop
— failures come back as {"error": ...} so the model can try something else.
"""
import json

from . import edgar
from .calculator import CalculatorError, calculate

TOOL_SPECS = [
    {
        'type': 'function',
        'function': {
            'name': 'lookup_company',
            'description': 'Find a US-listed company by ticker or by part of its name. '
                           'Returns ticker, SEC CIK number and official name.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Ticker (e.g. "AAPL") or name (e.g. "apple")'},
                },
                'required': ['query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_financials',
            'description': 'Annual values of one financial metric from the company\'s 10-K '
                           'filings at the SEC, with the exact reporting period and a source '
                           'link for each year. fiscal_year is the calendar year the period ends in.',
            'parameters': {
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
    },
    {
        'type': 'function',
        'function': {
            'name': 'calculate',
            'description': 'Evaluate an arithmetic expression (numbers, + - * / ** and '
                           'parentheses). Use it for EVERY derived number: margins, growth '
                           'rates, differences, unit conversions.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'expression': {'type': 'string', 'description': 'e.g. "(383285000000 - 394328000000) / 394328000000 * 100"'},
                },
                'required': ['expression'],
            },
        },
    },
]


def run_tool(name, arguments):
    """Run one tool call. `arguments` is the raw JSON string from the model."""
    try:
        args = json.loads(arguments or '{}')
    except json.JSONDecodeError:
        return {'error': f'arguments are not valid JSON: {arguments!r}'}

    try:
        if name == 'lookup_company':
            matches = edgar.lookup_company(args['query'])
            return {'matches': matches} if matches else {'error': f'no company matches {args["query"]!r}'}
        if name == 'get_financials':
            return edgar.get_financials(args['ticker'], args['metric'],
                                        args.get('start_year'), args.get('end_year'))
        if name == 'calculate':
            return {'expression': args['expression'], 'result': calculate(args['expression'])}
    except KeyError as exc:
        return {'error': f'missing argument {exc}'}
    except (edgar.EdgarError, CalculatorError) as exc:
        return {'error': str(exc)}
    except Exception as exc:          # network trouble etc. — let the model decide
        return {'error': f'{type(exc).__name__}: {exc}'}
    return {'error': f'unknown tool {name!r}'}
