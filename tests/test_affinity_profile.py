import os
import unittest

from store.database import Database
from store.state_store import StateStore
from store.affinity_store import AffinityStore
from store.profile_store import ProfileStore
from store.topic_store import TopicStore

DAY = 86400.0
T0 = 1_700_000_000.0  # fixed base timestamp


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self.path = "data/test_affinity_profile.sqlite"
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


class TestAffinityStore(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.store = AffinityStore(self.state_store)

    def test_initial_state(self):
        st = self.store.get_state("u1", now=T0)
        self.assertEqual(st["score"], 10.0)
        self.assertEqual(st["level"], "认识")

    def test_gain_and_cooldown(self):
        g1 = self.store.record_message("u1", engaged=True, now=T0)
        self.assertEqual(g1, 1.0)
        # within cooldown -> no gain
        g2 = self.store.record_message("u1", engaged=True, now=T0 + 10)
        self.assertEqual(g2, 0.0)
        # after cooldown -> passive gain
        g3 = self.store.record_message("u1", engaged=False, now=T0 + 70)
        self.assertEqual(g3, 0.2)
        st = self.store.get_state("u1", now=T0 + 71)
        self.assertAlmostEqual(st["score"], 11.2, places=3)
        self.assertEqual(st["total_interactions"], 3)

    def test_daily_cap(self):
        now = T0
        for i in range(15):
            self.store.record_message("u1", engaged=True, now=now)
            now += 61
        st = self.store.get_state("u1", now=now)
        # capped at +10 per day (allow tiny decay drift over simulated time)
        self.assertAlmostEqual(st["score"], 20.0, places=1)

    def test_lazy_decay_half_life(self):
        self.store.adjust("u1", 40, "test", source="system", now=T0)  # score 50
        st = self.store.get_state("u1", now=T0 + 30 * DAY)
        # base 10 + (50-10) * 0.5 = 30
        self.assertAlmostEqual(st["score"], 30.0, places=2)
        # negative scores also regress toward base
        self.store.adjust("u2", -25, "bad", source="system", now=T0)  # score -15
        st2 = self.store.get_state("u2", now=T0 + 30 * DAY)
        self.assertAlmostEqual(st2["score"], -2.5, places=2)

    def test_llm_adjust_caps(self):
        r = self.store.adjust("u1", 8, "sweet", source="llm", now=T0)
        self.assertEqual(r["applied_delta"], 5.0)  # single cap ±5
        r2 = self.store.adjust("u1", 5, "sweet again", source="llm", now=T0 + 1)
        self.assertEqual(r2["applied_delta"], 5.0)
        r3 = self.store.adjust("u1", 5, "over budget", source="llm", now=T0 + 2)
        self.assertEqual(r3["applied_delta"], 0.0)  # daily net cap ±10 reached
        st = self.store.get_state("u1", now=T0 + 3)
        self.assertAlmostEqual(st["score"], 20.0, places=3)

    def test_reflection_daily_cap(self):
        r = self.store.adjust("u1", -9, "rude all day", source="reflection", now=T0)
        self.assertEqual(r["applied_delta"], -3.0)

    def test_score_bounds(self):
        self.store.adjust("u1", 500, "huge", source="system", now=T0)
        self.assertEqual(self.store.get_state("u1", now=T0)["score"], 100.0)
        self.store.adjust("u1", -500, "awful", source="system", now=T0 + 1)
        self.assertEqual(self.store.get_state("u1", now=T0 + 1)["score"], -20.0)

    def test_levels(self):
        self.assertEqual(AffinityStore.get_level(-5)[0], "反感")
        self.assertEqual(AffinityStore.get_level(0)[0], "陌生")
        self.assertEqual(AffinityStore.get_level(10)[0], "认识")
        self.assertEqual(AffinityStore.get_level(30)[0], "熟悉")
        self.assertEqual(AffinityStore.get_level(60)[0], "朋友")
        self.assertEqual(AffinityStore.get_level(95)[0], "亲密")

    def test_hot_config_override(self):
        self.state_store.set_plugin_config("affinity", {"gain_engaged": 2.5})
        g = self.store.record_message("u1", engaged=True, now=T0)
        self.assertEqual(g, 2.5)

    def test_get_state_is_readonly(self):
        self.store.adjust("u1", 40, "t", source="system", now=T0)
        self.store.get_state("u1", now=T0 + 30 * DAY)
        raw = self.state_store.get("affinity", "user_u1", "state")
        self.assertAlmostEqual(raw["score"], 50.0, places=2)  # not persisted by read


class TestProfileStore(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.store = ProfileStore(self.state_store)

    def test_str_field_set_and_remove(self):
        self.store.apply("u1", "nickname", "set", "小明")
        self.assertEqual(self.store.get("u1")["nickname"], "小明")
        self.store.apply("u1", "nickname", "remove", "")
        self.assertNotIn("nickname", self.store.get("u1"))

    def test_list_field_append_remove_dedup(self):
        self.store.apply("u1", "hobbies", "append", "钓鱼")
        self.store.apply("u1", "hobbies", "append", "摄影")
        msg = self.store.apply("u1", "hobbies", "append", "钓鱼")
        self.assertIn("已存在", msg)
        self.assertEqual(self.store.get("u1")["hobbies"], ["钓鱼", "摄影"])
        self.store.apply("u1", "hobbies", "remove", "钓鱼")
        self.assertEqual(self.store.get("u1")["hobbies"], ["摄影"])

    def test_field_whitelist(self):
        msg = self.store.apply("u1", "password", "set", "x")
        self.assertIn("无效字段", msg)
        self.assertEqual(self.store.get("u1"), {})

    def test_notes_limit(self):
        for i in range(15):
            self.store.apply("u1", "notes", "append", f"note-{i}")
        notes = self.store.get("u1")["notes"]
        self.assertEqual(len(notes), 10)
        self.assertEqual(notes[-1], "note-14")

    def test_render_for_prompt(self):
        self.assertEqual(self.store.render_for_prompt("u1"), "")
        self.store.apply("u1", "nickname", "set", "小明")
        self.store.apply("u1", "hobbies", "append", "钓鱼")
        text = self.store.render_for_prompt("u1")
        self.assertIn("称呼偏好：小明", text)
        self.assertIn("爱好：钓鱼", text)
        self.assertNotIn("职业", text)

    def test_isolation_between_users(self):
        self.store.apply("u1", "nickname", "set", "小明")
        self.assertEqual(self.store.get("u2"), {})


class TestTopicStore(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.store = TopicStore(self.db)

    def test_add_recent_prune(self):
        import time
        now = time.time()
        for i in range(8):
            self.store.add("scope_a", f"topic-{i}", ts=now - i)
        self.store.add("scope_b", "other", ts=now)
        recent = self.store.recent("scope_a", limit=5)
        self.assertEqual(recent, [f"topic-{i}" for i in range(5)])
        # prune anything older than 1 day: nothing yet
        self.assertEqual(self.store.prune(1), 0)
        self.store.add("scope_a", "ancient", ts=now - 100 * 86400)
        self.assertEqual(self.store.prune(90), 1)
        self.assertEqual(self.store.prune(0), 0)  # disabled


if __name__ == "__main__":
    unittest.main()
