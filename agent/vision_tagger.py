"""
Asynchronous Vision Tagger

Runs in the background to automatically fetch and describe images using the configured vision model.
Results are cached in StateStore to speed up LLM context generation.
"""

import base64
import logging
import requests
from urllib.request import url2pathname
from urllib.parse import urlparse
import os

from config import backend_config
from nemollm.registry import get_registry
from nemollm.types import ChatMessage

logger = logging.getLogger(__name__)

def _fetch_image_as_base64(url: str) -> str:
    """Download or read an image and return its base64 encoded string."""
    if url.startswith("base64://"):
        return url[9:]
    if url.startswith("data:") and ";base64," in url:
        return url.split(";base64,")[1]

    if url.startswith("http://") or url.startswith("https://"):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        content = r.content
    else:
        if url.startswith("file://"):
            p = urlparse(url)
            local_path = url2pathname(p.path)
        else:
            local_path = url
            
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")
            
        with open(local_path, "rb") as f:
            content = f.read()
            
    if len(content) == 0:
        raise ValueError("Image is 0 bytes.")
        
    return base64.b64encode(content).decode("utf-8")


def async_tag_images(urls: list[str], message_id: str, state_store):
    """
    Background job to tag multiple images.
    """
    if not urls:
        return

    llm_cfg = backend_config.get("llm", {})
    vision_model_str = llm_cfg.get("vision_model")
    if not vision_model_str:
        return

    try:
        registry = get_registry()
    except RuntimeError:
        return

    vision_models = vision_model_str if isinstance(vision_model_str, list) else [vision_model_str]
    
    prompt = "请仔细阅读这张图片。如果图片中有任何文字，请务必完整、准确地提取出所有文字内容，并描述它们的排版和布局位置；然后，请详细描述图片的主要画面内容、场景、人物细节及整体风格。请提供最详尽的完整描述，无需精简字数。"

    for url in urls:
        # Check if already tagged
        existing = state_store.get("img_tags", "global", url)
        if existing:
            continue

        logger.info(f"Background tagging started for {url}")
        
        try:
            b64_img = _fetch_image_as_base64(url)
        except Exception as e:
            logger.warning(f"Failed to fetch image for background tagging: {e}")
            continue

        data_uri = f"data:image/jpeg;base64,{b64_img}"
        
        content_parts = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}}
        ]
        
        chat_msg = ChatMessage(
            role="user",
            content=content_parts
        )

        tagged = False
        for v_model_str in vision_models:
            parts = v_model_str.split(":", 1)
            provider_name, actual_model = parts if len(parts) == 2 else ("openai", v_model_str)
            
            client = registry.providers.get(provider_name)
            if not client:
                continue
                
            try:
                response = client.chat(
                    model=actual_model,
                    messages=[chat_msg],
                    temperature=0.3,
                )
                if response and response.text:
                    tag_result = response.text.strip()
                    state_store.set("img_tags", "global", url, tag_result)
                    logger.info(f"Successfully tagged {url} using {v_model_str}. Content:\n{tag_result}")
                    tagged = True
                    break
            except Exception as e:
                logger.warning(f"Failed to tag {url} using {v_model_str}: {e}")
                
        if not tagged:
            logger.warning(f"All vision models failed to tag {url}")
            
    # If there are multiple images, generate an overall summary
    if len(urls) > 1 and message_id:
        existing_summary = state_store.get("img_tags", "summary", message_id)
        if existing_summary:
            return
            
        logger.info(f"Background summarizing {len(urls)} images for message {message_id}")
        
        summary_prompt = "以下是同一条消息中的多张图片。请结合所有的图片内容，给出这组图片的一个整体总结描述，指出它们之间的联系和核心主题。"
        content_parts = [{"type": "text", "text": summary_prompt}]
        
        valid_images = False
        for url in urls:
            try:
                b64_img = _fetch_image_as_base64(url)
                data_uri = f"data:image/jpeg;base64,{b64_img}"
                content_parts.append({"type": "image_url", "image_url": {"url": data_uri}})
                valid_images = True
            except Exception:
                continue
                
        if not valid_images:
            return
            
        summary_msg = ChatMessage(role="user", content=content_parts)
        
        for v_model_str in vision_models:
            parts = v_model_str.split(":", 1)
            provider_name, actual_model = parts if len(parts) == 2 else ("openai", v_model_str)
            client = registry.providers.get(provider_name)
            if not client:
                continue
                
            try:
                response = client.chat(
                    model=actual_model,
                    messages=[summary_msg],
                    temperature=0.3,
                )
                if response and response.text:
                    summary_result = response.text.strip()
                    state_store.set("img_tags", "summary", message_id, summary_result)
                    logger.info(f"Successfully summarized message {message_id} using {v_model_str}")
                    break
            except Exception as e:
                logger.warning(f"Failed to summarize message {message_id} using {v_model_str}: {e}")
