"""
Crypto Trend & Multi-Timeframe Vegas Tunnel Plugin
--------------------------------------------------
Fetches K-lines, calculates indicators (EMA 12, EMA 144, EMA 169, Vegas Tunnel, MACD, RSI),
draws annotated charts, and provides structured payload and rich text reports for users & agents.
Supports single-timeframe, arbitrary custom timeframe lists (e.g. 5m, 15m, 30m), and full 6-timeframe analysis.
Features human-agent disentanglement (compact text for humans, comprehensive text for agents).
"""

import os
import re
import uuid
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
_command = ["vegas", "trend", "crypto_trend", "画线", "隧道"]
_man = """查询加密资产 Vegas 隧道与动态支撑/压力位。
用法: vegas [标的] [周期列表...]
示例: 
  vegas                  (默认查看 ETH 5m 单张大图)
  vegas BTC              (默认查看 BTC 5m 单张大图)
  vegas BTC 1h           (查看 BTC 1h 详细图表)
  vegas BTC 5m 15m 30m   (并发拉取并渲染 5m、15m、30m 3合1拼图)
  vegas ETH 15m，1h、4h  (支持全角逗号、顿号、斜杠分隔)
  vegas BTC all          (查看 5m/15m/30m/1h/4h/1d 全部6大级别)
"""
_tool_description = (
    "获取加密货币(Gate永续合约)多级别 Vegas 隧道(EMA 12/144/169)及动态支撑/阻力位分析。\n"
    "当你需要判断某币种(如 BTC, ETH, PAXG, SOL)的当前压力位、支撑位、趋势方向或回踩买入区间时，务必使用此工具。\n"
    "Agent 调用时默认并发拉取 5m、15m、30m、1h、4h、1d 六个核心级别的行情并输出详尽的数值汇总与 3x2 高清拼图；\n"
    "支持传入特定周期或周期列表（如 'BTC 1h' 或 'ETH 15m 1h 4h'）。\n"
    "返回结果包含完整的文字支撑压力汇总表以及结构化 JSON payload。"
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

ALL_FLAGS = {"ALL", "全", "全部", "全网", "-A", "--ALL"}


def parse_trend_args(args_str: str, is_agent: bool) -> tuple[str, list[str]]:
    """
    Smart argument parser supporting full-width and half-width punctuation.
    - For Human: defaults to ETH and 5m.
    - For Agent: defaults to BTC and all 6 intervals.
    - Supports lists like: `BTC 5m 15m 30m` or `ETH 15m，1h、4h`.
    """
    raw = args_str.strip()
    if not raw:
        if is_agent:
            return "BTC", list(ALL_INTERVALS)
        else:
            return "ETH", ["5m"]

    # Split using whitespace, full-width space (\u3000), commas, Chinese commas/enumeration marks, semicolons, slashes
    tokens = [t.strip() for t in re.split(r'[\s\u3000,，、;/／]+', raw) if t.strip()]

    symbol = None
    intervals = []

    for t in tokens:
        t_up = t.upper()
        if t_up in ALL_FLAGS:
            intervals = list(ALL_INTERVALS)
        elif t_up in INTERVAL_ALIASES:
            std_iv = INTERVAL_ALIASES[t_up]
            if std_iv not in intervals:
                intervals.append(std_iv)
        else:
            if symbol is None:
                symbol = t_up

    if symbol is None:
        symbol = "BTC" if is_agent else "ETH"

    if not intervals:
        intervals = list(ALL_INTERVALS) if is_agent else ["5m"]

    return symbol, intervals


def fetch_gate_klines(symbol: str, interval: str = "1d", limit: int = 300) -> pd.DataFrame:
    """Fetch raw K-lines from Gate.io USDT perpetual contract."""
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

    url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
    params = {
        "contract": contract,
        "interval": interval,
        "limit": limit
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Gate 返回空数据或未收录合约: {contract}")

    df = pd.DataFrame(data)
    df.rename(columns={'t': 'Open time', 'o': 'Open', 'c': 'Close', 'h': 'High', 'l': 'Low', 'v': 'Volume'}, inplace=True)
    df['Open time'] = pd.to_datetime(df['Open time'], unit='s')
    df.set_index('Open time', inplace=True)
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df


def compute_timeframe_indicators(df: pd.DataFrame) -> dict:
    """Compute EMA12, EMA144, EMA169, Vegas tunnel, MACD, RSI, and signals."""
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.ema(length=12, append=True)
    df.ta.ema(length=144, append=True)
    df.ta.ema(length=169, append=True)
    df.ta.rsi(length=14, append=True)

    # Fallbacks if df has fewer than 144/169 rows
    if 'EMA_12' not in df.columns:
        df['EMA_12'] = df['Close']
    if 'EMA_144' not in df.columns:
        df['EMA_144'] = df['Close']
    if 'EMA_169' not in df.columns:
        df['EMA_169'] = df['Close']

    tunnel_top_series = np.maximum(df['EMA_144'], df['EMA_169'])
    tunnel_bot_series = np.minimum(df['EMA_144'], df['EMA_169'])
    tunnel_mid_series = (df['EMA_144'] + df['EMA_169']) / 2.0

    latest = df.iloc[-1]
    close = float(latest['Close'])
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
        "signal_tag": signal_tag,
        "rsi": rsi_val,
        "rsi_desc": rsi_desc,
        "macd_desc": macd_desc,
        "signals": {
            "golden_cross": golden_cross,
            "death_cross": death_cross,
            "bounce_up": bounce_up,
            "bounce_down": bounce_down,
            "true_break_up": true_break_up,
            "false_break_up": false_break_up,
            "true_break_down": true_break_down,
            "false_break_down": false_break_down,
        }
    }


def format_human_compact_text(symbol: str, intervals: list[str], tf_data_dict: dict) -> str:
    """Format a clean, concise 3-5 line summary for human group chats."""
    first_iv = intervals[0] if intervals[0] in tf_data_dict else next(iter(tf_data_dict))
    current_price = tf_data_dict[first_iv]['info']['close']

    if len(intervals) == 1:
        iv = intervals[0]
        info = tf_data_dict[iv]["info"]
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        sig_str = f" | ⚠️ {info['signal_tag']}" if info.get("signal_tag") else ""
        return (
            f"【{symbol} ({iv.upper()}) Vegas 隧道】现价: {current_price:,.2f} USDT (Gate 合约)\n"
            f"• 状态: {info['status_short']}{sig_str} | EMA12: {info['ema12']:,.2f}\n"
            f"• 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} (距{info['key_type']}: {dist_str})\n"
            f"• 指标: RSI {info['rsi']:.1f} ({info['rsi_desc']}) | MACD {info['macd_desc']}"
        )

    # Multi-interval compact bullet points
    lines = [
        f"【{symbol} Vegas 隧道关键位】当前价: {current_price:,.2f} USDT (Gate 合约)"
    ]
    for iv in intervals:
        if iv not in tf_data_dict:
            continue
        info = tf_data_dict[iv]["info"]
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        sig_str = f" | {info['signal_tag']}" if info.get("signal_tag") else ""
        lines.append(
            f"• {iv.upper()}: {info['status_short']} | 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} ({dist_str}) | RSI {info['rsi']:.1f}{sig_str}"
        )

    return "\n".join(lines).strip()


def format_agent_detailed_text(symbol: str, tf_data_dict: dict) -> str:
    """Format full comprehensive report for Agent Observation."""
    first_iv = '5m' if '5m' in tf_data_dict else next(iter(tf_data_dict))
    current_price = tf_data_dict[first_iv]['info']['close']

    lines = [
        f"【{symbol} Vegas 隧道多级别动态支撑压力分析】",
        f"当前价格: {current_price:,.2f} USDT (数据源: Gate.io 合约)",
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
            lines.append(f"  • 状态: {info['status_short']}{sig_str} | EMA12: {info['ema12']:,.2f}")
            lines.append(f"  • Vegas 隧道({info['key_type']}): {info['tunnel_bot']:,.2f} ~ {info['tunnel_top']:,.2f} (距{info['key_type']}: {dist_str})")
            lines.append(f"  • 指标: RSI {info['rsi']:.1f} ({info['rsi_desc']}) | MACD {info['macd_desc']}")
        lines.append("")

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


def draw_adaptive_grid_chart(symbol: str, intervals: list[str], tf_dict: dict, out_path: str, theme: str = ""):
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
        if 'EMA_12' in plot_df.columns:
            ax.plot(x, plot_df['EMA_12'], color=COLORS['ma12'], linewidth=1.1, label='EMA12', alpha=0.9)
        if 'EMA_144' in plot_df.columns and 'EMA_169' in plot_df.columns:
            ax.plot(x, plot_df['EMA_144'], color=COLORS['ma144'], linewidth=0.85, label='EMA144', alpha=0.85)
            ax.plot(x, plot_df['EMA_169'], color=COLORS['ma169'], linewidth=0.85, label='EMA169', alpha=0.85)
            top_line = np.maximum(plot_df['EMA_144'], plot_df['EMA_169'])
            bot_line = np.minimum(plot_df['EMA_144'], plot_df['EMA_169'])
            ax.fill_between(x, bot_line, top_line, color=COLORS['tunnel_fill'], alpha=0.15)

        # Current price dashed line
        ax.axhline(info['close'], color='#FFD700', linestyle='--', linewidth=0.7, alpha=0.75)

        # Title
        dist_str = f"+{info['dist_pct']:.2f}%" if info['dist_pct'] > 0 else f"{info['dist_pct']:.2f}%"
        title_color = COLORS['bull'] if '多头' in info['status_short'] else (COLORS['bear'] if '空头' in info['status_short'] else '#FFD700')
        ax.set_title(
            f"[{iv.upper()}] 现价: {info['close']:,.2f} | 隧道: {info['tunnel_bot']:,.1f}~{info['tunnel_top']:,.1f} | {info['status_short']} ({dist_str})",
            fontsize=9.5, fontweight='bold', color=title_color, pad=6
        )

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
    fig.suptitle(
        f"{symbol} Vegas 隧道动态支撑压力 ({interval_str})  |  现价: {latest_price:,.2f} USDT",
        fontsize=14, fontweight="bold", color="#FFFFFF", y=suptitle_y
    )
    fig.savefig(out_path, dpi=150, facecolor=COLORS["bg"], bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def draw_single_chart(symbol: str, interval: str, source: str, df: pd.DataFrame, config: dict, out_path: str):
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

    # MAs
    ma_configs = [
        {"col": "EMA_12", "color": COLORS["ma12"], "lw": 1.2, "label": "EMA12"},
        {"col": "EMA_144", "color": COLORS["ma144"], "lw": 0.8, "label": "EMA144 (Vegas)"},
        {"col": "EMA_169", "color": COLORS["ma169"], "lw": 0.8, "label": "EMA169 (Vegas)"},
    ]
    for mc in ma_configs:
        col = mc["col"]
        if col in plot_df.columns:
            mask = plot_df[col].notna()
            ax_main.plot(x[mask], plot_df[col][mask], color=mc["color"], linewidth=mc["lw"], label=mc["label"], alpha=0.9)

    if 'EMA_144' in plot_df.columns and 'EMA_169' in plot_df.columns:
        top_line = np.maximum(plot_df['EMA_144'], plot_df['EMA_169'])
        bot_line = np.minimum(plot_df['EMA_144'], plot_df['EMA_169'])
        ax_main.fill_between(x, bot_line, top_line, color="#FFA500", alpha=0.15)

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


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    is_agent = getattr(message.request, "is_agent", False)
    raw_symbol, intervals = parse_trend_args(message.request.args, is_agent=is_agent)

    if "_" not in raw_symbol and not raw_symbol.endswith("USDT") and not raw_symbol.endswith("USD"):
        symbol = raw_symbol + "USDT"
    else:
        symbol = raw_symbol

    chart_dir = os.path.join(os.getcwd(), "data", "charts")
    os.makedirs(chart_dir, exist_ok=True)

    # -------------------------------------------------------------
    # CASE 1: Single Timeframe Mode
    # -------------------------------------------------------------
    if len(intervals) == 1:
        iv = intervals[0]
        try:
            df = fetch_gate_klines(symbol, interval=iv, limit=300)
            source = f"Gate.io Futures ({iv})"
        except Exception as e:
            message.reply(f"500: nemo: 获取 {symbol} 行情失败 (Gate 接口返回错误: {e})。")
            return

        if len(df) < 50:
            message.reply(f"500: nemo: {symbol} 数据过少，无法进行指标计算。")
            return

        info = compute_timeframe_indicators(df)
        chart_filename = f"{raw_symbol}_{iv}_{uuid.uuid4().hex[:8]}.png"
        chart_filepath = os.path.join(chart_dir, chart_filename)
        draw_single_chart(raw_symbol, iv, source, df, config, chart_filepath)

        tf_data_dict = {iv: {"df": df, "info": info}}
        text_reply = format_human_compact_text(raw_symbol, intervals, tf_data_dict)

        message.payload = {
            "symbol": raw_symbol,
            "interval": iv,
            "current_price": info['close'],
            "ema12": info['ema12'],
            "ema144": info['ema144'],
            "ema169": info['ema169'],
            "tunnel": [info['tunnel_bot'], info['tunnel_top']],
            "status": info['status_short'],
            "dist_pct": info['dist_pct'],
            "rsi": info['rsi'],
            "chart_local_path": os.path.abspath(chart_filepath),
        }
        message.reply(text_reply, photo_url=os.path.abspath(chart_filepath))
        return

    # -------------------------------------------------------------
    # CASE 2: Multi-Timeframe Mode (e.g. 5m, 15m, 30m or all 6)
    # -------------------------------------------------------------
    tf_data_dict = {}
    errors = {}

    def fetch_single(iv):
        try:
            df = fetch_gate_klines(symbol, interval=iv, limit=300)
            if len(df) < 50:
                return iv, None, "数据量过少"
            info = compute_timeframe_indicators(df)
            return iv, (df, info), None
        except Exception as e:
            return iv, None, str(e)

    # Concurrently fetch ONLY the requested intervals
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(intervals), 6)) as executor:
        future_map = {executor.submit(fetch_single, iv): iv for iv in intervals}
        for future in concurrent.futures.as_completed(future_map):
            iv, res_tuple, err = future.result()
            if res_tuple:
                df, info = res_tuple
                tf_data_dict[iv] = {"df": df, "info": info}
            else:
                errors[iv] = err

    if not tf_data_dict:
        sample_err = next(iter(errors.values()), "未知错误")
        message.reply(f"500: nemo: 获取 {raw_symbol} 多级别行情失败。错误: {sample_err}")
        return

    # Draw adaptive composite chart matching exact requested intervals
    chart_filename = f"{raw_symbol}_vegas_{uuid.uuid4().hex[:8]}.png"
    chart_filepath = os.path.join(chart_dir, chart_filename)
    draw_adaptive_grid_chart(raw_symbol, intervals, tf_data_dict, chart_filepath, theme=config.get("theme", ""))

    # Text output: detailed for Agent, compact for Human
    if is_agent:
        text_card = format_agent_detailed_text(raw_symbol, tf_data_dict)
    else:
        text_card = format_human_compact_text(raw_symbol, intervals, tf_data_dict)

    # Set structured payload for Agent
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
            "signal": info["signal_tag"]
        }

    first_iv = intervals[0] if intervals[0] in tf_data_dict else next(iter(tf_data_dict))
    message.payload = {
        "symbol": raw_symbol,
        "current_price": tf_data_dict[first_iv]["info"]["close"],
        "levels": agent_levels,
        "chart_local_path": os.path.abspath(chart_filepath)
    }

    message.reply(text_card, photo_url=os.path.abspath(chart_filepath))
