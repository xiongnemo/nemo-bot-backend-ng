import unittest
from unittest.mock import patch, MagicMock
from core.message_context import MessageContext
from adapters import discord as discord_adapter


class TestDiscordAdapter(unittest.TestCase):
    def setUp(self):
        # Clear DM cache
        discord_adapter._dm_channel_cache.clear()

    def test_chunk_discord_message_short(self):
        msg = "Hello world! This is a short message."
        chunks = discord_adapter._chunk_discord_message(msg, max_len=100)
        self.assertEqual(chunks, [msg])

    def test_chunk_discord_message_long_plain(self):
        # Create a message of 250 characters
        lines = [f"Line {i:02d}: some message content here." for i in range(10)]
        msg = "\n".join(lines)
        chunks = discord_adapter._chunk_discord_message(msg, max_len=100)
        self.assertTrue(len(chunks) > 1)
        for c in chunks:
            self.assertLessEqual(len(c), 100)
        # Rejoined content should match original
        self.assertEqual("".join(chunks), msg)

    def test_chunk_discord_message_preserves_code_block(self):
        code_body = "\n".join([f"    x_{i} = {i} * 2" for i in range(15)])
        msg = f"Intro text\n```python\n{code_body}\n```\nEnd text"
        chunks = discord_adapter._chunk_discord_message(msg, max_len=120)
        self.assertTrue(len(chunks) >= 2)
        
        # If a chunk split inside the code block, it should close and reopen code block
        first_chunk = chunks[0]
        second_chunk = chunks[1]
        self.assertTrue(first_chunk.endswith("```"))
        self.assertTrue(second_chunk.startswith("```python\n"))

    def test_resolve_target_channel_with_group_id(self):
        ctx = MessageContext({"group_id": "9876543210", "user_id": "11111"})
        ch = discord_adapter._resolve_target_channel(ctx)
        self.assertEqual(ch, "9876543210")

    def test_resolve_target_channel_with_explicit_channel_id(self):
        ctx = MessageContext({"channel_id": "8888888888", "user_id": "11111"})
        ch = discord_adapter._resolve_target_channel(ctx)
        self.assertEqual(ch, "8888888888")

    @patch("adapters.discord.s.request")
    def test_resolve_target_channel_dm(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "dm_channel_12345"}
        mock_request.return_value = mock_resp

        ctx = MessageContext({"group_id": "", "user_id": "55555"})
        ch = discord_adapter._resolve_target_channel(ctx)
        self.assertEqual(ch, "dm_channel_12345")
        self.assertEqual(discord_adapter._dm_channel_cache["55555"], "dm_channel_12345")

        # Second call should use cache without HTTP request
        mock_request.reset_mock()
        ch2 = discord_adapter._resolve_target_channel(ctx)
        self.assertEqual(ch2, "dm_channel_12345")
        mock_request.assert_not_called()

    @patch("adapters.discord.s.request")
    def test_send_msg_success(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg_999", "content": "test reply"}
        mock_request.return_value = mock_resp

        ctx = MessageContext({
            "group_id": "123456",
            "message_id": "prev_111",
            "user_id": "777",
        })

        res = discord_adapter.send_msg(ctx, "test reply", reply=True)
        self.assertEqual(res.get("id"), "msg_999")
        
        # Verify request parameters
        mock_request.assert_called_once()
        method, url = mock_request.call_args[0]
        kwargs = mock_request.call_args[1]
        self.assertEqual(method, "POST")
        self.assertIn("/channels/123456/messages", url)
        self.assertEqual(kwargs["json"]["content"], "test reply")
        self.assertEqual(kwargs["json"]["message_reference"]["message_id"], "prev_111")

    @patch("adapters.discord.s.request")
    def test_send_photo_url(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg_photo_1"}
        mock_request.return_value = mock_resp

        ctx = MessageContext({"group_id": "123456", "message_id": "777"})
        res = discord_adapter.send_photo(ctx, message="Check this", photo="https://example.com/pic.png")
        self.assertEqual(res.get("id"), "msg_photo_1")
        
        mock_request.assert_called_once()
        kwargs = mock_request.call_args[1]
        self.assertEqual(kwargs["json"]["embeds"][0]["image"]["url"], "https://example.com/pic.png")

    @patch("adapters.discord.s.request")
    def test_withdraw_and_pin(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_request.return_value = mock_resp

        ctx = MessageContext({"group_id": "123456"})
        
        # Withdraw
        res_w = discord_adapter.withdraw(ctx, "msg_to_del")
        self.assertEqual(res_w, "撤回成功")
        self.assertEqual(mock_request.call_args[0][0], "DELETE")

        # Pin
        res_p = discord_adapter.pin(ctx, "msg_to_pin")
        self.assertEqual(res_p, "置顶成功")
        self.assertEqual(mock_request.call_args[0][0], "PUT")

    @patch("adapters.discord.send_msg")
    def test_sender_delivery_to_discord(self, mock_send_msg):
        from runtime.sender import Sender
        from core.types import Action

        mock_send_msg.return_value = {"ok": True, "id": "123"}

        sender = Sender()
        payload = {
            "frontend": "discord",
            "context": {
                "group_id": "channel_999",
                "user_id": "user_888",
                "message_id": "msg_777",
            }
        }
        action = Action(kind="reply", text="Hello Discord User!")
        sender.deliver_actions(payload, [action])

        mock_send_msg.assert_called_once()
        call_kwargs = mock_send_msg.call_args.kwargs
        self.assertEqual(call_kwargs["message"], "Hello Discord User!")
        self.assertTrue(call_kwargs["reply"])
        self.assertEqual(call_kwargs["context"].group_id, "channel_999")


if __name__ == "__main__":
    unittest.main()
