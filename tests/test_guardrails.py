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


def test_years_dates_urls_and_small_counts_are_ignored():
    text = ('Over the 3 years from 2021 to 2023 (period ended 2023-09-30), see '
            'https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/ and Form 10-K.')
    assert extract_numbers(text) == []


def test_mentions_value():
    assert mentions_value('Revenue grew 125.9% year over year.', 125.85)
    assert not mentions_value('Revenue grew 12.6% year over year.', 125.85)
