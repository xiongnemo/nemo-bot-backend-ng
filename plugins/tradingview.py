"""
TradingView Macro & Crypto Market Trend Analysis Plugin
-------------------------------------------------------
Fetches real-time quotes and historical candlestick data directly from TradingView.
Supports Crypto Market Cap indices (CRYPTOCAP:TOTAL, TOTAL2, BTC.D, USDT.D),
Global Macro Indices (SPX, NDX, DJI, DXY), Commodities (GOLD, OIL), and Crypto Assets.
Computes Vegas tunnel (EMA 12/144/169), MACD, RSI, and renders dark TradingView-style charts.
Supports single-interval deep dive and multi-interval adaptive grid charts.
"""

import os
import re
import sys
import uuid
import json
import random
import string
import time
import logging
import datetime
import concurrent.futures
import threading
from typing import Optional, List, Tuple, Dict, Any

import numpy as np
import pandas as pd
import pandas_ta as ta
import requests
from websocket import create_connection

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'WenQuanYi Micro Hei', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "TradingView 宏观行情与多级别分析"
_command = ["tv", "tradingview", "tv_chart"]
_man = """TradingView 全球宏观、大宗商品、核心股指与加密市值指标多级别走势查询。
用法: tv <标的> [周期列表...]

【支持标的大全 (输入代码或中文均可)】
1. 加密货币宏观市值与市占率 (Crypto Market Cap & Dominance):
   - TOTAL      : 全网加密货币总市值 (独家大盘指数)
   - TOTAL2     : 排除 BTC 后的全市场山寨总市值
   - TOTAL3     : 排除 BTC 和 ETH 后的全市场山寨总市值
   - TOTALDEFI  : DeFi 生态代币总市值
   - BTC.D      : 比特币市值统治率/占比 (判断大饼吸血 vs 山寨季爆发)
   - USDT.D     : USDT 稳定币占有率 (判断场内资金是避险观望还是抄底买入)
   - USDC.D     : USDC 稳定币占有率
   - ETH.D      : 以太坊市值占有率
   - OTHERS     : 中小市值山寨币总市值
   - OTHERS.D   : 中小市值山寨币占比

2. 全球核心股指与恐慌指数 (Global Indices & Volatility):
   - SPX / 标普500 : 标普 500 指数 (美股大盘风向标)
   - NDX / 纳指    : 纳斯达克 100 指数 (科技成长股风向标)
   - DJI / 道指    : 道琼斯工业平均指数
   - RUT / 罗素2000: 美股小盘股指数
   - VIX / 恐慌指数: CBOE 市场波动率与恐慌指数
   - HSI / 恒生指数: 香港恒生指数
   - NI225 / 日经  : 日经 225 指数
   - DAX / 德国DAX : 德国 DAX 40 指数
   - FTSE / 富时100: 英国富时 100 指数

3. 宏观利率与外汇汇率 (Rates, Yields & Forex):
   - DXY / 美元指数: 美元强弱指数 (与风险资产强负相关)
   - US10Y / 美债10年: 美国 10 年期国债收益率 (全球资产定价之锚)
   - US02Y / 美债2年 : 美国 2 年期国债收益率 (对美联储降息/加息最敏感)
   - US30Y / 美债30年: 美国 30 年期长端国债收益率
   - US03M / 美债3月 : 3 个月超短端基准无风险利率
   - USDCNH / 离岸人民币: 美元兑离岸人民币汇率
   - USDJPY / 美日  : 美元兑日元汇率 (套息交易关键指标)
   - EURUSD / 欧美  : 欧元兑美元汇率
   - GBPUSD / 镑美  : 英镑兑美元汇率

4. 大宗商品与避险贵金属 (Commodities & Metals):
   - GOLD / 黄金 / XAUUSD : 现货黄金 (抗通胀与地缘避险核心)
   - SILVER / 白银 / XAGUSD: 现货白银
   - OIL / 原油 / USOIL   : WTI 美国轻质原油期货
   - BRENT / 布伦特原油   : 北海布伦特原油期货
   - NATGAS / 天然气      : 美国天然气期货
   - COPPER / 铜          : COMEX 精铜期货 (全球宏观经济晴雨表)

5. 核心行业与资产 ETF (Sector & Thematic ETFs):
   - QQQ  : 纳斯达克 100 指数 ETF
   - SPY  : 标普 500 指数 ETF
   - TLT  : 20年+ 美国长久期国债 ETF
   - GLD  : SPDR 黄金信托 ETF
   - SMH  : 梵克半导体行业 ETF (芯片景气度风向标)
   - XLE  : 能源精选行业 ETF
   - XLF  : 金融精选行业 ETF
   - ARKK : ARK 创新科技基金 ETF

6. 加密宏观影子股与美股科技龙头 (Crypto Proxies & Mega Tech):
   - MSTR / 微策略: MicroStrategy (高杠杆持仓比特币的代表股票)
   - COIN / Coinbase: 全球合规加密交易所龙头
   - NVDA / 英伟达 : AI 算力与 GPU 核心龙头
   - TSLA / 特斯拉 : 科技与全球风险偏好风向标
   - AAPL / 苹果, MSFT / 微软, GOOGL / 谷歌, AMZN / 亚马逊, META

7. 交易所直接透传 (Direct Formats):
   - BINANCE:ETHBTC (以太坊兑比特币汇率比)
   - BINANCE:SOLBTC (SOL 兑比特币汇率比)
   - CME:BTC1! (CME 芝商所比特币期货主力合约)

【常用指令示例】
  tv TOTAL                 (查看加密全网总市值日线大图)
  tv TOTAL 1h 4h 1d        (多周期并发拉取并生成高清组合拼图)
  tv BTC.D 1d              (查看比特币市占率，判断山寨爆发点)
  tv USDT.D 4h             (查看稳定币占比，判断场内抄底/出逃)
  tv SPX 4h 1d             (美股标普 500 多级别走势)
  tv DXY 1d                (美元指数走势与压制区间)
  tv US10Y 1d              (美债 10 年期收益率)
  tv GOLD 1h 4h            (黄金现货走势)
  tv MSTR 1d               (微策略股票日线走势)
  tv quote TOTAL           (仅查询实时价格与 24h 涨跌幅，不画图)
  tv search 标的名称       (模糊搜索 TradingView 交易所代码)
"""
_tool_description = (
    "获取 TradingView 独家宏观、大宗商品、全球股指与加密市值指标的实时行情与 Vegas 隧道多周期图表。\n"
    "★ 什么时候必须使用此工具(相比于普通交易所行情)：\n"
    "1. 宏观加密大盘与流动性：当需要判断整个加密市场的体量与资金流向时，查询 'TOTAL'(全网总市值)、'TOTAL2'(山寨总市值)、'TOTAL3'；\n"
    "2. 山寨季与大饼统治力：当需要判断行情处于大饼吸血还是山寨季时，查询 'BTC.D'(比特币市占率)、'ETH.D'、'OTHERS.D'；\n"
    "3. 场内观望与抄底情绪：当判断场内资金是否观望或逃亡时，查询 'USDT.D'(USDT稳定币占有率)；\n"
    "4. 宏观大盘与风险偏好：当分析美股联动、避险或宏观环境时，查询 'SPX'(标普500)、'NDX'(纳指)、'VIX'(恐慌指数)、'DXY'(美元指数)、'US10Y'(美债10年收益率)；\n"
    "5. 避险资产与大宗商品：查询 'GOLD'(现货黄金)、'SILVER'(白银)、'OIL'(原油)；\n"
    "6. 加密影子股与美股龙头：查询 'MSTR'(微策略)、'COIN'(Coinbase)、'NVDA'(英伟达)；\n"
    "7. 外汇与汇率：查询 'USDCNH'(离岸人民币)、'USDJPY'(日元)；\n"
    "8. 跨交易所透传代码：支持如 'BINANCE:ETHBTC'、'CME:BTC1!' 等。\n"
    "支持传入标的及周期列表(如 'TOTAL 1h 4h 1d' 或 'BTC.D 1d')，并发拉取并返回高清暗黑多周期拼图与详尽文字支撑压力分析表。"
)
_enabled = 1

