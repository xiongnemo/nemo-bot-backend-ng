"""
app.py — The Flask entry point for nemo-bot-backend-ng.
"""

from __future__ import annotations

import os
import logging
import uuid
from concurrent_log_handler import ConcurrentRotatingFileHandler
import sys

from flask import Flask, jsonify, request

from core.types import IngestMessage
from nemollm.registry import init_registry
from routing import Router, Ruleset
from runtime.executor import Executor
from runtime.sender import Sender
from store.database import Database
from store.conversation_store import ConversationStore
from store.message_store import MessageStore
from store.state_store import StateStore
from core.feed_service import FeedService
from agent.tool_registry import ToolRegistry
from agent.tool_executor import ToolExecutor
from agent.builtin_tools import register_builtin_tools
from agent.superuser_tools import register_superuser_tools
from agent.runner import AgentRunner
from scheduler.engine import SchedulerEngine
from scheduler.jobs import register_all_jobs
import config as app_config

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    handlers=[
        ConcurrentRotatingFileHandler("logs/bot.log", "a", 10 * 1024 * 1024, backupCount=30, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ======================================================================
# Globals / Dependencies (initialized in setup)
# ======================================================================

app = Flask(__name__)

db: Database = None
state_store: Any = None
msg_store: MessageStore = None
conv_store: ConversationStore = None
executor: Executor = None
sender: Sender = None
feed_service: FeedService = None
ruleset: Ruleset = None
router: Router = None
tool_registry: ToolRegistry = None
tool_executor: ToolExecutor = None
agent_runner: AgentRunner = None
scheduler: SchedulerEngine = None


def setup():
    global db, state_store, msg_store, conv_store, executor, sender, feed_service
    global ruleset, router, tool_registry, tool_executor, agent_runner, scheduler
    
    logger.info("Initializing nemo-bot-backend-ng...")

    import sys
    is_check_mode = len(sys.argv) > 1 and sys.argv[1] == "--check"

    # 1. Stores
    db = Database()
    state_store = StateStore(db)
    msg_store = MessageStore(db)
    conv_store = ConversationStore(db)

    # 2. Runtime
    executor = Executor(plugin_workers=20, dispatch_workers=8)
    sender = Sender()
    
    feed_service = FeedService(db, sender)
    
    from runtime import context
    context.sender = sender
    context.state_store = state_store
    context.db = db

    from store.affinity_store import AffinityStore
    from store.profile_store import ProfileStore
    from store.topic_store import TopicStore
    context.profile_store = ProfileStore(state_store)
    context.affinity_store = AffinityStore(state_store, profile_store=context.profile_store)
    context.topic_store = TopicStore(db)

    from store.user_thread import UserThreadStore
    from store.group_digest import GroupDigestStore
    context.user_thread_store = UserThreadStore(state_store)
    context.group_digest_store = GroupDigestStore(state_store, db)
    context.msg_store = msg_store

    from store.persona_store import PersonaStore
    personas_dir = os.path.join(os.path.dirname(__file__), "personas")
    context.persona_store = PersonaStore(personas_dir, state_store)

    # 3. LLM
    init_registry(app_config.backend_config.get("llm", {}))

    # 4. Routing
    from routing.router import Router
    from routing.ruleset import Ruleset
    ruleset = Ruleset()
    ruleset.load_defaults()

    agent_cfg = app_config.backend_config.get("agent", {})
    router = Router(
        ruleset=ruleset,
        state_store=state_store,
        bot_names=agent_cfg.get("bot_names", ["nemo"]),
        trigger_prefixes=agent_cfg.get("trigger_prefixes", ["nemonemo"]),
    )

    # 5. Scheduler
    scheduler = SchedulerEngine(db, sender, state_store)

    # 6. Tools
    from agent.tool_registry import ToolRegistry
    from agent.tool_executor import ToolExecutor
    from agent.builtin_tools import register_builtin_tools
    tool_registry = ToolRegistry()
    
    # Set context globals early so scheduler jobs can use them
    context.executor = executor
    
    from agent.superuser_tools import register_superuser_tools
    register_builtin_tools(tool_registry, msg_store, state_store, scheduler)
    register_superuser_tools(tool_registry, state_store)

    tool_registry.load_defaults()
    tool_executor = ToolExecutor(tool_registry, executor, state_store, sender, scheduler)
    
    from nemollm.memory import ConversationMemory
    mem = ConversationMemory(conv_store)
    agent_cfg = app_config.backend_config.get("agent", {})
    agent_runner = AgentRunner(
        memory=mem,
        state_store=state_store,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        max_steps=agent_cfg.get("max_steps", 8),
    )
    context.agent_runner = agent_runner

    register_all_jobs(scheduler)
    scheduler.start()

    logger.info("Initialization complete.")


# ======================================================================
# Flask Endpoints (defined at module level so Flask sees them)
# ======================================================================

@app.route("/ingest", methods=["POST"])
def ingest():
    """The unified entry point for all frontends."""
    payload = request.get_json()
    if not payload:
        logger.warning("Ingest failed: Empty or invalid JSON payload")
        return jsonify(error="Empty payload"), 400

    # Non-blocking dispatch
    executor.submit_dispatch(_handle_ingest, payload)
    return jsonify(status="accepted"), 202


@app.route("/bot", methods=["POST"])
def bot_compat():
    """Legacy compatibility endpoint."""
    return ingest()


@app.route("/man", methods=["POST"])
def man_compat():
    """Legacy man endpoint."""
    payload = request.get_json()
    executor.submit_dispatch(_handle_man, payload)
    return jsonify(status="accepted"), 202


@app.route("/explain", methods=["POST"])
def explain_compat():
    """Legacy explain endpoint."""
    payload = request.get_json()
    executor.submit_dispatch(_handle_explain, payload)
    return jsonify(status="accepted"), 202

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"})

@app.route('/api/feed', methods=['POST'])
def receive_feed():
    """Webhook for external scripts to push feeds."""
    # Auth
    valid_tokens = app_config.get_webhook_tokens()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if valid_tokens and token not in valid_tokens:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.json
    if not payload:
        logger.warning("Feed ingest failed: Invalid or missing JSON payload")
        return jsonify({"error": "Invalid JSON payload"}), 400

    success, msg, status_code = feed_service.handle_incoming_feed(payload)
    if not success:
        logger.warning(f"Feed ingest failed: {status_code} - {msg}. Payload snippet: {str(payload)[:500]}")
        return jsonify({"error": msg}), status_code
        
    return jsonify({"message": msg}), status_code

@app.route('/api/channel', methods=['POST'])
def create_channel():
    """API to create a new feed channel."""
    valid_tokens = app_config.get_webhook_tokens()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if valid_tokens and token not in valid_tokens:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.json
    if not payload:
        logger.warning("Channel creation failed: Invalid or missing JSON payload")
        return jsonify({"error": "Invalid JSON payload"}), 400
        
    channel_name = payload.get("name")
    description = payload.get("description", "")
    if not channel_name:
        logger.warning(f"Channel creation failed: Missing channel 'name'. Payload snippet: {str(payload)[:500]}")
        return jsonify({"error": "Missing channel 'name'"}), 400

    try:
        conn = db.get_conn()
        conn.execute("INSERT INTO channels (name, description) VALUES (?, ?)", (channel_name, description))
        conn.commit()
        return jsonify({"message": f"Channel '{channel_name}' created successfully."}), 201
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"error": f"Channel '{channel_name}' already exists."}), 409
        return jsonify({"error": str(e)}), 500


