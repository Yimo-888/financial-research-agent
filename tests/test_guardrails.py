from finagent.guardrails import extract_numbers, mentions_value, untraced_numbers

TOOLS = [
    {'values': [{'fiscal_year': 2023, 'value': 383285000000}]},
    {'expression': '169148000000 / 383285000000 * 100', 'result': 44.1311},
    {'values': [{'fiscal_year': 2023, 'value': -2104000000}]},
]


def test_scaled_dollar_amount_traces():
    assert untraced_numbers('Revenue was $383.3 billion in FY2023.', TOOLS) == []
    assert untraced_numbers('Revenue was $383,285 million.', TOOLS) == []


def test_percent_traces_to_calculator_result():
    assert untraced_numbers('Gross margin was 44.1%.', TOOLS) == []
    assert untraced_numbers('Gross margin was 44.13 percent.', TOOLS) == []


def test_loss_written_without_minus_sign():
    assert untraced_numbers('a net loss of $2.1 billion', TOOLS) == []


def test_made_up_numbers_are_flagged():
    assert untraced_numbers('Revenue was $400 billion and margin 52%.', TOOLS) == ['$400 billion', '52%']


def test_rounding_passes_but_close_wrong_numbers_do_not():
    # "383 billion" covers 382.5-383.5 billion; 383.285 is inside.
    assert untraced_numbers('$383 billion', TOOLS) == []
    # ~1.7% off the real value: outside both rounding and the 0.5% band.
    assert untraced_numbers('$390 billion', TOOLS) == ['$390 billion']


def test_scaled_amount_traces_to_calculator_result_already_in_that_scale():
    # calculate("(60922000000 - 26974000000) / 1000000000") returns 33.948.
    tools = [{'expression': '(60922000000 - 26974000000) / 1000000000', 'result': 33.948}]
    assert untraced_numbers('an increase of $33.948 billion', tools) == []


def test_scaled_amount_does_not_trace_to_a_small_edgar_value():
    # EDGAR values are always raw dollars, so "$6 billion" must not match EPS 5.8.
    tools = [{'values': [{'fiscal_year': 2023, 'value': 5.8}]}]
    assert untraced_numbers('$6 billion', tools) == ['$6 billion']


def test_years_dates_urls_and_small_counts_are_ignored():
    text = ('Over the 3 years from 2021 to 2023 (period ended 2023-09-30), see '
            'https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/ and Form 10-K.')
    assert extract_numbers(text) == []


def test_mentions_value():
    assert mentions_value('Revenue grew 125.9% year over year.', 125.85)
    assert not mentions_value('Revenue grew 12.6% year over year.', 125.85)


NVDA_TOOLS = [
    {'values': [{'fiscal_year': 2023, 'value': 26974000000}, {'fiscal_year': 2024, 'value': 60922000000}]},
    {'expression': '(60922000000 - 26974000000) / 26974000000 * 100', 'result': 125.8545},
]


def test_formula_constant_from_a_calculator_expression_traces():
    # The model wrote out the formula it had just run; the 100 is its own input.
    answer = '($60,922,000,000 − $26,974,000,000) ÷ $26,974,000,000 × 100 = 125.85%'
    assert untraced_numbers(answer, NVDA_TOOLS) == []


def test_number_with_a_unit_does_not_trace_to_an_expression_constant():
    # Only bare constants get this pass; "$100 billion" is a financial claim.
    assert untraced_numbers('Revenue was $100 billion.', NVDA_TOOLS) == ['$100 billion']


def test_bare_number_absent_from_every_expression_is_still_flagged():
    assert untraced_numbers('multiplied by 250', NVDA_TOOLS) == ['250']


BAC_TOOLS = [{'company': 'Bank of America', 'values': [{
    'fiscal_year': 2023, 'value': 2888505000000,
    'source': 'https://www.sec.gov/Archives/edgar/data/70858/000007085826000012/'}]}]


def test_identifier_copied_from_a_source_link_traces():
    # Real runs spent a revision round on the SEC company number (CIK).
    assert untraced_numbers('Bank of America (CIK 70858) had $2.89 trillion of liabilities.', BAC_TOOLS) == []


def test_number_with_a_unit_does_not_trace_to_a_source_link():
    assert untraced_numbers('Liabilities rose by $70,858 million.', BAC_TOOLS) == ['$70,858 million']


def test_bare_number_from_passage_text_is_not_an_identifier():
    tools = [{'passages': [{'id': 'EX-2023-1-p001', 'text': 'We employ 12500 people.'}],
              'source': 'https://www.sec.gov/Archives/edgar/data/1/2/ex.htm'}]
    assert untraced_numbers('It employs 12500 people.', tools) == ['12500']
