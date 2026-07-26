"""
Console Client for testing nemo-bot-backend-ng locally.

Usage:
  # In terminal 1:
  uv run python app.py

  # In terminal 2:
  uv run python console.py
"""

import time
import requests
import threading
import logging
import yaml
import os
import shutil
from flask import Flask, request

# Read the port from config.yml to ensure we hit the right server
with open("config.yml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

server_port = config.get("server", {}).get("port", 42164)
BASE = f"http://127.0.0.1:{server_port}"

console_cfg = config.get("message_backend", {}).get("console", {})
console_endpoint = console_cfg.get("endpoint", "http://127.0.0.1:42165/receive")
# Parse port from endpoint: e.g. "http://127.0.0.1:42165/receive"
try:
    receiver_port = int(console_endpoint.split(":")[2].split("/")[0])
except Exception:
    receiver_port = 42165

# Use the first superuser as our default user ID, else fallback
superusers = console_cfg.get("superusers", ["3240295516"])
current_user = superusers[0] if superusers else "3240295516"

import sys

# --- Local Receiver Server ---
receiver_app = Flask(__name__)
# Suppress flask logging so it doesn't mess up our console
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

reply_event = threading.Event()
current_message_id = None

@receiver_app.route("/receive", methods=["POST"])
def receive():
    payload = request.get_json()
    if payload:
        # Handle text
        text = payload.get("text", "")
        if text:
            print(text, end="")
            sys.stdout.flush()
            
        # Handle photo
        photo_url = payload.get("photo_url")
        if photo_url:
            os.makedirs("downloads", exist_ok=True)
            import urllib.parse
            ext = os.path.splitext(urllib.parse.urlparse(photo_url).path)[1]
            if not ext: ext = ".png"
            filename = f"downloads/photo_{int(time.time())}{ext}"
            try:
                if photo_url.startswith("http"):
                    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
                    r = requests.get(photo_url, headers=headers, timeout=10)
                    r.raise_for_status()
                    if len(r.content) == 0:
                        raise ValueError("Downloaded image is 0 bytes. The remote server might be blocking the request or the URL is invalid.")
                    with open(filename, "wb") as f:
                        f.write(r.content)
                else:
                    # Assume it's a local path
                    shutil.copy(photo_url, filename)
                print(f"\n[Image Saved]: {os.path.abspath(filename)}")
            except Exception as e:
                print(f"\n[Error saving image]: {e}")
            sys.stdout.flush()

        msg_id = payload.get("message_id")
        if msg_id and msg_id == current_message_id:
            reply_event.set()
            
    return "OK", 200

def start_receiver():
    receiver_app.run(host="127.0.0.1", port=receiver_port, debug=False, use_reloader=False)

# --- Console Client ---
def post_ingest(text: str, ated: bool = False):
    payload = {
        "frontend": "console",
        "context": {
            "group_id": "", # Console is treated as a DM (Direct Message)
            "user_id": current_user, # Your user ID, making you superuser by default based on config.yml
            "user_name": "TerminalUser",
            "message_id": current_message_id,
            "self_id": "nemo",
            "ated": ated,
        },
        "request": {
            "args": text,
            "imgs": [],
            "raw_message": text,
        },
    }
    try:
        requests.post(f"{BASE}/ingest", json=payload, timeout=2)
    except requests.ConnectionError:
        print(f"\n[Error]: Server not running on {BASE}!")
        print("Start it with: uv run python app.py")

def main():
    # Start receiver in background
    t = threading.Thread(target=start_receiver, daemon=True)
    t.start()

    print("=========================================================")
    print("                 Nemo Console Client                     ")
    print("=========================================================")
    print("- Type your message and press Enter.")
    print("- Use '@' prefix to simulate an @ message (e.g. '@天气 上海')")
    print("- Type 'exit' or 'quit' to quit.")
    print("=========================================================\n")
    
    while True:
        try:
            text = input("[You]: ").strip()
            if not text:
                continue
            if text.lower() in ('exit', 'quit'):
                break
            
            ated = False
            if text.startswith("@"):
                ated = True
                text = text[1:].strip()
                
            global current_message_id
            current_message_id = "console_" + str(int(time.time()))
            reply_event.clear()
            post_ingest(text, ated)
            
            # Wait up to 60 seconds for the backend to reply.
            # (If it's an agent task, it might take a while).
            replied = reply_event.wait(timeout=60.0)
            if replied:
                # Add a tiny sleep to ensure the stdout flush fully paints 
                # before we print the next [You]: prompt.
                time.sleep(0.05)
                print() # newline before the next prompt
            
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
            
if __name__ == "__main__":
    main()

