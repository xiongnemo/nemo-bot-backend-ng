"""
Builtin Tools — Context exploration functions for the agent.
"""

from __future__ import annotations

from core.message import Message
from nemollm.types import ToolDefinition
from store.message_store import MessageStore
from store.state_store import StateStore
from runtime.sender import Sender
import json
import logging
logger = logging.getLogger(__name__)


# 1. Search Chat History
SEARCH_HISTORY_DEF = ToolDefinition(
    name="search_chat_history",
    description="在当前群聊或私聊的历史消息中全文搜索。当需要查找某人说过什么、或者之前讨论过的特定话题时使用。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词（支持空格分隔多词）"},
            "limit": {"type": "integer", "description": "返回最多结果条数", "default": 10},
        },
        "required": ["query"],
    },
)

def search_history_executor(args: dict, msg: Message, store: MessageStore) -> dict:
    query = args.get("query", "")
    limit = args.get("limit", 10)
    group_id = msg.context.group_id
    
    # We only search within the current group for privacy
    # (If group_id is empty, it's a DM, we search globally but could restrict to user_id)
    results = store.search(query, group_id=group_id, limit=limit)
    
    if not results:
        return {"result": f"未找到包含 '{query}' 的消息。"}
    
    formatted = []
    for r in results:
        sender = r.get("user_name") or r.get("user_id") or "Unknown"
        formatted.append(f"[{r.get('created_at')}] {sender}: {r.get('text')}")
        
    return {"result": "\n".join(formatted)}


# 2. Get Recent Messages
RECENT_MESSAGES_DEF = ToolDefinition(
    name="get_recent_messages",
    description="获取当前群聊或私聊最近的聊天记录。用于了解当前的对话上下文、刚才是谁在说话。",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "返回多少条最新消息", "default": 20},
        },
    },
)

def recent_messages_executor(args: dict, msg: Message, store: MessageStore) -> dict:
    limit = args.get("limit", 20)
    
    results = store.recent(group_id=msg.context.group_id, user_id=msg.context.user_id, limit=limit)
    
    if not results:
        return {"result": "暂无近期消息。"}
        
    formatted = []
    for r in results:
        sender = r.get("user_name") or r.get("user_id") or "Unknown"
        msg_id_info = f" [msg_id: {r.get('message_id')}]" if r.get('message_id') else ""
        formatted.append(f"[{r.get('created_at')}]{msg_id_info} {sender}: {r.get('text')}")
        
    return {"result": "\n".join(formatted)}



# 3. Memory Tools
REMEMBER_FACT_DEF = ToolDefinition(
    name="remember_fact",
    description="主动将关于当前用户或当前群组的重要事实写入长期记忆。当你认为某个信息对未来的对话有长期价值时（例如用户的名字、喜好、群组规则等），务必调用此工具进行保存。",
    parameters={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["user", "group"], "description": "记忆的生效范围。如果是用户的个人信息选 user，如果是群组的公共规则选 group。"},
            "fact": {"type": "string", "description": "需要记住的具体事实，尽量精简准确。"}
        },
        "required": ["scope", "fact"]
    }
)

def remember_fact_executor(args: dict, msg: Message, store: StateStore) -> dict:
    scope_type = args.get("scope", "user")
    fact = args.get("fact", "").strip()
    
    if not fact:
        return {"result": "记录失败：事实内容不能为空。"}

    from store.affinity_store import is_affinity_stat_text
    if is_affinity_stat_text(fact):
        return {"result": "拒绝记录：好感度/亲密度分数是实时变化的动态数据，不允许写入长期记忆（会造成陈旧数字污染）。需要分数时请调用 query_affinity 工具实时获取。"}
        
    if scope_type == "group" and msg.context.group_id:
        scope_key = f"group_{msg.context.group_id}"
    else:
        scope_key = f"user_{msg.context.user_id}"
        
    facts = store.get("memory", scope_key, "facts", default=[])
    if fact not in facts:
        facts.append(fact)
        store.set("memory", scope_key, "facts", facts)
        return {"result": f"已成功记入长期记忆 ({scope_type}): {fact}"}
    return {"result": f"该事实已存在于长期记忆中 ({scope_type})。"}

FORGET_FACT_DEF = ToolDefinition(
    name="forget_fact",
    description="从长期记忆中删除不再准确或用户要求遗忘的事实。",
    parameters={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["user", "group"], "description": "记忆的作用域"},
            "fact": {"type": "string", "description": "需要被删除的具体事实（需要精确匹配）"}
        },
        "required": ["scope", "fact"]
    }
)

# 5. Think / Brainstorm
THINK_DEF = ToolDefinition(
    name="think",
    description="用于分段思考。当你需要进行复杂推理、长篇规划或避免超时崩溃时，请将你的中间思考过程写在这里。每次思考不要输出过长，可以分多次调用。",
    parameters={
        "type": "object",
        "properties": {
            "thought": {"type": "string", "description": "你当前的思考过程或计划的一小部分。"}
        },
        "required": ["thought"]
    }
)

def forget_fact_executor(args: dict, msg: Message, store: StateStore) -> dict:
    scope_type = args.get("scope", "user")
    fact = args.get("fact", "").strip()
    
    if scope_type == "group" and msg.context.group_id:
        scope_key = f"group_{msg.context.group_id}"
    else:
        scope_key = f"user_{msg.context.user_id}"
        
    facts = store.get("memory", scope_key, "facts", default=[])
    if fact in facts:
        facts.remove(fact)
        store.set("memory", scope_key, "facts", facts)
        return {"result": f"已成功从长期记忆 ({scope_type}) 中删除: {fact}"}
    return {"result": f"找不到该事实，无法删除 ({scope_type})。请确保精确匹配。"}


