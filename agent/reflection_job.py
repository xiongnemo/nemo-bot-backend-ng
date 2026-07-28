"""
Psychological Engine - Reflection Job
Runs in the background to summarize topics and extract core facts from short-term memory.
"""

import time
import json
import logging
from typing import List, Dict

from config import get_reflection_model
from nemollm.registry import get_client
from store.database import Database
from store.state_store import StateStore

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """你是一个智能的“赛博群友”心理学引擎。你的任务是分析过去一段时间内群聊的对话记录，并进行记忆提纯。

请仔细阅读下面提供的对话记录，提取出：
1. Topics (话题聚类)：大家讨论了哪几个主要话题？请将废话折叠，提取出最具代表性的话题。
2. Core Facts (核心事实)：提取关于群友的永久性事实（例如某人暴露了自己的职业、爱好、特殊经历，或者对某个事物强烈的喜恶）。如果没有，则留空。

请务必以如下 JSON 格式返回，不要包含任何额外的 Markdown 标记（如 ```json）：
{
    "topics": ["大家探讨了塞尔达新作的购买意愿", "关于十路CPU服务器架构的技术探讨"],
    "core_facts": [
        {"user_id": "123456", "fact": "从事程序员职业，对服务器架构很了解"},
        {"user_id": "789012", "fact": "非常喜欢玩塞尔达系列游戏"}
    ]
}
"""

def run_reflection_job():
    """
    Scans the conversations table for recent activity and reflects on them.
    """
    logger.info("[Reflection] Starting reflection job...")
    from runtime.context import db, state_store
    
    # We only care about group scopes for now
    conn = db.get_conn()
    
    # Get all scopes that had activity in the last 24 hours
    now = time.time()
    cutoff = now - 86400  # 24 hours ago
    
    cur = conn.execute(
        "SELECT DISTINCT scope_key FROM conversations WHERE created_at > ? AND scope_key LIKE '%:group:%'", 
        (cutoff,)
    )
    active_scopes = [r["scope_key"] for r in cur.fetchall()]
    
    if not active_scopes:
        logger.info("[Reflection] No active group scopes found in the last 24h.")
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
                        client, actual_model = get_client(ref_model_str)
                    except Exception as e:
                        logger.warning(f"[Reflection] Could not load client for reflection_model: {ref_model_str} ({e})")
                        continue
                        
                    try:
                        from nemollm import ChatMessage
                        resp = client.chat(
                            model=actual_model,
                            messages=[ChatMessage(role="user", content=f"【对话记录】\n{history_text}")],
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
                    
                resp_text = resp.text.strip()
                if resp_text.startswith("```json"):
                    resp_text = resp_text[7:]
                if resp_text.endswith("```"):
                    resp_text = resp_text[:-3]
                    
                data = json.loads(resp_text)
                
                topics = data.get("topics", [])
                core_facts = data.get("core_facts", [])
                
                # Save topics to DB (Mid-term)
                for t in topics:
                    conn.execute(
                        "INSERT INTO topics (scope_key, topic_summary, created_at) VALUES (?, ?, ?)",
                        (scope, t, time.time())
                    )
                conn.commit()
                
                # Save core facts to state_store (Long-term)
                for fact_obj in core_facts:
                    uid = fact_obj.get("user_id")
                    fact_text = fact_obj.get("fact")
                    if uid and fact_text:
                        user_key = f"user_{uid}"
                        existing_facts = state_store.get("memory", user_key, "facts", default=[])
                        if fact_text not in existing_facts:
                            existing_facts.append(fact_text)
                            state_store.set("memory", user_key, "facts", existing_facts)
                
                total_topics += len(topics)
                total_facts += len(core_facts)
            except Exception as e:
                logger.error("[Reflection] Failed to process batch %d-%d for scope %s: %s", i, i+batch_size, scope, e)
                
            if i + batch_size >= len(msgs):
                break
            i += (batch_size - overlap_size)
                
        logger.info("[Reflection] Scope %s processed successfully. Extracted %d topics and %d core facts.", scope, total_topics, total_facts)
            
    logger.info("[Reflection] Reflection job completed.")
