from classes.message import Message

import traceback

import requests
from bs4 import BeautifulSoup


PREFIX = "ptab"
URL = "https://www.kylc.com/bank/rmbfx.html"
currency_dict = {
    "港币": "HKD",
    "澳门元": "MOP",
    "美元": "USD",
    "欧元": "EUR",
    "新台币": "TWD",
    "新加坡元": "SGD",
    "日元": "JPY",
    "泰国铢": "THB",
    "韩国元": "KRW",
    "英镑": "GBP",
    "加拿大元": "CAD",
    "澳大利亚元": "AUD",
    "瑞士法郎": "CHF",
    "瑞典克朗": "SEK",
    "丹麦克朗": "DKK",
    "挪威克朗": "NOK",
    "新西兰元": "NZD",
    "卢布": "RUB",
    "马来西亚元": "MYR",
    "南非兰特": "ZAR",
}

_command = ["rmbfx", "银行汇率牌价"]
_name = "银行结售汇钞牌价"
_man = f"""数据来源自 https://www.kylc.com/bank/rmbfx.html
用法: __placeholder [币种]
币种是如下之中的一个：
{", ".join([key for key in currency_dict])}"""

_man = _man.replace("__placeholder", "{0}")

_tool_description = (
    "比较各大银行（工行、建行、中行、农行、招行、华夏等）的外汇结售汇牌价，"
    "帮用户找到结汇/购汇的最优银行。"
    "参数(query)传入币种名称（中文），如 '美元', '日元', '欧元', '英镑', '港币', '加元', '澳元' 等。"
    "如不传参，默认查美元。"
)


def workload(args: str) -> str:
    args = args.upper()
    if len(args.split()) == 2:
        pre_target, pre_amount = args.split()
        try:
            pre_amount = round(float(pre_amount), 2)
            assert pre_amount > 0
        except:
            return "401: nemo: 金额必须是正数"
    else:
        pre_target = args
        pre_amount = -1
    if pre_target in currency_dict:
        target = currency_dict[pre_target]
    elif pre_target in currency_dict.values():
        target = pre_target
    else:
        return "401: nemo: 未定义的币种"
    r = requests.get(URL)
    soup = BeautifulSoup(r.text, "html.parser")
    curr = soup.select_one(
        f"body > div.container > form > div:nth-child(5) > div.col-md-9.col-xs-12 > div.tabbable > div > table.table.show_all.show_{target}".lower()
    )
    if curr:
        general = curr
        # print(general)
        result = "\n".join(
            " ".join([col.text.strip() for col in line.select("td")])
            for line in general.select("tr")[:-2]
        )
        try:
            if pre_amount == -1:
                amount = 10000 if target == "JPY" else 100
            else:
                amount = pre_amount
            rate = float(result.split(" ")[-2].split("\xa0")[-1])
            result += (
                f"\nnemo: 购买 {amount} {target} 现钞需要 {round(amount * rate, 2)} CNY"
            )
        except:
            result += "\nnemo: 解析有误，这不应该发生。"
            traceback.print_exc()

        return result
    return "404: nemo: 远端没找到这个币种"


from utilities import generic_exception_handler

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    result = ""
    try:
        args = message.request.args.strip()
        # IF NEED ARGS
        if args == "":
            args = "USD"
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
