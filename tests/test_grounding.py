from finagent.grounding import appears_in, passages_in, quotes, strip_grounded, ungrounded

RESULTS = [
    {'ticker': 'AAPL', 'passages': [
        {'id': 'AAPL-2023-1A-p007', 'text': 'The Company’s business depends on outsourcing partners located in Asia.'},
    ]},
    {'revised': [{'new': {'id': 'AAPL-2024-1A-p009', 'text': 'Tariffs of 25% could raise costs materially.'},
                  'old': {'id': 'AAPL-2023-1A-p009', 'text': 'Trade disputes could raise costs.'}}]},
    {'expression': '1 + 1', 'result': 2},
]


def test_passages_are_found_at_any_depth():
    assert set(passages_in(RESULTS)) == {'AAPL-2023-1A-p007', 'AAPL-2024-1A-p009', 'AAPL-2023-1A-p009'}


def test_short_quoted_terms_are_not_evidence():
    assert quotes('It calls this "net sales" and says "depends on outsourcing partners".') == [
        'depends on outsourcing partners']


def test_quote_matches_despite_case_curly_quotes_and_markdown():
    assert appears_in("**The company's business** depends on outsourcing partners", [RESULTS[0]['passages'][0]['text']])


def test_bracketed_capital_edit_still_matches():
    assert appears_in('[T]he Company’s business depends on outsourcing', [RESULTS[0]['passages'][0]['text']])


def test_ellipsis_joins_parts_that_must_each_match():
    text = [RESULTS[0]['passages'][0]['text']]
    assert appears_in('The Company’s business depends ... partners located in Asia', text)
    assert not appears_in('The Company’s business depends ... partners located in Europe', text)


def test_paraphrase_in_quotes_is_ungrounded():
    answer = 'Apple warns that it "relies on a few partners in Asia" [AAPL-2023-1A-p007].'
    assert ungrounded(answer, RESULTS) == ['"relies on a few partners in Asia" is not in any retrieved passage']


def test_unknown_passage_id_is_ungrounded_once():
    answer = 'See [AAPL-2022-1A-p001] and again [AAPL-2022-1A-p001].'
    assert ungrounded(answer, RESULTS) == ['[AAPL-2022-1A-p001] is not a passage any tool returned']


def test_quote_from_memory_with_no_retrieval_is_ungrounded():
    assert ungrounded('The 10-K says "we face intense competition in all markets".', []) == [
        '"we face intense competition in all markets" is not in any retrieved passage']


def test_quoting_the_question_is_allowed():
    question = 'Is it true that Apple depends on a single supplier?'
    assert ungrounded('You asked whether "Apple depends on a single supplier".', [], question) == []


def test_grounded_answer_has_no_problems():
    answer = 'It "depends on outsourcing partners located in Asia" [AAPL-2023-1A-p007].'
    assert ungrounded(answer, RESULTS) == []


def test_strip_removes_verified_quotes_and_ids_but_keeps_other_text():
    answer = 'New in 2024: "Tariffs of 25% could raise costs" [AAPL-2024-1A-p009]. Margin fell 3.5%.'
    stripped = strip_grounded(answer, RESULTS)
    assert '25%' not in stripped and 'p009' not in stripped
    assert 'Margin fell 3.5%.' in stripped


def test_strip_keeps_unverified_quotes_so_their_numbers_are_checked():
    answer = 'It says "tariffs of 60% will apply to all imports".'
    assert strip_grounded(answer, RESULTS) == answer


def test_strip_keeps_short_quotes_so_a_bare_quoted_number_is_checked():
    assert '"25%"' in strip_grounded('Tariffs were "25%".', RESULTS)


def test_inner_quote_marks_may_change_style():
    # Nested double quotes become single quotes inside a quotation; that is
    # punctuation, not a misquote. Real runs were sent back for it.
    text = ['restrictions may encourage customers to “design-out” certain U.S. semiconductors']
    assert appears_in("encourage customers to 'design-out' certain U.S. semiconductors", text)
    assert not appears_in("encourage customers to 'design-in' certain U.S. semiconductors", text)
