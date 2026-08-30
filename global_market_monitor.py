import os
import requests
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

def get_weekly_performance(ticker_symbol):
    """計算特定標的過去一週（約5個交易日）的漲跌幅與趨勢"""
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1mo", interval="1d")
        if df.empty or len(df) < 6:
            return None, None, None
            
        latest_close = float(df['Close'].iloc[-1])
        # 取大約 5 個交易日前（上一週收盤）的價格來計算週漲跌
        prev_week_close = float(df['Close'].iloc[-6])
        weekly_change_pct = round(((latest_close - prev_week_close) / prev_week_close) * 100, 2)
        
        ma20 = float(df['Close'].rolling(20).mean().iloc[-1])
        trend = "多頭排列 🟢" if latest_close > ma20 else "弱勢整理 🔴"
        
        return latest_close, weekly_change_pct, trend
    except Exception as e:
        print(f"獲取 {ticker_symbol} 失敗: {e}")
        return None, None, None

def main():
    print("【全球宏觀】開始分析美股、亞股與台股上週趨勢...")
    
    targets = {
        "🇺🇸 那斯達克 (^IXIC)": "^IXIC",
        "🇺🇸 道瓊工業 (^DJI)": "^DJI",
        "🇺🇸 標普 500 (^GSPC)": "^GSPC",
        "🇯🇵 日本日經 225 (^N225)": "^N225",
        "🇰🇷 韓國綜合 (^KS11)": "^KS11",
        "🇹🇼 台股加權指數 (^TWII)": "^TWII"
    }
    
    fields = []
    for name, symbol in targets.items():
        close, pct, trend = get_weekly_performance(symbol)
        if close is not None:
            sign = "+" if pct > 0 else ""
            fields.append({
                "name": name,
                "value": f"> 收盤: `{close:,.2f}`\n> 週漲跌: `{sign}{pct}%`\n> 技術面: `{trend}`",
                "inline": True
            })

    payload = {
        "username": "全球市場宏觀雷達",
        "embeds": [{
            "title": f"🌍 跨市場宏觀週報與趨勢預測 ({datetime.now().strftime('%Y-%m-%d')})",
            "description": "早安！本週全球資金風向與主要指數上週表現總結如下，請作為本週操作規劃之參考：",
            "color": 15844367,
            "fields": fields if fields else [{"name": "提示", "value": "暫無數據"}]
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
