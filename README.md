# Financial Research Agent

A tool-calling LLM agent that answers questions about US public companies'
financials using **official SEC filings**, and proves that every number it
states came from the data rather than from the model's memory.

The tool calls it is designed to make (illustrative; replace with a real `-v`
run once you have one):

```
$ python -m finagent -v "What was Apple's gross margin in fiscal 2023?"
  → get_financials({"ticker": "AAPL", "metric": "gross_profit", "start_year": 2023, "end_year": 2023})
  → get_financials({"ticker": "AAPL", "metric": "revenue", "start_year": 2023, "end_year": 2023})
  → calculate({"expression": "169148000000 / 383285000000 * 100"})
```

> Not investment advice. The agent reports what filings show and declines
> buy/sell questions.

## Why this design

LLMs are fluent with financial numbers and often wrong about them. They recall
outdated figures, mix up fiscal years, and slip on multi-digit arithmetic. This
agent is built so those failures are **caught, not hoped away**:

| Failure mode | Defense |
|---|---|
| Number from memory | Numbers come only from `get_financials` (SEC EDGAR XBRL data) |
| Mental arithmetic | Every derived number goes through `calculate` (a safe AST evaluator, not `eval`) |
| Hallucinated or mistyped figure | **Number-tracing guardrail**: each number in the answer must match a tool result, unit-aware (`$383.3 billion` ↔ `383285000000`, `44.1%` ↔ `0.4413`) and rounding-tolerant. Untraced numbers get one revision round, then are reported, never silently passed |
| Fiscal-year confusion | Every value carries its exact period start/end and a link to the filing |
| Runaway loops / cost | Hard cap on model calls; token usage tracked per run |
| Investment advice | Refused by instruction; checked in the eval |

## How it works

```
question
  → agent loop (OpenAI tool calling), up to 10 model calls
      ├─ lookup_company   ticker / name → SEC CIK
      ├─ get_financials   annual 10-K values for one metric, with source links
      └─ calculate        arithmetic for margins, growth, differences
  → number-tracing guardrail → (one revision if needed)
  → answer with periods and sources
```

**Data:** SEC EDGAR `companyfacts` API: free, official, no API key. Annual
values are taken from 10-K filings only, ~1-year durations (52/53-week years
included); when a period is repeated or restated in a later 10-K, the most
recently filed value wins. Responses are cached in `.cache/`.

**Metrics:** revenue, cost_of_revenue, gross_profit, operating_income,
net_income, eps_diluted, operating_cash_flow, total_assets, total_liabilities,
stockholders_equity.

## Evaluation

`evals/questions.jsonl` holds questions of four types: single values, growth
rates, ratios (margins), and questions the agent should refuse. **Ground truth
is computed by the eval script straight from EDGAR**, never typed by hand and
never taken from the agent.

```
python -m evals.run_eval
```

It reports accuracy, how many answers still contained untraced numbers,
average tool calls and tokens, and saves every answer to `evals/results/`.

**Results:** _run the eval and record your numbers here._

## Run it

```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY and SEC_USER_AGENT
python -m finagent -v "How much did NVIDIA's revenue grow from fiscal 2023 to 2024?"
pytest                        # offline: fixture data and a scripted fake model
```

## Project layout

```
finagent/
  edgar.py        SEC client: ticker lookup, companyfacts, annual-value extraction
  tools.py        tool schemas the model sees + the dispatcher that runs them
  calculator.py   safe arithmetic (AST whitelist)
  guardrails.py   number extraction and tracing
  agent.py        the tool-calling loop, step cap, revision round
evals/            questions + scoring script
tests/            unit tests, no network or API key needed
```

## Known limitations

- "Fiscal year" = calendar year the period ends in. Retailers whose year ends
  in early February label that year the prior one; the period dates are always
  shown, so the agent can say exactly which period it means.
- Revenue uses the first available of three XBRL concepts. For a few
  companies the contract-revenue concept covers only part of total revenue.
- The refusal check in the eval is keyword-based for now.

## Roadmap

- [ ] Expand the eval to ~50 questions, including multi-company comparisons
- [ ] LLM-as-judge for refusals and answer quality
- [ ] Ablations: with vs. without `calculate`, with vs. without the guardrail
- [ ] Retrieval over 10-K text (risk factors, business description) with a
      vector store, measured against a no-retrieval baseline
