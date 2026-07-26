"""
Python Sandbox Plugin
-------------------
Evaluates Python expressions safely using asteval.
This plugin is loaded automatically by the ToolRegistry.
"""

import sys
import io
import json
import logging
from asteval import Interpreter

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "安全的数学与逻辑计算器"
_command = ["python_sandbox", "python_eval"]
_man = "用法: 供 Agent 内部工具调用"
_tool_description = "执行 Python 代码来计算数学公式、处理数据。不支持 import 等系统调用。代码可以包含变量定义，多行逻辑。你必须使用 print() 输出结果。只有 print() 的内容或直接返回的表达式结果会被提取！注意：请直接输出纯文本代码，绝对不要使用 ```python 这种 Markdown 代码块包裹！"
_enabled = 1

_parameters = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "要执行的纯 Python 代码段，必须用 print() 打印最终结果。请直接输出纯文本代码，严禁使用 ```python 等 Markdown 代码块包裹！",
        }
    },
    "required": ["code"],
}


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    try:
        args = json.loads(message.request.args)
        code = args.get("code", "").strip()
    except Exception:
        message.payload = {"error": "Invalid arguments format."}
        return

    if not code:
        message.payload = {"error": "Code cannot be empty."}
        return

    # Strip markdown code blocks if the LLM accidentally included them
    import re

    code = re.sub(r"^```[a-zA-Z]*\n", "", code)
    code = re.sub(r"```$", "", code).strip()

    # asteval creates a clean environment each time to be stateless
    # We create an io.StringIO to capture print output
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    aeval = Interpreter(writer=out_buf, err_writer=err_buf)

    try:
        res = aeval(code)
    except Exception as e:
        message.payload = {"error": f"Evaluation Exception: {str(e)}"}
        return

    # Check for asteval errors during AST execution
    if aeval.error:
        # aeval.error is a list of ExceptionHolder objects
        err_messages = [
            str(err.exc) if hasattr(err, "exc") else str(err) for err in aeval.error
        ]
        message.payload = {"error": "AST Error: " + "; ".join(err_messages)}
        return

    # Collect stdout and stderr
    stdout_str = out_buf.getvalue().strip()
    stderr_str = err_buf.getvalue().strip()

    result_dict = {}
    if stdout_str:
        result_dict["stdout"] = stdout_str
    if stderr_str:
        result_dict["stderr"] = stderr_str

    # If there is a return value from an expression (e.g., just '1+1' without print)
    if res is not None:
        result_dict["return_value"] = str(res)

    if not result_dict:
        result_dict["result"] = "Success, but no output produced."

    message.payload = result_dict
