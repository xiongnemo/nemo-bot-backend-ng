"""
System Exploration Plugin
------------------------
Allows manual or scheduled triggering of Bilibili meme harvesting, topic-targeted exploration, and lore ingestion.
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
_man = (
    "用法:\n"
    "/explore - 自动探索 B 站配置话题/全站热门榜单神评，提纯并沉淀到「赛博群友」语料库\n"
    "/explore <话题1> <话题2>... - 针对指定话题搜索播放量/热度最高的视频并提取热梗与总结\n"
    "/explore <BV号> - 针对指定 B 站视频抓取高赞神评并注入人设库"
)
_enabled = True

_tool_description = "从 B 站按指定话题（如黑神话、炒股、打工人、原神）搜索播放量与热度最高的爆款视频，提取高赞神评、热点总结与流行语，自动沉淀更新到「赛博群友」人设语料库。"
_parameters = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要探索的目标话题/关键词列表（如 [\"炒股\", \"原神\", \"打工人 摸鱼\"]）。系统将自动搜索该话题下热度最高的爆款视频并总结。",
        },
        "bvid": {
            "type": "string",
            "description": "可选的指定 B 站视频 BV 号（如 BV1GJ411x7h7）。",
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
    topics = []

    # 1. Parse JSON tool args or plain text
    if args_str.startswith("{"):
        try:
            data = json.loads(args_str)
            target_bvid = data.get("bvid", "").strip()
            raw_topics = data.get("topics", [])
            if isinstance(raw_topics, list):
                topics = [str(t).strip() for t in raw_topics if str(t).strip()]
            elif isinstance(raw_topics, str):
                topics = [t.strip() for t in raw_topics.replace("，", ",").split(",") if t.strip()]
        except json.JSONDecodeError:
            pass
    elif args_str:
        # Check if user passed a BV id
        m = re.search(r"BV[0-9a-zA-Z]{10}", args_str)
        if m:
            target_bvid = m.group(0)
        else:
            # Split by space, comma or Chinese comma
            raw_list = re.split(r"[\s,，]+", args_str)
            topics = [t.strip() for t in raw_list if t.strip()]

    # 2. Inform user
    if target_bvid:
        target_desc = f"指定视频 ({target_bvid})"
    elif topics:
        target_desc = f"指定话题 ({', '.join(topics)}) 的热度最高视频"
    else:
        target_desc = "默认关注话题与全站热门榜单"

    message.reply(f"[Nemo] 正在启动全网热点探索引擎，正在打捞 {target_desc} 并提纯高赞神评，请稍候…… 🚀")

    # 3. Run exploration
    res = run_exploration_job(target_bvid=target_bvid, topics=topics if topics else None)

    if not res.get("ok"):
        err_msg = res.get("msg", "未知错误")
        reply_text = f"500: nemo: 热点探索与提纯失败: {err_msg}"
    else:
        distilled = res.get("distilled", {})
        phrases = distilled.get("new_catchphrases", [])
        memes = distilled.get("new_memes", [])
        summaries = distilled.get("topic_summaries", [])

        lines = [
            f"🎉 【全网热点与热梗探索完成】",
            f"- 探索话题: {', '.join(res.get('topics', []))}",
            f"- 扫描爆款视频: {len(res.get('videos', []))} 个",
            f"- 新增切口: {res.get('added_phrases_count', 0)} 条",
            f"- 新增神回复场景: {res.get('added_memes_count', 0)} 个",
        ]

        if summaries:
            lines.append("\n📌 【话题核心热议焦点】")
            for s in summaries:
                lines.append(f"  • [{s.get('topic')}]: {s.get('summary')}")

        if phrases:
            lines.append("\n💬 【流行黑话与切口】")
            for p in phrases[:4]:
                lines.append(f"  • {p}")

        if memes:
            lines.append("\n🔥 【实战神回复场景】")
            for m in memes[:2]:
                lines.append(f"  • 【{m.get('situation')}】: {m.get('quote')}")

        lines.append("\n✨ 已自动沉淀至 `personas/cyber_mate_lore.md` 并完成人格库热重载！")
        reply_text = "\n".join(lines)

    message.reply(reply_text)
    return reply_text
