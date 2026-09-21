import requests
import traceback
import json
import logging
import concurrent.futures
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["ticker", "coin", "crypto", "币", "加密货币", "合约"]
_name = "统一市场行情查询"
_man = """查询加密资产及传统金融(TradFi)实时行情与合约多空情绪。
用法: {0} <标的> [交易所/全网参数] [细分市场]
示例: 
  {0} BTC              (人类默认仅查币安 Binance，避免群聊刷屏)
  {0} BTC -a           (推荐 flag: -a / --all / 全网，并发返回 Gate+Binance+OKX+Hyperliquid 全平台深度与多空情绪)
  {0} BTC okx          (单独查 OKX)
  {0} ETH hl           (单独查 Hyperliquid)
  {0} ETH/BTC          (查 Gate 交叉盘)
  {0} MSFT             (查 Gate TradFi 美股代币)
  {0} BNB binance spot (查 Binance 现货)

推荐聚合 Flag: -a, --all, all, 全网, 全平台 (返回全部支持的交易所数据)
支持的交易所: binance (默认), gate, okx, hl / hyperliquid
支持的市场: 合约 / futures (默认), 现货 / spot
"""
_man = _man.replace("{0}", _command[0])

_tool_description = (
    "非常强大的加密资产及美股(TradFi)实时行情与合约多空情绪查询引擎。\n"
    "当你需要获取加密货币的当前价格、24小时涨跌幅、或者合约的【资金费率(Funding Rate)】、【全网多空人数比】、【大户持仓/账户多空比】、【主动买卖比】和【未平仓量(OI)】时，务必使用此工具。\n"
    "Agent 调用时默认同时并发向 Gate、Binance、OKX、Hyperliquid 发送请求并聚合返回全部平台的最新行情与合约深度数据。也支持指定单一交易所（如 'BTC binance' 或 'ETH hl'）。\n"
    "参数 (args) 必须是个字符串，例如 'BTC' 或 'ETH binance'。"
)
_enabled = 1

def format_large_number(num):
    if num >= 1e8:
        return f"{num/1e8:.2f} 亿"
    elif num >= 1e4:
        return f"{num/1e4:.2f} 万"
    return f"{num:,.2f}"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0'
}

def fetch_url(url, timeout=3.5):
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug(f"fetch_url error for {url}: {e}")
    return None