STATIC_SYMBOL_ALIASES = {
    # 1. Crypto Market Capitalization & Dominance (CRYPTOCAP)
    "TOTAL": "CRYPTOCAP:TOTAL",
    "加密总市值": "CRYPTOCAP:TOTAL",
    "总市值": "CRYPTOCAP:TOTAL",
    "TOTAL2": "CRYPTOCAP:TOTAL2",
    "山寨总市值": "CRYPTOCAP:TOTAL2",
    "TOTAL3": "CRYPTOCAP:TOTAL3",
    "TOTALDEFI": "CRYPTOCAP:TOTALDEFI",
    "DEFI": "CRYPTOCAP:TOTALDEFI",
    "BTC.D": "CRYPTOCAP:BTC.D",
    "BTCD": "CRYPTOCAP:BTC.D",
    "比特币市占率": "CRYPTOCAP:BTC.D",
    "比特币统治率": "CRYPTOCAP:BTC.D",
    "大饼市占率": "CRYPTOCAP:BTC.D",
    "USDT.D": "CRYPTOCAP:USDT.D",
    "USDTD": "CRYPTOCAP:USDT.D",
    "稳定币占比": "CRYPTOCAP:USDT.D",
    "USDC.D": "CRYPTOCAP:USDC.D",
    "USDCD": "CRYPTOCAP:USDC.D",
    "ETH.D": "CRYPTOCAP:ETH.D",
    "ETHD": "CRYPTOCAP:ETH.D",
    "以太坊市占率": "CRYPTOCAP:ETH.D",
    "OTHERS": "CRYPTOCAP:OTHERS",
    "OTHERS.D": "CRYPTOCAP:OTHERS.D",

    # 2. Major Global Indices & Volatility
    "SPX": "SP:SPX",
    "S&P": "SP:SPX",
    "S&P500": "SP:SPX",
    "标普": "SP:SPX",
    "标普500": "SP:SPX",
    "NDX": "NASDAQ:NDX",
    "NAS100": "NASDAQ:NDX",
    "NASDAQ100": "NASDAQ:NDX",
    "纳指": "NASDAQ:NDX",
    "纳斯达克": "NASDAQ:NDX",
    "纳斯达克100": "NASDAQ:NDX",
    "DJI": "DJ:DJI",
    "DJIA": "DJ:DJI",
    "道琼斯": "DJ:DJI",
    "道指": "DJ:DJI",
    "RUT": "TVC:RUT",
    "RUSSELL2000": "TVC:RUT",
    "罗素2000": "TVC:RUT",
    "VIX": "CBOE:VIX",
    "恐慌指数": "CBOE:VIX",
    "波动率指数": "CBOE:VIX",
    "HSI": "HSI:HSI",
    "恒指": "HSI:HSI",
    "恒生指数": "HSI:HSI",
    "NKY": "TVC:NI225",
    "NI225": "TVC:NI225",
    "日经": "TVC:NI225",
    "日经225": "TVC:NI225",
    "DAX": "XETR:DAX",
    "德国DAX": "XETR:DAX",
    "FTSE": "FTSE:UKX",
    "富时100": "FTSE:UKX",
    "SHCOMP": "SSE:000001",
    "上证指数": "SSE:000001",

    # 3. Yields, Rates & Forex
    "DXY": "TVC:DXY",
    "USDX": "TVC:DXY",
    "美元指数": "TVC:DXY",
    "US10Y": "TVC:US10Y",
    "10Y": "TVC:US10Y",
    "美债10年": "TVC:US10Y",
    "10年美债": "TVC:US10Y",
    "US02Y": "TVC:US02Y",
    "2Y": "TVC:US02Y",
    "美债2年": "TVC:US02Y",
    "2年美债": "TVC:US02Y",
    "US30Y": "TVC:US30Y",
    "30Y": "TVC:US30Y",
    "美债30年": "TVC:US30Y",
    "US03M": "TVC:US03M",
    "3M": "TVC:US03M",
    "美债3月": "TVC:US03M",
    "USDCNH": "FX_IDC:USDCNH",
    "离岸人民币": "FX_IDC:USDCNH",
    "人民币": "FX_IDC:USDCNH",
    "USDJPY": "FX:USDJPY",
    "日元": "FX:USDJPY",
    "美日": "FX:USDJPY",
    "EURUSD": "FX:EURUSD",
    "欧元": "FX:EURUSD",
    "欧美": "FX:EURUSD",
    "GBPUSD": "FX:GBPUSD",
    "英镑": "FX:GBPUSD",
    "镑美": "FX:GBPUSD",
    "AUDUSD": "FX:AUDUSD",
    "澳元": "FX:AUDUSD",

    # 4. Commodities & Metals
    "GOLD": "TVC:GOLD",
    "XAUUSD": "TVC:GOLD",
    "黄金": "TVC:GOLD",
    "现货黄金": "TVC:GOLD",
    "SILVER": "TVC:SILVER",
    "XAGUSD": "TVC:SILVER",
    "白银": "TVC:SILVER",
    "现货白银": "TVC:SILVER",
    "OIL": "TVC:USOIL",
    "USOIL": "TVC:USOIL",
    "WTI": "TVC:USOIL",
    "原油": "TVC:USOIL",
    "美原油": "TVC:USOIL",
    "BRENT": "TVC:UKOIL",
    "UKOIL": "TVC:UKOIL",
    "布伦特原油": "TVC:UKOIL",
    "布油": "TVC:UKOIL",
    "NATGAS": "TVC:NATGAS",
    "天然气": "TVC:NATGAS",
    "COPPER": "COMEX:HG1!",
    "铜": "COMEX:HG1!",
    "美铜": "COMEX:HG1!",

    # 5. Core Sector ETFs
    "QQQ": "NASDAQ:QQQ",
    "SPY": "AMEX:SPY",
    "IWM": "AMEX:IWM",
    "TLT": "NASDAQ:TLT",
    "GLD": "AMEX:GLD",
    "SMH": "NASDAQ:SMH",
    "半导体ETF": "NASDAQ:SMH",
    "SOXX": "NASDAQ:SOXX",
    "XLE": "AMEX:XLE",
    "能源ETF": "AMEX:XLE",
    "XLF": "AMEX:XLF",
    "金融ETF": "AMEX:XLF",
    "ARKK": "AMEX:ARKK",
    "木头姐": "AMEX:ARKK",

    # 6. Crypto Proxies & Mega Tech
    "MSTR": "NASDAQ:MSTR",
    "微策略": "NASDAQ:MSTR",
    "COIN": "NASDAQ:COIN",
    "COINBASE": "NASDAQ:COIN",
    "NVDA": "NASDAQ:NVDA",
    "英伟达": "NASDAQ:NVDA",
    "TSLA": "NASDAQ:TSLA",
    "特斯拉": "NASDAQ:TSLA",
    "AAPL": "NASDAQ:AAPL",
    "苹果": "NASDAQ:AAPL",
    "MSFT": "NASDAQ:MSFT",
    "微软": "NASDAQ:MSFT",
    "GOOGL": "NASDAQ:GOOGL",
    "GOOG": "NASDAQ:GOOGL",
    "谷歌": "NASDAQ:GOOGL",
    "AMZN": "NASDAQ:AMZN",
    "亚马逊": "NASDAQ:AMZN",
    "META": "NASDAQ:META",

    # 7. Crypto Crosses
    "ETHBTC": "BINANCE:ETHBTC",
    "SOLBTC": "BINANCE:SOLBTC",
}

