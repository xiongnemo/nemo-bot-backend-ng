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
)

T0 = 1_700_000_000.0
HOUR = 3600.0


class LayeredBase(unittest.TestCase):
    def setUp(self):
        self.path = "data/test_layered.sqlite"
        self._cleanup()
        self.db = Database(self.path)
        self.state_store = StateStore(self.db)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
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


if __name__ == "__main__":
    unittest.main()
