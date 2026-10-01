import os
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from core.recording_message import RecordingMessage
from plugins.tradingview import (
    resolve_symbol,
    normalize_interval,
    format_smart_number,
    compute_indicators,
    draw_single_tv_chart,
    draw_grid_tv_chart,
    bot_execute,
    STATIC_SYMBOL_ALIASES
)


def create_mock_tv_df(length: int = 150, base_price: float = 2.8e12) -> pd.DataFrame:
    """Generate a mock OHLCV dataframe for TradingView index testing."""
    times = pd.to_datetime([1788200000 + i * 3600 for i in range(length)], unit='s')
    closes = [base_price + i * 1e9 + np.sin(i / 5.0) * 1e10 for i in range(length)]
    opens = [c - 5e8 for c in closes]
    highs = [max(o, c) + 1e9 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 1e9 for o, c in zip(opens, closes)]
    vols = [1e11 + i * 1e9 for i in range(length)]

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": vols
    }, index=times)
    return df


def make_test_msg(command: str, args: str, is_agent: bool = False) -> RecordingMessage:
    msg_dict = {
        "frontend": "onebot",
        "context": {
            "group_id": "123456",
            "user_id": "789",
            "user_name": "trader",
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
            "is_agent": is_agent,
            "files": []
        }
    }
    return RecordingMessage(msg_dict)


class TestTradingViewPlugin(unittest.TestCase):

    def test_symbol_resolution(self):
        self.assertEqual(resolve_symbol("TOTAL"), "CRYPTOCAP:TOTAL")
        self.assertEqual(resolve_symbol("total"), "CRYPTOCAP:TOTAL")
        self.assertEqual(resolve_symbol("TOTAL2"), "CRYPTOCAP:TOTAL2")
        self.assertEqual(resolve_symbol("TOTAL3"), "CRYPTOCAP:TOTAL3")
        self.assertEqual(resolve_symbol("BTC.D"), "CRYPTOCAP:BTC.D")
        self.assertEqual(resolve_symbol("USDT.D"), "CRYPTOCAP:USDT.D")
        self.assertEqual(resolve_symbol("ETH.D"), "CRYPTOCAP:ETH.D")
        self.assertEqual(resolve_symbol("OTHERS"), "CRYPTOCAP:OTHERS")
        self.assertEqual(resolve_symbol("SPX"), "SP:SPX")
        self.assertEqual(resolve_symbol("标普500"), "SP:SPX")
        self.assertEqual(resolve_symbol("GOLD"), "TVC:GOLD")
        self.assertEqual(resolve_symbol("BINANCE:BTCUSDT"), "BINANCE:BTCUSDT")
        self.assertEqual(resolve_symbol("SOLUSDT"), "BINANCE:SOLUSDT")

    def test_interval_normalization(self):
        self.assertEqual(normalize_interval("1m"), "1")
        self.assertEqual(normalize_interval("15m"), "15")
        self.assertEqual(normalize_interval("1h"), "60")
        self.assertEqual(normalize_interval("4h"), "240")
        self.assertEqual(normalize_interval("1d"), "1D")
        self.assertEqual(normalize_interval("1w"), "1W")
        self.assertEqual(normalize_interval("日线"), "1D")

    def test_format_smart_number(self):
        self.assertEqual(format_smart_number(2.831e12), "$2.831 T")
        self.assertEqual(format_smart_number(1.5e9), "$1.500 B")
        self.assertEqual(format_smart_number(50.25, is_percentage=True), "50.25%")
        self.assertEqual(format_smart_number(7650.5), "$7,650.50")

    def test_compute_indicators(self):
        df = create_mock_tv_df(length=180, base_price=2.8e12)
        info = compute_indicators(df)
        self.assertIn("tunnel_top", info)
        self.assertIn("tunnel_bot", info)
        self.assertIn("status", info)
        self.assertIn("rsi", info)
        self.assertIn("macd", info)
        self.assertGreater(info["tunnel_top"], 0)
        self.assertGreater(info["tunnel_bot"], 0)

    @patch("plugins.tradingview.tv_client.fetch_quote")
    def test_bot_execute_quote_mode(self, mock_quote):
        mock_quote.return_value = {
            "symbol": "CRYPTOCAP:TOTAL",
            "price": 2.83e12,
            "change": -5e9,
            "change_pct": -0.25,
            "description": "Crypto Total Market Cap, $",
            "exchange": "CRYPTOCAP"
        }
        msg = make_test_msg("tv", "quote TOTAL")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("CRYPTOCAP:TOTAL", msg.outbox[0].text)
        self.assertIn("$2.830 T", msg.outbox[0].text)

    @patch("plugins.tradingview.search_tradingview_symbol")
    def test_bot_execute_search_mode(self, mock_search):
        mock_search.return_value = "CRYPTOCAP:TOTAL"
        msg = make_test_msg("tv", "search TOTAL")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("CRYPTOCAP:TOTAL", msg.outbox[0].text)

    @patch("plugins.tradingview.tv_client.fetch_quote")
    @patch("plugins.tradingview.tv_client.fetch_klines")
    def test_bot_execute_chart_mode(self, mock_klines, mock_quote):
        mock_quote.return_value = {
            "symbol": "CRYPTOCAP:TOTAL",
            "price": 2.83e12,
            "change": -5e9,
            "change_pct": -0.25,
            "description": "Crypto Total Market Cap, $",
            "exchange": "CRYPTOCAP"
        }
        mock_klines.return_value = create_mock_tv_df(length=180, base_price=2.8e12)

        msg = make_test_msg("tv", "TOTAL 1d")
        bot_execute(msg, {})

        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("Vegas 隧道与关键位", msg.outbox[0].text)
        self.assertIsNotNone(msg.payload)
        self.assertEqual(msg.payload["symbol"], "CRYPTOCAP:TOTAL")


if __name__ == "__main__":
    unittest.main()
