# Financial Research Agent — working notes

Portfolio project: a tool-calling LLM agent that answers questions about US
public companies from SEC EDGAR data, with a guardrail that every number in an
answer must trace to a tool result. See README.md for the public description.

## How to work in this repo

**Keep it small and readable.** The next person should understand any file in
one sitting.
- Plain Python, small functions, no classes unless state needs them.
- No new dependency without a clear reason; prefer the standard library.
- Comments explain *why*, not what. Match the style of the existing files.
- One concern per module (see layout below). Don't add frameworks
  (LangChain etc.) — the point of the project is that the loop is visible.
- Change only what the task needs; no drive-by refactors.

**Design rules that must hold:**
- Financial numbers come only from `get_financials` (EDGAR). Never hardcode one.
- Derived numbers go through `calculate`. The calculator stays an AST
  whitelist — never `eval`.
- Tools never raise into the loop; failures return `{"error": ...}`.
- Eval ground truth is computed from EDGAR by `evals/run_eval.py`, never typed
  in by hand, never taken from the agent's answer.
- README results must come from real runs. No invented numbers anywhere.
- Secrets live in `.env` only (gitignored). Never commit `.env` or `.cache/`.

## Testing standard

Every change ships with tests, and `pytest` must pass before a task is done.

- **Offline by default.** Unit tests use no network and no API key: EDGAR
  payloads are small fixtures shaped like the real API with made-up numbers
  (`tests/test_edgar.py`); the model is the scripted `FakeClient`
  (`tests/test_agent.py`).
- **One behavior per test**, named for that behavior
  (`test_untraced_number_gets_one_revision`).
- **Test the failure paths**, not just the happy path: bad input, missing data,
  tool errors, step limits.
- **Bug fix = failing test first**, then the fix.
- Tests that need the network or OpenAI must be marked `@pytest.mark.live`
  and skipped by default (register the marker in a `pytest.ini` with
  `addopts = -m "not live"` when the first one is added).

```
./venv/bin/python -m pytest -q                 # all offline tests
./venv/bin/python -m finagent -v "question"    # one question (needs .env)
./venv/bin/python -m evals.run_eval            # full eval (needs .env)
```

## Layout

```
finagent/edgar.py        SEC client, metric → XBRL concept map, annual-value extraction, disk cache
finagent/tools.py        tool JSON schemas + run_tool dispatcher
finagent/calculator.py   safe arithmetic
finagent/guardrails.py   number extraction / tracing; mentions_value for the eval
finagent/agent.py        loop: MAX_STEPS=10 model calls, MAX_REVISIONS=1
evals/questions.jsonl    question specs (types: value, growth, ratio, refuse)
evals/run_eval.py        computes ground truth, scores, writes evals/results/*.json
tests/                   offline unit tests
```

## Status (as of 2026-10-27)

Done and verified:
- All modules above; 23 offline tests pass.
- EDGAR extraction checked against live SEC data for AAPL, MSFT, NVDA, GOOGL,
  JPM, KO, TSLA, AMZN (values match published 10-Ks).

Not yet done:
- **The agent has never been run against a real model, and the eval has never
  been run.** Needs `.env` (copy `.env.example`; set OPENAI_API_KEY and
  SEC_USER_AGENT = "Name email").
- README "Results" section is a placeholder; the example tool calls at the top
  are illustrative and should be replaced with a real `-v` run.
- No git repo yet. Intended home: GitHub account `Yimo-888`.

Known limitations (also in README): fiscal year = calendar year the period
ends; revenue concept priority can pick a partial-revenue concept for a few
companies; refusal scoring is keyword-based.

## Next steps, in order

1. Run one question with `-v`, then the full eval; fix what breaks (with tests).
2. Record real results in README; replace the illustrative example.
3. `git init`, first commit, push to GitHub.
4. Week 2: grow `questions.jsonl` to ~50 (add multi-company comparisons);
   LLM-as-judge for refusals; ablations — with/without `calculate`,
   with/without the guardrail — reported as a table in README.
5. Week 3: retrieval over 10-K text (risk factors, business description) with
   a local vector store (Chroma), measured against a no-retrieval baseline.
