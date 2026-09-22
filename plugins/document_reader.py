"""
plugins/document_reader.py — Document reader plugin for PDF, Word (.docx), and text files.
Enforces strict Superuser-only permissions for safety.
"""

from __future__ import annotations

import os
import logging
from core.message import Message
from utilities import generic_exception_handler
from core.document_parser import parse_document
from config import is_superuser

logger = logging.getLogger(__name__)

_name = "文档文件阅读解析器"
_command = ["doc", "read_doc", "read_file", "pdf", "word", "读文档", "读文件"]
_man = """解析并阅读已接收到的 PDF、Word (.docx) 以及纯文本文件内容。
（注意：出于系统安全防护考量，本功能仅限 Bot 超级管理员使用）

用法:
  {0}                    (自动读取当前消息或最近收到的文档)
  {0} <文件ID或文件名>     (读取指定ID或文件名的文档)

示例:
  {0}
  {0} 1
  {0} 会议纪要.docx
  {0} 白皮书.pdf
"""
_man = _man.replace("{0}", _command[0])

_tool_description = (
    "解析并阅读 PDF、Word (.docx) 以及代码/文本文件的全文内容。\n"
    "当你需要阅读、总结、翻译或回答关于用户发送的 Word 文档、PDF 文档或代码文件的问题时，必须调用此工具。\n"
    "安全限制：仅超级管理员可以使用此工具读取非图片类型的文件。"
)
_enabled = 1


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    # 1. Strict Security / Permission Check
    if not is_superuser(message.frontend, message.context.user_id):
        message.reply("403: nemo: 由于安全风险，非管理员无法处理未知文件（如 Word、PDF 等），需要让超级管理员来。")
        return

    from runtime import context as rt_context
    fstore = getattr(rt_context, "file_store", None)
    if not fstore:
        try:
            from store.database import Database
            from store.file_store import FileStore
            fstore = FileStore(Database())
            rt_context.file_store = fstore
        except Exception as fe:
            logger.debug("On-demand FileStore init failed: %s", fe)
            fstore = None

    query = (message.request.args or "").strip()
    target_file = None

    # Strategy A: Attached directly to this message
    current_files = getattr(message.request, "files", [])
    if current_files and not query:
        target_file = current_files[-1]

    # Strategy B: Explicit query (ID or filename)
    if not target_file and query:
        target_file = fstore.find_file(
            query,
            group_id=message.context.group_id,
            user_id=message.context.user_id,
        )

    # Strategy C: Quoted reply message
    if not target_file and message.request.reply_to:
        reply_id = str(message.request.reply_to.get("message_id", ""))
        reply_files = fstore.get_files_by_message(reply_id)
        if reply_files:
            target_file = reply_files[-1]

    # Strategy D: Most recent file in this scope (within 24 hours)
    if not target_file:
        recent = fstore.get_recent_files(
            frontend=message.frontend,
            group_id=message.context.group_id,
            user_id=message.context.user_id if not message.context.group_id else "",
            limit=1,
            max_age_seconds=86400.0,
        )
        if recent:
            target_file = recent[0]

    logger.info(
        "[DocReader] Superuser %s invoked doc reader in %s (query: %r)",
        message.context.user_id, message.context.group_id or "DM", query
    )

    if not target_file:
        logger.warning("[DocReader] Target file not found for query %r", query)
        message.reply("404: nemo: 未找到可供解析的文档文件。请直接发送文件、引用带文件的消息，或指定文件名/ID。")
        return

    local_path = target_file.get("local_path", "")
    file_name = target_file.get("file_name", "未知文件")

    if not local_path or not os.path.exists(local_path):
        if fstore and hasattr(fstore, "ensure_local_file"):
            local_path = fstore.ensure_local_file(target_file)
            file_name = target_file.get("file_name", file_name)

    if not local_path or not os.path.exists(local_path):
        logger.warning("[DocReader] File '%s' not present on disk", file_name)
        message.reply(f"404: nemo: 文件 '{file_name}' 在服务器本地不存在或尚未完成下载。")
        return

    # Parse the document
    result = parse_document(local_path, max_pages=30)
    if not result.get("ok"):
        error_msg = result.get("error", "解析失败")
        logger.warning("[DocReader] Parse failure for '%s': %s", file_name, error_msg)
        message.reply(f"500: nemo: {error_msg}")
        return

    doc_type = result.get("type", "").upper()
    title = result.get("title", file_name)
    content = result.get("content", "").strip()
    logger.info(
        "[DocReader] Successfully parsed '%s' (%s, %d/%d pages, %d chars)",
        file_name, doc_type, result.get("read_pages", 1), result.get("page_count", 1), len(content)
    )

    header = f"📄 【文档解析: {title}】 ({doc_type})\n"
    if doc_type == "PDF":
        header += f"页数: {result.get('read_pages')}/{result.get('page_count')} 页\n"
        if result.get("is_scanned"):
            header += "⚠️ 提示: 检测到该 PDF 疑似扫描件/纯图片版，提取到的文本较少。\n"
    elif doc_type == "DOCX":
        header += f"段落: {result.get('paragraphs_count')} | 表格: {result.get('tables_count')}\n"

    header += "═" * 30 + "\n\n"

    MAX_PREVIEW_CHARS = 1500
    if len(content) > MAX_PREVIEW_CHARS:
        preview = content[:MAX_PREVIEW_CHARS].rstrip()
        output = (
            f"{header}{preview}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 【内容已截断】全文共 {len(content):,} 字符（为避免刷屏，仅预览前 {MAX_PREVIEW_CHARS} 字）。\n"
            f"💡 提示: 如需对全文进行深度总结、翻译或问答，请直接 @bot 询问（例如：“@bot 总结一下刚才的文档”）。"
        )
    else:
        output = header + content

    message.reply(output)
