import os
import requests
import yfinance as yf
from datetime import datetime

# 從系統環境變數讀取 Webhook URL (由 GitHub Actions 的 Secrets 注入)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not WEBHOOK_URL:
    raise ValueError("找不到 DISCORD_WEBHOOK_URL，請確保已在 GitHub Secrets 中設定！")

def analyze_currency(ticker_symbol, currency_name, icon):
    try:
        # 下載兌台幣近 3 個月歷史數據
        ticker = yf.Ticker(ticker_symbol)
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

        # 換匯建議評估 (通用邏輯)
        advice = "區間震盪觀望"
        color = 3447003  # 藍色

        if latest_price <= min_60d * 1.005:
            advice = "🟢 觸及波段極低點（極佳換匯買點）"
            color = 5763719  # 綠色
        elif latest_price < ma20:
            advice = "🟡 處於月線下方（適合分批佈局）"
            color = 16776960  # 黃色
        elif change_pct >= 0.8:
            advice = "🔴 急漲反彈（暫緩追高）"
            color = 15548997  # 紅色

        return {
            "name": currency_name,
            "symbol": ticker_symbol.replace("=X", ""),
            "icon": icon,
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
        print(f"抓取 {currency_name} 資料出錯: {e}")
        return None

def send_discord(results):
    embeds = []
    
    # 建立多個貨幣的 Embed 區塊
    for data in results:
        trend_emoji = "🔺" if data["change_pct"] > 0 else "🔻"
        base_currency = data['symbol'][:3] # 提取 JPY, USD, CNY
        
        embeds.append({
            "title": f"{data['icon']} {data['name']} / 台幣 ({data['symbol']}) 匯率動態",
            "description": f"更新時間：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            "color": data["color"],
            "fields": [
                {
                    "name": "📊 最新匯率行情",
                    "value": (
                        f"> **現價**: `1 {base_currency} = {data['price']} TWD`\n"
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
        })

    payload = {
        "username": "全球匯率監控",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
        "embeds": embeds
    }

    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"Discord 推播狀態碼: {resp.status_code}")

def main():
    # 定義要監控的貨幣列表
    target_currencies = [
        ("USDTWD=X", "美元", "💵"),
        ("JPYTWD=X", "日圓", "💴"),
        ("CNYTWD=X", "人民幣", "💴")
    ]
    
    results = []
    for ticker, name, icon in target_currencies:
        res = analyze_currency(ticker, name, icon)
        if res:
            results.append(res)
            
    if results:
        send_discord(results)

if __name__ == "__main__":
    main()
