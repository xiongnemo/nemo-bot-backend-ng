import unittest
import requests

BASE = "http://127.0.0.1:42163"


def is_ng_server_running(url=f"{BASE}/health", timeout=0.5):
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        return False


@unittest.skipUnless(is_ng_server_running(), "nemo-bot-backend-ng server not running on port 42163")
class TestSmoke(unittest.TestCase):
    def post_ingest(self, text: str, ated: bool = False, frontend: str = "satori_http"):
        payload = {
            "frontend": frontend,
            "context": {
                "group_id": "485541033",
                "user_id": "3240295516",
                "user_name": "nemo",
                "message_id": "test_smoke",
                "self_id": "bot_id",
                "ated": ated,
            },
            "request": {
                "args": text,
                "imgs": [],
                "raw_message": text,
            },
        }
        resp = requests.post(f"{BASE}/ingest", json=payload, timeout=5)
        return resp

    def test_command_mode(self):
        resp = self.post_ingest("天气 上海")
        self.assertEqual(resp.status_code, 202)

    def test_agent_mode(self):
        resp = self.post_ingest("nemonemo 上海天气怎么样")
        self.assertEqual(resp.status_code, 202)

    def test_ated_mode(self):
        resp = self.post_ingest("今天上海天气怎么样", ated=True)
        self.assertEqual(resp.status_code, 202)

    def test_silent_mode(self):
        resp = self.post_ingest("今天午饭吃什么")
        self.assertEqual(resp.status_code, 202)


if __name__ == "__main__":
    unittest.main()
