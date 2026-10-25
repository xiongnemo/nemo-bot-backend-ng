"""
Calculator Plugin
-----------------
Safely evaluates mathematical expressions for chat users and agents.
Supports basic arithmetic, exponentiation, parentheses, and common math functions.
"""

import logging
import math
from asteval import Interpreter

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# Mandatory Plugin Attributes
# ===========================
_name = "计算器"
_command = ["calc", "计算器"]
_man = """计算器。
用法:
  /calc <数学表达式>
示例:
  /calc 9.6*1.8*6.66-30
  /calc 2^10
  /calc sqrt(16) + (10 - 2) * 3
  /calc sin(pi / 2) + log10(100)
支持常用的四则运算、幂运算(^ 或 **)、括号以及常见数学函数与常数(sqrt, abs, round, sin, cos, tan, log, log10, exp, pi, e)。
"""
_tool_description = (
    "数学表达式计算器。用于快速计算纯数学公式、四则运算、三角函数或幂运算等数值结果。"
    "参数可直接传入纯数学表达式字符串，如 '9.6*1.8*6.66-30'。"
)
_enabled = 1

MATH_SYMBOLS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
    "abs": abs,
    "round": round,
    "pow": pow,
}


def evaluate_expression(expr: str) -> str:
    """Evaluate a mathematical expression string safely."""
    raw = expr.strip()
    if not raw:
        return "400: nemo: 请输入要计算的数学表达式。\n示例: calc 9.6*1.8*6.66-30"

    # Pre-process ^ to ** for power operations
    sanitized = raw.replace("^", "**")

    aeval = Interpreter(
        usersyms=MATH_SYMBOLS,
        use_numpy=False,
        no_for=True,
        no_while=True,
        no_try=True,
        no_functiondef=True,
        no_if=True,
        no_assert=True,
        no_delete=True,
        no_raise=True,
        no_print=True,
    )

    try:
        res = aeval(sanitized)
    except Exception as e:
        logger.warning("Calc exception for %r: %s", raw, e)
        return f"400: nemo: 表达式计算异常: {e}"

    if aeval.error:
        err = aeval.error[0].get_error()
        err_msg = str(err[1]) if isinstance(err, tuple) and len(err) > 1 else str(err)
        # Clean traceback if multiline
        if "\n" in err_msg:
            err_msg = err_msg.strip().split("\n")[-1]
        logger.info("Calc syntax/eval error for %r: %s", raw, err_msg)
        return f"400: nemo: 计算错误: {err_msg}"

    if res is None:
        return "400: nemo: 表达式无有效返回结果。"

    if isinstance(res, (int, float)):
        if isinstance(res, float):
            res = round(res, 12)
            if res.is_integer():
                res = int(res)
        return str(res)

    return str(res)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    result = evaluate_expression(args)
    message.reply(result)
