"""
Arithmetic for the agent — LLMs are unreliable at multi-digit math, so every
derived number (margins, growth rates, differences) is computed here.

Parses the expression with `ast` and evaluates only numbers, + - * / ** and
parentheses. Never uses eval(): the expression comes from the model.
"""
import ast
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_EXPONENT = 100


class CalculatorError(Exception):
    pass


def _eval(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError('exponent too large')
        if isinstance(node.op, ast.Div) and right == 0:
            raise CalculatorError('division by zero')
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    raise CalculatorError(f'unsupported expression element: {type(node).__name__}')


def calculate(expression):
    try:
        tree = ast.parse(expression.replace(',', ''), mode='eval')
    except SyntaxError as exc:
        raise CalculatorError(f'cannot parse {expression!r}') from exc
    return _eval(tree.body)
