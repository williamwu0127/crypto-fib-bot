import os
import time
import requests
import pandas as pd

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

TARGET_SYMBOLS = [
    'BTC', 'ETH', 'XAU', 'TSM', 'MU', 'SPCX', 'CLU', 
    'GOOGL', 'SAMSUNG', 'NVDA', 'GLW', 'TSLA', 'AAPL', 
    'LAB', 'PLAY', 'AMZN', '币安人生'
]

TIMEFRAME = '15m'
FETCH_LIMIT = 50

# 幣安免美國 IP 限制之公開鏡像端點
MIRROR_BASES = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines"
]

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print(content)
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print("推播失敗:", err)

def test_fetch(raw_name):
    name = raw_name.strip()
    
    # 交易對代號對照
    if name.upper() == 'XAU':
        pair = 'PAXGUSDT'
    elif name.upper() == 'CLU':
        pair = 'CLUUSDT'
    elif name == '币安人生':
        pair = 'LIFEUSDT'
    else:
        pair = f"{name.upper()}USDT"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    # 依序嘗試鏡像端點
    for base_url in MIRROR_BASES:
        url = f"{base_url}?symbol={pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    latest_close = float(data[-1][4])
                    return True, pair, len(data), latest_close
            elif res.status_code == 400:
                # 400 代表交易對名稱不存在
                return False, pair, "無此交易對 (HTTP 400)", None
        except Exception:
            continue

    return False, pair, "所有鏡像端點連線失敗", None

def main():
    send_discord_alert("📡 **[鏡像端點測試] 開始測試 17 檔標的 K 線抓取...**")
    
    results = []
    success_count = 0

    for sym in TARGET_SYMBOLS:
        ok, pair, msg_or_len, price = test_fetch(sym)
        if ok:
            success_count += 1
            results.append(f"✅ {sym:<8} -> {pair:<10} | 成功 {msg_or_len} 根 | 最新價: ${price:,.2f}")
        else:
            results.append(f"❌ {sym:<8} -> {pair:<10} | {msg_or_len}")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[鏡像連線測試結果總覽]**\n"
        f"成功抓取: {success_count} / {len(TARGET_SYMBOLS)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
