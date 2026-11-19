"""
The agent loop: the model decides which tool to call next, sees the result,
and repeats until it answers — bounded by MAX_STEPS model calls.

Before an answer is returned, two guardrails check it: every number must
trace to a tool result (guardrails.py), and every quote and passage citation
must match 10-K text a tool returned (grounding.py). If something fails, the
model is told what and gets ONE revision; whatever still fails after that is
reported on the result, never silently passed through.

Three switches exist for the ablations in evals/run_eval.py: `calculator`
and `text_tools` remove those tools, `max_revisions=0` turns the revision
round off (problems are still measured and reported).
"""
import json
import os
from dataclasses import dataclass, field

from .grounding import strip_grounded, ungrounded
from .guardrails import untraced_numbers
from .tools import TEXT_TOOLS, TOOL_SPECS, run_tool

DEFAULT_MODEL = 'claude-opus-5-5'
MAX_STEPS = 10
MAX_REVISIONS = 1
MAX_TOKENS = 16000
# Opus 5.5 always thinks; effort is the only depth control. Set explicitly so
# a change in the model's default can't silently move the eval.
EFFORT = 'medium'
# If a safety classifier declines a request, the API re-runs it on Anthropic's
# recommended fallback model instead of returning the refusal.
BETAS = ['server-side-fallback-2026-07-01']

CALCULATOR_RULE = """\
- Compute every derived number (margins, growth, differences, conversions) with
  calculate. Never do arithmetic yourself.
"""
# Ablation only: the model has no calculator and does the arithmetic itself.
NO_CALCULATOR_RULE = """\
- Work out derived numbers (margins, growth, differences, conversions) yourself.
"""
TEXT_RULE = """\
- For what a company says in its 10-K (risks, business, strategy, reasons it
  gives), use search_filing; for how that changed between years, use
  compare_filings. Rest every such statement on the passages returned and cite
  their ids in square brackets, e.g. [AAPL-2023-1A-p012]. Keep quotes short and
  exact; never quote or describe a filing from memory.
- Use quotation marks only for exact words from those passages, not for metric
  names, labels or your own phrasing.
- A number found only in filing text may appear only inside an exact quote.
"""
SYSTEM_PROMPT = """\
You are a financial research assistant for US public companies.

Rules:
- Get every financial number from get_financials. Never use numbers from memory.
{calculator_rule}{text_rule}\
- When you state a number, write it with its unit, e.g. "$383.3 billion",
  "44.1%", "$6.13 per share".
- State the fiscal year and period end date for each value, and list the
  source links you used at the end.
- If the data is missing, say so plainly. Do not guess.
- Do not give investment advice (buy / sell / hold, price targets). If asked,
  say you only report what the filings show.
"""


# The user sees only the final answer, so the rewrite must read as a first
# answer: real runs otherwise opened with "You're right: I converted…".
REVISION_REQUEST = """\
This is an automated check, not the user. The user has not seen your draft
and will not see this message.

{problems}

Then write the complete answer again from the top, as if for the first time.
Do not mention this check, the draft, or that anything was corrected."""
UNTRACED_NOTE = """\
These numbers in your draft do not appear in any tool result: {numbers}
Get them from get_financials, compute them with calculate, or leave them out."""
UNGROUNDED_NOTE = """\
These quotes or citations in your draft do not match the filing text you retrieved:
{items}
Quote the passages exactly and cite only ids a tool returned, or leave them out."""


@dataclass
class AgentResult:
    answer: str
    steps: list = field(default_factory=list)       # one dict per tool call
    untraced: list = field(default_factory=list)    # numbers no tool produced
    ungrounded: list = field(default_factory=list)  # quotes/citations not in retrieved text
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stopped: str = 'answered'                       # or 'max_steps', 'refused'
    drafts: list = field(default_factory=list)      # answers sent back for revision


def _default_client():
    from anthropic import Anthropic
    return Anthropic()


def default_model():
    # Read at call time: .env is loaded after this module is imported.
    return os.environ.get('AGENT_MODEL') or DEFAULT_MODEL


def run(question, client=None, model=None, max_steps=MAX_STEPS, on_step=None,
        calculator=True, text_tools=True, max_revisions=MAX_REVISIONS):
    client = client or _default_client()
    model = model or default_model()
    system = SYSTEM_PROMPT.format(
        calculator_rule=CALCULATOR_RULE if calculator else NO_CALCULATOR_RULE,
        text_rule=TEXT_RULE if text_tools else '')
    tools = [t for t in TOOL_SPECS
             if (calculator or t['name'] != 'calculate')
             and (text_tools or t['name'] not in TEXT_TOOLS)]
    messages = [{'role': 'user', 'content': question}]
    result = AgentResult(answer='')
    revisions_left = max_revisions

    while result.model_calls < max_steps:
        response = client.beta.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system,
            messages=messages, tools=tools, output_config={'effort': EFFORT},
            betas=BETAS, fallbacks='default')
        result.model_calls += 1
        if response.usage:
            result.prompt_tokens += response.usage.input_tokens
            result.completion_tokens += response.usage.output_tokens
        # Send the whole content back unchanged: thinking blocks only count
        # if the next request carries them exactly as they arrived.
        messages.append({'role': 'assistant', 'content': response.content})

        if response.stop_reason == 'refusal':
            result.stopped = 'refused'
            result.answer = 'The model declined to answer this question.'
            return result

        tool_uses = [b for b in response.content if b.type == 'tool_use']
        if tool_uses:
            tool_results = []
            for tu in tool_uses:
                output = run_tool(tu.name, tu.input)
                step = {'tool': tu.name, 'arguments': tu.input, 'result': output}
                result.steps.append(step)
                if on_step:
                    on_step(step)
                tool_results.append({'type': 'tool_result', 'tool_use_id': tu.id,
                                     'content': json.dumps(output, default=str),
                                     'is_error': 'error' in output})
            # All results in one message; splitting them discourages parallel calls.
            messages.append({'role': 'user', 'content': tool_results})
            continue

        answer = ''.join(b.text for b in response.content if b.type == 'text')
        results = [s['result'] for s in result.steps]
        # Numbers inside a verified quote are the filing's words, not a claim.
        untraced = untraced_numbers(strip_grounded(answer, results), results)
        loose = ungrounded(answer, results, question)
        if (untraced or loose) and revisions_left:
            revisions_left -= 1
            result.drafts.append({'answer': answer, 'untraced': untraced, 'ungrounded': loose})
            notes = ([UNTRACED_NOTE.format(numbers=', '.join(untraced))] if untraced else []) \
                + ([UNGROUNDED_NOTE.format(items='\n'.join(f'- {p}' for p in loose))] if loose else [])
            messages.append({'role': 'user', 'content': REVISION_REQUEST.format(
                problems='\n\n'.join(notes))})
            continue

        result.answer = answer
        result.untraced = untraced
        result.ungrounded = loose
        return result

    result.stopped = 'max_steps'
    result.answer = f'Stopped after {max_steps} model calls without a final answer.'
    return result