def fetch_post(url, json_data, timeout=3.5):
    try:
        headers = {'Content-Type': 'application/json', **DEFAULT_HEADERS}
        r = requests.post(url, json=json_data, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug(f"fetch_post error for {url}: {e}")
    return None

def fetch_gate(base: str, quote: str, market: str, attempts: list):
    markets_to_try = []
    if market in ['spot', '现货']:
        markets_to_try = ['spot']
    elif market in ['futures', '合约', 'contract']:
        markets_to_try = ['futures']
    elif market in ['tradfi']:
        markets_to_try = ['tradfi']
    else:
        markets_to_try = ['futures', 'spot', 'tradfi']

    for m in markets_to_try:
        try:
            if m == 'futures':
                pair = f"{base}_{quote}"
                attempts.append(f"Gate 合约 ({pair})")
                
                margin = quote.lower() if quote.lower() in ['usdt', 'btc', 'usd'] else 'usdt'
                urls = {
                    'ticker': f"https://api.gateio.ws/api/v4/futures/{margin}/tickers?contract={pair}",
                    'stats': f"https://api.gateio.ws/api/v4/futures/{margin}/contract_stats?contract={pair}"
                }
                
                results = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    future_to_url = {executor.submit(fetch_url, url): key for key, url in urls.items()}
                    for future in concurrent.futures.as_completed(future_to_url):
                        key = future_to_url[future]
                        results[key] = future.result()
                
                ticker_data = results.get('ticker')
                if ticker_data and isinstance(ticker_data, list) and len(ticker_data) > 0:
                    d = ticker_data[0]
                    last = float(d['last'])
                    change = float(d['change_percentage']) / 100
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['high_24h'])
                    low = float(d['low_24h'])
                    mark = float(d.get('mark_price', 0))
                    vol = float(d.get('volume_24h_quote', 0))
                    
                    res = f"[GATE USDT合约] {pair}\n"
                    res += f"当前价: {last} (标记: {mark})\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} USDT\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    
                    # Advanced Stats
                    stats_data = results.get('stats')
                    funding = float(d.get('funding_rate', 0)) * 100
                    
                    res += f"-------------------------\n"
                    res += f"【合约高阶数据】\n"
                    res += f"资金费率: {funding:.4f}%\n"
                    
                    if stats_data and isinstance(stats_data, list) and len(stats_data) > 0:
                        st = stats_data[0]
                        lsr = float(st.get('lsr_account', 0))
                        long_users = int(st.get('long_users', 0))
                        short_users = int(st.get('short_users', 0))
                        res += f"全网多空比: {lsr:.2f} (多军 {long_users} 人 / 空军 {short_users} 人)\n"
                        
                        top_lsr = float(st.get('top_lsr_account', 0))
                        res += f"大户多空比: {top_lsr:.2f}\n"
                        
                        oi = float(st.get('open_interest_usd', 0))
                        if oi == 0:
                            oi = float(st.get('open_interest', 0))
                            res += f"未平仓量: {format_large_number(oi)} 张\n"
                        else:
                            res += f"未平仓量: {format_large_number(oi)} USD\n"
                            
                    return res.strip()
            
            elif m == 'spot':
                pair = f"{base}_{quote}"
                attempts.append(f"Gate 现货 ({pair})")
                d = fetch_url(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={pair}")
                if d and isinstance(d, list) and len(d) > 0:
                    d = d[0]
                    last = float(d['last'])
                    change = float(d['change_percentage']) / 100
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['high_24h'])
                    low = float(d['low_24h'])
                    vol = float(d.get('quote_volume', 0))
                    
                    res = f"[GATE 现货] {pair}\n"
                    res += f"当前价: {last}\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} {quote}\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    return res.strip()
            
            elif m == 'tradfi':
                attempts.append(f"Gate TradFi ({base})")
                data = fetch_url(f"https://api.gateio.ws/api/v4/tradfi/symbols/{base}/klines?kline_type=1d&limit=2")
                if data:
                    klines = data.get('data', {}).get('list', [])
                    if klines and len(klines) > 0:
                        latest = klines[-1]
                        last = float(latest['c'])
                        high = float(latest['h'])
                        low = float(latest['l'])
                        change = 0.0
                        if len(klines) >= 2:
                            prev = klines[-2]
                            prev_close = float(prev['c'])
                            if prev_close > 0:
                                change = (last - prev_close) / prev_close
                        else:
                            open_p = float(latest['o'])
                            if open_p > 0:
                                change = (last - open_p) / open_p
                        
                        change_sign = "+" if change >= 0 else ""        
                        res = f"[GATE TRADFI/美股] {base}\n"
                        res += f"当前价: {last}\n"
                        res += f"24H涨跌: {change_sign}{change*100:.2f}%\n"
                        res += f"24H最高: {high} / 最低: {low}\n"
                        return res.strip()
        except Exception as e:
            logger.warning(f"Gate fetch failed for {m}: {str(e)}")
            continue

    return None

