import requests
import traceback
import json
import logging
import concurrent.futures
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["coin", "crypto", "币", "加密货币", "合约"]
_name = "统一市场行情查询"
_man = """查询加密资产及传统金融(TradFi)实时行情。
用法: {0} <标的> [交易所] [细分市场]
示例: 
  {0} BTC        (默认查 Gate 合约 BTC_USDT，自动降级查现货)
  {0} ETH/BTC    (查 Gate 交叉盘)
  {0} MSFT       (自动查 Gate TradFi 美股代币)
  {0} ETH hl     (查 Hyperliquid)
  {0} BNB binance spot (查 Binance 现货)

支持的交易所: gate (默认), binance, okx, hl / hyperliquid
支持的市场: 合约 / futures (默认), 现货 / spot
"""
_man = _man.replace("{0}", _command[0])

_tool_description = (
    "非常强大的加密资产及美股(TradFi)实时行情查询引擎。\n"
    "当你需要获取加密货币的当前价格、24小时涨跌幅、最高/最低价，或者合约的【资金费率(Funding Rate)】和【多空比(Long/Short Ratio)/持仓量(OI)】时，务必使用此工具。\n"
    "支持跨交易所和跨市场。只需提供标的（如 BTC, ETH/BTC, MSFT）。\n"
    "会自动经历 Fallback（合约 -> 现货 -> TradFi）。如果在默认交易所没找到，它会自动跨 Gate -> Binance -> OKX -> Hyperliquid 搜索。\n"
    "参数 (args) 必须是个字符串，例如 'BTC' 或 'ETH/BTC binance spot'。"
)
_enabled = 1

def format_large_number(num):
    if num >= 1e8:
        return f"{num/1e8:.2f} 亿"
    elif num >= 1e4:
        return f"{num/1e4:.2f} 万"
    return f"{num:,.2f}"

def fetch_url(url, timeout=3):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except:
        pass
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
                    'oi': f"https://fapi.binance.com/fapi/v1/openInterest?symbol={pair}"
                }
                
                results = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
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
                    if premium:
                        mark = float(premium.get('markPrice', 0))
                        res += f"当前价: {last} (标记: {mark})\n"
                    else:
                        res += f"当前价: {last}\n"
                        
                    res += f"24H涨跌: {change_sign}{change*100:.2f}%  |  24H成交额: {format_large_number(vol)} USDT\n"
                    res += f"24H最高: {high} / 最低: {low}\n"
                    
                    res += f"-------------------------\n"
                    res += f"【合约高阶数据】\n"
                    
                    if premium:
                        funding = float(premium.get('lastFundingRate', 0)) * 100
                        res += f"资金费率: {funding:.4f}%\n"
                        
                    lsr_data = results.get('lsr')
                    if lsr_data and isinstance(lsr_data, list) and len(lsr_data) > 0:
                        ls_ratio = float(lsr_data[0].get('longShortRatio', 0))
                        res += f"全网多空比: {ls_ratio:.2f}\n"
                        
                    oi_data = results.get('oi')
                    if oi_data:
                        oi = float(oi_data.get('openInterest', 0))
                        res += f"未平仓量: {format_large_number(oi)} {base}\n"
                        
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
                    'lsr': f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={base}"
                }
                
                results = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
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
                        res += f"全网多空比: {ls_ratio:.2f}\n"
                        
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
                pair = f"{base}" # Hyperliquid futures are mostly USD settled perps
                attempts.append(f"Hyperliquid 永续合约 ({pair})")
                try:
                    r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}, timeout=3)
                    if r.status_code == 200:
                        data = r.json()
                        universe = data[0]['universe']
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
                            
                            res += f"-------------------------\n"
                            res += f"【合约高阶数据】\n"
                            res += f"资金费率: {funding:.4f}%\n"
                            res += f"未平仓量: {format_large_number(oi)} {base}\n"
                            
                            return res.strip()
                except:
                    pass
                        
            elif m == 'spot':
                pair = f"{base}/{quote}"
                attempts.append(f"Hyperliquid 现货 ({pair})")
                try:
                    r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "spotMetaAndAssetCtxs"}, timeout=3)
                    if r.status_code == 200:
                        data = r.json()
                        universe = data[0]['universe']
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
                except:
                    pass
        except Exception as e:
            logger.warning(f"Hyperliquid fetch failed for {m}: {str(e)}")
            continue

    return None

def parse_args(args_str: str):
    tokens = [t.strip().upper() for t in args_str.split() if t.strip()]
    if not tokens:
        return None, None, None, None, None, False
        
    symbol_raw = tokens[0]
    base, quote = None, None
    if "/" in symbol_raw:
        base, quote = symbol_raw.split("/", 1)
    elif "_" in symbol_raw:
        base, quote = symbol_raw.split("_", 1)
    else:
        base = symbol_raw
        quote = None
        
    exchange = "gate"
    explicit_exchange = False
    market = None
    
    if len(tokens) > 1:
        ex = tokens[1].lower()
        if ex in ['binance', 'bn']:
            exchange = 'binance'
            explicit_exchange = True
        elif ex in ['hyperliquid', 'hl']:
            exchange = 'hyperliquid'
            explicit_exchange = True
        elif ex in ['gate', 'gateio']:
            exchange = 'gate'
            explicit_exchange = True
        elif ex in ['okx', 'ok']:
            exchange = 'okx'
            explicit_exchange = True
        else:
            market = ex

    if len(tokens) > 2 and market is None:
        market = tokens[2].lower()
        
    return base, quote, exchange, market, symbol_raw, explicit_exchange

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args_str = message.request.args
    base, quote, exchange, market, symbol_raw, explicit_exchange = parse_args(args_str)
    
    if not base:
        message.reply("400: nemo: 请提供标的名称，例如 `coin BTC` 或 `coin ETH/BTC binance`")
        return
        
    exchanges_to_try = [exchange] if explicit_exchange else ['gate', 'binance', 'okx', 'hyperliquid']
    attempts = []
    result = None
    
    for ex in exchanges_to_try:
        current_quote = quote
        if current_quote is None:
            if ex == 'hyperliquid':
                current_quote = 'USDC'
            else:
                current_quote = 'USDT'
                
        if ex == 'gate':
            result = fetch_gate(base, current_quote, market, attempts)
        elif ex == 'binance':
            result = fetch_binance(base, current_quote, market, attempts)
        elif ex == 'okx':
            result = fetch_okx(base, current_quote, market, attempts)
        elif ex == 'hyperliquid':
            result = fetch_hyperliquid(base, current_quote, market, attempts)
            
        if result:
            break
            
    if result:
        message.reply(result)
    else:
        attempts_str = "\n".join([f"- {a}" for a in attempts])
        msg = f"404: nemo: 找不到相关的行情数据。\n"
        msg += f"我们为你按顺序尝试了以下查询路径:\n{attempts_str}\n"
        if "/" not in symbol_raw and "_" not in symbol_raw:
            msg += f"\n💡 提示: 如果你要查特定的交叉盘，请完整输入如 `{base}/BTC`。"
        message.reply(msg)
