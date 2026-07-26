import json
import time
import os
from utilities import generic_exception_handler
from core.message import Message

_name = "记录反馈"
_command = ["feedback", "record_feedback"]
_tool_description = "记录系统反馈、Agent 自己的意见、或者用户的建议。这些反馈会持久化保存下来，供后续维护和改进使用。如果你发现有什么工具不好用、有什么逻辑不合理，可以通过这个工具写下来。"
_parameters = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["bug", "feature_request", "agent_thought", "user_feedback", "other"],
            "description": "反馈的分类"
        },
        "content": {
            "type": "string",
            "description": "具体的反馈内容"
        }
    },
    "required": ["category", "content"]
}

@generic_exception_handler
def bot_execute(message: Message, config: dict) -> str:
    args_str = message.request.args
    try:
        kwargs = json.loads(args_str)
    except Exception:
        kwargs = {"category": "other", "content": args_str}
        
    category = kwargs.get("category", "other")
    content = kwargs.get("content", "")
    
    if not content:
        return "400: nemo: Feedback content cannot be empty"
        
    feedback_file = "data/feedback.jsonl"
    os.makedirs("data", exist_ok=True)
    
    record = {
        "timestamp": time.time(),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "category": category,
        "content": content,
        "source_user": message.context.user_id if message.context else "system"
    }
    
    try:
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return f"反馈已成功记录至 {feedback_file}"
    except Exception as e:
        return f"500: nemo: Failed to record feedback: {e}"
