"""
System Exploration Plugin
------------------------
Allows manual or scheduled triggering of Bilibili meme harvesting, topic-targeted exploration, and dynamic topic management.
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
    "1. 执行探索:\n"
    "  /explore - 自动探索当前所有常驻话题的热度最高爆款与神评\n"
    "  /explore <话题1> <话题2>... - 即时探索指定话题（如 /explore 黑神话 原神 炒股）\n"
    "  /explore <BV号> - 针对指定 B 站视频抓取高赞神评并注入人设库\n"
    "2. 常驻话题管理:\n"
    "  /explore topic list - 查看当前所有夜间自动探索的常驻话题\n"
    "  /explore topic add <话题> - 添加新的夜间常驻探索话题\n"
    "  /explore topic remove <话题> - 移除指定的常驻探索话题"
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
    from agent.exploration_job import (
        run_exploration_job,
        get_all_exploration_topics,
        add_dynamic_topic,
        remove_dynamic_topic,
    )
    import re
    import json

    args_str = (message.request.args or "").strip()

    # --- Topic Management Subcommands ---
    if args_str.startswith("topic") or args_str.startswith("话题"):
        parts = args_str.split(maxsplit=2)
        subcmd = parts[1].lower() if len(parts) > 1 else "list"
        param = parts[2].strip() if len(parts) > 2 else ""

        if subcmd in ("list", "查看", "列表"):
            all_topics = get_all_exploration_topics()
            topic_lines = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(all_topics)])
            reply_text = f"📋 【当前夜间常驻探索话题列表】\n{topic_lines}\n\n💡 提示: 发送 `/explore topic add <话题>` 可随时添加新话题！"
            message.reply(reply_text)
            return reply_text

        elif subcmd in ("add", "添加", "新增"):
            if not param:
                reply_text = "400: nemo: 请提供要添加的话题名称，例如 `/explore topic add 考研 考公`"
                message.reply(reply_text)
                return reply_text
            new_topics = [t.strip() for t in re.split(r"[\s,，]+", param) if t.strip()]
            for nt in new_topics:
                add_dynamic_topic(nt)
            all_topics = get_all_exploration_topics()
            topic_lines = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(all_topics)])
            reply_text = f"✅ 已成功添加常驻探索话题: {', '.join(new_topics)}\n\n📋 【更新后的常驻话题列表】\n{topic_lines}"
            message.reply(reply_text)
            return reply_text

        elif subcmd in ("remove", "delete", "del", "rm", "删除", "移除"):
            if not param:
                reply_text = "400: nemo: 请提供要移除的话题名称，例如 `/explore topic remove 炒股`"
                message.reply(reply_text)
                return reply_text
            remove_dynamic_topic(param)
            all_topics = get_all_exploration_topics()
            topic_lines = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(all_topics)])
            reply_text = f"🗑️ 已移除常驻探索话题: {param}\n\n📋 【当前常驻话题列表】\n{topic_lines}"
            message.reply(reply_text)
            return reply_text

    # --- Direct Exploration Execution ---
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
        all_t = get_all_exploration_topics()
        target_desc = f"常驻话题 ({', '.join(all_t)}) 的热度最高视频"

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