def fetch_binance(base: str, quote: str, market: str, attempts: list):
    markets_to_try = []
    if market in ['spot', '现货']:
        markets_to_try = ['spot']
    elif market in ['futures', '合约', 'contract']:
        markets_to_try = ['futures']
    else:
        markets_to_try = ['futures', 'spot']
        
    pair = f"{base}{quote}"

    for m in markets_to_try:
        try:
            if m == 'futures':
                attempts.append(f"Binance U本位合约 ({pair})")
                urls = {
                    'ticker': f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={pair}",
                    'premium': f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={pair}",
                    'lsr': f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={pair}&period=5m&limit=1",
                    'top_pos': f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={pair}&period=5m&limit=1",
                    'top_acc': f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={pair}&period=5m&limit=1",
                    'taker': f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={pair}&period=5m&limit=1",
                    'oi': f"https://fapi.binance.com/fapi/v1/openInterest?symbol={pair}"
                }
                
                results = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    future_to_url = {executor.submit(fetch_url, url): key for key, url in urls.items()}
                    for future in concurrent.futures.as_completed(future_to_url):
                        key = future_to_url[future]
                        results[key] = future.result()
                
                ticker_data = results.get('ticker')
                if ticker_data and 'lastPrice' in ticker_data:
                    d = ticker_data
                    last = float(d['lastPrice'])
                    change = float(d['priceChangePercent']) / 100
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['highPrice'])
                    low = float(d['lowPrice'])
                    vol = float(d.get('quoteVolume', 0))
                    
                    res = f"[BINANCE U本位合约] {pair}\n"
                    
                    premium = results.get('premium')
                    mark = float(premium.get('markPrice', 0)) if premium else last
                    res += f"当前价: {last} (标记: {mark})\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} USDT\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    
                    res += f"-------------------------\n"
                    res += f"【合约高阶数据】\n"
                    
                    if premium:
                        funding = float(premium.get('lastFundingRate', 0)) * 100
                        res += f"资金费率: {funding:.4f}%\n"
                        
                    lsr_data = results.get('lsr')
                    if lsr_data and isinstance(lsr_data, list) and len(lsr_data) > 0:
                        item = lsr_data[0]
                        ls_ratio = float(item.get('longShortRatio', 0))
                        long_pct = float(item.get('longAccount', 0)) * 100
                        short_pct = float(item.get('shortAccount', 0)) * 100
                        res += f"全网多空比: {ls_ratio:.2f} (多军 {long_pct:.1f}% / 空军 {short_pct:.1f}%)\n"

                    top_pos_data = results.get('top_pos')
                    if top_pos_data and isinstance(top_pos_data, list) and len(top_pos_data) > 0:
                        item = top_pos_data[0]
                        pos_lsr = float(item.get('longShortRatio', 0))
                        pos_long_pct = float(item.get('longAccount', 0)) * 100
                        pos_short_pct = float(item.get('shortAccount', 0)) * 100
                        res += f"大户持仓多空比: {pos_lsr:.2f} (多头 {pos_long_pct:.1f}% / 空头 {pos_short_pct:.1f}%)\n"

                    top_acc_data = results.get('top_acc')
                    if top_acc_data and isinstance(top_acc_data, list) and len(top_acc_data) > 0:
                        item = top_acc_data[0]
                        acc_lsr = float(item.get('longShortRatio', 0))
                        res += f"大户账户多空比: {acc_lsr:.2f}\n"

                    taker_data = results.get('taker')
                    if taker_data and isinstance(taker_data, list) and len(taker_data) > 0:
                        item = taker_data[0]
                        tk_ratio = float(item.get('buySellRatio', 0))
                        buy_v = float(item.get('buyVol', 0))
                        sell_v = float(item.get('sellVol', 0))
                        res += f"主动买卖比: {tk_ratio:.2f} (买入 {format_large_number(buy_v)} / 卖出 {format_large_number(sell_v)})\n"

                    oi_data = results.get('oi')
                    if oi_data:
                        oi = float(oi_data.get('openInterest', 0))
                        res += f"未平仓量: {format_large_number(oi)} {base} (~${format_large_number(oi * mark)} USD)\n"
                        
                    return res.strip()
                    
            elif m == 'spot':
                attempts.append(f"Binance 现货 ({pair})")
                d = fetch_url(f"https://api.binance.com/api/v3/ticker/24hr?symbol={pair}")
                if d and 'lastPrice' in d:
                    last = float(d['lastPrice'])
                    change = float(d['priceChangePercent']) / 100
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['highPrice'])
                    low = float(d['lowPrice'])
                    vol = float(d.get('quoteVolume', 0))
                    
                    res = f"[BINANCE 现货] {pair}\n"
                    res += f"当前价: {last}\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} {quote}\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    return res.strip()
        except Exception as e:
            logger.warning(f"Binance fetch failed for {m}: {str(e)}")
            continue
            
    return None

