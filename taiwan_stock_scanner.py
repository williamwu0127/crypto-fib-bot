import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# 優先讀取環境變數，若無則使用指定 Webhook
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
if not WEBHOOK_URL or not WEBHOOK_URL.startswith("http"):
    WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

STOCK_POOL = [
    ("2330", "台積電"), ("2454", "聯發科"), ("2317", "鴻海"), ("2382", "廣達"), ("3231", "緯創"),
    ("6669", "緯穎"), ("2376", "技嘉"), ("2357", "華碩"), ("2308", "台達電"), ("2303", "聯電"),
    ("3711", "日月光投控"), ("3034", "聯詠"), ("2408", "南亞科"), ("3443", "創意"), ("3661", "世芯-KY"),
    ("3037", "欣興"), ("8046", "南電"), ("3035", "智原"), ("2345", "智邦"), ("2379", "瑞昱"),
    ("3017", "奇鋐"), ("3324", "雙鴻"), ("3529", "力旺"), ("6415", "矽力*-KY"), ("5269", "祥碩"),
    ("1519", "華城"), ("1513", "中興電"), ("1504", "東元"), ("1503", "士電"), ("1609", "大亞"),
    ("2603", "長榮"), ("2609", "陽明"), ("2615", "萬海"), ("2618", "長榮航"), ("2610", "華航"),
    ("2881", "富邦金"), ("2882", "國泰金"), ("2891", "中信金"), ("2886", "兆豐金"), ("2884", "玉山金")
]

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
        if r.status_code not in [200, 204]:
            print(f"推播錯誤詳情: {r.text}")
    except Exception as e:
        print(f"發送 Discord 異常: {e}")

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    dif = exp1 - exp2
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist

def main():
    print(f"目標 Webhook: {WEBHOOK_URL[:45]}...")
    
    scored_results = []
    latest_trade_date = datetime.now().strftime("%Y-%m-%d")

    for sid, name in STOCK_POOL:
        ticker_str = f"{sid}.TW"
        try:
            stock = yf.Ticker(ticker_str)
            df = stock.history(period="3mo", interval="1d")
            
            if df.empty or len(df) < 25:
                continue

            latest_trade_date = df.index[-1].strftime("%Y-%m-%d")
            
            close_s = df['Close']
            high_s = df['High']
            low_s = df['Low']
            vol_s = df['Volume']

            today_close = float(close_s.iloc[-1])
            today_high = float(high_s.iloc[-1])
            today_low = float(low_s.iloc[-1])
            today_vol = float(vol_s.iloc[-1])

            ma5 = float(close_s.rolling(5).mean().iloc[-1])
            ma10 = float(close_s.rolling(10).mean().iloc[-1])
            ma20_s = close_s.rolling(20).mean()
            ma20 = float(ma20_s.iloc[-1])
            ma20_slope = ma20 - float(ma20_s.iloc[-2])
            vol_ma5 = float(vol_s.rolling(5).mean().iloc[-1])

            est_money_mil = (today_close * today_vol) / 100_000_000

            # 基礎門檻
            if today_close < ma20:
                continue

            score = 0
            reasons = []

            # 均線多頭 (+25)
            if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                score += 25
                reasons.append("均線多頭 (20MA向上)")

            # 突破20日高 (+20)
            high_20d = float(close_s.iloc[-21:-1].max())
            if today_close > high_20d:
                score += 20
                reasons.append("突破20日新高")

            # 爆量表態 (+20)
            if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.2:
                score += 20
                reasons.append(f"帶量表態 (量比 {round(today_vol/vol_ma5, 1)}x)")

            # 實體紅K (+15)
            k_range = today_high - today_low
            if k_range > 0 and (today_close - today_low) / k_range >= 0.7:
                score += 15
                reasons.append("實體紅K收高")

            # RSI & MACD (+20)
            rsi = float(calculate_rsi(close_s).iloc[-1])
            _, _, hist = calculate_macd(close_s)
            if 50 <= rsi <= 75 and hist.iloc[-1] > 0:
                score += 20
                reasons.append("MACD偏多 / RSI強勢區")

            # 上影線扣分
            if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                score -= 15
                reasons.append("上影線偏長 (-15)")

            scored_results.append({
                "sid": sid,
                "name": name,
                "close": round(today_close, 2),
                "ma20": round(ma20, 2),
                "turnover_mil": round(est_money_mil, 2),
                "score": score,
                "reasons": reasons
            })

        except Exception as e:
            print(f"分析 {sid} 出錯: {e}")

    # 排序取前 5 檔
    top_picks = sorted(scored_results, key=lambda x: x["score"], reverse=True)[:5]
    
    fields = []
    for item in top_picks:
        reasons_str = "、".join(item["reasons"]) if item["reasons"] else "符合多頭支撐"
        fields.append({
            "name": f"🎯 【{item['sid']} {item['name']}】 綜合評分: {item['score']} 分",
            "value": f"• **收盤價**: `{item['close']}` 元 (防守月線: `{item['ma20']}`)\n• **預估成交額**: `{item['turnover_mil']}` 億元\n• **型態特徵**: {reasons_str}",
            "inline": False
        })

    payload = {
        "username": "台股量化選股機器人",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
        "embeds": [{
            "title": f"📊 台股高勝率篩選報告 ({latest_trade_date})",
            "description": f"✅ **掃描執行完畢**\n共篩選 {len(STOCK_POOL)} 檔權值主流股，精選前 5 名多頭標的：",
            "color": 3066993 if (top_picks and top_picks[0]["score"] >= 60) else 8421504,
            "fields": fields if fields else [{"name": "提示", "value": "目前暫無符合門檻個股"}],
            "footer": {"text": "量化指標篩選 • 僅供策略參考"}
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
