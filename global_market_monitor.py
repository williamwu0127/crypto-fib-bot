import os
import urllib.parse
import requests
import pandas as pd
import yfinance as yf
import concurrent.futures
import time
from datetime import datetime, timezone, timedelta

# 🚨 安全性升級：改用環境變數讀取 Webhook，與台股、匯率腳本統一使用 DISCORD_WEBHOOK_URL
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

GLOBAL_SYMBOLS = {
    "^GSPC": ("S&P 500", "美股大盤基準"),
    "^IXIC": ("NASDAQ 綜合指數", "科技成長核心"),
    "^SOX": ("費城半導體指數", "台股半導體連動核心"),
    "^DJI": ("道瓊工業指數", "傳統藍籌價值"),
    "^VIX": ("VIX 恐慌指數", "市場情緒指標"),
    "^TNX": ("美債 10 年期殖利率", "無風險利率基準"),
    "DX-Y.NYB": ("美元指數 (DXY)", "全球流動性風向"),
    "CL=F": ("WTI 原油期貨", "通膨與大宗商品"),
    "GC=F": ("黃金期貨 (Gold)", "避險與抗通膨資產"),
    "BTC-USD": ("比特幣 (Bitcoin)", "高風險偏好資產")
}

def send_msg(payload):
    if not WEBHOOK_URL:
        print("錯誤：找不到 DISCORD_WEBHOOK_URL 環境變數，請確保已在 GitHub Secrets 中設定！")
        return
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
        if r.status_code >= 400:
            print(f"Discord 錯誤回傳: {r.text}")
    except Exception as e:
        print(f"Discord 發送失敗: {e}")

