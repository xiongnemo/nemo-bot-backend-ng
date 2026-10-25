"""
Polymarket Prediction Market & Smart Money Tracker Plugin
---------------------------------------------------------
Enables querying Polymarket prediction markets, odds, probabilities,
and tracking whale/smart-money addresses on Polygon.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# Mandatory Plugin Attributes
# ===========================
_name = "Polymarket预测市场与聪明钱"
_command = ["poly", "polymarket", "预测市场", "聪明钱", "赔率"]
_man = """查询 Polymarket 去中心化预测市场事件、实时胜率赔率与巨鲸聪明钱持仓动向。
用法:
  /poly <关键词>             - 搜索预测市场事件与盘口赔率（如 /poly S赛, /poly HLE, /poly 比特币 100k, /poly 美联储）
  /poly <0x钱包地址>         - 追踪指定 Polygon/Polymarket 巨鲸钱包持仓、均价与近期开仓流水
  /poly whale <0x钱包地址>   - 同上（显式指定巨鲸地址模式）

示例:
  /poly HLE IG              - 查询英雄联盟世界赛 HLE vs IG 的双方胜率与盘口赔率
  /poly S赛                 - 查询当前 S 赛世界赛相关所有热门预测事件
  /poly 比特币 11月          - 查询比特币在 11 月各个目标价位/区间的达成概率
  /poly 0x6ac5bb06a9eb05641fd5e82640268b92f3ab4b6e - 追踪昨晚重仓 S 赛的巨鲸持仓
"""

_tool_description = (
    "专用于查询去中心化预测市场（Polymarket）的实时事件行情、胜率概率、赔率折算以及链上聪明钱巨鲸钱包动向。\n"
    "当你需要获取：\n"
    "1. 英雄联盟 S 赛/世界赛/体育赛事的胜负概率与盘口赔率；\n"
    "2. 加密货币行情预测（例如比特币在某月底能否突破某价格、达成概率多少）；\n"
    "3. 宏观政策与大选预测（如美联储某次会议降息概率、美国大选赔率）；\n"
    "4. 链上巨鲸/聪明钱钱包在预测市场的持仓头寸、均价与最新交易。\n"
    "参数可直接传入搜索词（如 'HLE'、'LoL'、'Bitcoin 100k'）或 EVM 钱包地址（'0x...'）。"
)

_parameters = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词（如 'HLE'、'S赛'、'Bitcoin'、'美联储'）或 0x 开头的巨鲸钱包地址。",
        },
        "action": {
            "type": "string",
            "enum": ["search", "whale"],
            "description": "操作类型：'search' 为搜索预测市场事件赔率，'whale' 为查询巨鲸钱包持仓流水。默认为 'search'（若传入地址自动判定为 'whale'）。",
        },
    },
    "required": ["query"],
}

_enabled = True

GAMMA_SEARCH_URL = "https://gamma-api.polymarket.com/public-search?q={0}"
DATA_POSITIONS_URL = "https://data-api.polymarket.com/positions?user={0}"
DATA_ACTIVITY_URL = "https://data-api.polymarket.com/activity?user={0}&limit={1}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# 常见中文术语与月份映射，帮助精准命中 Polymarket 英文盘口
TERM_MAP = {
    "大饼": "Bitcoin",
    "比特币": "Bitcoin",
    "以太": "Ethereum",
    "以太坊": "Ethereum",
    "索拉纳": "Solana",
    "s赛": "LoL Worlds",
    "世界赛": "LoL Worlds",
    "英雄联盟": "LoL",
    "韩华": "Hanwha",
    "降息": "Fed rate cut",
    "加息": "Fed rate hike",
    "美联储": "Fed",
    "大选": "US Election",
    "特朗普": "Trump",
    "哈里斯": "Harris",
}

# 战队缩写映射至 Polymarket 官方全称/关键字
TEAM_MAP = {
    r"\bhle\b": "Hanwha",
    r"\big\b": "Invictus",
    r"\bblg\b": "Bilibili",
    r"\btes\b": "Top Esports",
    r"\bwbg\b": "Weibo",
    r"\bjdg\b": "JD Gaming",
    r"\bgeng\b": "Gen.G",
    r"\bdk\b": "Dplus",
}

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def _clean_and_translate_query(raw_query: str) -> str:
    """清理并映射中文关键词至 Polymarket 英文检索项"""
    text = raw_query.strip()
    
    # 替换中文月份：如 '11月' -> 'November', '11月底' -> 'November'
    def _replace_month(m):
        m_num = int(m.group(1))
        if 1 <= m_num <= 12:
            return MONTH_NAMES[m_num] + " "
        return m.group(0)

    text = re.sub(r"(\d{1,2})月(?:底)?", _replace_month, text)
    text = text.replace("月底", "")

    # 替换常见中文金融/赛事术语
    for zh_term, en_term in sorted(TERM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if zh_term in text.lower():
            text = re.sub(re.escape(zh_term), en_term, text, flags=re.IGNORECASE)

    # 替换战队缩写为 Polymarket 官方全称/关键词
    for pat, rep in TEAM_MAP.items():
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)

    # 去除多余空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_json(url: str, timeout: int = 8) -> Any:
    """发送 HTTP GET 请求并返回解析后的 JSON 对象"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_volume(vol: Any) -> str:
    """将成交量格式化为易读的美元金额"""
    try:
        v = float(vol or 0)
        if v >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v / 1_000:.1f}K"
        return f"${v:.0f}"
    except Exception:
        return "$0"


