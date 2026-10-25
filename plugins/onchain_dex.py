"""
On-Chain DEX & Alpha Market Data Plugin
---------------------------------------
Provides real-time on-chain pricing, liquidity, transaction sentiment,
market cap, and contract address (CA) for DEX tokens across Solana,
Ethereum, Base, BSC, and other public blockchains.
"""

import logging
import time
import urllib.request
import json
from typing import Optional, Dict, Any, List

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# Mandatory Plugin Attributes
# ===========================
_name = "链上DEX与Alpha行情"
_command = ["dex", "alpha", "链上", "土狗", "冲狗", "合约地址"]
_man = """查询全网区块链 DEX 及 Web3 创新区实时代币行情与合约信息。
用法:
  /dex <代币代码或合约地址CA> [链]
示例:
  /dex KURUMI                       - 智能搜索全链流动性最高的 KURUMI 代币池 (涵盖 Solana/以太坊/BSC/Base 等)
  /dex Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump - 通过合约地址(CA)精确查询
  /dex MOODENG solana               - 仅搜索 Solana 链上池子
  /dex PEPE eth                     - 仅搜索 Ethereum 链上池子

💡 提示: 链上同名代币较多，请重点核对合约地址(CA)与资金池流动性规模(Liquidity)，注意甄别风险。
"""
_tool_description = (
    "专用于查询去中心化交易所（DEX，涵盖 Solana、Ethereum、Base、BSC、Arbitrum 等）未在主流交易所主板上线的早期/Meme代币实时行情。\n"
    "当你需要获取链上代币的当前价格、流动性池规模(Liquidity)、市值(Market Cap/FDV)、24小时成交量与买卖交易情绪(Buy/Sell Txns)、"
    "上线时间以及合约地址(CA)时，务必使用此工具。\n"
    "参数可直接传入代币 Symbol（如 'KURUMI'）或合约地址 Mint/CA（如 'Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump'）。"
)
_enabled = 1

DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q={0}"
DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens/{0}"
GECKOTERMINAL_SEARCH_URL = "https://api.geckoterminal.com/api/v2/search/pools?query={0}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _http_get(url: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
    except Exception as e:
        logger.debug("HTTP GET failed for %s: %s", url, e)
    return None


def format_num(val: Any, is_usd: bool = True, decimals: int = 2) -> str:
    """Format numbers into human-readable units ($1.23 M, $45.6 K, etc.)."""
    if val is None:
        return "N/A"
    try:
        f = float(val)
    except (ValueError, TypeError):
        return str(val)

    prefix = "$" if is_usd else ""
    if abs(f) >= 1e9:
        return f"{prefix}{f/1e9:.2f} B"
    elif abs(f) >= 1e6:
        return f"{prefix}{f/1e6:.2f} M"
    elif abs(f) >= 1e3:
        return f"{prefix}{f/1e3:.2f} K"
    elif abs(f) >= 1:
        return f"{prefix}{f:,.{decimals}f}"
    elif abs(f) > 0:
        s = f"{f:.8f}".rstrip("0")
        return f"{prefix}{s}"
    return f"{prefix}0.00"


