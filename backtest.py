import os
import time
import requests
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 根據截圖完整對齊的 17 檔標的配置
SYMBOL_CONFIG = {
    # 1. 幣安原生加密與迷因幣種 (USDT 計價)
    'BTC': {'type': 'crypto', 'symbols': ['BTCUSDT'], 'curr': 'USDT'},
    'ETH': {'type': 'crypto', 'symbols': ['ETHUSDT'], 'curr': 'USDT'},
    'XAU': {'type': 'crypto', 'symbols': ['PAXGUSDT', 'XAUUSDT'], 'curr': 'USDT'},
    'PLAY': {'type': 'crypto', 'symbols': ['PLAYUSDT', '1000PLAYUSDT'], 'curr': 'USDT'},
    'LAB': {'type': 'crypto', 'symbols': ['LABUSDT', '1000LABUSDT'], 'curr': 'USDT'},
    '币安人生': {'type': 'crypto', 'symbols': ['LIFEUSDT', '币安人生USDT'], 'curr': 'USDT'},

    # 2. 傳統金融/美股股票永續合約 (Yahoo Finance 美股數據, USD 計價)
    'TSM': {'type': 'stock', 'ticker': 'TSM', 'curr': 'USD'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA', 'curr': 'USD'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA', 'curr': 'USD'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL', 'curr': 'USD'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL', 'curr': 'USD'},
    'MU': {'type': 'stock', 'ticker': 'MU', 'curr': 'USD'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN', 'curr': 'USD'},
    'GLW': {'type': 'stock', 'ticker': 'GLW', 'curr': 'USD'},
    'SPCX': {'type': 'stock', 'ticker': 'SPCX', 'curr': 'USD'},
    'CLU': {'type': 'stock', 'ticker': 'CL=F', 'curr': 'USD'},           # 原油期貨 (與 CLUSDT 連動)
    'SAMSUNG': {'type': 'stock', 'ticker': '005930.KS', 'curr': 'KRW'}    # 三星電子本股數據
}

TIMEFRAME = '15m'
FETCH_LIMIT = 60

# 幣安免美國 IP 限制鏡像端點
BINANCE_MIRRORS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines"
]

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

def fetch_crypto_kline(symbols):
    """輪詢幣安鏡像端點抓取 K 線"""
    headers = {"User-Agent": "Mozilla/5.0"}
    for sym in symbols:
        for base_url in BINANCE_MIRRORS:
            url = f"{base_url}?symbol={sym}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        latest_close = float(data[-1][4])
                        return True, len(data), latest_close, sym, "Binance"
            except Exception:
                continue
    return False, 0, None, symbols[0], "抓取失敗"

def fetch_stock_kline(ticker):
    """從 Yahoo Finance 抓取美股/商品 15m K 線"""
    try:
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if not df.empty and len(df) >= 10:
            if isinstance(df['Close'], pd.DataFrame):
                latest_close = float(df['Close'].iloc[-1].values[0])
            else:
                latest_close = float(df['Close'].iloc[-1])
            return True, len(df), latest_close, "YahooFin"
        return False, 0, None, "數據為空"
    except Exception as e:
        return False, 0, None, str(e)

def main():
    send_discord_alert("📡 **[全資產連線測試] 依照合約自選清單精準對齊測試...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        curr = cfg['curr']
        if cfg['type'] == 'crypto':
            ok, count, price, used_label, source = fetch_crypto_kline(cfg['symbols'])
        else:
            ok, count, price, source = fetch_stock_kline(cfg['ticker'])
            used_label = cfg['ticker']

        if ok:
            success_count += 1
            if price < 1.0:
                price_str = f"${price:.5f}"
            else:
                price_str = f"${price:,.2f}"
            results.append(f"✅ {name:<8} [{source:<8}] -> {used_label:<10} | {count:3d} 根 | 最新價: {price_str} {curr}")
        else:
            results.append(f"❌ {name:<8} [{source:<8}] -> {used_label:<10} | 失敗")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[全資產自選清單連線測試總覽]**\n"
        f"成功抓取: {success_count} / {len(SYMBOL_CONFIG)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
