import os
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np

from core.message import Message
from core.recording_message import RecordingMessage
from plugins.crypto_trend import (
    compute_timeframe_indicators,
    parse_trend_args,
    format_human_compact_text,
    format_agent_detailed_text,
    draw_adaptive_grid_chart,
    bot_execute,
    ALL_INTERVALS,
)


def create_mock_kline_df(length: int = 200, base_price: float = 60000.0, trend: float = 1.0) -> pd.DataFrame:
    """Generate a realistic mock OHLCV dataframe for testing."""
    times = pd.to_datetime([1788200000 + i * 3600 for i in range(length)], unit='s')
    closes = [base_price + i * trend * 50 + np.sin(i / 5.0) * 100 for i in range(length)]
    opens = [c - 20 for c in closes]
    highs = [max(o, c) + 30 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 30 for o, c in zip(opens, closes)]
    vols = [1000 + i * 10 for i in range(length)]

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": vols
    }, index=times)
    return df


class TestCryptoTrend(unittest.TestCase):

    def test_parse_trend_args(self):
        # 1. Empty input
        s, ivs, *_ = parse_trend_args("", is_agent=False)
        self.assertEqual(s, "ETH")
        self.assertEqual(ivs, ["5m"])

        s, ivs, *_ = parse_trend_args("", is_agent=True)
        self.assertEqual(s, "BTC")
        self.assertEqual(ivs, ALL_INTERVALS)

        # 2. Single symbol
        s, ivs, *_ = parse_trend_args("BTC", is_agent=False)
        self.assertEqual(s, "BTC")
        self.assertEqual(ivs, ["5m"])

        s, ivs, *_ = parse_trend_args("BTC", is_agent=True)
        self.assertEqual(s, "BTC")
        self.assertEqual(ivs, ALL_INTERVALS)

        # 3. Full-width punctuation & multiple intervals
        s, ivs, *_ = parse_trend_args("BTC 5m，15m、30m", is_agent=False)
        self.assertEqual(s, "BTC")
        self.assertEqual(ivs, ["5m", "15m", "30m"])

        s, ivs, *_ = parse_trend_args("ETH 15m／1h／4h", is_agent=False)
        self.assertEqual(s, "ETH")
        self.assertEqual(ivs, ["15m", "1h", "4h"])

        # 4. Chinese interval names
        s, ivs, *_ = parse_trend_args("SOL 15分钟，1小时、日线", is_agent=False)
        self.assertEqual(s, "SOL")
        self.assertEqual(ivs, ["15m", "1h", "1d"])

        # 5. All flag
        s, ivs, *_ = parse_trend_args("BTC all", is_agent=False)
        self.assertEqual(s, "BTC")
        self.assertEqual(ivs, ALL_INTERVALS)

    def test_compute_timeframe_indicators(self):
        df = create_mock_kline_df(length=200, base_price=50000.0, trend=1.5)
        info = compute_timeframe_indicators(df)

        self.assertIn("close", info)
        self.assertIn("ema12", info)
        self.assertIn("ema144", info)
        self.assertIn("ema169", info)
        self.assertIn("tunnel_top", info)
        self.assertIn("tunnel_bot", info)
        self.assertIn("status_short", info)
        self.assertIn("key_type", info)
        self.assertIn("dist_pct", info)
        self.assertIn("rsi", info)
        self.assertIn("macd_desc", info)

        self.assertGreater(info["tunnel_top"], 0)
        self.assertGreater(info["tunnel_bot"], 0)
        self.assertGreaterEqual(info["tunnel_top"], info["tunnel_bot"])

    def test_format_human_compact_text(self):
        mock_tf_dict = {}
        for iv in ["5m", "15m", "30m"]:
            df = create_mock_kline_df(length=200, base_price=64000.0)
            info = compute_timeframe_indicators(df)
            mock_tf_dict[iv] = {"df": df, "info": info}

        # Multi-timeframe compact text
        text = format_human_compact_text("BTC", ["5m", "15m", "30m"], mock_tf_dict)
        self.assertIn("【BTC Vegas 隧道关键位】", text)
        self.assertIn("• 5M:", text)
        self.assertIn("• 15M:", text)
        self.assertIn("• 30M:", text)
        # Should be compact (around 4 lines)
        self.assertLessEqual(len(text.splitlines()), 5)

        # Single timeframe compact text
        text_single = format_human_compact_text("ETH", ["5m"], {"5m": mock_tf_dict["5m"]})
        self.assertIn("【ETH (5M) Vegas 隧道】", text_single)
        self.assertLessEqual(len(text_single.splitlines()), 5)

    def test_draw_adaptive_grid_chart_3_panels(self):
        mock_tf_dict = {}
        ivs = ["5m", "15m", "30m"]
        for iv in ivs:
            df = create_mock_kline_df(length=200, base_price=4200.0)
            info = compute_timeframe_indicators(df)
            mock_tf_dict[iv] = {"df": df, "info": info}

        test_out_path = os.path.join("data", "charts", "test_vegas_3panels.png")
        os.makedirs(os.path.dirname(test_out_path), exist_ok=True)
        if os.path.exists(test_out_path):
            os.remove(test_out_path)

        draw_adaptive_grid_chart("PAXG", ivs, mock_tf_dict, test_out_path)

        self.assertTrue(os.path.exists(test_out_path))
        self.assertGreater(os.path.getsize(test_out_path), 30000)

        if os.path.exists(test_out_path):
            os.remove(test_out_path)

    @patch("plugins.crypto_trend.fetch_gate_klines")
    def test_bot_execute_human_custom_list(self, mock_fetch):
        mock_fetch.return_value = create_mock_kline_df(length=200, base_price=65000.0)

        # Human requesting 5m, 15m, 30m with Chinese commas
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
                "command": "vegas",
                "args": "BTC 5m，15m、30m",
                "imgs": [],
                "raw_message": "vegas BTC 5m，15m、30m",
                "reply_to": None,
                "message_id": "m1",
                "is_agent": False,
                "files": []
            }
        }
        rec_msg = RecordingMessage(msg_dict)
        bot_execute(rec_msg, {})

        self.assertEqual(len(rec_msg.outbox), 1)
        action = rec_msg.outbox[0]
        # Human should get compact text
        self.assertIn("【BTC Vegas 隧道关键位】", action.text)
        self.assertLessEqual(len(action.text.splitlines()), 5)
        self.assertTrue(action.photo_url and os.path.exists(action.photo_url))

        # Only 3 intervals should be in levels
        self.assertEqual(len(rec_msg.payload["levels"]), 3)
        self.assertIn("5m", rec_msg.payload["levels"])
        self.assertIn("15m", rec_msg.payload["levels"])
        self.assertIn("30m", rec_msg.payload["levels"])

        if action.photo_url and os.path.exists(action.photo_url):
            try:
                os.remove(action.photo_url)
            except Exception:
                pass

    @patch("plugins.crypto_trend.fetch_gate_klines")
    def test_bot_execute_agent_default_all(self, mock_fetch):
        mock_fetch.return_value = create_mock_kline_df(length=200, base_price=65000.0)

        # Agent call without intervals
        msg_dict = {
            "frontend": "onebot",
            "context": {
                "group_id": "123456",
                "user_id": "789",
                "user_name": "trader",
                "message_id": "m2",
                "self_id": "bot",
                "ated": False,
                "frontend_system_info": {}
            },
            "request": {
                "command": "vegas",
                "args": "BTC",
                "imgs": [],
                "raw_message": "vegas BTC",
                "reply_to": None,
                "message_id": "m2",
                "is_agent": True,
                "files": []
            }
        }
        rec_msg = RecordingMessage(msg_dict)
        bot_execute(rec_msg, {})

        self.assertEqual(len(rec_msg.outbox), 1)
        action = rec_msg.outbox[0]
        # Agent should get full detailed report
        self.assertIn("【BTC Vegas 隧道多级别动态支撑压力分析】", action.text)
        self.assertIn("⚡【超短线级别】", action.text)
        self.assertIn("⚡【日内波段级别】", action.text)
        self.assertIn("⚡【中长趋势级别】", action.text)
        self.assertEqual(len(rec_msg.payload["levels"]), 6)

        if action.photo_url and os.path.exists(action.photo_url):
            try:
                os.remove(action.photo_url)
            except Exception:
                pass

    def test_personalization_settings_flow(self):
        # 1. View settings
        msg_dict = {
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "998877", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置", "is_agent": False}
        }
        rec_msg = RecordingMessage(msg_dict)
        bot_execute(rec_msg, {})
        self.assertEqual(len(rec_msg.outbox), 1)
        self.assertIn("画线个性化看盘配置", rec_msg.outbox[0].text)

        # 2. Set default symbol to PAXG
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "998877", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置 标的 PAXG", "is_agent": False}
        })
        bot_execute(rec_msg, {})
        self.assertIn("已将你的专属默认标的更新为: 【PAXG】", rec_msg.outbox[0].text)

        # 3. Set default intervals to 4h
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "998877", "user_name": "trader"},
            "request": {"command": "画线设置", "args": "周期 4h", "is_agent": False}
        })
        bot_execute(rec_msg, {})
        self.assertIn("已将你的专属默认周期更新为: 【4h】", rec_msg.outbox[0].text)

        # 4. Set hybrid indicators
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "998877", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置 指标 vegas ma200", "is_agent": False}
        })
        bot_execute(rec_msg, {})
        self.assertIn("已将你的专属指标体系更新为", rec_msg.outbox[0].text)
        self.assertIn("MA200", rec_msg.outbox[0].text)

        # 5. Reset
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "998877", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置 重置", "is_agent": False}
        })
        bot_execute(rec_msg, {})
        self.assertIn("已重置你的画线个性化设置", rec_msg.outbox[0].text)

    @patch("plugins.crypto_trend.fetch_gate_klines")
    def test_on_the_fly_indicators_execution(self, mock_fetch):
        mock_fetch.return_value = create_mock_kline_df(length=200, base_price=3000.0)

        # On the fly: AIN 4h ema 20 ma 200
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "8888", "user_name": "trader"},
            "request": {"command": "画线", "args": "AIN 4h ema 20 ma 200", "is_agent": False}
        })
        bot_execute(rec_msg, {})
        self.assertEqual(len(rec_msg.outbox), 1)
        self.assertIn("AIN", rec_msg.outbox[0].text)
        self.assertEqual(rec_msg.payload["symbol"], "AIN")
        self.assertEqual(rec_msg.payload["interval"], "4h")
        self.assertIn("EMA_20", rec_msg.payload["mas"])
        self.assertIn("SMA_200", rec_msg.payload["mas"])

        if rec_msg.outbox[0].photo_url and os.path.exists(rec_msg.outbox[0].photo_url):
            try:
                os.remove(rec_msg.outbox[0].photo_url)
            except Exception:
                pass

    @patch("plugins.crypto_trend.fetch_gate_klines")
    def test_user_preference_auto_application(self, mock_fetch):
        mock_fetch.return_value = create_mock_kline_df(length=200, base_price=2700.0)

        # 1. User configures default to PAXG and 4h
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "auto_trader_77", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置 标的 PAXG", "is_agent": False}
        })
        bot_execute(rec_msg, {})

        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "auto_trader_77", "user_name": "trader"},
            "request": {"command": "画线", "args": "设置 周期 4h", "is_agent": False}
        })
        bot_execute(rec_msg, {})

        # 2. User just sends "画线" without arguments
        rec_msg = RecordingMessage({
            "frontend": "onebot",
            "context": {"group_id": "1064595974", "user_id": "auto_trader_77", "user_name": "trader"},
            "request": {"command": "画线", "args": "", "is_agent": False}
        })
        bot_execute(rec_msg, {})

        self.assertEqual(rec_msg.payload["symbol"], "PAXG")
        self.assertEqual(rec_msg.payload["interval"], "4h")
        self.assertIn("PAXG", rec_msg.outbox[0].text)

        if rec_msg.outbox[0].photo_url and os.path.exists(rec_msg.outbox[0].photo_url):
            try:
                os.remove(rec_msg.outbox[0].photo_url)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
