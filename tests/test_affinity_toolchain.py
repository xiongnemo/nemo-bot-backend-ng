import os
import unittest

from store.database import Database
from store.state_store import StateStore


class TestAffinityToolChain(unittest.TestCase):
    """End-to-end: registry -> executor dispatch -> store mutation, exactly
    as the agent runner invokes tools. Guards against silently broken wiring."""

    def setUp(self):
        self.path = "data/test_toolchain.sqlite"
        self._cleanup()
        self.db = Database(self.path)
        self.ss = StateStore(self.db)
        self.ss.set_plugin_config("affinity", {"crit_chance": 0.0})

        from store.affinity_store import AffinityStore
        from store.profile_store import ProfileStore
        from store.message_store import MessageStore
        from runtime import context
        self._saved = {k: getattr(context, k, None) for k in
                       ("db", "state_store", "affinity_store", "profile_store")}
        context.db = self.db
        context.state_store = self.ss
        context.profile_store = ProfileStore(self.ss)
        context.affinity_store = AffinityStore(self.ss, profile_store=context.profile_store)

        from agent.tool_registry import ToolRegistry
        from agent.builtin_tools import register_builtin_tools
        from agent.superuser_tools import register_superuser_tools
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry, MessageStore(self.db), self.ss, None)
        register_superuser_tools(self.registry, self.ss)

        from agent.tool_executor import ToolExecutor
        self.tool_executor = ToolExecutor(self.registry, None, self.ss, None, None)

        from core.message import Message
        self.msg = Message({"frontend": "onebot",
                            "context": {"group_id": "G1", "group_name": "g", "user_id": "U1",
                                        "user_name": "小明", "message_id": "1", "self_id": "9", "ated": True},
                            "request": {"command": "", "args": "", "imgs": [], "raw_message": ""}})

    def tearDown(self):
        from runtime import context
        for k, v in self._saved.items():
            setattr(context, k, v)
        self._cleanup()

    def _cleanup(self):
        for ext in ["", "-shm", "-wal"]:
            p = self.path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_all_affinity_tools_visible_to_llm(self):
        names = [t.name for t in self.registry.get_tools_for_user("onebot", "U1")]
        for tool in ("query_affinity", "query_affinity_history", "adjust_affinity", "gift_affinity"):
            self.assertIn(tool, names, f"{tool} 未注册进 LLM 可见工具表")
        self.assertNotIn("admin_affinity", names)  # non-superuser

    def test_adjust_really_mutates_store_via_executor(self):
        from runtime import context
        before = context.affinity_store.get_state("U1")["score"]
        obs = self.tool_executor.execute("adjust_affinity", {"delta": 4, "reason": "集成测试"}, self.msg)
        self.assertIn("result", obs, f"executor 返回异常: {obs}")
        after = context.affinity_store.get_state("U1")["score"]
        self.assertEqual(after - before, 4.0)  # 真实写入
        # 且流水可审计
        hist = context.affinity_store.get_state("U1")["history"]
        self.assertTrue(any(h["reason"] == "集成测试" and h["source"] == "llm" for h in hist))

    def test_query_returns_live_value_via_executor(self):
        from runtime import context
        context.affinity_store.adjust("U1", 3, "seed", source="system")
        obs = self.tool_executor.execute("query_affinity", {}, self.msg)
        self.assertEqual(obs["result"]["score"], 3.0)

    def test_gift_via_executor(self):
        from runtime import context
        context.affinity_store.adjust("U1", 30, "seed", source="system")
        obs = self.tool_executor.execute("gift_affinity", {"target_user_id": "U2"}, self.msg)
        self.assertIn("赠礼成功", obs["result"])
        self.assertEqual(context.affinity_store.get_state("U2")["score"], 2.0)

    def test_admin_tool_blocked_for_normal_user(self):
        obs = self.tool_executor.execute("admin_affinity", {"action": "reset", "user_id": "U2"}, self.msg)
        self.assertIn("error", obs)
        self.assertIn("superuser", obs["error"])

    def test_unknown_tool(self):
        obs = self.tool_executor.execute("no_such_tool", {}, self.msg)
        self.assertIn("error", obs)


class TestAffinityClaimGuard(unittest.TestCase):
    """The runner must detect verbal affinity claims without real tool calls."""

    def test_claim_without_call_detected(self):
        from agent.runner import affinity_claim_without_call
        self.assertTrue(affinity_claim_without_call("太暖了，好感度+5！", ["think", "weather"]))
        self.assertTrue(affinity_claim_without_call("哼，好感度 -3", []))
        self.assertTrue(affinity_claim_without_call("给你好感度加了2分哦", ["query_affinity"]))

    def test_claim_with_real_call_passes(self):
        from agent.runner import affinity_claim_without_call
        self.assertFalse(affinity_claim_without_call("好感度+5！现在是 15 分啦", ["adjust_affinity"]))
        self.assertFalse(affinity_claim_without_call("送礼成功，对方好感度+2", ["gift_affinity"]))

    def test_no_claim_no_trigger(self):
        from agent.runner import affinity_claim_without_call
        self.assertFalse(affinity_claim_without_call("今天天气不错", []))
        self.assertFalse(affinity_claim_without_call("你的好感度是 15 分", []))  # 报数不是加减分声明


if __name__ == "__main__":
    unittest.main()
