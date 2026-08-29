import os
import time
import requests
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 17 檔標的配置（全面對齊美股行情與美元計價）
SYMBOL_CONFIG = {
    # 主流加密貨幣 / 黃金 (Binance 公開鏡像，以 USDT 計價)
    'BTC': {'type': 'crypto', 'pair': 'BTCUSDT', 'curr': 'USDT'},
    'ETH': {'type': 'crypto', 'pair': 'ETHUSDT', 'curr': 'USDT'},
    'XAU': {'type': 'crypto', 'pair': 'PAXGUSDT', 'curr': 'USDT'},
    '币安人生': {'type': 'crypto', 'pair': 'LIFEUSDT', 'curr': 'USDT'},
    
    # 美股龍頭、ETF、商品期貨與美股代號 (Yahoo Finance 15m 美股數據，以 USD 計價)
    'TSM': {'type': 'stock', 'ticker': 'TSM', 'curr': 'USD'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA', 'curr': 'USD'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA', 'curr': 'USD'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL', 'curr': 'USD'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL', 'curr': 'USD'},
    'MU': {'type': 'stock', 'ticker': 'MU', 'curr': 'USD'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN', 'curr': 'USD'},
    'GLW': {'type': 'stock', 'ticker': 'GLW', 'curr': 'USD'},
    'PLAY': {'type': 'stock', 'ticker': 'PLAY', 'curr': 'USD'},      # 美股 PLAY (Dave & Buster's)
    'LAB': {'type': 'stock', 'ticker': 'LABU', 'curr': 'USD'},      # 美股生技三倍做多 LABU / LAB
    'CLU': {'type': 'stock', 'ticker': 'CL=F', 'curr': 'USD'},      # 原油期貨 Crude Oil
    'SPCX': {'type': 'stock', 'ticker': 'SPCX', 'curr': 'USD'},      # 太空/SPAC ETF
    'SAMSUNG': {'type': 'stock', 'ticker': 'SSNLF', 'curr': 'USD'}  # 三星電子美股 ADR (美元)
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

def fetch_crypto_kline(pair):
    """抓取加密貨幣 K 線 (Binance Vision 公開鏡像)"""
    url = f"{BINANCE_MIRROR}?symbol={pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
    try:
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                return True, len(data), float(data[-1][4]), "Binance"
        return False, 0, None, f"HTTP {res.status_code}"
    except Exception as e:
        return False, 0, None, str(e)

def fetch_stock_kline(ticker):
    """抓取美股/商品 15m K 線 (Yahoo Finance)"""
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
    send_discord_alert("📡 **[全美股/美元資產連線測試] 啟動 17 檔標的抓取...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        currency = cfg['curr']
        if cfg['type'] == 'crypto':
            ok, count, price, source = fetch_crypto_kline(cfg['pair'])
            label = cfg['pair']
        else:
            ok, count, price, source = fetch_stock_kline(cfg['ticker'])
            label = cfg['ticker']

        if ok:
            success_count += 1
            results.append(f"✅ {name:<8} [{source:<8}] -> {label:<8} | {count:3d} 根 | 最新價: {price:10,.2f} {currency}")
        else:
            results.append(f"❌ {name:<8} [{source:<8}] -> {label:<8} | 失敗")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[全資產連線測試總覽 (美元計價)]**\n"
        f"成功抓取: {success_count} / {len(SYMBOL_CONFIG)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
