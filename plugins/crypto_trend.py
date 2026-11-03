"""
Crypto Trend & Multi-Timeframe Vegas Tunnel & Hybrid Indicators Plugin
----------------------------------------------------------------------
Fetches K-lines, calculates indicators (Vegas Tunnel, EMA/MA moving averages, BOLL, MACD, RSI),
draws annotated charts, and provides structured payload and rich text reports for users & agents.
Supports single-timeframe, arbitrary custom timeframe lists, full 6-timeframe analysis,
and comprehensive per-user personalization (default symbol, default intervals, custom indicator systems).
"""

import os
import re
import time
import uuid
import json
import logging
import requests
import concurrent.futures
import pandas as pd
import pandas_ta as ta
import numpy as np
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'WenQuanYi Micro Hei', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "加密货币趋势与Vegas多级别分析"
_command = ["vegas", "trend", "crypto_trend", "画线", "隧道", "画线设置", "trend_set", "trend_config"]
_man = """查询加密资产走势图表、Vegas 隧道、经典均线（EMA/MA）与动态支撑/阻力位，支持个性化配置看盘习惯。
用法:
  1. 行情与画线:
     vegas [标的] [周期列表...] [交易所] [指标...]
     示例:
       画线                     (按个人专属偏好画图，默认 ETH 5m Vegas)
       画线 BTC                 (查看 BTC 图表)
       画线 PAXG 4h             (查看 PAXG 4小时图表)
       画线 BTC 5m 15m 30m      (并发拉取并渲染 5m/15m/30m 3合1高清拼图)
       画线 AIN 4h ema 20 ma 200 (单次指定 EMA20 和 MA200 混合均线)
       画线 BTC 1d vegas ma200  (单次指定 Vegas 隧道 + 200日牛熊均线)
       画线 ETH boll            (单次指定布林带 BOLL 20, 2)
       画线 BTC okx             (指定 OKX 交易所)
       画线 ETH hl              (指定 Hyperliquid 交易所)

  2. 个人专属看盘设置 (持久化存储，随设即用):
     画线 设置                  (查看自己当前的专属看盘配置卡片)
     画线 设置 标的 PAXG        (将自己的默认币种设为 PAXG，后续直接发「画线」即画 PAXG)
     画线 设置 周期 4h          (将自己的默认周期设为 4小时，支持多级别如: 周期 1h 4h 1d)
     画线 设置 交易所 okx       (将自己的首选交易所设为 OKX)
     画线 设置 指标 vegas       (切换为 Vegas 隧道系统: EMA12 + 144/169 隧道)
     画线 设置 指标 ema 20 50 100 200 (切换为欧美经典 4 条 EMA 均线体系)
     画线 设置 指标 ma 5 10 20 60 (切换为传统 MA 均线体系)
     画线 设置 指标 ema 12 20 ma 50 200 (自由混搭 EMA 与 MA 均线组)
     画线 设置 指标 vegas ma200 (Vegas 隧道加配 MA200 关键牛熊分界线)
     画线 设置 指标 boll        (切换为布林带 BOLL 20, 2 通道)
     画线 设置 重置             (一键清空个人配置，恢复系统默认)
"""

_tool_description = (
    "获取加密资产(Binance/OKX/Gate/Hyperliquid 现货与合约，按币安->OKX->Gate->Hyperliquid 自动回退)多级别走势图、Vegas 隧道、经典均线(EMA/MA/BOLL)及动态支撑/阻力位分析，并支持为用户管理个性化看盘配置。\n"
    "功能包含：\n"
    "1. 行情与技术分析：当需要查询某币种(如 BTC, ETH, PAXG, SOL, AIN)或进行技术面画线、判断支撑/压力位、均线位置、突破回踩时使用。\n"
    "   - 支持任意周期(如 5m, 15m, 30m, 1h, 4h, 1d)；\n"
    "   - 支持自由指标系统：Vegas 隧道、经典 EMA 均线(如 20 50 100 200)、MA 均线、EMA/MA 混合均线(如 ema 20 ma 200)、Vegas+MA200、布林带(boll)；\n"
    "   - 默认并发拉取多级别并生成高清图表与支撑压力点位数据。\n"
    "2. 专属看盘偏好设置：当用户要求更改其默认看盘配置(如“帮我把默认画线改成 PAXG 4小时”、“把我的均线改成 20 50 200”、“恢复默认画线”等)时：\n"
    "   - 传入 query='设置 标的 PAXG 周期 4h'\n"
    "   - 传入 query='设置 指标 ema 20 50 200'\n"
    "   - 传入 query='设置 重置'\n"
    "   系统会自动完成用户专属配置持久化存储。"
)
_enabled = 1

VALID_INTERVALS = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]
ALL_INTERVALS = ["5m", "15m", "30m", "1h", "4h", "1d"]

INTERVAL_ALIASES = {
    "5M": "5m", "5分": "5m", "5分钟": "5m",
    "15M": "15m", "15分": "15m", "15分钟": "15m",
    "30M": "30m", "30分": "30m", "30分钟": "30m",
    "1H": "1h", "1时": "1h", "1小时": "1h", "60M": "1h", "60分": "1h",
    "4H": "4h", "4时": "4h", "4小时": "4h",
    "1D": "1d", "日线": "1d", "日K": "1d", "日": "1d", "1天": "1d", "天": "1d",
    "1W": "1w", "周线": "1w", "周K": "1w", "周": "1w",
}

EXCHANGE_ALIASES = {
    "BINANCE": "binance", "BN": "binance", "币安": "binance",
    "OKX": "okx", "OK": "okx", "欧易": "okx",
    "GATE": "gate", "GATEIO": "gate", "芝麻": "gate",
    "HL": "hyperliquid", "HYPERLIQUID": "hyperliquid",
}

ALL_FLAGS = {"ALL", "全", "全部", "全网", "-A", "--ALL"}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

DEFAULT_EXCHANGE_PRIORITY = ["binance", "okx", "gate", "hyperliquid"]

DEFAULT_VEGAS_SPEC = {
    "name": "vegas",
    "has_vegas_tunnel": True,
    "has_boll": False,
    "lines": [
        {"type": "ema", "length": 12},
        {"type": "ema", "length": 144},
        {"type": "ema", "length": 169},
    ]
}


# -------------------------------------------------------------
# Indicator Parsing & Formatting
# -------------------------------------------------------------

