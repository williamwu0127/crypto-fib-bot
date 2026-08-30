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
    """動態抓取 Google 新聞的中文財經與總經 RSS，確保標題為中文並附帶超連結"""
    news_items = []
    try:
        # 使用 Google 新聞中文版搜尋全球股市、經濟、聯準會等關鍵字
        rss_url = "https://news.google.com/rss/search?q=%E8%82%A1%E5%B8%82+%E7%B6%93%E6%BF%9F+%E8%81%AF%E6%BA%96%E6%9C%83&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:5]:
            title = entry.get('title', '無標題')
            link = entry.get('link', '#')
            
            # 清理可能破壞 Markdown 的特殊字元
            title = title.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
            if len(title) > 75:
                title = title[:72] + "..."
                
            news_items.append(f"• [{title}]({link})")
    except Exception as e:
        print(f"動態抓取新聞失敗: {e}")
        
    if not news_items:
        news_items.append("> 目前無法取得即時新聞，請透過各大財經平台關注本週最新動態。")
        
    return news_items

def main():
    print("【一週全球市場資訊】開始分析美股、亞股、台股、加密貨幣與中文即時新聞...")
    
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

    # --- 第一則訊息：全球指數與加密貨幣行情 ---
    payload_market = {
        "username": "一週全球市場資訊雷達",
        "embeds": [{
            "title": f"🌍 一週全球市場指數與宏觀週報 ({datetime.now().strftime('%Y-%m-%d')})",
            "description": "早安！本週全球資金風向、主要指數與加密貨幣表現總結如下：",
            "color": 15844367,
            "fields": fields
        }]
    }
    print("發送第一則訊息 (市場行情)...")
    send_msg(payload_market)

    # --- 第二則訊息：中文即時財經新聞超連結 ---
    latest_news = fetch_latest_financial_news()
    news_fields = []
    
    for idx, item in enumerate(latest_news, 1):
        news_fields.append({
            "name": f"焦點新聞 {idx}",
            "value": item,
            "inline": False
        })
    
    payload_news = {
        "username": "一週全球市場資訊雷達",
        "embeds": [{
            "title": f"📰 即時全球財經新聞與事件快訊 ({datetime.now().strftime('%Y-%m-%d')})",
            "description": "本週自動抓取的最新中文財經動態與焦點新聞（點擊標題即可查看原文）：",
            "color": 3447003,
            "fields": news_fields
        }]
    }
    print("發送第二則訊息 (中文即時新聞)...")
    send_msg(payload_news)

if __name__ == "__main__":
    main()
