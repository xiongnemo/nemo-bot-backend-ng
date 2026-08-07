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
kv_daemon: Any = None
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
    global db, state_store, kv_daemon, msg_store, conv_store, executor, sender, feed_service
    global ruleset, router, tool_registry, tool_executor, agent_runner, scheduler
    
    logger.info("Initializing nemo-bot-backend-ng...")

    import sys
    is_check_mode = len(sys.argv) > 1 and sys.argv[1] == "--check"

    # 1. Stores
    db = Database()
    storage_cfg = app_config.backend_config.get("storage", {})
    if storage_cfg.get("enabled", False) and not is_check_mode:
        from store.zmq_daemon import KVStorageDaemon
        from store.zmq_client import ZmqStateStore
        endpoint = storage_cfg.get("endpoint", "inproc://nemo-kv")
        backend = storage_cfg.get("backend", "sqlite")
        rdb_path = storage_cfg.get("rocksdb_path", "data/nemo_rocksdb")
        kv_daemon = KVStorageDaemon(endpoint=endpoint, db=db, backend=backend, rocksdb_path=rdb_path)
        kv_daemon.start(background=True)
        state_store = ZmqStateStore(endpoint=endpoint)
        logger.info("ZMQ Storage Daemon enabled (backend=%s, endpoint=%s)", backend, endpoint)
    else:
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
    context.affinity_store = AffinityStore(state_store)
    context.profile_store = ProfileStore(state_store)
    context.topic_store = TopicStore(db)

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
        return jsonify({"error": "Invalid JSON payload"}), 400

    success, msg, status_code = feed_service.handle_incoming_feed(payload)
    if not success:
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
    channel_name = payload.get("name")
    description = payload.get("description", "")
    if not channel_name:
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
        logger.info("Routed message to: %s", route.mode)

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
        if kv_daemon:
            kv_daemon.stop()

    server_cfg = app_config.backend_config.get("server", {})
    app.run(
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 42164),
    )

