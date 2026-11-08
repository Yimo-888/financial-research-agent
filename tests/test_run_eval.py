"""Eval scoring tests with a scripted fake judge — no network, no API key."""
import json
from types import SimpleNamespace as NS

from evals import run_eval
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
    assert run_eval.score(q, AgentResult(answer='Revenue was $383.3 billion.'), 383285000000, judge) == (True, None)
    assert judge.params is None