def _format_odds(prob: float) -> str:
    """将概率 (0.0~1.0) 格式化为欧式小数赔率与百分比"""
    pct_str = f"{prob * 100:.1f}%"
    if prob >= 0.01:
        odds = 1.0 / prob
        return f"{pct_str} (~{odds:.2f})"
    if prob > 0:
        return f"{pct_str} (>100)"
    return "0.0%"


def handle_whale_query(address: str) -> str:
    """查询指定巨鲸钱包的持仓与最近交易"""
    address = address.lower().strip()
    if not re.match(r"^0x[a-f0-9]{40}$", address):
        return f"400: nemo: 无效的 EVM 钱包地址格式: {address}，必须为 0x 开头的 42 位十六进制字符串"

    # 1. 查询当前持仓头寸
    try:
        positions_raw = _fetch_json(DATA_POSITIONS_URL.format(address), timeout=8)
    except Exception as e:
        logger.warning(f"Failed to fetch Polymarket positions for {address}: {e}")
        return f"502: nemo: 无法从 Polymarket 获取该钱包持仓数据，上游接口错误: {e}"

    if not isinstance(positions_raw, list):
        positions_raw = []

    # 过滤出有真实持仓的有效头寸并按当前价值倒序排序
    active_positions = [p for p in positions_raw if float(p.get("currentValue", 0)) > 1.0]
    active_positions.sort(key=lambda x: float(x.get("currentValue", 0)), reverse=True)

    # 2. 查询近期开仓流水
    recent_activities = []
    try:
        act_raw = _fetch_json(DATA_ACTIVITY_URL.format(address, 5), timeout=8)
        if isinstance(act_raw, list):
            recent_activities = act_raw[:3]
    except Exception as e:
        logger.debug(f"Failed to fetch activity for {address}: {e}")

    total_value = sum(float(p.get("currentValue", 0)) for p in active_positions)

    lines = [
        f"🐋 【Polymarket 巨鲸追踪】",
        f"• 监控地址: `{address[:6]}...{address[-4:]}` ({address})",
        f"• 当前活跃持仓总值: ${_format_volume(total_value).lstrip('$')} ({len(active_positions)} 个活跃盘口)",
    ]

    if active_positions:
        lines.append("\n📊 【当前重仓头寸 (Top 4)】")
        for idx, p in enumerate(active_positions[:4], 1):
            title = p.get("title", "未知事件")
            outcome = p.get("outcome", "YES")
            val = float(p.get("currentValue", 0))
            avg_p = float(p.get("avgPrice", 0))
            cur_p = float(p.get("curPrice", 0))
            pnl_pct = float(p.get("percentPnl", 0))
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"

            lines.append(
                f"  {idx}. 《{title}》 → 【{outcome}】\n"
                f"     持仓估值: ${_format_volume(val).lstrip('$')} | 均价: {avg_p:.1%} (当前: {cur_p:.1%}) | 浮盈亏: {pnl_str}"
            )

    if recent_activities:
        lines.append("\n⏱️ 【最近交易动态 (Latest 3)】")
        for act in recent_activities:
            side = act.get("side", "BUY")
            side_str = "🟢 买入开仓" if side == "BUY" else "🔴 卖出平仓"
            title = act.get("title", "")
            outcome = act.get("outcome", "")
            usdc_size = float(act.get("usdcSize", 0))
            price = float(act.get("price", 0))
            ts = act.get("timestamp", 0)
            t_str = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8))).strftime("%m-%d %H:%M") if ts else ""

            lines.append(
                f"  • [{t_str}] {side_str} 【{outcome}】 ${usdc_size:,.1f} (单价: {price:.1%}) → 《{title}》"
            )

    return "\n".join(lines)


