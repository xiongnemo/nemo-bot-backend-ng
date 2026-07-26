from core.message import Message
from utilities import generic_exception_handler
from core.md2img import markdown_to_image
from runtime.sender import Sender
import logging

logger = logging.getLogger(__name__)

_name = "Markdown图像渲染"
_command = ["md2img", "render_markdown"]
_man = """
把 Markdown 或带 LaTeX 公式的纯文本渲染成精美的长图发送。
用法: md2img <markdown文本>
"""
_tool_description = (
    "Render Markdown text and LaTeX math into a beautiful image. "
    "Useful for bypassing strict keyword filters, displaying tables, or rendering math equations."
)
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        message.reply("用法: md2img <一段Markdown文本>")
        return

    message.reply("正在为你渲染图像，请稍候...")
    
    try:
        img_url = markdown_to_image(query)
        message.reply("渲染完成！", photo_url=img_url)
        
    except Exception as e:
        logger.error(f"Render failed: {e}")
        message.reply(f"500: nemo: 渲染失败 ({e})")
