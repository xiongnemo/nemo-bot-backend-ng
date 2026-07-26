from functools import lru_cache
from typing import List
import json
import requests
from bs4 import BeautifulSoup
from bs4 import SoupStrainer

from classes.message import Message

import traceback
import argparse

_command = ["天气", "weather"]
_name = "天气查询"
_man = """查询中国城市天气（数据源：weather.com.cn）。
用法: {0} <城市名>
例如: {0} 北京
例如: {0} hangzhou
"""
_tool_description = (
    "查询中国城市天气（数据源：weather.com.cn）。"
    "参数(query)传入城市名（中文或拼音均可）。"
    "示例: '北京', '上海', 'hangzhou'。"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.2171.95 Safari/537.36",
    "Referer": "http://www.weather.com.cn/",
}

WEATHER_COM_CN_SEARCH_BASE = "https://toy1.weather.com.cn/search"
WEATHER_COM_CN_DINGZHI_BASE = "http://d1.weather.com.cn/dingzhi/{}.html"
WEATHER_COM_CN_WEATHER_BASE = "http://www.weather.com.cn/weather1d/{}.shtml#input"


class WeatherComCnSearchResult:
    def __init__(self, data: List[str]):
        self.data = data
        self.code = data[0]
        self.belong_city = data[1]
        self.chinese_name = data[2]
        self.english_name = data[3]
        self.pinyin_first_letter = data[8]
        self.intro = data[9]

    def __str__(self) -> str:
        return f"""名称: {self.chinese_name} - {self.belong_city}
代码: {self.code}"""


@lru_cache
def search_weather_com_cn_for_cities(query: str) -> List[List[str]]:
    params = {"cityname": query}
    r = requests.get(WEATHER_COM_CN_SEARCH_BASE, params=params, headers=HEADERS)
    print(r.encoding)
    r.encoding = "utf-8"
    json_results = json.loads(r.text.lstrip("(").rstrip(")"))
    if not json_results:
        return []
    return [
        search_result["ref"].split("~")
        if "~" in search_result["ref"]
        else search_result["ref"].split("‾")
        for search_result in json_results
    ]


def get_formatted_weather_by_code(code: str) -> str:
    r = requests.get(WEATHER_COM_CN_DINGZHI_BASE.format(code), headers=HEADERS)
    r.encoding = r.apparent_encoding
    raw_text_list = r.text.split(";var")
    dingzhi, raw_alarm = [
        json.loads(raw_text[raw_text.index("{") :]) for raw_text in raw_text_list
    ]
    print(dingzhi)
    weatherinfo = dingzhi["weatherinfo"]
    print(raw_alarm)
    alarm_list = raw_alarm["w"]
    weatherinfo_formatted = (
        f"""
{weatherinfo["cityname"]}: 
天气: {weatherinfo["weather"]}
夜间温度: {weatherinfo["tempn"]}
日间温度: {weatherinfo["temp"]}
时间: {weatherinfo["fctime"]}"""
        if weatherinfo["cityname"]
        else ""
    )
    alarm_formatted = (
        "\n".join(
            [
                f"""
{alarm["w13"]}
发布于 {alarm["w8"]} 生效于 {alarm["w12"]}
{alarm["w9"]}"""
                for alarm in alarm_list
            ]
        )
        if alarm_list
        else ""
    )
    return f"""{weatherinfo_formatted}
{alarm_formatted}""".strip()


def get_formatted_weather_scraped_by_code(code: str) -> str:
    r = requests.get(WEATHER_COM_CN_WEATHER_BASE.format(code), headers=HEADERS)
    r.encoding = r.apparent_encoding
    for line in r.text.splitlines():
        if "var hour3data={" in line:

            def generate_weather_info(line: List[str]) -> str:
                return f"{line[0]}: {line[2]} {line[3]} {line[4]}: {line[5]}"

            raw = json.loads(line[line.index("{") :])
            result = "\n".join(
                list(map(generate_weather_info, [day.split(",") for day in raw["1d"]]))
            )
            return result
    else:
        only_tags_with_today = SoupStrainer(id="today")
        soup = BeautifulSoup(r.text, "html.parser", parse_only=only_tags_with_today)
        weather_info = soup.select("#today > div.t > ul > li")
        print(weather_info)
        return "如果你看到这个, 帮我叫一下这人写完这代码"


from utilities import generic_exception_handler

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    result = ""
    try:
        args = message.request.args.split()
        list_mode = False
        query = ""
        if args == []:
            query = "杨浦"
        elif len(args) > 0 and args[0] == "列出":
            list_mode = True
            if len(args) == 1:
                query = "上海"
            else:
                query = args[1]
        else:
            query = args[0]
        print(f"query is: {query}")
        cities = [
            WeatherComCnSearchResult(city)
            for city in search_weather_com_cn_for_cities(query)
        ]
        if not cities:
            message.reply("一个也没查到")
            return
        if list_mode:
            message.reply("\n".join([f"{city}" for city in cities]).strip())
            return
        code_to_scrape = cities[0].code
        try:
            result = get_formatted_weather_by_code(code_to_scrape)
        except json.JSONDecodeError:
            # 这个时候没有对应的天气
            result = ""
        result += f"""\n{cities[0].chinese_name} {cities[0].english_name}
{get_formatted_weather_scraped_by_code(code_to_scrape)}"""
    except Exception as e:
        raise e
    if result:
        message.reply(result.strip())
    else:
        message.reply("似乎查不到")
