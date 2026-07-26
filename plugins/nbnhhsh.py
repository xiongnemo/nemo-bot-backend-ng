import requests
from core.message import Message
from utilities import generic_exception_handler

_command = ["nbnhhsh"]
_name = "能不能好好说话"
_man = """https://lab.magiconch.com/nbnhhsh/
用法: {0} <要解释的缩写>
例如: {0} ymfm
"""
_tool_description = (
    "网络缩写翻译工具。将中文拼音首字母缩写翻译成完整的词组。"
    "参数(query)传入需要翻译的缩写字母（如 ymfm, yyds, xswl）。"
    "返回该缩写可能代表的完整含义。"
)
_enabled = 1


def _lookup(query: str) -> str:
    """Query the nbnhhsh API and return formatted results."""
    data = {"text": query}
    r = requests.post(
        "https://lab.magiconch.com/api/nbnhhsh/guess",
        json=data,
        timeout=10,
    )
    r.raise_for_status()
    results = r.json()

    if not results:
        return "nemo 听不懂呢"

    entry = results[0]
    lines = []

    if entry.get("trans"):
        lines.append(f"{query} 应该是：")
        for t in entry["trans"]:
            lines.append(t)
    elif entry.get("inputting") and len(entry["inputting"]):
        lines.append(f"{query} 可能是：")
        for t in entry["inputting"]:
            lines.append(t)
    else:
        return "nemo 听不懂呢"

    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        message.reply("请输入要翻译的缩写，例如: nbnhhsh ymfm")
        return

    result = _lookup(query)
    message.reply(result)
