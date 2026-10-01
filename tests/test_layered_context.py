import json
import os
import time
import unittest
from unittest import mock

from store.database import Database
from store.state_store import StateStore
from store.conversation_store import ConversationStore
from store.message_store import MessageStore
from store.user_thread import UserThreadStore
from store.group_digest import GroupDigestStore
from agent.context_loader import (
    load_weighted_history, retrieve_related, trim_memory_blocks, _split_turns,
    load_interturn_chatter,
)

T0 = 1_700_000_000.0
HOUR = 3600.0


class LayeredBase(unittest.TestCase):
    def setUp(self):
        self.path = f"data/test_layered_{self._testMethodName}.sqlite"
        self._cleanup()
        self.db = Database(self.path)
        self.state_store = StateStore(self.db)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if hasattr(self, "db"):
            self.db.close()
        for ext in ["", "-shm", "-wal"]:
            p = self.path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


class TestUserThread(LayeredBase):
    def setUp(self):
        super().setUp()
        self.store = UserThreadStore(self.state_store)

    def test_salience(self):
        self.assertEqual(self.store._salience("哈哈哈", [], []), 0)
        self.assertEqual(self.store._salience("查一下天气", ["weather"], []), 2)
        self.assertEqual(self.store._salience("查一下天气", ["think"], []), 1)
        self.assertGreaterEqual(self.store._salience("帮我看看这个报错" * 5, ["python_sandbox"], ["affinity"]), 5)

    def test_append_and_eviction(self):
        for i in range(3):
            self.store.append_turn("u1", "dm", "哈哈哈", "嗯", now=T0 + i)
        for i in range(25):
            self.store.append_turn("u1", "dm", f"正经问题 {i}", "答", tools=["weather"], now=T0 + 10 + i)
        buf = self.state_store.get("user_thread", "user_u1", "buffer")
        self.assertEqual(len(buf), 20)
        self.assertTrue(all(e["sal"] > 0 for e in buf))  # trivial entries evicted first

    def test_should_compress_by_count_and_age(self):
        for i in range(7):
            self.store.append_turn("u1", "dm", f"q{i}", "a", now=T0 + i)
        self.assertFalse(self.store.should_compress("u1", now=T0 + 10))
        self.store.append_turn("u1", "dm", "q8", "a", now=T0 + 8)
        self.assertTrue(self.store.should_compress("u1", now=T0 + 10))
        # age trigger
        for i in range(3):
            self.store.append_turn("u2", "dm", f"q{i}", "a", now=T0)
        self.assertFalse(self.store.should_compress("u2", now=T0 + HOUR))
        self.assertTrue(self.store.should_compress("u2", now=T0 + 49 * HOUR))

    def test_compress_success_and_privacy(self):
        for i in range(8):
            scene = "dm" if i % 2 == 0 else "group:123"
            self.store.append_turn("u1", scene, f"问题{i}", f"回答{i}", tools=["weather"], now=T0 + i)
        fake = json.dumps({"lines": [
            {"text": "常问天气", "scene": "group"},
            {"text": "私聊聊过工作烦恼", "scene": "dm"},
        ]}, ensure_ascii=False)
        with mock.patch("agent.compress_llm.call_cheap_model", return_value=fake):
            ok = self.store.compress("u1", now=T0 + 100)
        self.assertTrue(ok)
        digest = self.state_store.get("user_thread", "user_u1", "digest")
        self.assertEqual(len(digest["lines"]), 2)
        buf = self.state_store.get("user_thread", "user_u1", "buffer")
        self.assertEqual(len(buf), 2)  # keep_recent_after_compress

        ctx_dm = self.store.get_context("u1", in_group=False, now=T0 + 101)
        self.assertEqual(len(ctx_dm["digest"]), 2)
        ctx_group = self.store.get_context("u1", in_group=True, now=T0 + 101)
        self.assertEqual(ctx_group["digest"], ["常问天气"])  # dm line hidden in group
        for line in ctx_group["recent"]:
            self.assertNotIn("私聊", line)

    def test_compress_parse_failure_keeps_buffer(self):
        for i in range(8):
            self.store.append_turn("u1", "dm", f"q{i}", "a", now=T0 + i)
        with mock.patch("agent.compress_llm.call_cheap_model", return_value="不是JSON的胡话"):
            ok = self.store.compress("u1", now=T0 + 100)
        self.assertFalse(ok)
        self.assertEqual(len(self.state_store.get("user_thread", "user_u1", "buffer")), 8)