def fetch_okx(base: str, quote: str, market: str, attempts: list):
    markets_to_try = []
    if market in ['spot', '现货']:
        markets_to_try = ['spot']
    elif market in ['futures', '合约', 'contract']:
        markets_to_try = ['futures']
    else:
        markets_to_try = ['futures', 'spot']
        
    for m in markets_to_try:
        try:
            if m == 'futures':
                pair = f"{base}-{quote}-SWAP"
                attempts.append(f"OKX 永续合约 ({pair})")
                
                urls = {
                    'ticker': f"https://www.okx.com/api/v5/market/ticker?instId={pair}",
                    'funding': f"https://www.okx.com/api/v5/public/funding-rate?instId={pair}",
                    'oi': f"https://www.okx.com/api/v5/public/open-interest?instId={pair}",
                    'lsr': f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={base}&period=5m",
                    'top_pos': f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader?instId={pair}&period=5m",
                    'top_acc': f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader?instId={pair}&period=5m",
                    'taker': f"https://www.okx.com/api/v5/rubik/stat/taker-volume-contract?instId={pair}&period=5m"
                }
                
                results = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    future_to_url = {executor.submit(fetch_url, url): key for key, url in urls.items()}
                    for future in concurrent.futures.as_completed(future_to_url):
                        key = future_to_url[future]
                        results[key] = future.result()
                        
                ticker_data = results.get('ticker')
                if ticker_data and ticker_data.get('code') == '0' and ticker_data.get('data'):
                    d = ticker_data['data'][0]
                    last = float(d['last'])
                    open24h = float(d['open24h'])
                    change = (last - open24h) / open24h if open24h > 0 else 0.0
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['high24h'])
                    low = float(d['low24h'])
                    vol = float(d['volCcy24h'])
                    
                    res = f"[OKX 永续合约] {pair}\n"
                    res += f"当前价: {last}\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} {quote}\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    
                    res += f"-------------------------\n"
                    res += f"【合约高阶数据】\n"
                    
                    funding_data = results.get('funding')
                    if funding_data and funding_data.get('code') == '0' and funding_data.get('data'):
                        funding = float(funding_data['data'][0]['fundingRate']) * 100
                        res += f"资金费率: {funding:.4f}%\n"
                        
                    lsr_data = results.get('lsr')
                    if lsr_data and lsr_data.get('code') == '0' and lsr_data.get('data'):
                        ls_ratio = float(lsr_data['data'][0][1])
                        long_pct = (ls_ratio / (1.0 + ls_ratio)) * 100
                        short_pct = 100.0 - long_pct
                        res += f"全网多空比: {ls_ratio:.2f} (多军 {long_pct:.1f}% / 空军 {short_pct:.1f}%)\n"

                    top_pos_data = results.get('top_pos')
                    if top_pos_data and top_pos_data.get('code') == '0' and top_pos_data.get('data'):
                        pos_lsr = float(top_pos_data['data'][0][1])
                        pos_long_pct = (pos_lsr / (1.0 + pos_lsr)) * 100
                        pos_short_pct = 100.0 - pos_long_pct
                        res += f"大户持仓多空比: {pos_lsr:.2f} (多头 {pos_long_pct:.1f}% / 空头 {pos_short_pct:.1f}%)\n"

                    top_acc_data = results.get('top_acc')
                    if top_acc_data and top_acc_data.get('code') == '0' and top_acc_data.get('data'):
                        acc_lsr = float(top_acc_data['data'][0][1])
                        res += f"大户账户多空比: {acc_lsr:.2f}\n"

                    taker_data = results.get('taker')
                    if taker_data and taker_data.get('code') == '0' and taker_data.get('data'):
                        item = taker_data['data'][0]
                        buy_v = float(item[1])
                        sell_v = float(item[2])
                        tk_ratio = buy_v / sell_v if sell_v else 0.0
                        res += f"主动买卖比: {tk_ratio:.2f} (买入 {format_large_number(buy_v)} / 卖出 {format_large_number(sell_v)})\n"

                    oi_data = results.get('oi')
                    if oi_data and oi_data.get('code') == '0' and oi_data.get('data'):
                        oi = float(oi_data['data'][0]['oiUsd'])
                        res += f"未平仓量: {format_large_number(oi)} USD\n"
                        
                    return res.strip()
                    
            elif m == 'spot':
                pair = f"{base}-{quote}"
                attempts.append(f"OKX 现货 ({pair})")
                ticker_data = fetch_url(f"https://www.okx.com/api/v5/market/ticker?instId={pair}")
                if ticker_data and ticker_data.get('code') == '0' and ticker_data.get('data'):
                    d = ticker_data['data'][0]
                    last = float(d['last'])
                    open24h = float(d['open24h'])
                    change = (last - open24h) / open24h if open24h > 0 else 0.0
                    change_sign = "+" if change >= 0 else ""
                    high = float(d['high24h'])
                    low = float(d['low24h'])
                    vol = float(d['volCcy24h'])
                    
                    res = f"[OKX 现货] {pair}\n"
                    res += f"当前价: {last}\n"
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} {quote}\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    return res.strip()
                    
        except Exception as e:
            logger.warning(f"OKX fetch failed for {m}: {str(e)}")
            continue
            
    return None

