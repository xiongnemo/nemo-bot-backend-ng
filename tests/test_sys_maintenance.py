import unittest
from unittest.mock import patch, MagicMock

from core.recording_message import RecordingMessage
from runtime import context
from store.system_control import SystemControl, DEFAULT_MAINTENANCE_REASON
from plugins.sys_maintenance import bot_execute


class MockStateStore:
    def __init__(self):
        self._data = {}

    def get(self, namespace: str, scope: str, key: str, default=None):
        return self._data.get((namespace, scope, key), default)

    def set(self, namespace: str, scope: str, key: str, value):
        self._data[(namespace, scope, key)] = value


def make_test_msg(command: str, args: str, user_id: str = "superuser_1", frontend: str = "onebot", group_id: str = "123456") -> RecordingMessage:
    msg_dict = {
        "frontend": frontend,
        "context": {
            "group_id": group_id,
            "user_id": user_id,
            "user_name": "admin",
            "message_id": "m1",
            "self_id": "bot",
            "ated": False,
            "frontend_system_info": {}
        },
        "request": {
            "command": command,
            "args": args,
            "imgs": [],
            "raw_message": f"{command} {args}".strip(),
            "reply_to": None,
            "message_id": "m1",
            "is_agent": False,
            "files": []
        }
    }
    return RecordingMessage(msg_dict)


class TestSystemControl(unittest.TestCase):
    def setUp(self):
        self.state_store = MockStateStore()
        self.sys_ctrl = SystemControl(self.state_store)

    def test_default_status(self):
        self.assertTrue(self.sys_ctrl.is_master_agent_enabled())
        self.assertTrue(self.sys_ctrl.is_agent_chat_enabled())
        self.assertTrue(self.sys_ctrl.is_tagging_enabled())
        self.assertTrue(self.sys_ctrl.is_jobs_enabled())
        self.assertEqual(self.sys_ctrl.get_maintenance_reason(), DEFAULT_MAINTENANCE_REASON)
        self.assertEqual(self.sys_ctrl.get_whitelist_groups(), [])

    def test_set_maintenance_mode(self):
        custom_reason = "系统升级中，预计2小时后恢复"
        self.sys_ctrl.set_maintenance_mode(True, reason=custom_reason)

        self.assertFalse(self.sys_ctrl.is_master_agent_enabled())
        self.assertFalse(self.sys_ctrl.is_agent_chat_enabled())
        self.assertFalse(self.sys_ctrl.is_tagging_enabled())
        self.assertFalse(self.sys_ctrl.is_jobs_enabled())
        self.assertEqual(self.sys_ctrl.get_maintenance_reason(), custom_reason)

        # Disable maintenance mode -> restores all
        self.sys_ctrl.set_maintenance_mode(False)
        self.assertTrue(self.sys_ctrl.is_master_agent_enabled())
        self.assertTrue(self.sys_ctrl.is_agent_chat_enabled())
        self.assertTrue(self.sys_ctrl.is_tagging_enabled())
        self.assertTrue(self.sys_ctrl.is_jobs_enabled())
        # Reason is preserved
        self.assertEqual(self.sys_ctrl.get_maintenance_reason(), custom_reason)

    def test_granular_switches(self):
        # Disable only tagging
        self.sys_ctrl.set_component_switch("tagging", False)
        self.assertTrue(self.sys_ctrl.is_master_agent_enabled())
        self.assertTrue(self.sys_ctrl.is_agent_chat_enabled())
        self.assertFalse(self.sys_ctrl.is_tagging_enabled())
        self.assertTrue(self.sys_ctrl.is_jobs_enabled())

        # Disable chat
        self.sys_ctrl.set_component_switch("chat", False)
        self.assertFalse(self.sys_ctrl.is_agent_chat_enabled())

        # Disable jobs
        self.sys_ctrl.set_component_switch("jobs", False)
        self.assertFalse(self.sys_ctrl.is_jobs_enabled())

        # Re-enable chat
        self.sys_ctrl.set_component_switch("chat", True)
        self.assertTrue(self.sys_ctrl.is_agent_chat_enabled())

    def test_whitelist_management(self):
        self.assertFalse(self.sys_ctrl.is_group_whitelisted("903421726"))
        self.sys_ctrl.add_whitelist_group("903421726")
        self.assertTrue(self.sys_ctrl.is_group_whitelisted("903421726"))
        self.assertEqual(self.sys_ctrl.get_whitelist_groups(), ["903421726"])

        # Duplicate addition handled cleanly
        self.sys_ctrl.add_whitelist_group("903421726")
        self.assertEqual(self.sys_ctrl.get_whitelist_groups(), ["903421726"])

        # Add second group
        self.sys_ctrl.add_whitelist_group(123456)
        self.assertTrue(self.sys_ctrl.is_group_whitelisted("123456"))
        self.assertEqual(self.sys_ctrl.get_whitelist_groups(), ["903421726", "123456"])

        # Remove group
        self.sys_ctrl.remove_whitelist_group("903421726")
        self.assertFalse(self.sys_ctrl.is_group_whitelisted("903421726"))
        self.assertTrue(self.sys_ctrl.is_group_whitelisted("123456"))

        # Clear whitelist
        self.sys_ctrl.clear_whitelist_groups()
        self.assertEqual(self.sys_ctrl.get_whitelist_groups(), [])


