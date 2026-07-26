import requests
from urllib.parse import quote
from core.message import Message
from variables.headers import Headers
from utilities import generic_exception_handler

_command = ["sina", "新浪", "股票"]
_name = "新浪股票"
_man = """新浪股票查询实用程序。https://finance.sina.com.cn
支持 A 股、美股、港股、ETF
用法: {0} <股票名称/代码>
例子: {0} 茅台
例子: {0} sh688981
例子: {0} 微软
例子: {0} 0700
"""
_tool_description = (
    "新浪财经股票行情查询工具。支持查询 A股、美股、港股以及 ETF 的最新行情。"
    "参数(query)传入纯股票代码(如 600519, aapl, 00700)或纯名称(如 茅台, 苹果)。"
    "【注意】港股代码必须补齐5位数字（如 00100，不能是 0100），且不需要加 hk 前缀。绝不能把名称和代码拼在一起传入。"
    "返回最新的价格、涨跌幅、成交量等信息，并可能附带走势图。"
)
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip().strip(".")
    if not query:
        message.reply("请输入股票名称或代码。")
        return
        
    headers = Headers.get("default", {}).copy()
    headers["Referer"] = "https://finance.sina.com.cn"
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    # Fetch suggestion
    first_url = f"https://suggest3.sinajs.cn/suggest/type=&key={quote(query)}&name=_"
    r = requests.get(first_url, headers=headers, timeout=5)
    r.encoding = 'gbk'
    
    raw_text = r.text.lstrip('var _="').rstrip('";\n')
    if not raw_text:
        message.reply("nemo: 好像没有结果, 换个名字试试？")
        return
        
    search_results = raw_text.split(";")
    
    # Try to find exact match on index 3 (code) or 4 (name) or just take first
    code_match = [x for x in search_results if query.lower() in (x.split(",")[3].lower(), x.split(",")[4].lower(), x.split(",")[0].lower())]
    if code_match:
        result_str = code_match[0]
    else:
        result_str = search_results[0]
        
    result = result_str.split(",")
    if len(result) < 5:
        message.reply("nemo: 解析股票代码失败。")
        return
        
    stock_type = int(result[1])
    code = result[3]
    
    if stock_type == 41: # US Stock
        code = f"gb_{code.strip('.')}"
    elif stock_type == 31: # HK Stock
        code = f"rt_hk{code.strip('.')}"
    elif stock_type in [22, 23, 24, 25, 26, 201]: # Funds/ETFs (often returned as ofXXXXXX or just sh/sz)
        # Check if it already has sh/sz prefix
        if not (code.startswith('sh') or code.startswith('sz') or code.startswith('rt_') or code.startswith('of') or code.startswith('f_')):
            code = f"f_{code}"

    second_url = f"https://hq.sinajs.cn/etag.php?list={quote(code)}"
    r = requests.get(second_url, headers=headers, timeout=5)
    r.encoding = 'gbk'
    
    quote_text = r.text.lstrip(f'var hq_str_{code}="').rstrip('";\n')
    if not quote_text:
        message.reply("nemo: 获取行情失败，可能是代码不支持。")
        return
        
    quote_detail = quote_text.split(",")
    
    try:
        if stock_type == 41:
            name, current, _, current_time, _, today_open, today_highest, today_lowest, _, _, volume, tendays_average_vol, _, _, _, _, _, _, _, _, _, pre_price, pre_rise_percent, pre_rise, local_time, timestamp_time, yesterday_close, *_ = quote_detail
            today_open, yesterday_close, current = float(today_open), float(yesterday_close), float(current)
            rise = (current - yesterday_close) / yesterday_close if yesterday_close else 0
            
            result_text = f"名称: {name}\n今开: {today_open:.2f}\n昨收: {yesterday_close:.2f}\n当前: {current:.2f}\n"
            result_text += f"涨跌幅: {rise * 100:.2f}%\n最高: {float(today_highest):.2f}\n最低: {float(today_lowest):.2f}\n"
            result_text += f"盘前价格: {float(pre_price):.2f} ({float(pre_rise_percent):.2f}%)\n"
            result_text += f"成交量: {volume}\n十日均量: {tendays_average_vol}\n时间: {local_time}"
            message.reply(result_text)
            
        elif stock_type == 31:
            # HK Stock rt_hk...
            name = quote_detail[1]
            today_open = float(quote_detail[2])
            yesterday_close = float(quote_detail[3])
            today_highest = float(quote_detail[4])
            today_lowest = float(quote_detail[5])
            current = float(quote_detail[6])
            rise = (current - yesterday_close) / yesterday_close if yesterday_close else 0
            timestamp_date = quote_detail[17]
            timestamp_time = quote_detail[18]
            
            result_text = f"名称: {name}\n今开: {today_open:.2f}\n昨收: {yesterday_close:.2f}\n当前: {current:.2f}\n"
            result_text += f"涨跌幅: {rise * 100:.2f}%\n最高: {today_highest:.2f}\n最低: {today_lowest:.2f}\n"
            result_text += f"时间: {timestamp_date} {timestamp_time}"
            message.reply(result_text)
            
        else:
            # A Share / ETF / etc
            name = quote_detail[0]
            today_open = float(quote_detail[1])
            yesterday_close = float(quote_detail[2])
            current = float(quote_detail[3])
            rise = (current - yesterday_close) / yesterday_close if yesterday_close else 0
            today_highest = float(quote_detail[4])
            today_lowest = float(quote_detail[5])
            volume = quote_detail[8]
            turnover = quote_detail[9]
            # timestamp might not exist for some funds
            timestamp_date = quote_detail[30] if len(quote_detail) > 30 else ""
            timestamp_time = quote_detail[31] if len(quote_detail) > 31 else ""
            
            result_text = f"名称: {name}\n今开: {today_open:.2f}\n昨收: {yesterday_close:.2f}\n当前: {current:.2f}\n"
            result_text += f"涨跌幅: {rise * 100:.2f}%\n最高: {today_highest:.2f}\n最低: {today_lowest:.2f}\n"
            result_text += f"成交量: {volume}\n成交额: {turnover}\n时间: {timestamp_date} {timestamp_time}".strip()
            message.reply(result_text)
            
    except IndexError:
        message.reply(f"nemo: 解析行情数据时越界，可能不支持该类型数据。原始数据：{quote_text[:50]}...")
        return
    except ValueError:
        message.reply(f"nemo: 解析数值失败。原始数据：{quote_text[:50]}...")
        return

    # Send chart if it's not a fund (fund charts are different/not always available)
    if stock_type not in [22, 23, 24, 25, 26, 201]:
        import random
        # Determine chart URL based on stock type
        if stock_type == 41:
            chart_code = code.replace("gb_", "")
            url_daily = f"https://image.sinajs.cn/newchart/usstock/daily/{chart_code}.gif?_={random.random()}"
        elif stock_type == 31:
            chart_code = code.replace("rt_hk", "")
            url_daily = f"https://image.sinajs.cn/newchart/hk_stock/daily/{chart_code}.gif?_={random.random()}"
        else:
            chart_code = code
            url_daily = f"https://image.sinajs.cn/newchart/daily/n/{chart_code}.gif?_={random.random()}"
            
        message.reply(photo_url=url_daily)
