# Financial Research Agent — working notes

Portfolio project: a tool-calling LLM agent that answers questions about US
public companies from SEC EDGAR data, with a guardrail that every number in an
answer must trace to a tool result, and every quote to retrieved 10-K text.
See README.md for the public description.

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
- Filing text (`search_filing`, `compare_filings`) is evidence for what a
  company said, never a source of financial figures: a number from a passage
  is allowed only inside a verified quote. Quotes must match a retrieved
  passage word for word (`grounding.py`).
- `report.py` uses no model. Its derived cells go through `calculate` and keep
  the expression; a cell that can't be filled is `{"error": ...}`, not a guess.
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
- Tests that need the network or the Claude API must be marked `@pytest.mark.live`
  and skipped by default (register the marker in a `pytest.ini` with
  `addopts = -m "not live"` when the first one is added).

```
./venv/bin/python -m pytest -q                 # all offline tests
./venv/bin/python -m finagent -v "question"    # one question (needs .env)
./venv/bin/python -m evals.run_eval            # full eval (needs .env)
./venv/bin/python -m evals.run_eval --ablation no-guardrail   # also no-calculator, no-retrieval
./venv/bin/python -m finagent.report AAPL MSFT --year 2023    # no model, SEC only
./venv/bin/python -m finagent.ui               # evidence UI on localhost:8000
```

## Layout

```
finagent/edgar.py        SEC client, metric → XBRL concept map, annual-value extraction, disk cache
finagent/filings.py      10-K text: find the filing, split Items 1 / 1A / 7, cut passages (cached parsed)
finagent/retrieval.py    BM25 passage search; year-over-year section diff
finagent/tools.py        tool JSON schemas + run_tool dispatcher
finagent/calculator.py   safe arithmetic
finagent/guardrails.py   number extraction / tracing; mentions_value for the eval
finagent/grounding.py    quote + passage-id checking; strip_grounded for the number check
finagent/agent.py        loop: MAX_STEPS=10 model calls, MAX_REVISIONS=1; ablation switches
finagent/report.py       comparison table (no model); CLI
finagent/evidence.py     answer spans → backing tool call (data for the UI)
finagent/pages.py        HTML for the evidence and report pages (stdlib, no JS)
finagent/ui.py           localhost http.server: POST /ask, GET /report
evals/questions.jsonl    question specs (types: value, growth, ratio, compare, refuse, text)
evals/run_eval.py        computes ground truth, scores, ablations, writes evals/results/*.json
tests/                   offline unit tests
```

## Status (as of 2026-11-18)

Done and verified:
- All modules above; 139 offline tests pass. Model: Claude (`claude-opus-5-5`).
- EDGAR extraction checked against live SEC data for AAPL, MSFT, NVDA, GOOGL,
  JPM, KO, TSLA, AMZN (values match published 10-Ks).
- The three issues from the first eval are fixed with tests: formula
  constants (a bare number that is a literal in a `calculate` expression is
  traced), revised answers mentioning the correction (`REVISION_REQUEST`),
  `AGENT_MODEL` read at call time (`agent.default_model()`).
- Eval: 64 questions (15 value, 10 growth, 10 ratio, 12 compare, 5 refuse,
  12 text). Real runs on 2026-11-18, one per configuration (README has the
  tables): full 64/64; no revision round 52/52 numeric, 7/12 text; no
  calculator 52/52 numeric with 37 answers holding untraced numbers; no
  retrieval 0/12 text (declined to quote from memory).
- 10-K text extraction checked on live filings for AAPL, MSFT, GOOGL, KO,
  NVDA, TSLA, AMZN, META, COST, PEP, JNJ, DIS, WMT, JPM. Comparison report,
  evidence UI (`--html` page and the local server) and both text tools were
  each run against live data.
- Git remote `origin` = github.com/Yimo-888/financial-research-agent.

Decisions worth knowing:
- Retrieval is BM25 in `retrieval.py`, not Chroma as first planned: no new
  dependency, deterministic, offline tests. An embedding ranker is a possible
  comparison, not a requirement.
- Ablations: `no-calculator` and `no-retrieval` also switch the revision
  round off, because the guardrail would only make the model delete what it
  can no longer verify.
- The text eval checks quotes against the full 10-K text from EDGAR (the
  asked years plus any year the answer cites a passage from), independent of
  what the agent retrieved.

Open issues:
- Numeric accuracy is 52/52 in every configuration, so the question set
  cannot show an accuracy effect of the calculator or the guardrail. Harder
  questions (multi-step, longer spans) are needed for that.
- The quote check treats any quoted phrase of 4+ words as a filing quote; a
  quoted metric label or suggested follow-up costs a revision (2 of 9
  revisions in the last full run).
- A quote that runs across two passages (page break) is flagged even when
  each half is verbatim.
- Section splitting needs "Item 1A."-style headings: INTC returns no
  sections; XOM resolves to a CIK with no 10-K data (financials empty too).
- Paraphrased claims are not checked against the passage they cite.
- `companyfacts` and `submissions` caches never expire; delete `.cache/` to
  pick up new filings.

Known limitations (also in README): fiscal year = calendar year the period
ends; revenue concept priority can pick a partial-revenue concept for a few
companies (PFE and BAC revenue looked suspect; not verified); latest-filed value wins, so EPS can be
split-adjusted (NVDA, NFLX, WMT); the refusal judge isn't validated against
human labels; one eval run per configuration, no variance estimate.

## Next steps, in order

1. Harder numeric questions so the ablations can separate on accuracy;
   repeat runs for variance.
2. Retrieval relevance labels; compare BM25 with an embedding ranker.
3. Check paraphrases against cited passages; handle quotes that span passages.
4. LLM judge for answer quality, validated against human labels.