class TestGroupDigest(LayeredBase):
    def setUp(self):
        super().setUp()
        self.msg_store = MessageStore(self.db)
        self.store = GroupDigestStore(self.state_store, self.db)

    def _seed_messages(self, gid, n, start_ts):
        for i in range(n):
            self.msg_store.ingest(
                frontend="onebot", group_id=gid, user_id=f"u{i % 3}",
                user_name=f"名字{i % 3}", text=f"聊天内容 {i}", message_id=f"m{start_ts}-{i}",
                timestamp=start_ts + i,
            )

    def test_count_trigger(self):
        triggered = [self.store.record("g1", now=T0 + i) for i in range(80)]
        self.assertFalse(any(triggered[:79]))
        self.assertTrue(triggered[79])

    def test_age_trigger(self):
        self.state_store.set("group_digest", "group_g1", "state", {"last_ts": T0 - 1000})
        results = [self.store.record("g1", now=T0 + i) for i in range(10)]
        self.assertTrue(results[9])  # min_count reached and window older than 900s

    def test_compress_rolling(self):
        t = time.time() - 200  # near-now base so get_lines staleness check passes
        self.state_store.set("group_digest", "group_g1", "state",
                             {"last_ts": t - 1, "lines": [f"old-{i}" for i in range(5)]})
        self._seed_messages("g1", 15, t)
        with mock.patch("agent.compress_llm.call_cheap_model", return_value="大家在讨论周末去爬山"):
            ok = self.store.compress("g1", now=t + 100)
        self.assertTrue(ok)
        state = self.state_store.get("group_digest", "group_g1", "state")
        self.assertEqual(len(state["lines"]), 5)  # rolling cap
        self.assertIn("大家在讨论周末去爬山", state["lines"][-1])
        self.assertNotIn("old-0", state["lines"])  # oldest rolled out
        self.assertEqual(state["last_ts"], t + 100)
        lines = self.store.get_lines("g1", max_age_hours=24)
        self.assertEqual(len(lines), 5)

    def test_get_lines_stale(self):
        self.state_store.set("group_digest", "group_g1", "state",
                             {"lines": ["x"], "updated_at": time.time() - 30 * 3600})
        self.assertEqual(self.store.get_lines("g1"), [])


