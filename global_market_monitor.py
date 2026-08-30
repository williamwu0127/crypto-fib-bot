import os
import requests
import feedparser
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
        prev_week_close = float(df['Close'].iloc[-6])
        weekly_change_pct = round(((latest_close - prev_week_close) / prev_week_close) * 100, 2)
        
        ma20 = float(df['Close'].rolling(20).mean().iloc[-1])
        trend = "多頭排列 🟢" if latest_close > ma20 else "弱勢整理 🔴"
        
        return latest_close, weekly_change_pct, trend
    except Exception as e:
        print(f"獲取 {ticker_symbol} 失敗: {e}")
        return None, None, None

def fetch_latest_financial_news():
    """動態抓取 Yahoo Finance 的即時財經新聞 RSS 作為參考"""
    news_list = []
    try:
        rss_url = "https://finance.yahoo.com/news/rssindex"
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:5]:
            title = entry.get('title', '無標題')
            link = entry.get('link', '#')
            news_list.append(f"📌 [{title}]({link})")
    except Exception as e:
        print(f"動態抓取新聞失敗: {e}")
        
    if not news_list:
        news_list.append("> 目前無法取得即時新聞，請透過各大財經平台關注本週聯準會動向與總經數據。")
        
    return news_list

def main():
    print("【一週全球市場資訊】開始分析美股、亞股、台股、加密貨幣與即時新聞...")
    
    targets = {
        "🇺🇸 那斯達克 (^IXIC)": "^IXIC",
        "🇺🇸 道瓊工業 (^DJI)": "^DJI",
        "🇺🇸 標普 500 (^GSPC)": "^GSPC",
        "🇯🇵 日本日經 225 (^N225)": "^N225",
        "🇰🇷 韓國綜合 (^KS11)": "^KS11",
        "🇹🇼 台股加權指數 (^TWII)": "^TWII",
        "₿ 比特幣 (BTC-USD)": "BTC-USD",
        "Ξ 以太幣 (ETH-USD)": "ETH-USD"
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

    latest_news = fetch_latest_financial_news()
    news_text = "\n".join([f"> {item}" for item in latest_news])
    
    fields.append({
        "name": "───────── 📰 即時全球財經新聞快訊 ─────────",
        "value": news_text,
        "inline": False
    })

    payload = {
        "username": "一週全球市場資訊雷達",
        "embeds": [{
            "title": f"🌍 一週全球市場資訊與宏觀週報 ({datetime.now().strftime('%Y-%m-%d')})",
            "description": "早安！本週全球資金風向、主要指數、加密貨幣表現以及自動抓取的最新市場動態如下：",
            "color": 15844367,
            "fields": fields
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
