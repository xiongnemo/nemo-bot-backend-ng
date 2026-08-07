"""
Affinity Plugin (好感度查询)
--------------------------
Lets a user query their affinity score with the bot. Read-only: the score
shown includes lazy decay but is never persisted here, because plugins run
in worker processes and all affinity writes stay in the main process.
"""

import logging

from config import backend_config, get_platform
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["查询我的好感度", "查询好感度", "我的好感度", "好感度"]
_name = "好感度系统"
_man = (
    "好感度系统：和 nemo-bot 聊天互动可以慢慢提升好感度，长期不理它会缓慢回落，"
    "惹它生气还会扣分。\n用法：发送「好感度」「我的好感度」「查询好感度」即可查询当前分数和关系等级。"
)
_tool_description = "查询当前用户与你（bot）之间的好感度分数、关系等级和互动统计。当用户想知道你对 ta 的好感、关系亲密程度或好感度分数时调用。"
_enabled = 1

BAR_WIDTH = 10


def _render_bar(score: float) -> str:
    ratio = max(0.0, min(1.0, score / 100.0))
    filled = round(ratio * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


@generic_exception_handler
def bot_execute(message: Message, config: dict) -> None:
    from store.database import Database
    from store.state_store import StateStore
    from store.affinity_store import AffinityStore

    db = Database(backend_config.get("database", {}).get("path", "data/nemo.sqlite"))
    state_store = StateStore(db)

    # Normalize cross-platform identity (the command path does not go through
    # the agent runner, so we resolve the primary uid here ourselves).
    platform = get_platform(message.frontend)
    link_key = f"{platform}:{message.context.user_id}"
    uid = state_store.get("user_link", "global", link_key, default=message.context.user_id)

    store = AffinityStore(state_store)
    st = store.get_state(uid)
    score = st["score"]

    lines = [
        f"💗 {message.context.user_name or uid} 与 Nemo 的好感度",
        f"{_render_bar(score)} {score:.1f}/100",
        f"关系等级：{st['level']}",
        f"累计互动：{st.get('total_interactions', 0)} 次",
    ]
    history = st.get("history") or []
    if history:
        last = history[-1]
        lines.append(f"最近变动：{last.get('delta', 0):+.1f}（{last.get('reason', '未知')}）")
    message.reply("\n".join(lines))
