import os
import time
import requests
import urllib.parse
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOL_CONFIG = {
    # 1. 幣安主流幣與現貨代幣 (USDT 計價)
    'BTC': {'type': 'crypto_binance', 'pairs': ['BTCUSDT'], 'curr': 'USDT'},
    'ETH': {'type': 'crypto_binance', 'pairs': ['ETHUSDT'], 'curr': 'USDT'},
    'XAU': {'type': 'crypto_binance', 'pairs': ['PAXGUSDT'], 'curr': 'USDT'},
    '币安人生': {'type': 'crypto_binance', 'pairs': ['币安人生USDT'], 'curr': 'USDT'},

    # 2. 鏈上 / Alpha 迷因幣 (GeckoTerminal 15m K 線, USD 計價)
    'PLAY': {'type': 'crypto_dex', 'network': 'base', 'pool': '0xf1cacdfb3260c67539097e366df047ef1fcf0b08', 'curr': 'USD'},
    'LAB': {'type': 'crypto_dex', 'network': 'bsc', 'pool': '0xd9434e63fe78a6e77dafe2abc504121bf8500822f6d3a59eccba577cf0a070f2', 'curr': 'USD'},

    # 3. 美股龍頭與商品期貨 (Yahoo Finance 美股數據, USD 計價)
    'TSM': {'type': 'stock', 'ticker': 'TSM', 'curr': 'USD'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA', 'curr': 'USD'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA', 'curr': 'USD'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL', 'curr': 'USD'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL', 'curr': 'USD'},
    'MU': {'type': 'stock', 'ticker': 'MU', 'curr': 'USD'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN', 'curr': 'USD'},
    'GLW': {'type': 'stock', 'ticker': 'GLW', 'curr': 'USD'},
    'SPCX': {'type': 'stock', 'ticker': 'SPCX', 'curr': 'USD'},
    'CLU': {'type': 'stock', 'ticker': 'CL=F', 'curr': 'USD'},
    'SNDK': {'type': 'stock', 'ticker': 'SNDK', 'curr': 'USD'},
    'SAMSUNG': {'type': 'stock', 'ticker': 'SMSN.L', 'curr': 'USD'}   # 美元計價三星電子 GDR/美股
}

TIMEFRAME = '15m'
FETCH_LIMIT = 60

BINANCE_MIRROR = "https://data-api.binance.vision/api/v3/klines"

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print(content)
        return
    try:
        if len(content) > 1900:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=10)
                time.sleep(0.5)
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print("推播失敗:", err)

def fetch_binance_kline(pairs):
    """抓取幣安主流現貨 K 線"""
    headers = {"User-Agent": "Mozilla/5.0"}
    for pair in pairs:
        encoded_pair = urllib.parse.quote(pair)
        url = f"{BINANCE_MIRROR}?symbol={encoded_pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    return True, len(data), float(data[-1][4]), "Binance", pair
        except Exception:
            continue
    return False, 0, None, "Binance", pairs[0]

def fetch_dex_kline(network, pool):
    """抓取 GeckoTerminal 鏈上 15m K 線"""
    headers = {"Accept": "application/json;version=20230302"}
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/minute?aggregate=15&limit={FETCH_LIMIT}"
    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            ohlcv_list = res.json().get('data', {}).get('attributes', {}).get('ohlcv_list', [])
            if ohlcv_list:
                latest_close = float(ohlcv_list[0][4])
                return True, len(ohlcv_list), latest_close, "Alpha-DEX", pool[:8] + "..."
    except Exception:
        pass
    return False, 0, None, "Alpha-DEX", pool[:8] + "..."

def fetch_stock_kline(ticker):
    """抓取美股/商品 15m K 線 (Yahoo Finance)"""
    try:
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if not df.empty and len(df) >= 10:
            if isinstance(df['Close'], pd.DataFrame):
                latest_close = float(df['Close'].iloc[-1].values[0])
            else:
                latest_close = float(df['Close'].iloc[-1])
            return True, len(df), latest_close, "YahooFin", ticker
        return False, 0, None, "數據為空", ticker
    except Exception as e:
        return False, 0, None, str(e), ticker

def main():
    send_discord_alert("📡 **[全資產連線測試] 啟動全 18 檔標的連線驗證...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        curr = cfg['curr']
        t = cfg['type']
        
        if t == 'crypto_binance':
            ok, count, price, source, label = fetch_binance_kline(cfg['pairs'])
        elif t == 'crypto_dex':
            ok, count, price, source, label = fetch_dex_kline(cfg['network'], cfg['pool'])
        else:
            ok, count, price, source, label = fetch_stock_kline(cfg['ticker'])

        if ok:
            success_count += 1
            if price < 1.0:
                price_str = f"${price:.5f}"
            else:
                price_str = f"${price:,.2f}"
            results.append(f"✅ {name:<8} [{source:<9}] -> {label:<10} | {count:3d} 根 | 最新價: {price_str} {curr}")
        else:
            results.append(f"❌ {name:<8} [{source:<9}] -> {label:<10} | 失敗")
        time.sleep(0.15)

    summary_text = (
        f"📋 **[全資產連線測試總覽]**\n"
        f"成功抓取: {success_count} / {len(SYMBOL_CONFIG)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
