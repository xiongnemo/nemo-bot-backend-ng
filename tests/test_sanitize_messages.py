import unittest
from nemollm import ChatMessage
from nemollm.types import ToolCall
from agent.runner import _sanitize_messages

class TestSanitizeMessages(unittest.TestCase):
    def test_remove_orphaned_tool_message(self):
        # Tool message at the start without preceding assistant with tool_calls
        msgs = [
            ChatMessage(role="tool", content="orphan", tool_call_id="call_1"),
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="hi"),
        ]
        cleaned = _sanitize_messages(msgs)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0].role, "user")
        self.assertEqual(cleaned[1].role, "assistant")

    def test_keep_valid_tool_call_pair(self):
        tc = ToolCall(id="call_123", name="weather", arguments={"query": "Shanghai"})
        msgs = [
            ChatMessage(role="user", content="weather"),
            ChatMessage(role="assistant", content="", tool_calls=[tc]),
            ChatMessage(role="tool", content="Sunny", tool_call_id="call_123", name="weather"),
        ]
        cleaned = _sanitize_messages(msgs)
        self.assertEqual(len(cleaned), 3)

    def test_strip_incomplete_tool_call(self):
        # Assistant declared tool call, but response is missing (e.g. truncated)
        tc = ToolCall(id="call_999", name="weather", arguments={})
        msgs = [
            ChatMessage(role="user", content="weather"),
            ChatMessage(role="assistant", content="Let me check...", tool_calls=[tc]),
            ChatMessage(role="user", content="next question"),
        ]
        cleaned = _sanitize_messages(msgs)
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned[1].role, "assistant")
        self.assertEqual(cleaned[1].content, "Let me check...")
        self.assertIsNone(cleaned[1].tool_calls)

if __name__ == "__main__":
    unittest.main()
