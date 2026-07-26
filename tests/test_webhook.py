import requests
import time

payload = {
    "channel_name": "test_news",
    "title": "Breaking News: Agent completed task",
    "content": "The backend system now successfully supports Pub/Sub and Information Feeds.",
    "original_time": int(time.time()),
    "meta": {"source": "local_test"}
}

headers = {
    "Authorization": "Bearer secret_token_123"
}

# Add channel first
r1 = requests.post("http://127.0.0.1:42163/api/channel", json={"name": "test_news", "description": "Test Channel"}, headers=headers)
print("Create Channel:", r1.status_code, r1.text)

# Push feed
r2 = requests.post("http://127.0.0.1:42163/api/feed", json=payload, headers=headers)
print("Push Feed:", r2.status_code, r2.text)
