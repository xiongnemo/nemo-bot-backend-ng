"""
Bilibili Hot Comments & Memes Scraper
-------------------------------------
Fetches top-liked comments from Bilibili videos (by BVID or keyword)
and formats them for Cyber Groupmate lore corpus.
"""

import sys
import json
import requests

def fetch_bilibili_hot_comments(bvid: str, count: int = 10) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com"
    }
    
    # 1. Get AID from BVID
    view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    r = requests.get(view_url, headers=headers, timeout=8)
    if r.status_code != 200:
        print(f"Failed to fetch video info: HTTP {r.status_code}")
        return []
    
    data = r.json().get("data", {})
    aid = data.get("aid")
    title = data.get("title", "")
    if not aid:
        print("Could not resolve AID from BVID.")
        return []
    
    print(f"Video: {title} (AID: {aid})")
    
    # 2. Get Hot Replies (mode=3 is hot sort)
    reply_url = f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&ps={count}"
    rr = requests.get(reply_url, headers=headers, timeout=8)
    if rr.status_code != 200:
        print(f"Failed to fetch replies: HTTP {rr.status_code}")
        return []
    
    replies = rr.json().get("data", {}).get("replies", []) or []
    results = []
    for rep in replies:
        user = rep.get("member", {}).get("uname", "网友")
        msg = rep.get("content", {}).get("message", "").strip()
        like = rep.get("like", 0)
        results.append({
            "user": user,
            "message": msg,
            "likes": like
        })
    return results

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    test_bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1GJ411x7h7"
    print(f"Fetching hot comments for {test_bvid}...")
    comments = fetch_bilibili_hot_comments(test_bvid, 10)
    print(f"\n--- Top {len(comments)} Comments ---")
    for i, c in enumerate(comments, 1):
        print(f"{i}. [{c['user']} | 👍{c['likes']}]:\n   {c['message']}\n")
