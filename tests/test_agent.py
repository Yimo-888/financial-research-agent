"""Agent loop tests with a scripted fake model — no network, no API key."""
from types import SimpleNamespace as NS

from finagent import agent, edgar


def _tool_use(call_id, name, args):
    return NS(type='tool_use', id=call_id, name=name, input=args)


def _text(text):
    return NS(type='text', text=text)


def _response(*content, stop_reason=None):
    if stop_reason is None:
        stop_reason = 'tool_use' if any(b.type == 'tool_use' for b in content) else 'end_turn'
    return NS(content=list(content), stop_reason=stop_reason,
              usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    """Replays `script` one response per model call and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.params = None
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, messages, **params):
        self.sent.append([dict(m) for m in messages])
        self.params = params
        return self.script.pop(0)


def _fake_financials(monkeypatch):
    monkeypatch.setattr(edgar, 'get_financials', lambda ticker, metric, start=None, end=None: {
        'ticker': ticker, 'metric': metric,
        'values': [{'fiscal_year': 2023, 'value': 383285000000}],
    })


def test_tool_call_then_answer(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(_tool_use('c1', 'get_financials', {'ticker': 'AAPL', 'metric': 'revenue'})),
        _response(_text('Apple revenue in FY2023 was $383.3 billion.')),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')

    assert result.stopped == 'answered'
    assert result.answer.endswith('$383.3 billion.')
    assert result.untraced == []
    assert [s['tool'] for s in result.steps] == ['get_financials']
    assert result.model_calls == 2 and result.prompt_tokens == 20
    # The tool result was fed back to the model under the right call id.
    tool_msg = client.sent[1][-1]
    assert tool_msg['role'] == 'user'
    assert tool_msg['content'][0]['type'] == 'tool_result'
    assert tool_msg['content'][0]['tool_use_id'] == 'c1'


def test_assistant_content_is_sent_back_unchanged(monkeypatch):
    # Thinking blocks must go back exactly as received, or the model loses them.
    _fake_financials(monkeypatch)
    turn = _response(NS(type='thinking', thinking='', signature='sig'),
                     _tool_use('c1', 'get_financials', {'ticker': 'AAPL', 'metric': 'revenue'}))
    client = FakeClient([turn, _response(_text('Revenue was $383.3 billion.'))])
    agent.run('Apple revenue 2023?', client=client, model='fake')

    assistant_msg = client.sent[1][-2]
    assert assistant_msg == {'role': 'assistant', 'content': turn.content}


def test_untraced_number_gets_one_revision(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(_tool_use('c1', 'get_financials', {'ticker': 'AAPL', 'metric': 'revenue'})),
        _response(_text('Revenue was $383.3 billion, up 8% from last year.')),
        _response(_text('Revenue was $383.3 billion.')),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')

    assert result.answer == 'Revenue was $383.3 billion.'
    assert result.untraced == []
    feedback = client.sent[2][-1]['content']
    assert '8%' in feedback and 'calculate' in feedback


def test_still_untraced_after_revision_is_reported(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(_text('Revenue was $500 billion.')),
        _response(_text('Revenue was $500 billion.')),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')
    assert result.untraced == ['$500 billion']


def test_tool_errors_go_back_to_the_model():
    client = FakeClient([
        _response(_tool_use('c1', 'calculate', {'expression': '1 / 0'})),
        _response(_text('I could not compute that.')),
    ])
    result = agent.run('?', client=client, model='fake')
    assert result.steps[0]['result'] == {'error': 'division by zero'}
    assert client.sent[1][-1]['content'][0]['is_error'] is True


def test_refusal_is_reported():
    client = FakeClient([_response(stop_reason='refusal')])
    result = agent.run('?', client=client, model='fake')
    assert result.stopped == 'refused'
    assert result.model_calls == 1


def test_requests_server_side_fallback():
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='fake')
    assert client.params['fallbacks'] == 'default'
    assert 'server-side-fallback-2026-07-01' in client.params['betas']


def test_stops_at_max_steps():
    loop = [_response(_tool_use(f'c{i}', 'calculate', {'expression': '1 + 1'})) for i in range(3)]
    result = agent.run('?', client=FakeClient(loop), model='fake', max_steps=3)
    assert result.stopped == 'max_steps'
    assert len(result.steps) == 3
