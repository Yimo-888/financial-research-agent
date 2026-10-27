"""
The agent loop: the model decides which tool to call next, sees the result,
and repeats until it answers — bounded by MAX_STEPS model calls.

Before an answer is returned, the number-tracing guardrail checks it. If it
contains numbers no tool produced, the model is told which ones and gets ONE
revision; whatever is still untraced after that is reported on the result,
never silently passed through.
"""
import json
import os
from dataclasses import dataclass, field

from .guardrails import untraced_numbers
from .tools import TOOL_SPECS, run_tool

DEFAULT_MODEL = os.environ.get('AGENT_MODEL', 'gpt-4o-mini')
MAX_STEPS = 10
MAX_REVISIONS = 1

SYSTEM_PROMPT = """\
You are a financial research assistant for US public companies.

Rules:
- Get every financial number from get_financials. Never use numbers from memory.
- Compute every derived number (margins, growth, differences, conversions) with
  calculate. Never do arithmetic yourself.
- When you state a number, write it with its unit, e.g. "$383.3 billion",
  "44.1%", "$6.13 per share".
- State the fiscal year and period end date for each value, and list the
  source links you used at the end.
- If the data is missing, say so plainly. Do not guess.
- Do not give investment advice (buy / sell / hold, price targets). If asked,
  say you only report what the filings show.
"""


@dataclass
class AgentResult:
    answer: str
    steps: list = field(default_factory=list)       # one dict per tool call
    untraced: list = field(default_factory=list)    # numbers no tool produced
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stopped: str = 'answered'                       # or 'max_steps'


def _default_client():
    from openai import OpenAI
    return OpenAI()


def run(question, client=None, model=None, max_steps=MAX_STEPS, on_step=None):
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': question}]
    result = AgentResult(answer='')
    revisions_left = MAX_REVISIONS

    while result.model_calls < max_steps:
        response = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SPECS)
        result.model_calls += 1
        if response.usage:
            result.prompt_tokens += response.usage.prompt_tokens
            result.completion_tokens += response.usage.completion_tokens
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append({
                'role': 'assistant',
                'content': msg.content,
                'tool_calls': [{'id': tc.id, 'type': 'function',
                                'function': {'name': tc.function.name,
                                             'arguments': tc.function.arguments}}
                               for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                output = run_tool(tc.function.name, tc.function.arguments)
                step = {'tool': tc.function.name, 'arguments': tc.function.arguments, 'result': output}
                result.steps.append(step)
                if on_step:
                    on_step(step)
                messages.append({'role': 'tool', 'tool_call_id': tc.id,
                                 'content': json.dumps(output, default=str)})
            continue

        answer = msg.content or ''
        untraced = untraced_numbers(answer, [s['result'] for s in result.steps])
        if untraced and revisions_left:
            revisions_left -= 1
            messages.append({'role': 'assistant', 'content': answer})
            messages.append({'role': 'user', 'content': (
                'These numbers in your answer do not appear in any tool result: '
                + ', '.join(untraced)
                + '. Get them from get_financials, compute them with calculate, '
                  'or remove them. Then give the full corrected answer.')})
            continue

        result.answer = answer
        result.untraced = untraced
        return result

    result.stopped = 'max_steps'
    result.answer = f'Stopped after {max_steps} model calls without a final answer.'
    return result
