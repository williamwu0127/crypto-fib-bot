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

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print("未設定 Webhook URL，輸出到日誌:\n", content)
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print("推播失敗:", err)

def test_fetch(raw_name):
    name = raw_name.strip()
    if name.upper() == 'XAU':
        pair = 'PAXGUSDT'
    elif name.upper() == 'CLU':
        pair = 'CLUUSDT'
    elif name == '币安人生':
        pair = 'LIFEUSDT'
    else:
        pair = f"{name.upper()}USDT"

    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
    
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                latest_close = float(data[-1][4])
                return True, pair, len(data), latest_close
            else:
                return False, pair, "回傳資料為空", None
        else:
            return False, pair, f"HTTP {res.status_code} ({res.text[:30]})", None
    except Exception as e:
        return False, pair, str(e), None

def main():
    send_discord_alert("📡 **[連線測試] 開始測試 17 檔標的 K 線抓取...**")
    
    results = []
    success_count = 0

    for sym in TARGET_SYMBOLS:
        ok, pair, msg_or_len, price = test_fetch(sym)
        if ok:
            success_count += 1
            results.append(f"✅ {sym:<8} -> {pair:<10} | 成功 {msg_or_len} 根 | 最新價: {price}")
        else:
            results.append(f"❌ {sym:<8} -> {pair:<10} | 失敗: {msg_or_len}")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[K 線連線測試結果總覽]**\n"
        f"成功: {success_count} / {len(TARGET_SYMBOLS)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
