import requests
from urllib.parse import quote
from core.message import Message
from utilities import generic_exception_handler

_command = ["yahoo", "雅虎", "美股"]
_name = "雅虎财经"
_man = """使用雅虎财经查询全球股票行情。
支持全球市场（美股、港股、A股、加密货币等）。
用法: {0} <股票名称/代码>
例如: {0} AAPL
例如: {0} 微软
例如: {0} 0700.HK
"""
_tool_description = (
    "雅虎财经股票行情查询工具。支持全球股票市场行情查询。"
    "参数(query)传入你需要搜索的纯股票名称或纯股票代码。"
    "【注意1】传入名称时必须是完整名称（例如传 'Minimax W' 而不是只传 'Minimax'，否则可能搜到无关国家的同名股票）。"
    "【注意2】必须且仅能传入名称或代码其一，绝对不能把名称和代码拼在一起传入（例如不能传 '100.HK MINIMAX'，只能传 '0100.HK' 或 'MINIMAX W'）。"
    "返回最新股票报价、涨跌幅、最高最低价及成交量。"
)
_enabled = 1


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        message.reply("请输入股票名称或代码，例如：yahoo AAPL")
        return

    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. Search for symbol
    search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={quote(query)}"
    r = requests.get(search_url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    quotes = data.get("quotes", [])
    if not quotes:
        message.reply("nemo: 在雅虎财经中未找到该股票。")
        return

    symbol = quotes[0]["symbol"]
    shortname = quotes[0].get("shortname") or quotes[0].get("longname") or symbol

    # 2. Get Quote data
    chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(chart_url, headers=headers, timeout=10)
    r.raise_for_status()
    chart_data = r.json()

    result_array = chart_data.get("chart", {}).get("result")
    if not result_array:
        message.reply("nemo: 无法获取该股票的具体行情。")
        return

    meta = result_array[0]["meta"]
    currency = meta.get("currency", "USD")
    current = meta.get("regularMarketPrice", 0)
    prev_close = meta.get("chartPreviousClose", 0)
    rise = (current - prev_close) / prev_close if prev_close else 0

    high = meta.get("regularMarketDayHigh", 0)
    low = meta.get("regularMarketDayLow", 0)
    vol = meta.get("regularMarketVolume", 0)

    result_text = f"名称: {shortname} ({symbol})\n"
    result_text += f"当前: {current} {currency}\n"
    result_text += f"涨跌幅: {rise * 100:.2f}%\n"
    result_text += f"昨收: {prev_close} {currency}\n"
    result_text += f"最高: {high}\n最低: {low}\n"
    result_text += f"成交量: {vol}"

    message.reply(result_text)


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

    args_str = " ".join(sys.argv[1:])
    if not args_str:
        args_str = "AAPL"

    msg = MockMessage(args_str)
    print(f"Testing with args: '{args_str}'")
    bot_execute(msg, {})