def fetch_hyperliquid(base: str, quote: str, market: str, attempts: list):
    markets_to_try = []
    if market in ['spot', '现货']:
        markets_to_try = ['spot']
    elif market in ['futures', '合约', 'contract']:
        markets_to_try = ['futures']
    else:
        markets_to_try = ['futures', 'spot']

    for m in markets_to_try:
        try:
            if m == 'futures':
                pair = f"{base}" # Hyperliquid futures are USD settled perps
                attempts.append(f"Hyperliquid 永续合约 ({pair})")
                try:
                    urls_post = {
                        'meta': ("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"}),
                        'l2': ("https://api.hyperliquid.xyz/info", {"type": "l2Book", "coin": base})
                    }
                    results = {}
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                        future_to_key = {executor.submit(fetch_post, url, payload): key for key, (url, payload) in urls_post.items()}
                        for future in concurrent.futures.as_completed(future_to_key):
                            key = future_to_key[future]
                            results[key] = future.result()

                    data = results.get('meta')
                    if data and isinstance(data, list) and len(data) >= 2:
                        universe = data[0].get('universe', [])
                        idx = -1
                        for i, asset in enumerate(universe):
                            if asset['name'] == base:
                                idx = i
                                break
                        if idx != -1:
                            ctx = data[1][idx]
                            last = float(ctx['markPx'])
                            prev = float(ctx['prevDayPx'])
                            change = (last - prev) / prev if prev > 0 else 0.0
                            change_sign = "+" if change >= 0 else ""
                            vol = float(ctx.get('dayNtlVlm', 0))
                            
                            res = f"[HYPERLIQUID 永续合约] {pair}\n"
                            res += f"当前价: {last} (标记: {last})\n"
                            res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} USD\n"
                            
                            funding = float(ctx.get('funding', 0)) * 100
                            oi = float(ctx.get('openInterest', 0))
                            premium = float(ctx.get('premium', 0)) * 100
                            
                            res += f"-------------------------\n"
                            res += f"【合约高阶数据】\n"
                            res += f"资金费率: {funding:.4f}% (折合8H: {funding * 8:.4f}%)\n"
                            res += f"现货/合约溢价: {premium:+.4f}%\n"

                            l2_data = results.get('l2')
                            if l2_data and 'levels' in l2_data:
                                levels = l2_data['levels']
                                bids = levels[0] if len(levels) > 0 else []
                                asks = levels[1] if len(levels) > 1 else []
                                bid_vol = sum(float(b['sz']) for b in bids)
                                ask_vol = sum(float(a['sz']) for a in asks)
                                depth_ratio = bid_vol / ask_vol if ask_vol else 0.0
                                res += f"盘口买卖比: {depth_ratio:.2f} (买盘深度 {bid_vol:.2f} {base} / 卖盘深度 {ask_vol:.2f} {base})\n"
                                
                            res += f"未平仓量: {format_large_number(oi)} {base} (~${format_large_number(oi * last)} USD)\n"
                            return res.strip()
                except Exception as e:
                    logger.warning(f"Hyperliquid futures error: {e}")
                        
            elif m == 'spot':
                pair = f"{base}/{quote}"
                attempts.append(f"Hyperliquid 现货 ({pair})")
                try:
                    data = fetch_post("https://api.hyperliquid.xyz/info", {"type": "spotMetaAndAssetCtxs"})
                    if data and isinstance(data, list) and len(data) >= 2:
                        universe = data[0].get('universe', [])
                        idx = -1
                        for i, asset in enumerate(universe):
                            if asset['name'] == pair:
                                idx = i
                                break
                        if idx != -1:
                            ctx = data[1][idx]
                            last = float(ctx['markPx'])
                            prev = float(ctx['prevDayPx'])
                            change = (last - prev) / prev if prev > 0 else 0.0
                            change_sign = "+" if change >= 0 else ""
                            vol = float(ctx.get('dayNtlVlm', 0))
                            
                            res = f"[HYPERLIQUID 现货] {pair}\n"
                            res += f"当前价: {last}\n"
                            res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} USD\n"
                            return res.strip()
                except Exception as e:
                    logger.warning(f"Hyperliquid spot error: {e}")
        except Exception as e:
            logger.warning(f"Hyperliquid fetch failed for {m}: {str(e)}")
            continue

    return None

