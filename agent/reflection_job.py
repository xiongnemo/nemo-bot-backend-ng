"""
Psychological Engine - Reflection Job
Runs in the background to summarize topics, extract core facts, distill user
profiles, and propose affinity adjustments from short-term memory. Also
prunes old short-term conversations after they have been reflected upon.
"""

import re
import time
import json
import logging

from config import get_reflection_model, get_reflection_retention_days

logger = logging.getLogger(__name__)

PROFILE_STR_FIELDS = {"nickname", "occupation", "birthday"}
PROFILE_LIST_FIELDS = {"hobbies", "personality", "notes"}

REFLECTION_PROMPT = """你是一个智能的“赛博群友”心理学引擎。你的任务是分析过去一段时间内聊天（群聊或私聊）的对话记录，并进行记忆提纯。

请仔细阅读下面提供的对话记录，提取出：
1. Topics (话题聚类)：大家讨论了哪几个主要话题？请将废话折叠，提取出最具代表性的话题。
2. Core Facts (核心事实)：提取关于用户的永久性事实（例如某人暴露了自己的职业、爱好、特殊经历，或者对某个事物强烈的喜恶）。如果没有，则留空。
3. Profile Updates (画像更新)：如果对话中明确暴露了某用户的结构化画像信息，请提取。field 只允许：nickname(称呼偏好)、occupation(职业)、birthday(生日)、hobbies(爱好)、personality(性格特点)、notes(备注)。没有则留空。
【禁止事项】Core Facts 和 Profile Updates 中严禁记录好感度/亲密度的具体分数（如"好感度69分"）——这类数值是实时变化的系统数据，写入记忆会造成污染。
4. Affinity Adjustments (好感度调整)：站在 bot 的视角回顾，如果某用户当天的言行整体上特别温暖友善（正分）或特别无礼恶劣（负分），给出 -3 到 +3 的整数调整建议。表现平淡的用户不要出现在列表里。没有则留空。

请务必以如下 JSON 格式返回，不要包含任何额外的 Markdown 标记（如 ```json）：
{
    "topics": ["大家探讨了塞尔达新作的购买意愿", "关于十路CPU服务器架构的技术探讨"],
    "core_facts": [
        {"user_id": "123456", "fact": "从事程序员职业，对服务器架构很了解"}
    ],
    "profile_updates": [
        {"user_id": "123456", "field": "occupation", "value": "程序员"},
        {"user_id": "789012", "field": "hobbies", "value": "塞尔达系列游戏"}
    ],
    "affinity_adjustments": [
        {"user_id": "789012", "delta": 2, "reason": "全天都在耐心帮助群友解答问题"}
    ]
}
"""


def _parse_reflection_json(resp_text: str) -> dict:
    text = resp_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _apply_reflection_data(data: dict, scope: str, state_store) -> tuple[int, int]:
    """Persist one batch of reflection output. Returns (n_topics, n_facts)."""
    from runtime import context

    topics = data.get("topics", []) or []
    core_facts = data.get("core_facts", []) or []
    profile_updates = data.get("profile_updates", []) or []
    affinity_adjustments = data.get("affinity_adjustments", []) or []

    # Mid-term topics
    for t in topics:
        if isinstance(t, str) and t.strip():
            context.topic_store.add(scope, t.strip())

    # Long-term facts (affinity stat numbers are volatile -> never persisted)
    from store.affinity_store import is_affinity_stat_text
    for fact_obj in core_facts:
        uid = fact_obj.get("user_id")
        fact_text = fact_obj.get("fact")
        if fact_text and is_affinity_stat_text(fact_text):
            logger.info("[Reflection] Dropping stale affinity-stat fact: %s", fact_text)
            continue
        if uid and fact_text:
            user_key = f"user_{uid}"
            existing_facts = state_store.get("memory", user_key, "facts", default=[])
            if fact_text not in existing_facts:
                existing_facts.append(fact_text)
                state_store.set("memory", user_key, "facts", existing_facts)

    # Structured profiles (field whitelist enforced here and inside ProfileStore)
    if context.profile_store is not None:
        for upd in profile_updates:
            uid = str(upd.get("user_id") or "").strip()
            field = str(upd.get("field") or "").strip()
            value = str(upd.get("value") or "").strip()
            if not uid or not value:
                continue
            if is_affinity_stat_text(value):
                logger.info("[Reflection] Dropping affinity-stat profile value: %s", value)
                continue
            if field in PROFILE_STR_FIELDS:
                context.profile_store.apply(uid, field, "set", value)
            elif field in PROFILE_LIST_FIELDS:
                context.profile_store.apply(uid, field, "append", value)
            else:
                logger.warning("[Reflection] Dropping profile update with invalid field: %s", field)

    # Offline affinity adjustments (daily cap enforced by AffinityStore)
    if context.affinity_store is not None:
        for adj in affinity_adjustments:
            uid = str(adj.get("user_id") or "").strip()
            try:
                delta = float(adj.get("delta", 0))
            except (TypeError, ValueError):
                continue
            reason = str(adj.get("reason") or "每日反思").strip()
            if uid and delta:
                context.affinity_store.adjust(uid, delta, reason, source="reflection")

    return len(topics), len(core_facts)


