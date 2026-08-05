import json
import logging
import importlib
from core.message import Message
from core.types import Action
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "消息管理 (Message Operations)"
_command = ["message_ops"]
_tool_description = "用于管理聊天消息，支持撤回(withdraw)、置顶精华(pin)、取消置顶(unpin)。如果需要在群里撤回用户消息或者将某些消息设为精华，请使用本工具。"
_enabled = 1
_superuser_only = False  # 代理内部本身不设限，由大模型决定何时调用，且依赖乐观执行

_parameters = {
    "type": "object",
    "properties": {
        "action_type": {
            "type": "string",
            "description": "要执行的操作类型，可选值为: 'withdraw' (撤回/删除消息), 'pin' (置顶/设置精华), 'unpin' (取消置顶/取消精华)",
            "enum": ["withdraw", "pin", "unpin"]
        },
        "target_message_id": {
            "type": "string",
            "description": "要操作的目标消息的唯一 ID (msg_id)。如果你不知道要撤回哪条消息，请先调用 get_recent_messages 获取近期的聊天记录及其 msg_id。"
        }
    },
    "required": ["action_type", "target_message_id"]
}

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    # 结构化参数通过 args 传来（为 JSON 字符串格式）
    args_str = message.request.args
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        return [Action(kind="reply", text="参数解析失败，请确保下发了正确的 JSON 格式")]

    action = args.get("action_type")
    target_id = args.get("target_message_id")
    
    if not action or not target_id:
        return [Action(kind="reply", text="缺少必要的参数: action_type 或 target_message_id")]
        
    frontend = message.frontend
    try:
        adapter = importlib.import_module(f"adapters.{frontend}")
    except ImportError:
        return [Action(kind="reply", text=f"找不到对应平台 {frontend} 的适配器模块。")]

    try:
        if action == "withdraw":
            if hasattr(adapter, "withdraw"):
                result_text = adapter.withdraw(message.context, target_id)
            else:
                return [Action(kind="reply", text=f"当前平台 ({frontend}) 不支持撤回操作。")]
        elif action == "pin":
            if hasattr(adapter, "pin"):
                result_text = adapter.pin(message.context, target_id)
            else:
                return [Action(kind="reply", text=f"当前平台 ({frontend}) 不支持置顶(pin)操作。")]
        elif action == "unpin":
            if hasattr(adapter, "unpin"):
                result_text = adapter.unpin(message.context, target_id)
            else:
                return [Action(kind="reply", text=f"当前平台 ({frontend}) 不支持取消置顶(unpin)操作。")]
        else:
            return [Action(kind="reply", text=f"未知的操作类型: {action}")]
            
        return [Action(kind="reply", text=f"{result_text}")]
    except Exception as e:
        logger.error(f"Message ops {action} failed: {e}", exc_info=True)
        return [Action(kind="reply", text=f"操作执行失败 (可能是权限不足或API报错): {str(e)}")]