class TestSysMaintenancePlugin(unittest.TestCase):
    def setUp(self):
        self.state_store = MockStateStore()
        self.sys_ctrl = SystemControl(self.state_store)
        context.system_control = self.sys_ctrl

    @patch("plugins.sys_maintenance.is_superuser")
    def test_permission_denied(self, mock_su):
        mock_su.return_value = False
        msg = make_test_msg("maintenance", "status", user_id="normal_user")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("403: nemo: 权限拒绝", msg.outbox[0].text)

    @patch("plugins.sys_maintenance.is_superuser")
    def test_status_command(self, mock_su):
        mock_su.return_value = True
        msg = make_test_msg("maintenance", "status")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("系统运维与功能开关状态", reply)
        self.assertIn("Agent 总控开关", reply)
        self.assertIn("聊天 Agent", reply)
        self.assertIn("后台图片视觉打标", reply)
        self.assertIn("后台定时任务", reply)

    @patch("plugins.sys_maintenance.is_superuser")
    def test_lazy_initialization_when_context_system_control_is_none(self, mock_su):
        mock_su.return_value = True
        context.system_control = None
        context.state_store = self.state_store
        msg = make_test_msg("maintenance", "status")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("系统运维与功能开关状态", msg.outbox[0].text)
        self.assertIsNotNone(context.system_control)

    @patch("plugins.sys_maintenance.is_superuser")
    def test_maintenance_on_off(self, mock_su):
        mock_su.return_value = True
        # Turn ON with reason
        msg_on = make_test_msg("maintenance", "on nemo 的 infra 将在近日进行维护，暂时下线 agent 功能")
        bot_execute(msg_on, {})
        self.assertIn("系统维护模式已【全面开启】", msg_on.outbox[0].text)
        self.assertIn("nemo 的 infra 将在近日进行维护，暂时下线 agent 功能", msg_on.outbox[0].text)
        self.assertFalse(self.sys_ctrl.is_agent_chat_enabled())
        self.assertFalse(self.sys_ctrl.is_tagging_enabled())
        self.assertFalse(self.sys_ctrl.is_jobs_enabled())

        # Turn OFF
        msg_off = make_test_msg("maintenance", "off")
        bot_execute(msg_off, {})
        self.assertIn("系统维护模式已【解除】", msg_off.outbox[0].text)
        self.assertTrue(self.sys_ctrl.is_agent_chat_enabled())
        self.assertTrue(self.sys_ctrl.is_tagging_enabled())
        self.assertTrue(self.sys_ctrl.is_jobs_enabled())

    @patch("plugins.sys_maintenance.is_superuser")
    def test_switch_granular_commands(self, mock_su):
        mock_su.return_value = True

        # Switch chat off
        msg_chat_off = make_test_msg("switch", "chat off")
        bot_execute(msg_chat_off, {})
        self.assertIn("聊天 Agent 功能已【关闭】", msg_chat_off.outbox[0].text)
        self.assertFalse(self.sys_ctrl.is_agent_chat_enabled())

        # Switch tagging off
        msg_tag_off = make_test_msg("switch", "tagging off")
        bot_execute(msg_tag_off, {})
        self.assertIn("后台图片视觉打标已【关闭】", msg_tag_off.outbox[0].text)
        self.assertFalse(self.sys_ctrl.is_tagging_enabled())

        # Switch jobs off
        msg_jobs_off = make_test_msg("switch", "jobs off")
        bot_execute(msg_jobs_off, {})
        self.assertIn("后台定时任务已【关闭】", msg_jobs_off.outbox[0].text)
        self.assertFalse(self.sys_ctrl.is_jobs_enabled())

        # Switch master off
        msg_all_off = make_test_msg("switch", "master off")
        bot_execute(msg_all_off, {})
        self.assertIn("Agent 总控开关已【关闭】", msg_all_off.outbox[0].text)
        self.assertFalse(self.sys_ctrl.is_master_agent_enabled())

    @patch("plugins.sys_maintenance.is_superuser")
    def test_reason_and_test_and_reset(self, mock_su):
        mock_su.return_value = True

        # Set custom reason
        msg_r = make_test_msg("maintenance", "reason 正在机房搬迁，明日清晨恢复")
        bot_execute(msg_r, {})
        self.assertIn("维护提示理由已更新", msg_r.outbox[0].text)
        self.assertEqual(self.sys_ctrl.get_maintenance_reason(), "正在机房搬迁，明日清晨恢复")

        # Preview test
        msg_t = make_test_msg("maintenance", "test")
        bot_execute(msg_t, {})
        self.assertIn("正在机房搬迁，明日清晨恢复", msg_t.outbox[0].text)

        # Reset to default
        msg_reset = make_test_msg("maintenance", "reset")
        bot_execute(msg_reset, {})
        self.assertIn(DEFAULT_MAINTENANCE_REASON, msg_reset.outbox[0].text)
        self.assertEqual(self.sys_ctrl.get_maintenance_reason(), DEFAULT_MAINTENANCE_REASON)

    @patch("plugins.sys_maintenance.is_superuser")
    def test_whitelist_command(self, mock_su):
        mock_su.return_value = True

        msg_add = make_test_msg("maintenance", "whitelist add 903421726")
        bot_execute(msg_add, {})
        self.assertIn("903421726", msg_add.outbox[0].text)
        self.assertTrue(self.sys_ctrl.is_group_whitelisted("903421726"))

        msg_list = make_test_msg("maintenance", "whitelist list")
        bot_execute(msg_list, {})
        self.assertIn("903421726", msg_list.outbox[0].text)

        msg_del = make_test_msg("maintenance", "whitelist del 903421726")
        bot_execute(msg_del, {})
        self.assertFalse(self.sys_ctrl.is_group_whitelisted("903421726"))