ALL_FLAGS = {'-A', '--ALL', '-ALL', 'ALL', '全', '全网', '全平台', '全部'}

def parse_args(args_str: str):
    raw_tokens = [t.strip() for t in args_str.split() if t.strip()]
    if not raw_tokens:
        return None, None, None, None, None, False, False
        
    query_all = False
    filtered_tokens = []
    for t in raw_tokens:
        if t.upper() in ALL_FLAGS:
            query_all = True
        else:
            filtered_tokens.append(t)

    if not filtered_tokens:
        return None, None, None, None, None, False, query_all

    symbol_raw = filtered_tokens[0].upper()
    base, quote = None, None
    if "/" in symbol_raw:
        base, quote = symbol_raw.split("/", 1)
    elif "_" in symbol_raw:
        base, quote = symbol_raw.split("_", 1)
    else:
        base = symbol_raw
        quote = None
        
    exchange = "binance"
    explicit_exchange = False
    market = None
    
    for t in filtered_tokens[1:]:
        t_lower = t.lower()
        if t_lower in ['binance', 'bn']:
            exchange = 'binance'
            explicit_exchange = True
        elif t_lower in ['hyperliquid', 'hl']:
            exchange = 'hyperliquid'
            explicit_exchange = True
        elif t_lower in ['gate', 'gateio']:
            exchange = 'gate'
            explicit_exchange = True
        elif t_lower in ['okx', 'ok']:
            exchange = 'okx'
            explicit_exchange = True
        elif t_lower in ['spot', '现货', 'futures', '合约', 'contract', 'tradfi']:
            market = t_lower
        else:
            if market is None:
                market = t_lower
        
    return base, quote, exchange, market, symbol_raw, explicit_exchange, query_all

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args_str = message.request.args
    base, quote, exchange, market, symbol_raw, explicit_exchange, query_all = parse_args(args_str)
    
    if not base:
        message.reply("400: nemo: 请提供标的名称，例如 `coin BTC` 或 `coin BTC -a`")
        return
        
    is_agent = getattr(message.request, "is_agent", False)
    attempts = []
    
    # 1. Explicit exchange specified (e.g. `coin BTC okx` or `coin ETH hl`)
    if explicit_exchange and not query_all:
        current_quote = quote
        if current_quote is None:
            current_quote = 'USDC' if exchange == 'hyperliquid' else 'USDT'
            
        result = None
        if exchange == 'gate':
            result = fetch_gate(base, current_quote, market, attempts)
        elif exchange == 'binance':
            result = fetch_binance(base, current_quote, market, attempts)
        elif exchange == 'okx':
            result = fetch_okx(base, current_quote, market, attempts)
        elif exchange == 'hyperliquid':
            result = fetch_hyperliquid(base, current_quote, market, attempts)
            
        if result:
            message.reply(result)
        else:
            attempts_str = "\n".join([f"- {a}" for a in attempts])
            msg = f"404: nemo: 找不到相关的行情数据。\n我们为你尝试了以下查询路径:\n{attempts_str}\n"
            if "/" not in symbol_raw and "_" not in symbol_raw:
                msg += f"\n💡 提示: 如果你要查特定的交叉盘，请完整输入如 `{base}/BTC`。"
            message.reply(msg)
        return

    # 2. ALL EXCHANGES: Triggered if query_all flag is set (-a, --all, all, 全网) OR invoked by Agent
    if query_all or is_agent:
        exchanges = ['gate', 'binance', 'okx', 'hyperliquid']
        
        def run_fetch(ex):
            att = []
            q = quote
            if q is None:
                q = 'USDC' if ex == 'hyperliquid' else 'USDT'
            res = None
            if ex == 'gate':
                res = fetch_gate(base, q, market, att)
            elif ex == 'binance':
                res = fetch_binance(base, q, market, att)
            elif ex == 'okx':
                res = fetch_okx(base, q, market, att)
            elif ex == 'hyperliquid':
                res = fetch_hyperliquid(base, q, market, att)
            return ex, res, att

        results_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_ex = {executor.submit(run_fetch, ex): ex for ex in exchanges}
            for future in concurrent.futures.as_completed(future_to_ex):
                ex, res, att = future.result()
                results_dict[ex] = res
                attempts.extend(att)
                
        successful_results = [results_dict[ex] for ex in exchanges if results_dict.get(ex)]
        
        if successful_results:
            separator = "\n\n" + "═" * 30 + "\n\n"
            message.reply(separator.join(successful_results))
        else:
            attempts_str = "\n".join([f"- {a}" for a in attempts])
            msg = f"404: nemo: 找不到相关的行情数据。\n我们为你同时尝试了以下交易所查询路径:\n{attempts_str}\n"
            if "/" not in symbol_raw and "_" not in symbol_raw:
                msg += f"\n💡 提示: 如果你要查特定的交叉盘，请完整输入如 `{base}/BTC`。"
            message.reply(msg)
        return

    # 3. HUMAN DEFAULT: Binance only to prevent chat flooding
    current_quote = quote if quote is not None else 'USDT'
    result = fetch_binance(base, current_quote, market, attempts)
    if result:
        message.reply(result)
        return

    # Fallback to other exchanges if not found on Binance (e.g. MSFT or niche tokens)
    for ex, fetcher in [('gate', fetch_gate), ('okx', fetch_okx), ('hyperliquid', fetch_hyperliquid)]:
        q = 'USDC' if ex == 'hyperliquid' else current_quote
        res = fetcher(base, q, market, attempts)
        if res:
            message.reply(f"{res}\n\n💡 提示: Binance 未收录该标的，已自动为你展示 {ex.upper()} 行情。可使用 `coin {symbol_raw} -a` 查全网。")
            return

    attempts_str = "\n".join([f"- {a}" for a in attempts])
    msg = f"404: nemo: 找不到相关的行情数据。\n我们为你尝试了以下查询路径:\n{attempts_str}\n"
    if "/" not in symbol_raw and "_" not in symbol_raw:
        msg += f"\n💡 提示: 如果你要查特定的交叉盘，请完整输入如 `{base}/BTC`。如需全网查询可加 `-a`。"
    message.reply(msg)
