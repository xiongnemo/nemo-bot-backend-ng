import os
import json
import logging
import requests
from config import backend_config
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["gsearch", "谷歌搜索", "googlesearch"]
_name = "Google Grounding搜索"
_man = """使用 Gemini Google Grounding 功能进行深度搜索。
用法: {0} <搜索词>
例如: {0} 东京今天天气如何
"""
_tool_description = (
    "使用 Google 搜索引擎查询实时信息。当需要获取最新的互联网内容（如新闻、股市、热点、事实）时，应调用此工具。"
    "参数(query)传入你要搜索的自然语言问题。返回模型总结的文本内容以及引用的URL参考链接。"
)
_enabled = 1

def _do_search(query: str, model: str, base_url: str, api_key: str) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"googleSearch": {}}]
    }
    # Fix the model URL format if needed
    model_path = model if "/" in model else f"models/{model}"
    url = f"{base_url}/v1beta/{model_path}:generateContent"
    
    resp = requests.post(url, params={"key": api_key}, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Gemini API Error {resp.status_code}: {resp.text}")
    return resp.json()

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        raise Exception("400: nemo: 请提供搜索关键词，例如：gsearch 苹果发布会最新消息")
        
    gemini_cfg = backend_config.get("llm", {}).get("providers", {}).get("nemo-axonhub-gemini", {})
    api_key = gemini_cfg.get("api_key")
    base_url = gemini_cfg.get("base_url")
    
    if not api_key or not base_url:
        raise Exception("500: nemo: 系统未配置 Gemini API Key，无法使用谷歌搜索功能。")
        
    primary_model = "gemini-2.5-flash"
    fallback_model = "gemini-2.5-flash-lite"
    
    data = None
    try:
        data = _do_search(query, primary_model, base_url, api_key)
    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            logger.warning(f"Model {primary_model} hit 429, falling back to {fallback_model}...")
            try:
                data = _do_search(query, fallback_model, base_url, api_key)
            except Exception as inner_e:
                raise Exception(f"429: nemo: 所有搜索模型均已触及请求频率限制: {inner_e}")
        elif "400" in err_str:
            raise Exception(f"400: nemo: 请求参数无效，搜索失败: {err_str}")
        else:
            raise Exception(f"502: nemo: 外部搜索网关出现异常: {err_str}")
            
    # Parse result
    if not data or "candidates" not in data or not data["candidates"]:
        raise Exception("404: nemo: 搜索引擎未能返回有效结果。")
        
    candidate = data["candidates"][0]
    content_parts = candidate.get("content", {}).get("parts", [])
    answer_text = "".join([p.get("text", "") for p in content_parts])
    
    # Parse grounding metadata
    grounding_meta = candidate.get("groundingMetadata", {})
    chunks = grounding_meta.get("groundingChunks", [])
    
    refs = []
    for i, chunk in enumerate(chunks):
        web = chunk.get("web", {})
        title = web.get("title", "Unknown")
        uri = web.get("uri", "")
        if uri:
            refs.append(f"[{i}] {title}: {uri}")
            
    if refs:
        ref_str = "\n".join(refs)
        formatted = f"【谷歌搜索结果】\n{answer_text}\n\n【参考来源】\n{ref_str}"
    else:
        formatted = f"【谷歌搜索结果】\n{answer_text}"
        
    message.reply(formatted)

if __name__ == "__main__":
    import sys
    class MockRequest:
        def __init__(self, args):
            self.args = args
    class MockMessage:
        def __init__(self, args):
            self.request = MockRequest(args)
            self.replies = []
        def reply(self, text, **kwargs):
            print(f"[{__name__}] REPLY:\n{text}")
            self.replies.append(text)
            
    args_str = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "东京天气"
    msg = MockMessage(args_str)
    print(f"Testing with args: '{args_str}'")
    bot_execute(msg, {})