class TestSystemMaintenanceInterception(unittest.TestCase):
    def setUp(self):
        self.state_store = MockStateStore()
        self.sys_ctrl = SystemControl(self.state_store)
        context.system_control = self.sys_ctrl
        context.state_store = self.state_store
        import app
        app.state_store = self.state_store

    def test_vision_tagging_skipped_when_disabled(self):
        from agent.vision_tagger import async_tag_images
        self.sys_ctrl.set_component_switch("tagging", False)

        with patch("agent.vision_tagger._fetch_image_as_base64") as mock_fetch:
            async_tag_images(["http://example.com/test.jpg"], "msg_123", self.state_store)
            mock_fetch.assert_not_called()

    def test_jobs_skipped_when_disabled(self):
        self.sys_ctrl.set_component_switch("jobs", False)

        # 1. user_notification_job
        from scheduler.jobs import user_notification_job
        mock_sender = MagicMock()
        context.sender = mock_sender
        user_notification_job({"frontend": "test"}, "hello", True)
        mock_sender.send_text.assert_not_called()

        # 2. trigger_agent_task
        from agent.builtin_tools import trigger_agent_task
        mock_runner = MagicMock()
        context.agent_runner = mock_runner
        trigger_agent_task("onebot", {"group_id": "123"}, "prompt", "t1")
        mock_runner.run.assert_not_called()

        # 3. run_reflection_job
        from agent.reflection_job import run_reflection_job
        mock_db = MagicMock()
        context.db = mock_db
        run_reflection_job()
        mock_db.get_conn.assert_not_called()

        # 4. run_exploration_job
        from agent.exploration_job import run_exploration_job
        res = run_exploration_job()
        self.assertFalse(res["ok"])
        self.assertIn("disabled by system_control", res["msg"])

    def test_chat_agent_interception_in_handle_ingest(self):
        import app
        from core.types import Action, RouteResult

        self.sys_ctrl.set_component_switch("chat", False)
        self.sys_ctrl.set_maintenance_reason("系统维护中，请稍后再试")

        mock_sender = MagicMock()
        mock_router = MagicMock()
        mock_runner = MagicMock()
        mock_store = MagicMock()
        mock_store.exists.return_value = True

        app.sender = mock_sender
        context.sender = mock_sender
        app.router = mock_router
        context.router = mock_router
        app.agent_runner = mock_runner
        context.agent_runner = mock_runner
        app.msg_store = mock_store
        context.msg_store = mock_store

        # Simulate user explicitly calling agent
        mock_router.route.return_value = RouteResult(mode="agent", query="你好")

        payload = {
            "frontend": "onebot",
            "context": {
                "group_id": "888888",
                "user_id": "111111",
                "user_name": "tester",
                "message_id": "m100",
                "ated": True,
            },
            "request": {
                "args": "@bot 你好",
                "imgs": [],
            }
        }

        # Handle ingest directly
        app._handle_ingest(payload)

        # Agent runner should NOT be called
        mock_runner.run.assert_not_called()

        # Sender should deliver the maintenance reason
        mock_sender.deliver_actions.assert_called_once()
        sent_payload, actions = mock_sender.deliver_actions.call_args[0]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, "reply")
        self.assertEqual(actions[0].text, "系统维护中，请稍后再试")

    def test_whitelisted_group_bypasses_chat_maintenance(self):
        import app
        from core.types import Action, RouteResult

        self.sys_ctrl.set_component_switch("chat", False)
        self.sys_ctrl.add_whitelist_group("888888")

        mock_sender = MagicMock()
        mock_router = MagicMock()
        mock_runner = MagicMock()
        mock_runner.run.return_value = [Action(kind="reply", text="正常回复")]
        mock_store = MagicMock()
        mock_store.exists.return_value = True

        app.sender = mock_sender
        context.sender = mock_sender
        app.router = mock_router
        context.router = mock_router
        app.agent_runner = mock_runner
        context.agent_runner = mock_runner
        app.msg_store = mock_store
        context.msg_store = mock_store

        mock_router.route.return_value = RouteResult(mode="agent", query="你好")

        payload = {
            "frontend": "onebot",
            "context": {
                "group_id": "888888",
                "user_id": "111111",
                "user_name": "tester",
                "message_id": "m101",
                "ated": True,
            },
            "request": {
                "args": "@bot 你好",
                "imgs": [],
            }
        }

        app._handle_ingest(payload)

        # Agent runner SHOULD be called for whitelisted group
        mock_runner.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()