# 6. User Profile & Affinity
UPDATE_PROFILE_DEF = ToolDefinition(
    name="update_profile",
    description="更新当前用户的结构化画像档案。当你在对话中感知到用户的称呼偏好、职业、生日、爱好、性格特点或其他值得备注的信息时，主动调用此工具记录。画像严格按用户隔离，只影响当前对话用户。",
    parameters={
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "enum": ["nickname", "occupation", "birthday", "hobbies", "personality", "notes"],
                "description": "画像字段：nickname 称呼偏好 / occupation 职业 / birthday 生日 / hobbies 爱好 / personality 性格 / notes 备注",
            },
            "action": {
                "type": "string",
                "enum": ["set", "append", "remove"],
                "description": "set: 覆盖设置；append: 向列表字段追加；remove: 删除某项或清除字段",
            },
            "value": {"type": "string", "description": "字段内容，精简准确。"},
        },
        "required": ["field", "action", "value"],
    },
)

def update_profile_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.profile_store is None:
        return {"error": "画像系统未启用。"}
    field = args.get("field", "")
    action = args.get("action", "append")
    result = context.profile_store.apply(
        msg.context.user_id, field, action, args.get("value", ""),
    )
    # Sharing personal info is a rewarded affinity event (once per field, ever)
    if action in ("set", "append") and result.startswith("已更新") and context.affinity_store is not None:
        try:
            bonus = context.affinity_store.grant_profile_share(msg.context.user_id, field)
            if bonus:
                result += f"（好感度 +{bonus:.0f}：感谢分享！）"
        except Exception:
            logger.exception("profile share bonus failed")
    return {"result": result}


QUERY_AFFINITY_DEF = ToolDefinition(
    name="query_affinity",
    description="查询你对当前用户的实时好感度：分数、关系等级、连续互动天数、今日加分明细。当用户询问好感度/分数/关系/今天赚了多少好感度时，必须调用此工具获取实时数据后再回答，严禁凭记忆或历史对话里的旧数字作答。",
    parameters={"type": "object", "properties": {}},
)

def query_affinity_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    st = context.affinity_store.get_state(msg.context.user_id)
    daily = st.get("daily", {})
    events = [f"{e.get('note', '')} +{e.get('pts', 0)}" for e in daily.get("events", [])]
    chat_gain = float(daily.get("chat_gain", 0.0))
    if chat_gain:
        events.append(f"聊天互动 +{chat_gain:.1f}")
    llm_delta = float(daily.get("llm_delta", 0.0))
    if llm_delta:
        events.append(f"情绪调整 {llm_delta:+.1f}")
    result = {
        "score": round(st["score"], 1),
        "level": f"{st['level']} Lv.{st['lv']}",
        "streak_days": (st.get("streak") or {}).get("days", 0),
        "total_interactions": st.get("total_interactions", 0),
        "today_total": st.get("today_total", 0),
        "today_breakdown": events or ["今日暂无收获"],
    }
    nxt = st.get("next_level")
    if nxt:
        result["next_level"] = f"距离「{nxt['name']}」还差 {nxt['need']} 分"
    if st.get("titles"):
        result["titles"] = st["titles"]
    weekly = st.get("weekly") or {}
    ch = weekly.get("challenge")
    if ch:
        progress = weekly.get(ch["metric"], 0)
        status = "✅ 已达成" if weekly.get("done") else f"{progress}/{ch['target']}"
        result["weekly_challenge"] = f"{ch['name']}（{status}，奖励 +{ch['reward']:.0f}）"
    return {"result": result}


QUERY_AFFINITY_HISTORY_DEF = ToolDefinition(
    name="query_affinity_history",
    description="查询当前用户好感度的变动历史：近几天的分数趋势图、每一笔加减分流水（时间/原因/来源）、按当前速度的升级预测。当用户想知道好感度是怎么变的、为什么涨/掉了、要多久升级时调用。",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "回看天数，1-30，默认 7"},
        },
    },
)

def query_affinity_history_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    from datetime import datetime
    from store.affinity_store import render_sparkline
    days = max(1, min(int(args.get("days") or 7), 30))
    store = context.affinity_store
    uid = msg.context.user_id
    st = store.get_state(uid)
    timeline = store.get_timeline(uid, days=days)

    result: dict = {"current_score": round(st["score"], 1), "level": f"{st['level']} Lv.{st['lv']}"}

    scores = [t["end_score"] for t in timeline] + [round(st["score"], 1)]
    if len(scores) >= 2:
        result["trend"] = f"{render_sparkline(scores)} （{scores[0]} → {scores[-1]}，近{len(scores)}个数据点）"
    daily_rollups = [
        f"{t['date']}: 收盘 {t['end_score']}（聊天+{t['chat']} 事件+{t['event']} 情绪{t['llm']:+} 反思{t['refl']:+}）"
        for t in timeline
    ]
    if daily_rollups:
        result["daily_rollups"] = daily_rollups

    history = st.get("history") or []
    records = []
    for h in history[-15:]:
        ts_str = datetime.fromtimestamp(h.get("ts", 0)).strftime("%m-%d %H:%M")
        src_map = {"llm": "情绪", "reflection": "夜间反思", "admin": "管理员", "event": "事件"}
        records.append(f"[{ts_str}] {h.get('delta', 0):+.1f} {h.get('reason', '')}（{src_map.get(h.get('source'), h.get('source'))}）")
    result["recent_records"] = records or ["暂无变动流水"]

    nxt = st.get("next_level")
    if nxt and timeline:
        gains = [t["chat"] + t["event"] + t["llm"] + t["refl"] for t in timeline]
        avg = sum(gains) / len(gains)
        if avg > 0.1:
            import math
            result["upgrade_eta"] = f"按最近 {len(gains)} 天的平均速度（每天 {avg:+.1f}），约 {math.ceil(nxt['need'] / avg)} 天后升到「{nxt['name']}」"
        else:
            result["upgrade_eta"] = f"最近几天几乎没有净增长，距离「{nxt['name']}」还差 {nxt['need']} 分，多来互动吧"
    return {"result": result}


