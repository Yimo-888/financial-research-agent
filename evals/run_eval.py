"""
Score the agent against SEC ground truth.

    python -m evals.run_eval                  # all questions
    python -m evals.run_eval --only aapl      # ids containing "aapl"

Ground truth is computed straight from EDGAR data by this script — never
typed in by hand and never taken from the agent — so the eval stays honest
when filings are restated. A numeric question passes when the answer
contains the expected value (unit-aware, rounding-tolerant; see
finagent.guardrails). Results land in evals/results/<timestamp>.json.
"""
import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from finagent import agent, edgar
from finagent.guardrails import mentions_value

HERE = Path(__file__).parent
# Crude refusal check for week 1; replace with an LLM-as-judge in week 2.
REFUSAL_MARKERS = ('investment advice', 'not able to recommend', "can't recommend",
                   'cannot recommend', 'not provide', 'only report')


def _value(ticker, metric, year):
    values = edgar.annual_values(edgar.company_facts(edgar.resolve_cik(ticker)), metric)
    if year not in values:
        raise edgar.EdgarError(f'no {metric} for {ticker} {year}')
    return values[year]['value']


def expected_value(q):
    if q['type'] == 'value':
        return _value(q['ticker'], q['metric'], q['year'])
    if q['type'] == 'growth':
        a = _value(q['ticker'], q['metric'], q['from_year'])
        b = _value(q['ticker'], q['metric'], q['to_year'])
        return (b - a) / abs(a) * 100
    if q['type'] == 'ratio':
        return (_value(q['ticker'], q['numerator'], q['year'])
                / _value(q['ticker'], q['denominator'], q['year']) * 100)
    return None


def score(q, result, expected):
    if q['type'] == 'refuse':
        return any(m in result.answer.lower() for m in REFUSAL_MARKERS)
    return mentions_value(result.answer, expected)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', default='')
    parser.add_argument('--model', default=None)
    args = parser.parse_args()

    questions = [json.loads(line) for line in (HERE / 'questions.jsonl').read_text().splitlines() if line.strip()]
    questions = [q for q in questions if args.only in q['id']]

    rows = []
    for q in questions:
        expected = expected_value(q)
        started = time.monotonic()
        result = agent.run(q['question'], model=args.model)
        passed = score(q, result, expected)
        rows.append({
            'id': q['id'], 'type': q['type'], 'passed': passed, 'expected': expected,
            'answer': result.answer, 'untraced': result.untraced,
            'tool_calls': len(result.steps), 'model_calls': result.model_calls,
            'tokens': result.prompt_tokens + result.completion_tokens,
            'seconds': round(time.monotonic() - started, 1), 'stopped': result.stopped,
        })
        flag = 'PASS' if passed else 'FAIL'
        print(f'{flag}  {q["id"]:<28} expected={expected!r:<22} tools={len(result.steps)} '
              f'untraced={result.untraced or "-"}')

    if not rows:
        print('no questions matched')
        return
    n = len(rows)
    summary = {
        'model': args.model or agent.DEFAULT_MODEL,
        'accuracy': sum(r['passed'] for r in rows) / n,
        'answers_with_untraced_numbers': sum(bool(r['untraced']) for r in rows),
        'avg_tool_calls': sum(r['tool_calls'] for r in rows) / n,
        'avg_tokens': sum(r['tokens'] for r in rows) / n,
    }
    print(f'\naccuracy {summary["accuracy"]:.0%} ({sum(r["passed"] for r in rows)}/{n}) · '
          f'untraced answers {summary["answers_with_untraced_numbers"]} · '
          f'avg tools {summary["avg_tool_calls"]:.1f} · avg tokens {summary["avg_tokens"]:.0f}')

    out_dir = HERE / 'results'
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f'{time.strftime("%Y%m%d-%H%M%S")}.json'
    out.write_text(json.dumps({'summary': summary, 'rows': rows}, indent=2, default=str))
    print(f'saved {out}')


if __name__ == '__main__':
    main()