def parse_indicator_spec(tokens: list[str]) -> tuple[dict | None, list[str]]:
    """
    Parse indicator specifications from tokens (supporting vegas, boll, ema, ma, and arbitrary hybrids).
    Returns: (indicator_spec_dict, remaining_tokens)
    """
    has_vegas = False
    has_boll = False
    lines = []
    current_mode = None
    consumed_indices = set()

    for i, t in enumerate(tokens):
        t_up = t.upper()

        # Check combined token: e.g. EMA20, MA200, SMA60
        m = re.match(r'^(EMA|MA|SMA)(\d+)$', t_up)
        if m:
            kind = "ema" if m.group(1) == "EMA" else "ma"
            length = int(m.group(2))
            if 2 <= length <= 500:
                lines.append({"type": kind, "length": length})
                consumed_indices.add(i)
                current_mode = kind
            continue

        if t_up in ("VEGAS", "隧道"):
            has_vegas = True
            consumed_indices.add(i)
            current_mode = None
            continue

        if t_up in ("BOLL", "BOLLINGER", "布林", "布林带"):
            has_boll = True
            consumed_indices.add(i)
            current_mode = None
            continue

        if t_up in ("EMA",):
            current_mode = "ema"
            consumed_indices.add(i)
            continue

        if t_up in ("MA", "SMA", "均线"):
            current_mode = "ma"
            consumed_indices.add(i)
            continue

        if t.isdigit() and current_mode in ("ema", "ma"):
            length = int(t)
            if 2 <= length <= 500:
                lines.append({"type": current_mode, "length": length})
                consumed_indices.add(i)
            continue

        current_mode = None

    if not consumed_indices:
        return None, tokens

    remaining = [t for i, t in enumerate(tokens) if i not in consumed_indices]

    if has_vegas:
        base_vegas = [{"type": "ema", "length": 12}, {"type": "ema", "length": 144}, {"type": "ema", "length": 169}]
        existing = {(l["type"], l["length"]) for l in lines}
        for bv in base_vegas:
            if (bv["type"], bv["length"]) not in existing:
                lines.insert(len([l for l in lines if l["length"] < bv["length"]]), bv)

    if not lines and not has_vegas and not has_boll:
        for i in consumed_indices:
            t_up = tokens[i].upper()
            if t_up == "EMA":
                lines = [{"type": "ema", "length": x} for x in [20, 50, 100, 200]]
                break
            elif t_up in ("MA", "SMA", "均线"):
                lines = [{"type": "ma", "length": x} for x in [20, 50, 100, 200]]
                break

    unique_lines = []
    seen = set()
    for l in lines:
        k = (l["type"], l["length"])
        if k not in seen:
            seen.add(k)
            unique_lines.append(l)

    is_hybrid = len(set(l["type"] for l in unique_lines)) > 1 or (has_vegas and any(l["length"] not in (12, 144, 169) for l in unique_lines))

    if has_vegas and not is_hybrid:
        name = "vegas"
    elif has_boll and not unique_lines:
        name = "boll"
    elif unique_lines and all(l["type"] == "ema" for l in unique_lines) and not has_vegas:
        name = "ema"
    elif unique_lines and all(l["type"] == "ma" for l in unique_lines) and not has_vegas:
        name = "ma"
    else:
        name = "hybrid"

    return {
        "name": name,
        "has_vegas_tunnel": has_vegas,
        "has_boll": has_boll,
        "lines": unique_lines[:8],
    }, remaining


def format_indicator_name(spec: dict) -> str:
    """Format indicator spec into an attractive human-readable title."""
    if not spec:
        return "Vegas 隧道 (默认)"
    has_vegas = spec.get("has_vegas_tunnel", False)
    has_boll = spec.get("has_boll", False)
    lines = spec.get("lines", [])

    parts = []
    if has_vegas:
        other_lines = [l for l in lines if not (l["type"] == "ema" and l["length"] in (12, 144, 169))]
        if other_lines:
            other_str = ", ".join(f"{l['type'].upper()}{l['length']}" for l in other_lines)
            return f"Vegas 隧道 + {other_str}"
        return "Vegas 隧道 (EMA 12 + 144/169 隧道)"
    if has_boll:
        parts.append("布林带 BOLL (20, 2)")
    if lines:
        line_desc = ", ".join(f"{l['type'].upper()}{l['length']}" for l in lines)
        parts.append(f"均线组 ({line_desc})")
    return " + ".join(parts) if parts else "Vegas 隧道 (默认)"


# -------------------------------------------------------------
# Preference Persistence (StateStore)
# -------------------------------------------------------------

def get_user_trend_key(message: Message, state_store) -> str:
    user_id = str(message.context.user_id) if message.context and message.context.user_id else "default"
    frontend = message.frontend or "default"
    link_key = f"{frontend}:{user_id}"
    return state_store.get("user_link", "global", link_key, default=f"{frontend}_{user_id}")


def get_user_trend_pref(user_key: str, state_store) -> dict:
    pref = state_store.get("trend_pref", f"user_{user_key}", "config")
    return pref if isinstance(pref, dict) else {}


def save_user_trend_pref(user_key: str, pref: dict, state_store):
    state_store.set("trend_pref", f"user_{user_key}", "config", pref)


def delete_user_trend_pref(user_key: str, state_store):
    state_store.delete("trend_pref", f"user_{user_key}", "config")


def handle_trend_config(message: Message, tokens: list[str], state_store):
    """Handles '画线 设置' subcommands."""
    user_key = get_user_trend_key(message, state_store)
    pref = get_user_trend_pref(user_key, state_store)

    if not tokens or tokens[0].lower() in ("查看", "view", "info", "list", "当前", "偏好"):
        sym_str = pref.get("symbol") or "ETH (系统默认)"
        iv_str = " / ".join(pref.get("intervals") or ["5m (系统默认)"])
        ex_str = pref.get("exchange", "").upper() or "自动级联 (币安->OKX->Gate->HL)"
        ind_str = format_indicator_name(pref.get("indicator") or DEFAULT_VEGAS_SPEC)

        reply_text = (
            f"⚙️ 【画线个性化看盘配置】\n"
            f"• 专属默认标的: {sym_str}\n"
            f"• 专属默认周期: {iv_str}\n"
            f"• 专属首选交易所: {ex_str}\n"
            f"• 当前均线指标体系: {ind_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 常用修改指令示例（随发即改）:\n"
            f"  • 改标的: 画线 设置 标的 PAXG\n"
            f"  • 改周期: 画线 设置 周期 4h (多周期: 周期 1h 4h 1d)\n"
            f"  • 改均线: 画线 设置 指标 ema 20 50 100 200\n"
            f"  • 混合均线: 画线 设置 指标 ema 12 20 ma 50 200\n"
            f"  • 切回 Vegas: 画线 设置 指标 vegas (加牛熊线: vegas ma200)\n"
            f"  • 切布林带: 画线 设置 指标 boll\n"
            f"  • 重置默认: 画线 设置 重置"
        )
        message.reply(reply_text)
        return

    sub = tokens[0].lower()
    if sub in ("重置", "reset", "clear", "恢复"):
        delete_user_trend_pref(user_key, state_store)
        message.reply("🔄 已重置你的画线个性化设置，恢复为系统默认配置 (ETH 5m Vegas 隧道)。")
        return

    if sub in ("标的", "币种", "symbol", "sym"):
        if len(tokens) > 1:
            new_sym = tokens[1].upper()
            pref["symbol"] = new_sym
            save_user_trend_pref(user_key, pref, state_store)
            message.reply(f"✅ 已将你的专属默认标的更新为: 【{new_sym}】\n后续直接发送「画线」将默认查看 {new_sym}。")
        else:
            message.reply("400: nemo: 请提供标的名称。例如: 画线 设置 标的 PAXG")
        return

    if sub in ("周期", "interval", "intervals", "iv"):
        if len(tokens) > 1:
            new_ivs = []
            for t in tokens[1:]:
                t_up = t.upper()
                if t_up in ALL_FLAGS:
                    new_ivs = list(ALL_INTERVALS)
                    break
                elif t_up in INTERVAL_ALIASES:
                    std_iv = INTERVAL_ALIASES[t_up]
                    if std_iv not in new_ivs:
                        new_ivs.append(std_iv)
            if new_ivs:
                pref["intervals"] = new_ivs
                save_user_trend_pref(user_key, pref, state_store)
                iv_disp = " / ".join(new_ivs)
                message.reply(f"✅ 已将你的专属默认周期更新为: 【{iv_disp}】")
            else:
                message.reply("400: nemo: 未能识别周期。支持: 5m, 15m, 30m, 1h, 4h, 1d, 1w")
        else:
            message.reply("400: nemo: 请提供周期参数。例如: 画线 设置 周期 4h 或 周期 1h 4h 1d")
        return

    if sub in ("交易所", "exchange", "ex"):
        if len(tokens) > 1:
            ex_input = tokens[1].upper()
            if ex_input in EXCHANGE_ALIASES:
                target_ex = EXCHANGE_ALIASES[ex_input]
                pref["exchange"] = target_ex
                save_user_trend_pref(user_key, pref, state_store)
                message.reply(f"✅ 已将你的专属首选交易所更新为: 【{target_ex.upper()}】")
            else:
                message.reply("400: nemo: 不支持的交易所。可选: binance (币安), okx (欧易), gate (芝麻), hyperliquid")
        else:
            message.reply("400: nemo: 请提供交易所名称。例如: 画线 设置 交易所 okx")
        return

    if sub in ("指标", "indicator", "ind", "均线"):
        if len(tokens) > 1:
            spec, _ = parse_indicator_spec(tokens[1:])
            if spec:
                pref["indicator"] = spec
                save_user_trend_pref(user_key, pref, state_store)
                message.reply(f"✅ 已将你的专属指标体系更新为: 【{format_indicator_name(spec)}】")
            else:
                message.reply("400: nemo: 未能识别指标参数。示例: 画线 设置 指标 vegas 或 ema 20 50 100 200 或 ma 5 10 20 60 或 vegas ma200")
        else:
            message.reply("400: nemo: 请提供指标参数。例如: 画线 设置 指标 ema 20 50 200")
        return

    # Fallback: check if the tokens directly specify indicators (e.g. 画线 设置 ema 20 50 200)
    spec, _ = parse_indicator_spec(tokens)
    if spec:
        pref["indicator"] = spec
        save_user_trend_pref(user_key, pref, state_store)
        message.reply(f"✅ 已将你的专属指标体系更新为: 【{format_indicator_name(spec)}】")
        return

    message.reply("400: nemo: 未识别的设置指令。发送「画线 设置」可查看完整配置说明。")


