import os
import time
import requests
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 17 檔標的與對應最佳數據源配置
SYMBOL_CONFIG = {
    # 加密貨幣 (走幣安鏡像)
    'BTC': {'type': 'crypto', 'pair': 'BTCUSDT'},
    'ETH': {'type': 'crypto', 'pair': 'ETHUSDT'},
    'XAU': {'type': 'crypto', 'pair': 'PAXGUSDT'},
    'LAB': {'type': 'crypto', 'pair': 'LABUSDT'},
    'PLAY': {'type': 'crypto', 'pair': 'PLAYUSDT'},
    '币安人生': {'type': 'crypto', 'pair': 'LIFEUSDT'},
    
    # 美股龍頭與商品期貨 (走 Yahoo Finance 美股 15m 數據源)
    'TSM': {'type': 'stock', 'ticker': 'TSM'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL'},
    'MU': {'type': 'stock', 'ticker': 'MU'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN'},
    'GLW': {'type': 'stock', 'ticker': 'GLW'},
    'CLU': {'type': 'stock', 'ticker': 'CL=F'},       # 原油期貨 Crude Oil
    'SPCX': {'type': 'stock', 'ticker': 'SPCX'},      # 太空/SPAC ETF
    'SAMSUNG': {'type': 'stock', 'ticker': '005930.KS'} # 三星電子
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
    """抓取加密貨幣 K 線 (Binance Vision)"""
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
        # yfinance 支援 15m 週期 (過去 5~7 天)
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if not df.empty and len(df) >= 10:
            # 取得最新收盤價 (相容 multi-index)
            if isinstance(df['Close'], pd.DataFrame):
                latest_close = float(df['Close'].iloc[-1].values[0])
            else:
                latest_close = float(df['Close'].iloc[-1])
            return True, len(df), latest_close, "YahooFin"
        return False, 0, None, "數據為空 (非開盤或代碼有誤)"
    except Exception as e:
        return False, 0, None, str(e)

def main():
    send_discord_alert("📡 **[全資產連線測試] 啟動 Crypto + 美股商品 雙引擎抓取...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        if cfg['type'] == 'crypto':
            ok, count, price, source = fetch_crypto_kline(cfg['pair'])
            label = cfg['pair']
        else:
            ok, count, price, source = fetch_stock_kline(cfg['ticker'])
            label = cfg['ticker']

        if ok:
            success_count += 1
            results.append(f"✅ {name:<8} [{source:<8}] -> {label:<10} | {count} 根 | 最新價: ${price:,.2f}")
        else:
            results.append(f"❌ {name:<8} [{source:<8}] -> {label:<10} | 失敗")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[全資產雙引擎連線測試總覽]**\n"
        f"成功抓取: {success_count} / {len(SYMBOL_CONFIG)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
