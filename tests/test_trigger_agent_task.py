import unittest
from runtime import context
from core.message import Message
from agent.builtin_tools import trigger_agent_task


class DummyAgentRunner:
    def __init__(self):
        self.last_msg = None
        self.last_config = None

    def run(self, msg: Message, config=None):
        self.last_msg = msg
        self.last_config = config
        return "Task completed"


class DummyExecutor:
    def __init__(self):
        self.dispatched = False

    def submit_dispatch(self, func, *args, **kwargs):
        self.dispatched = True
        func(*args, **kwargs)


class DummySender:
    def deliver_actions(self, *args, **kwargs):
        pass


class TestTriggerAgentTask(unittest.TestCase):
    def setUp(self):
        self.runner = DummyAgentRunner()
        self.executor = DummyExecutor()
        self.sender = DummySender()
        context.agent_runner = self.runner
        context.executor = self.executor
        context.sender = self.sender

    def test_trigger(self):
        res = trigger_agent_task(
            frontend="console",
            context={"group_id": "123", "user_id": "456"},
            prompt="Test prompt",
            task_id="test_job_123",
        )
        self.assertTrue(self.executor.dispatched)
        self.assertIsNotNone(self.runner.last_msg)
        self.assertIn("Test prompt", self.runner.last_msg.text)
        self.assertIn("test_job_123", self.runner.last_msg.text)


if __name__ == "__main__":
    unittest.main()