class TestContextLoader(LayeredBase):
    def setUp(self):
        super().setUp()
        self.conv = ConversationStore(self.db)

    def _add_turn(self, scope, uid, name, q, a):
        self.conv.append(scope, "user", f"[{name} (ID: {uid})]:\n{q}", metadata={"user_id": uid})
        self.conv.append(scope, "assistant", a)

    def test_dm_passthrough(self):
        for i in range(5):
            self.conv.append("agent:onebot:dm:u1", "user", f"q{i}")
            self.conv.append("agent:onebot:dm:u1", "assistant", f"a{i}")
        msgs = load_weighted_history(self.conv, "agent:onebot:dm:u1", "u1", is_group=False)
        self.assertEqual(len(msgs), 10)

    def test_group_weighted_and_collapse(self):
        scope = "agent:onebot:group:g1"
        # 10 old turns from B, then 3 from A (current speaker), then 2 recent from B
        for i in range(10):
            self._add_turn(scope, "B", "小B", f"B的旧问题{i}", f"B答{i}")
        for i in range(3):
            self._add_turn(scope, "A", "小A", f"A的问题{i}", f"A答{i}")
        for i in range(2):
            self._add_turn(scope, "B", "小B", f"B的新问题{i}", f"B新答{i}")

        msgs = load_weighted_history(self.conv, scope, "A", is_group=True,
                                     cfg={"other_turns_verbatim": 2, "collapse_max_items": 8})
        text = "\n".join(m.content for m in msgs if m.content)
        # A's turns all kept verbatim
        self.assertIn("A的问题0", text)
        self.assertIn("A的问题2", text)
        # B's most recent 2 turns verbatim
        self.assertIn("B的新问题1", text)
        # B's old turns collapsed, capped at 8 items
        self.assertIn("前情提要", text)
        self.assertNotIn("[小B (ID: B)]:\nB的旧问题9", text)  # old B turn not kept verbatim
        collapse_block = next(m.content for m in msgs if "前情提要" in m.content)
        self.assertEqual(collapse_block.count("小B:"), 8)
        # collapse block comes first
        self.assertIn("前情提要", msgs[0].content)

    def test_legacy_rows_without_metadata(self):
        scope = "agent:onebot:group:g2"
        self.conv.append(scope, "user", "[老王 (ID: W1)]:\n老王的问题")
        self.conv.append(scope, "assistant", "答")
        msgs = load_weighted_history(self.conv, scope, "W1", is_group=True)
        self.assertIn("老王的问题", msgs[0].content)  # regex fallback owns the turn

    def test_split_turns_orphan(self):
        rows = [{"role": "assistant", "content": "孤儿"}, {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"}]
        turns = _split_turns(rows)
        self.assertEqual(len(turns), 2)

    def test_retrieve_related(self):
        msg_store = MessageStore(self.db)
        old_ts = time.time() - 3 * 86400
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="小明",
                         text="we discussed kubernetes deployment yesterday", message_id="r1",
                         timestamp=old_ts)
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u2", user_name="小王",
                         text="kubernetes is hard", message_id="r2", timestamp=time.time())
        results = retrieve_related(msg_store, "g1", "how to do kubernetes deployment", top_k=3)
        self.assertEqual(len(results), 1)  # recent one excluded
        self.assertIn("kubernetes", results[0])
        self.assertEqual(retrieve_related(msg_store, "g1", "hi", top_k=3), [])  # too short

    def test_trim_memory_blocks(self):
        blocks = [(1, "A" * 100), (3, "B" * 100), (2, "C" * 100)]
        out = trim_memory_blocks(blocks, budget_chars=250)
        self.assertEqual(len(out), 2)  # prio 3 dropped
        self.assertEqual(out[0][0], "A")
        self.assertEqual(out[1][0], "C")
        # order preserved
        out_all = trim_memory_blocks(blocks, budget_chars=10000)
        self.assertEqual([b[0] for b in out_all], ["A", "B", "C"])
        # high-priority truncation
        out_trunc = trim_memory_blocks([(1, "X" * 500)], budget_chars=300)
        self.assertTrue(out_trunc[0].endswith("…"))


    def test_load_interturn_chatter_basic(self):
        msg_store = MessageStore(self.db)
        scope = "agent:onebot:group:g1"
        # Prior turn at T0
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO conversations (scope_key, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, "assistant", "你好", "{}", T0),
        )
        conn.commit()

        # Messages between T0 and T0 + 100
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="韭菜",
                         text="画线paxg 30m", message_id="m1", timestamp=T0 + 10)
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u2", user_name="小李",
                         text="看看这个", imgs=["http://img.jpg"], message_id="m2", timestamp=T0 + 20)
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="韭菜",
                         text="多行内容\n第二行", message_id="m3", timestamp=T0 + 30)
        # Current message that triggers agent
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="韭菜",
                         text="帮我算一下", message_id="cur_id", timestamp=T0 + 40)

        lines = load_interturn_chatter(
            msg_store=msg_store,
            db=self.db,
            group_id="g1",
            scope_key=scope,
            current_msg_id="cur_id",
            current_ts=T0 + 40,
        )
        self.assertEqual(len(lines), 3)
        self.assertIn("[msg_id: m1] 韭菜: 画线paxg 30m", lines[0])
        self.assertIn("[msg_id: m2] 小李: 看看这个 [附图]", lines[1])
        self.assertIn("[msg_id: m3] 韭菜: 多行内容 第二行", lines[2])
        # Current message must not be in the output
        self.assertFalse(any("帮我算一下" in l for l in lines))

    def test_send_message_with_reply_to_target_id(self):
        from agent.builtin_tools import send_message_executor
        from core.message import Message

        delivered_actions = []

        class MockSender:
            def send_text(self, message_dict, text, reply=True, target_id=None):
                delivered_actions.append({"text": text, "reply": reply, "target_id": target_id})

        msg = Message({
            "frontend": "onebot",
            "context": {"group_id": "g1", "user_id": "u1", "message_id": "cur_msg_id"},
            "request": {"command": "", "args": "", "imgs": [], "raw_message": ""},
        })

        sender = MockSender()
        # Default without message_id
        res1 = send_message_executor({"text": "回复当前"}, msg, sender)
        self.assertEqual(delivered_actions[-1]["target_id"], None)
        self.assertTrue(delivered_actions[-1]["reply"])

        # With specific message_id
        res2 = send_message_executor({"text": "顺便回复之前那条", "message_id": "historical_123"}, msg, sender)
        self.assertEqual(delivered_actions[-1]["target_id"], "historical_123")
        self.assertTrue(delivered_actions[-1]["reply"])
        self.assertIn("historical_123", res2["result"])

    def test_sender_deliver_one_target_id(self):
        from runtime.sender import Sender
        from unittest.mock import patch, MagicMock

        sender = Sender()
        mock_adapter = MagicMock()

        with patch("importlib.import_module", return_value=mock_adapter):
            sender.send_text(
                {"frontend": "onebot", "context": {"group_id": "g1", "user_id": "u1", "message_id": "cur_id"}},
                "顺便回复",
                reply=True,
                target_id="history_999",
            )
            call_kwargs = mock_adapter.send_msg.call_args.kwargs
            self.assertEqual(call_kwargs["context"].message_id, "history_999")
            self.assertTrue(call_kwargs["reply"])

    def test_message_store_get_by_message_id(self):
        msg_store = MessageStore(self.db)
        msg_store.ingest(
            frontend="onebot", group_id="g1", user_id="u_alice", user_name="爱丽丝",
            text="hello world", message_id="msg_alice_1", timestamp=T0,
        )
        row = msg_store.get_by_message_id("msg_alice_1")
        self.assertIsNotNone(row)
        self.assertEqual(row["user_id"], "u_alice")
        self.assertEqual(row["user_name"], "爱丽丝")
        self.assertEqual(row["text"], "hello world")

        self.assertIsNone(msg_store.get_by_message_id("non_existent"))
        self.assertIsNone(msg_store.get_by_message_id(""))

    def test_runner_send_message_per_person_rate_limiting(self):
        from agent.runner import AgentRunner
        from agent.tool_registry import ToolRegistry
        from agent.tool_executor import ToolExecutor
        from agent.builtin_tools import register_builtin_tools
        from nemollm.memory import ConversationMemory
        from runtime import context as rt_context
        from nemollm.types import ToolCall
        from nemollm import ChatMessage
        from core.message import Message
        from unittest.mock import MagicMock, patch

        msg_store = MessageStore(self.db)
        rt_context.msg_store = msg_store
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="Alice",
                         text="Alice says hi", message_id="mid_alice_1", timestamp=T0)
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u1", user_name="Alice",
                         text="Alice says bye", message_id="mid_alice_2", timestamp=T0 + 1)
        msg_store.ingest(frontend="onebot", group_id="g1", user_id="u2", user_name="Bob",
                         text="Bob asks a question", message_id="mid_bob_1", timestamp=T0 + 2)

        registry = ToolRegistry()
        mock_sender = MagicMock()
        register_builtin_tools(registry, msg_store, self.state_store, None)
        executor = ToolExecutor(registry, None, self.state_store, mock_sender)
        memory = ConversationMemory(self.conv)
        runner = AgentRunner(memory, self.state_store, registry, executor)

        resp1 = MagicMock()
        resp1.text = ""
        resp1.tool_calls = [
            ToolCall(id="tc1", name="send_message", arguments={"text": "hi Alice", "message_id": "mid_alice_1"}),
            ToolCall(id="tc2", name="send_message", arguments={"text": "hi Bob", "message_id": "mid_bob_1"}),
        ]

        resp2 = MagicMock()
        resp2.text = ""
        resp2.tool_calls = [
            ToolCall(id="tc3", name="send_message", arguments={"text": "hi again Alice", "message_id": "mid_alice_2"}),
        ]

        resp3 = MagicMock()
        resp3.text = "Answer to Charlie"
        resp3.tool_calls = []

        mock_client = MagicMock()
        mock_client.chat.side_effect = [resp1, resp2, resp3]

        with patch("nemollm.registry.get_registry") as mock_get_reg:
            mock_reg_inst = MagicMock()
            mock_reg_inst.get_models.return_value = [(mock_client, "fake-model")]
            mock_get_reg.return_value = mock_reg_inst

            trigger_msg = Message({
                "frontend": "onebot",
                "context": {"group_id": "g1", "user_id": "u3", "user_name": "Charlie", "message_id": "mid_charlie_1"},
                "request": {"command": "", "args": "What about the market?", "imgs": [], "raw_message": ""},
            })

            actions = runner.run(trigger_msg, "What about the market?")
            # mock_sender.send_text should have been called exactly twice (once Alice, once Bob)
            self.assertEqual(mock_sender.send_text.call_count, 2)
            targets = [c.kwargs.get("target_id") for c in mock_sender.send_text.call_args_list]
            self.assertEqual(targets, ["mid_alice_1", "mid_bob_1"])

            # Final action is the reply to Charlie
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].text, "Answer to Charlie")

    def test_load_interturn_chatter_cap_and_order(self):
        msg_store = MessageStore(self.db)
        scope = "agent:onebot:group:g2"
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO conversations (scope_key, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, "assistant", "已回复", "{}", T0),
        )
        conn.commit()

        # Ingest 20 messages
        for i in range(20):
            msg_store.ingest(frontend="onebot", group_id="g2", user_id="u", user_name="群友",
                             text=f"消息{i:02d}", message_id=f"m_{i}", timestamp=T0 + 1 + i)

        lines = load_interturn_chatter(
            msg_store=msg_store,
            db=self.db,
            group_id="g2",
            scope_key=scope,
            current_ts=T0 + 25,
            max_messages=5,
        )
        # Should be capped to 5 most recent (messages 15 to 19), in chronological order
        self.assertEqual(len(lines), 5)
        self.assertIn("消息15", lines[0])
        self.assertIn("消息19", lines[4])

    def test_load_interturn_chatter_lookback_limit(self):
        msg_store = MessageStore(self.db)
        scope = "agent:onebot:group:g3"
        conn = self.db.get_conn()
        # Prior turn was 10 hours ago
        conn.execute(
            "INSERT INTO conversations (scope_key, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, "assistant", "早前回复", "{}", T0 - 36000),
        )
        conn.commit()

        # Message older than max_lookback_seconds (7200s)
        msg_store.ingest(frontend="onebot", group_id="g3", user_id="u", user_name="群友",
                         text="太久远的消息", message_id="old_m", timestamp=T0 - 8000)
        # Message within 2 hours
        msg_store.ingest(frontend="onebot", group_id="g3", user_id="u", user_name="群友",
                         text="近期的消息", message_id="recent_m", timestamp=T0 - 1000)

        lines = load_interturn_chatter(
            msg_store=msg_store,
            db=self.db,
            group_id="g3",
            scope_key=scope,
            current_ts=T0,
            max_lookback_seconds=7200.0,
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("近期的消息", lines[0])


if __name__ == "__main__":
    unittest.main()
