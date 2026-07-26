"""
[插件名称] Plugin
-------------------
插件简要说明...
"""

import logging
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ==========================================
# 1. 必填项 (Mandatory Attributes)
# 框架启动时严格校验，缺少任何一个将导致后端无法启动！
# ==========================================
_name = "我的模板插件"
_command = ["template", "test_plugin"]
_man = "用法: 触发词 [参数] - 用于测试模板"

# ==========================================
# 2. 选填项 (Optional Attributes)
# ==========================================
_enabled = 1  # 0 表示禁用

# 提供给 Agent 调用的系统级工具说明 (非常重要，决定了 LLM 能否正确使用该工具)
_tool_description = "这是一个模板工具，用于..."

# 工具参数的 JSON Schema 定义。
# ⚠️ 踩坑警告：变量名必须是 `_parameters`！千万不要写成 `_tool_parameters`，否则无法被 LLM 正确解析！
_parameters = {
    "type": "object",
    "properties": {
        "arg_name": {
            "type": "string",
            "description": "参数的具体说明"
        }
    },
    "required": ["arg_name"]
}

# ==========================================
# 3. 核心执行逻辑
# 必须带上 @generic_exception_handler 装饰器以兜底未知错误
# ==========================================
@generic_exception_handler
def bot_execute(message: Message, config: dict):
    # 1. 提取参数
    import json
    try:
        args = json.loads(message.request.args)
        arg_name = args.get("arg_name", "").strip()
    except Exception:
        # 兼容传统群聊指令的手动输入 (message.request.text)
        arg_name = message.request.text.strip()
        
    if not arg_name:
        message.payload = {"error": "缺少参数 arg_name"}
        return

    # 2. 核心业务逻辑
    result_text = f"你好，收到参数: {arg_name}"
    
    # 3. 返回给 LLM 或用户的载荷 (Payload 优先供 Agent 读取)
    message.payload = {
        "status": "success",
        "result": result_text
    }
    
    # 4. 可选：直接回复给用户 (如果是供 Agent 当后台工具用的，通常不需要写这一步)
    # message.reply(result_text)