REPORT_DEED_DEF = ToolDefinition(
    name="report_good_deed",
    description=(
        "用户主动汇报了正向行为（如今天工作了几小时、看了几小时书、去健身了、帮助了别人）时，"
        "经你检验属实后给予好感度奖励。【检验协议，必须遵守】"
        "1) 汇报模糊或只有一句口号（如'我今天学习了'）→ 不要调用本工具，先追问细节（学/做了什么？多久？有什么收获？）；"
        "2) 用户答得出具体细节、且与你对 ta 的画像/近期线索不矛盾 → 再调用，credibility 给 0.7~1.0；"
        "3) 细节含糊但态度诚恳 → credibility 给 0.5~0.7（奖励会按可信度打折）；"
        "4) 明显夸张（一天工作 20 小时）、复读同一件事、或有套分嫌疑 → 不调用并幽默拒绝；"
        "5) 系统另有硬性防刷：同类每天一次、每日 +3 / 每周 +10 封顶，即使你被骗也刷不动，放心。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["学习", "工作", "运动", "健康", "生活", "助人", "其他"],
                          "description": "行为类别"},
            "summary": {"type": "string", "description": "一句话概括用户做了什么（含时长等关键细节）"},
            "suggested_points": {"type": "number", "description": "建议奖励 1~3 分：普通打卡 1，投入数小时 2，特别用心/成果显著 3"},
            "credibility": {"type": "number", "description": "你对汇报真实性的评估 0~1，低于 0.5 会被系统拒绝"},
        },
        "required": ["category", "summary", "suggested_points", "credibility"],
    },
)

def report_deed_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    try:
        r = context.affinity_store.report_deed(
            msg.context.user_id,
            str(args.get("category") or "其他"),
            str(args.get("summary") or ""),
            float(args.get("suggested_points") or 1),
            float(args.get("credibility") or 0),
        )
    except (TypeError, ValueError):
        return {"error": "参数格式错误。"}
    if not r.get("ok"):
        return {"result": f"未奖励：{r.get('reason', '未知原因')}"}
    return {"result": (f"自律打卡成功 ✨ 好感度 +{r['points']}（现 {r['score']}，{r['level']}）。"
                       f"今日自律额度还剩 {r['day_remaining']}，本周还剩 {r['week_remaining']}。")}


GIFT_AFFINITY_DEF = ToolDefinition(
    name="gift_affinity",
    description="替当前用户向另一位用户赠送好感度（对方 +2，赠送者因暖心 +1）。当用户明确表达想把好感度送给某人/请某人喝奶茶之类的赠礼意图时调用。限制：赠送者需达到「熟悉」等级，每天只能送一次。",
    parameters={
        "type": "object",
        "properties": {
            "target_user_id": {"type": "string", "description": "接收方用户 ID（QQ号）。群聊里可以从发言前缀 (ID: xxx) 获取。"},
        },
        "required": ["target_user_id"],
    },
)

def gift_affinity_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    target = str(args.get("target_user_id") or "").strip()
    if not target:
        return {"error": "缺少 target_user_id。"}
    r = context.affinity_store.gift(msg.context.user_id, target)
    if not r.get("ok"):
        return {"result": f"赠礼失败：{r.get('reason', '未知原因')}"}
    return {"result": f"赠礼成功 🎁 对方好感度 +{r['received']:.0f}（现 {r['target_score']}），你也因为暖心 +1（现 {r['giver_score']}）。"}


ADJUST_AFFINITY_DEF = ToolDefinition(
    name="adjust_affinity",
    description="微调你对当前用户的好感度。仅当用户的言行让你产生明显情绪波动时调用：温暖/贴心/有趣的举动加分（正数），无礼/冒犯/恶意的言行扣分（负数）。单次幅度 ±5 以内，每日总额受限。平淡的日常对话不要调用。",
    parameters={
        "type": "object",
        "properties": {
            "delta": {"type": "number", "description": "好感度变化量，范围 -5 到 +5。"},
            "reason": {"type": "string", "description": "调整原因，简短一句话。"},
        },
        "required": ["delta", "reason"],
    },
)

def adjust_affinity_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    try:
        delta = float(args.get("delta", 0))
    except (TypeError, ValueError):
        return {"error": "delta 必须是数字。"}
    reason = (args.get("reason") or "").strip() or "未说明"
    r = context.affinity_store.adjust(msg.context.user_id, delta, reason, source="llm")
    return {
        "result": f"好感度已调整 {r['applied_delta']:+.1f}（原因：{reason}）。当前 {r['score']:.1f}/100，关系等级：{r['level']}。"
    }

def think_executor(args: dict, msg: Message, sender: Sender = None, state_store: StateStore = None) -> dict:
    thought = args.get("thought", "")
    if sender and state_store:
        try:
            gid = msg.context.group_id
            uid = msg.context.user_id
            scope_key = f"agent:{msg.frontend}:group:{gid}" if gid else f"agent:{msg.frontend}:dm:{uid}"
            verbose_level = state_store.get("agent", "verbose_level", scope_key, default=0)
            if verbose_level >= 1:
                sender.send_text(msg.to_dict(), f"202: nemo: {thought}", reply=True)
        except Exception:
            pass
    return {"result": f"思考已记录 (Length: {len(thought)} chars)。"}

SEND_MESSAGE_DEF = ToolDefinition(
    name="send_message",
    description="向用户发送文本消息。可以用于执行长任务时的进度汇报，或者主动开启新话题。",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要发送的消息内容"},
            "is_reply": {"type": "boolean", "description": "是否以回复的形式发送（如果是针对用户的请求，选true；如果是独立的新提醒/汇报，选false）", "default": True}
        },
        "required": ["text"]
    }
)

def send_message_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    text = args.get("text", "")
    is_reply = args.get("is_reply", True)
    if sender:
        sender.send_text(msg.to_dict(), text, reply=is_reply)
    return {"result": f"消息已发送。"}

ADD_REMINDER_DEF = ToolDefinition(
    name="send_delayed_message",
    description="设置一个一次性定时提醒。经过指定的时间后，系统会直接把消息发送给用户。（警告：这个工具仅仅是当复读机给用户发消息，绝对不会唤醒你！如果你需要在未来执行查询或任何操作，必须使用 schedule_agent_delay_job，否则任务会失败！）",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "多久之后触发（天数，必须大于等于0）", "default": 0, "minimum": 0},
            "hours": {"type": "integer", "description": "多久之后触发（小时数，必须大于等于0）", "default": 0, "minimum": 0},
            "minutes": {"type": "integer", "description": "多久之后触发（分钟数，必须大于等于0）", "default": 0, "minimum": 0},
            "message": {"type": "string", "description": "提醒时发送的内容"}
        },
        "required": ["message"]
    }
)