def _cleanup(conn):
    """Prune reflected-upon short-term memory and stale topics."""
    from runtime import context

    retention_days = get_reflection_retention_days()
    if retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        cur = conn.execute("DELETE FROM conversations WHERE created_at < ?", (cutoff,))
        conn.commit()
        if cur.rowcount:
            logger.info("[Reflection] Pruned %d old conversation rows (>%s days).", cur.rowcount, retention_days)
    try:
        pruned = context.topic_store.prune(90)
        if pruned:
            logger.info("[Reflection] Pruned %d stale topics (>90 days).", pruned)
    except Exception:
        logger.exception("[Reflection] Topic pruning failed")


def run_reflection_job():
    """
    Scans the conversations table for recent activity (group chats AND direct
    messages) and reflects on them.
    """
    logger.info("[Reflection] Starting reflection job...")
    from runtime.context import db, state_store

    conn = db.get_conn()

    # Get all agent scopes that had activity in the last 24 hours
    now = time.time()
    cutoff = now - 86400  # 24 hours ago

    cur = conn.execute(
        "SELECT DISTINCT scope_key FROM conversations WHERE created_at > ? AND scope_key LIKE 'agent:%'",
        (cutoff,)
    )
    active_scopes = [r["scope_key"] for r in cur.fetchall()]

    if not active_scopes:
        logger.info("[Reflection] No active scopes found in the last 24h.")
        _cleanup(conn)
        return

    reflection_models = get_reflection_model()
    if not reflection_models:
        logger.error("[Reflection] reflection_model is not configured in config.yml!")
        return

    for scope in active_scopes:
        logger.info("[Reflection] Processing scope: %s", scope)
        # Fetch all recent messages for this scope
        cur = conn.execute(
            "SELECT role, content FROM conversations WHERE scope_key = ? AND created_at > ? ORDER BY created_at ASC",
            (scope, cutoff)
        )
        msgs = cur.fetchall()

        if len(msgs) < 10:
            logger.info("[Reflection] Skipping scope %s, too few messages (%d).", scope, len(msgs))
            continue

        # DM scopes carry the (normalized) user id in the scope key itself
        dm_hint = ""
        if ":dm:" in scope:
            dm_uid = scope.split(":dm:", 1)[-1]
            dm_hint = (
                f"【注意】这是 bot 与单个用户的私聊记录，对话中 [user] 角色的发言均来自 user_id 为 {dm_uid} 的用户。"
                f"所有 core_facts / profile_updates / affinity_adjustments 的 user_id 都必须填 {dm_uid}。\n"
            )

        batch_size = 200
        overlap_size = 20
        total_topics = 0
        total_facts = 0

        i = 0
        while i < len(msgs):
            batch_msgs = msgs[i : i + batch_size]
            chat_log = []
            for r in batch_msgs:
                role = r["role"]
                content = r["content"]
                # Exclude massive system outputs or tool dumps if any were missed by ephemeral hook
                if role == "tool" or len(content) > 1000:
                    continue
                chat_log.append(f"[{role}] {content}")

            if not chat_log:
                if i + batch_size >= len(msgs):
                    break
                i += (batch_size - overlap_size)
                continue

            history_text = "\n".join(chat_log)

            try:
                resp = None
                last_err = None
                for ref_model_str in reflection_models:
                    try:
                        from nemollm.registry import get_client
                        client, actual_model = get_client(ref_model_str)
                    except Exception as e:
                        logger.warning(f"[Reflection] Could not load client for reflection_model: {ref_model_str} ({e})")
                        continue

                    try:
                        from nemollm import ChatMessage
                        resp = client.chat(
                            model=actual_model,
                            messages=[ChatMessage(role="user", content=f"{dm_hint}【对话记录】\n{history_text}")],
                            system=REFLECTION_PROMPT,
                        )
                        break
                    except Exception as e:
                        logger.warning(f"[Reflection] Model {actual_model} failed: {e}")
                        last_err = e
                        continue

                if not resp:
                    logger.error(f"[Reflection] All reflection models failed for scope {scope} batch {i}-{i+batch_size}. Last error: {last_err}")
                    continue

                data = _parse_reflection_json(resp.text)
                n_topics, n_facts = _apply_reflection_data(data, scope, state_store)
                total_topics += n_topics
                total_facts += n_facts
            except Exception as e:
                logger.error("[Reflection] Failed to process batch %d-%d for scope %s: %s", i, i+batch_size, scope, e)

            if i + batch_size >= len(msgs):
                break
            i += (batch_size - overlap_size)

        logger.info("[Reflection] Scope %s processed successfully. Extracted %d topics and %d core facts.", scope, total_topics, total_facts)

    _cleanup(conn)
    logger.info("[Reflection] Reflection job completed.")