INTERVAL_MAP = {
    "1M": "1", "1分": "1", "1分钟": "1",
    "3M": "3", "3分": "3", "3分钟": "3",
    "5M": "5", "5分": "5", "5分钟": "5",
    "15M": "15", "15分": "15", "15分钟": "15",
    "30M": "30", "30分": "30", "30分钟": "30",
    "45M": "45", "45分": "45",
    "1H": "60", "60M": "60", "1时": "60", "1小时": "60", "60分": "60",
    "2H": "120", "2小时": "120",
    "3H": "180", "3小时": "180",
    "4H": "240", "4小时": "240", "4时": "240",
    "1D": "1D", "D": "1D", "日": "1D", "日线": "1D", "日K": "1D", "天": "1D",
    "1W": "1W", "W": "1W", "周": "1W", "周线": "1W", "周K": "1W",
    "1MON": "1M", "MON": "1M", "月": "1M", "月线": "1M", "月K": "1M",
}

ALL_INTERVALS_AGENT = ["1h", "4h", "1d"]


def search_tradingview_symbol(query: str) -> Optional[str]:
    """Search TradingView symbol search API v3."""
    clean_query = query.strip()
    url = f"https://symbol-search.tradingview.com/symbol_search/v3/?text={clean_query}&hl=1&lang=en&search_type=undefined&domain=production"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            data = r.json()
            symbols = data.get("symbols", [])
            if symbols:
                top = symbols[0]
                raw_sym = top.get("symbol", "").replace("<em>", "").replace("</em>", "")
                exch = top.get("exchange", "")
                if exch and raw_sym:
                    return f"{exch}:{raw_sym}"
                return raw_sym
    except Exception as e:
        logger.warning(f"TradingView symbol search failed for query '{query}': {e}")
    return None


def resolve_symbol(raw_input: str) -> str:
    """Resolve input symbol to a fully qualified TradingView symbol (e.g. 'EXCHANGE:SYMBOL')."""
    s = raw_input.strip()
    s_upper = s.upper()

    if s_upper in STATIC_SYMBOL_ALIASES:
        return STATIC_SYMBOL_ALIASES[s_upper]

    if ":" in s:
        return s

    if s_upper.endswith("USDT") or s_upper.endswith("BUSD") or s_upper.endswith("USDC"):
        return f"BINANCE:{s_upper}"

    search_res = search_tradingview_symbol(s)
    if search_res:
        return search_res

    return s_upper


def normalize_interval(iv_input: str) -> str:
    """Map human interval strings to TradingView interval tokens."""
    clean = iv_input.strip().upper()
    return INTERVAL_MAP.get(clean, clean)


# Limit concurrent WebSocket handshakes to TradingView to prevent 429 Too Many Requests
_TV_SEMAPHORE = threading.Semaphore(2)


