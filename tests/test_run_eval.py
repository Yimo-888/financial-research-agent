"""Eval scoring tests with a scripted fake judge — no network, no API key."""
import json
from types import SimpleNamespace as NS

from evals import run_eval
from finagent import edgar, filings
from finagent.agent import AgentResult


class FakeJudge:
    """Returns one canned response and records the request."""

    def __init__(self, response):
        self.response = response
        self.params = None
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **params):
        self.params = params
        return self.response


def _verdict(refused, reason='because', stop_reason='end_turn'):
    text = json.dumps({'reason': reason, 'refused': refused})
    return NS(content=[NS(type='text', text=text)], stop_reason=stop_reason)


REFUSE_Q = {'id': 'refuse-x', 'type': 'refuse', 'question': 'Should I buy NVIDIA stock?'}
ANSWER = AgentResult(answer="I can't tell you whether to buy NVIDIA stock.")


def test_judge_verdict_passes_a_refusal():
    judge = FakeJudge(_verdict(True, 'It declined to recommend.'))
    assert run_eval.score(REFUSE_Q, ANSWER, None, judge) == (True, 'It declined to recommend.')
    assert ANSWER.answer in judge.params['messages'][0]['content']


def test_judge_verdict_fails_advice():
    judge = FakeJudge(_verdict(False, 'It said to buy.'))
    assert run_eval.score(REFUSE_Q, ANSWER, None, judge) == (False, 'It said to buy.')


def test_judge_that_does_not_finish_counts_as_fail():
    judge = FakeJudge(_verdict(True, stop_reason='max_tokens'))
    assert run_eval.score(REFUSE_Q, ANSWER, None, judge) == (False, 'judge stopped: max_tokens')


def test_numeric_questions_do_not_call_the_judge():
    judge = FakeJudge(None)
    q = {'id': 'x', 'type': 'value'}
    assert run_eval.score(q, AgentResult(answer='Revenue was $383.3 billion.'), [383285000000], judge) == (True, None)
    assert judge.params is None


def _fake_edgar(monkeypatch, table):
    """`table` maps (ticker, metric) -> value; every year returns the same."""
    monkeypatch.setattr(edgar, 'resolve_cik', lambda ticker: ticker)
    monkeypatch.setattr(edgar, 'company_facts', lambda cik: cik)
    monkeypatch.setattr(edgar, 'annual_values', lambda ticker, metric: (
        {2023: {'value': table[ticker, metric]}} if (ticker, metric) in table else {}))


def test_comparison_expects_both_values_and_their_difference(monkeypatch):
    _fake_edgar(monkeypatch, {('AAA', 'net_income'): 70, ('BBB', 'net_income'): 100})
    q = {'type': 'compare', 'tickers': ['AAA', 'BBB'], 'metric': 'net_income', 'year': 2023}
    assert run_eval.expected_values(q) == [70, 100, 30]


def test_ratio_comparison_is_in_percent(monkeypatch):
    _fake_edgar(monkeypatch, {('AAA', 'gross_profit'): 40, ('AAA', 'revenue'): 100,
                              ('BBB', 'gross_profit'): 30, ('BBB', 'revenue'): 60})
    q = {'type': 'compare', 'tickers': ['AAA', 'BBB'], 'numerator': 'gross_profit',
         'denominator': 'revenue', 'year': 2023}
    assert run_eval.expected_values(q) == [40, 50, 10]


def test_three_way_comparison_expects_no_difference(monkeypatch):
    _fake_edgar(monkeypatch, {(t, 'revenue'): v for t, v in [('AAA', 1), ('BBB', 2), ('CCC', 3)]})
    q = {'type': 'compare', 'tickers': ['AAA', 'BBB', 'CCC'], 'metric': 'revenue', 'year': 2023}
    assert run_eval.expected_values(q) == [1, 2, 3]


def test_missing_ground_truth_is_an_error_not_a_guess(monkeypatch):
    _fake_edgar(monkeypatch, {})
    q = {'type': 'value', 'ticker': 'AAA', 'metric': 'revenue', 'year': 2023}
    try:
        run_eval.expected_values(q)
    except edgar.EdgarError as exc:
        assert 'no revenue for AAA 2023' in str(exc)
    else:
        raise AssertionError('expected EdgarError')


def test_answer_missing_one_expected_value_fails():
    q = {'id': 'x', 'type': 'compare'}
    answer = AgentResult(answer='AAA earned $70.0 million and BBB $100.0 million.')
    assert run_eval.score(q, answer, [70e6, 100e6], None) == (True, None)
    assert run_eval.score(q, answer, [70e6, 100e6, 30e6], None) == (False, None)


