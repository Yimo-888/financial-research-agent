import pytest

from finagent.calculator import CalculatorError, calculate


def test_arithmetic():
    assert calculate('(120 - 100) / 100 * 100') == 20
    assert calculate('-3 + 2 ** 3') == 5
    assert calculate('1,000 / 4') == 250


@pytest.mark.parametrize('expr', [
    '__import__("os").system("ls")',
    'open("x")',
    'a + 1',
    '[1, 2]',
])
def test_rejects_anything_but_arithmetic(expr):
    with pytest.raises(CalculatorError):
        calculate(expr)


def test_division_by_zero_and_huge_exponent():
    with pytest.raises(CalculatorError):
        calculate('1 / 0')
    with pytest.raises(CalculatorError):
        calculate('10 ** 100000')
