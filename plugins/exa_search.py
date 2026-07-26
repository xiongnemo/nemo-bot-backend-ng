import os
import json
import asyncio
import traceback
from core.message import Message
from utilities import generic_exception_handler

_command = ["exa", "搜索", "exa搜索"]
_name = "Exa智能搜索"
_man = """使用 Exa.ai MCP 进行语义智能搜索。
用法: {0} <搜索词>
例如: {0} python 最新特性
"""
_tool_description = (
    "使用 Exa.ai MCP 进行基于语义的互联网搜索。非常适合长句问题、查找博客、论文或特定领域知识。"
    "参数(query)传入你需要搜索的自然语言问题或关键词。"
    "返回搜索到的网页标题、URL 以及关键内容摘要(Highlights)。"
)
_enabled = 1

EXA_MCP_URL = "https://mcp.exa.ai/mcp"

async def _mcp_search(query: str, num_results: int = 3) -> str:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    
    async with streamablehttp_client(url=EXA_MCP_URL, timeout=60, terminate_on_close=False) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            result = await session.call_tool("web_search_exa", arguments={
                "query": query,
                "numResults": num_results,
            })
            
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        message.reply("请提供搜索关键词，例如：exa搜索 python最新特性")
        return

    try:
        raw_result = asyncio.run(_mcp_search(query, num_results=3))
        # Exa MCP server already returns beautifully formatted markdown text, 
        # so we can directly reply with it.
        formatted = f"【Exa MCP 搜索结果】: {query}\n\n{raw_result[:4000]}"
        message.reply(formatted)
    except Exception as e:
        raise e

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
            if kwargs:
                print(f"[{__name__}] KWARGS:", kwargs)
            self.replies.append(text)
            
    # Mock OS ENV for testing if provided in sys.argv
    args_str = " ".join(sys.argv[1:])
    if not args_str:
        args_str = "Artificial Intelligence breakthroughs 2026"
        
    msg = MockMessage(args_str)
    print(f"Testing with args: '{args_str}'")
    bot_execute(msg, {})