def add_reminder_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    from datetime import datetime, timedelta
    import uuid
    from scheduler.jobs import user_notification_job
    try:
        days = int(args.get("days", 0))
        hours = int(args.get("hours", 0))
        minutes = int(args.get("minutes", 0))
        if days < 0 or hours < 0 or minutes < 0:
            return {"error": "时间间隔不能为负数 (days, hours, or minutes)"}
        if days == 0 and hours == 0 and minutes == 0:
            return {"error": "必须设置一个大于0的时间间隔 (days, hours, or minutes)"}
        run_time = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes)
    except Exception as e:
        return {"error": f"Invalid delay_minutes format: {e}"}
    
    job_id = f"reminder_{uuid.uuid4().hex[:8]}"
    scheduler.add_date_job(job_id, user_notification_job, run_time, message_dict=msg.to_dict(), text=args.get("message", ""), is_reply=True)
    return {"result": f"已成功设置提醒，将于 {run_time.strftime('%Y-%m-%d %H:%M:%S')} 触发。任务ID: {job_id}"}

ADD_CRON_DEF = ToolDefinition(
    name="send_recurring_message",
    description="设置一个周期性的定时任务。触发时会自动发送消息给用户。（警告：这仅仅是复读机发消息，绝对不会唤醒你！如果你需要在未来循环执行查询等操作，必须使用 schedule_agent_cron_job，否则任务会失败！）",
    parameters={
        "type": "object",
        "properties": {
            "cron_expr": {"type": "string", "description": "标准 Cron 表达式，如 '0 16 * * *'"},
            "message": {"type": "string", "description": "提醒时发送的内容"}
        },
        "required": ["cron_expr", "message"]
    }
)

def add_cron_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    import uuid
    from scheduler.jobs import user_notification_job
    cron_expr = args.get("cron_expr", "")
    
    job_id = f"cron_{uuid.uuid4().hex[:8]}"
    try:
        scheduler.add_cron_job(job_id, user_notification_job, cron_expr, message_dict=msg.to_dict(), text=args.get("message", ""), is_reply=False)
    except Exception as e:
        return {"error": f"Invalid cron expression: {e}"}
    return {"result": f"已成功设置周期任务。Cron: {cron_expr}。任务ID: {job_id}"}

LIST_JOBS_DEF = ToolDefinition(
    name="list_jobs",
    description="列出当前用户/群聊的所有已设定的定时提醒和周期任务。",
    parameters={"type": "object", "properties": {}}
)
def list_jobs_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    jobs = scheduler.scheduler.get_jobs()
    if not jobs:
        return {"result": "当前没有任何定时任务。"}
    
    lines = []
    for j in jobs:
        lines.append(f"- ID: {j.id} | Trigger: {j.trigger} | Next Run: {j.next_run_time}")
    return {"result": "当前任务列表：\n" + "\n".join(lines)}

DELETE_JOB_DEF = ToolDefinition(
    name="delete_job",
    description="删除/取消一个指定的定时任务。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "要删除的任务 ID"}
        },
        "required": ["job_id"]
    }
)
def delete_job_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    job_id = args.get("job_id")
    if not job_id:
        return {"error": "Missing job_id"}
        
    if str(job_id).startswith("system:"):
        return {"result": "拒绝访问：这是一个内置的系统级守护进程。若要修改或停止，请联系超级管理员修改底层代码或配置。"}
    
    job = scheduler.scheduler.get_job(job_id)
    if not job:
        return {"error": f"找不到任务ID: {job_id}"}
        
    scheduler.scheduler.remove_job(job_id)
    return {"result": f"成功删除任务: {job_id}"}

# ======================================================================
# Agent Autonomy Tools (Self-Scheduling)
# ======================================================================

def trigger_agent_task(frontend: str, context: dict, prompt: str, task_id: str):
    """Called by APScheduler to trigger the agent automatically."""
    try:
        from runtime import context as rt_context
        agent_runner = rt_context.agent_runner
        executor = rt_context.executor
        from core.message import Message
        import time
        
        # Inject the task_id into the prompt so the agent has context
        enriched_prompt = f"[定时任务/Cron Job 触发: {task_id}]\n{prompt}"
        
        msg_dict = {
            "frontend": frontend,
            "context": context,
            "request": {"command": "agent_chat", "args": enriched_prompt},
            # Dummy fields required by Message/Sender
            "message_id": f"trigger_{task_id}",
            "time": int(time.time()),
            "type": "group" if context.get("group_id") else "private",
        }
        
        def run_and_send():
            msg = Message(msg_dict)
            msg.role = "user"
            msg.text = enriched_prompt
            msg.timestamp = time.time()
            
            actions = agent_runner.run(msg, enriched_prompt)
            rt_context.sender.deliver_actions(msg_dict, actions)
            
        executor.submit_dispatch(run_and_send)
    except Exception as e:
        logger.error(f"Failed to trigger agent task {task_id}: {e}")

SCHEDULE_AGENT_CRON_DEF = ToolDefinition(
    name="schedule_agent_cron_job",
    description="给自己（Agent）设定一个基于 Cron 表达式的定时任务。时间到了之后，系统会自动用设定的 Prompt 唤醒你，并将你处理后的结果发送回当前群聊。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "定时任务的唯一ID"},
            "cron_expr": {"type": "string", "description": "Cron表达式，如 '0 9 * * *' (每天早上9点)"},
            "prompt": {"type": "string", "description": "唤醒你时系统会向你发送的指令内容。如: '请去搜索昨晚的美股新闻并总结发出来'"}
        },
        "required": ["job_id", "cron_expr", "prompt"]
    }
)
def schedule_agent_cron_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    job_id = args.get("job_id")
    cron_expr = args.get("cron_expr")
    prompt = args.get("prompt")
    
    if not job_id or not cron_expr or not prompt:
        return {"error": "Missing parameters"}
        
    context = {"group_id": msg.context.group_id, "user_id": msg.context.user_id}
    
    try:
        scheduler.add_cron_job(
            job_id,
            trigger_agent_task,
            cron_expr,
            frontend=msg.frontend,
            context=context,
            prompt=prompt,
            task_id=job_id
        )
        return {"result": f"成功为你设定 Cron 任务 [{job_id}]，计划时间 [{cron_expr}]。"}
    except Exception as e:
        return {"error": str(e)}