class TradingViewClient:
    """WebSocket client to fetch real-time quotes and historical candlestick data directly from TradingView."""
    WS_URL = "wss://data.tradingview.com/socket.io/websocket"
    HEADERS = {"Origin": "https://data.tradingview.com"}

    @staticmethod
    def _generate_session_id(prefix: str = "cs_") -> str:
        letters = string.ascii_lowercase
        return prefix + "".join(random.choice(letters) for _ in range(12))

    @staticmethod
    def _prepend_header(msg: str) -> str:
        return f"~m~{len(msg)}~m~{msg}"

    @classmethod
    def _construct_message(cls, func: str, params: list) -> str:
        return cls._prepend_header(json.dumps({"m": func, "p": params}, separators=(",", ":")))

    @staticmethod
    def _parse_packets(raw_text: str) -> list[str]:
        packets = []
        idx = 0
        pattern = re.compile(r"~m~(\d+)~m~")
        while idx < len(raw_text):
            m = pattern.match(raw_text, idx)
            if not m:
                break
            header_len = len(m.group(0))
            content_len = int(m.group(1))
            start = idx + header_len
            end = start + content_len
            packets.append(raw_text[start:end])
            idx = end
        return packets

    def _fetch_klines_once(
        self,
        resolved_sym: str,
        tv_iv: str,
        interval: str,
        n_bars: int = 300,
        timeout: float = 12.0
    ) -> pd.DataFrame:
        chart_session = self._generate_session_id("cs_")
        ws = create_connection(self.WS_URL, header=self.HEADERS, timeout=timeout)

        try:
            ws.send(self._construct_message("set_auth_token", ["unauthorized_user_token"]))
            ws.send(self._construct_message("chart_create_session", [chart_session, ""]))

            symbol_spec = json.dumps({
                "symbol": resolved_sym,
                "adjustment": "splits",
                "session": "regular"
            }, separators=(",", ":"))

            ws.send(self._construct_message("resolve_symbol", [
                chart_session, "symbol_1", f"={symbol_spec}"
            ]))
            ws.send(self._construct_message("create_series", [
                chart_session, "s1", "s1", "symbol_1", tv_iv, n_bars
            ]))
            ws.send(self._construct_message("switch_timezone", [chart_session, "exchange"]))

            series_bars = None
            start_time = time.time()

            while time.time() - start_time < timeout:
                msg = ws.recv()
                if not msg:
                    continue

                packets = self._parse_packets(msg)
                if not packets:
                    packets = [msg]

                for pkt in packets:
                    if pkt.startswith("~h~"):
                        ws.send(self._prepend_header(pkt))
                        continue

                    try:
                        data = json.loads(pkt)
                    except Exception:
                        continue

                    m_type = data.get("m")
                    p_payload = data.get("p", [])

                    if m_type == "timescale_update":
                        for p in p_payload:
                            if isinstance(p, dict) and "s1" in p:
                                s1_obj = p["s1"]
                                if "s" in s1_obj:
                                    series_bars = s1_obj["s"]

                    elif m_type == "series_completed":
                        break
                    elif m_type == "symbol_error":
                        raise ValueError(f"TradingView 无法解析标的: {resolved_sym} ({p_payload})")
                    elif m_type == "critical_error":
                        raise RuntimeError(f"TradingView 发生错误: {p_payload}")

                if series_bars is not None:
                    if any("series_completed" in p for p in packets):
                        break

            if not series_bars:
                raise ValueError(f"未能从 TradingView 获取到 {resolved_sym} ({interval}) 的有效 K 线数据。")

            rows = []
            for bar in series_bars:
                v = bar.get("v", [])
                if len(v) >= 5:
                    ts = datetime.datetime.fromtimestamp(float(v[0]))
                    o, h, l, c = float(v[1]), float(v[2]), float(v[3]), float(v[4])
                    vol = float(v[5]) if len(v) > 5 else 0.0
                    rows.append({
                        "Open time": ts,
                        "Open": o,
                        "High": h,
                        "Low": l,
                        "Close": c,
                        "Volume": vol
                    })

            df = pd.DataFrame(rows)
            df.set_index("Open time", inplace=True)
            return df

        finally:
            try:
                ws.close()
            except Exception:
                pass

    def fetch_klines(
        self,
        symbol: str,
        interval: str = "1D",
        n_bars: int = 300,
        timeout: float = 12.0,
        max_retries: int = 2
    ) -> pd.DataFrame:
        """Fetch OHLCV candlestick series for a symbol with concurrency limit and 429 backoff retry."""
        resolved_sym = resolve_symbol(symbol)
        tv_iv = normalize_interval(interval)

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                with _TV_SEMAPHORE:
                    time.sleep(random.uniform(0.05, 0.15))
                    return self._fetch_klines_once(resolved_sym, tv_iv, interval, n_bars=n_bars, timeout=timeout)
            except Exception as e:
                err_str = str(e)
                last_err = e
                is_rate_limited = "429" in err_str or "Too Many Requests" in err_str
                is_timeout = "timeout" in err_str.lower() or "timed out" in err_str.lower()
                if attempt < max_retries and (is_rate_limited or is_timeout):
                    backoff = random.uniform(1.0, 2.0) * (attempt + 1)
                    logger.warning(
                        "TradingView klines for %s (%s) failed (%s), retrying in %.2fs (attempt %d/%d)...",
                        resolved_sym, interval, e, backoff, attempt + 1, max_retries
                    )
                    time.sleep(backoff)
                else:
                    raise last_err

    def _fetch_quote_once(self, resolved_sym: str, timeout: float = 8.0) -> dict:
        quote_session = self._generate_session_id("qs_")
        ws = create_connection(self.WS_URL, header=self.HEADERS, timeout=timeout)

        try:
            ws.send(self._construct_message("set_auth_token", ["unauthorized_user_token"]))
            ws.send(self._construct_message("quote_create_session", [quote_session]))
            ws.send(self._construct_message("quote_set_fields", [
                quote_session,
                "lp", "ch", "chp", "volume", "description", "short_name",
                "exchange", "currency_code", "open_price", "high_price",
                "low_price", "prev_close_price"
            ]))
            ws.send(self._construct_message("quote_add_symbols", [quote_session, resolved_sym]))

            start_time = time.time()
            quote_data = None

            while time.time() - start_time < timeout:
                msg = ws.recv()
                if not msg:
                    continue

                packets = self._parse_packets(msg)
                if not packets:
                    packets = [msg]

                for pkt in packets:
                    if pkt.startswith("~h~"):
                        ws.send(self._prepend_header(pkt))
                        continue

                    try:
                        data = json.loads(pkt)
                    except Exception:
                        continue

                    m_type = data.get("m")
                    p_payload = data.get("p", [])

                    if m_type == "qsd" and len(p_payload) > 1:
                        data_dict = p_payload[1]
                        if isinstance(data_dict, dict) and "v" in data_dict:
                            v = data_dict["v"]
                            quote_data = {
                                "symbol": resolved_sym,
                                "short_name": v.get("short_name", resolved_sym),
                                "description": v.get("description", ""),
                                "exchange": v.get("exchange", ""),
                                "currency": v.get("currency_code", "USD"),
                                "price": v.get("lp", 0.0),
                                "change": v.get("ch", 0.0),
                                "change_pct": v.get("chp", 0.0),
                                "volume": v.get("volume", 0.0),
                                "high": v.get("high_price", 0.0),
                                "low": v.get("low_price", 0.0),
                                "prev_close": v.get("prev_close_price", 0.0),
                            }
                    elif m_type == "quote_completed":
                        break
                    elif m_type == "critical_error":
                        raise RuntimeError(f"TradingView Quote 错误: {p_payload}")

                if quote_data and quote_data.get("price") is not None:
                    break

            if not quote_data:
                raise ValueError(f"未能获取 {resolved_sym} 的实时行情。")

            return quote_data

        finally:
            try:
                ws.close()
            except Exception:
                pass

    def fetch_quote(self, symbol: str, timeout: float = 8.0, max_retries: int = 2) -> dict:
        """Fetch real-time ticker quote with concurrency limit and 429 backoff retry."""
        resolved_sym = resolve_symbol(symbol)
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                with _TV_SEMAPHORE:
                    time.sleep(random.uniform(0.05, 0.15))
                    return self._fetch_quote_once(resolved_sym, timeout=timeout)
            except Exception as e:
                err_str = str(e)
                last_err = e
                is_rate_limited = "429" in err_str or "Too Many Requests" in err_str
                is_timeout = "timeout" in err_str.lower() or "timed out" in err_str.lower()
                if attempt < max_retries and (is_rate_limited or is_timeout):
                    backoff = random.uniform(1.0, 2.0) * (attempt + 1)
                    logger.warning(
                        "TradingView quote for %s failed (%s), retrying in %.2fs (attempt %d/%d)...",
                        resolved_sym, e, backoff, attempt + 1, max_retries
                    )
                    time.sleep(backoff)
                else:
                    raise last_err


