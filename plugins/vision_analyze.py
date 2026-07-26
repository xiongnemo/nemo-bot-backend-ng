"""
Vision Analyze Plugin
---------------------
Takes a prompt and an image URL, downloads the image, and sends it to the
configured vision_model for multimodal analysis.

Usage via Agent:
    {"query": "{\"prompt\": \"Analyze this chart\", \"url\": \"http://...\"}"}

Usage via CLI:
    vision_analyze <url> <prompt...>
"""

import base64
import json
import logging
import requests
import traceback
from typing import Any

from config import backend_config
from core.message import Message
from nemollm.registry import get_registry
from nemollm.types import ChatMessage
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["vision", "vision_analyze"]
_name = "多模态视觉分析"
_man = "用法: vision_analyze <url> <prompt>。例如: vision_analyze http://example.com/img.jpg 请分析这张图片。"
_tool_description = "对给定的图片 URL 进行多模态视觉分析。支持 http(s):// 网络链接以及 file:/// 本地绝对路径。参数(query)建议以 JSON 格式提供，包含 prompt 和 url 两个字段。"
_enabled = 1


def _fetch_image_as_base64(url: str) -> str:
    """Download or read an image and return its base64 encoded string."""
    if url.startswith("http://") or url.startswith("https://"):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        content = r.content
    else:
        import os
        from urllib.request import url2pathname
        from urllib.parse import urlparse
        
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


@generic_exception_handler
def bot_execute(message: Message, config: dict) -> None:
    query = message.request.args.strip()
    if not query:
        message.reply("缺少参数。必须提供 prompt 和 url。")
        return
        
    # 1. Parse Arguments (JSON or Space-separated)
    prompt = "请简要分析这张图片"
    url = ""
    
    if query.startswith("{") and query.endswith("}"):
        try:
            data = json.loads(query)
            prompt = data.get("prompt", prompt)
            url = data.get("url", "")
        except json.JSONDecodeError:
            message.reply("传入的 JSON 参数格式不正确。")
            return
    else:
        # CLI fallback: first part is URL, rest is prompt
        parts = query.split(" ", 1)
        url = parts[0]
        if len(parts) > 1:
            prompt = parts[1].strip()
            
    if not url:
        message.reply("未提供图片 URL 或路径。")
        return
        
    # 2. Get Vision Model Config
    llm_cfg = backend_config.get("llm", {})
    vision_model_str = llm_cfg.get("vision_model")
    if not vision_model_str:
        message.reply("配置中未找到 llm.vision_model，无法进行视觉分析。")
        return
        
    try:
        registry = get_registry()
    except RuntimeError:
        message.reply("模型注册表尚未初始化。")
        return
        
    vision_models = vision_model_str if isinstance(vision_model_str, list) else [vision_model_str]
    
    # 3. Download and Encode Image
    message.reply(f"正在拉取图片并召唤视觉模型进行分析...")
    try:
        b64_img = _fetch_image_as_base64(url)
    except Exception as e:
        logger.error(f"Failed to fetch image {url}: {e}")
        message.reply(f"拉取图片失败: {e}")
        return
        
    # 4. Construct Multimodal ChatMessage
    data_uri = f"data:image/jpeg;base64,{b64_img}"
    
    content_parts = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}}
    ]
    
    chat_msg = ChatMessage(
        role="user",
        content=content_parts
    )
    
    # 5. Execute Analysis with Fallback
    response = None
    last_err = None
    
    for v_model_str in vision_models:
        parts = v_model_str.split(":", 1)
        provider_name, actual_model = parts if len(parts) == 2 else ("openai", v_model_str)
        
        client = registry.providers.get(provider_name)
        if not client:
            last_err = Exception(f"未找到对应的模型供应商: {provider_name}")
            continue
            
        try:
            response = client.chat(
                model=actual_model,
                messages=[chat_msg],
                temperature=0.3,
            )
            break
        except Exception as e:
            logger.warning(f"Vision model {actual_model} failed: {e}")
            last_err = e
            continue
            
    if not response:
        traceback.print_exc()
        message.reply(f"视觉分析失败: 所有后备模型均不可用。最后错误: {last_err}")
        return
        
    # Save to payload for the agentic loop
    message.payload = {
        "prompt": prompt,
        "url": url,
        "analysis": response.text
    }
    
    # Reply for human user
    message.reply(response.text)
        


if __name__ == "__main__":
    pass
