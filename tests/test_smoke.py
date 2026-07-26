"""
Smoke test for nemo-bot-backend-ng.

Tests:
1. Command-mode: POST /ingest with "天气 上海" -> should route to weather plugin
2. Agent-mode: POST /ingest with "nemonemo 上海天气怎么样" -> should go through agent

Usage:
    # First, start the backend in another terminal:
    #   cd nemo-bot-backend-ng && uv run app.py
    #
    # Then run this test:
    #   uv run python test_smoke.py
"""

import json
import time
import requests

BASE = "http://127.0.0.1:42163"


def post_ingest(text: str, ated: bool = False, frontend: str = "satori_http"):
    """Send a message to the /ingest endpoint."""
    payload = {
        "frontend": frontend,
        "context": {
            "group_id": "485541033",
            "user_id": "3240295516",
            "user_name": "nemo",
            "message_id": "test_" + str(int(time.time())),
            "self_id": "bot_id",
            "ated": ated,
        },
        "request": {
            "args": text,
            "imgs": [],
            "raw_message": text,
        },
    }
    print(f"\n{'='*60}")
    print(f">>> POST /ingest: {text!r} (ated={ated})")
    print(f"    payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    resp = requests.post(f"{BASE}/ingest", json=payload, timeout=5)
    print(f"<<< HTTP {resp.status_code}: {resp.json()}")
    return resp


def test_health():
    """Check if the server is up."""
    try:
        resp = requests.get(f"{BASE}/", timeout=2)
        print(f"Server health: HTTP {resp.status_code}")
        return True
    except requests.ConnectionError:
        print("ERROR: Server not running! Start with: cd nemo-bot-backend-ng && uv run app.py")
        return False


def main():
    print("=" * 60)
    print("nemo-bot-backend-ng Smoke Test")
    print("=" * 60)

    if not test_health():
        return

    # Test 1: Command mode (deterministic routing)
    print("\n--- Test 1: Command-mode (天气 上海) ---")
    resp = post_ingest("天气 上海")
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
    print("✓ Accepted (202). Check backend logs for weather plugin output.")
    
    # Give the process pool time to execute
    time.sleep(3)

    # Test 2: Agent mode (nemonemo trigger)
    print("\n--- Test 2: Agent-mode (nemonemo 上海天气) ---")
    print("    (Requires LLM API key in config.json to work fully)")
    resp = post_ingest("nemonemo 上海天气怎么样")
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
    print("✓ Accepted (202). Check backend logs for agent loop output.")
    
    time.sleep(3)

    # Test 3: @ triggers agent
    print("\n--- Test 3: @-mode (ated=True) ---")
    resp = post_ingest("今天上海天气怎么样", ated=True)
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
    print("✓ Accepted (202). Agent should be triggered by @.")
    
    time.sleep(3)

    # Test 4: Silent mode (group chat, no trigger)
    print("\n--- Test 4: Silent-mode (group noise) ---")
    resp = post_ingest("今天午饭吃什么")
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
    print("✓ Accepted (202). Should be silently stored, no reply.")

    print(f"\n{'='*60}")
    print("All smoke tests passed! Check the backend terminal for execution details.")
    print("Also check data/nemo.sqlite for stored messages:")
    print("  sqlite3 data/nemo.sqlite 'SELECT * FROM messages;'")
    print("=" * 60)


if __name__ == "__main__":
    main()
