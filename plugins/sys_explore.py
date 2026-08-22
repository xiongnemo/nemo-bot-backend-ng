"""
System Exploration Plugin
------------------------
Allows manual or scheduled triggering of Bilibili meme harvesting and lore ingestion.
"""

from core.message import Message
from utilities import generic_exception_handler
import logging

logger = logging.getLogger(__name__)

# ===========================
# 强制性模块变量 (Required)
# ===========================
_name = "全网热梗自主探索"
_command = ["explore", "收割热梗", "自动探索", "打捞热梗"]
_man = "用法:\n/explore - 自动探索 B 站热门榜单神评，提纯并沉淀到「赛博群友」语料库\n/explore <BV号> - 针对指定 B 站视频抓取高赞神评并注入人设库"
_enabled = True

_tool_description = "从 B 站热门榜单或指定视频中打捞高赞神评与网络热梗，自动提纯并沉淀更新到「赛博群友」人设语料库。"
_parameters = {
    "type": "object",
    "properties": {
        "bvid": {
            "type": "string",
            "description": "可选的 B 站视频 BV 号（如 BV1GJ411x7h7）。若不填则默认扫描全站热门榜单。",
        },
    },
}


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from agent.exploration_job import run_exploration_job
    import re
    import json

    args_str = (message.request.args or "").strip()
    target_bvid = ""

    # Parse args or JSON tool args
    if args_str.startswith("{"):
        try:
            data = json.loads(args_str)
            target_bvid = data.get("bvid", "").strip()
        except json.JSONDecodeError:
            pass
    elif args_str:
        # Check if user passed a BV id or URL
        m = re.search(r"BV[0-9a-zA-Z]{10}", args_str)
        if m:
            target_bvid = m.group(0)

    # Let user know exploration has started
    target_desc = f"指定视频 ({target_bvid})" if target_bvid else "B 站全站热门榜单"
    message.reply(f"[Nemo] 正在启动全网热梗探索引擎，正在扫描 {target_desc} 并提纯高赞神评，请稍候…… 🚀")

    res = run_exploration_job(target_bvid=target_bvid)

    if not res.get("ok"):
        err_msg = res.get("msg", "未知错误")
        reply_text = f"500: nemo: 热梗探索与提纯失败: {err_msg}"
    else:
        distilled = res.get("distilled", {})
        phrases = distilled.get("new_catchphrases", [])
        memes = distilled.get("new_memes", [])

        lines = [
            f"🎉 【全网热梗探索完成】",
            f"- 扫描视频: {len(res.get('videos', []))} 个",
            f"- 新增切口: {res.get('added_phrases_count', 0)} 条",
            f"- 新增神回复场景: {res.get('added_memes_count', 0)} 个",
        ]

        if phrases:
            lines.append("\n【新增流行切口】")
            for p in phrases[:4]:
                lines.append(f"  • {p}")

        if memes:
            lines.append("\n【新增实战神回复】")
            for m in memes[:2]:
                lines.append(f"  • 【{m.get('situation')}】: {m.get('quote')}")

        lines.append("\n✨ 已自动沉淀至 `personas/cyber_mate_lore.md` 并完成人格库热重载！")
        reply_text = "\n".join(lines)

    message.reply(reply_text)
    return reply_text