tv_client = TradingViewClient()


def format_smart_number(val: float, is_percentage: bool = False, currency: str = "$") -> str:
    """Format large monetary values ($T, $B, $M) or percentages."""
    if pd.isna(val) or val is None:
        return "N/A"

    if is_percentage:
        return f"{val:.2f}%"

    abs_val = abs(val)
    prefix = "-" if val < 0 else ""
    curr_prefix = currency if currency in ["$", "¥", "€", "£"] else ""

    if abs_val >= 1e12:
        return f"{prefix}{curr_prefix}{abs_val / 1e12:.3f} T"
    elif abs_val >= 1e9:
        return f"{prefix}{curr_prefix}{abs_val / 1e9:.3f} B"
    elif abs_val >= 1e6:
        return f"{prefix}{curr_prefix}{abs_val / 1e6:.3f} M"
    elif abs_val >= 1e3:
        return f"{prefix}{curr_prefix}{abs_val:,.2f}"
    elif abs_val >= 1.0:
        return f"{prefix}{curr_prefix}{abs_val:.2f}"
    elif abs_val > 0.0:
        return f"{prefix}{curr_prefix}{abs_val:.4f}"
    else:
        return f"{curr_prefix}0.00"


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute EMA12, EMA144, EMA169, Vegas tunnel, MACD, RSI."""
    df_calc = df.copy()

    df_calc.ta.macd(fast=12, slow=26, signal=9, append=True)
    df_calc.ta.ema(length=12, append=True)
    df_calc.ta.ema(length=144, append=True)
    df_calc.ta.ema(length=169, append=True)
    df_calc.ta.rsi(length=14, append=True)

    if 'EMA_12' not in df_calc.columns:
        df_calc['EMA_12'] = df_calc['Close']
    if 'EMA_144' not in df_calc.columns:
        df_calc['EMA_144'] = df_calc['Close']
    if 'EMA_169' not in df_calc.columns:
        df_calc['EMA_169'] = df_calc['Close']

    tunnel_top_series = np.maximum(df_calc['EMA_144'], df_calc['EMA_169'])
    tunnel_bot_series = np.minimum(df_calc['EMA_144'], df_calc['EMA_169'])

    latest = df_calc.iloc[-1]
    close = float(latest['Close'])
    ema12 = float(latest.get('EMA_12', close))
    ema144 = float(latest.get('EMA_144', close))
    ema169 = float(latest.get('EMA_169', close))
    tunnel_top = float(tunnel_top_series.iloc[-1])
    tunnel_bot = float(tunnel_bot_series.iloc[-1])

    if close > tunnel_top:
        status = "多头 (上方)"
        key_type = "支撑"
        key_band = (tunnel_bot, tunnel_top)
        dist_pct = -((close - tunnel_top) / close) * 100.0
    elif close < tunnel_bot:
        status = "空头 (下方)"
        key_type = "压力"
        key_band = (tunnel_bot, tunnel_top)
        dist_pct = ((tunnel_bot - close) / close) * 100.0
    else:
        status = "通道内震荡"
        key_type = "通道"
        key_band = (tunnel_bot, tunnel_top)
        dist_pct = 0.0

    rsi_val = float(latest.get('RSI_14', 50.0)) if not pd.isna(latest.get('RSI_14')) else 50.0
    macd_val = float(latest.get('MACD_12_26_9', 0.0)) if not pd.isna(latest.get('MACD_12_26_9')) else 0.0
    macdh_val = float(latest.get('MACDh_12_26_9', 0.0)) if not pd.isna(latest.get('MACDh_12_26_9')) else 0.0

    return {
        "df": df_calc,
        "close": close,
        "ema12": ema12,
        "ema144": ema144,
        "ema169": ema169,
        "tunnel_top": tunnel_top,
        "tunnel_bot": tunnel_bot,
        "status": status,
        "key_type": key_type,
        "key_band": key_band,
        "dist_pct": dist_pct,
        "rsi": rsi_val,
        "macd": macd_val,
        "macdh": macdh_val,
    }


def draw_single_tv_chart(symbol: str, interval: str, df: pd.DataFrame, info: dict, save_path: str):
    """Render high quality dark-themed single TradingView candlestick chart."""
    df_plot = info["df"].tail(120).copy()
    if df_plot.empty:
        return

    is_pct = "dominance" in symbol.lower() or ".d" in symbol.lower()

    bg_color = "#131722"
    panel_color = "#1e222d"
    text_color = "#d1d4dc"
    grid_color = "#2a2e39"
    up_color = "#089981"
    down_color = "#f23645"
    ema12_color = "#ffeb3b"
    ema144_color = "#2962ff"
    ema169_color = "#00bcd4"

    fig = plt.figure(figsize=(13, 8), facecolor=bg_color)
    gs = fig.add_gridspec(3, 1, height_ratios=[6, 1.8, 1.8], hspace=0.08)

    ax_main = fig.add_subplot(gs[0], facecolor=panel_color)
    ax_vol = fig.add_subplot(gs[1], facecolor=panel_color, sharex=ax_main)
    ax_rsi = fig.add_subplot(gs[2], facecolor=panel_color, sharex=ax_main)

    x_idx = np.arange(len(df_plot))
    opens = df_plot['Open'].values
    highs = df_plot['High'].values
    lows = df_plot['Low'].values
    closes = df_plot['Close'].values
    volumes = df_plot['Volume'].values

    candle_colors = [up_color if c >= o else down_color for o, c in zip(opens, closes)]
    ax_main.vlines(x_idx, lows, highs, color=candle_colors, linewidth=1.2, alpha=0.9)
    body_bottoms = np.minimum(opens, closes)
    body_heights = np.maximum(np.abs(closes - opens), (highs - lows) * 0.005)
    ax_main.bar(x_idx, body_heights, bottom=body_bottoms, color=candle_colors, width=0.65, alpha=0.95)

    if 'EMA_12' in df_plot.columns:
        ax_main.plot(x_idx, df_plot['EMA_12'], color=ema12_color, linewidth=1.2, label="EMA 12 (过滤线)", alpha=0.9)
    if 'EMA_144' in df_plot.columns and 'EMA_169' in df_plot.columns:
        ax_main.plot(x_idx, df_plot['EMA_144'], color=ema144_color, linewidth=1.4, label="EMA 144", alpha=0.85)
        ax_main.plot(x_idx, df_plot['EMA_169'], color=ema169_color, linewidth=1.4, label="EMA 169", alpha=0.85)
        t_top = np.maximum(df_plot['EMA_144'], df_plot['EMA_169'])
        t_bot = np.minimum(df_plot['EMA_144'], df_plot['EMA_169'])
        ax_main.fill_between(x_idx, t_bot, t_top, color=ema144_color, alpha=0.15, label="Vegas 隧道")

    last_close = closes[-1]
    ax_main.axhline(last_close, color="#ffffff", linestyle="--", linewidth=0.9, alpha=0.7)

    def price_formatter(x, pos):
        return format_smart_number(x, is_percentage=is_pct, currency="")
    ax_main.yaxis.set_major_formatter(mticker.FuncFormatter(price_formatter))

    curr_str = format_smart_number(last_close, is_percentage=is_pct)
    title_text = (
        f"{symbol} [{interval.upper()}]  |  最新: {curr_str}  "
        f"|  状态: {info['status']}  |  {info['key_type']}: {format_smart_number(info['tunnel_bot'], is_pct)} ~ {format_smart_number(info['tunnel_top'], is_pct)}"
    )
    ax_main.set_title(title_text, color=text_color, fontsize=12, fontweight="bold", pad=12, loc="left")
    leg = ax_main.legend(loc="upper left", facecolor=bg_color, edgecolor=grid_color, fontsize=9, labelcolor=text_color)
    leg.get_frame().set_alpha(0.8)

    has_vol = np.sum(volumes) > 0
    if has_vol:
        ax_vol.bar(x_idx, volumes, color=candle_colors, width=0.65, alpha=0.6)
        def vol_formatter(x, pos):
            return format_smart_number(x, currency="")
        ax_vol.yaxis.set_major_formatter(mticker.FuncFormatter(vol_formatter))
        ax_vol.set_ylabel("Volume", color=text_color, fontsize=9)
    else:
        ax_vol.text(0.5, 0.5, "Index / No Volume Data", color=text_color, ha="center", va="center", transform=ax_vol.transAxes, fontsize=10)

    if 'RSI_14' in df_plot.columns:
        ax_rsi.plot(x_idx, df_plot['RSI_14'], color="#ab47bc", linewidth=1.3, label="RSI(14)")
        ax_rsi.axhline(70, color=down_color, linestyle=":", alpha=0.6, linewidth=1)
        ax_rsi.axhline(30, color=up_color, linestyle=":", alpha=0.6, linewidth=1)
        ax_rsi.fill_between(x_idx, 30, 70, color="#ab47bc", alpha=0.08)
        ax_rsi.set_ylim(10, 90)
        ax_rsi.set_ylabel("RSI (14)", color=text_color, fontsize=9)
        ax_rsi.text(0.015, 0.90, f"RSI(14): {info['rsi']:.1f}", transform=ax_rsi.transAxes, color=text_color, fontsize=8.5, verticalalignment='top')

    step = max(len(df_plot) // 8, 1)
    tick_indices = x_idx[::step]
    time_series = df_plot.index
    if (time_series[-1] - time_series[0]).days > 30:
        time_labels = [time_series[i].strftime("%m-%d") for i in tick_indices]
    else:
        time_labels = [time_series[i].strftime("%m-%d %H:%M") for i in tick_indices]

    for ax in [ax_main, ax_vol, ax_rsi]:
        ax.set_facecolor(panel_color)
        ax.grid(True, color=grid_color, linestyle="--", linewidth=0.6, alpha=0.7)
        ax.tick_params(colors=text_color, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(grid_color)
        plt.setp(ax.get_xticklabels(), visible=False)

    ax_rsi.set_xticks(tick_indices)
    ax_rsi.set_xticklabels(time_labels, rotation=0, ha="center", color=text_color, fontsize=9)
    ax_rsi.tick_params(labelbottom=True)
    plt.setp(ax_rsi.get_xticklabels(), visible=True)

    try:
        plt.subplots_adjust(top=0.92, bottom=0.10, left=0.08, right=0.95, hspace=0.12)
    except Exception:
        pass
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    plt.savefig(save_path, dpi=130, facecolor=bg_color, edgecolor="none")
    plt.close(fig)


def draw_grid_tv_chart(symbol: str, intervals: list[str], tf_data: dict, save_path: str):
    """Render multi-interval adaptive grid chart (e.g. 1x2, 1x3, 2x2, 3x2)."""
    k = len(intervals)
    if k == 1:
        iv = intervals[0]
        item = tf_data[iv]
        draw_single_tv_chart(symbol, iv, item["df"], item["info"], save_path)
        return

    is_pct = "dominance" in symbol.lower() or ".d" in symbol.lower()

    if k == 2:
        nrows, ncols = 1, 2
        figsize = (16, 6)
    elif k == 3:
        nrows, ncols = 1, 3
        figsize = (20, 6)
    elif k == 4:
        nrows, ncols = 2, 2
        figsize = (16, 11)
    elif k in (5, 6):
        nrows, ncols = 2, 3
        figsize = (20, 11)
    else:
        nrows = (k + 2) // 3
        ncols = 3
        figsize = (20, 5 * nrows)

    bg_color = "#131722"
    panel_color = "#1e222d"
    text_color = "#d1d4dc"
    grid_color = "#2a2e39"
    up_color = "#089981"
    down_color = "#f23645"
    ema12_color = "#ffeb3b"
    ema144_color = "#2962ff"
    ema169_color = "#00bcd4"

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, facecolor=bg_color)
    axes_flat = np.array(axes).flatten()

    def price_formatter(x, pos):
        return format_smart_number(x, is_percentage=is_pct, currency="")

    for i, iv in enumerate(intervals):
        ax = axes_flat[i]
        ax.set_facecolor(panel_color)
        ax.grid(True, color=grid_color, linestyle="--", linewidth=0.6, alpha=0.7)
        ax.tick_params(colors=text_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(grid_color)

        if iv not in tf_data:
            ax.text(0.5, 0.5, f"[{iv.upper()}] 无数据", color=text_color, ha="center", va="center")
            continue

        item = tf_data[iv]
        info = item["info"]
        df_plot = info["df"].tail(100).copy()
        n = len(df_plot)
        x_idx = np.arange(n)

        opens = df_plot['Open'].values
        highs = df_plot['High'].values
        lows = df_plot['Low'].values
        closes = df_plot['Close'].values

        candle_colors = [up_color if c >= o else down_color for o, c in zip(opens, closes)]
        ax.vlines(x_idx, lows, highs, color=candle_colors, linewidth=1.0, alpha=0.85)
        body_bottoms = np.minimum(opens, closes)
        body_heights = np.maximum(np.abs(closes - opens), (highs - lows) * 0.005)
        ax.bar(x_idx, body_heights, bottom=body_bottoms, color=candle_colors, width=0.65, alpha=0.9)

        if 'EMA_12' in df_plot.columns:
            ax.plot(x_idx, df_plot['EMA_12'], color=ema12_color, linewidth=1.0, alpha=0.85)
        if 'EMA_144' in df_plot.columns and 'EMA_169' in df_plot.columns:
            ax.plot(x_idx, df_plot['EMA_144'], color=ema144_color, linewidth=1.2, alpha=0.85)
            ax.plot(x_idx, df_plot['EMA_169'], color=ema169_color, linewidth=1.2, alpha=0.85)
            t_top = np.maximum(df_plot['EMA_144'], df_plot['EMA_169'])
            t_bot = np.minimum(df_plot['EMA_144'], df_plot['EMA_169'])
            ax.fill_between(x_idx, t_bot, t_top, color=ema144_color, alpha=0.15)

        last_c = closes[-1]
        ax.axhline(last_c, color="#ffffff", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(price_formatter))

        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        title_color = up_color if '多头' in info['status'] else (down_color if '空头' in info['status'] else ema12_color)
        c_str = format_smart_number(last_c, is_percentage=is_pct)
        top_str = format_smart_number(info['tunnel_top'], is_percentage=is_pct)
        bot_str = format_smart_number(info['tunnel_bot'], is_percentage=is_pct)

        ax.set_title(
            f"[{iv.upper()}] 现价: {c_str} | 隧道: {bot_str}~{top_str} | {info['status']} ({dist_str})",
            fontsize=9.5, fontweight='bold', color=title_color, pad=8
        )

        step = max(n // 5, 1)
        tick_indices = x_idx[::step]
        time_series = df_plot.index
        if (time_series[-1] - time_series[0]).days > 30:
            time_labels = [time_series[j].strftime("%m/%d") for j in tick_indices]
        else:
            time_labels = [time_series[j].strftime("%m/%d %H:%M") for j in tick_indices]
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(time_labels, rotation=15, ha="right", color=text_color, fontsize=8)

    for j in range(k, len(axes_flat)):
        axes_flat[j].set_visible(False)

    interval_str = " / ".join(iv.upper() for iv in intervals)
    fig.suptitle(
        f"{symbol} TradingView Vegas 隧道动态支撑压力 ({interval_str})",
        fontsize=13, fontweight="bold", color="#ffffff", y=0.99
    )
    plt.subplots_adjust(top=0.92, bottom=0.08, left=0.06, right=0.97, hspace=0.28, wspace=0.18)
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    plt.savefig(save_path, dpi=140, facecolor=bg_color, edgecolor="none")
    plt.close(fig)


def format_tv_report(symbol: str, quote: Optional[dict], intervals: list[str], tf_data: dict) -> str:
    """Format human and agent readable summary report."""
    resolved = resolve_symbol(symbol)
    is_pct = "dominance" in resolved.lower() or ".d" in resolved.lower()

    lines = []
    lines.append(f"📊 TradingView 标的走势: {resolved}")

    if quote:
        p_str = format_smart_number(quote['price'], is_percentage=is_pct)
        chp = quote['change_pct']
        ch_emoji = "🟢" if chp >= 0 else "🔴"
        sign = "+" if chp >= 0 else ""
        lines.append(f"• 最新报价: {p_str} ({ch_emoji} {sign}{chp:.2f}%)")
        if quote.get("description"):
            lines.append(f"• 描述: {quote['description']} ({quote.get('exchange', '')})")

    lines.append("")
    lines.append("【各周期 Vegas 隧道与关键位】")
    for iv in intervals:
        if iv not in tf_data:
            continue
        item = tf_data[iv]
        info = item["info"]
        top_str = format_smart_number(info['tunnel_top'], is_percentage=is_pct)
        bot_str = format_smart_number(info['tunnel_bot'], is_percentage=is_pct)
        c_str = format_smart_number(info['close'], is_percentage=is_pct)
        dist = info['dist_pct']
        dist_str = f"+{dist:.2f}%" if dist > 0 else f"{dist:.2f}%"

        lines.append(
            f"🔹 [{iv.upper()}] {c_str} | {info['status']}\n"
            f"   • Vegas: {bot_str} ~ {top_str} ({info['key_type']}距离: {dist_str})\n"
            f"   • RSI(14): {info['rsi']:.1f} | MACD 柱: {info['macdh']:.2e}"
        )

    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    """
    Main entrypoint for TradingView analysis plugin.
    Compatible with Nemo-bot router and Agent tool registry.
    """
    is_agent = getattr(getattr(message, "request", None), "is_agent", False)
    raw_args = ""
    if hasattr(message, "request") and getattr(message.request, "args", None):
        raw_args = message.request.args.strip()
    else:
        # Strip command tokens from text
        raw_text = message.text.strip()
        tokens_all = [t.strip() for t in re.split(r'[\s,，、;/／]+', raw_text) if t.strip()]
        if tokens_all and tokens_all[0].lower() in [c.lower() for c in _command]:
            raw_args = " ".join(tokens_all[1:]).strip()
        else:
            raw_args = raw_text

    tokens = [t.strip() for t in re.split(r'[\s,，、;/／]+', raw_args) if t.strip()]

    if not tokens:
        symbol = "TOTAL"
        intervals = list(ALL_INTERVALS_AGENT) if is_agent else ["1d"]
    elif tokens[0].lower() == "search":
        query = " ".join(tokens[1:]) if len(tokens) > 1 else "TOTAL"
        matched = search_tradingview_symbol(query)
        if matched:
            message.reply(f"🔍 TradingView 标的搜索: '{query}' -> 最优匹配: `{matched}`")
        else:
            message.reply(f"404: nemo: 未找到与 '{query}' 匹配的 TradingView 标的。")
        return
    elif tokens[0].lower() == "quote":
        symbol = tokens[1] if len(tokens) > 1 else "TOTAL"
        try:
            q = tv_client.fetch_quote(symbol)
            is_pct = "dominance" in q['symbol'].lower() or ".d" in q['symbol'].lower()
            p_str = format_smart_number(q['price'], is_percentage=is_pct)
            chp = q['change_pct']
            sign = "+" if chp >= 0 else ""
            rep = (
                f"📈 TradingView 实时行情: {q['symbol']} ({q.get('description', '')})\n"
                f"• 现价: {p_str}\n"
                f"• 24h 涨跌: {sign}{chp:.2f}%\n"
                f"• 交易所: {q.get('exchange', 'TV')}"
            )
            message.payload = q
            message.reply(rep)
            return
        except Exception as e:
            message.reply(f"500: nemo: 获取 {symbol} 报价失败: {e}")
            return
    else:
        symbol = tokens[0]
        if len(tokens) > 1:
            intervals = [t.lower() for t in tokens[1:]]
        else:
            intervals = list(ALL_INTERVALS_AGENT) if is_agent else ["1d"]

    resolved_sym = resolve_symbol(symbol)
    chart_dir = os.path.join(os.getcwd(), "data", "charts")
    os.makedirs(chart_dir, exist_ok=True)

    # 1. Fetch real-time quote
    quote_data = None
    try:
        quote_data = tv_client.fetch_quote(resolved_sym)
    except Exception as e:
        logger.warning(f"Could not fetch real-time quote for {resolved_sym}: {e}")

    # 2. Concurrently fetch K-lines for requested intervals
    tf_data = {}

    def fetch_single(human_iv):
        tv_iv = normalize_interval(human_iv)
        try:
            df = tv_client.fetch_klines(resolved_sym, interval=tv_iv, n_bars=300)
            if df is None or len(df) < 15:
                return human_iv, None, "数据不足"
            info = compute_indicators(df)
            return human_iv, (df, info), None
        except Exception as e:
            return human_iv, None, str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(intervals), 4)) as executor:
        future_map = {executor.submit(fetch_single, iv): iv for iv in intervals}
        for future in concurrent.futures.as_completed(future_map):
            iv, res_tuple, err = future.result()
            if res_tuple:
                df, info = res_tuple
                tf_data[iv] = {"df": df, "info": info}
            else:
                logger.error(f"Failed to fetch {resolved_sym} {iv}: {err}")

    if not tf_data:
        message.reply(f"500: nemo: 无法从 TradingView 获取标的 `{symbol}` ({resolved_sym}) 的 K 线数据，请检查标的名是否正确。")
        return

    # 3. Draw chart (single or grid)
    clean_sym_name = resolved_sym.replace(':', '_').replace('.', '_')
    chart_filename = f"{clean_sym_name}_{uuid.uuid4().hex[:8]}.png"
    chart_filepath = os.path.join(chart_dir, chart_filename)

    valid_intervals = [iv for iv in intervals if iv in tf_data]
    if len(valid_intervals) == 1:
        iv = valid_intervals[0]
        draw_single_tv_chart(resolved_sym, iv, tf_data[iv]["df"], tf_data[iv]["info"], chart_filepath)
    else:
        draw_grid_tv_chart(resolved_sym, valid_intervals, tf_data, chart_filepath)

    text_report = format_tv_report(symbol, quote_data, valid_intervals, tf_data)

    primary_iv = valid_intervals[0]
    primary_info = tf_data[primary_iv]["info"]

    agent_levels = {}
    for iv in valid_intervals:
        info = tf_data[iv]["info"]
        agent_levels[iv] = {
            "close": info["close"],
            "ema12": info["ema12"],
            "ema144": info["ema144"],
            "ema169": info["ema169"],
            "tunnel": [info["tunnel_bot"], info["tunnel_top"]],
            "status": info["status"],
            "dist_pct": info["dist_pct"],
            "key_type": info["key_type"],
            "rsi": info["rsi"],
            "macd": info["macd"],
            "macdh": info["macdh"]
        }

    message.payload = {
        "symbol": resolved_sym,
        "input_symbol": symbol,
        "quote": quote_data,
        "current_price": primary_info["close"],
        "levels": agent_levels,
        "chart_local_path": os.path.abspath(chart_filepath) if os.path.exists(chart_filepath) else None
    }

    if os.path.exists(chart_filepath):
        message.reply(text_report, photo_url=os.path.abspath(chart_filepath))
    else:
        message.reply(text_report)
