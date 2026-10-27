"""Agent loop tests with a scripted fake model — no network, no API key."""
import json
from types import SimpleNamespace as NS

from finagent import agent, edgar


def _tool_call(call_id, name, args):
    return NS(id=call_id, function=NS(name=name, arguments=json.dumps(args)))


def _response(content=None, tool_calls=None):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5))


class FakeClient:
    """Replays `script` one response per model call and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools):
        self.sent.append([dict(m) for m in messages])
        return self.script.pop(0)


def _fake_financials(monkeypatch):
    monkeypatch.setattr(edgar, 'get_financials', lambda ticker, metric, start=None, end=None: {
        'ticker': ticker, 'metric': metric,
        'values': [{'fiscal_year': 2023, 'value': 383285000000}],
    })


def test_tool_call_then_answer(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(tool_calls=[_tool_call('c1', 'get_financials', {'ticker': 'AAPL', 'metric': 'revenue'})]),
        _response(content='Apple revenue in FY2023 was $383.3 billion.'),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')

    assert result.stopped == 'answered'
    assert result.answer.endswith('$383.3 billion.')
    assert result.untraced == []
    assert [s['tool'] for s in result.steps] == ['get_financials']
    assert result.model_calls == 2 and result.prompt_tokens == 20
    # The tool result was fed back to the model under the right call id.
    tool_msg = client.sent[1][-1]
    assert tool_msg['role'] == 'tool' and tool_msg['tool_call_id'] == 'c1'


def test_untraced_number_gets_one_revision(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(tool_calls=[_tool_call('c1', 'get_financials', {'ticker': 'AAPL', 'metric': 'revenue'})]),
        _response(content='Revenue was $383.3 billion, up 8% from last year.'),
        _response(content='Revenue was $383.3 billion.'),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')

    assert result.answer == 'Revenue was $383.3 billion.'
    assert result.untraced == []
    feedback = client.sent[2][-1]['content']
    assert '8%' in feedback and 'calculate' in feedback


def test_still_untraced_after_revision_is_reported(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(content='Revenue was $500 billion.'),
        _response(content='Revenue was $500 billion.'),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')
    assert result.untraced == ['$500 billion']


def test_tool_errors_go_back_to_the_model():
    client = FakeClient([
        _response(tool_calls=[_tool_call('c1', 'calculate', {'expression': '1 / 0'})]),
        _response(content='I could not compute that.'),
    ])
    result = agent.run('?', client=client, model='fake')
    assert result.steps[0]['result'] == {'error': 'division by zero'}


def test_stops_at_max_steps():
    loop = [_response(tool_calls=[_tool_call(f'c{i}', 'calculate', {'expression': '1 + 1'})]) for i in range(3)]
    result = agent.run('?', client=FakeClient(loop), model='fake', max_steps=3)
    assert result.stopped == 'max_steps'
    assert len(result.steps) == 3