SCHEDULE_AGENT_INTERVAL_DEF = ToolDefinition(
    name="schedule_agent_interval_job",
    description="给自己（Agent）设定一个间隔执行的任务。时间到了之后，系统会自动用设定的 Prompt 唤醒你，并将你处理后的结果发送回当前群聊。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "定时任务的唯一ID"},
            "minutes": {"type": "integer", "description": "间隔的分钟数", "default": 0},
            "hours": {"type": "integer", "description": "间隔的小时数", "default": 0},
            "prompt": {"type": "string", "description": "唤醒你时系统会向你发送的指令内容。"}
        },
        "required": ["job_id", "prompt"]
    }
)
def schedule_agent_interval_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    job_id = args.get("job_id")
    minutes = args.get("minutes", 0)
    hours = args.get("hours", 0)
    prompt = args.get("prompt")
    
    if not job_id or not prompt or (minutes == 0 and hours == 0):
        return {"error": "Missing parameters or invalid interval"}
        
    context = {"group_id": msg.context.group_id, "user_id": msg.context.user_id, "message_id": msg.context.message_id}
    
    try:
        scheduler.add_interval_job(
            job_id,
            trigger_agent_task,
            minutes=minutes,
            hours=hours,
            frontend=msg.frontend,
            context=context,
            prompt=prompt,
            task_id=job_id
        )
        return {"result": f"成功为你设定间隔任务 [{job_id}]，间隔 {hours}小时 {minutes}分钟。"}
    except Exception as e:
        return {"error": str(e)}


SPAWN_SUBAGENT_DEF = ToolDefinition(
    name="spawn_subagent",
    description="立刻派发一个后台子代理(Subagent)去执行耗时或复杂的研究任务。它会在后台静默运行，不会阻塞当前群聊/私聊的对话。当它运行完毕后，会自动将结果总结并发送回当前聊天上下文。用于应对'帮我搜集一份报告'等需要大量时间和步骤的任务。",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "你给这个子代理派发的详尽任务指令（相当于你对它说的 prompt）"}
        },
        "required": ["prompt"]
    }
)

def spawn_subagent_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    prompt = args.get("prompt")
    if not prompt:
        return {"error": "Missing prompt"}
        
    try:
        from runtime import context as rt_context
        agent_runner = rt_context.agent_runner
        executor = rt_context.executor
        import time
        from core.message import Message
        import uuid
        
        task_id = f"subagent_{uuid.uuid4().hex[:8]}"
        enriched_prompt = f"[后台子代理任务: {task_id}]\n{prompt}"
        
        msg_dict = {
            "frontend": msg.frontend,
            "context": {
                "group_id": msg.context.group_id,
                "user_id": msg.context.user_id,
                "message_id": msg.context.message_id
            },
            "request": {"command": "agent_chat", "args": enriched_prompt},
            "message_id": f"trigger_{task_id}",
            "time": int(time.time()),
            "type": "group" if msg.context.group_id else "private",
        }
        
        def run_and_send():
            m = Message(msg_dict)
            m.role = "user"
            m.text = enriched_prompt
            m.timestamp = time.time()
            
            actions = agent_runner.run(m, enriched_prompt)
            rt_context.sender.deliver_actions(msg_dict, actions)
            
        executor.submit_dispatch(run_and_send)
        return {"result": f"已成功启动后台子代理 (ID: {task_id})。它将在后台执行任务并自动把结果发回这里。"}
    except Exception as e:
        return {"error": str(e)}

SCHEDULE_AGENT_DELAY_DEF = ToolDefinition(
    name="schedule_agent_delay_job",
    description="给自己（Agent）设定一个一次性的延时任务。经过指定时间后，系统会自动用设定的 Prompt 唤醒你，并将你处理后的结果发送回当前群聊。用于“X分钟/小时后帮我做某事”。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "定时任务的唯一ID"},
            "days": {"type": "integer", "description": "多久之后触发（天数）", "default": 0, "minimum": 0},
            "hours": {"type": "integer", "description": "多久之后触发（小时数）", "default": 0, "minimum": 0},
            "minutes": {"type": "integer", "description": "多久之后触发（分钟数）", "default": 0, "minimum": 0},
            "prompt": {"type": "string", "description": "唤醒你时系统会向你发送的指令内容。"}
        },
        "required": ["job_id", "prompt"]
    }
)
def schedule_agent_delay_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    from datetime import datetime, timedelta
    job_id = args.get("job_id")
    days = int(args.get("days", 0))
    hours = int(args.get("hours", 0))
    minutes = int(args.get("minutes", 0))
    prompt = args.get("prompt")
    
    if not job_id or not prompt:
        return {"error": "Missing job_id or prompt"}
    if days < 0 or hours < 0 or minutes < 0:
        return {"error": "时间间隔不能为负数"}
    if days == 0 and hours == 0 and minutes == 0:
        return {"error": "必须设置一个大于0的时间间隔"}
        
    run_time = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes)
    context = {"group_id": msg.context.group_id, "user_id": msg.context.user_id, "message_id": msg.context.message_id}
    
    try:
        scheduler.add_date_job(
            job_id,
            trigger_agent_task,
            run_time,
            frontend=msg.frontend,
            context=context,
            prompt=prompt,
            task_id=job_id
        )
        return {"result": f"成功为你设定一次性延时任务 [{job_id}]，将于 {run_time.strftime('%Y-%m-%d %H:%M:%S')} 触发。"}
    except Exception as e:
        logger.error(f"Error in schedule_agent_delay_executor: {e}", exc_info=True)
        return {"error": str(e)}

