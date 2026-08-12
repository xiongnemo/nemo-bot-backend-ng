"""
Affinity Plugin (好感度查询) v2
---------------------------
Renders a black-frame progress card with level, streak, milestones and a
"today's gains" breakdown. Read-only: plugins run in worker processes, all
affinity writes stay in the main process.
"""

import logging

from config import get_platform
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["查询我的好感度", "查询好感度", "我的好感度", "好感度"]
_name = "好感度系统"
_man = (
    "好感度系统 v2：和 Nemo 互动会积累好感度——\n"
    "· 每日第一次互动 +2，连续互动有 streak 加成 🔥\n"
    "· 聊天互动持续加分（有冷却和每日上限，刷屏没用）\n"
    "· 分享个人信息（生日/爱好等）、达成互动里程碑有大额奖励\n"
    "· 生日当天互动有惊喜 🎂\n"
    "· 让 Nemo 开心/生气会实时加减分；超过 3 天不理它会慢慢降温\n"
    "发送「好感度」查看你的好感度卡片和今日明细。"
)
_tool_description = "查询当前用户与你（bot）之间的好感度卡片：分数、关系等级、连续互动天数、今日加分明细。当用户想知道你对 ta 的好感、关系等级或今天赚了多少好感度时调用。"
_enabled = 1

BAR_WIDTH = 10


def _render_bar(score: float) -> str:
    ratio = max(0.0, min(1.0, score / 100.0))
    filled = round(ratio * BAR_WIDTH)
    return "⬛" * filled + "⬜" * (BAR_WIDTH - filled)


def render_card(display_name: str, st: dict) -> str:
    score = st["score"]
    lines = [
        "┏━━━━━━━━━━━━━━━━━━",
        f"┃ 💗 {display_name} × Nemo",
        f"┃ {_render_bar(score)} {score:.1f}/100",
        f"┃ 关系等级：{st['level']} Lv.{st['lv']}",
    ]
    nxt = st.get("next_level")
    if nxt:
        lines.append(f"┃ 距离「{nxt['name']}」还差 {nxt['need']} 分")
    streak_days = (st.get("streak") or {}).get("days", 0)
    total = st.get("total_interactions", 0)
    lines.append(f"┃ 连续互动：{streak_days} 天 🔥 ｜ 累计 {total} 次")
    trend = st.get("trend_scores") or []
    if len(trend) >= 2:
        from store.affinity_store import render_sparkline
        lines.append(f"┃ 近{len(trend)}日走势 {render_sparkline(trend)}")
    titles = st.get("titles") or []
    if titles:
        lines.append(f"┃ 称号：{'、'.join(titles[:3])}")
    weekly = st.get("weekly") or {}
    ch = weekly.get("challenge")
    if ch:
        if weekly.get("done"):
            lines.append(f"┃ 周挑战：{ch['name']} ✅")
        else:
            lines.append(f"┃ 周挑战：{ch['name']}（{weekly.get(ch['metric'], 0)}/{ch['target']}，奖励+{ch['reward']:.0f}）")

    lines.append("┣━━━━━━━━━━━━━━━━━━")
    daily = st.get("daily", {})
    today_total = st.get("today_total", 0)
    if today_total:
        lines.append(f"┃ 今日 {today_total:+.1f}")
        for e in daily.get("events", []):
            pts = e.get("pts", 0)
            lines.append(f"┃ ✓ {e.get('note', '')}" + (f" +{pts}" if pts else ""))
        chat_gain = float(daily.get("chat_gain", 0.0))
        if chat_gain:
            lines.append(f"┃ ✓ 聊天互动 +{chat_gain:.1f}")
        llm_delta = float(daily.get("llm_delta", 0.0))
        if llm_delta:
            lines.append(f"┃ {'✓' if llm_delta > 0 else '✗'} Nemo 的心情 {llm_delta:+.1f}")
        refl = float(daily.get("reflection_delta", 0.0))
        if refl:
            lines.append(f"┃ ✓ 夜间回顾 {refl:+.1f}")
    else:
        lines.append("┃ 今日还没有互动收获，快来聊天吧～")

    history = st.get("history") or []
    if history:
        last = history[-1]
        lines.append(f"┃ 最近变动：{last.get('delta', 0):+.1f}（{last.get('reason', '未知')}）")
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

    # Normalize cross-platform identity (command path bypasses the agent runner)
    platform = get_platform(message.frontend)
    link_key = f"{platform}:{message.context.user_id}"
    uid = state_store.get("user_link", "global", link_key, default=message.context.user_id)

    store = AffinityStore(state_store, profile_store=ProfileStore(state_store))
    st = store.get_state(uid)
    timeline = store.get_timeline(uid, days=7)
    st["trend_scores"] = [t["end_score"] for t in timeline] + [round(st["score"], 1)]
    message.reply(render_card(message.context.user_name or str(uid), st))
