"""
AgentRunner — The main loop that manages the LLM conversation and tool calls.
"""

from __future__ import annotations

import json
import logging
from typing import List, Callable

from core.message import Message
from core.types import Action
from nemollm import ChatMessage
from nemollm.memory import ConversationMemory
from store.conversation_store import ConversationStore

from store.state_store import StateStore
from .prompts import build_system_prompt
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


import re as _re

AFFINITY_CLAIM_RE = _re.compile(r"好感度?\s*(?:[+＋\-－]|加了?|减了?|扣了?)\s*\d")
AFFINITY_WRITE_TOOLS = {"adjust_affinity", "gift_affinity", "admin_affinity"}


def affinity_claim_without_call(reply_text: str, turn_tool_names: list[str]) -> bool:
    """True when the reply claims an affinity change but no affinity-write tool ran this turn."""
    if not reply_text or not AFFINITY_CLAIM_RE.search(reply_text):
        return False
    return not any(t in AFFINITY_WRITE_TOOLS for t in turn_tool_names)


def _sanitize_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Ensure tool calls and tool responses are properly paired and valid."""
    cleaned = []
    seen_tc_ids = set()
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == "tool":
            i += 1
            continue
        elif msg.role == "assistant" and msg.tool_calls:
            tool_msgs = []
            j = i + 1
            while j < len(messages) and messages[j].role == "tool":
                tool_msgs.append(messages[j])
                j += 1
            
            unique_tcs = []
            for tc in msg.tool_calls:
                if tc.id not in seen_tc_ids:
                    unique_tcs.append(tc)
                    seen_tc_ids.add(tc.id)
            msg.tool_calls = unique_tcs

            expected_ids = {tc.id for tc in msg.tool_calls if tc.id}
            found_ids = {tm.tool_call_id for tm in tool_msgs if tm.tool_call_id}
            
            if not msg.tool_calls:
                if msg.content:
                    cleaned.append(ChatMessage(role="assistant", content=msg.content))
            elif expected_ids and not expected_ids.issubset(found_ids):
                if msg.content:
                    cleaned.append(ChatMessage(role="assistant", content=msg.content))
            else:
                cleaned.append(msg)
                cleaned.extend([tm for tm in tool_msgs if tm.tool_call_id in expected_ids])
            i = j
        else:
            cleaned.append(msg)
            i += 1
            
    # Final pass: merge consecutive text-only messages to satisfy Gemini API strict alternation
    final = []
    for m in cleaned:
        if not final:
            final.append(m)
        else:
            last = final[-1]
            if last.role == m.role and last.role in ("user", "assistant"):
                if not getattr(last, "tool_calls", None) and not getattr(m, "tool_calls", None):
                    last.content = f"{last.content}\n\n{m.content}".strip()
                else:
                    final.append(m)
            else:
                final.append(m)
                
    return final


class AgentRunner:
    def __init__(
        self,
        memory: ConversationMemory,
        state_store: StateStore,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        max_steps: int = 8,
    ):
        self.memory = memory
        self.state_store = state_store
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.max_steps = max_steps

    def run(self, message: Message, query: str, run_id: str = None, observer: Callable[[List[Action]], None] = None) -> List[Action]:
        """
        Execute the agent loop for a given query.
        Returns a list of Actions to be delivered to the user.
        """
        from config import get_platform
        # Resolve cross-platform user identity
        platform = get_platform(message.frontend)
        link_key = f"{platform}:{message.context.user_id}"
        primary_uid = self.state_store.get("user_link", "global", link_key, default=message.context.user_id)
        # Override the original ID so plugins (like core_memory) use the primary ID
        message.context.user_id = primary_uid

        gid = message.context.group_id
        uid = primary_uid

        # Scope key identifies the conversation thread
        if gid:
            scope_key = f"agent:{message.frontend}:group:{gid}"
        else:
            scope_key = f"agent:{message.frontend}:dm:{uid}"
            
        if run_id:
            self.state_store.set("agent", "latest_run_id", scope_key, run_id)
        
        # Tools this user is allowed to use
        tools = self.tool_registry.get_tools_for_user(message.frontend, uid)
        
        # We manually manage the loop here rather than just calling memory.chat() once,
        # because we need to handle multiple tool call steps within a single "turn".
        
        # 1. Load history (L2: speaker-weighted for group scopes)
        from agent.context_loader import load_weighted_history
        from config import get_context_config
        messages = load_weighted_history(
            self.memory.store, scope_key, uid, bool(gid),
            cfg=get_context_config().get("history", {}),
        )
        messages = _sanitize_messages(messages)
        
        all_imgs = list(message.request.imgs)
        reply_ctx = ""
        if getattr(message.request, "reply_to", None):
            reply_text = message.request.reply_to.get("text", "")
            reply_imgs = message.request.reply_to.get("imgs", [])
            reply_author = message.request.reply_to.get("user_name", "") or message.request.reply_to.get("user_id", "Unknown")
            if reply_imgs:
                all_imgs.extend(reply_imgs)
            reply_ctx = f"\n\n[Replying to {reply_author}]:\n{reply_text}".rstrip()

        img_str = ""
        if all_imgs:
            img_parts = []
            for url in all_imgs:
                tag = self.state_store.get("img_tags", "global", url)
                if tag:
                    img_parts.append(f"[附图/Image Attached]: {url}\n<图像内容分析>: {tag}")
                else:
                    img_parts.append(f"[附图/Image Attached]: {url}")
            urls = "\n\n".join(img_parts)
            img_str = f"\n{urls}"
            
            # Check for overall summary
            summary = self.state_store.get("img_tags", "summary", message.context.message_id)
            if summary:
                img_str += f"\n\n<多图整体总结>: {summary}"
            
        # Append new user message with speaker injection if in group
        if gid:
            group_info = f" (Group: {message.context.group_name})" if getattr(message.context, "group_name", "") else ""
            formatted_query = f"[{message.context.user_name} (ID: {uid}){group_info}]:\n{query}{reply_ctx}{img_str}"
        else:
            formatted_query = f"{query}{reply_ctx}{img_str}"
            
        messages.append(ChatMessage(role="user", content=formatted_query))
        
        # We'll collect new messages to save to history at the end
        new_messages_for_db = []
        
        # Collect any media actions (photos, voices) generated by plugins
        media_actions = []
        
        from nemollm.registry import get_registry
        registry = get_registry()
        
        # 2. Build dynamic system prompt
        system_prompt = build_system_prompt(message, self.state_store)
        
        verbose_level = self.state_store.get("agent", "verbose_level", scope_key, default=0)
        
        if observer and verbose_level >= 1:
            run_id_str = f" (Run ID: {run_id})" if run_id else ""
            observer([Action(kind="reply", text=f"[Nemo] 任务已收到，开始思考...{run_id_str}")])
        
        for step in range(self.max_steps):
            if run_id and self.state_store.get("sys", "cancel", run_id):
                self.state_store.set("sys", "cancel", run_id, False) # clear flag
                logger.info(f"Run {run_id} cancelled by user at step {step + 1}.")
                return [Action(kind="reply", text=f"[Nemo] 任务已强行中断 (Run ID: {run_id})")]

            resp = None
            last_err = None
            for client, actual_model in registry.get_models():
                logger.info("Agent Step %d: calling LLM (model: %s)...", step + 1, actual_model)
                try:
                    resp = client.chat(
                        model=actual_model,
                        messages=messages,
                        system=system_prompt,
                        tools=tools,
                    )
                    registry.report_success(client, actual_model)
                    break  # Success!
                except Exception as e:
                    logger.warning("Model %s failed: %s", actual_model, e)
                    last_err = e
                    continue
                    
            if not resp:
                raise RuntimeError(f"All fallback models failed. Last error: {last_err}")
            
            # Record assistant response
            msg_assistant = ChatMessage(
                role="assistant", 
                content=resp.text, 
                tool_calls=resp.tool_calls
            )
            messages.append(msg_assistant)
            new_messages_for_db.append(msg_assistant)
            
            if resp.tool_calls:
                logger.info("Agent Step %d: got %d tool calls", step + 1, len(resp.tool_calls))
                if observer and verbose_level >= 1:
                    tc_descriptions = []
                    for tc in resp.tool_calls:
                        args_str = ", ".join([f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" for k, v in (tc.arguments or {}).items()])
                        if verbose_level == 1 and len(args_str) > 80:
                            args_str = args_str[:77] + "..."
                        tc_descriptions.append(f"- {tc.name}({args_str})")
                    run_id_str = f"\n(Run ID: {run_id})" if run_id else ""
                    tools_list = "\n".join(tc_descriptions)
                    observer([Action(kind="reply", text=f"[Nemo] 正在调用:\n{tools_list}{run_id_str}")])

                # Execute all tool calls concurrently
                import concurrent.futures
                
                def execute_single_tool(tc):
                    obs = self.tool_executor.execute(tc.name, tc.arguments, message)
                    if isinstance(obs, dict) and "_raw_actions" in obs:
                        raw = obs.pop("_raw_actions")
                        for a in raw:
                            if a.get("photo_url") or a.get("voice_url"):
                                media_actions.append(Action.from_dict(a))
                    return ChatMessage(
                        role="tool",
                        content=json.dumps(obs, ensure_ascii=False),
                        tool_call_id=tc.id,
                        name=tc.name,
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(resp.tool_calls), 10)) as executor:
                    # Submit all tools
                    future_to_tc = {executor.submit(execute_single_tool, tc): tc for tc in resp.tool_calls}
                    # Wait for all to complete in the original order
                    for tc in resp.tool_calls:
                        # Find the corresponding future
                        future = next(f for f, t in future_to_tc.items() if t == tc)
                        msg_tool = future.result()
                        messages.append(msg_tool)
                        new_messages_for_db.append(msg_tool)
                    
                # Continue loop to send tool results back to LLM
                continue
            else:
                # No tool calls, we're done
                logger.info("Agent loop finished at step %d", step + 1)
                break
        else:
            logger.warning("Agent loop reached max_steps (%d), aborting", self.max_steps)
            return [Action(kind="reply", text="[Nemo] 我想太久了，脑袋有点晕...")]
            
        # 4. Save to DB
        self.memory.store.append(scope_key, role="user", content=formatted_query, metadata={"user_id": uid})
        for m in new_messages_for_db:
            meta = {}
            if m.tool_calls:
                meta["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m.tool_calls]
            if m.tool_call_id:
                meta["tool_call_id"] = m.tool_call_id
            if m.name:
                meta["name"] = m.name
            
            content_to_save = str(m.content)
            

            
            self.memory.store.append(
                scope_key,
                role=m.role,
                content=content_to_save,
                metadata=meta,
            )
            
        turn_tool_names = []
        for m in new_messages_for_db:
            for tc in (getattr(m, "tool_calls", None) or []):
                turn_tool_names.append(tc.name)

        # L3: record this turn into the per-user thread and maybe compress
        try:
            from runtime import context as rt_context
            if rt_context.user_thread_store is not None:
                tool_names = turn_tool_names
                events = []
                if "adjust_affinity" in tool_names:
                    events.append("affinity")
                if "update_profile" in tool_names:
                    events.append("profile")
                scene = f"group:{gid}" if gid else "dm"
                answer_text = (resp.text or "") if resp else ""
                rt_context.user_thread_store.append_turn(
                    uid, scene, query, answer_text, tools=tool_names, events=events
                )
                if rt_context.user_thread_store.should_compress(uid) and rt_context.executor is not None:
                    rt_context.executor.submit_dispatch(rt_context.user_thread_store.compress, uid)
        except Exception:
            logger.exception("user_thread tracking failed")

        final_actions = []
        if resp and resp.text and resp.text.strip():
            final_text = resp.text.strip()
            is_duplicate = False
            for m in new_messages_for_db:
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        if tc.name == "send_message":
                            try:
                                args = tc.arguments
                                if isinstance(args, str):
                                    args = json.loads(args)
                                if isinstance(args, dict) and "text" in args:
                                    sent_text = args["text"].strip()
                                    # If the agent already sent this text via tool, don't repeat it in the final reply
                                    if sent_text and (final_text in sent_text or sent_text in final_text):
                                        is_duplicate = True
                                        break
                            except Exception:
                                pass
            
            if not is_duplicate:
                if final_text == "[NO_REPLY]" or "[NO_REPLY]" in final_text:
                    logger.info("Agent returned [NO_REPLY], skipping final reply action.")
                else:
                    if affinity_claim_without_call(final_text, turn_tool_names):
                        logger.warning("[AffinityGuard] Reply claims an affinity change but no affinity-write tool was called this turn. scope=%s", scope_key)
                        final_text += "\n（系统提示：上面提到的好感度变动没有真正写入系统，实际分数请发送「好感度」查询为准）"
                    final_actions.append(Action(kind="reply", text=final_text))
        
        # Combine multiple images if present
        if media_actions:
            from utilities import combine_images_vertically
            image_urls = [a.photo_url for a in media_actions if a.photo_url]
            voice_actions = [a for a in media_actions if a.voice_url]
            
            if len(image_urls) > 1:
                combined_url = combine_images_vertically(image_urls)
                if combined_url:
                    final_actions.append(Action(kind="send", photo_url=combined_url))
                else:
                    # Fallback to separate images
                    for url in image_urls:
                        final_actions.append(Action(kind="send", photo_url=url))
            elif len(image_urls) == 1:
                final_actions.append(Action(kind="send", photo_url=image_urls[0]))
                
            final_actions.extend(voice_actions)
            
        return final_actions
