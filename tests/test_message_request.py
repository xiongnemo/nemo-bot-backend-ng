import unittest
from core.message_request import MessageRequest
from core.message import Message
from core.recording_message import RecordingMessage


class TestMessageRequest(unittest.TestCase):
    def test_message_request_basic(self):
        req = MessageRequest({"args": "test", "command": "echo"})
        self.assertEqual(req.args, "test")
        self.assertEqual(req.command, "echo")
        self.assertEqual(req.message_id, "")

    def test_message_request_with_reply_to(self):
        reply_data = {
            "message_id": "123456",
            "user_id": "789",
            "user_name": "Alice",
            "text": "Hello world",
            "imgs": ["http://example.com/img.jpg"]
        }
        req = MessageRequest({"args": "reply test", "command": "vision", "reply_to": reply_data})
        self.assertEqual(req.reply_to, reply_data)
        self.assertEqual(req.message_id, "123456")

    def test_message_request_explicit_message_id(self):
        req = MessageRequest({"args": "test", "command": "echo", "message_id": "msg_999"})
        self.assertEqual(req.message_id, "msg_999")

    def test_message_and_recording_message_serialization(self):
        payload = {
            "frontend": "onebot",
            "context": {
                "group_id": "100",
                "user_id": "200",
                "user_name": "Bob",
                "message_id": "msg_001",
                "self_id": "300",
                "ated": False,
                "frontend_system_info": "info"
            },
            "request": {
                "command": "vision_analyze",
                "args": "http://img.png analyze",
                "imgs": ["http://img.png"],
                "raw_message": "",
                "reply_to": {
                    "message_id": "reply_999",
                    "user_id": "300",
                    "user_name": "Charlie",
                    "text": "Check this out",
                    "imgs": ["http://reply_img.png"]
                }
            }
        }
        msg = Message(payload)
        self.assertEqual(msg.request.message_id, "reply_999")
        d = msg.to_dict()
        self.assertEqual(d["request"]["message_id"], "reply_999")

        rec_msg = RecordingMessage(payload)
        self.assertEqual(rec_msg.request.message_id, "reply_999")
        rd = rec_msg.to_dict()
        self.assertEqual(rd["request"]["message_id"], "reply_999")
        self.assertEqual(rd["request"]["reply_to"]["message_id"], "reply_999")


if __name__ == "__main__":
    unittest.main()