@app.route('/api/inline', methods=['POST'])
def inline_eval():
    """Synchronous command evaluation endpoint for Telegram Inline Query."""
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    query = (payload.get("query") or "").strip()
    frontend_name = payload.get("frontend", "telegram")
    user_id = str(payload.get("context", {}).get("user_id", "guest"))
    user_name = str(payload.get("context", {}).get("user_name", "User"))
    group_id = str(payload.get("context", {}).get("group_id", ""))

    if not query:
        return jsonify({
            "status": "ok",
            "type": "suggestions",
            "suggestions": [
                {"title": "银联卡汇率 (upfx)", "command": "upfx USD", "description": "查询银联实时汇率 (例: upfx USD / upfx JPY)"},
                {"title": "加密货币行情 (ticker)", "command": "ticker BTC", "description": "查询代币实时价格行情 (例: ticker BTC)"},
                {"title": "人民币外汇牌价 (rmbfx)", "command": "rmbfx USD", "description": "查询中国银行外汇牌价 (例: rmbfx JPY)"},
                {"title": "天气预报 (weather)", "command": "weather 上海", "description": "查询实时天气预报 (例: weather 北京)"},
                {"title": "全量指令手册 (help)", "command": "help", "description": "查看 Nemo 机器人帮助与插件使用说明"},
            ]
        })

    # Prepare IngestMessage payload
    ingest_payload = {
        "frontend": frontend_name,
        "context": {
            "group_id": group_id,
            "group_name": "",
            "user_id": user_id,
            "user_name": user_name,
            "message_id": f"inline_{int(time.time() * 1000)}",
            "self_id": "",
            "ated": True,
            "avatar_info": "",
            "avatar_photo": "",
            "frontend_system_info": "inline_query"
        },
        "request": {
            "command": "",
            "args": query,
            "imgs": [],
            "raw_message": query,
            "reply_to": None
        }
    }

    try:
        msg = IngestMessage.from_dict(ingest_payload)
        route = router.route(msg)

        if route.mode == "command" and route.plugin:
            from core.recording_message import RecordingMessage
            rec_msg = RecordingMessage(ingest_payload)
            plugin_mod = ruleset.get_plugin_module(route.plugin)
            if plugin_mod and hasattr(plugin_mod, "bot_execute"):
                rec_msg.request.args = route.args
                rec_msg.request.command = route.plugin
                plugin_mod.bot_execute(rec_msg, app_config.backend_config)

                texts = [a.text for a in rec_msg.outbox if a.text]
                result_text = "\n".join(texts).strip() if texts else "（指令执行完毕，无输出）"
                return jsonify({
                    "status": "ok",
                    "type": "command_result",
                    "plugin": route.plugin,
                    "query": query,
                    "title": f"[{route.plugin}] {query}",
                    "text": result_text
                })

        return jsonify({
            "status": "ok",
            "type": "unhandled",
            "title": f"未匹配快捷指令: {query}",
            "text": f"输入 '{query}' 未匹配到可直接执行的命令。可以尝试输入 'upfx USD' 或 'ticker BTC'。"
        })
    except Exception as e:
        logger.exception("Failed to evaluate inline query: %s", query)
        return jsonify({
            "status": "error",
            "type": "command_result",
            "title": f"执行异常: {query}",
            "text": f"500: nemo: 执行发生异常: {e}"
        }), 200


