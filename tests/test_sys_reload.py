import unittest
from unittest.mock import patch, MagicMock

from core.recording_message import RecordingMessage
from runtime import context
from routing.ruleset import Ruleset
from agent.tool_registry import ToolRegistry
from store.persona_store import PersonaStore
from plugins.sys_reload import bot_execute


def make_test_msg(command: str, args: str, user_id: str = "superuser_1", frontend: str = "onebot") -> RecordingMessage:
    msg_dict = {
        "frontend": frontend,
        "context": {
            "group_id": "123456",
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


class TestSysReloadPlugin(unittest.TestCase):

    def setUp(self):
        self.mock_ruleset = MagicMock(spec=Ruleset)
        self.mock_ruleset.reload.return_value = 219

        self.mock_tool_registry = MagicMock(spec=ToolRegistry)
        self.mock_tool_registry.reload_plugins.return_value = 41

        self.mock_persona_store = MagicMock(spec=PersonaStore)
        self.mock_persona_store.reload.return_value = 8

        context.ruleset = self.mock_ruleset
        context.tool_registry = self.mock_tool_registry
        context.persona_store = self.mock_persona_store

    @patch("plugins.sys_reload.is_superuser")
    def test_permission_denied(self, mock_su):
        mock_su.return_value = False
        msg = make_test_msg("reload", "all", user_id="normal_user")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("403: nemo: 权限拒绝", msg.outbox[0].text)
        self.mock_ruleset.reload.assert_not_called()

    @patch("plugins.sys_reload.is_superuser")
    def test_reload_all(self, mock_su):
        mock_su.return_value = True
        msg = make_test_msg("reload", "")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("Nemo-bot 统一热重载完成", reply)
        self.assertIn("219 条路由规则", reply)
        self.assertIn("41 个插件工具", reply)
        self.assertIn("8 个角色文件", reply)
        self.mock_ruleset.reload.assert_called_once()
        self.mock_tool_registry.reload_plugins.assert_called_once()
        self.mock_persona_store.reload.assert_called_once()

    @patch("plugins.sys_reload.is_superuser")
    def test_reload_plugins_only(self, mock_su):
        mock_su.return_value = True
        msg = make_test_msg("reload", "plugins")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("路由规则", reply)
        self.assertIn("工具池", reply)
        self.mock_ruleset.reload.assert_called_once()
        self.mock_tool_registry.reload_plugins.assert_called_once()
        self.mock_persona_store.reload.assert_not_called()

    @patch("plugins.sys_reload.is_superuser")
    def test_reload_persona_only(self, mock_su):
        mock_su.return_value = True
        msg = make_test_msg("reload", "persona")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("人格角色库", reply)
        self.mock_ruleset.reload.assert_not_called()
        self.mock_tool_registry.reload_plugins.assert_not_called()
        self.mock_persona_store.reload.assert_called_once()

    def test_get_loaded_plugins_caching(self):
        from plugins import get_loaded_plugins
        plugins_1 = get_loaded_plugins()
        self.assertIn("tradingview", plugins_1)
        self.assertIn("sys_reload", plugins_1)
        plugins_2 = get_loaded_plugins()
        self.assertIs(plugins_1, plugins_2)

    def test_missing_module_warning_format(self):
        import plugins
        with patch("plugins.logger.error") as mock_log_err, \
             patch("plugins.importlib.reload") as mock_reload, \
             patch("plugins.importlib.import_module") as mock_import:
            err = ModuleNotFoundError("No module named 'fake_dependency'")
            err.name = "fake_dependency"
            mock_import.side_effect = err
            mock_reload.side_effect = err

            plugins.get_loaded_plugins(reload=True)

            self.assertGreater(mock_log_err.call_count, 0)
            format_found = any(
                "插件似乎缺少" in str(call_args) and "fake_dependency" in str(call_args)
                for call_args in mock_log_err.call_args_list
            )
            self.assertTrue(format_found, "Expected log message formatted with '!!!!!! xxx 插件似乎缺少 yyy module !!!!!!'")


if __name__ == "__main__":
    unittest.main()
