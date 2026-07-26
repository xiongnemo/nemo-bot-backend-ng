from concurrent.futures import ThreadPoolExecutor
from classes.message import Message

import requests

import traceback
import io

from datetime import datetime, timezone
import random


def utc_to_local(utc_dt: datetime) -> datetime:
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


_command = ["汇率"]
_name = "汇率查询"
_man = """汇率查询实用程序。
用法: {0} <法币交易对> [数量]
例如: {0} usdcny
例如: {0} jpy 5500
* 得到的结果会自动四舍五入到小数点后两位。
"""
_tool_description = (
    "查询外汇汇率（数据源：新浪财经 + Wise）。"
    "参数(query)支持以下格式: "
    "1) 三字母货币代码，默认对CNY，如 'usd', 'jpy', 'eur'; "
    "2) 六字母货币对，如 'usdcny', 'usdjpy', 'eurusd'; "
    "3) 币种后加数量，如 'jpy 5500'（计算5500日元等于多少人民币）。"
    "结果会同时返回新浪汇率和Wise汇率。"
)

hq_sinajs_headers = {"User-Agent": "curl/7.58.0", "Referer": "https://gu.sina.cn/"}

DEFAULT = "USDCNY"


def normalize_curr(curr_type_: str) -> str:
    try:
        curr = curr_type_.split()[0].upper()
        if len(curr) == 3:
            return curr.upper() + "CNY"
        elif len(curr) == 6:
            return curr
        else:
            return DEFAULT.upper()
    except:
        return DEFAULT.upper()


def currencies_sina(curr_type_: str) -> str:
    fake_file = io.StringIO()
    curr_type = curr_type_.lower() if curr_type_ else DEFAULT.lower()
    temp = curr_type.split(" ")
    multiply_flag = False
    if len(temp) == 2:
        curr_type = temp[0]
        multiply_flag = True
        try:
            multiply_ = float(temp[1])
        except ValueError:
            return "请确定你想转换的是一个数字。"
        if multiply_ < 0:
            return "您好有钱啊"
    if len(curr_type) == 3:
        curr_type += "cny"
    rate_r = requests.get(
        "http://w.sinajs.cn/?list=fx_s" + curr_type, headers=hq_sinajs_headers
    )
    print(rate_r.text)
    rate_raw = rate_r.text.lstrip("var hq_str_fx_s" + curr_type + '="')[:-3]
    rate_result = rate_raw.split(",")
    try:
        rate_current_rate = float(rate_result[5])
    except IndexError:
        return "请确定你输入的法币交易对存在, 正确且合法。"
    rate_chn_representation = rate_result[9]
    rate_update_date = rate_result[17]
    rate_update_time = rate_result[0]
    real_time = f"{rate_update_date}T{rate_update_time}+08:00"
    rate_source_department = rate_result[13]
    if multiply_flag:
        print(
            temp[1]
            + " * "
            + curr_type.upper()
            + " = "
            + str(round(rate_current_rate * multiply_, 2)),
            file=fake_file,
        )
    else:
        print(
            curr_type.upper()
            + f"({rate_chn_representation})"
            + ": "
            + str(rate_current_rate),
            file=fake_file,
        )
    print(
        "汇率报价时间: "
        + datetime.fromisoformat(real_time).strftime("%Y-%m-%d %H:%M:%S %Z (%z)"),
        file=fake_file,
    )
    print("汇率报价来源: " + rate_source_department, file=fake_file)
    return fake_file.getvalue()[:-1]


def currencies_wise(curr: str) -> str:
    if not curr:
        curr = DEFAULT.lower()
    tmp = curr.upper().split()
    multiply_flag = False
    if len(tmp) == 2:
        curr_type = tmp[0]
        multiply_flag = True
        try:
            multiply_ = float(tmp[1])
        except ValueError:
            return "请确定你想转换的是一个数字。"
        if multiply_ < 0:
            return "您好有钱啊"
    elif len(tmp) == 1:
        curr_type = tmp[0]
        multiply_flag = False
    if len(curr_type) == 3:
        target = "CNY"
        source = curr_type
    elif len(curr_type) == 6:
        target = curr_type[3:]
        source = curr_type[:3]
    else:
        return "400: nemo: symbol 长度有误。"
    if "CNH" in target or "CNH" in source:
        return "412: nemo: Wise 没有所谓的 CNH。"
    param = {"source": source, "target": target}
    header = {"Authorization": "Bearer 6831a537-d985-456f-bfaf-b6ce7214d550"}
    r = requests.get(
        "https://api.wise-sandbox.com/v1/rates", params=param, headers=header
    )
    # [{"rate":158.345,"source":"USD","target":"JPY","time":"2024-04-27T03:29:49+0000"}]
    if r.status_code != 200:
        print(r.text)
        return f"502: nemo: 请求失败({r.status_code})。"
    data = r.json()
    rate = data[0]["rate"]
    time = data[0]["time"]
    result = f"{source}{target}: {rate}"
    if multiply_flag:
        result += f"\n{multiply_} * {source}{target} = {round(rate * multiply_, 2)}"
    result += f"\n更新时间: {utc_to_local(datetime.fromisoformat(time)).strftime('%Y-%m-%d %H:%M:%S %Z (%z)')}"
    # result += f"\n==\n破坏性改变！我们正在从新浪迁移至 TransferWise API。\n您毋须担心，现有参数和传参方式不会受到影响。"
    return result


from utilities import generic_exception_handler

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    try:
        result = ""
        try:
            args = message.request.args
            # create two threads to get the result
            executor = ThreadPoolExecutor(max_workers=3)

            # get the result from the first thread
            future_normal = executor.submit(normalize_curr, args)
            future_sina = executor.submit(currencies_sina, args)
            future_wise = executor.submit(currencies_wise, args)
            result = "新浪汇率\n"
            try:
                result += future_sina.result()
            except:
                traceback.print_exc()
                result += "新浪汇率查询失败。\n"
            result += "\n==\nWise 汇率\n"
            try:
                result += future_wise.result()
            except:
                traceback.print_exc()
                result += "Wise 汇率查询失败。\n"

        except Exception as e:
            raise e
        message.reply(result)
        future_normal_result = future_normal.result()
        if future_normal_result == "USDCNY":
            message.reply(
                f"{future_normal_result} 近期状况：",
                photo_url=f"https://image.sinajs.cn/newchart/futures/forex/min30_hollow/{future_normal_result}.gif?{random.randint(0, 999999)}",
            )
        # message.reply("四小时", photo_url=f'https://image.sinajs.cn/newchart/v5/forex/min_m/{future_normal.result()}.gif?1720165573684')
    except:
        traceback.print_exc()


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