# ======================================================================
# Dispatch Workers
# ======================================================================

def _handle_ingest(payload: dict):
    try:
        msg = IngestMessage.from_dict(payload)
        
        if msg.reply_to and "message_id" in msg.reply_to:
            reply_id = msg.reply_to["message_id"]
            if not msg_store.exists(reply_id):
                msg_store.ingest(
                    frontend=msg.frontend, group_id=msg.group_id, user_id=msg.reply_to.get("user_id", ""),
                    user_name=msg.reply_to.get("user_name", ""), text=msg.reply_to.get("text", ""), message_id=reply_id,
                    ated=False, imgs=[], raw_message="", timestamp=msg.reply_to.get("timestamp") or (msg.timestamp - 1)
                )

        msg_store.ingest(
            frontend=msg.frontend, group_id=msg.group_id, user_id=msg.user_id,
            user_name=msg.user_name, text=msg.text, message_id=msg.message_id,
            ated=msg.ated, imgs=msg.imgs, raw_message=msg.raw_message, timestamp=msg.timestamp
        )

        if msg.imgs:
            from agent.vision_tagger import async_tag_images
            executor.submit_dispatch(async_tag_images, msg.imgs, msg.message_id, state_store)

        # --- Alias Interception Start ---
        first_word = msg.full_text.split()[0] if msg.full_text.strip() else ""
        if first_word:
            alias_target = state_store.get("alias", "global", first_word)
            if alias_target:
                # Replace the first word with the alias target
                msg.full_text = alias_target + msg.full_text[len(first_word):]
                msg.text = alias_target + msg.text[len(first_word):]
                logger.info("Alias expanded: %s -> %s", first_word, alias_target)
        # --- Alias Interception End ---

        route = router.route(msg)
        logger.info(
            "Routed message %r (from %s in %s) -> mode: %s, plugin: %s, args: %r",
            msg.text, msg.user_id, msg.group_id or "DM", route.mode, route.plugin, route.args
        )

        from core.message import Message
        raw_msg = Message(payload)

        # --- ACL Logic Start ---
        from config import is_superuser, get_platform, get_rejection_phrases
        import random
        
        platform = get_platform(msg.frontend)
        link_key = f"{platform}:{msg.user_id}"
        primary_uid = state_store.get("user_link", "global", link_key, default=msg.user_id)
        
        is_su = is_superuser(msg.frontend, msg.user_id)
        
        if not is_su and route.mode in ["command", "agent"]:
            global_blacklist = state_store.get("acl", "global", "blacklist", default=[])
            target_user = f"user_{primary_uid}"
            target_group = f"group_{msg.group_id}" if msg.group_id else None
            
            if target_user in global_blacklist or (target_group and target_group in global_blacklist):
                logger.info("User %s (or group) is globally blacklisted.", target_user)
                if route.mode == "agent":
                    phrases = get_rejection_phrases()
                    rejection = random.choice(phrases) if phrases else "Nemo 并不是很想跟你讲话。"
                    from core.types import Action
                    sender.deliver_actions(payload, [Action(kind="reply", text=rejection)])
                return
                
            if route.mode in ["command", "agent"]:
                plugin_name = route.plugin if route.mode == "command" else "agent"
                
                whitelist = state_store.get("acl", f"plugin_{plugin_name}", "whitelist", default=[])
                blacklist = state_store.get("acl", f"plugin_{plugin_name}", "blacklist", default=[])
                
                if whitelist and blacklist:
                    logger.error("Plugin/Agent %s has BOTH whitelist and blacklist. Rejecting.", plugin_name)
                    return
                    
                allowed = True
                if whitelist:
                    allowed = target_user in whitelist or (target_group and target_group in whitelist)
                elif blacklist:
                    allowed = target_user not in blacklist and (not target_group or target_group not in blacklist)
                    
                if not allowed:
                    logger.info("User %s is unauthorized for %s. Silently dropping.", target_user, plugin_name)
                    return

        # --- Guest Mode Enforcement Start ---
        guest_cfg = app_config.get_guest_config()
        if guest_cfg.get("enabled", False) and not is_su and route.mode in ["command", "agent"]:
            whitelisted_users = [str(u) for u in guest_cfg.get("whitelisted_users", [])]
            whitelisted_groups = [str(g) for g in guest_cfg.get("whitelisted_groups", [])]

            is_member = (
                str(msg.user_id) in whitelisted_users
                or str(primary_uid) in whitelisted_users
                or (bool(msg.group_id) and str(msg.group_id) in whitelisted_groups)
            )

            if not is_member:
                policy = guest_cfg.get("policy", "safe_commands_only")
                if policy == "disabled":
                    logger.info("Guest mode: silently dropping message from guest %s in %s", primary_uid, msg.group_id or "DM")
                    return
                elif policy == "safe_commands_only":
                    if route.mode == "command":
                        allowed_plugins = guest_cfg.get("allowed_plugins", [])
                        if route.plugin not in allowed_plugins:
                            logger.info("Guest %s tried to execute non-allowed command %s", primary_uid, route.plugin)
                            from core.types import Action
                            sender.deliver_actions(payload, [Action(kind="reply", text="403: nemo: 访客模式下仅开放基础查询指令（如 /upfx 汇率、/ticker 行情、/weather 天气等）。")])
                            return
                    elif route.mode == "agent":
                        logger.info("Guest %s tried to trigger agent in safe_commands_only mode", primary_uid)
                        from core.types import Action
                        sender.deliver_actions(payload, [Action(kind="reply", text="[Nemo] 当前处于访客模式，全量智能体对话暂未对访客开放。输入 /help 可查看可用的公共查询指令。")])
                        return
                elif policy == "sandboxed_agent":
                    now_ts = time.time()
                    current_hour = int(now_ts // 3600)
                    rate_key = f"{primary_uid}:{current_hour}"
                    cur_count = state_store.get("guest_rate", "hourly", rate_key, default=0)
                    limit = int(guest_cfg.get("rate_limit_per_hour", 10))
                    if cur_count >= limit:
                        logger.info("Guest %s exceeded hourly limit %s", primary_uid, limit)
                        from core.types import Action
                        sender.deliver_actions(payload, [Action(kind="reply", text="429: nemo: 访客每小时请求次数已达上限，请稍后再试。")])
                        return
                    state_store.set("guest_rate", "hourly", rate_key, cur_count + 1)
        # --- Guest Mode Enforcement End ---
        # --- ACL Logic End ---

        # --- Affinity Tracking Start ---
        try:
            from runtime import context as rt_context
            if rt_context.affinity_store is not None:
                rt_context.affinity_store.record_message(
                    primary_uid, engaged=route.mode in ("command", "agent")
                )
        except Exception:
            logger.exception("Affinity tracking failed")
        # --- Affinity Tracking End ---

        # --- Group Ambient Digest (L1) Start ---
        try:
            from runtime import context as rt_context
            if msg.group_id and rt_context.group_digest_store is not None:
                if rt_context.group_digest_store.record(msg.group_id):
                    executor.submit_dispatch(rt_context.group_digest_store.compress, msg.group_id)
        except Exception:
            logger.exception("Group digest tracking failed")
        # --- Group Ambient Digest (L1) End ---

        if route.mode == "command":
            _execute_command(raw_msg, route)
        elif route.mode == "agent":
            run_id = uuid.uuid4().hex[:6]
            def observer_callback(actions):
                sender.deliver_actions(payload, actions)
            
            agent_query = route.query
            if msg.reply_to:
                if "text" in msg.reply_to:
                    reply_user = msg.reply_to.get("user_name") or msg.reply_to.get("user_id") or "未知"
                    reply_id = msg.reply_to.get("message_id", "未知ID")
                    agent_query = f"【引用了消息】({reply_user}/{reply_id}): {msg.reply_to['text']}\n【回复】: {agent_query}"
                if msg.reply_to.get("imgs"):
                    msg.imgs.extend(msg.reply_to["imgs"])
                    raw_msg.request.imgs.extend(msg.reply_to["imgs"])
            
            actions = agent_runner.run(raw_msg, agent_query, run_id=run_id, observer=observer_callback)
            sender.deliver_actions(payload, actions)
        elif route.mode == "man":
            _handle_man(payload, route)
        elif route.mode == "explain":
            _handle_explain(payload, route)
        elif route.mode == "silent":
            pass

    except Exception as e:
        logger.exception("Error in dispatch worker")
        try:
            from core.types import Action
            sender.deliver_actions(payload, [Action(kind="reply", text=f"500: nemo: 内部错误 (Internal Server Error) - {str(e)}")])
        except Exception as inner_e:
            logger.error("Failed to send error message back: %s", inner_e)


def _execute_command(msg, route):
    logger.info(
        "[Command Triggered] Plugin: %s | Args: %r | User: %s | Group: %s",
        route.plugin, route.args, msg.context.user_id, msg.context.group_id or "DM"
    )
    config = state_store.get_plugin_config(route.plugin)
    
    # We mutate the MessageRequest args for the plugin to see exactly what matched
    msg_dict = msg.to_dict()
    msg_dict["request"]["args"] = route.args
    msg_dict["request"]["command"] = route.plugin
    
    result = executor.run_plugin_sync(msg_dict, route.plugin, config)
    sender.deliver(msg_dict, result)
    
    if result.get("config") and result["config"] != config:
        state_store.set_plugin_config(route.plugin, result["config"])


def _handle_man(payload: dict, route):
    import importlib
    from plugins import plugin_names
    
    args = getattr(route, "args", "").strip()
    msg = IngestMessage.from_dict(payload)
    reply_text = ""
    
    if not args:
        reply_text = "nemo-bot 操作手册实用程序。\n以下是 [该插件所有可能的指令] 和 [该插件简介] 。\n"
        for module_name in plugin_names:
            try:
                mod = importlib.import_module(f"plugins.{module_name}")
                cmds = getattr(mod, "_command", [])
                name = getattr(mod, "_name", module_name)
                if cmds:
                    reply_text += f"{' '.join(cmds)} ({module_name}): {name}\n"
            except Exception:
                continue
        reply_text += "使用 man [该插件可能的指令] 来查看对应插件的操作手册。"
    else:
        found_mod = None
        for module_name in plugin_names:
            try:
                mod = importlib.import_module(f"plugins.{module_name}")
                cmds = getattr(mod, "_command", [])
                if args in cmds:
                    found_mod = mod
                    break
            except Exception:
                continue
        if found_mod:
            name = getattr(found_mod, "_name", args)
            man_text = getattr(found_mod, "_man", "该指令未提供手册。")
            reply_text = f"nemo-bot 操作手册实用程序。\n{name}\n{man_text}"
        else:
            reply_text = "未找到该指令对应的手册，可以使用 EXPLAIN 指令来进行诊断。"
            
    from core.types import Action
    sender.deliver_actions(payload, [Action(kind="reply", text=reply_text)])

def _handle_explain(payload: dict, route):
    msg = IngestMessage.from_dict(payload)
    args = getattr(route, "args", "")
    
    reply_text = (
        f"nemo-bot EXPLAIN 和诊断实用程序。\n"
        f"你当前解析出的指令为: {route.mode if route.mode else '未知'}\n"
        f"你当前提供的参数为: {args}\n"
        f"你的 ID 是: {msg.user_id} {'，当前在群组 ID ' + str(msg.group_id) + ' 中' if msg.group_id else ''}"
    )
    from core.types import Action
    sender.deliver_actions(payload, [Action(kind="reply", text=reply_text)])


# ======================================================================
# Main Entry Point
# ======================================================================

if __name__ == "__main__":
    import multiprocessing
    import sys
    multiprocessing.freeze_support()  # Required for Windows ProcessPoolExecutor

    setup()

    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        logger.info("Initialization check passed successfully!")
        print("OK")
        sys.exit(0)

    import atexit
    @atexit.register
    def cleanup():
        logger.info("Shutting down...")
        if scheduler:
            scheduler.shutdown()
        if executor:
            executor.shutdown()
        if hasattr(state_store, "close"):
            state_store.close()

    server_cfg = app_config.backend_config.get("server", {})
    app.run(
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 42164),
    )

