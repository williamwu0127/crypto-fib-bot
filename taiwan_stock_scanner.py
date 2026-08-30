import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

STOCK_POOL = [
    # 半導體 / 電子代工 / AI 概念
    ("2330", "台積電", "TW"), ("2454", "聯發科", "TW"), ("2317", "鴻海", "TW"), 
    ("2382", "廣達", "TW"), ("3231", "緯創", "TW"), ("6669", "緯穎", "TW"), 
    ("2376", "技嘉", "TW"), ("2357", "華碩", "TW"), ("2308", "台達電", "TW"), 
    ("2303", "聯電", "TW"), ("3711", "日月光投控", "TW"), ("3034", "聯詠", "TW"), 
    ("2408", "南亞科", "TW"), ("3443", "創意", "TW"), ("3661", "世芯-KY", "TW"),
    ("3037", "欣興", "TW"), ("8046", "南電", "TW"), ("3035", "智原", "TW"), 
    ("2345", "智邦", "TW"), ("2379", "瑞昱", "TW"), ("3017", "奇鋐", "TW"), 
    ("3324", "雙鴻", "TWO"), ("3529", "力旺", "TWO"), ("6415", "矽力*-KY", "TW"), 
    ("5269", "祥碩", "TW"),
    # 重電 / 綠能 / 航運
    ("1519", "華城", "TW"), ("1513", "中興電", "TW"), ("1504", "東元", "TW"), 
    ("1503", "士電", "TW"), ("1609", "大亞", "TW"), ("2603", "長榮", "TW"), 
    ("2609", "陽明", "TW"), ("2615", "萬海", "TW"), ("2618", "長榮航", "TW"), 
    ("2610", "華航", "TW"),
    # 金融 / 傳產
    ("2881", "富邦金", "TW"), ("2882", "國泰金", "TW"), ("2891", "中信金", "TW"), 
    ("2886", "兆豐金", "TW"), ("2884", "玉山金", "TW")
]

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

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
    scored_results = []
    latest_trade_date = datetime.now().strftime("%Y-%m-%d")

    for sid, name, market in STOCK_POOL:
        ticker_str = f"{sid}.{market}"
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

            # 站上月線基礎門檻
            if today_close < ma20:
                continue

            score = 0
            reasons = []

            # 1. 均線多頭 (+25)
            if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                score += 25
                reasons.append("均線多頭")

            # 2. 突破 20 日高 (+20)
            high_20d = float(high_s.iloc[-21:-1].max())
            if today_close > high_20d:
                score += 20
                reasons.append("突破20日高")

            # 3. 帶量表態 (+20)
            if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.2:
                score += 20
                reasons.append(f"爆量 {round(today_vol/vol_ma5, 1)}x")

            # 4. 實體紅 K (+15)
            k_range = today_high - today_low
            if k_range > 0 and (today_close - today_low) / k_range >= 0.7:
                score += 15
                reasons.append("紅K實體強")

            # 5. RSI & MACD (+20)
            rsi = float(calculate_rsi(close_s).iloc[-1])
            _, _, hist = calculate_macd(close_s)
            if 50 <= rsi <= 75 and hist.iloc[-1] > 0:
                score += 20
                reasons.append("MACD偏多")

            # 扣分
            if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                score -= 15

            # ================= 結構型價位推算 (Price Action) =================
            # 1. 結構性止損 (SL)：取近 5 日波段最低點或今日起漲低點下方作為結構破位防守
            low_5d = float(low_s.iloc[-5:].min())
            sl_price = round(min(low_5d, today_low) * 0.99, 1)

            # 2. 進場區間 (Entry)：回踩 5MA / 突破點 ~ 現價平盤（若 5MA 低於 SL 則用保護性緩衝）
            entry_low = round(max(ma5, today_close * 0.985), 1)
            entry_high = round(today_close * 1.003, 1)
            # 確保 SL 必定在進場區間下方
            if sl_price >= entry_low:
                sl_price = round(entry_low * 0.97, 1)

            # 3. 結構性止盈 (TP)：
            # 回溯近 60 日歷史波段高點（排除今日）
            past_60d_high = float(high_s.iloc[-60:-1].max()) if len(high_s) >= 60 else float(high_s.iloc[:-1].max())

            if past_60d_high > today_close * 1.02:
                # 情況 A：上方有明確的前波高點壓力位 -> 以歷史前高作為止盈目標
                tp_price = round(past_60d_high, 1)
            else:
                # 情況 B：已突破近季新高（上方無套牢賣壓） -> 採用等距箱體對稱測幅
                low_20d = float(low_s.iloc[-20:].min())
                box_height = today_close - low_20d
                tp_price = round(today_close + box_height, 1)

            scored_results.append({
                "sid": sid,
                "name": name,
                "entry": f"{entry_low} ~ {entry_high}",
                "tp": tp_price,
                "sl": sl_price,
                "score": score,
                "tags": " ‧ ".join(reasons) if reasons else "多頭結構"
            })

        except Exception:
            continue

    top_picks = sorted(scored_results, key=lambda x: x["score"], reverse=True)[:5]
    
    fields = []
    for item in top_picks:
        fields.append({
            "name": f"📌 {item['sid']} {item['name']}",
            "value": (
                f"> **進場**: `{item['entry']}`\n"
                f"> **止盈 (TP)**: `{item['tp']}`\n"
                f"> **止損 (SL)**: `{item['sl']}`\n"
                f"> **特徵**: `{item['tags']}`"
            ),
            "inline": False
        })

    payload = {
        "username": "台股量化選股",
        "embeds": [{
            "title": f"📈 台股盤後精選 ({latest_trade_date})",
            "color": 3447003,
            "fields": fields if fields else [{"name": "提示", "value": "今日無符合條件個股"}]
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