SCHEDULE_AGENT_AT_TIME_DEF = ToolDefinition(
    name="schedule_agent_at_time_job",
    description="给自己（Agent）设定一个指定绝对时间的定时任务。时间到了之后，系统会自动用设定的 Prompt 唤醒你，并将你处理后的结果发送回当前群聊。用于“在今天下午2点帮我做某事”等指定时刻的任务。注意：你必须严格将时间格式化为 'YYYY-MM-DD HH:MM:SS'。绝对不要使用口语化时间！",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "定时任务的唯一ID"},
            "target_time": {"type": "string", "description": "任务触发的绝对时间，必须严格采用格式：YYYY-MM-DD HH:MM:SS (例如：2026-07-03 14:00:00)"},
            "prompt": {"type": "string", "description": "唤醒你时系统会向你发送的指令内容。"}
        },
        "required": ["job_id", "target_time", "prompt"]
    }
)
def schedule_agent_at_time_executor(args: dict, msg: Message, sender: Sender = None, scheduler=None) -> dict:
    if not scheduler: return {"error": "Scheduler not available"}
    from datetime import datetime
    job_id = args.get("job_id")
    target_time_str = args.get("target_time")
    prompt = args.get("prompt")
    
    if not job_id or not prompt or not target_time_str:
        return {"error": "Missing job_id, target_time or prompt"}
        
    try:
        run_time = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return {"error": f"target_time 格式错误。收到了 '{target_time_str}'，但必须严格为 'YYYY-MM-DD HH:MM:SS'"}
        
    if run_time < datetime.now():
        return {"error": "设定的时间不能早于当前时间！"}
        
    context = {"group_id": msg.context.group_id, "user_id": msg.context.user_id, "message_id": msg.context.message_id}
    
    try:
        scheduler.add_date_job(
            job_id,
            trigger_agent_task,
            run_time,
            frontend=msg.frontend,
            context=context,
            prompt=prompt,
            task_id=job_id
        )
        return {"result": f"成功为你设定绝对时间任务 [{job_id}]，将于 {run_time.strftime('%Y-%m-%d %H:%M:%S')} 准时触发。"}
    except Exception as e:
        logger.error(f"Error in schedule_agent_at_time_executor: {e}", exc_info=True)
        return {"error": str(e)}

# ======================================================================
# Feed Hub Tools
# ======================================================================

ADD_CHANNEL_DEF = ToolDefinition(
    name="add_channel",
    description="在系统中新增一个资讯频道。用于后续接收外部脚本的新闻推送。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "频道唯一名称（如 jinshi, cctv）"},
            "description": {"type": "string", "description": "该频道的详细描述"}
        },
        "required": ["name"]
    }
)

def add_channel_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    name = args.get("name")
    description = args.get("description", "")
    if not name:
        return {"error": "Missing channel name"}
    try:
        from runtime import context
        conn = context.db.get_conn()
        conn.execute("INSERT INTO channels (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
        return {"result": f"频道 {name} 创建成功。"}
    except Exception as e:
        return {"error": str(e)}


LIST_CHANNELS_DEF = ToolDefinition(
    name="list_channels",
    description="列出系统中所有已注册的资讯频道及其描述。",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)

def list_channels_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    try:
        from runtime import context
        conn = context.db.get_conn()
        cur = conn.execute("SELECT name, description FROM channels")
        channels = cur.fetchall()
        if not channels:
            return {"result": "当前没有注册任何频道。"}
        result = "当前系统中的资讯频道如下：\n"
        for c in channels:
            desc = c['description'] or "无描述"
            result += f"- {c['name']}: {desc}\n"
        return {"result": result.strip()}
    except Exception as e:
        return {"error": str(e)}

UPDATE_CHANNEL_DEF = ToolDefinition(
    name="update_channel",
    description="更新一个已有频道的描述信息。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "要更新的频道名称"},
            "description": {"type": "string", "description": "新的频道描述"}
        },
        "required": ["name", "description"]
    }
)

def update_channel_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    name = args.get("name")
    description = args.get("description")
    if not name or description is None:
        return {"error": "Missing name or description"}
    try:
        from runtime import context
        conn = context.db.get_conn()
        # Check if exists
        cur = conn.execute("SELECT id FROM channels WHERE name = ?", (name,))
        if not cur.fetchone():
            return {"error": f"频道 {name} 不存在"}
        conn.execute("UPDATE channels SET description = ? WHERE name = ?", (description, name))
        conn.commit()
        return {"result": f"频道 {name} 描述更新成功。"}
    except Exception as e:
        return {"error": str(e)}

SEARCH_FEEDS_DEF = ToolDefinition(
    name="search_feeds",
    description="在资讯库中按关键词和频道搜索历史新闻。注意：新闻有时会是英文，因此建议同时使用中英双语关键词。支持高级搜索语法：空格表示 AND（同时包含），竖线 | 表示 OR（或者包含）。例如 '海力士 美股 | SK Hynix' 匹配 (包含海力士且包含美股) 或者 (包含SK且包含Hynix)。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词。空格代表AND，|代表OR。"},
            "channel_name": {"type": "string", "description": "限制搜索某个特定频道 (可选)"},
            "limit": {"type": "integer", "description": "返回条数", "default": 5}
        },
        "required": ["query"]
    }
)

def search_feeds_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    query = args.get("query", "")
    channel_name = args.get("channel_name", "")
    limit = args.get("limit", 5)
    
    try:
        from runtime import context
        conn = context.db.get_conn()
        sql = "SELECT id, channel_name, title, content, created_at FROM feeds WHERE 1=1"
        params = []
        
        if query and query != "*":
            or_groups = [g.strip() for g in query.split('|') if g.strip()]
            if not or_groups:
                or_groups = [query]
            
            group_sqls = []
            for group in or_groups:
                keywords = group.split()
                if not keywords: continue
                kw_sqls = []
                for kw in keywords:
                    kw_sqls.append("(title LIKE ? OR content LIKE ?)")
                    params.extend([f"%{kw}%", f"%{kw}%"])
                group_sqls.append("(" + " AND ".join(kw_sqls) + ")")
                
            if group_sqls:
                sql += " AND (" + " OR ".join(group_sqls) + ")"
            
        if channel_name:
            sql += " AND channel_name = ?"
            params.append(channel_name)
        sql += " ORDER BY original_time DESC LIMIT ?"
        params.append(limit)
        
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall()
        if not rows:
            return {"result": "没有找到相关资讯。"}
            
        results = []
        for r in rows:
            results.append(f"ID: {r['id']} | [{r['channel_name']}] {r['title']}\n正文: {r['content']}")
        
        # We add a hidden flag _is_feed_search so runner.py can intercept this specific tool
        return {"result": "\n\n".join(results), "_is_feed_search": True, "_feed_results": results}
    except Exception as e:
        return {"error": str(e)}

