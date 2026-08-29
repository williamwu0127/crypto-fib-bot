import os
import time
import requests
import urllib.parse

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

TARGET_SYMBOLS = [
    'BTC', 'ETH', 'XAU', '币安人生', 'PLAY', 'LAB', 
    'TSM', 'NVDA', 'TSLA', 'AAPL', 'GOOGL', 'MU', 
    'AMZN', 'GLW', 'SPCX', 'CLU', 'SNDK', 'SAMSUNG'
]

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

def test_fetch_binance_unified(raw_name):
    """統一採用 Binance Vision + URL Encode 嘗試多種配對格式"""
    name = raw_name.strip()
    
    # 建立候選交易對名單
    candidates = []
    if name == 'XAU':
        candidates = ['PAXGUSDT', 'XAUUSDT']
    elif name == 'CLU':
        candidates = ['CLUUSDT', 'CLUSDT', 'OILUSDT']
    else:
        candidates = [
            f"{name.upper()}USDT",
            f"1000{name.upper()}USDT",
            f"{name}USDT",
            f"{name.upper()}USDC"
        ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for pair in candidates:
        encoded_pair = urllib.parse.quote(pair)
        url = f"{BINANCE_MIRROR}?symbol={encoded_pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    latest_close = float(data[-1][4])
                    return True, pair, len(data), latest_close
        except Exception:
            continue

    return False, f"{name.upper()}USDT", 0, None

def main():
    send_discord_alert("📡 **[全標的 Binance Vision 鏡像測試] 開始執行...**")
    
    results = []
    success_count = 0

    for sym in TARGET_SYMBOLS:
        ok, matched_pair, count, price = test_fetch_binance_unified(sym)
        if ok:
            success_count += 1
            if price < 1.0:
                price_str = f"${price:.5f}"
            else:
                price_str = f"${price:,.2f}"
            results.append(f"✅ {sym:<8} [Binance ] -> {matched_pair:<12} | {count:2d} 根 | 最新價: {price_str} USDT")
        else:
            results.append(f"❌ {sym:<8} [Binance ] -> {matched_pair:<12} | 無法抓取 (HTTP 400)")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[全標的 Binance 鏡像端點測試總覽]**\n"
        f"成功抓取: {success_count} / {len(TARGET_SYMBOLS)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
