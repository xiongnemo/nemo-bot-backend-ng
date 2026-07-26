from classes.message import Message

import traceback

import requests

_command = ["工行外汇"]
_name = "工商银行外汇牌价"
_man = """查询工商银行外汇牌价。
用法: {0} <货币代码>
例如: {0} USD
"""
_tool_description = (
    "查询工商银行外汇牌价。"
    "参数(query)传入三字母ISO货币代码，如 'USD', 'JPY', 'EUR', 'GBP', 'HKD'。"
    "仅支持3字母货币代码。"
)
_enabled = 1


ENDPOINT = "http://papi.icbc.com.cn/exchanges/ns/getLatest"


def workload(args: str) -> str:
    data = requests.get(ENDPOINT).json()["data"]
    tmp_corresponding_data = list(
        tmp_data for tmp_data in data if tmp_data["currencyENName"] == args.upper()
    )
    if not tmp_corresponding_data:
        return "请确定你输入的法币在工行即期外汇牌价列表中。"
    currency = tmp_corresponding_data[0]
    return f"""壹佰{currency["currencyCHName"]} (100 {currency["currencyENName"]})
汇率参考价: {currency["reference"]}
现汇买入价: {currency["foreignBuy"]}
现钞买入价: {currency["cashBuy"]}
现汇卖出价: {currency["foreignSell"]}
现钞卖出价: {currency["cashSell"]}
发布时间: {currency["publishDate"]} {currency["publishTime"]}"""


from utilities import generic_exception_handler

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    result = ""
    try:
        args = message.request.args.strip()
        result = workload(args)
    except Exception as e:
        raise e
    message.reply(result)


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
            print(f"[{__name__}] REPLY:", text)
            if kwargs:
                print(f"[{__name__}] KWARGS:", kwargs)
            self.replies.append(text)
            
    args = " ".join(sys.argv[1:])
    msg = MockMessage(args)
    print(f"Testing with args: '{args}'")
    bot_execute(msg, {})