def handle_market_search(query: str) -> str:
    """搜索 Polymarket 预测市场事件与盘口"""
    raw_query = query.strip()
    if not raw_query:
        return "400: nemo: 请提供要搜索的预测市场关键词，例如 `/poly HLE`、`/poly S赛`、`/poly 比特币 100k`"

    translated_query = _clean_and_translate_query(raw_query)

    # 优先搜索翻译/清理后的关键词，若无结果再尝试原始关键词
    events = []
    queries_to_try = [translated_query]
    if raw_query.lower() != translated_query.lower():
        queries_to_try.append(raw_query)

    for q in queries_to_try:
        try:
            url = GAMMA_SEARCH_URL.format(urllib.parse.quote(q))
            res = _fetch_json(url, timeout=8)
            events = res.get("events", []) or []
            if events:
                break
        except Exception as e:
            logger.warning(f"Polymarket search failed for query '{q}': {e}")

    if not events:
        return f"404: nemo: 未在 Polymarket 找到与 '{raw_query}' 相关的预测事件或盘口。建议换用英文赛事简写（如 LoL, HLE, T1, BTC, Fed）重试。"

    lines = [f"🎲 【Polymarket 预测市场盘口】(关键词: {raw_query})"]

    # 遍历展示前 3 个最具代表性的预测事件
    event_count = 0
    for e in events:
        if event_count >= 3:
            break

        title = e.get("title", "").strip()
        vol_str = _format_volume(e.get("volume", 0))
        markets = e.get("markets", []) or []

        # 过滤未开盘或已关闭的无效市场
        active_markets = [m for m in markets if not m.get("closed", False)]
        if not active_markets:
            active_markets = markets[:2]  # 若全为 closed，保留前两个展示历史赛果

        if not active_markets:
            continue

        event_count += 1
        lines.append(f"\n🏆 事件: 《{title}》 (总下注池: {vol_str})")

        # 每个事件展示最多 3 个具体细分盘口
        for m in active_markets[:3]:
            q_text = m.get("question", "").strip()
            outcomes = m.get("outcomes", [])
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception:
                    outcomes = ["Yes", "No"]

            prices = m.get("outcomePrices", [])
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    prices = []

            p_strs = []
            for idx, o in enumerate(outcomes):
                if idx < len(prices):
                    try:
                        p_float = float(prices[idx])
                        p_strs.append(f"【{o}】: {_format_odds(p_float)}")
                    except Exception:
                        p_strs.append(f"【{o}】: {prices[idx]}")

            odds_line = " vs ".join(p_strs) if p_strs else "暂无赔率"

            if q_text and q_text != title:
                lines.append(f"  • {q_text} → {odds_line}")
            else:
                lines.append(f"  • 胜率/赔率 → {odds_line}")

    lines.append("\n💡 赔率说明: 百分比为市场概率共识，括号内为对应欧式小数赔率 (如 72.5% ~1.38)。")
    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args_str = (message.request.args or "").strip()

    # 1. 解析可能由 LLM 传回的 JSON 参数
    query = ""
    action = "search"

    if args_str.startswith("{") and args_str.endswith("}"):
        try:
            param_dict = json.loads(args_str)
            query = str(param_dict.get("query", "")).strip()
            action = str(param_dict.get("action", "search")).strip().lower()
        except Exception:
            pass

    if not query:
        query = args_str

    if not query:
        reply_text = (
            "400: nemo: 请提供要查询的预测市场内容或钱包地址。\n"
            "用法示例:\n"
            "  /poly HLE IG         - 查英雄联盟 S 赛 HLE 对阵 IG 胜率赔率\n"
            "  /poly 比特币 100k    - 查比特币达到 10 万美元各时间段预测概率\n"
            "  /poly 0x6ac5...      - 查 Polymarket 巨鲸钱包持仓"
        )
        message.reply(reply_text)
        return reply_text

    # 2. 判断是否为巨鲸钱包地址模式
    # 支持形如 /poly whale 0x... 或直接 /poly 0x...
    m_addr = re.search(r"0x[a-fA-F0-9]{40}", query)
    if action == "whale" or query.lower().startswith("whale") or m_addr:
        target_addr = m_addr.group(0) if m_addr else query.replace("whale", "").strip()
        reply_text = handle_whale_query(target_addr)
    else:
        reply_text = handle_market_search(query)

    message.reply(reply_text)
    return reply_text