def parse_input_args(raw_args: str) -> str:
    """Extracts raw query string if arguments were passed as a JSON dict by an LLM Agent."""
    raw = (raw_args or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            d = json.loads(raw)
            if "query" in d:
                return str(d["query"]).strip()
            parts = []
            if "action" in d:
                parts.append(str(d["action"]))
            if "symbol" in d:
                parts.append(str(d["symbol"]))
            if "interval" in d:
                parts.append(str(d["interval"]))
            elif "intervals" in d:
                ivs = d["intervals"]
                if isinstance(ivs, list):
                    parts.extend(str(x) for x in ivs)
                else:
                    parts.append(str(ivs))
            if "indicator" in d or "indicators" in d:
                ind = d.get("indicator") or d.get("indicators")
                if isinstance(ind, list):
                    parts.extend(str(x) for x in ind)
                else:
                    parts.append(str(ind))
            if parts:
                return " ".join(parts).strip()
        except Exception:
            pass
    return raw


def parse_trend_args(args_str: str, is_agent: bool, user_pref: dict | None = None, is_setting_cmd: bool = False) -> tuple[str, list[str], str | None, dict, bool, list[str]]:
    """
    Smart argument parser supporting full-width and half-width punctuation,
    subcommand setting detection, indicator extraction, and user preferences fallback.
    Returns: (symbol, intervals, target_exchange, indicator_spec, is_setting, setting_tokens)
    """
    raw = parse_input_args(args_str)
    pref = user_pref or {}

    tokens = [t.strip() for t in re.split(r'[\s\u3000,，、;/／]+', raw) if t.strip()]

    if is_setting_cmd:
        setting_tokens = tokens[1:] if (tokens and tokens[0].lower() in ("设置", "配置", "set", "config", "pref", "偏好")) else tokens
        return "", [], None, DEFAULT_VEGAS_SPEC, True, setting_tokens

    # Check for setting subcommand
    if tokens and tokens[0].lower() in ("设置", "配置", "set", "config", "pref", "偏好"):
        return "", [], None, DEFAULT_VEGAS_SPEC, True, tokens[1:]

    # Parse on-the-fly indicator spec if provided
    indicator_spec, remaining_tokens = parse_indicator_spec(tokens)
    if indicator_spec is None:
        indicator_spec = pref.get("indicator") or DEFAULT_VEGAS_SPEC

    symbol = None
    intervals = []
    target_exchange = None

    for t in remaining_tokens:
        t_up = t.upper()
        if t_up in ALL_FLAGS:
            intervals = list(ALL_INTERVALS)
        elif t_up in INTERVAL_ALIASES:
            std_iv = INTERVAL_ALIASES[t_up]
            if std_iv not in intervals:
                intervals.append(std_iv)
        elif t_up in EXCHANGE_ALIASES:
            target_exchange = EXCHANGE_ALIASES[t_up]
        else:
            if symbol is None:
                symbol = t_up

    # Apply defaults if missing
    if symbol is None:
        symbol = pref.get("symbol") or ("BTC" if is_agent else "ETH")

    if not intervals:
        intervals = pref.get("intervals") or (list(ALL_INTERVALS) if is_agent else ["5m"])

    if target_exchange is None:
        target_exchange = pref.get("exchange")

    return symbol, intervals, target_exchange, indicator_spec, False, []


# -------------------------------------------------------------
# Market Data Fetchers
# -------------------------------------------------------------

def fetch_binance_klines(symbol: str, interval: str = "1d", limit: int = 300) -> tuple[pd.DataFrame, str]:
    """Fetch raw K-lines from Binance (Futures first, fallback to Spot)."""
    base = symbol.upper().replace("USDT", "").replace("USD", "").replace("_", "").replace("-", "")
    pair = f"{base}USDT"
    source = "Binance 合约"
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={pair}&interval={interval}&limit={limit}"
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
    data = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []

    if not data:
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={interval}&limit={limit}"
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
        source = "Binance 现货"
        data = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []

    if not data:
        raise ValueError(f"Binance 无可用数据: {pair}")

    df = pd.DataFrame(data).iloc[:, :6]
    df.columns = ["Open time", "Open", "High", "Low", "Close", "Volume"]
    df["Open time"] = pd.to_datetime(df["Open time"].astype(int), unit="ms")
    df.set_index("Open time", inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df, source


def fetch_okx_klines(symbol: str, interval: str = "1d", limit: int = 300) -> tuple[pd.DataFrame, str]:
    """Fetch raw K-lines from OKX (Perp SWAP first, fallback to Spot)."""
    base = symbol.upper().replace("USDT", "").replace("USD", "").replace("_", "").replace("-", "")
    bar_map = {"5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"}
    bar = bar_map.get(interval, interval)
    source = "OKX 永续"
    inst_id = f"{base}-USDT-SWAP"
    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar={bar}&limit={limit}"
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
    data = r.json().get("data", []) if r.status_code == 200 and isinstance(r.json(), dict) else []

    if not data:
        inst_id = f"{base}-USDT"
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar={bar}&limit={limit}"
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
        source = "OKX 现货"
        data = r.json().get("data", []) if r.status_code == 200 and isinstance(r.json(), dict) else []

    if not data:
        raise ValueError(f"OKX 无可用数据: {base}")

    candles = data[::-1]
    df = pd.DataFrame(candles).iloc[:, :6]
    df.columns = ["Open time", "Open", "High", "Low", "Close", "Volume"]
    df["Open time"] = pd.to_datetime(df["Open time"].astype(int), unit="ms")
    df.set_index("Open time", inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df, source


def fetch_gate_klines(symbol: str, interval: str = "1d", limit: int = 300) -> tuple[pd.DataFrame, str]:
    """Fetch raw K-lines from Gate.io (Futures first, fallback to Spot)."""
    clean_symbol = symbol.upper().replace("/", "").replace("-", "")
    if "_" not in clean_symbol:
        if clean_symbol.endswith("USDT"):
            contract = clean_symbol[:-4] + "_USDT"
        elif clean_symbol.endswith("USD"):
            contract = clean_symbol[:-3] + "_USD"
        else:
            contract = clean_symbol + "_USDT"
    else:
        contract = clean_symbol

    url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={contract}&interval={interval}&limit={limit}"
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
    data = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
    source = "Gate.io 合约"

    if not data:
        currency_pair = contract
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={currency_pair}&interval={interval}&limit={limit}"
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=6)
        data = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
        source = "Gate.io 现货"

    if not data:
        raise ValueError(f"Gate.io 无可用数据: {contract}")

    df = pd.DataFrame(data).iloc[:, :6]
    df.columns = ["Open time", "Volume", "Close", "High", "Low", "Open"]
    df["Open time"] = pd.to_datetime(df["Open time"].astype(int), unit="s")
    df.set_index("Open time", inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df, source


def fetch_hyperliquid_klines(symbol: str, interval: str = "1d", limit: int = 300) -> tuple[pd.DataFrame, str]:
    """Fetch raw K-lines from Hyperliquid DEX API."""
    coin = symbol.upper().replace("USDT", "").replace("USD", "").replace("_", "").replace("-", "")
    url = "https://api.hyperliquid.xyz/info"
    now_ms = int(time.time() * 1000)
    iv_seconds = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}.get(interval, 86400)
    start_time = now_ms - (limit * iv_seconds * 1000)

    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start_time,
            "endTime": now_ms
        }
    }
    r = requests.post(url, json=body, headers=DEFAULT_HEADERS, timeout=6)
    data = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []

    if not data:
        raise ValueError(f"Hyperliquid 无可用数据: {coin}")

    df = pd.DataFrame(data)
    df.rename(columns={"t": "Open time", "o": "Open", "c": "Close", "h": "High", "l": "Low", "v": "Volume"}, inplace=True)
    df["Open time"] = pd.to_datetime(df["Open time"].astype(int), unit="ms")
    df.set_index("Open time", inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df, "Hyperliquid 永续"


EXCHANGE_FETCHERS = {
    "binance": fetch_binance_klines,
    "okx": fetch_okx_klines,
    "gate": fetch_gate_klines,
    "hyperliquid": fetch_hyperliquid_klines,
}


def fetch_klines_by_exchange(exchange: str, symbol: str, interval: str, limit: int = 300) -> tuple[pd.DataFrame, str]:
    fetcher = EXCHANGE_FETCHERS.get(exchange)
    if not fetcher:
        raise ValueError(f"未支持的交易所: {exchange}")
    return fetcher(symbol, interval, limit=limit)


def resolve_exchange_and_probe(symbol: str, probe_interval: str, target_exchange: str | None = None) -> tuple[str, str, pd.DataFrame]:
    """Resolve which exchange has the symbol and valid K-line data."""
    exchanges_to_try = [target_exchange] if target_exchange else DEFAULT_EXCHANGE_PRIORITY
    attempts_errors = []

    for ex in exchanges_to_try:
        try:
            df, src = fetch_klines_by_exchange(ex, symbol, probe_interval, limit=300)
            if len(df) >= 30:
                logger.info("[Crypto Trend] Resolved exchange for %s to %s (%s)", symbol, ex, src)
                return ex, src, df
            else:
                attempts_errors.append(f"{ex}: 数据量不足 ({len(df)} 根)")
        except Exception as e:
            attempts_errors.append(f"{ex}: {e}")

    err_summary = "; ".join(attempts_errors)
    raise ValueError(f"全网未能获取 {symbol} 行情数据。尝试结果: {err_summary}")


# -------------------------------------------------------------
# Indicator Computations
# -------------------------------------------------------------

def compute_timeframe_indicators(df: pd.DataFrame, indicator_spec: dict | None = None) -> dict:
    """Compute indicators (Vegas tunnel, MAs, BOLL, MACD, RSI, and signals)."""
    spec = indicator_spec or DEFAULT_VEGAS_SPEC

    # Common subplots
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.rsi(length=14, append=True)

    has_vegas = spec.get("has_vegas_tunnel", True)
    has_boll = spec.get("has_boll", False)
    lines = spec.get("lines", [])

    if has_vegas:
        df.ta.ema(length=12, append=True)
        df.ta.ema(length=144, append=True)
        df.ta.ema(length=169, append=True)
        if 'EMA_12' not in df.columns: df['EMA_12'] = df['Close']
        if 'EMA_144' not in df.columns: df['EMA_144'] = df['Close']
        if 'EMA_169' not in df.columns: df['EMA_169'] = df['Close']

    if has_boll:
        df.ta.bbands(length=20, std=2, append=True)

    mas = {}
    for l in lines:
        kind = l["type"]
        length = l["length"]
        col = f"EMA_{length}" if kind == "ema" else f"SMA_{length}"
        if col not in df.columns:
            if kind == "ema":
                df.ta.ema(length=length, append=True)
            else:
                df.ta.sma(length=length, append=True)
        if col in df.columns:
            val = df[col].iloc[-1]
            mas[col] = float(val) if pd.notna(val) else float(df['Close'].iloc[-1])

    latest = df.iloc[-1]
    close = float(latest['Close'])

    if has_vegas:
        tunnel_top_series = np.maximum(df['EMA_144'], df['EMA_169'])
        tunnel_bot_series = np.minimum(df['EMA_144'], df['EMA_169'])
        tunnel_mid_series = (df['EMA_144'] + df['EMA_169']) / 2.0

        ema12 = float(latest.get('EMA_12', close))
        ema144 = float(latest.get('EMA_144', close))
        ema169 = float(latest.get('EMA_169', close))
        tunnel_top = float(tunnel_top_series.iloc[-1])
        tunnel_bot = float(tunnel_bot_series.iloc[-1])
        tunnel_mid = float(tunnel_mid_series.iloc[-1])

        if close > tunnel_top:
            status_short = "多头 (上方)"
            key_type = "支撑"
            key_band = (tunnel_bot, tunnel_top)
            dist_pct = -((close - tunnel_top) / close) * 100.0
        elif close < tunnel_bot:
            status_short = "空头 (下方)"
            key_type = "压力"
            key_band = (tunnel_bot, tunnel_top)
            dist_pct = +((tunnel_bot - close) / close) * 100.0
        else:
            status_short = "震荡 (通道内)"
            key_type = "区间"
            key_band = (tunnel_bot, tunnel_top)
            dist_pct = 0.0

        # Patterns
        bounce_up = (df['Low'] <= tunnel_top_series) & (df['Close'] > tunnel_top_series) & (df['EMA_12'] > tunnel_mid_series)
        bounce_up = bounce_up & ~bounce_up.shift(1, fill_value=False)
        bounce_down = (df['High'] >= tunnel_bot_series) & (df['Close'] < tunnel_bot_series) & (df['EMA_12'] < tunnel_mid_series)
        bounce_down = bounce_down & ~bounce_down.shift(1, fill_value=False)
        break_up = (df['Close'] > tunnel_top_series) & (df['Close'].shift(1) <= tunnel_top_series.shift(1))
        true_break_up = break_up & (df['EMA_12'] > tunnel_top_series)
        false_break_up = break_up & (df['EMA_12'] <= tunnel_top_series)
        break_down = (df['Close'] < tunnel_bot_series) & (df['Close'].shift(1) >= tunnel_bot_series.shift(1))
        true_break_down = break_down & (df['EMA_12'] < tunnel_bot_series)
        false_break_down = break_down & (df['EMA_12'] >= tunnel_bot_series)

        signal_tag = ""
        if bounce_up.iloc[-1]: signal_tag = "隧道支撑反弹!"
        elif bounce_down.iloc[-1]: signal_tag = "隧道阻力受挫!"
        elif true_break_up.iloc[-1]: signal_tag = "向上真突破!"
        elif false_break_up.iloc[-1]: signal_tag = "向上假突破(诱多)!"
        elif true_break_down.iloc[-1]: signal_tag = "向下真跌破!"
        elif false_break_down.iloc[-1]: signal_tag = "向下假跌破(诱空)!"
    else:
        ema12 = mas.get("EMA_12", close)
        ema144 = mas.get("EMA_144", close)
        ema169 = mas.get("EMA_169", close)
        tunnel_top = close
        tunnel_bot = close
        key_type = "均线"
        key_band = (close, close)
        dist_pct = 0.0
        signal_tag = ""

        if mas:
            all_vals = list(mas.values())
            if all(close > v for v in all_vals):
                status_short = "多头排列 (站上全均线)"
            elif all(close < v for v in all_vals):
                status_short = "空头排列 (全均线下破)"
            else:
                status_short = "均线交织 (震荡)"
        elif has_boll:
            bbu = latest.get("BBU_20_2.0", close * 1.02)
            bbl = latest.get("BBL_20_2.0", close * 0.98)
            bbm = latest.get("BBM_20_2.0", close)
            if close >= bbu:
                status_short = "布林触顶 (超买区)"
            elif close <= bbl:
                status_short = "布林触底 (超卖区)"
            elif close >= bbm:
                status_short = "布林中上轨 (偏多)"
            else:
                status_short = "布林中下轨 (偏空)"
        else:
            status_short = "中性走势"

    # RSI
    rsi_val = float(latest.get('RSI_14', 50))
    rsi_desc = "中性"
    if rsi_val >= 70: rsi_desc = "超买"
    elif rsi_val <= 30: rsi_desc = "超卖"
    elif rsi_val > 55: rsi_desc = "偏强"
    elif rsi_val < 45: rsi_desc = "偏弱"

    # MACD
    macdh = df.get('MACDh_12_26_9', pd.Series([0] * len(df), index=df.index))
    golden_cross = (macdh > 0) & (macdh.shift(1) <= 0)
    death_cross = (macdh < 0) & (macdh.shift(1) >= 0)
    macd_val = float(latest.get('MACD_12_26_9', 0))
    macd_sig = float(latest.get('MACDs_12_26_9', 0))
    macd_h = float(latest.get('MACDh_12_26_9', 0))
    if golden_cross.iloc[-1]:
        macd_desc = "刚金叉"
    elif death_cross.iloc[-1]:
        macd_desc = "刚死叉"
    elif macd_val > macd_sig:
        prev_h = df['MACDh_12_26_9'].iloc[-2] if len(df) > 1 else macd_h
        macd_desc = "多头" + ("放量" if macd_h > prev_h else "缩量")
    else:
        prev_h = df['MACDh_12_26_9'].iloc[-2] if len(df) > 1 else macd_h
        macd_desc = "空头" + ("放量" if macd_h < prev_h else "缩量")

    return {
        "close": close,
        "ema12": ema12,
        "ema144": ema144,
        "ema169": ema169,
        "tunnel_top": tunnel_top,
        "tunnel_bot": tunnel_bot,
        "status_short": status_short,
        "key_type": key_type,
        "key_band": key_band,
        "dist_pct": dist_pct,
        "rsi": rsi_val,
        "rsi_desc": rsi_desc,
        "macd_desc": macd_desc,
        "signal_tag": signal_tag,
        "mas": mas,
        "indicator_spec": spec,
    }


# -------------------------------------------------------------
# Text Formatting
# -------------------------------------------------------------

def format_human_compact_text(symbol: str, intervals: list[str], tf_data_dict: dict, source_label: str = "Gate 合约", indicator_spec: dict | None = None) -> str:
    """Format a clean, concise 3-5 line summary for human group chats."""
    first_iv = intervals[0] if intervals[0] in tf_data_dict else next(iter(tf_data_dict))
    current_price = tf_data_dict[first_iv]['info']['close']
    spec = indicator_spec or tf_data_dict[first_iv]['info'].get('indicator_spec') or DEFAULT_VEGAS_SPEC
    has_vegas = spec.get("has_vegas_tunnel", True)

    if len(intervals) == 1:
        iv = intervals[0]
        info = tf_data_dict[iv]["info"]
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        sig_str = f" | ⚠️ {info['signal_tag']}" if info.get("signal_tag") else ""
        if has_vegas:
            return (
                f"【{symbol} ({iv.upper()}) Vegas 隧道】现价: {current_price:,.2f} USDT ({source_label})\n"
                f"• 状态: {info['status_short']}{sig_str} | EMA12: {info['ema12']:,.2f}\n"
                f"• 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} (距{info['key_type']}: {dist_str})\n"
                f"• 指标: RSI {info['rsi']:.1f} ({info['rsi_desc']}) | MACD {info['macd_desc']}"
            )
        else:
            mas_str = " | ".join(f"{k}: {v:,.1f}" for k, v in list(info.get('mas', {}).items())[:4]) or "均线已计算"
            return (
                f"【{symbol} ({iv.upper()}) 均线分析】现价: {current_price:,.2f} USDT ({source_label})\n"
                f"• 状态: {info['status_short']}\n"
                f"• 均线: {mas_str}\n"
                f"• 指标: RSI {info['rsi']:.1f} ({info['rsi_desc']}) | MACD {info['macd_desc']}"
            )

    # Multi-interval compact bullet points
    title = f"【{symbol} Vegas 隧道关键位】" if has_vegas else f"【{symbol} 均线走势关键位】"
    lines = [
        f"{title}当前价: {current_price:,.2f} USDT ({source_label})"
    ]
    for iv in intervals:
        if iv not in tf_data_dict:
            continue
        info = tf_data_dict[iv]["info"]
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        sig_str = f" | {info['signal_tag']}" if info.get("signal_tag") else ""
        if has_vegas:
            lines.append(
                f"• {iv.upper()}: {info['status_short']} | 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} ({dist_str}) | RSI {info['rsi']:.1f}{sig_str}"
            )
        else:
            mas_str = " | ".join(f"{k}: {v:,.1f}" for k, v in list(info.get('mas', {}).items())[:3])
            lines.append(
                f"• {iv.upper()}: {info['status_short']} | {mas_str} | RSI {info['rsi']:.1f}"
            )

    return "\n".join(lines).strip()


def format_agent_detailed_text(symbol: str, tf_data_dict: dict, source_label: str = "Gate.io 合约", indicator_spec: dict | None = None) -> str:
    """Format full comprehensive report for Agent Observation."""
    first_iv = '5m' if '5m' in tf_data_dict else next(iter(tf_data_dict))
    current_price = tf_data_dict[first_iv]['info']['close']
    spec = indicator_spec or tf_data_dict[first_iv]['info'].get('indicator_spec') or DEFAULT_VEGAS_SPEC
    has_vegas = spec.get("has_vegas_tunnel", True)

    ind_title = "Vegas 隧道" if has_vegas else "多级别均线"
    lines = [
        f"【{symbol} {ind_title}多级别动态支撑压力分析】",
        f"当前价格: {current_price:,.2f} USDT (数据源: {source_label})",
        ""
    ]
    groups = [
        ("⚡【超短线级别】", ["5m", "15m"]),
        ("⚡【日内波段级别】", ["30m", "1h"]),
        ("⚡【中长趋势级别】", ["4h", "1d"]),
    ]
    for grp_title, iv_list in groups:
        lines.append(grp_title)
        for iv in iv_list:
            if iv not in tf_data_dict:
                continue
            info = tf_data_dict[iv]["info"]
            sig_str = f" | ⚠️ {info['signal_tag']}" if info.get("signal_tag") else ""
            dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
            lines.append(f"📊 {iv.upper()}:")
            if has_vegas:
                lines.append(f"  • 状态: {info['status_short']}{sig_str} | EMA12: {info['ema12']:,.2f}")
                lines.append(f"  • Vegas 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} (距{info['key_type']}: {dist_str})")
            else:
                mas_str = " | ".join(f"{k}: {v:,.1f}" for k, v in list(info.get('mas', {}).items())[:4])
                lines.append(f"  • 状态: {info['status_short']} | 均线: {mas_str}")
            lines.append(f"  • 指标: RSI {info['rsi']:.1f} ({info['rsi_desc']}) | MACD {info['macd_desc']}")
        lines.append("")

    if has_vegas:
        above_count = sum(1 for d in tf_data_dict.values() if d['info']['close'] > d['info']['tunnel_top'])
        below_count = sum(1 for d in tf_data_dict.values() if d['info']['close'] < d['info']['tunnel_bot'])
        total_count = len(tf_data_dict)

        lines.append("📌【结构与关键点位汇总】:")
        if above_count == total_count:
            lines.append(f"  • 全级别多头共振: {total_count} 个周期全部运行在 Vegas 隧道上方，多头趋势强劲！")
        elif below_count == total_count:
            lines.append(f"  • 全级别空头共振: {total_count} 个周期全部处于 Vegas 隧道下方，受均线空头压制！")
        else:
            lines.append(f"  • 级别分化: {above_count}/{total_count} 个级别处于多头隧道上方，{below_count}/{total_count} 个级别处于空头隧道下方。")

        if "1d" in tf_data_dict:
            d = tf_data_dict["1d"]["info"]
            lines.append(f"  • 1D 大周期防线: {d['tunnel_bot']:,.2f} ~ {d['tunnel_top']:,.2f} ({d['key_type']})")
        if "4h" in tf_data_dict:
            h4 = tf_data_dict["4h"]["info"]
            lines.append(f"  • 4H 日内波段防线: {h4['tunnel_bot']:,.2f} ~ {h4['tunnel_top']:,.2f} ({h4['key_type']})")
        if "15m" in tf_data_dict:
            m15 = tf_data_dict["15m"]["info"]
            lines.append(f"  • 15M 短线防线: {m15['tunnel_bot']:,.2f} ~ {m15['tunnel_top']:,.2f} ({m15['key_type']})")

    return "\n".join(lines).strip()


# -------------------------------------------------------------
# Chart Plotting
# -------------------------------------------------------------

PALETTE_LINES = ["#00E5FF", "#76FF03", "#FFD600", "#FF4081", "#E040FB", "#B388FF", "#69F0AE"]

def draw_adaptive_grid_chart(symbol: str, intervals: list[str], tf_dict: dict, out_path: str, theme: str = "", source_label: str = "", indicator_spec: dict | None = None):
    """Dynamically draw a composite chart matching the exact number of requested intervals."""
    k = len(intervals)
    is_dark = "Dark" in theme or True
    COLORS = {
        "bg": "#181a20" if is_dark else "#FFFFFF",
        "card_bg": "#1e2329" if is_dark else "#F5F5F5",
        "grid": "#2b313a" if is_dark else "#E8E8E8",
        "text": "#eaecef" if is_dark else "#333333",
        "bull": "#0ecb81",
        "bear": "#f6465d",
        "ma12": "#ff4d4f",
        "ma144": "#faad14",
        "ma169": "#1890ff",
        "tunnel_fill": "#faad14"
    }

    spec = indicator_spec or DEFAULT_VEGAS_SPEC
    has_vegas = spec.get("has_vegas_tunnel", True)
    has_boll = spec.get("has_boll", False)
    lines_to_draw = spec.get("lines", [])

    if k == 2:
        nrows, ncols = 1, 2
        figsize = (16, 6.8)
        top_val, suptitle_y = 0.80, 0.95
        bottom_val, hspace = 0.09, 0.25
    elif k == 3:
        nrows, ncols = 1, 3
        figsize = (18, 6.8)
        top_val, suptitle_y = 0.80, 0.95
        bottom_val, hspace = 0.09, 0.25
    elif k == 4:
        nrows, ncols = 2, 2
        figsize = (16, 11.0)
        top_val, suptitle_y = 0.88, 0.97
        bottom_val, hspace = 0.06, 0.28
    elif k <= 6:
        nrows, ncols = 3, 2
        figsize = (16, 15.0)
        top_val, suptitle_y = 0.91, 0.98
        bottom_val, hspace = 0.05, 0.28
    else:
        ncols = 3
        nrows = (k + 2) // 3
        figsize = (18, 5.0 * nrows)
        top_val, suptitle_y = 0.92, 0.982
        bottom_val, hspace = 0.04, 0.30

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, facecolor=COLORS["bg"], dpi=150)
    plt.subplots_adjust(left=0.045, right=0.965, top=top_val, bottom=bottom_val, hspace=hspace, wspace=0.10)

    axes_flat = np.array(axes).flatten()
    first_iv = intervals[0] if intervals[0] in tf_dict else next(iter(tf_dict))
    latest_price = tf_dict[first_iv]["info"]["close"]

    for i, iv in enumerate(intervals):
        ax = axes_flat[i]
        ax.set_facecolor(COLORS["card_bg"])
        ax.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7)
        ax.tick_params(colors=COLORS["text"], labelsize=8)

        if iv not in tf_dict:
            ax.text(0.5, 0.5, f"{iv.upper()} 无可用数据", color=COLORS["text"], ha='center', va='center')
            continue

        df = tf_dict[iv]["df"]
        info = tf_dict[iv]["info"]

        plot_len = min(80, len(df))
        plot_df = df.tail(plot_len).copy()
        n = len(plot_df)
        x = np.arange(n)
        dates = plot_df.index

        # Candlesticks
        width = 0.6
        for bar_i in range(n):
            o, h, l, cl = plot_df["Open"].iloc[bar_i], plot_df["High"].iloc[bar_i], plot_df["Low"].iloc[bar_i], plot_df["Close"].iloc[bar_i]
            color = COLORS["bull"] if cl >= o else COLORS["bear"]
            body_bottom = min(o, cl)
            body_height = abs(cl - o) if abs(cl - o) > 0 else (h - l) * 0.01
            ax.bar(x[bar_i], body_height, bottom=body_bottom, width=width, color=color, edgecolor=color, linewidth=0.3)
            ax.vlines(x[bar_i], l, h, color=color, linewidth=0.4)

        # Lines
        if has_boll:
            bbu_col = "BBU_20_2.0"
            bbl_col = "BBL_20_2.0"
            bbm_col = "BBM_20_2.0"
            if bbu_col in plot_df.columns and bbl_col in plot_df.columns:
                ax.plot(x, plot_df[bbu_col], color="#64B5F6", linewidth=0.7, linestyle="--", alpha=0.8)
                ax.plot(x, plot_df[bbm_col], color="#FFA500", linewidth=0.7, alpha=0.8)
                ax.plot(x, plot_df[bbl_col], color="#64B5F6", linewidth=0.7, linestyle="--", alpha=0.8)
                ax.fill_between(x, plot_df[bbl_col], plot_df[bbu_col], color="#64B5F6", alpha=0.08)

        if has_vegas:
            if 'EMA_12' in plot_df.columns:
                ax.plot(x, plot_df['EMA_12'], color=COLORS['ma12'], linewidth=1.1, label='EMA12', alpha=0.9)
            if 'EMA_144' in plot_df.columns and 'EMA_169' in plot_df.columns:
                ax.plot(x, plot_df['EMA_144'], color=COLORS['ma144'], linewidth=0.85, label='EMA144', alpha=0.85)
                ax.plot(x, plot_df['EMA_169'], color=COLORS['ma169'], linewidth=0.85, label='EMA169', alpha=0.85)
                top_line = np.maximum(plot_df['EMA_144'], plot_df['EMA_169'])
                bot_line = np.minimum(plot_df['EMA_144'], plot_df['EMA_169'])
                ax.fill_between(x, bot_line, top_line, color=COLORS['tunnel_fill'], alpha=0.15)

        # Draw any additional MA lines
        c_idx = 0
        for l in lines_to_draw:
            kind = l["type"]
            length = l["length"]
            if has_vegas and kind == "ema" and length in (12, 144, 169):
                continue
            col = f"EMA_{length}" if kind == "ema" else f"SMA_{length}"
            if col in plot_df.columns:
                c = PALETTE_LINES[c_idx % len(PALETTE_LINES)]
                c_idx += 1
                ax.plot(x, plot_df[col], color=c, linewidth=0.9, label=f"{kind.upper()}{length}", alpha=0.85)

        # Current price dashed line
        ax.axhline(info['close'], color='#FFD700', linestyle='--', linewidth=0.7, alpha=0.75)

        # Title
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        title_color = COLORS['bull'] if '多头' in info['status_short'] else (COLORS['bear'] if '空头' in info['status_short'] else '#FFD700')
        if has_vegas:
            title_text = f"[{iv.upper()}] 现价: {info['close']:,.2f} | 隧道: {info['tunnel_bot']:,.1f}~{info['tunnel_top']:,.1f} | {info['status_short']} ({dist_str})"
        else:
            title_text = f"[{iv.upper()}] 现价: {info['close']:,.2f} | {info['status_short']}"

        ax.set_title(title_text, fontsize=9.5, fontweight='bold', color=title_color, pad=6)

        # X-ticks
        tick_idx = np.linspace(0, n - 1, min(6, n), dtype=int)
        ax.set_xticks(tick_idx)
        ax.set_xticklabels(
            [dates[j].strftime("%m/%d" if iv in ("1d", "1w") else "%m/%d %H:%M") for j in tick_idx],
            fontsize=7, rotation=15, color=COLORS["text"]
        )

    # Hide extra empty subplots if any
    for j in range(k, len(axes_flat)):
        axes_flat[j].set_visible(False)

    interval_str = " / ".join(iv.upper() for iv in intervals)
    source_str = f"  |  {source_label}" if source_label else ""
    indicator_title = "Vegas 隧道" if has_vegas else "多级别均线"
    fig.suptitle(
        f"{symbol} {indicator_title}动态支撑压力 ({interval_str})  |  现价: {latest_price:,.2f} USDT{source_str}",
        fontsize=14, fontweight="bold", color="#FFFFFF", y=suptitle_y
    )
    fig.savefig(out_path, dpi=150, facecolor=COLORS["bg"], bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_single_chart(symbol: str, interval: str, source: str, df: pd.DataFrame, config: dict, out_path: str, indicator_spec: dict | None = None):
    """Draw detailed single timeframe 3-panel chart (Candles + Volume + MACD)."""
    COLORS = {
        "bg": "#1e1e1e" if "Dark" in config.get("theme", "") else "#FFFFFF",
        "grid": "#333333" if "Dark" in config.get("theme", "") else "#E8E8E8",
        "text": "#dddddd" if "Dark" in config.get("theme", "") else "#333333",
        "bull": "#1E8E3E",
        "bear": "#C62828",
        "ma12": "#FF0000",
        "ma144": "#FFA500",
        "ma169": "#64B5F6",
        "macd_line": "#2962FF",
        "macd_signal": "#FF6D00",
        "macd_pos": "#1E8E3E",
        "macd_neg": "#C62828",
    }

    spec = indicator_spec or DEFAULT_VEGAS_SPEC
    has_vegas = spec.get("has_vegas_tunnel", True)
    has_boll = spec.get("has_boll", False)
    lines_to_draw = spec.get("lines", [])

    plot_len = min(150, len(df))
    plot_df = df.tail(plot_len).copy()
    n = len(plot_df)
    x = np.arange(n)
    dates = plot_df.index

    fig = plt.figure(figsize=(18, 9), facecolor=COLORS["bg"], dpi=150)
    gs = fig.add_gridspec(
        3, 1, height_ratios=[5, 1.2, 1.2],
        hspace=0.05, left=0.04, right=0.96, top=0.93, bottom=0.06,
    )

    ax_main = fig.add_subplot(gs[0])
    ax_vol = fig.add_subplot(gs[1], sharex=ax_main)
    ax_macd = fig.add_subplot(gs[2], sharex=ax_main)

    for ax in [ax_main, ax_vol, ax_macd]:
        ax.set_facecolor(COLORS["bg"])
        ax.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7)
        ax.tick_params(colors=COLORS["text"], labelsize=8)

    width = 0.6
    for i in range(n):
        o, h, l, c = plot_df["Open"].iloc[i], plot_df["High"].iloc[i], plot_df["Low"].iloc[i], plot_df["Close"].iloc[i]
        color = COLORS["bull"] if c >= o else COLORS["bear"]
        body_bottom = min(o, c)
        body_height = abs(c - o) if abs(c - o) > 0 else (h - l) * 0.01
        ax_main.bar(x[i], body_height, bottom=body_bottom, width=width, color=color, edgecolor=color, linewidth=0.3)
        ax_main.vlines(x[i], l, h, color=color, linewidth=0.4)

    # Plot BOLL if enabled
    if has_boll:
        bbu_col = "BBU_20_2.0"
        bbl_col = "BBL_20_2.0"
        bbm_col = "BBM_20_2.0"
        if bbu_col in plot_df.columns and bbl_col in plot_df.columns:
            ax_main.plot(x, plot_df[bbu_col], color="#64B5F6", linewidth=0.8, label="BOLL-UP", linestyle="--")
            ax_main.plot(x, plot_df[bbm_col], color="#FFA500", linewidth=0.8, label="BOLL-MID")
            ax_main.plot(x, plot_df[bbl_col], color="#64B5F6", linewidth=0.8, label="BOLL-DN", linestyle="--")
            ax_main.fill_between(x, plot_df[bbl_col], plot_df[bbu_col], color="#64B5F6", alpha=0.08)

    # Plot Vegas if enabled
    if has_vegas:
        if 'EMA_12' in plot_df.columns:
            ax_main.plot(x, plot_df['EMA_12'], color=COLORS["ma12"], linewidth=1.2, label="EMA12", alpha=0.9)
        if 'EMA_144' in plot_df.columns and 'EMA_169' in plot_df.columns:
            ax_main.plot(x, plot_df['EMA_144'], color=COLORS["ma144"], linewidth=0.8, label="EMA144 (Vegas)", alpha=0.85)
            ax_main.plot(x, plot_df['EMA_169'], color=COLORS["ma169"], linewidth=0.8, label="EMA169 (Vegas)", alpha=0.85)
            top_line = np.maximum(plot_df['EMA_144'], plot_df['EMA_169'])
            bot_line = np.minimum(plot_df['EMA_144'], plot_df['EMA_169'])
            ax_main.fill_between(x, bot_line, top_line, color="#FFA500", alpha=0.15)

    # Plot remaining custom moving averages
    c_idx = 0
    for l in lines_to_draw:
        kind = l["type"]
        length = l["length"]
        if has_vegas and kind == "ema" and length in (12, 144, 169):
            continue
        col = f"EMA_{length}" if kind == "ema" else f"SMA_{length}"
        if col in plot_df.columns:
            c = PALETTE_LINES[c_idx % len(PALETTE_LINES)]
            c_idx += 1
            ax_main.plot(x, plot_df[col], color=c, linewidth=1.0, label=f"{kind.upper()}{length}", alpha=0.9)

    ax_main.legend(loc="upper left", fontsize=8, framealpha=0.8)
    ax_main.set_ylabel("Price", fontsize=9, color=COLORS["text"])

    # Volume
    vol_colors = [COLORS["bull"] if plot_df["Close"].iloc[i] >= plot_df["Open"].iloc[i] else COLORS["bear"] for i in range(n)]
    ax_vol.bar(x, plot_df["Volume"], width=width, color=vol_colors, alpha=0.7)
    ax_vol.set_ylabel("Vol", fontsize=8, color=COLORS["text"])
    ax_vol.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else (f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}")
    ))

    # MACD
    if 'MACDh_12_26_9' in plot_df.columns:
        macd_colors = [COLORS["macd_pos"] if v >= 0 else COLORS["macd_neg"] for v in plot_df["MACDh_12_26_9"]]
        ax_macd.bar(x, plot_df["MACDh_12_26_9"], width=width * 0.8, color=macd_colors, alpha=0.6)
        ax_macd.plot(x, plot_df["MACD_12_26_9"], color=COLORS["macd_line"], linewidth=0.8, label="MACD")
        ax_macd.plot(x, plot_df["MACDs_12_26_9"], color=COLORS["macd_signal"], linewidth=0.8, label="Signal")
        ax_macd.axhline(0, color=COLORS["grid"], linewidth=0.5)
        ax_macd.legend(loc="upper left", fontsize=7, framealpha=0.8)
    ax_macd.set_ylabel("MACD", fontsize=8, color=COLORS["text"])

    plt.setp(ax_main.get_xticklabels(), visible=False)
    plt.setp(ax_vol.get_xticklabels(), visible=False)
    tick_idx = np.linspace(0, n - 1, min(15, n), dtype=int) if n > 10 else np.arange(n)
    ax_macd.set_xticks(tick_idx)
    ax_macd.set_xticklabels(
        [dates[i].strftime("%m/%d" if interval in ("1d", "1w") else "%m/%d %H:%M") for i in tick_idx],
        fontsize=7, rotation=30
    )

    last_close = plot_df["Close"].iloc[-1]
    first_close = plot_df["Close"].iloc[0]
    pct = ((last_close - first_close) / first_close * 100) if first_close else 0
    sign = "+" if pct >= 0 else ""
    title_color = COLORS["bull"] if pct >= 0 else COLORS["bear"]
    fig.suptitle(
        f"{symbol}  |  {last_close:,.2f}  ({sign}{pct:.1f}%)  |  {interval}  |  {source}",
        fontsize=16, fontweight="bold", color=title_color, y=0.97,
    )
    fig.savefig(out_path, dpi=150, facecolor=COLORS["bg"], bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


# -------------------------------------------------------------
# Main Plugin Execution
# -------------------------------------------------------------

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from runtime import context
    state_store = getattr(context, "state_store", None)
    if state_store is None:
        from store.database import Database
        from store.state_store import StateStore
        state_store = StateStore(Database())

    user_key = get_user_trend_key(message, state_store)
    user_pref = get_user_trend_pref(user_key, state_store)

    is_agent = getattr(message.request, "is_agent", False)
    cmd = (message.request.command or "").lower()
    is_setting_cmd = cmd in ("画线设置", "trend_set", "trend_config")
    raw_args = parse_input_args(message.request.args or "")

    raw_symbol, intervals, target_exchange, indicator_spec, is_setting, setting_tokens = parse_trend_args(
        raw_args, is_agent=is_agent, user_pref=user_pref, is_setting_cmd=is_setting_cmd
    )

    # Handle configuration command
    if cmd in ("画线设置", "trend_set", "trend_config") or is_setting:
        handle_trend_config(message, setting_tokens, state_store)
        return

    chart_dir = os.path.join(os.getcwd(), "data", "charts")
    os.makedirs(chart_dir, exist_ok=True)

    # -------------------------------------------------------------
    # CASE 1: Single Timeframe Mode
    # -------------------------------------------------------------
    if len(intervals) == 1:
        iv = intervals[0]
        try:
            resolved_ex, source_label, df = resolve_exchange_and_probe(raw_symbol, iv, target_exchange=target_exchange)
            source = f"{source_label} ({iv})"
        except Exception as e:
            message.reply(f"404: nemo: 获取 {raw_symbol} 行情失败: {e}")
            return

        if len(df) < 30:
            message.reply(f"404: nemo: {raw_symbol} 数据量过少 ({len(df)} 根)，无法进行指标计算。")
            return

        info = compute_timeframe_indicators(df, indicator_spec=indicator_spec)
        chart_filename = f"{raw_symbol}_{iv}_{uuid.uuid4().hex[:8]}.png"
        chart_filepath = os.path.join(chart_dir, chart_filename)
        draw_single_chart(raw_symbol, iv, source, df, config, chart_filepath, indicator_spec=indicator_spec)

        tf_data_dict = {iv: {"df": df, "info": info}}
        text_reply = format_human_compact_text(raw_symbol, intervals, tf_data_dict, source_label=source_label, indicator_spec=indicator_spec)

        message.payload = {
            "symbol": raw_symbol,
            "interval": iv,
            "exchange": resolved_ex,
            "source": source_label,
            "current_price": info['close'],
            "ema12": info['ema12'],
            "ema144": info['ema144'],
            "ema169": info['ema169'],
            "tunnel": [info['tunnel_bot'], info['tunnel_top']],
            "status": info['status_short'],
            "dist_pct": info['dist_pct'],
            "rsi": info['rsi'],
            "mas": info.get('mas', {}),
            "indicator": indicator_spec,
            "chart_local_path": os.path.abspath(chart_filepath),
        }
        message.reply(text_reply, photo_url=os.path.abspath(chart_filepath))
        return

    # -------------------------------------------------------------
    # CASE 2: Multi-Timeframe Mode (e.g. 5m, 15m, 30m or all 6)
    # -------------------------------------------------------------
    tf_data_dict = {}
    errors = {}

    first_iv = intervals[0]
    try:
        resolved_ex, source_label, df_first = resolve_exchange_and_probe(raw_symbol, first_iv, target_exchange=target_exchange)
        info_first = compute_timeframe_indicators(df_first, indicator_spec=indicator_spec)
        tf_data_dict[first_iv] = {"df": df_first, "info": info_first}
    except Exception as e:
        message.reply(f"404: nemo: 获取 {raw_symbol} 多级别行情失败: {e}")
        return

    remaining_ivs = [iv for iv in intervals if iv != first_iv]
    if remaining_ivs:
        def fetch_single(iv):
            try:
                df, _ = fetch_klines_by_exchange(resolved_ex, raw_symbol, interval=iv, limit=300)
                if len(df) < 30:
                    return iv, None, "数据量过少"
                info = compute_timeframe_indicators(df, indicator_spec=indicator_spec)
                return iv, (df, info), None
            except Exception as e:
                return iv, None, str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(remaining_ivs), 6)) as executor:
            future_map = {executor.submit(fetch_single, iv): iv for iv in remaining_ivs}
            for future in concurrent.futures.as_completed(future_map):
                iv, res_tuple, err = future.result()
                if res_tuple:
                    df, info = res_tuple
                    tf_data_dict[iv] = {"df": df, "info": info}
                else:
                    errors[iv] = err

    if not tf_data_dict:
        sample_err = next(iter(errors.values()), "未知错误")
        message.reply(f"404: nemo: 获取 {raw_symbol} 多级别行情失败。错误: {sample_err}")
        return

    chart_filename = f"{raw_symbol}_trend_{uuid.uuid4().hex[:8]}.png"
    chart_filepath = os.path.join(chart_dir, chart_filename)
    draw_adaptive_grid_chart(raw_symbol, intervals, tf_data_dict, chart_filepath, theme=config.get("theme", ""), source_label=source_label, indicator_spec=indicator_spec)

    if is_agent:
        text_card = format_agent_detailed_text(raw_symbol, tf_data_dict, source_label=source_label, indicator_spec=indicator_spec)
    else:
        text_card = format_human_compact_text(raw_symbol, intervals, tf_data_dict, source_label=source_label, indicator_spec=indicator_spec)

    agent_levels = {}
    for iv, d in tf_data_dict.items():
        info = d["info"]
        agent_levels[iv] = {
            "close": info["close"],
            "ema12": info["ema12"],
            "ema144": info["ema144"],
            "ema169": info["ema169"],
            "tunnel": [info["tunnel_bot"], info["tunnel_top"]],
            "status": info["status_short"],
            "dist_pct": info["dist_pct"],
            "key_type": info["key_type"],
            "rsi": info["rsi"],
            "macd": info["macd_desc"],
            "signal": info["signal_tag"],
            "mas": info.get("mas", {}),
        }

    first_iv = intervals[0] if intervals[0] in tf_data_dict else next(iter(tf_data_dict))
    message.payload = {
        "symbol": raw_symbol,
        "exchange": resolved_ex,
        "source": source_label,
        "current_price": tf_data_dict[first_iv]["info"]["close"],
        "levels": agent_levels,
        "indicator": indicator_spec,
        "chart_local_path": os.path.abspath(chart_filepath)
    }

    message.reply(text_card, photo_url=os.path.abspath(chart_filepath))
