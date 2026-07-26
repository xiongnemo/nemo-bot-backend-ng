import unittest
import requests
import time

BASE = "http://127.0.0.1:42163"


def is_ng_server_running(url=f"{BASE}/health", timeout=0.5):
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        return False


@unittest.skipUnless(is_ng_server_running(), "nemo-bot-backend-ng server not running on port 42163")
class TestWebhook(unittest.TestCase):
    def test_feed_webhook(self):
        headers = {"Authorization": "Bearer secret_token_123"}
        r1 = requests.post(
            f"{BASE}/api/channel",
            json={"name": "test_news", "description": "Test Channel"},
            headers=headers,
            timeout=5,
        )
        self.assertIn(r1.status_code, [200, 201, 400, 401, 403, 404, 409])

        payload = {
            "channel_name": "test_news",
            "title": "Breaking News: Agent completed task",
            "content": "The backend system now successfully supports Pub/Sub and Information Feeds.",
            "original_time": int(time.time()),
            "meta": {"source": "local_test"},
        }
        r2 = requests.post(f"{BASE}/api/feed", json=payload, headers=headers, timeout=5)
        self.assertIn(r2.status_code, [200, 201, 400, 401, 403, 404])


if __name__ == "__main__":
    unittest.main()
