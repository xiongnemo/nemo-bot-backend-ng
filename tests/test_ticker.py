import unittest
from unittest.mock import patch, MagicMock
from plugins.ticker import parse_args, bot_execute
from core.recording_message import RecordingMessage


class TestTickerPlugin(unittest.TestCase):
    def test_parse_args_defaults(self):
        base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args("BTC")
        self.assertEqual(base, "BTC")
        self.assertIsNone(quote)
        self.assertEqual(exchange, "binance")
        self.assertIsNone(market)
        self.assertFalse(explicit_exchange)
        self.assertFalse(query_all)

    def test_parse_args_all_flags(self):
        for flag in ["-a", "-A", "--all", "--ALL", "all", "ALL", "全", "全网", "全平台"]:
            base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args(f"BTC {flag}")
            self.assertEqual(base, "BTC")
            self.assertFalse(explicit_exchange)
            self.assertTrue(query_all, f"Flag {flag} should trigger query_all")

        # Leading flag
        base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args("-a ETH")
        self.assertEqual(base, "ETH")
        self.assertTrue(query_all)

    def test_parse_args_explicit_exchange(self):
        base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args("BTC okx")
        self.assertEqual(base, "BTC")
        self.assertEqual(exchange, "okx")
        self.assertTrue(explicit_exchange)
        self.assertFalse(query_all)

        base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args("ETH hl spot")
        self.assertEqual(base, "ETH")
        self.assertEqual(exchange, "hyperliquid")
        self.assertEqual(market, "spot")
        self.assertTrue(explicit_exchange)
        self.assertFalse(query_all)

    def test_parse_args_pairs(self):
        base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args("ETH/BTC")
        self.assertEqual(base, "ETH")
        self.assertEqual(quote, "BTC")
        self.assertEqual(symbol_raw, "ETH/BTC")

    @patch("plugins.ticker.fetch_binance")
    @patch("plugins.ticker.fetch_gate")
    @patch("plugins.ticker.fetch_okx")
    @patch("plugins.ticker.fetch_hyperliquid")
    def test_bot_execute_human_default(self, mock_hl, mock_okx, mock_gate, mock_bn):
        mock_bn.return_value = "[BINANCE] BTC 65000"
        
        payload = {
            "frontend": "onebot",
            "context": {"group_id": "100", "user_id": "200"},
            "request": {"command": "coin", "args": "BTC", "is_agent": False}
        }
        msg = RecordingMessage(payload)
        bot_execute(msg, {})
        
        self.assertTrue(mock_bn.called)
        self.assertFalse(mock_gate.called)
        self.assertFalse(mock_okx.called)
        self.assertFalse(mock_hl.called)
        self.assertEqual(len(msg.outbox), 1)
        self.assertIn("[BINANCE] BTC 65000", msg.outbox[0].text)

    @patch("plugins.ticker.fetch_binance")
    @patch("plugins.ticker.fetch_gate")
    @patch("plugins.ticker.fetch_okx")
    @patch("plugins.ticker.fetch_hyperliquid")
    def test_bot_execute_human_flag_all(self, mock_hl, mock_okx, mock_gate, mock_bn):
        mock_bn.return_value = "[BINANCE] BTC"
        mock_gate.return_value = "[GATE] BTC"
        mock_okx.return_value = "[OKX] BTC"
        mock_hl.return_value = "[HL] BTC"
        
        payload = {
            "frontend": "onebot",
            "context": {"group_id": "100", "user_id": "200"},
            "request": {"command": "coin", "args": "BTC -a", "is_agent": False}
        }
        msg = RecordingMessage(payload)
        bot_execute(msg, {})
        
        self.assertTrue(mock_bn.called)
        self.assertTrue(mock_gate.called)
        self.assertTrue(mock_okx.called)
        self.assertTrue(mock_hl.called)
        self.assertEqual(len(msg.outbox), 1)
        self.assertIn("[GATE] BTC", msg.outbox[0].text)
        self.assertIn("[BINANCE] BTC", msg.outbox[0].text)

    @patch("plugins.ticker.fetch_binance")
    @patch("plugins.ticker.fetch_gate")
    @patch("plugins.ticker.fetch_okx")
    @patch("plugins.ticker.fetch_hyperliquid")
    def test_bot_execute_agent_auto_all(self, mock_hl, mock_okx, mock_gate, mock_bn):
        mock_bn.return_value = "[BINANCE] BTC"
        mock_gate.return_value = "[GATE] BTC"
        mock_okx.return_value = "[OKX] BTC"
        mock_hl.return_value = "[HL] BTC"
        
        # When invoked by agent without -a flag, it should still query all exchanges
        payload = {
            "frontend": "onebot",
            "context": {"group_id": "100", "user_id": "200"},
            "request": {"command": "coin", "args": "BTC", "is_agent": True}
        }
        msg = RecordingMessage(payload)
        bot_execute(msg, {})
        
        self.assertTrue(mock_bn.called)
        self.assertTrue(mock_gate.called)
        self.assertTrue(mock_okx.called)
        self.assertTrue(mock_hl.called)
        self.assertEqual(len(msg.outbox), 1)
        self.assertIn("[GATE] BTC", msg.outbox[0].text)
        self.assertIn("[BINANCE] BTC", msg.outbox[0].text)

    @patch("plugins.ticker.fetch_binance")
    @patch("plugins.ticker.fetch_gate")
    @patch("plugins.ticker.fetch_okx")
    @patch("plugins.ticker.fetch_hyperliquid")
    def test_bot_execute_human_fallback_gate(self, mock_hl, mock_okx, mock_gate, mock_bn):
        # Binance has no data for MSFT token, but Gate has it
        mock_bn.return_value = None
        mock_gate.return_value = "[GATE TradFi] MSFT 450.0"
        
        payload = {
            "frontend": "onebot",
            "context": {"group_id": "100", "user_id": "200"},
            "request": {"command": "coin", "args": "MSFT", "is_agent": False}
        }
        msg = RecordingMessage(payload)
        bot_execute(msg, {})
        
        self.assertTrue(mock_bn.called)
        self.assertTrue(mock_gate.called)
        self.assertEqual(len(msg.outbox), 1)
        self.assertIn("[GATE TradFi] MSFT 450.0", msg.outbox[0].text)
        self.assertIn("Binance 未收录该标的，已自动为你展示 GATE 行情", msg.outbox[0].text)


if __name__ == "__main__":
    unittest.main()
