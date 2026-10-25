import unittest
from unittest.mock import patch, MagicMock

from core.recording_message import RecordingMessage
from plugins.onchain_dex import (
    is_contract_address,
    format_num,
    format_age,
    build_onchain_report,
    fetch_onchain_data,
    bot_execute as dex_bot_execute,
)
from plugins.ticker import bot_execute as ticker_bot_execute


def make_test_msg(command: str, args: str, is_agent: bool = False) -> RecordingMessage:
    msg_dict = {
        "frontend": "onebot",
        "context": {
            "group_id": "123456",
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


MOCK_PAIR = {
    "chainId": "solana",
    "dexId": "pumpswap",
    "url": "https://dexscreener.com/solana/2xhrmdxskurh8ckmerbnhyciqghgsjlwmgckep9bmlkk",
    "baseToken": {
        "address": "Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump",
        "name": "FX Fighter Kurumi-chan",
        "symbol": "Kurumi"
    },
    "quoteToken": {
        "address": "So11111111111111111111111111111111111111112",
        "name": "Wrapped SOL",
        "symbol": "SOL"
    },
    "priceNative": "0.000009406",
    "priceUsd": "0.001138",
    "txns": {
        "h24": {"buys": 370, "sells": 343}
    },
    "volume": {"h24": 97049.14},
    "priceChange": {"h1": -2.01, "h24": -11.08},
    "liquidity": {"usd": 179340.10},
    "fdv": 1138131,
    "marketCap": 1138131,
    "pairCreatedAt": 1700000000000,
    "info": {
        "websites": [{"url": "https://kurumi.xyz"}],
        "socials": [{"type": "twitter", "url": "https://x.com/kurumi"}]
    }
}


class TestOnchainDexPlugin(unittest.TestCase):

    def test_is_contract_address(self):
        # Solana base58 mint addresses
        self.assertTrue(is_contract_address("Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump"))
        self.assertTrue(is_contract_address("2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"))
        self.assertTrue(is_contract_address("ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY"))

        # EVM addresses
        self.assertTrue(is_contract_address("0x44449eb99a54fb5F6de516Ca4DC213602d50BE33"))
        self.assertTrue(is_contract_address("0xbDAeccc75eBEd26E3069b768353f609Daa3F8b07"))

        # Normal tickers / symbols
        self.assertFalse(is_contract_address("BTC"))
        self.assertFalse(is_contract_address("ETH"))
        self.assertFalse(is_contract_address("KURUMI"))
        self.assertFalse(is_contract_address("MOODENG"))
        self.assertFalse(is_contract_address(""))

    def test_format_num(self):
        self.assertEqual(format_num(1234567890), "$1.23 B")
        self.assertEqual(format_num(1234567), "$1.23 M")
        self.assertEqual(format_num(1234), "$1.23 K")
        self.assertEqual(format_num(12.345), "$12.35")
        self.assertEqual(format_num(0.00001234), "$0.00001234")

    def test_build_onchain_report(self):
        report = build_onchain_report("KURUMI", [MOCK_PAIR])
        self.assertIn("FX Fighter Kurumi-chan", report)
        self.assertIn("SOLANA (pumpswap)", report)
        self.assertIn("$0.001138", report)
        self.assertIn("Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump", report)
        self.assertIn("$179.34 K", report)
        self.assertIn("370 买 / 343 卖", report)

    @patch("plugins.onchain_dex._http_get")
    def test_dex_bot_execute_success(self, mock_http):
        mock_http.return_value = {"pairs": [MOCK_PAIR]}
        msg = make_test_msg("dex", "KURUMI")
        dex_bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("FX Fighter Kurumi-chan", msg.outbox[0].text)

    @patch("plugins.onchain_dex._http_get")
    def test_dex_bot_execute_not_found(self, mock_http):
        mock_http.return_value = {"pairs": []}
        msg = make_test_msg("dex", "FAKECOIN")
        dex_bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("404: nemo: 未在链上或 DEX 搜索到关于 'FAKECOIN'", msg.outbox[0].text)

    def test_dex_bot_execute_empty(self):
        msg = make_test_msg("dex", "")
        dex_bot_execute(msg, {})
        self.assertTrue(len(msg.outbox) > 0)
        self.assertIn("400: nemo: 请提供链上代币代码或合约地址", msg.outbox[0].text)

    @patch("plugins.ticker.fetch_binance")
    @patch("plugins.ticker.fetch_gate")
    @patch("plugins.ticker.fetch_okx")
    @patch("plugins.ticker.fetch_hyperliquid")
    @patch("plugins.onchain_dex._http_get")
    def test_ticker_fallback_to_onchain(self, mock_http, mock_hl, mock_okx, mock_gate, mock_bn):
        # All CEX return None (not found)
        mock_bn.return_value = None
        mock_gate.return_value = None
        mock_okx.return_value = None
        mock_hl.return_value = None

        # DEX finds the token
        mock_http.return_value = {"pairs": [MOCK_PAIR]}

        msg = make_test_msg("coin", "KURUMI")
        ticker_bot_execute(msg, {})

        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("各大主板交易所未收录，已自动为你展示链上 DEX 行情", reply)
        self.assertIn("FX Fighter Kurumi-chan", reply)
        self.assertIn("Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump", reply)

    @patch("plugins.onchain_dex._http_get")
    def test_ticker_direct_ca_routing(self, mock_http):
        mock_http.return_value = {"pairs": [MOCK_PAIR]}

        msg = make_test_msg("coin", "Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump")
        ticker_bot_execute(msg, {})

        self.assertTrue(len(msg.outbox) > 0)
        reply = msg.outbox[0].text
        self.assertIn("检测到输入为链上合约地址(CA)，已自动为你查询 DEX 行情", reply)
        self.assertIn("FX Fighter Kurumi-chan", reply)


if __name__ == "__main__":
    unittest.main()
