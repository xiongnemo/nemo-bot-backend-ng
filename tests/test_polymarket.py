import unittest
from unittest.mock import patch, MagicMock

from core.recording_message import RecordingMessage
from plugins.polymarket import (
    _clean_and_translate_query,
    _format_odds,
    _format_volume,
    handle_market_search,
    handle_whale_query,
    bot_execute,
)


def make_test_msg(command: str, args: str, is_agent: bool = False) -> RecordingMessage:
    msg_dict = {
        "frontend": "onebot",
        "context": {
            "group_id": "1064595974",
            "user_id": "u1",
            "user_name": "tester",
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


class TestPolymarketPlugin(unittest.TestCase):

    def test_query_cleaning_and_translation(self):
        self.assertEqual(_clean_and_translate_query("比特币 11月底"), "Bitcoin November")
        self.assertEqual(_clean_and_translate_query("大饼 100k"), "Bitcoin 100k")
        self.assertEqual(_clean_and_translate_query("S赛"), "LoL Worlds")
        self.assertEqual(_clean_and_translate_query("美联储 降息"), "Fed Fed rate cut")
        self.assertEqual(_clean_and_translate_query("HLE IG"), "Hanwha Invictus")

    def test_odds_formatting(self):
        self.assertEqual(_format_odds(0.725), "72.5% (~1.38)")
        self.assertEqual(_format_odds(0.275), "27.5% (~3.64)")
        self.assertEqual(_format_odds(0.50), "50.0% (~2.00)")
        self.assertEqual(_format_odds(0.0), "0.0%")

    def test_volume_formatting(self):
        self.assertEqual(_format_volume(1500000), "$1.50M")
        self.assertEqual(_format_volume(25400), "$25.4K")
        self.assertEqual(_format_volume(500), "$500")

    @patch("plugins.polymarket._fetch_json")
    def test_market_search_success(self, mock_fetch):
        mock_fetch.return_value = {
            "events": [
                {
                    "title": "LoL: Hanwha Life Esports vs Invictus Gaming",
                    "volume": 500000,
                    "markets": [
                        {
                            "question": "LoL: Hanwha Life Esports vs Invictus Gaming",
                            "outcomes": '["Hanwha Life Esports", "Invictus Gaming"]',
                            "outcomePrices": '["0.725", "0.275"]',
                            "closed": False
                        }
                    ]
                }
            ]
        }
        res = handle_market_search("HLE IG")
        self.assertIn("Hanwha Life Esports", res)
        self.assertIn("72.5%", res)
        self.assertIn("~1.38", res)
        self.assertIn("27.5%", res)
        self.assertIn("~3.64", res)

    @patch("plugins.polymarket._fetch_json")
    def test_whale_query_success(self, mock_fetch):
        def mock_fetch_router(url, timeout=8):
            if "positions" in url:
                return [
                    {
                        "title": "LoL: G2 vs LOS",
                        "outcome": "G2",
                        "currentValue": 50000,
                        "avgPrice": 0.80,
                        "curPrice": 0.85,
                        "percentPnl": 6.25
                    }
                ]
            elif "activity" in url:
                return [
                    {
                        "side": "BUY",
                        "title": "LoL: G2 vs LOS",
                        "outcome": "G2",
                        "usdcSize": 12000,
                        "price": 0.80,
                        "timestamp": 1792846580
                    }
                ]
            return []

        mock_fetch.side_effect = mock_fetch_router
        res = handle_whale_query("0x6ac5bb06a9eb05641fd5e82640268b92f3ab4b6e")
        self.assertIn("Polymarket 巨鲸追踪", res)
        self.assertIn("0x6ac5...4b6e", res)
        self.assertIn("LoL: G2 vs LOS", res)
        self.assertIn("买入开仓", res)

    @patch("plugins.polymarket._fetch_json")
    def test_bot_execute_dispatch(self, mock_fetch):
        mock_fetch.return_value = {"events": []}
        msg = make_test_msg("poly", "HLE")
        bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("404: nemo:", msg.outbox[0].text)

        # Empty query
        msg_empty = make_test_msg("poly", "")
        bot_execute(msg_empty, {})
        self.assertTrue(len(msg_empty.outbox) > 0)
        self.assertIn("400: nemo:", msg_empty.outbox[0].text)


if __name__ == "__main__":
    unittest.main()
