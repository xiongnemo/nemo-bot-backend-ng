"""
Feed Service - Information Feed Hub Logic (Pub/Sub)
Handles parsing external feeds, keyword matching, and LLM Gatekeeper duplicate/importance checks.
"""
from __future__ import annotations

import logging
import json
import time
from typing import Any
from threading import Thread

from core.message import Message
from nemollm.types import ChatMessage
from nemollm.registry import get_client
from runtime.sender import Sender
from store.database import Database
import config as app_config

logger = logging.getLogger(__name__)

class FeedService:
    def __init__(self, db: Database, sender: Sender):
        self.db = db
        self.sender = sender

    def handle_incoming_feed(self, payload: dict[str, Any]) -> tuple[bool, str, int]:
        """
        Process an incoming webhook feed.
        Returns: (success, message, http_status_code)
        """
        channel_name = payload.get("channel_name")
        title = payload.get("title") or ""
        content = payload.get("content")
        original_time = payload.get("original_time")
        if not original_time:
            original_time = int(time.time())
            
        meta = payload.get("meta", {})

        if not channel_name or not content:
            return False, "Missing required fields (channel_name, content).", 400

        conn = self.db.get_conn()
        
        # 1. Check if channel exists, if not, auto-create it
        cur = conn.execute("SELECT id FROM channels WHERE name = ?", (channel_name,))
        if not cur.fetchone():
            try:
                conn.execute("INSERT INTO channels (name, description) VALUES (?, ?)", (channel_name, "Auto-created channel"))
                conn.commit()
                logger.info("Auto-created missing channel: %s", channel_name)
            except Exception as e:
                logger.error("Failed to auto-create channel %s: %s", channel_name, e)
                return False, f"Channel not found and failed to create: {channel_name}", 500

        # 2. Find subscriptions for this channel
        cur = conn.execute("SELECT target_group, keywords FROM subscriptions WHERE channel_name = ?", (channel_name,))
        subs = cur.fetchall()

        # If no one subscribes, we still save it, but don't do any processing.
        matched_subs = []
        for sub in subs:
            target_group = sub["target_group"]
            keywords_str = sub["keywords"]
            
            if not keywords_str:
                continue
                
            # Basic keyword matching
            keywords = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
            full_text = f"{title}\n{content}".lower()
            
            matched_keywords = [k for k in keywords if k in full_text]
            if matched_keywords:
                import logging
                logging.getLogger(__name__).info(f"Feed '{title}' matched keywords: {matched_keywords} for group {target_group}")
                matched_subs.append(target_group)

        # 3. If we have matches, invoke Gatekeeper asynchronously (to avoid blocking the webhook)
        # We will save to DB first, then let the async task update it and broadcast.
        
        # Insert into feeds
        try:
            cur = conn.execute(
                """
                INSERT INTO feeds (channel_name, title, content, original_time, created_at, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel_name, title, content, original_time, time.time(), json.dumps(meta, ensure_ascii=False))
            )
            conn.commit()
            feed_id = cur.lastrowid
        except Exception as e:
            conn.rollback()
            logger.error("Failed to insert feed %s: %s", channel_name, e)
            return False, f"Database error during insert: {e}", 500
        
        if matched_subs:
            # Deduplicate target groups to avoid sending multiple identical messages
            unique_subs = list(set(matched_subs))
            # Dispatch to background thread
            Thread(
                target=self._run_gatekeeper,
                args=(feed_id, channel_name, title, content, unique_subs),
                daemon=True
            ).start()
            return True, "Feed accepted and queued for gatekeeper evaluation.", 200
        else:
            logger.info(f"Feed '{title}' matched 0 subscriptions, skipping LLM Gatekeeper.")
            return True, "Feed accepted and saved (no matching subscriptions).", 200

    def _run_gatekeeper(self, feed_id: int, channel_name: str, title: str, content: str, target_groups: list[str]):
        """Runs the LLM gatekeeper and forwards to matched groups if valuable."""
        try:
            gatekeeper_models = app_config.get_gatekeeper_model()
            if not gatekeeper_models:
                logger.warning("No gatekeeper_model configured. Skipping LLM eval.")
                return

            # Context 1: Current System Time
            current_time_str = time.strftime('%Y-%m-%d %H:%M:%S')

            from runtime import context
            conn = context.db.get_conn()

            # Context 2: Channel Description
            cur = conn.execute("SELECT description FROM channels WHERE name = ?", (channel_name,))
            channel_desc_row = cur.fetchone()
            channel_desc = channel_desc_row['description'] if channel_desc_row else "Unknown channel"

            # Context 3: Audience Subscriptions
            group_ph = ','.join(['?'] * len(target_groups))
            cur = conn.execute(
                f"SELECT target_group, keywords FROM subscriptions WHERE channel_name = ? AND target_group IN ({group_ph})",
                [channel_name] + target_groups
            )
            subs = cur.fetchall()
            subs_text = "\n".join([f"- 受众 {row['target_group']}: 关注关键词 [{row['keywords']}]" for row in subs]) if subs else "No specific keywords."

            # Context 4: Recent Chat History
            cur = conn.execute(
                f"SELECT group_id, user_name, text FROM messages WHERE group_id IN ({group_ph}) ORDER BY timestamp DESC LIMIT 15",
                target_groups
            )
            msgs = cur.fetchall()
            chat_hist = "\n".join([f"[{row['group_id']}] {row['user_name']}: {row['text']}" for row in reversed(msgs)]) if msgs else "No recent chat history."

            # Context 5: Recent history for this channel (last 3 hours)
            cutoff = time.time() - 3 * 3600
            cur = conn.execute(
                "SELECT title, content FROM feeds WHERE channel_name = ? AND created_at > ? AND id != ? ORDER BY created_at DESC LIMIT 10",
                (channel_name, cutoff, feed_id)
            )
            history = cur.fetchall()
            
            history_text = "No recent history."
            if history:
                history_text = "\n\n".join([f"[{i+1}] {row['title']}\n{row['content']}" for i, row in enumerate(history)])

            prompt = f"""You are a smart news gateway (Gatekeeper).
You need to evaluate a new incoming news piece against recent history, audience interests, and recent chat context.

### System Context
- Current Time: {current_time_str}
- Channel Name: {channel_name}
- Channel Description: {channel_desc}

### Audience Subscriptions
The news will be pushed to the following groups, who have these subscriptions/interests:
{subs_text}

### Recent Chat History (from target groups)
{chat_hist}

### Recent News History (for deduplication)
{history_text}

### New News
Title: {title}
Content: {content}

### Your Task
Evaluate the new news:
1. Is it an advertisement, self-promotion, or low-value clickbait? Look out for phrases like "点击查看" (Click to view), "马上参与" (Participate now), "正在直播中" (Live broadcasting), "一图看懂" (Understand with one picture), "一文看懂" (Understand with one article), ">>", or meaningless placeholders. ALSO reject "teasing" messages (吊胃口的消息) that ask a question without providing the actual answer in the text (e.g. "what is the outlook? Read this article."). If it falls into this category, you MUST set should_forward to false, regardless of how important the topic seems.
2. Is it a duplicate or just a minor update of the events in the history? (Set is_duplicate to true if yes)
3. If it is NOT a duplicate and NOT an ad/clickbait, is it highly valuable/breaking/important enough to actively alert these specific users based on their interests and current chat context? (Set should_forward to true if yes)

Return your evaluation as a strict JSON object with this format:
{{
  "is_duplicate": boolean,
  "should_forward": boolean,
  "reason": "short explanation in Chinese (必须用中文写评语)"
}}
"""
            # Request JSON mode natively since we added it
            response = None
            last_err = None
            
            for gk_model_str in gatekeeper_models:
                try:
                    client, actual_model = get_client(gk_model_str)
                except Exception as e:
                    logger.warning(f"Could not load client for gatekeeper_model: {gk_model_str} ({e})")
                    continue
                    
                try:
                    response = client.chat(
                        model=actual_model,
                        messages=[ChatMessage(role="user", content=prompt, name="")],
                        temperature=0.1,
                        response_format="json"
                    )
                    break
                except Exception as e:
                    logger.warning(f"Gatekeeper model {actual_model} failed: {e}")
                    last_err = e
                    continue
                    
            if not response:
                logger.error(f"All gatekeeper fallback models failed. Last error: {last_err}")
                return
            
            try:
                result = json.loads(response.text)
            except json.JSONDecodeError:
                logger.error(f"Gatekeeper returned invalid JSON: {response.text}")
                return

            is_duplicate = bool(result.get("is_duplicate", False))
            should_forward = bool(result.get("should_forward", False))
            meta_score = 100 if should_forward else 50
            if is_duplicate:
                meta_score = 0

            # Update DB
            conn.execute(
                "UPDATE feeds SET is_duplicate = ?, meta_score = ? WHERE id = ?",
                (1 if is_duplicate else 0, meta_score, feed_id)
            )
            conn.commit()

            # Broadcast
            if not is_duplicate and should_forward:
                msg_text = f"📰 【{channel_name} 最新资讯】\n{title}\n\n{content}\n(Gatekeeper 评语: {result.get('reason', '')})"
                for group in target_groups:
                    # Construct a dummy message_dict so sender knows the context
                    # Assuming group is from onebot or ntchat. We don't know the exact frontend from target_group alone,
                    # but target_group could be stored as "ntchat:44779935091@chatroom"
                    if ":" in group:
                        frontend, gid = group.split(":", 1)
                        dummy_dict = {
                            "frontend": frontend,
                            "context": {"group_id": gid}
                        }
                    else:
                        # Fallback for old configurations
                        dummy_dict = {
                            "frontend": "ntchat",
                            "context": {"group_id": group}
                        }
                    self.sender.send_text(dummy_dict, msg_text)
                    
        except Exception as e:
            logger.exception("Gatekeeper execution failed")
