# Financial Research Agent

**English** · [中文说明](#中文说明)

A tool-calling LLM agent that answers questions about US public companies'
financials using **official SEC filings**, and proves that every number it
states came from the data rather than from the model's memory.

A real run (`claude-opus-5-5`, 2026-11-07):

```
$ python -m finagent -v "What was Apple's gross margin in fiscal 2023?"
  → get_financials({"ticker": "AAPL", "metric": "gross_profit", "start_year": 2023, "end_year": 2023})
  → get_financials({"ticker": "AAPL", "metric": "revenue", "start_year": 2023, "end_year": 2023})
  → calculate({"expression": "169148000000 / 383285000000 * 100"})

Apple's gross margin for fiscal 2023 was **44.1%**. Fiscal 2023 ran from
September 25, 2022 to September 30, 2023.
...
[3 tool calls · 3 model calls · 5320 tokens · answered]
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
  → agent loop (Claude tool use), up to 10 model calls
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
never taken from the agent. Refusals are graded by Claude as a judge with a
fixed model and a JSON verdict (`reason`, `refused`), since a refusal can be
phrased too many ways for a keyword list.

```
python -m evals.run_eval
```

It reports accuracy, how many answers still contained untraced numbers,
average tool calls and tokens, and saves every answer to `evals/results/`.

**Results** (one run, `claude-opus-5-5`, 2026-11-07, 10 questions):

| Type | Passed |
|---|---|
| Single value | 5/5 |
| Growth rate | 2/2 |
| Ratio (margin) | 2/2 |
| Refusal | 1/1 |
| **Total** | **10/10** |

Average 3.0 tool calls and 5,896 tokens per question. One answer still
contained an untraced number after its revision round: the NVIDIA growth
answer wrote out its formula ("… × 100"), and the guardrail flags the bare
`100` (see limitations). Ten questions is a small sample; week 2 grows it to
~50.

What the first run caught: before two fixes, the same eval scored 9/10. The
guardrail flagged a correct "$33.948 billion" because the calculator had
already returned it in billions (`33.948`), and the old keyword scorer
missed a real refusal ("I can't tell you whether to buy NVIDIA stock").
Both now have regression tests.

## Run it

```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY and SEC_USER_AGENT
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
- The refusal judge is Claude grading Claude; it is not yet checked against
  human labels.
- The guardrail flags constants written into a formula in the answer
  (the `100` in "… × 100"). After a revision round, the answer sometimes
  mentions the correction ("You're right: I converted…").

## Roadmap

- [ ] Expand the eval to ~50 questions, including multi-company comparisons
- [x] LLM-as-judge for refusals
- [ ] LLM-as-judge for answer quality
- [ ] Ablations: with vs. without `calculate`, with vs. without the guardrail
- [ ] Retrieval over 10-K text (risk factors, business description) with a
      vector store, measured against a no-retrieval baseline

---

## 中文说明

[English](#financial-research-agent) · **中文**

一个基于工具调用（tool calling）的大语言模型智能体，使用 **SEC 官方披露文件**
回答有关美国上市公司财务状况的问题，并能证明答案中的每一个数字都来自数据，
而不是模型的记忆。

一次真实运行（`claude-opus-5-5`，2026-11-07）：

```
$ python -m finagent -v "What was Apple's gross margin in fiscal 2023?"
  → get_financials({"ticker": "AAPL", "metric": "gross_profit", "start_year": 2023, "end_year": 2023})
  → get_financials({"ticker": "AAPL", "metric": "revenue", "start_year": 2023, "end_year": 2023})
  → calculate({"expression": "169148000000 / 383285000000 * 100"})

Apple's gross margin for fiscal 2023 was **44.1%**. Fiscal 2023 ran from
September 25, 2022 to September 30, 2023.
...
[3 tool calls · 3 model calls · 5320 tokens · answered]
```

> 不构成投资建议。智能体只报告披露文件中的内容，并拒绝回答买入/卖出类问题。

### 为什么这样设计

大语言模型谈论财务数字时语气流畅，却常常出错：会记错过时的数据、混淆财年、
在多位数运算上失误。本智能体的设计目标是让这些错误**被发现，而不是寄希望于
它们不发生**：

| 失败模式 | 防御措施 |
|---|---|
| 凭记忆给出数字 | 数字只能来自 `get_financials`（SEC EDGAR XBRL 数据） |
| 心算 | 所有派生数字都必须经过 `calculate`（安全的 AST 求值器，而不是 `eval`） |
| 编造或写错的数字 | **数字溯源护栏**：答案中的每个数字都必须与某个工具结果匹配，支持单位换算（`$383.3 billion` ↔ `383285000000`，`44.1%` ↔ `0.4413`）并容忍四舍五入。无法溯源的数字会触发一轮修订，之后仍无法溯源则如实报告，绝不悄悄放过 |
| 财年混淆 | 每个数值都附带精确的报告期起止日期和披露文件链接 |
| 无限循环 / 成本失控 | 模型调用次数有硬上限；每次运行都统计 token 用量 |
| 投资建议 | 通过指令拒绝；在评测中检查 |

### 工作原理

```
问题
  → 智能体循环（Claude 工具调用），最多 10 次模型调用
      ├─ lookup_company   股票代码 / 公司名 → SEC CIK
      ├─ get_financials   某一指标的 10-K 年度数值，附来源链接
      └─ calculate        计算利润率、增长率、差额等
  → 数字溯源护栏 →（必要时修订一次）
  → 附带报告期和来源的答案
```

**数据：** SEC EDGAR `companyfacts` API：免费、官方、无需 API key。年度数值
只取自 10-K 文件，且报告期约为一年（包含 52/53 周财年）；当同一期间在之后的
10-K 中重复出现或被重述时，以最近提交的数值为准。响应缓存在 `.cache/` 中。

**指标：** revenue（营业收入）、cost_of_revenue（营业成本）、gross_profit
（毛利）、operating_income（营业利润）、net_income（净利润）、eps_diluted
（稀释每股收益）、operating_cash_flow（经营现金流）、total_assets（总资产）、
total_liabilities（总负债）、stockholders_equity（股东权益）。

### 评测

`evals/questions.jsonl` 包含四类问题：单一数值、增长率、比率（利润率），以及
智能体应当拒绝回答的问题。**标准答案由评测脚本直接从 EDGAR 计算得出**，从不
手工录入，也从不取自智能体的回答。拒答类问题由 Claude 作为评审（judge）打分，
使用固定模型和 JSON 格式的判定（`reason`、`refused`），因为拒绝的说法太多，
关键词列表无法覆盖。

```
python -m evals.run_eval
```

脚本会报告准确率、仍含有无法溯源数字的答案数量、平均工具调用次数和 token 数，
并将每个答案保存到 `evals/results/`。

**结果**（一次运行，`claude-opus-5-5`，2026-11-07，10 个问题）：

| 类型 | 通过 |
|---|---|
| 单一数值 | 5/5 |
| 增长率 | 2/2 |
| 比率（利润率） | 2/2 |
| 拒答 | 1/1 |
| **合计** | **10/10** |

平均每个问题 3.0 次工具调用、5,896 个 token。有一个答案在修订一轮后仍含有
无法溯源的数字：NVIDIA 增长率的答案写出了计算公式（"… × 100"），护栏标记了
单独的 `100`（见“已知局限”）。10 个问题样本量较小；第 2 周将扩充到约 50 个。

首次运行发现的问题：在两处修复之前，同一评测得分为 9/10。护栏错误地标记了
一个正确的 "$33.948 billion"，因为计算器已经以十亿为单位返回了结果
（`33.948`）；而旧的关键词评分器漏判了一次真实的拒答（"I can't tell you
whether to buy NVIDIA stock"）。两者现在都有回归测试。

### 运行

```
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入 ANTHROPIC_API_KEY 和 SEC_USER_AGENT
python -m finagent -v "How much did NVIDIA's revenue grow from fiscal 2023 to 2024?"
pytest                        # 离线运行：使用测试夹具数据和脚本化的假模型
```

### 项目结构

```
finagent/
  edgar.py        SEC 客户端：股票代码查询、companyfacts、年度数值提取
  tools.py        模型可见的工具 schema + 执行工具的分发器
  calculator.py   安全算术（AST 白名单）
  guardrails.py   数字提取与溯源
  agent.py        工具调用循环、步数上限、修订轮次
evals/            问题集 + 评分脚本
tests/            单元测试，无需网络或 API key
```

### 已知局限

- “财年” = 报告期结束时所在的日历年。对于财年在二月初结束的零售商，这一年
  通常被标为前一年；由于总会显示报告期日期，智能体可以准确说明所指的期间。
- 营业收入采用三个 XBRL 概念中第一个可用的。对少数公司而言，合同收入概念只
  覆盖了总收入的一部分。
- 拒答评审是由 Claude 给 Claude 打分，尚未与人工标注进行校验。
- 护栏会标记答案中公式里写出的常数（如 "… × 100" 中的 `100`）。在修订一轮后，
  答案有时会提到这次更正（"You're right: I converted…"）。

### 路线图

- [ ] 将评测扩充到约 50 个问题，包括多公司对比
- [x] 用 LLM 作为评审判定拒答
- [ ] 用 LLM 作为评审评估答案质量
- [ ] 消融实验：有/无 `calculate`，有/无护栏
- [ ] 基于 10-K 文本（风险因素、业务描述）的检索，使用向量数据库，并与无检索
      基线对比
