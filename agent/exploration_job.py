"""
Autonomous Nightly Exploration Engine
------------------------------------
Automatically explores Bilibili trending videos or user-specified topics (searching by highest popularity/views),
harvests hot comments, distills sharp memes, topic summaries, and witty comebacks using LLM,
and ingests them directly into `personas/cyber_mate_lore.md` with hot-reload.
"""

from __future__ import annotations

import os
import re
import time
import json
import logging
from datetime import datetime, timezone, timedelta
import requests

from config import get_reflection_model, get_exploration_topics

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/"
}

DISTILL_PROMPT = """你是一个顶级中文互联网社群文化与造梗大师（兼资深群友）。你的任务是从以下 B 站特定话题/热门视频及其高赞神评中，总结出话题热点，并提炼适合作为“赛博群友”在群聊中吐槽、互动、接梗的高质量语料。

请仔细阅读提供的视频标题、播放量与高赞神评列表，提取并重构为三部分：
1. topic_summaries: 针对输入中的每个主要话题，用 1-2 句犀利、幽默、一针见血的群友风格语言总结【目前该话题的网民核心热议焦点与主流态度】。
2. new_catchphrases: 2-5 条简短有力、适用性广的最新流行梗短句/切口/黑话（例如：“一身的班味洗都洗不掉”、“纯度太高了”、“做完你的做你的”）。
3. new_memes: 2-5 个典型的【群聊互动情境】与【赛博群友神回复】组合。
   - situation: 概括群聊中什么情况下会触发（例如：“群友在群里晒单亏钱/被套”、“群友深夜发癫”、“群友讨论某某游戏被刺”、“群友疯狂凡尔赛”）。
   - quote: 赛博群友极具活人感、懂梗、幽默讽刺或一针见血的原话神回复（必须是地道真实的群友口吻）。

请务必以如下严格的 JSON 格式输出，不要包含任何额外的 Markdown 标记（如 ```json）：
{
    "topic_summaries": [
        {
            "topic": "打工人 摸鱼",
            "summary": "打工人普遍处于‘一身班味但只想开摆’的状态，对带薪摸鱼技巧和吐槽甲方有极高共鸣，核心态度是反内卷与自嘲。"
        }
    ],
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


def _get_bilibili_session() -> requests.Session:
    """Create a requests session initialized with cookies from bilibili.com."""
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://www.bilibili.com/", timeout=5)
    except Exception:
        pass
    return s


def fetch_bilibili_by_topics(
    topics: list[str],
    max_videos_per_topic: int = 3,
    comments_per_video: int = 10,
    order: str = "click"  # "click" (按播放量最多/热度最高) 或 "totalrank" (综合热度)
) -> list[dict]:
    """
    Search Bilibili for multiple specific topics, retrieving the highest popularity videos and their hot comments.
    """
    session = _get_bilibili_session()
    all_results = []

    for topic in topics:
        topic_clean = topic.strip()
        if not topic_clean:
            continue

        search_url = "https://api.bilibili.com/x/web-interface/search/type"
        params = {
            "search_type": "video",
            "keyword": topic_clean,
            "order": order,
            "page": 1,
            "page_size": max_videos_per_topic,
        }

        try:
            r = session.get(search_url, params=params, timeout=8)
            if r.status_code != 200:
                logger.warning("Search failed for topic '%s': HTTP %s", topic_clean, r.status_code)
                continue

            raw_results = r.json().get("data", {}).get("result", []) or []
            for v in raw_results[:max_videos_per_topic]:
                raw_title = v.get("title", "")
                clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
                bvid = v.get("bvid")
                aid = v.get("aid")
                play_count = v.get("play", 0)

                if not bvid or not aid:
                    continue

                # Fetch hot comments
                comments = _fetch_video_comments(session, aid, count=comments_per_video)
                all_results.append({
                    "topic": topic_clean,
                    "bvid": bvid,
                    "aid": aid,
                    "title": clean_title,
                    "play": play_count,
                    "comments": comments,
                })
        except Exception:
            logger.exception("Error searching Bilibili for topic: %s", topic_clean)

    return all_results


def _fetch_video_comments(session: requests.Session, aid: int | str, count: int = 12) -> list[dict]:
    """Fetch top-liked comments for a specific video aid."""
    reply_url = f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&ps={count}"
    comment_list = []
    try:
        rr = session.get(reply_url, timeout=8)
        replies = rr.json().get("data", {}).get("replies", []) or []
        for rep in replies:
            uname = rep.get("member", {}).get("uname", "网友")
            msg = rep.get("content", {}).get("message", "").strip().replace("\n", " ")
            like = rep.get("like", 0)
            if len(msg) >= 4 and not msg.startswith("http"):
                comment_list.append({"user": uname, "message": msg, "like": like})
    except Exception:
        logger.warning("Failed to fetch replies for aid %s", aid)
    return comment_list


def fetch_bilibili_trending_data(max_videos: int = 6, comments_per_video: int = 12, target_bvid: str = "") -> list[dict]:
    """Fetch trending or specific video metadata and top-liked comments."""
    session = _get_bilibili_session()
    videos_data = []

    if target_bvid:
        view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={target_bvid}"
        try:
            r = session.get(view_url, timeout=8)
            if r.status_code == 200:
                vdata = r.json().get("data", {})
                aid = vdata.get("aid")
                title = vdata.get("title", "")
                if aid:
                    videos_data.append({"topic": "指定视频", "bvid": target_bvid, "aid": aid, "title": title, "play": "热门"})
        except Exception:
            logger.exception("Failed to fetch info for %s", target_bvid)
    else:
        popular_url = f"https://api.bilibili.com/x/web-interface/popular?ps={max_videos}&pn=1"
        try:
            r = session.get(popular_url, timeout=8)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("list", []) or []
                for item in items[:max_videos]:
                    bvid = item.get("bvid")
                    aid = item.get("aid")
                    title = item.get("title", "")
                    play = item.get("stat", {}).get("view", "热门")
                    if bvid and aid:
                        videos_data.append({"topic": "全站热门", "bvid": bvid, "aid": aid, "title": title, "play": play})
        except Exception:
            logger.exception("Failed to fetch Bilibili popular list")

    results = []
    for v in videos_data:
        comments = _fetch_video_comments(session, v["aid"], count=comments_per_video)
        if comments:
            results.append({
                "topic": v["topic"],
                "bvid": v["bvid"],
                "aid": v["aid"],
                "title": v["title"],
                "play": v["play"],
                "comments": comments,
            })
    return results


def distill_memes_with_llm(video_data: list[dict]) -> dict:
    """Use LLM to analyze comments and generate structured topic summaries & memes."""
    if not video_data:
        return {}

    blocks = []
    for i, v in enumerate(video_data, 1):
        topic_tag = f"【话题: {v['topic']}】" if "topic" in v else ""
        c_lines = [f"  - [{c['user']} | 👍{c['like']}]: {c['message']}" for c in v["comments"][:10]]
        comments_str = "\n".join(c_lines)
        blocks.append(f"{topic_tag} 视频 {i}: 《{v['title']}》 (播放量: {v.get('play', '热门')}, BV: {v['bvid']})\n高赞神评:\n{comments_str}")

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
                messages=[ChatMessage(role="user", content=f"【B 站热门视频与高赞评论汇总】\n\n{full_text}")],
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


def ingest_into_cyber_mate_lore(distilled: dict, topic_label: str = "") -> tuple[int, int]:
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
    topic_summaries = distilled.get("topic_summaries", []) or []

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
    header_extra = f" (话题: {topic_label})" if topic_label else ""

    append_parts = [f"\n\n### 【夜间自动探索新增语料 ({now_str}){header_extra}】\n"]

    if topic_summaries:
        append_parts.append("#### 话题核心态势与焦点：")
        for ts in topic_summaries:
            append_parts.append(f"* **[{ts.get('topic')}]**: {ts.get('summary')}")
        append_parts.append("")

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


def save_discovery_archive(video_data: list[dict], distilled: dict, topics: list[str] | None = None):
    """Save raw discovery result to data/discoveries/YYYY-MM-DD.json."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    disc_dir = os.path.join(base_dir, "data", "discoveries")
    os.makedirs(disc_dir, exist_ok=True)

    tz_bj = timezone(timedelta(hours=8))
    date_str = datetime.now(tz_bj).strftime("%Y-%m-%d")
    out_file = os.path.join(disc_dir, f"{date_str}.json")

    record = {
        "timestamp": datetime.now(tz_bj).isoformat(),
        "topics_queried": topics or [],
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


def run_exploration_job(target_bvid: str = "", topics: list[str] | None = None) -> dict:
    """
    Main entrypoint for autonomous exploration:
    - If target_bvid is passed: Explore that single video.
    - If topics are passed (or configured): Search Bilibili for highest popularity videos under each topic!
    - Otherwise: Explore general trending videos.
    """
    effective_topics = topics
    if not target_bvid and not effective_topics:
        cfg_topics = get_exploration_topics()
        if cfg_topics:
            effective_topics = cfg_topics

    if target_bvid:
        logger.info("[Exploration] Exploring specific BVID: %s...", target_bvid)
        video_data = fetch_bilibili_trending_data(target_bvid=target_bvid)
        topic_label = target_bvid
    elif effective_topics:
        logger.info("[Exploration] Exploring highest popularity videos for topics: %s...", effective_topics)
        video_data = fetch_bilibili_by_topics(effective_topics, max_videos_per_topic=3, comments_per_video=10, order="click")
        topic_label = ", ".join(effective_topics)
    else:
        logger.info("[Exploration] Exploring general Bilibili trending popular videos...")
        video_data = fetch_bilibili_trending_data(max_videos=6, comments_per_video=12)
        topic_label = "全站热门"

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
    n_phrases, n_memes = ingest_into_cyber_mate_lore(distilled, topic_label=topic_label)

    # 4. Save discovery archive
    save_discovery_archive(video_data, distilled, topics=effective_topics)

    # 5. Hot Reload Persona Store
    try:
        from runtime import context
        if context.persona_store is not None:
            count = context.persona_store.reload()
            logger.info("[Exploration] Hot reloaded %d personas in memory.", count)
    except Exception:
        logger.exception("[Exploration] Hot reloading personas failed")

    summary_msg = (
        f"成功探索 {len(video_data)} 个热度最高视频（涵盖: {topic_label}），"
        f"提纯并沉淀了 {n_phrases} 条新切口、{n_memes} 个群聊神回复场景，"
        f"已自动更新「赛博群友」语料库并完成热重载！"
    )
    logger.info("[Exploration] Done: %s", summary_msg)
    return {
        "ok": True,
        "msg": summary_msg,
        "topics": effective_topics or [topic_label],
        "videos": [v["title"] for v in video_data],
        "distilled": distilled,
        "added_phrases_count": n_phrases,
        "added_memes_count": n_memes,
    }