GET_FEED_BY_ID_DEF = ToolDefinition(
    name="get_feed_by_id",
    description="通过新闻的唯一 ID 获取该条资讯的完整正文内容。当 search_feeds 仅返回标题时，可使用此工具获取详情。",
    parameters={
        "type": "object",
        "properties": {
            "feed_id": {"type": "integer", "description": "要查询的新闻 ID"}
        },
        "required": ["feed_id"]
    }
)

MERGE_CHANNELS_DEF = ToolDefinition(
    name="merge_channels",
    description="将源频道(source)合并到目标频道(target)。这会将源频道的所有新闻和订阅转移到目标频道，然后删除源频道。",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "要被合并并删除的频道"},
            "target": {"type": "string", "description": "保留下来的目标频道"}
        },
        "required": ["source", "target"]
    }
)

def merge_channels_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    source = args.get("source")
    target = args.get("target")
    if not source or not target:
        return {"error": "Missing source or target"}
    if source == target:
        return {"error": "Source and target must be different"}
    try:
        from runtime import context
        conn = context.db.get_conn()
        cur = conn.execute("SELECT id FROM channels WHERE name = ?", (source,))
        if not cur.fetchone():
            return {"error": f"源频道 {source} 不存在"}
            
        cur = conn.execute("SELECT id FROM channels WHERE name = ?", (target,))
        if not cur.fetchone():
            return {"error": f"目标频道 {target} 不存在"}
            
        # Update feeds
        conn.execute("UPDATE feeds SET channel_name = ? WHERE channel_name = ?", (target, source))
        # Update subscriptions
        conn.execute("UPDATE subscriptions SET channel_name = ? WHERE channel_name = ?", (target, source))
        # Delete source channel
        conn.execute("DELETE FROM channels WHERE name = ?", (source,))
        conn.commit()
        return {"result": f"成功将频道 {source} 合并至 {target}。"}
    except Exception as e:
        return {"error": str(e)}

SUBSCRIBE_CHANNEL_DEF = ToolDefinition(
    name="subscribe_channel",
    description="让当前群聊订阅某个资讯频道，并设置关注的关键词。命中关键词的新闻将会被推送到当前群聊。",
    parameters={
        "type": "object",
        "properties": {
            "channel_name": {"type": "string", "description": "要订阅的频道名称。如果需要订阅所有频道，请传入 'all'。"},
            "keywords": {"type": "string", "description": "关键词列表，多个用逗号分隔。只有命中关键词的新闻才会推送。"}
        },
        "required": ["channel_name", "keywords"]
    }
)

def subscribe_channel_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    channel_name = args.get("channel_name")
    keywords = args.get("keywords")
    if not channel_name or not keywords:
        return {"error": "Missing parameters"}
        
    target_group = f"{msg.frontend}:{msg.context.group_id}" if msg.context.group_id else f"{msg.frontend}:{msg.context.user_id}"
    
    try:
        from runtime import context
        conn = context.db.get_conn()
        if channel_name.lower() == "all":
            cur = conn.execute("SELECT name FROM channels")
            channels = [row["name"] for row in cur.fetchall()]
            if not channels:
                return {"error": "系统内当前没有任何频道。"}
            for ch in channels:
                conn.execute("DELETE FROM subscriptions WHERE channel_name = ? AND target_group = ?", (ch, target_group))
                conn.execute(
                    "INSERT INTO subscriptions (channel_name, target_group, keywords) VALUES (?, ?, ?)",
                    (ch, target_group, keywords)
                )
            conn.commit()
            return {"result": f"成功在所有 {len(channels)} 个频道上更新了订阅关键词: {keywords}"}
        else:
            # Check single channel
            cur = conn.execute("SELECT id FROM channels WHERE name = ?", (channel_name,))
            if not cur.fetchone():
                return {"error": f"频道 {channel_name} 不存在"}
                
            conn.execute("DELETE FROM subscriptions WHERE channel_name = ? AND target_group = ?", (channel_name, target_group))
            conn.execute(
                "INSERT INTO subscriptions (channel_name, target_group, keywords) VALUES (?, ?, ?)",
                (channel_name, target_group, keywords)
            )
            conn.commit()
            return {"result": f"成功订阅(并覆盖)频道 {channel_name}，当前关键词: {keywords}"}
    except Exception as e:
        return {"error": str(e)}



UNSUBSCRIBE_CHANNEL_DEF = ToolDefinition(
    name="unsubscribe_channel",
    description="让当前群聊退订（取消订阅）某个资讯频道，停止接收其推送。",
    parameters={
        "type": "object",
        "properties": {
            "channel_name": {"type": "string", "description": "要退订的频道名称。如果需要退订所有频道，请传入 'all'。"}
        },
        "required": ["channel_name"]
    }
)

def unsubscribe_channel_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    channel_name = args.get("channel_name")
    if not channel_name:
        return {"error": "Missing channel_name"}
        
    target_group = f"{msg.frontend}:{msg.context.group_id}" if msg.context.group_id else f"{msg.frontend}:{msg.context.user_id}"
    
    try:
        from runtime import context
        conn = context.db.get_conn()
        
        if channel_name.lower() == "all":
            conn.execute("DELETE FROM subscriptions WHERE target_group = ?", (target_group,))
            conn.commit()
            return {"result": "已成功退订当前群聊的所有资讯频道。"}
        else:
            cur = conn.execute("SELECT id FROM subscriptions WHERE channel_name = ? AND target_group = ?", (channel_name, target_group))
            if not cur.fetchone():
                return {"result": f"当前群聊尚未订阅频道 {channel_name}，无需退订。"}
                
            conn.execute("DELETE FROM subscriptions WHERE channel_name = ? AND target_group = ?", (channel_name, target_group))
            conn.commit()
            return {"result": f"已成功退订频道 {channel_name}。"}
    except Exception as e:
        return {"error": str(e)}


