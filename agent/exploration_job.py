"""
Autonomous Nightly Exploration Engine
------------------------------------
Automatically explores Bilibili trending videos, harvests hot comments,
distills sharp memes and witty comebacks using LLM, and ingests them directly
into `personas/cyber_mate_lore.md` with hot-reload.
"""

from __future__ import annotations

import os
import re
import time
import json
import logging
from datetime import datetime, timezone, timedelta
import requests

from config import get_reflection_model

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com"
}

DISTILL_PROMPT = """你是一个顶级中文互联网社群文化与造梗大师（兼资深群友）。你的任务是从以下 B 站最新热门视频与高赞神评中，提炼出适合作为“赛博群友”在群聊中吐槽、互动、接梗的高质量语料。

请仔细阅读提供的视频标题与高赞神评列表，提取并重构为两部分：
1. new_catchphrases: 2-5 条简短有力、适用性广的最新流行梗短句/切口/黑话（例如：“一身的班味洗都洗不掉”、“纯度太高了”、“做完你的做你的”）。
2. new_memes: 2-4 个典型的【群聊互动情境】与【赛博群友神回复】组合。
   - situation: 概括群聊中什么情况下会触发（例如：“群友在群里晒单亏钱/被套”、“群友深夜发癫”、“群友遇到离谱Bug”）。
   - quote: 赛博群友极具活人感、懂梗、幽默讽刺或一针见血的原话神回复（避免生硬书面语，必须是地道真实的群友口吻）。

请务必以如下严格的 JSON 格式输出，不要包含任何额外的 Markdown 标记（如 ```json）：
{
    "new_catchphrases": [
        "又被你装到了，下次提前通知我戴墨镜",
        "好跌！开香槟咯~"
    ],
    "new_memes": [
        {
            "situation": "群友在群里疯狂凡尔赛或者炫耀",
            "quote": "哎呦喂，这波凡尔赛纯度拉满了啊，刺得我眼睛都快睁不开了。大家快来看啊，这里有个有钱人又在不经意间流露出尊贵的气息了！"
        }
    ]
}
"""


