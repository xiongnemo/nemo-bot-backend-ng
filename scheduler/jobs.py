"""
Definitions for built-in cron jobs (github-monitor, jinshi, gzctf).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from runtime.sender import Sender
from store.database import Database
from store.state_store import StateStore

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 1. GitHub Monitor
# ----------------------------------------------------------------------
def github_monitor_job(
    author: str, repo: str, branch: str, 
    github_username: str, github_pat: str,
    target_frontend: str, target_group_id: str,
):
    from runtime.context import sender, state_store
    state_key = f"{author}_{repo}_{branch}"
    last_sha = state_store.get("scheduler", "github_monitor", state_key, default="")

    url = f"https://api.github.com/repos/{author}/{repo}/commits"
    if branch:
        url += f"/{branch}"

    try:
        resp = requests.get(url, auth=(github_username, github_pat), timeout=10)
        resp.raise_for_status()
        commits = resp.json()
        
        latest_commit = commits if branch else commits[0]
        latest_sha = latest_commit["sha"]
        
        if latest_sha != last_sha:
            logger.info("GitHub Monitor: New commit in %s/%s: %s", author, repo, latest_sha)
            state_store.set("scheduler", "github_monitor", state_key, latest_sha)
            
            # Send message
            msg = latest_commit["commit"]["message"]
            html_url = latest_commit["html_url"]
            author_name = latest_commit["commit"]["author"]["name"]
            
            branch_str = f"({branch})" if branch else ""
            out_text = f"New commit in {author}/{repo} {branch_str} by {author_name}:\n{msg}\n{html_url}"
            
            msg_dict = {
                "frontend": target_frontend,
                "context": {"group_id": target_group_id, "user_id": ""},
            }
            sender.send_text(msg_dict, out_text)
            
    except Exception:
        logger.exception("GitHub monitor failed for %s/%s", author, repo)


# ----------------------------------------------------------------------
# 2. Jinshi (财经快讯)
# ----------------------------------------------------------------------
def jinshi_job(
    target_frontend: str, target_group_id: str,
):
    from runtime.context import sender, state_store
    import time
    import tls_client
    
    most_recent_id = state_store.get("scheduler", "jinshi", "most_recent_id", default=0)
    
    current_time = int(time.time() * 1000)
    url = f"https://www.jin10.com/flash_newest.js?t={current_time}"
    
    try:
        client = tls_client.Session(client_identifier="chrome_120")
        resp = client.get(url, timeout_seconds=10)
        j = resp.text.replace("var newest = ", "").strip(";")
        data = json.loads(j)
        
        # filter new important messages
        new_items = [i for i in data if "id" in i and int(i["id"]) > most_recent_id]
        
        if new_items:
            # Update state
            newest_id = int(new_items[0]["id"])
            state_store.set("scheduler", "jinshi", "most_recent_id", newest_id)
            
            for item in reversed(new_items): # older first for sending in order
                if item.get("important") == 1:
                    content = item.get("data", {}).get("content", "")
                    if "点击查看" not in content and "点击获取" not in content and ">>" not in content:
                        soup = BeautifulSoup(content, "html.parser")
                        title = item.get("data", {}).get("title", "")
                        
                        out_text = f"{item['time']}\n"
                        if title: out_text += f"{title}\n"
                        out_text += soup.text
                        
                        msg_dict = {
                            "frontend": target_frontend,
                            "context": {"group_id": target_group_id, "user_id": ""},
                        }
                        sender.send_text(msg_dict, out_text)
                        
    except Exception:
        logger.exception("Jinshi job failed")


# ----------------------------------------------------------------------
# 3. GZCTF Notice
# ----------------------------------------------------------------------
def gzctf_job(
    game_id: int, cookie: str,
    target_frontend: str, target_group_id: str,
):
    from runtime.context import sender, state_store
    last_id = state_store.get("scheduler", "gzctf", f"last_id_{game_id}", default=0)
    
    url = f"https://catctf.tongji.edu.cn/api/game/{game_id}/notices"
    headers = {"Cookie": cookie}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        if "status" in data:
            return  # Game not started or error
            
        new_items = [i for i in data if i.get("id", 0) > last_id]
        if new_items:
            max_id = max(i["id"] for i in new_items)
            state_store.set("scheduler", "gzctf", f"last_id_{game_id}", max_id)
            
            new_items.sort(key=lambda x: x["id"])
            
            for item in new_items:
                typ = item.get("type")
                vals = item.get("values", [])
                
                out_text = ""
                if typ == "NewChallenge":
                    chal = vals[0] if vals else "未知题目"
                    out_text = f"新增了题目 「{chal}」"
                elif typ == "NewHint":
                    chal = vals[0] if vals else "未知题目"
                    out_text = f"题目 「{chal}」 发布了新的提示"
                elif typ in ("FirstBlood", "SecondBlood", "ThirdBlood"):
                    player = vals[0] if len(vals) > 0 else "未知选手"
                    chal = vals[1] if len(vals) > 1 else "未知题目"
                    blood_map = {"FirstBlood": "一血", "SecondBlood": "二血", "ThirdBlood": "三血"}
                    out_text = f"恭喜 {player} 获得 「{chal}」 的{blood_map.get(typ, '血')}"
                else:
                    details = ", ".join(map(str, vals)) if vals else "无详细信息"
                    out_text = f"[{typ}] {details}"
                    
                msg_dict = {
                    "frontend": target_frontend,
                    "context": {"group_id": target_group_id, "user_id": ""},
                }
                sender.send_text(msg_dict, out_text)
                
    except Exception:
        logger.exception("GZCTF job failed")


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
def register_all_jobs(engine):
    """Register jobs defined in config or defaults."""
    from agent.reflection_job import run_reflection_job
    from agent.exploration_job import run_exploration_job
    
    # Run daily at 03:00 AM: Reflection & Memory distillation
    engine.add_cron_job(
        job_id="system:reflection_job",
        func=run_reflection_job,
        cron_expr="0 3 * * *"
    )

    # Run daily at 03:30 AM: Autonomous Meme Exploration & Lore evolution
    engine.add_cron_job(
        job_id="system:exploration_job",
        func=run_exploration_job,
        cron_expr="30 3 * * *"
    )

# ----------------------------------------------------------------------
# 4. User Notification
# ----------------------------------------------------------------------
def user_notification_job(
    message_dict: dict,
    text: str,
    is_reply: bool,
):
    from runtime.context import sender
    sender.send_text(message_dict, text, reply=is_reply)
