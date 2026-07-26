"""
WebFetch Plugin
---------------------
Bypasses basic anti-bot protections using TLS fingerprint spoofing (tls-client).
Extracts HTML and converts it to Markdown.
"""

import logging
import tls_client
import re
from markdownify import markdownify as markdown

from core.message import Message
from config import backend_config
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "网页抓取 (WebFetch)"
_command = ["webfetch", "fetch"]
_man = "用法: webfetch <URL>。"
_tool_description = "伪造 Chrome 浏览器指纹绕过反爬机制，抓取目标 URL 的网页内容，并自动转为适合大模型阅读的 Markdown 格式。"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    url = message.request.args.strip()
    if not url:
        message.reply("400: nemo: 请提供要抓取的 URL。")
        return

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    message.reply(f"正在模拟 Chrome_146 抓取: {url} ...")
    
    try:
        # Spoof Chrome 146 TLS fingerprint
        session = tls_client.Session(
            client_identifier="chrome_146",
            random_tls_extension_order=True
        )
        
        # Add basic browser headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        response = session.get(url, headers=headers, timeout_seconds=30, allow_redirects=True)
        
        if response.status_code != 200:
            message.reply(f"【抓取警告】目标返回非 200 状态码: {response.status_code}")
            
        html_content = response.text
        
        # Convert HTML to Markdown, stripping out noisy tags
        md_content = markdown(
            html_content, 
            strip=['script', 'style', 'img', 'video', 'audio', 'iframe']
        )
        
        # Clean up excessive empty lines without destroying Markdown indentation/paragraphs
        import re
        cleaned_md = re.sub(r'\n{3,}', '\n\n', md_content).strip()
        
        reply_text = f"【抓取成功 ({response.status_code})】\n\n{cleaned_md}"
        
        # Truncate if too long for messaging platforms (Agent payload can be longer)
        if len(reply_text) > 3000:
            message.reply(reply_text[:3000] + "\n... (为保护聊天界面已截断，Agent 将读取完整 Payload)")
        else:
            message.reply(reply_text)
            
        # Give the full text to the Agent payload
        message.payload = {
            "url": url,
            "status_code": response.status_code,
            "markdown_content": cleaned_md[:8000] # Limit to 8000 to prevent context window overflow
        }
        
    except Exception as e:
        message.reply(f"500: nemo: 网页抓取失败: {str(e)}")

