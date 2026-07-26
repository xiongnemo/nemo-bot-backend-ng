import sys
sys.path.append('.')

from runtime import context
from core.message import Message

class DummyAgentRunner:
    def run(self, msg: Message):
        print("AgentRunner executed with message:", msg.text)

class DummyExecutor:
    def submit_dispatch(self, func, *args, **kwargs):
        print("Executor received dispatch!")
        func(*args, **kwargs)

context.agent_runner = DummyAgentRunner()
context.executor = DummyExecutor()

from agent.builtin_tools import trigger_agent_task

# Run the task directly
trigger_agent_task(
    frontend="console",
    context={"group_id": "123", "user_id": "456"},
    prompt="Test prompt",
    task_id="test_job_123"
)
