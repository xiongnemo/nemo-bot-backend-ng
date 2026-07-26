from classes.message import Message
from utilities import generic_exception_handler

import traceback

import requests

# _allowed_groups = ['485541033'] # uncomment to set allowed groups, superusers will always be allowed
# _allowed_users = ['1234567890'] # uncomment to set allowed users, superusers will always be allowed
# _disallowed_users = ['1234567890'] # uncomment to set disallowed users, superusers will always be allowed
# _disallowed_groups = ['485541033'] # uncomment to set disallowed groups, superusers will always be allowed

_command = ["U"]
_name = "C2C USDT 价格查询（Gate.IO）"
_man = """查询当前 C2C USDT 价格。
用法: {0}
"""
_tool_description = (
    "查询当前 USDT 场外 C2C 价格（数据源：Gate.IO）。"
    "返回人民币买入价和卖出价。无需传参，参数(query)可留空。"
)


# {
#     "result": true,
#     "appraised_rates": {
#         "buy_rate": "7.32",
#         "sell_rate": "7.36",
#         "max_rate": "8.11",
#         "min_rate": "6.71",
#         "rate_24h_ago": "7.40",
#         "reference_price": "7.34"
#     }
# }

cookies = {
    'lang': 'en',
    '_dx_uzZo5y': 'de90bfcef3b728ca6b754bd0b7186755296a1280104bb3a21a63de4c4a5d7429f6e8c0a9',
    'finger_print': '69687a9d2TUcZslpDZHrDDSIaWakUeNz9qOe6us1',
    'lasturl': '%2Fp2p',
    'login_notice_check': '%2F',
    'defaultP2PFiat': 'CNY',
}

headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9',
    'cache-control': 'no-cache',
    'content-type': 'application/x-www-form-urlencoded',
    'csrftoken': '1',
    'dnt': '1',
    'origin': 'https://www.gate.com',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'referer': 'https://www.gate.com/p2p/buy/CNY-USDT',
    'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    'x-page-host': 'www.gate.com',
    # 'cookie': 'lang=en; _dx_uzZo5y=de90bfcef3b728ca6b754bd0b7186755296a1280104bb3a21a63de4c4a5d7429f6e8c0a9; finger_print=69687a9d2TUcZslpDZHrDDSIaWakUeNz9qOe6us1; lasturl=%2Fp2p; login_notice_check=%2F; defaultP2PFiat=CNY',
}

data = {
    'type': 'push_order_list',
    'asset_pair': 'USDT_CNY',
    'big_trade': '0',
    'fiat_amount': '',
    'amount': '',
    'pay_type': '',
    'is_blue': '0',
    'is_crown': '0',
    'is_shield': '0',
    'is_follow': '0',
    'have_traded': '0',
    'no_query_hide': '0',
    'remove_limit': '1',
    'per_page': '20',
    'push_type': 'sell',
    'sort_type': '1',
    'page': '1',
}


def workload(args: str) -> str:
    import os
    os.environ["http_proxy"] = "http://127.0.0.1:11085"
    os.environ["https_proxy"] = "http://127.0.0.1:11085"
    response = requests.post('https://www.gate.com/api/web/v1/c2c/advertisements', cookies=cookies, headers=headers, data=data)
    data['push_type'] = 'buy'
    response_sell = requests.post('https://www.gate.com/api/web/v1/c2c/advertisements', cookies=cookies, headers=headers, data=data)
    response_sell_json = response_sell.json()
    response_json = response.json()
    if response_json["data"]["lists"]:
        buy_rate = min(response_json["data"]["lists"], key=lambda x: float(x["rate"]))["rate"]  # lowest sell price
        # result = f"当前 C2C USDT 价格（CNY）：\n买入价：{buy_rate}\n卖出价：{sell_rate}\n最高价：{max_rate}\n最低价：{min_rate}\n24 小时前价格：{rate_24h_ago}\n参考价格：{reference_price}"
        result = f"当前 Gate C2C USDT 市场（CNY）：\n可能的最低买入价：{buy_rate}\n"
        if args != "" and args.isnumeric():
            tmp = float('inf')
            amount = float(args)
            for i in response_json["data"]["lists"]:
                current_min_amount = float(i["min_amount"])
                current_max_amount = float(i["max_amount"])
                if current_min_amount <= amount <= current_max_amount:
                    current_rate = float(i["rate"])
                    if amount * current_rate < tmp:
                        tmp = amount * current_rate
            result += f"nemo: 购买 {args} USDT 在当前市场中最少需花费 {tmp} CNY。\n"
    else:
        return "查询失败，请稍后再试。"
    if response_sell_json["data"]["lists"]:
        sell_rate = max(response_sell_json["data"]["lists"], key=lambda x: float(x["rate"]))["rate"]  # highest buy price
        result += f"可能的最高卖出价：{sell_rate}\n"
        if args != "" and args.isnumeric():
            tmp = 0
            amount = float(args)
            for i in response_sell_json["data"]["lists"]:
                current_min_amount = float(i["min_amount"])
                current_max_amount = float(i["max_amount"])
                if current_min_amount <= amount <= current_max_amount:
                    current_rate = float(i["rate"])
                    if amount * current_rate > tmp:
                        tmp = amount * current_rate
            result += f"nemo: 出售 {args} USDT 在当前市场中最多可获得 {tmp} CNY。"
    else:
        return "查询失败，请稍后再试。"
    return result


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    result = workload(args)
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
