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


def test_agent_model_env_is_read_at_call_time(monkeypatch):
    # .env is loaded after `finagent.agent` is imported, so the variable must
    # be read when a run starts, not when the module loads.
    monkeypatch.setenv('AGENT_MODEL', 'model-from-env')
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client)
    assert client.params['model'] == 'model-from-env'


def test_explicit_model_beats_agent_model_env(monkeypatch):
    monkeypatch.setenv('AGENT_MODEL', 'model-from-env')
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='explicit')
    assert client.params['model'] == 'explicit'


def test_revision_request_asks_for_an_answer_that_hides_the_correction(monkeypatch):
    # Real runs opened revised answers with "You're right: I converted…".
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(_text('Revenue was $500 billion.')),
        _response(_text('Revenue was $383.3 billion.')),
    ])
    agent.run('Apple revenue 2023?', client=client, model='fake')
    feedback = client.sent[1][-1]['content']
    assert 'automated check' in feedback
    assert 'has not seen' in feedback and 'do not mention' in feedback.lower()


def test_draft_sent_back_for_revision_is_recorded(monkeypatch):
    _fake_financials(monkeypatch)
    client = FakeClient([
        _response(_text('Revenue was $500 billion.')),
        _response(_text('Revenue was $383.3 billion.')),
    ])
    result = agent.run('Apple revenue 2023?', client=client, model='fake')
    assert result.drafts == [{'answer': 'Revenue was $500 billion.',
                              'untraced': ['$500 billion'], 'ungrounded': []}]


def test_without_revisions_untraced_numbers_are_still_reported():
    client = FakeClient([_response(_text('Revenue was $500 billion.'))])
    result = agent.run('?', client=client, model='fake', max_revisions=0)
    assert result.untraced == ['$500 billion']
    assert result.model_calls == 1 and result.drafts == []


def test_without_calculator_the_tool_and_its_rule_are_gone():
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='fake', calculator=False)
    assert 'calculate' not in [t['name'] for t in client.params['tools']]
    assert 'get_financials' in [t['name'] for t in client.params['tools']]
    assert 'calculate' not in client.params['system']


def test_calculator_is_offered_by_default():
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='fake')
    assert 'calculate' in [t['name'] for t in client.params['tools']]
    assert 'calculate' in client.params['system']


PASSAGE = {'id': 'AAPL-2023-1A-p007', 'section': 'Risk Factors',
           'text': 'The Company depends on outsourcing partners, and about 90% of assembly is in Asia.'}


def _fake_search(monkeypatch):
    monkeypatch.setattr(agent, 'run_tool', lambda name, args: {'ticker': 'AAPL', 'passages': [PASSAGE]})


def _search_then(*answers):
    return FakeClient([_response(_tool_use('c1', 'search_filing', {'ticker': 'AAPL', 'year': 2023, 'query': 'x'})),
                       *[_response(_text(a)) for a in answers]])


def test_exact_quote_with_a_cited_passage_passes(monkeypatch):
    _fake_search(monkeypatch)
    client = _search_then('Apple says it "depends on outsourcing partners" [AAPL-2023-1A-p007].')
    result = agent.run('Apple supply risk?', client=client, model='fake')
    assert result.ungrounded == [] and result.untraced == [] and result.drafts == []


def test_number_inside_a_verified_quote_is_not_flagged(monkeypatch):
    _fake_search(monkeypatch)
    client = _search_then('The filing says "about 90% of assembly is in Asia" [AAPL-2023-1A-p007].')
    result = agent.run('Apple supply risk?', client=client, model='fake')
    assert result.untraced == []


def test_number_from_filing_text_outside_a_quote_is_flagged(monkeypatch):
    # Passage text is not a source of figures; only get_financials is.
    _fake_search(monkeypatch)
    answer = 'Around 90% of assembly is in Asia [AAPL-2023-1A-p007].'
    result = agent.run('Apple supply risk?', client=_search_then(answer, answer), model='fake')
    assert result.untraced == ['90%']


def test_misquote_gets_one_revision(monkeypatch):
    _fake_search(monkeypatch)
    client = _search_then('Apple says it "relies heavily on a single supplier in China".',
                          'Apple says it "depends on outsourcing partners" [AAPL-2023-1A-p007].')
    result = agent.run('Apple supply risk?', client=client, model='fake')
    assert result.ungrounded == [] and len(result.drafts) == 1
    feedback = client.sent[2][-1]['content']
    assert 'relies heavily on a single supplier in China' in feedback
    assert 'Quote the passages exactly' in feedback


def test_citation_of_a_passage_no_tool_returned_is_reported(monkeypatch):
    _fake_search(monkeypatch)
    answer = 'Apple discusses tariffs [AAPL-2023-1A-p099].'
    result = agent.run('Apple tariffs?', client=_search_then(answer, answer), model='fake')
    assert result.ungrounded == ['[AAPL-2023-1A-p099] is not a passage any tool returned']


def test_without_text_tools_the_tools_and_their_rule_are_gone():
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='fake', text_tools=False)
    assert [t['name'] for t in client.params['tools']] == ['lookup_company', 'get_financials', 'calculate']
    assert 'search_filing' not in client.params['system']


def test_prompt_reserves_quotation_marks_for_filing_text():
    # Real runs quoted metric labels, which the grounding check then flagged.
    client = FakeClient([_response(_text('Done.'))])
    agent.run('?', client=client, model='fake')
    assert 'quotation marks only for exact words from those passages' in client.params['system']
