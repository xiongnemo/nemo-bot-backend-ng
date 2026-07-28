"""
Crypto Trend Plugin
-------------------
Fetches K-lines, calculates indicators, draws an annotated chart, and provides a structured
payload for the agent. Supports Binance (crypto).
"""

import os
import uuid
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
import logging

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "加密货币趋势分析"
_command = ["crypto_trend", "trend", "画线"]
_man = "用法: crypto_trend <交易对> [周期]。支持周期: 5m, 15m, 30m, 1h, 4h, 1d, 1w。示例: crypto_trend BTCUSDT 4h"
_tool_description = "获取加密货币(Gate永续合约)近期K线图及技术指标摘要。此工具专门用于视觉+文本多模态分析，返回结果包含一个 JSON payload 和本地图表路径。图中要素包含：1. 主图 K 线，带红色的 EMA12 均线，以及由 EMA144(橙) 和 EMA169(蓝) 构成的 Vegas 隧道。2. 主图上可能标注高价值交易信号：绿色向上箭头(^)=真突破或假跌破(看涨)，红色向下箭头(v)=真跌破或假突破(看跌)，橙色/紫色箭头=隧道支撑/阻力反弹。3. 中部副图为成交量。4. 底部副图为 MACD 及其红绿动能柱。大语言模型应结合图片视觉信号与文本摘要做综合研判。"
_enabled = 1

