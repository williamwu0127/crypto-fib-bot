import os
import requests
import yfinance as yf
from datetime import datetime

# 指向同一個 Discord Webhook 頻道
WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

def get_jpy_rate():
    try:
        # 抓取日圓兌台幣 (JPYTWD=X) 最新匯率
        ticker = yf.Ticker("JPYTWD=X")
        df = ticker.history(period="5d", interval="1d")
        if df.empty:
            return None
        latest_price = round(float(df["Close"].iloc[-1]), 4)
        prev_price = round(float(df["Close"].iloc[-2]), 4)
        change_pct = round(((latest_price - prev_price) / prev_price) * 100, 2)
        return latest_price, change_pct
    except Exception as e:
        print(f"抓取日幣匯率失敗: {e}")
        return None

def send_discord(rate, change_pct):
    trend_emoji = "🔺" if change_pct > 0 else "🔻"
    payload = {
        "username": "匯率監控機器人",
        "embeds": [{
            "title": "💴 日圓 / 台幣 匯率監控報告",
            "description": (
                f"> **最新匯率**: `1 JPY = {rate} TWD`\n"
                f"> **單日漲跌**: `{trend_emoji} {change_pct}%`\n"
                f"> **更新時間**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            ),
            "color": 15844367 if change_pct > 0 else 3447003
        }]
    }
    
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"Discord 推播狀態: {resp.status_code}")

def main():
    res = get_jpy_rate()
    if res:
        rate, change_pct = res
        send_discord(rate, change_pct)

if __name__ == "__main__":
    main()
