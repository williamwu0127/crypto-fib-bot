import os
import requests
import yfinance as yf
from datetime import datetime

# 指向台股同一個 Discord Webhook
WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

def analyze_jpy():
    try:
        # 下載日圓兌台幣近 3 個月歷史數據
        ticker = yf.Ticker("JPYTWD=X")
        df = ticker.history(period="3mo", interval="1d")
        if df.empty or len(df) < 20:
            return None

        close_s = df["Close"]
        latest_price = round(float(close_s.iloc[-1]), 4)
        prev_price = round(float(close_s.iloc[-2]), 4)
        change_pct = round(((latest_price - prev_price) / prev_price) * 100, 2)

        # 計算均線與歷史極值
        ma5 = round(float(close_s.rolling(5).mean().iloc[-1]), 4)
        ma20 = round(float(close_s.rolling(20).mean().iloc[-1]), 4)
        min_60d = round(float(close_s.min()), 4)
        max_60d = round(float(close_s.max()), 4)

        # 換匯建議評估
        advice = "區間震盪觀望"
        color = 3447003  # 藍色

        if latest_price <= min_60d * 1.005 or latest_price < 0.2100:
            advice = "🟢 觸及波段極低點（極佳換匯買點）"
            color = 5763719  # 綠色
        elif latest_price < ma20:
            advice = "🟡 處於月線下方（適合分批佈局）"
            color = 16776960  # 黃色
        elif change_pct >= 0.8:
            advice = "🔴 日圓急漲反彈（暫緩追高）"
            color = 15548997  # 紅色

        return {
            "price": latest_price,
            "change_pct": change_pct,
            "ma5": ma5,
            "ma20": ma20,
            "min_60d": min_60d,
            "max_60d": max_60d,
            "advice": advice,
            "color": color
        }
    except Exception as e:
        print(f"抓取日幣資料出錯: {e}")
        return None

def send_discord(data):
    trend_emoji = "🔺" if data["change_pct"] > 0 else "🔻"
    
    payload = {
        "username": "匯率行情監控",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
        "embeds": [{
            "title": "💴 日圓 / 台幣 (JPY/TWD) 匯率動態",
            "description": f"更新時間：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            "color": data["color"],
            "fields": [
                {
                    "name": "📊 最新匯率行情",
                    "value": (
                        f"> **現價**: `1 JPY = {data['price']} TWD`\n"
                        f"> **單日漲跌**: `{trend_emoji} {data['change_pct']}%`\n"
                        f"> **近3月區間**: `{data['min_60d']} ~ {data['max_60d']}`"
                    ),
                    "inline": True
                },
                {
                    "name": "💡 換匯策略評估",
                    "value": (
                        f"> **趨勢均線**: `5MA: {data['ma5']} | 20MA: {data['ma20']}`\n"
                        f"> **策略建議**: **{data['advice']}**"
                    ),
                    "inline": True
                }
            ]
        }]
    }

    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"Discord 推播狀態碼: {resp.status_code}")

def main():
    res = analyze_jpy()
    if res:
        send_discord(res)

if __name__ == "__main__":
    main()
