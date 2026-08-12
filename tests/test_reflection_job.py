import json
import os
import time
import unittest
from unittest import mock

from store.database import Database
from store.state_store import StateStore
from store.conversation_store import ConversationStore
from store.affinity_store import AffinityStore
from store.profile_store import ProfileStore
from store.topic_store import TopicStore
from runtime import context

GROUP_SCOPE = "agent:onebot:group:485541033"
DM_SCOPE = "agent:onebot:dm:3240295516"

REFLECTION_OUTPUT = {
    "topics": ["讨论了塞尔达新作"],
    "core_facts": [{"user_id": "111", "fact": "是程序员"}],
    "profile_updates": [
        {"user_id": "111", "field": "occupation", "value": "程序员"},
        {"user_id": "111", "field": "hobbies", "value": "塞尔达"},
        {"user_id": "111", "field": "password", "value": "should_be_dropped"},
    ],
    "affinity_adjustments": [{"user_id": "111", "delta": 9, "reason": "全天热心助人"}],
}


class DummyResp:
    text = json.dumps(REFLECTION_OUTPUT, ensure_ascii=False)


class DummyClient:
    def chat(self, model, messages, system):
        return DummyResp()


class TestReflectionJob(unittest.TestCase):
    def setUp(self):
        self.path = "data/test_reflection.sqlite"
        self._cleanup_files()
        self.db = Database(self.path)
        self.state_store = StateStore(self.db)
        self.conv_store = ConversationStore(self.db)
        # Mount runtime context the way app.setup() does
        self._saved = {k: getattr(context, k) for k in
                       ("db", "state_store", "topic_store", "profile_store", "affinity_store")}
        context.db = self.db
        context.state_store = self.state_store
        context.topic_store = TopicStore(self.db)
        context.profile_store = ProfileStore(self.state_store)
        context.affinity_store = AffinityStore(self.state_store)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(context, k, v)
        self._cleanup_files()

    def _cleanup_files(self):
        for ext in ["", "-shm", "-wal"]:
            p = self.path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def _seed_scope(self, scope, n=12):
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            self.conv_store.append(scope, role, f"message {i} in {scope}")

    def test_reflection_full_flow(self):
        self._seed_scope(GROUP_SCOPE)
        self._seed_scope(DM_SCOPE)
        # An ancient conversation row that must be pruned
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO conversations (scope_key, role, content, created_at) VALUES (?, 'user', 'ancient', ?)",
            (GROUP_SCOPE, time.time() - 30 * 86400),
        )
        conn.commit()

        import agent.reflection_job as rj
        with mock.patch.object(rj, "get_reflection_model", return_value=["dummy:model"]), \
             mock.patch.object(rj, "get_reflection_retention_days", return_value=14.0), \
             mock.patch("nemollm.registry.get_client", return_value=(DummyClient(), "dummy-model")):
            rj.run_reflection_job()

        # Topics written for both scopes (group AND dm are now scanned)
        self.assertEqual(context.topic_store.recent(GROUP_SCOPE), ["讨论了塞尔达新作"])
        self.assertEqual(context.topic_store.recent(DM_SCOPE), ["讨论了塞尔达新作"])

        # Core facts appended, deduped across the two scope batches
        facts = self.state_store.get("memory", "user_111", "facts", default=[])
        self.assertEqual(facts, ["是程序员"])

        # Profile written with whitelist enforcement
        profile = context.profile_store.get("111")
        self.assertEqual(profile["occupation"], "程序员")
        self.assertEqual(profile["hobbies"], ["塞尔达"])
        self.assertNotIn("password", profile)

        # Affinity adjusted with reflection daily cap (+3) from the 0 baseline
        st = context.affinity_store.get_state("111")
        self.assertAlmostEqual(st["score"], 3.0, places=1)

        # Ancient conversation row pruned; recent ones retained
        rows = conn.execute("SELECT COUNT(*) FROM conversations WHERE content='ancient'").fetchone()[0]
        self.assertEqual(rows, 0)
        remaining = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        self.assertEqual(remaining, 24)

    def test_parse_fallback_with_markdown_noise(self):
        from agent.reflection_job import _parse_reflection_json
        noisy = "好的，以下是分析结果：\n```json\n" + json.dumps(REFLECTION_OUTPUT) + "\n```"
        data = _parse_reflection_json(noisy)
        self.assertEqual(data["topics"], REFLECTION_OUTPUT["topics"])

    def test_retention_zero_disables_cleanup(self):
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO conversations (scope_key, role, content, created_at) VALUES (?, 'user', 'ancient', ?)",
            (GROUP_SCOPE, time.time() - 30 * 86400),
        )
        conn.commit()
        import agent.reflection_job as rj
        with mock.patch.object(rj, "get_reflection_retention_days", return_value=0.0):
            rj._cleanup(conn)
        rows = conn.execute("SELECT COUNT(*) FROM conversations WHERE content='ancient'").fetchone()[0]
        self.assertEqual(rows, 1)


if __name__ == "__main__":
    unittest.main()
