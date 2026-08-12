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


class TestAffinityStoreV2(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.store = AffinityStore(self.state_store)

    def test_fresh_start_from_zero(self):
        # v1 data present under the old key must be ignored
        self.state_store.set("affinity", "user_u1", "state", {"score": 88.0})
        st = self.store.get_state("u1", now=T0)
        self.assertEqual(st["score"], 0.0)
        self.assertEqual(st["level"], "陌生")
        self.assertEqual(st["lv"], 1)

    def test_daily_first_and_chat_gain(self):
        g = self.store.record_message("u1", engaged=True, now=T0)
        # 每日初见 +2, chat +1 (day 1: streak=1, no streak bonus)
        self.assertEqual(g, 3.0)
        st = self.store.get_state("u1", now=T0 + 1)
        self.assertEqual(st["score"], 3.0)
        notes = [e["note"] for e in st["daily"]["events"]]
        self.assertIn("每日初见", notes)

    def test_streak_bonus_and_break(self):
        self.store.record_message("u1", engaged=True, now=T0)
        self.store.record_message("u1", engaged=True, now=T0 + DAY)
        g3 = self.store.record_message("u1", engaged=True, now=T0 + 2 * DAY)
        # day3: 初见2 + streak 0.5*2=1 + chat 1 = 4
        self.assertEqual(g3, 4.0)
        st = self.store.get_state("u1", now=T0 + 2 * DAY + 1)
        self.assertEqual(st["streak"]["days"], 3)
        # break the streak (skip 2 days) -> resets to 1, no streak bonus
        g = self.store.record_message("u1", engaged=True, now=T0 + 5 * DAY)
        self.assertEqual(g, 3.0)  # 初见2 + chat1
        st = self.store.get_state("u1", now=T0 + 5 * DAY + 1)
        self.assertEqual(st["streak"]["days"], 1)

    def test_streak_bonus_capped(self):
        now = T0
        for i in range(10):
            self.store.record_message("u1", engaged=False, now=now + i * DAY)
        st = self.store.get_state("u1", now=now + 9 * DAY + 1)
        self.assertEqual(st["streak"]["days"], 10)
        streak_events = [e for e in st["daily"]["events"] if e["k"] == "streak"]
        # capped at streak_step * streak_max_steps = 0.5 * 6 = 3
        self.assertEqual(streak_events[0]["pts"], 3.0)

    def test_milestone_once_ever(self):
        state = self.store._load("u1", T0)
        state["total_interactions"] = 99
        self.store._save("u1", state)
        g = self.store.record_message("u1", engaged=True, now=T0)
        # crosses 100: 初见2 + milestone5 + chat1
        self.assertEqual(g, 8.0)
        g2 = self.store.record_message("u1", engaged=True, now=T0 + 61)
        self.assertEqual(g2, 1.0)  # milestone not granted twice
        st = self.store.get_state("u1", now=T0 + 62)
        self.assertIn("milestone:100", st["granted"])

    def test_cooldown_and_daily_chat_cap(self):
        self.store.record_message("u1", engaged=True, now=T0)
        g = self.store.record_message("u1", engaged=True, now=T0 + 10)  # within cooldown
        self.assertEqual(g, 0.0)
        for i in range(12):
            self.store.record_message("u1", engaged=True, now=T0 + 61 + i * 61)
        st = self.store.get_state("u1", now=T0 + 61 + 13 * 61)
        self.assertAlmostEqual(st["daily"]["chat_gain"], 10.0, places=3)  # capped

    def test_grace_then_decay_with_floor(self):
        self.store.adjust("u1", 60, "test", source="system", now=T0)  # score 60, peak 60 (朋友)
        st = self.store.get_state("u1", now=T0 + 2 * DAY)
        self.assertAlmostEqual(st["score"], 60.0, places=2)  # within grace: no decay
        # grace(3d) + one half-life(45d): 60 * 0.5 = 30, above floor 21
        st2 = self.store.get_state("u1", now=T0 + 48 * DAY)
        self.assertAlmostEqual(st2["score"], 30.0, places=1)
        # very long idle: floor 21 protects (曾达朋友)
        st3 = self.store.get_state("u1", now=T0 + 500 * DAY)
        self.assertAlmostEqual(st3["score"], 21.0, places=1)

    def test_no_floor_without_milestone(self):
        self.store.adjust("u1", 40, "test", source="system", now=T0)  # peak 40 < 51
        st = self.store.get_state("u1", now=T0 + 500 * DAY)
        self.assertLess(st["score"], 1.0)  # decays toward 0

    def test_llm_adjust_caps(self):
        r = self.store.adjust("u1", 8, "sweet", source="llm", now=T0)
        self.assertEqual(r["applied_delta"], 5.0)
        r2 = self.store.adjust("u1", 5, "again", source="llm", now=T0 + 1)
        self.assertEqual(r2["applied_delta"], 5.0)
        r3 = self.store.adjust("u1", 5, "over", source="llm", now=T0 + 2)
        self.assertEqual(r3["applied_delta"], 0.0)  # daily net ±10 reached

    def test_profile_share_once_ever(self):
        self.assertEqual(self.store.grant_profile_share("u1", "birthday", now=T0), 5.0)
        self.assertEqual(self.store.grant_profile_share("u1", "birthday", now=T0 + DAY), 0.0)
        self.assertEqual(self.store.grant_profile_share("u1", "hobbies", now=T0), 5.0)

    def test_birthday_surprise(self):
        profile = ProfileStore(self.state_store)
        store = AffinityStore(self.state_store, profile_store=profile)
        import datetime
        d = datetime.datetime.fromtimestamp(T0)
        profile.apply("u1", "birthday", "set", f"{d.month}月{d.day}日")
        g = store.record_message("u1", engaged=True, now=T0)
        self.assertEqual(g, 13.0)  # 初见2 + 生日10 + chat1
        st = store.get_state("u1", now=T0 + 1)
        self.assertIn("生日快乐！🎂", [e["note"] for e in st["daily"]["events"]])
        g2 = store.record_message("u2", engaged=True, now=T0 + 40 * DAY)
        self.assertEqual(g2, 3.0)  # non-birthday user unaffected

    def test_daily_event_cap(self):
        self.state_store.set_plugin_config("affinity", {"daily_event_cap": 3.0})
        self.store.record_message("u1", engaged=True, now=T0)
        st = self.store.get_state("u1", now=T0 + 1)
        self.assertLessEqual(st["daily"]["event_gain"], 3.0)

    def test_levels_and_next_level(self):
        self.assertEqual(AffinityStore.get_level(-5)[0], "反感")
        self.assertEqual(AffinityStore.get_level(0)[0], "陌生")
        self.assertEqual(AffinityStore.get_level(21)[0], "熟悉")
        self.assertEqual(AffinityStore.get_level(51)[0], "朋友")
        self.assertEqual(AffinityStore.get_level(81)[0], "挚友")
        name, need = AffinityStore.next_level_info(32.5)
        self.assertEqual(name, "朋友")
        self.assertEqual(need, 18.5)
        self.assertIsNone(AffinityStore.next_level_info(95))

    def test_score_bounds(self):
        self.store.adjust("u1", 500, "huge", source="system", now=T0)
        self.assertEqual(self.store.get_state("u1", now=T0)["score"], 100.0)
        self.store.adjust("u1", -500, "awful", source="system", now=T0 + 1)
        self.assertEqual(self.store.get_state("u1", now=T0 + 1)["score"], -20.0)

    def test_get_state_is_readonly(self):
        self.store.adjust("u1", 60, "t", source="system", now=T0)
        self.store.get_state("u1", now=T0 + 100 * DAY)
        raw = self.state_store.get("affinity", "user_u1", "state_v2")
        self.assertAlmostEqual(raw["score"], 60.0, places=2)  # reads never persist


class TestAffinityCard(StoreTestBase):
    def test_render_card(self):
        from plugins.affinity import render_card
        store = AffinityStore(self.state_store)
        store.record_message("u1", engaged=True, now=T0)
        store.adjust("u1", 50, "boost", source="system", now=T0)  # so the bar has filled blocks
        st = store.get_state("u1", now=T0 + 1)
        card = render_card("小明", st)
        self.assertIn("┏━", card)
        self.assertIn("┗━", card)
        self.assertIn("⬛", card)
        self.assertIn("Lv.3", card)
        self.assertIn("每日初见", card)
        self.assertIn("聊天互动 +1.0", card)


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
        self.assertEqual(self.store.prune(1), 0)
        self.store.add("scope_a", "ancient", ts=now - 100 * 86400)
        self.assertEqual(self.store.prune(90), 1)
        self.assertEqual(self.store.prune(0), 0)


if __name__ == "__main__":
    unittest.main()
