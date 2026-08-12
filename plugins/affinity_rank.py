"""
Affinity Leaderboard Plugin (好感度排行榜)
--------------------------------------
Global top-N affinity ranking. Display names come from profile nicknames
when available; otherwise user ids are masked for privacy. Read-only.
"""

import logging

from config import get_platform
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["好感度排行榜", "好感度排行", "好感排行", "好感度榜"]
_name = "好感度排行榜"
_man = "好感度排行榜：查看和 Nemo 关系最好的前 10 名用户。发送「好感度排行」即可。"
_tool_description = "查询全局好感度排行榜（top 10）：谁和你（bot）的关系最好。当用户想看排行榜、想知道谁好感度最高、自己排第几时调用。"
_enabled = 1

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _mask(uid: str) -> str:
    u = str(uid)
    return u if len(u) <= 4 else f"{u[:2]}***{u[-2:]}"


def render_rank(rows: list, my_uid: str, profile_store) -> str:
    lines = ["┏━━━━━━━━━━━━━━━━━━", "┃ 🏆 Nemo 好感度排行榜"]
    my_rank = None
    for i, r in enumerate(rows, 1):
        nickname = (profile_store.get(r["uid"]) or {}).get("nickname") or _mask(r["uid"])
        me = ""
        if str(r["uid"]) == str(my_uid):
            my_rank = i
            me = " ← 你"
        medal = MEDALS.get(i, f"{i:2d}.")
        lines.append(f"┃ {medal} {nickname} {r['score']:.1f} · {r['level']}{me}")
    if my_rank is None:
        lines.append("┃ （你还没有上榜，多来聊天吧～）")
    lines.append("┗━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict) -> None:
    from store.plugin_store import get_plugin_state_store
    from store.affinity_store import AffinityStore
    from store.profile_store import ProfileStore

    state_store, warning = get_plugin_state_store()
    if warning:
        message.reply(f"⚠️ {warning}")
        return

    platform = get_platform(message.frontend)
    link_key = f"{platform}:{message.context.user_id}"
    my_uid = state_store.get("user_link", "global", link_key, default=message.context.user_id)

    profile_store = ProfileStore(state_store)
    store = AffinityStore(state_store, profile_store=profile_store)
    rows = store.leaderboard(top_n=10)
    if not rows:
        message.reply("排行榜还是空的，快来和 Nemo 聊天抢占第一名吧～")
        return
    message.reply(render_rank(rows, my_uid, profile_store))
