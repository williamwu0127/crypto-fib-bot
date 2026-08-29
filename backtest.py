import os
import time
import requests
import urllib.parse
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOL_CONFIG = {
    # 加密貨幣 (自動相容現貨與合約)
    'BTC': {'type': 'crypto', 'symbols': ['BTCUSDT']},
    'ETH': {'type': 'crypto', 'symbols': ['ETHUSDT']},
    'XAU': {'type': 'crypto', 'symbols': ['PAXGUSDT', 'XAUUSDT']},
    'LAB': {'type': 'crypto', 'symbols': ['LABUSDT', '1000LABUSDT']},
    'PLAY': {'type': 'crypto', 'symbols': ['PLAYUSDT', '1000PLAYUSDT']},
    '币安人生': {'type': 'crypto', 'symbols': ['币安人生USDT', 'BIANRENSHENGUSDT', 'LIFEUSDT']},
    
    # 美股龍頭與商品期貨 (Yahoo Finance 15m 數據源)
    'TSM': {'type': 'stock', 'ticker': 'TSM'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL'},
    'MU': {'type': 'stock', 'ticker': 'MU'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN'},
    'GLW': {'type': 'stock', 'ticker': 'GLW'},
    'CLU': {'type': 'stock', 'ticker': 'CL=F'},
    'SPCX': {'type': 'stock', 'ticker': 'SPCX'},
    'SAMSUNG': {'type': 'stock', 'ticker': '005930.KS'}
}

TIMEFRAME = '15m'
FETCH_LIMIT = 60

# 幣安免美國 IP 封鎖之公共鏡像端點 (現貨 + 合約)
CRYPTO_ENDPOINTS = [
    ("現貨", "https://data-api.binance.vision/api/v3/klines"),
    ("合約", "https://fapi.binance.com/fapi/v1/klines"),
    ("現貨", "https://api1.binance.com/api/v3/klines")
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

def fetch_crypto_kline_multi(sym_list):
    """嘗試多個候選交易對與不同端點"""
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for sym in sym_list:
        encoded_sym = urllib.parse.quote(sym)
        for market_type, base_url in CRYPTO_ENDPOINTS:
            url = f"{base_url}?symbol={encoded_sym}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        return True, len(data), float(data[-1][4]), f"Binance-{market_type}", sym
            except Exception:
                continue

    # 若幣安 API 均無，針對迷因幣嘗試 DEX / GeckoTerminal 備援
    return False, 0, None, "未找到可用端點", sym_list[0]

def fetch_stock_kline(ticker):
    """抓取美股/商品 15m K 線"""
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
    send_discord_alert("📡 **[全資產連線測試] 啟動 17 檔全覆蓋測試 (含合約迷因幣)...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        if cfg['type'] == 'crypto':
            ok, count, price, source, used_sym = fetch_crypto_kline_multi(cfg['symbols'])
            label = used_sym
        else:
            ok, count, price, source = fetch_stock_kline(cfg['ticker'])
            label = cfg['ticker']

        if ok:
            success_count += 1
            results.append(f"✅ {name:<8} [{source:<12}] -> {label:<12} | {count} 根 | 最新價: ${price:,.2f}")
        else:
            results.append(f"❌ {name:<8} [{source:<12}] -> {label:<12} | 抓取失敗")
        time.sleep(0.1)

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
