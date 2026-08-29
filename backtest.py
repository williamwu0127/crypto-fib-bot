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

# 幣安免美國 IP 封鎖之現貨鏡像端點
SPOT_MIRRORS = [
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

def test_fetch_pure_spot(raw_name):
    """全部統一使用現貨鏡像端點嘗試抓取"""
    name = raw_name.strip()
    
    # 候選交易對嘗試清單
    candidates = []
    if name == 'XAU':
        candidates = ['PAXGUSDT', 'XAUUSDT']
    elif name == 'CLU':
        candidates = ['CLUSDT', 'CLUUSDT', 'OILUSDT']
    elif name == '币安人生':
        candidates = ['币安人生USDT', 'LIFEUSDT']
    else:
        candidates = [
            f"{name.upper()}USDT",
            f"{name}USDT",
            f"1000{name.upper()}USDT",
            f"{name.upper()}USDC",
            f"{name.upper()}FDUSD"
        ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    last_status = "無連線"

    for pair in candidates:
        encoded_pair = urllib.parse.quote(pair)
        for base_url in SPOT_MIRRORS:
            url = f"{base_url}?symbol={encoded_pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                last_status = f"HTTP {res.status_code}"
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        latest_close = float(data[-1][4])
                        return True, pair, len(data), latest_close, "成功"
            except Exception as e:
                last_status = str(e)[:15]
                continue

    return False, f"{name.upper()}USDT", 0, None, last_status

def main():
    send_discord_alert("📡 **[全標的現貨抓法測試] 統一走 Binance Vision 現貨端點...**")
    
    results = []
    success_count = 0

    for sym in TARGET_SYMBOLS:
        ok, matched_pair, count, price, status_info = test_fetch_pure_spot(sym)
        if ok:
            success_count += 1
            if price < 1.0:
                price_str = f"${price:.5f}"
            else:
                price_str = f"${price:,.2f}"
            results.append(f"✅ {sym:<8} -> {matched_pair:<12} | {count:2d} 根 | 最新價: {price_str} USDT")
        else:
            results.append(f"❌ {sym:<8} -> {matched_pair:<12} | 失敗 ({status_info})")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[全標的現貨端點測試總覽]**\n"
        f"成功抓取: {success_count} / {len(TARGET_SYMBOLS)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