def fetch_bilibili_trending_data(max_videos: int = 6, comments_per_video: int = 12, target_bvid: str = "") -> list[dict]:
    """Fetch trending or specific video metadata and top-liked comments."""
    videos_data = []

    if target_bvid:
        # Fetch specific video
        view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={target_bvid}"
        try:
            r = requests.get(view_url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                vdata = r.json().get("data", {})
                aid = vdata.get("aid")
                title = vdata.get("title", "")
                if aid:
                    videos_data.append({"bvid": target_bvid, "aid": aid, "title": title})
        except Exception:
            logger.exception("Failed to fetch info for %s", target_bvid)
    else:
        # Fetch popular list
        popular_url = f"https://api.bilibili.com/x/web-interface/popular?ps={max_videos}&pn=1"
        try:
            r = requests.get(popular_url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("list", []) or []
                for item in items[:max_videos]:
                    bvid = item.get("bvid")
                    aid = item.get("aid")
                    title = item.get("title", "")
                    if bvid and aid:
                        videos_data.append({"bvid": bvid, "aid": aid, "title": title})
        except Exception:
            logger.exception("Failed to fetch Bilibili popular list")

    results = []
    for v in videos_data:
        aid = v["aid"]
        bvid = v["bvid"]
        title = v["title"]
        reply_url = f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&ps={comments_per_video}"
        try:
            rr = requests.get(reply_url, headers=HEADERS, timeout=8)
            replies = rr.json().get("data", {}).get("replies", []) or []
            comment_list = []
            for rep in replies:
                uname = rep.get("member", {}).get("uname", "网友")
                msg = rep.get("content", {}).get("message", "").strip().replace("\n", " ")
                like = rep.get("like", 0)
                # Filter out single-character or trivial comments
                if len(msg) >= 4 and not msg.startswith("http"):
                    comment_list.append({"user": uname, "message": msg, "like": like})
            if comment_list:
                results.append({
                    "bvid": bvid,
                    "title": title,
                    "comments": comment_list
                })
        except Exception:
            logger.warning("Failed to fetch replies for aid %s", aid)

    return results


def distill_memes_with_llm(video_data: list[dict]) -> dict:
    """Use LLM to analyze comments and generate structured meme pairs."""
    if not video_data:
        return {}

    # Format into text context
    blocks = []
    for i, v in enumerate(video_data, 1):
        c_lines = [f"  - [{c['user']} | 👍{c['like']}]: {c['message']}" for c in v["comments"][:10]]
        comments_str = "\n".join(c_lines)
        blocks.append(f"【热门视频 {i}】: {v['title']} (BV: {v['bvid']})\n高赞神评:\n{comments_str}")

    full_text = "\n\n".join(blocks)

    reflection_models = get_reflection_model()
    if not reflection_models:
        logger.error("[Exploration] reflection_model is not configured!")
        return {}

    for ref_model_str in reflection_models:
        try:
            from nemollm.registry import get_client
            client, actual_model = get_client(ref_model_str)
        except Exception as e:
            logger.warning("[Exploration] Could not load client for %s: %s", ref_model_str, e)
            continue

        try:
            from nemollm import ChatMessage
            resp = client.chat(
                model=actual_model,
                messages=[ChatMessage(role="user", content=f"【今日 B 站热门视频与高赞评论汇总】\n\n{full_text}")],
                system=DISTILL_PROMPT,
            )
            raw = (resp.text or "").strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.endswith("```"):
                raw = raw[:-3]
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    data = json.loads(m.group(0))
                else:
                    continue
            return data
        except Exception as e:
            logger.warning("[Exploration] Model %s failed during meme distillation: %s", actual_model, e)

    return {}


def ingest_into_cyber_mate_lore(distilled: dict) -> tuple[int, int]:
    """
    Append new catchphrases and meme scenarios into personas/cyber_mate_lore.md.
    Returns (num_catchphrases_added, num_memes_added).
    """
    if not distilled:
        return 0, 0

    base_dir = os.path.dirname(os.path.dirname(__file__))
    lore_path = os.path.join(base_dir, "personas", "cyber_mate_lore.md")
    
    existing_content = ""
    if os.path.exists(lore_path):
        with open(lore_path, "r", encoding="utf-8") as f:
            existing_content = f.read()

    new_catchphrases = distilled.get("new_catchphrases", []) or []
    new_memes = distilled.get("new_memes", []) or []

    added_phrases = []
    for p in new_catchphrases:
        p_clean = p.strip().strip('"').strip("'")
        if p_clean and p_clean not in existing_content:
            added_phrases.append(p_clean)

    added_memes = []
    for m in new_memes:
        sit = m.get("situation", "").strip()
        quote = m.get("quote", "").strip()
        if sit and quote and quote not in existing_content:
            added_memes.append((sit, quote))

    if not added_phrases and not added_memes:
        logger.info("[Exploration] No new unique memes to append.")
        return 0, 0

    tz_bj = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")

    append_parts = [f"\n\n### 【夜间自动探索新增语料 ({now_str})】\n"]

    if added_phrases:
        append_parts.append("#### 最新流行切口与短句：")
        for p in added_phrases:
            append_parts.append(f'- "{p}"')
        append_parts.append("")

    if added_memes:
        append_parts.append("#### 最新实战情境与神回复：")
        for sit, quote in added_memes:
            append_parts.append(f"* **【情境：{sit}】**\n  > “{quote}”\n")

    full_append = "\n".join(append_parts)

    with open(lore_path, "a", encoding="utf-8") as f:
        f.write(full_append)

    logger.info(
        "[Exploration] Successfully ingested %d catchphrases and %d meme scenarios into %s",
        len(added_phrases), len(added_memes), lore_path
    )
    return len(added_phrases), len(added_memes)


def save_discovery_archive(video_data: list[dict], distilled: dict):
    """Save raw discovery result to data/discoveries/YYYY-MM-DD.json."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    disc_dir = os.path.join(base_dir, "data", "discoveries")
    os.makedirs(disc_dir, exist_ok=True)

    tz_bj = timezone(timedelta(hours=8))
    date_str = datetime.now(tz_bj).strftime("%Y-%m-%d")
    out_file = os.path.join(disc_dir, f"{date_str}.json")

    record = {
        "timestamp": datetime.now(tz_bj).isoformat(),
        "videos_scanned": len(video_data),
        "video_titles": [v["title"] for v in video_data],
        "distilled_memes": distilled,
    }

    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        logger.info("[Exploration] Saved discovery archive to %s", out_file)
    except Exception:
        logger.exception("Failed to save discovery archive")


def run_exploration_job(target_bvid: str = "") -> dict:
    """
    Main entrypoint for nightly autonomous exploration.
    Can also be invoked on-demand with a specific BVID.
    """
    logger.info("[Exploration] Starting autonomous meme exploration job (target_bvid: %s)...", target_bvid or "Trending")

    # 1. Fetch data from Bilibili
    video_data = fetch_bilibili_trending_data(max_videos=6, comments_per_video=12, target_bvid=target_bvid)
    if not video_data:
        logger.warning("[Exploration] Failed to fetch any video or comment data from Bilibili.")
        return {"ok": False, "msg": "未获取到有效的 B 站视频或评论数据"}

    logger.info("[Exploration] Fetched %d videos with hot comments. Distilling with LLM...", len(video_data))

    # 2. Distill with LLM
    distilled = distill_memes_with_llm(video_data)
    if not distilled:
        logger.warning("[Exploration] LLM meme distillation returned empty result.")
        return {"ok": False, "msg": "大模型热梗提纯未产生有效输出"}

    # 3. Ingest into Cyber Groupmate Lore
    n_phrases, n_memes = ingest_into_cyber_mate_lore(distilled)

    # 4. Save discovery archive
    save_discovery_archive(video_data, distilled)

    # 5. Hot Reload Persona Store
    try:
        from runtime import context
        if context.persona_store is not None:
            count = context.persona_store.reload()
            logger.info("[Exploration] Hot reloaded %d personas in memory.", count)
    except Exception:
        logger.exception("[Exploration] Hot reloading personas failed")

    summary_msg = (
        f"成功探索 {len(video_data)} 个热门视频，"
        f"提纯并沉淀了 {n_phrases} 条新切口、{n_memes} 个群聊神回复场景，"
        f"已自动更新「赛博群友」语料库并完成热重载！"
    )
    logger.info("[Exploration] Done: %s", summary_msg)
    return {
        "ok": True,
        "msg": summary_msg,
        "videos": [v["title"] for v in video_data],
        "distilled": distilled,
        "added_phrases_count": n_phrases,
        "added_memes_count": n_memes,
    }
