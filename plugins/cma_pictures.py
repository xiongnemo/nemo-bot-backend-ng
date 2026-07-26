import requests
from bs4 import BeautifulSoup
import traceback
import random

from core.message import Message
from utilities import generic_exception_handler

WEBROOT = "https://weather.cma.cn/"
BASE_URL = "https://weather.cma.cn/web/"

pic_type = {
    "FY4A真彩色": "channel-d3236549863e453aab0ccc4027105bad.html",
    "FY4A红外": "channel-ee6f0049d0bc4846a0396647b5a90cc3.html",
    "FY4A可见光": "channel-24f65d2fb237439d91b6a7fd75a7bfb3.html",
    "FY4A水汽": "channel-37107647b1744dc6b36bb252ca652a63.html",
    "全国降水量预报-24小时预报图": "channel-339.html",
    "全国降水量预报-48小时预报图": "channel-340.html",
    "全国降水量预报-72小时预报图": "channel-341.html",
    "单站雷达-南汇": "channel-145.html",
    "单站雷达-青浦": "channel-146.html",
    "单站雷达-北京": "channel-103.html",
    "单站雷达-天津": "channel-105.html",
    "单站雷达-河北": "channel-107.html",
    "单站雷达-山西": "channel-113.html",
    "单站雷达-内蒙古": "channel-119.html",
    "单站雷达-辽宁": "channel-126.html",
    "单站雷达-吉林": "channel-131.html",
    "单站雷达-黑龙江": "channel-137.html",
    "单站雷达-上海": "channel-145.html",
    "单站雷达-江苏": "channel-148.html",
    "单站雷达-浙江": "channel-157.html",
    "单站雷达-安徽": "channel-166.html",
    "单站雷达-福建": "channel-174.html",
    "单站雷达-江西": "channel-181.html",
    "单站雷达-河南": "channel-193.html",
    "单站雷达-山东": "channel-196.html",
    "单站雷达-湖北": "channel-205.html",
    "单站雷达-湖南": "channel-214.html",
    "单站雷达-广东": "channel-222.html",
    "单站雷达-广西": "channel-233.html",
    "单站雷达-海南": "channel-242.html",
    "单站雷达-四川": "channel-246.html",
    "单站雷达-贵州": "channel-254.html",
    "单站雷达-云南": "channel-262.html",
    "单站雷达-重庆": "channel-270.html",
    "单站雷达-西藏": "channel-275.html",
    "单站雷达-陕西": "channel-280.html",
    "单站雷达-甘肃": "channel-287.html",
    "单站雷达-宁夏": "channel-293.html",
    "单站雷达-青海": "channel-296.html",
    "单站雷达-新疆": "channel-299.html",
    "10厘米土壤相对湿度": "channel-45.html",
    "20厘米土壤相对湿度": "channel-46.html",
    "30厘米土壤相对湿度": "channel-47.html",
    "40厘米土壤相对湿度": "channel-48.html",
    "50厘米土壤相对湿度": "channel-49.html",
    "近10天全国平均气温距平图": "channel-32.html",
    "近20天全国平均气温距平图": "channel-33.html",
    "近30天全国平均气温距平图": "channel-34.html",
    "近10天降水距平百分率": "channel-18.html",
    "近20天降水距平百分率": "channel-19.html",
    "近30天降水距平百分率": "channel-20.html",
}

DEFAULT_PIC = "FY4A真彩色"

_command = ["气象图", "cma_pictures"]
_name = "中国气象局气象图"

_man = f"""由 https://weather.cma.cn/ 提供的气象图。
用法: __placeholder [类型]
例如: __placeholder {DEFAULT_PIC}
目前支持的类型有: 
{", ".join([key for key in pic_type])}"""

_man = _man.replace("__placeholder", "{0}")

_tool_description = f"获取中国气象局的各种气象云图、降水预报、雷达图和温度/湿度图等。输入参数(query)为期望的气象图类型。目前支持的类型有: {', '.join(list(pic_type.keys()))}。如果留空将默认返回 {DEFAULT_PIC}。返回值为获取到的图片URL。返回图片后，大模型通常需要结合 vision_analyze 工具来进行多模态分析。"

def _fetch_with_waf_bypass(url: str):
    import re
    import hashlib
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'})
    r = session.get(url, timeout=15)
    
    match_prefix = re.search(r"var prefix = '(.*?)';//arg1", r.text)
    match_bits = re.search(r"var leading_zero_bit = (\d+);//arg2", r.text)
    
    if match_prefix and match_bits:
        prefix = match_prefix.group(1)
        bits = int(match_bits.group(1))
        cnt = 0
        while True:
            suffix = hex(cnt)[2:]
            hash_val = hashlib.sha1((prefix + suffix).encode('utf-8')).digest()
            bin_str = ''.join(f'{b:08b}' for b in hash_val)
            if bin_str.startswith('0' * bits):
                break
            cnt += 1
        safeline = session.cookies.get('safeline_bot_challenge', '')
        session.cookies.set('safeline_bot_challenge_ans', safeline + suffix)
        r = session.get(url, timeout=15)
    return r

def cma_pictures(arg: str):
    target = DEFAULT_PIC if not arg else arg
    if target not in pic_type:
        raise Exception(f"400: nemo: 未定义的类型。已定义类型如下：\n{', '.join([key for key in pic_type])}")
    
    real_url = f"{BASE_URL}{pic_type[target]}"
    r = _fetch_with_waf_bypass(real_url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    element = soup.select_one("#imgPath")
    if not element:
        raise Exception("500: nemo: 无法从页面解析出图片地址。")
        
    img_src = element["src"]
    if img_src.startswith("http"):
        return img_src
    
    # Also strip leading slash just in case WEBROOT already has a trailing slash
    if img_src.startswith("/"):
        img_src = img_src[1:]
    return f"{WEBROOT}{img_src}"

import time
_last_cma_calls = {}

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    arg = message.request.args.strip()
    img_url = cma_pictures(arg)
    
    user_key = f"{message.group_id}_{message.user_id}_{arg}"
    current_time = time.time()
    
    if user_key in _last_cma_calls and current_time - _last_cma_calls[user_key] < 30:
        # Debounced: return url to agent but do not send the photo again
        message.reply(f"[缓存获取] 图片直链: {img_url}")
    else:
        message.reply(f"图片已获取: {img_url}", photo_url=img_url)
        _last_cma_calls[user_key] = current_time