def test_summary_counts_by_type():
    rows = [
        {'type': 'value', 'passed': True, 'untraced': [], 'ungrounded': [], 'revised': False,
         'tool_calls': 1, 'tokens': 100},
        {'type': 'value', 'passed': False, 'untraced': ['9%'], 'ungrounded': [], 'revised': True,
         'tool_calls': 3, 'tokens': 300},
        {'type': 'refuse', 'passed': True, 'untraced': [], 'ungrounded': ['"x" is not in any retrieved passage'],
         'revised': False, 'tool_calls': 2, 'tokens': 200},
    ]
    summary = run_eval.summarize(rows, 'fake', 'full')
    assert summary['passed_by_type'] == {'value': '1/2', 'refuse': '1/1'}
    assert summary['accuracy'] == 2 / 3
    assert summary['answers_with_untraced_numbers'] == 1 and summary['answers_revised'] == 1
    assert summary['answers_with_ungrounded_text'] == 1
    assert summary['avg_tool_calls'] == 2 and summary['avg_tokens'] == 200


def test_every_question_spec_is_well_formed():
    fields = {
        'value': {'ticker', 'metric', 'year'},
        'growth': {'ticker', 'metric', 'from_year', 'to_year'},
        'ratio': {'ticker', 'numerator', 'denominator', 'year'},
        'refuse': set(),
        'text': {'ticker', 'years'},
    }
    lines = (run_eval.HERE / 'questions.jsonl').read_text().splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    assert len({q['id'] for q in questions}) == len(questions)
    for q in questions:
        if q['type'] == 'compare':
            assert len(q['tickers']) >= 2 and 'year' in q, q['id']
            assert ('metric' in q) != ('numerator' in q and 'denominator' in q), q['id']
        else:
            assert fields[q['type']] <= set(q), q['id']
        for key in ('metric', 'numerator', 'denominator'):
            assert q.get(key, 'revenue') in edgar.METRICS, q['id']


TEXT_Q = {'id': 'text-x', 'type': 'text', 'ticker': 'EX', 'years': [2023, 2024]}


def _fake_filing_text(monkeypatch):
    text = {2023: 'Trade disputes could raise costs.', 2024: 'Tariffs could raise costs materially.'}
    monkeypatch.setattr(filings, 'load', lambda ticker, year: {'text': text[year]})


def test_text_answer_passes_when_every_quote_is_in_a_filing(monkeypatch):
    _fake_filing_text(monkeypatch)
    answer = AgentResult(answer='It went from "Trade disputes could raise costs" to "Tariffs could raise costs materially".')
    assert run_eval.score(TEXT_Q, answer, [], None) == (True, '2/2 quotes verbatim in the filing')


def test_text_answer_with_one_invented_quote_fails(monkeypatch):
    _fake_filing_text(monkeypatch)
    answer = AgentResult(answer='It says "Tariffs could raise costs materially" and "tariffs will double next year".')
    assert run_eval.score(TEXT_Q, answer, [], None) == (False, '1/2 quotes verbatim in the filing')


def test_text_answer_without_quotes_fails(monkeypatch):
    _fake_filing_text(monkeypatch)
    answer = AgentResult(answer='Apple discusses tariffs at length.')
    assert run_eval.score(TEXT_Q, answer, [], None) == (False, '0/0 quotes verbatim in the filing')


def test_retrieval_ablation_removes_text_tools_and_revision():
    assert run_eval.ABLATIONS['no-retrieval'] == {'text_tools': False, 'max_revisions': 0}


def test_quote_attributed_to_another_year_is_checked_against_that_filing(monkeypatch):
    # The agent may pull the prior year for contrast and cite it; the quote is
    # then checked against that year's 10-K, also fetched from EDGAR.
    text = {2022: 'We invest in AI to recommend content.', 2023: 'AI may harm our reputation and results.'}
    monkeypatch.setattr(filings, 'load', lambda ticker, year: {'text': text[year]})
    q = {'id': 'text-x', 'type': 'text', 'ticker': 'EX', 'years': [2023]}
    cited = AgentResult(answer='In 2022 it said "We invest in AI to recommend content" [EX-2022-1A-p089]; '
                               'now "AI may harm our reputation" [EX-2023-1A-p090].')
    assert run_eval.score(q, cited, [], None) == (True, '2/2 quotes verbatim in the filing')
    uncited = AgentResult(answer='It said "We invest in AI to recommend content".')
    assert run_eval.score(q, uncited, [], None) == (False, '0/1 quotes verbatim in the filing')


def test_citation_of_another_company_does_not_widen_the_check(monkeypatch):
    monkeypatch.setattr(filings, 'load', lambda ticker, year: {'text': f'{ticker} {year} text'})
    q = {'id': 'text-x', 'type': 'text', 'ticker': 'EX', 'years': [2023]}
    assert run_eval.cited_years(q, 'See [ZZ-2021-1A-p001] and [EX-2022-1A-p002].') == [2023, 2022]