def fetch_gate_klines(symbol: str, interval: str = "1d", limit: int = 300) -> pd.DataFrame:
    if "_" not in symbol and symbol.endswith("USDT"):
        symbol = symbol[:-4] + "_USDT"
        
    url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
    params = {
        "contract": symbol.upper(),
        "interval": interval,
        "limit": limit
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    
    df = pd.DataFrame(data)
    df.rename(columns={'t': 'Open time', 'o': 'Open', 'c': 'Close', 'h': 'High', 'l': 'Low', 'v': 'Volume'}, inplace=True)
    
    df['Open time'] = pd.to_datetime(df['Open time'], unit='s')
    df.set_index('Open time', inplace=True)
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    df[numeric_cols] = df[numeric_cols].astype(float)
    return df

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    if not args:
        message.reply("400: nemo: 请提供交易对，例如 BTCUSDT 4h")
        return
        
    parts = args.split()
    symbol = parts[0].upper().replace("/", "")
    if "_" not in symbol and not symbol.endswith("USDT") and not symbol.endswith("USD"):
        symbol += "USDT"
        
    interval = parts[1].lower() if len(parts) > 1 else "1d"
    
    valid_intervals = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if interval not in valid_intervals:
        message.reply(f"400: nemo: 不支持的周期 '{interval}'。支持的周期有: {', '.join(valid_intervals)}")
        return
    
    # 1. Fetch data (300 bars for warm-up of EMA169)
    try:
        df = fetch_gate_klines(symbol, interval=interval, limit=300)
        source = f"Gate.io Futures ({interval})"
    except Exception as e_gate:
        message.reply(f"500: nemo: 获取 {symbol} 行情失败 (Gate 接口返回错误)。({e_gate})")
        return
            
    if len(df) < 50:
        message.reply(f"500: nemo: {symbol} 数据过少，无法进行指标计算。")
        return
        
    # 2. Calculate Indicators using pandas-ta
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.ema(length=12, append=True)
    df.ta.ema(length=144, append=True)
    df.ta.ema(length=169, append=True)
    df.ta.rsi(length=14, append=True)
    
    # Detect patterns/signals
    macdh = df['MACDh_12_26_9']
    golden_cross = (macdh > 0) & (macdh.shift(1) <= 0)
    death_cross = (macdh < 0) & (macdh.shift(1) >= 0)
    
    ema12 = df['EMA_12']
    ema144 = df['EMA_144']
    ema169 = df['EMA_169']
    tunnel_top = np.maximum(ema144, ema169)
    tunnel_bot = np.minimum(ema144, ema169)
    tunnel_mid = (ema144 + ema169) / 2
    
    bounce_up = (df['Low'] <= tunnel_top) & (df['Close'] > tunnel_top) & (ema12 > tunnel_mid)
    bounce_up = bounce_up & ~bounce_up.shift(1, fill_value=False)
    
    bounce_down = (df['High'] >= tunnel_bot) & (df['Close'] < tunnel_bot) & (ema12 < tunnel_mid)
    bounce_down = bounce_down & ~bounce_down.shift(1, fill_value=False)
    
    break_up = (df['Close'] > tunnel_top) & (df['Close'].shift(1) <= tunnel_top.shift(1))
    true_break_up = break_up & (ema12 > tunnel_top)
    false_break_up = break_up & (ema12 <= tunnel_top)
    
    break_down = (df['Close'] < tunnel_bot) & (df['Close'].shift(1) >= tunnel_bot.shift(1))
    true_break_down = break_down & (ema12 < tunnel_bot)
    false_break_down = break_down & (ema12 >= tunnel_bot)
    
    # Slice the last 150 bars for plotting
    plot_len = min(150, len(df))
    plot_df = df.tail(plot_len).copy()
    
    # We need NaN for scatter points where condition is False
    # Calculate dynamic offset based on the visible chart range to avoid squashing the Y-axis
    y_max = plot_df['High'].max()
    y_min = plot_df['Low'].min()
    y_range = y_max - y_min if y_max > y_min else y_max * 0.01
    
    offset_small = y_range * 0.05
    offset_large = y_range * 0.10
    
    gc_scatter = np.where(golden_cross.tail(plot_len), plot_df['Low'] - offset_small, np.nan)
    dc_scatter = np.where(death_cross.tail(plot_len), plot_df['High'] + offset_small, np.nan)
    bu_scatter = np.where(bounce_up.tail(plot_len), plot_df['Low'] - offset_small, np.nan)
    bd_scatter = np.where(bounce_down.tail(plot_len), plot_df['High'] + offset_small, np.nan)
    
    tbu_scatter = np.where(true_break_up.tail(plot_len), plot_df['Low'] - offset_large, np.nan)
    fbu_scatter = np.where(false_break_up.tail(plot_len), plot_df['High'] + offset_large, np.nan)
    tbd_scatter = np.where(true_break_down.tail(plot_len), plot_df['High'] + offset_large, np.nan)
    fbd_scatter = np.where(false_break_down.tail(plot_len), plot_df['Low'] - offset_large, np.nan)
    
    # 3. Draw Chart (Perfectly replicating Hermes UI)
    COLORS = {
        "bg":           "#1e1e1e" if "Dark" in config.get("theme", "") else "#FFFFFF",
        "grid":         "#333333" if "Dark" in config.get("theme", "") else "#E8E8E8",
        "text":         "#dddddd" if "Dark" in config.get("theme", "") else "#333333",
        "bull":         "#1E8E3E",
        "bear":         "#C62828",
        "ma12":         "#FF0000",
        "ma144":        "#FFA500",
        "ma169":        "#64B5F6",
        "macd_line":    "#2962FF",
        "macd_signal":  "#FF6D00",
        "macd_pos":     "#1E8E3E",
        "macd_neg":     "#C62828",
    }
    
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'WenQuanYi Micro Hei', 'sans-serif']
    matplotlib.rcParams['axes.unicode_minus'] = False
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    
    n = len(plot_df)
    x = np.arange(n)
    dates = plot_df.index
    
    fig = plt.figure(figsize=(18, 9), facecolor=COLORS["bg"], dpi=150)
    gs = fig.add_gridspec(
        3, 1, height_ratios=[5, 1.2, 1.2],
        hspace=0.05, left=0.04, right=0.96, top=0.93, bottom=0.06,
    )
    
    ax_main = fig.add_subplot(gs[0])
    ax_vol  = fig.add_subplot(gs[1], sharex=ax_main)
    ax_macd = fig.add_subplot(gs[2], sharex=ax_main)
    
    for ax in [ax_main, ax_vol, ax_macd]:
        ax.set_facecolor(COLORS["bg"])
        ax.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7)
        ax.tick_params(colors=COLORS["text"], labelsize=8)
        
    # Candlesticks
    width = 0.6
    for i in range(n):
        o, h, l, c = plot_df["Open"].iloc[i], plot_df["High"].iloc[i], plot_df["Low"].iloc[i], plot_df["Close"].iloc[i]
        color = COLORS["bull"] if c >= o else COLORS["bear"]
        body_bottom = min(o, c)
        body_height = abs(c - o) if abs(c - o) > 0 else (h - l) * 0.01
        ax_main.bar(x[i], body_height, bottom=body_bottom, width=width,
                    color=color, edgecolor=color, linewidth=0.3)
        ax_main.vlines(x[i], l, h, color=color, linewidth=0.4)
        
    # Signals
    if not np.isnan(bu_scatter).all():
        ax_main.scatter(x, bu_scatter, marker='^', s=100, color='orange', zorder=5, label='Bounce Up')
    if not np.isnan(bd_scatter).all():
        ax_main.scatter(x, bd_scatter, marker='v', s=100, color='purple', zorder=5, label='Bounce Down')
    if not np.isnan(tbu_scatter).all():
        ax_main.scatter(x, tbu_scatter, marker='^', s=100, color=COLORS['bull'], zorder=5, label='True Break Up')
    if not np.isnan(fbu_scatter).all():
        ax_main.scatter(x, fbu_scatter, marker='v', s=100, color=COLORS['bear'], zorder=5, label='False Break Up (Fakeout)')
    if not np.isnan(tbd_scatter).all():
        ax_main.scatter(x, tbd_scatter, marker='v', s=100, color=COLORS['bear'], zorder=5, label='True Break Down')
    if not np.isnan(fbd_scatter).all():
        ax_main.scatter(x, fbd_scatter, marker='^', s=100, color=COLORS['bull'], zorder=5, label='False Break Down (Fakeout)')

    # MAs
    ma_configs = [
        {"col": "EMA_12",  "color": COLORS["ma12"],  "lw": 1.2, "label": "EMA12"},
        {"col": "EMA_144", "color": COLORS["ma144"], "lw": 0.8, "label": "EMA144 (Vegas)"},
        {"col": "EMA_169", "color": COLORS["ma169"], "lw": 0.8, "label": "EMA169 (Vegas)"},
    ]
    for mc in ma_configs:
        col = mc["col"]
        if col in plot_df.columns:
            mask = plot_df[col].notna()
            ax_main.plot(x[mask], plot_df[col][mask],
                         color=mc["color"], linewidth=mc["lw"],
                         label=mc["label"], alpha=0.9)

    ax_main.legend(loc="upper left", fontsize=8, framealpha=0.8)
    ax_main.set_ylabel("Price", fontsize=9, color=COLORS["text"])
    
    # Volume
    vol_colors = [COLORS["bull"] if plot_df["Close"].iloc[i] >= plot_df["Open"].iloc[i]
                  else COLORS["bear"] for i in range(n)]
    ax_vol.bar(x, plot_df["Volume"], width=width, color=vol_colors, alpha=0.7)
    ax_vol.set_ylabel("Vol", fontsize=8, color=COLORS["text"])
    ax_vol.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else (f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}")
    ))

    # MACD
    if 'MACDh_12_26_9' in plot_df.columns:
        macd_colors = [COLORS["macd_pos"] if v >= 0 else COLORS["macd_neg"]
                       for v in plot_df["MACDh_12_26_9"]]
        ax_macd.bar(x, plot_df["MACDh_12_26_9"], width=width * 0.8, color=macd_colors, alpha=0.6)
        ax_macd.plot(x, plot_df["MACD_12_26_9"], color=COLORS["macd_line"], linewidth=0.8, label="MACD")
        ax_macd.plot(x, plot_df["MACDs_12_26_9"], color=COLORS["macd_signal"], linewidth=0.8, label="Signal")
        ax_macd.axhline(0, color=COLORS["grid"], linewidth=0.5)
        ax_macd.legend(loc="upper left", fontsize=7, framealpha=0.8)
    ax_macd.set_ylabel("MACD", fontsize=8, color=COLORS["text"])

    # X-axis
    plt.setp(ax_main.get_xticklabels(), visible=False)
    plt.setp(ax_vol.get_xticklabels(), visible=False)

    tick_idx = np.linspace(0, n - 1, min(15, n), dtype=int) if n > 10 else np.arange(n)
    ax_macd.set_xticks(tick_idx)
    ax_macd.set_xticklabels(
        [dates[i].strftime("%m/%d" if interval in ("1d", "1w") else "%m/%d %H:%M")
         for i in tick_idx],
        fontsize=7, rotation=30
    )

    # Title
    last_close = plot_df["Close"].iloc[-1]
    first_close = plot_df["Close"].iloc[0]
    pct = ((last_close - first_close) / first_close * 100) if first_close else 0
    sign = "+" if pct >= 0 else ""
    title_color = COLORS["bull"] if pct >= 0 else COLORS["bear"]

    fig.suptitle(
        f"{symbol}  |  {last_close:,.2f}  ({sign}{pct:.1f}%)  |  {interval}  |  {source}",
        fontsize=16, fontweight="bold", color=title_color, y=0.97,
    )

    # Save
    import uuid
    chart_filename = f"{symbol}_{uuid.uuid4().hex[:8]}.png"
    chart_dir = os.path.join(os.getcwd(), "data", "charts")
    os.makedirs(chart_dir, exist_ok=True)
    chart_filepath = os.path.join(chart_dir, chart_filename)
    
    fig.savefig(chart_filepath, dpi=150, facecolor=COLORS["bg"],
                bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)    
    # 4. Construct Payload
    latest = df.iloc[-1]
    
    # Basic MACD sentiment logic
    macd_val = latest.get('MACD_12_26_9', 0)
    macd_sig = latest.get('MACDs_12_26_9', 0)
    macd_trend = "Bullish (多头)" if macd_val > macd_sig else "Bearish (空头)"
    if golden_cross.iloc[-1]:
        macd_trend += " - 刚发生金叉!"
    elif death_cross.iloc[-1]:
        macd_trend += " - 刚发生死叉!"
        
    # Basic RSI logic
    rsi_val = latest.get('RSI_14', 50)
    rsi_status = "Neutral (中性)"
    if rsi_val > 70:
        rsi_status = "Overbought (超买)"
    elif rsi_val < 30:
        rsi_status = "Oversold (超卖)"
        
    # Vegas Tunnel logic
    vegas_status = "Neutral"
    if latest['Close'] > tunnel_top.iloc[-1]:
        vegas_status = "Above Tunnel (多头趋势)"
    elif latest['Close'] < tunnel_bot.iloc[-1]:
        vegas_status = "Below Tunnel (空头趋势)"
    else:
        vegas_status = "Inside Tunnel (震荡/变盘)"
        
    if bounce_up.iloc[-1]:
        vegas_status += " - 隧道支撑反弹!"
    elif bounce_down.iloc[-1]:
        vegas_status += " - 隧道阻力受挫!"
    elif true_break_up.iloc[-1]:
        vegas_status += " - 真突破 (向上)!"
    elif false_break_up.iloc[-1]:
        vegas_status += " - 假突破 (向上)!"
    elif true_break_down.iloc[-1]:
        vegas_status += " - 真突破 (向下)!"
    elif false_break_down.iloc[-1]:
        vegas_status += " - 假突破 (向下)!"
        
    # Recent signals summary (last 5 days)
    recent_signals = []
    last_5 = plot_df.tail(5)
    for i, (idx, row) in enumerate(last_5.iterrows()):
        date_str = idx.strftime('%m-%d')
        if golden_cross.loc[idx]: recent_signals.append(f"{date_str}: MACD金叉")
        if death_cross.loc[idx]: recent_signals.append(f"{date_str}: MACD死叉")
        if bounce_up.loc[idx]: recent_signals.append(f"{date_str}: Vegas隧道支撑反弹")
        if bounce_down.loc[idx]: recent_signals.append(f"{date_str}: Vegas隧道阻力受压")
        if true_break_up.loc[idx]: recent_signals.append(f"{date_str}: Vegas向上真突破")
        if false_break_up.loc[idx]: recent_signals.append(f"{date_str}: Vegas向上假突破")
        if true_break_down.loc[idx]: recent_signals.append(f"{date_str}: Vegas向下真突破")
        if false_break_down.loc[idx]: recent_signals.append(f"{date_str}: Vegas向下假突破")
        
    if not recent_signals:
        recent_signals.append("近5天无明显技术信号交叉")

    payload = {
        "symbol": symbol,
        "source": source,
        "current_price": latest['Close'],
        "technical_indicators": {
            "RSI_14": {
                "value": round(rsi_val, 2),
                "status": rsi_status
            },
            "MACD": {
                "histogram": round(latest.get('MACDh_12_26_9', 0), 2),
                "trend": macd_trend
            },
            "Vegas_Tunnel": {
                "status": vegas_status
            },
            "Recent_Signals_5d": recent_signals
        },
        "chart_local_path": os.path.abspath(chart_filepath)
    }
    
    message.payload = payload
    message.reply(
        f"已成功获取 {symbol} 的数据并生成带有趋势标注的图表 (数据源: {source})。",
        photo_url=os.path.abspath(chart_filepath)
    )