LIST_MY_SUBSCRIPTIONS_DEF = ToolDefinition(
    name="list_my_subscriptions",
    description="查询当前群聊或私聊已经订阅的所有资讯频道及其关注的关键词。",
    parameters={"type": "object", "properties": {}}
)

def list_my_subscriptions_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    target_group = f"{msg.frontend}:{msg.context.group_id}" if msg.context.group_id else f"{msg.frontend}:{msg.context.user_id}"
    
    try:
        from runtime import context
        conn = context.db.get_conn()
        cur = conn.execute("SELECT channel_name, keywords FROM subscriptions WHERE target_group = ?", (target_group,))
        rows = cur.fetchall()
        
        if not rows:
            return {"result": "当前尚未订阅任何资讯频道。"}
            
        result = "当前群聊/私聊的订阅列表如下：\n"
        for r in rows:
            result += f"- 频道 [{r['channel_name']}], 关注关键词: {r['keywords']}\n"
        return {"result": result.strip()}
    except Exception as e:
        return {"error": str(e)}

def get_feed_by_id_executor(args: dict, msg: Message, sender: Sender = None) -> dict:
    feed_id = args.get("feed_id")
    if not feed_id:
        return {"error": "缺少 feed_id 参数"}
        
    try:
        from runtime import context
        conn = context.db.get_conn()
        cur = conn.execute("SELECT channel_name, title, content, original_time FROM feeds WHERE id = ?", (feed_id,))
        row = cur.fetchone()
        if not row:
            return {"error": f"找不到 ID 为 {feed_id} 的新闻。"}
            
        import time
        date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row["original_time"]))
        return {
            "result": f"标题: [{row['channel_name']}] {row['title']}\n时间: {date_str}\n\n{row['content']}"
        }
    except Exception as e:
        return {"error": str(e)}

def register_builtin_tools(registry, message_store: MessageStore, state_store: StateStore, scheduler=None):
    """Register all builtin tools with injected dependencies."""
    
    registry.register_builtin(
        SPAWN_SUBAGENT_DEF,
        lambda args, msg, sender: spawn_subagent_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        SEARCH_HISTORY_DEF,
        lambda args, msg, sender: search_history_executor(args, msg, message_store),
    )
    
    registry.register_builtin(
        RECENT_MESSAGES_DEF,
        lambda args, msg, sender: recent_messages_executor(args, msg, message_store),
    )

    registry.register_builtin(
        REMEMBER_FACT_DEF,
        lambda args, msg, sender: remember_fact_executor(args, msg, state_store),
    )

    registry.register_builtin(
        FORGET_FACT_DEF,
        lambda args, msg, sender: forget_fact_executor(args, msg, state_store),
    )

    registry.register_builtin(
        UPDATE_PROFILE_DEF,
        lambda args, msg, sender: update_profile_executor(args, msg),
    )

    registry.register_builtin(
        ADJUST_AFFINITY_DEF,
        lambda args, msg, sender: adjust_affinity_executor(args, msg),
    )

    registry.register_builtin(
        QUERY_AFFINITY_DEF,
        lambda args, msg, sender: query_affinity_executor(args, msg),
    )

    registry.register_builtin(
        QUERY_AFFINITY_HISTORY_DEF,
        lambda args, msg, sender: query_affinity_history_executor(args, msg),
    )

    registry.register_builtin(
        GIFT_AFFINITY_DEF,
        lambda args, msg, sender: gift_affinity_executor(args, msg),
    )

    registry.register_builtin(
        REPORT_DEED_DEF,
        lambda args, msg, sender: report_deed_executor(args, msg),
    )
    
    from config import backend_config
    if not backend_config.get("agent", {}).get("disable_think_tool", False):
        registry.register_builtin(
            THINK_DEF,
            lambda args, msg, sender: think_executor(args, msg, sender, state_store),
        )
    
    registry.register_builtin(
        SEND_MESSAGE_DEF,
        lambda args, msg, sender: send_message_executor(args, msg, sender),
    )
    registry.register_builtin(
        ADD_REMINDER_DEF,
        lambda args, msg, sender: add_reminder_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        ADD_CRON_DEF,
        lambda args, msg, sender: add_cron_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        LIST_JOBS_DEF,
        lambda args, msg, sender: list_jobs_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        DELETE_JOB_DEF,
        lambda args, msg, sender: delete_job_executor(args, msg, sender, scheduler),
    )
    
    # Agent Autonomy Tools
    registry.register_builtin(
        SCHEDULE_AGENT_CRON_DEF,
        lambda args, msg, sender: schedule_agent_cron_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        SCHEDULE_AGENT_INTERVAL_DEF,
        lambda args, msg, sender: schedule_agent_interval_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        SCHEDULE_AGENT_DELAY_DEF,
        lambda args, msg, sender: schedule_agent_delay_executor(args, msg, sender, scheduler),
    )
    registry.register_builtin(
        SCHEDULE_AGENT_AT_TIME_DEF,
        lambda args, msg, sender: schedule_agent_at_time_executor(args, msg, sender, scheduler),
    )
    
    # Feed Hub Tools
    registry.register_builtin(ADD_CHANNEL_DEF, add_channel_executor)
    registry.register_builtin(LIST_CHANNELS_DEF, list_channels_executor)
    registry.register_builtin(UPDATE_CHANNEL_DEF, update_channel_executor)
    registry.register_builtin(MERGE_CHANNELS_DEF, merge_channels_executor)
    registry.register_builtin(SUBSCRIBE_CHANNEL_DEF, subscribe_channel_executor)
    registry.register_builtin(UNSUBSCRIBE_CHANNEL_DEF, unsubscribe_channel_executor)
    registry.register_builtin(LIST_MY_SUBSCRIPTIONS_DEF, list_my_subscriptions_executor)
    registry.register_builtin(SEARCH_FEEDS_DEF, search_feeds_executor)
    registry.register_builtin(GET_FEED_BY_ID_DEF, get_feed_by_id_executor)
    
    from agent.skills import register_skills
    register_skills(registry)