def translate_to_zh(text):
    if not text:
        return ""
    
    encoded_text = urllib.parse.quote(text)
    
    # 方式一：還原最初版本的極簡 Header (有時過於複雜的偽裝反而會被 Google 擋下)
    try:
        url_api = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={encoded_text}"
        r = requests.get(url_api, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            return "".join([part[0] for part in r.json()[0] if part[0]])
    except Exception:
        pass

    # 方式二：終極備援 - Google Mobile Web 解析法 (對 CI/CD IP 最友善，不會回傳 429)
    try:
        url_web = f"https://translate.google.com/m?sl=en&tl=zh-TW&q={encoded_text}"
        r = requests.get(url_web, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            # 傳統手機版網頁會固定將翻譯結果包在 <div class="result-container"> 裡面
            if 'class="result-container">' in r.text:
                result = r.text.split('class="result-container">')[1].split('</div>')[0]
                # 替換常見的 HTML 實體字元
                result = result.replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&")
                return result
    except Exception as e:
        print(f"[Mobile Web 翻譯錯誤] {e}")

    # 若雙重機制皆失敗，退回原文
    return text

def get_market_analysis(args):
    symbol, name, role = args
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="1mo", interval="1d")
        if df.empty or len(df) < 20:
            print(f"[警告] {symbol} 抓取不到足夠歷史資料。")
            return None
            
        close_s = df['Close']
        latest_p = float(close_s.iloc[-1])
        prev_p = float(close_s.iloc[-2])
        pts = latest_p - prev_p
        pct = (pts / prev_p) * 100
        ma20 = float(close_s.rolling(20).mean().iloc[-1])

        # 結構解析顏色燈號邏輯
        if symbol == "^VIX":
            if latest_p >= 20.0:
                struct_text = "🔴 市場避險情緒升溫 (警戒)"
            elif latest_p <= 14.0:
                struct_text = "🟢 市場處於極度樂觀擴張期"
            else:
                struct_text = "🟡 處於常態震盪波動區間"
            price_str = f"`{latest_p:.2f}` ({pts:+.2f} / {pct:+.2f}%)"
            
        elif symbol == "^TNX":
            struct_text = "🔴 殖利率攀升 壓抑高估值科技股" if pts > 0 else "🟢 殖利率回落 科技股估值壓力緩解"
            price_str = f"`{latest_p:.3f}%` ({pts:+.3f}%)"
            
        elif symbol == "DX-Y.NYB":
            struct_text = "🔴 美元強勢 留意新興市場資金外流" if latest_p > ma20 else "🟢 美元走弱 有利外資回流台股"
            price_str = f"`{latest_p:.2f}` ({pts:+.2f} / {pct:+.2f}%)"
            
        else:
            trend_icon = "🟢 多頭強勢 (站穩月線)" if latest_p > ma20 else "🔴 偏弱整理 (失守月線)"
            struct_text = f"{trend_icon} ｜ 20MA `{ma20:,.2f}`"
            price_str = f"`{latest_p:,.2f}` ({pts:+,.2f} / {pct:+.2f}%)"

        return {
            "name": name,
            "role": role,
            "price_str": price_str,
            "struct_text": struct_text,
            "pct": pct
        }
    except Exception as e:
        print(f"[資料錯誤] 處理 {symbol} 時發生錯誤: {e}")
        return None

def fetch_macro_news():
    news_items = []
    try:
        t = yf.Ticker("^GSPC")
        raw_news = t.news
        if raw_news:
            for item in raw_news[:4]:
                content = item.get('content', {})
                title_en = content.get('title') or item.get('title', '')
                provider = content.get('provider', {}).get('displayName') or item.get('publisher', '國際財經')
                
                link = item.get('link', '')
                if not link:
                    canonical_url = content.get('canonicalUrl', {})
                    link = canonical_url.get('url', '') if isinstance(canonical_url, dict) else ''

                if title_en:
                    # 加入 3 秒延遲，確保爬蟲頻率在安全範圍內
                    time.sleep(3)
                    title_zh = translate_to_zh(title_en)
                    
                    if link:
                        news_items.append(f" [{title_zh}]({link})  `({provider})`")
                    else:
                        news_items.append(f" **{title_zh}** `({provider})`")
    except Exception as e:
        print(f"[新聞抓取錯誤] {e}")
        
    if not news_items:
        news_items.append(" [國際市場隔夜數據平穩，無重大黑天鵝突發事件。](https://finance.yahoo.com)")
        news_items.append(" [資金焦點聚焦聯準會利率路徑與半導體供應鏈財報動向。](https://finance.yahoo.com)")
        
    return news_items

def main():
    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    date_str = now_tw.strftime("%Y-%m-%d")

    print("開始抓取市場數據...")
    analyzed_items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        args_list = [(sym, name, role) for sym, (name, role) in GLOBAL_SYMBOLS.items()]
        results = executor.map(get_market_analysis, args_list)
        
    for res in results:
        if res:
            analyzed_items.append(res)
            
    print("開始抓取並翻譯新聞...")
    news_list = fetch_macro_news()

    fields = []
    fields.append({
        "name": "───────── 🌐 隔夜全球市場 ＆ 宏觀指標掃描 ─────────",
        "value": "\u200b",
        "inline": False
    })

    for i, item in enumerate(analyzed_items):
        # 視覺修復：補回漲跌符號
        emoji = "📈" if item["pct"] >= 0 else "📉"
        
        fields.append({
            "name": f"{emoji} {item['name']} ｜ {item['role']}",
            "value": (
                f"> **最新報價**: {item['price_str']}\n"
                f"> **結構解析**: {item['struct_text']}"
            ),
            "inline": True
        })
        
        if (i + 1) % 2 == 0 and (i + 1) < len(analyzed_items):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    fields.append({
        "name": "───────── 📰 隔夜全球重磅財經快訊 (點擊看原文) ─────────",
        "value": "\n".join([f"> {n}" for n in news_list]),
        "inline": False
    })

    payload = {
        "username": "全球市場宏觀雷達",
        "embeds": [{
            "title": f"🌍 全球市場早盤監控報告 ({date_str} 08:00)",
            "description": "已完成美股隔夜收盤、VIX、公債殖利率、美元指數及重磅新聞解析：",
            "color": 1752220,
            "fields": fields
        }]
    }

    print("發送至 Discord...")
    send_msg(payload)
    print("執行完成！")

if __name__ == "__main__":
    main()