def format_age(pair_created_at_ms: Optional[int]) -> str:
    """Format timestamp into human-readable age (e.g. 12 天前, 3 小时前)."""
    if not pair_created_at_ms:
        return "未知"
    now_ms = time.time() * 1000
    diff_sec = max(0, (now_ms - pair_created_at_ms) / 1000)
    if diff_sec < 60:
        return "刚刚"
    elif diff_sec < 3600:
        return f"{int(diff_sec // 60)} 分钟前"
    elif diff_sec < 86400:
        return f"{int(diff_sec // 3600)} 小时前"
    else:
        days = int(diff_sec // 86400)
        return f"{days} 天前"


def is_contract_address(s: str) -> bool:
    """Check if input string is likely a blockchain contract address (EVM 0x... or Solana base58)."""
    s = s.strip()
    if s.startswith("0x") and len(s) == 42:
        return True
    if len(s) >= 32 and len(s) <= 44 and all(c.isalnum() for c in s):
        if any(c.isdigit() for c in s) and not s.isalpha():
            return True
    return False


def fetch_onchain_data(query: str, chain_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search on-chain token pairs across DexScreener and GeckoTerminal.
    Returns ranked and filtered list of pairs sorted by liquidity descending.
    """
    clean_q = query.strip()
    pairs = []

    # 1. Primary Engine: DexScreener
    if is_contract_address(clean_q):
        url = DEXSCREENER_TOKENS_URL.format(urllib.request.quote(clean_q))
        res = _http_get(url)
        if res and res.get("pairs"):
            pairs = res["pairs"]

    if not pairs:
        url = DEXSCREENER_SEARCH_URL.format(urllib.request.quote(clean_q))
        res = _http_get(url)
        if res and res.get("pairs"):
            pairs = res["pairs"]

    # 2. Fallback Engine: GeckoTerminal if DexScreener returns empty
    if not pairs:
        gt_url = GECKOTERMINAL_SEARCH_URL.format(urllib.request.quote(clean_q))
        gt_res = _http_get(gt_url)
        if gt_res and gt_res.get("data"):
            for p in gt_res["data"]:
                attr = p.get("attributes", {})
                chain_id = p.get("relationships", {}).get("network", {}).get("data", {}).get("id", "")
                pairs.append({
                    "chainId": chain_id,
                    "dexId": p.get("relationships", {}).get("dex", {}).get("data", {}).get("id", "dex"),
                    "url": f"https://www.geckoterminal.com/{chain_id}/pools/{attr.get('address')}",
                    "baseToken": {
                        "name": attr.get("name", "").split("/")[0].strip(),
                        "symbol": attr.get("name", "").split("/")[0].strip(),
                        "address": attr.get("address", ""),
                    },
                    "quoteToken": {
                        "symbol": attr.get("name", "").split("/")[1].strip() if "/" in attr.get("name", "") else "USDT",
                    },
                    "priceUsd": attr.get("base_token_price_usd"),
                    "liquidity": {"usd": float(attr.get("reserve_in_usd", 0) or 0)},
                    "volume": {"h24": float(attr.get("volume_usd", {}).get("h24", 0) or 0)},
                    "priceChange": {"h24": float(attr.get("price_change_percentage", {}).get("h24", 0) or 0)},
                    "fdv": float(attr.get("fdv_usd", 0) or 0),
                    "marketCap": float(attr.get("market_cap_usd", 0) or 0),
                })

    if chain_filter:
        cf = chain_filter.lower().strip()
        pairs = [p for p in pairs if cf in p.get("chainId", "").lower()]

    def get_liq(p):
        try:
            return float(p.get("liquidity", {}).get("usd", 0) or 0)
        except Exception:
            return 0.0

    pairs.sort(key=get_liq, reverse=True)
    return pairs


def build_onchain_report(query: str, pairs: List[Dict[str, Any]], is_fallback: bool = False) -> str:
    """Format the top on-chain pair report with price, liquidity, sentiment, and CA."""
    if not pairs:
        return f"404: nemo: 未在链上或 DEX 搜索到关于 '{query}' 的流动性池数据。\n💡 建议: 请尝试输入完整的合约地址(CA)进行精确查询。"

    top = pairs[0]
    chain = top.get("chainId", "unknown").upper()
    dex = top.get("dexId", "unknown")
    base = top.get("baseToken", {})
    quote = top.get("quoteToken", {})
    base_sym = base.get("symbol", query.upper())
    quote_sym = quote.get("symbol", "USD")
    base_name = base.get("name", base_sym)
    ca = base.get("address", "未知")

    price_usd = format_num(top.get("priceUsd"))
    price_native = top.get("priceNative")
    native_str = f" ({price_native} {quote_sym})" if price_native else ""

    ch = top.get("priceChange", {})
    ch5m = ch.get("m5")
    ch1h = ch.get("h1")
    ch24h = ch.get("h24")

    def fmt_ch(val):
        if val is None:
            return "--"
        f = float(val)
        emoji = "🟢" if f >= 0 else "🔴"
        sign = "+" if f >= 0 else ""
        return f"{emoji} {sign}{f:.2f}%"

    liq = format_num(top.get("liquidity", {}).get("usd"))
    vol24 = format_num(top.get("volume", {}).get("h24"))
    mc = format_num(top.get("marketCap") or top.get("fdv"))

    txns = top.get("txns", {})
    tx24 = txns.get("h24", {})
    buys = tx24.get("buys", 0)
    sells = tx24.get("sells", 0)
    ratio_str = f"{buys/sells:.2f}" if sells > 0 else ("多头压倒" if buys > 0 else "--")
    sentiment = "🟢 净买入" if buys >= sells else "🔴 净抛售"

    age_str = format_age(top.get("pairCreatedAt"))
    url = top.get("url", "")

    info = top.get("info", {})
    socials = info.get("socials", [])
    websites = info.get("websites", [])
    link_parts = []
    for s in socials:
        stype = s.get("type", "link").capitalize()
        link_parts.append(f"[{stype}]({s.get('url')})")
    for w in websites:
        link_parts.append(f"[官网]({w.get('url')})")
    links_str = " | ".join(link_parts) if link_parts else "无"

    header_prefix = "ℹ️ 各大主板交易所未收录，已自动为你展示链上 DEX 行情:\n\n" if is_fallback else ""

    lines = [
        f"{header_prefix}⛓️【链上/DEX 行情】{base_name} (${base_sym})",
        f"• 交易对: {base_sym}/{quote_sym} | 网络: {chain} ({dex})",
        f"• 实时价格: {price_usd}{native_str}",
        f"• 周期涨跌: 5m: {fmt_ch(ch5m)} | 1h: {fmt_ch(ch1h)} | 24h: {fmt_ch(ch24h)}",
        f"• 资金池流动性 (Liquidity): {liq}",
        f"• 24H 成交量 (Volume): {vol24} | 市值/FDV: {mc}",
        f"• 24H 交易情绪: {buys} 买 / {sells} 卖 ({sentiment}, 情绪买卖比: {ratio_str})",
        f"• 上线时长: {age_str}",
        f"• 合约地址 (CA):\n`{ca}`",
    ]

    if links_str != "无":
        lines.append(f"• 社区/外链: {links_str}")

    seen_cas = {ca}
    alt_tokens = []
    for p in pairs[1:]:
        p_ca = p.get("baseToken", {}).get("address", "")
        p_liq = float(p.get("liquidity", {}).get("usd", 0) or 0)
        p_chain = p.get("chainId", "unknown").upper()
        if p_ca and p_ca not in seen_cas and p_liq > 1000:
            seen_cas.add(p_ca)
            alt_tokens.append(f"- [{p_chain}/{p.get('dexId')}] 流动性 {format_num(p_liq)} | CA: `{p_ca[:8]}...{p_ca[-6:]}`")
            if len(alt_tokens) >= 3:
                break

    if alt_tokens:
        lines.append("")
        lines.append("⚠️ 【同名/跨链其它池警示】链上存在同名合约，请仔细核对 CA:")
        lines.extend(alt_tokens)

    if url:
        lines.append(f"\n📊 看盘图表: {url}")

    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    raw_args = ""
    if hasattr(message, "request") and getattr(message.request, "args", None):
        raw_args = message.request.args.strip()
    elif hasattr(message, "text"):
        raw_args = message.text.strip()

    tokens = [t.strip() for t in raw_args.split() if t.strip()]
    if not tokens:
        message.reply("400: nemo: 请提供链上代币代码或合约地址(CA)，例如 `/dex KURUMI` 或 `/dex Ew8KqgSitYucieR5KnSAL2SUFspcwA8AgSuZ5xWspump`")
        return

    query = tokens[0]
    chain_filter = tokens[1] if len(tokens) > 1 else None

    logger.info("[OnChain DEX] Querying on-chain for query='%s', chain_filter='%s'", query, chain_filter)
    pairs = fetch_onchain_data(query, chain_filter)
    report = build_onchain_report(query, pairs)
    message.reply(report)
