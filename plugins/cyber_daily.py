import os
import json
import random
import datetime
from core.message import Message
from utilities import generic_exception_handler

_command = ["赛博黄历", "每日主机", "黄历", "s390x"]
_name = "赛博黄历 & 每日主机"
_man = """John 的赛博黄历与每日 s390x 指令。
用法: {0}
每次调用同时返回今日赛博黄历（宜/忌）和你的每日 s390x 大型机指令。
"""
_tool_description = (
    "趣味工具：赛博黄历 + 每日主机。"
    "调用后同时返回今日程序员赛博黄历（宜/忌）和用户专属的每日 IBM s390x 大型机指令。"
    "无需传参。"
)
_enabled = 1

# --- Asset loading ---
_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

_langs = []
_langs_path = os.path.join(_BASE, "langs.txt")
if os.path.exists(_langs_path):
    with open(_langs_path, "r", encoding="utf-8") as f:
        _langs = [line.strip() for line in f if line.strip()]

_verbs = []
_verbs_path = os.path.join(_BASE, "Cal_verbs.txt")
if os.path.exists(_verbs_path):
    with open(_verbs_path, "r", encoding="utf-8") as f:
        _verbs = f.readlines()

_s390x_list = []
_s390x_path = os.path.join(_BASE, "s390x_instruction_list.json")
if os.path.exists(_s390x_path):
    with open(_s390x_path, encoding="utf-8") as f:
        _s390x_list = json.load(f)

# --- Optional lunar calendar ---
_lunar_available = False
try:
    from lunar_python import Lunar
    _lunar_available = True
except ImportError:
    pass


def _get_huangli() -> str:
    """Generate today's cyber almanac."""
    seed_str = str(datetime.date.today())
    random.seed(seed_str)

    if _lunar_available:
        today = Lunar.fromDate(datetime.datetime.now())
        header = today.toFullString()
    else:
        header = datetime.date.today().strftime("%Y年%m月%d日")

    picks = random.choices(_verbs, k=4)
    formatted = [t.format(lang=random.choice(_langs)) for t in picks]
    good = "".join(formatted[0:2])
    bad = "".join(formatted[2:4])

    return f"""{header}

宜:
{good}
忌:
{bad}"""


def _get_s390x(user_id: str) -> str:
    """Generate today's s390x instruction for the user."""
    current_date = datetime.date.today().strftime("%Y%m%d")
    random.seed(f"{current_date}{user_id}")
    instruction = random.choice(_s390x_list)
    lines = "\n".join(f"{key}: {value}" for key, value in instruction.items())
    return f"Your s390x instruction of the day!\n{lines}"


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    parts = []

    if _verbs and _langs:
        parts.append("📅 赛博黄历\n" + _get_huangli())
    if _s390x_list:
        parts.append("🖥️ 每日主机\n" + _get_s390x(message.context.user_id))

    if not parts:
        message.reply("404: nemo: 黄历/主机数据文件未找到。")
        return

    message.reply("\n\n---\n\n".join(parts))
