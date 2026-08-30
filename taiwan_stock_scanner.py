import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

STOCK_POOL = [
    # 半導體 / IC 設計 / 封測 / 矽智財
    ("2330", "台積電", "TW"), ("2454", "聯發科", "TW"), ("2303", "聯電", "TW"), 
    ("3711", "日月光投控", "TW"), ("3034", "聯詠", "TW"), ("2408", "南亞科", "TW"), 
    ("3443", "創意", "TW"), ("3661", "世芯-KY", "TW"), ("3035", "智原", "TW"), 
    ("3529", "力旺", "TWO"), ("6415", "矽力*-KY", "TW"), ("5269", "祥碩", "TW"),
    ("6531", "愛普*", "TW"), ("6770", "力積電", "TW"), ("2458", "義隆", "TW"),
    ("4966", "譜瑞-KY", "TWO"), ("6223", "旺矽", "TWO"), ("3264", "欣銓", "TWO"),
    
    # AI 伺服器 / 代工 / 機殼 / 散熱 / 零組件
    ("2317", "鴻海", "TW"), ("2382", "廣達", "TW"), ("3231", "緯創", "TW"), 
    ("6669", "緯穎", "TW"), ("2376", "技嘉", "TW"), ("2357", "華碩", "TW"), 
    ("2308", "台達電", "TW"), ("2345", "智邦", "TW"), ("2379", "瑞昱", "TW"), 
    ("3017", "奇鋐", "TW"), ("3324", "雙鴻", "TWO"), ("3037", "欣興", "TW"), 
    ("8046", "南電", "TW"), ("2368", "金像電", "TW"), ("3653", "健策", "TW"),
    ("2059", "川湖", "TW"), ("2383", "台光電", "TW"), ("6274", "台燿", "TWO"),
    
    # 重電 / 綠能 / 能源
    ("1519", "華城", "TW"), ("1513", "中興電", "TW"), ("1504", "東元", "TW"), 
    ("1503", "士電", "TW"), ("1609", "大亞", "TW"), ("6806", "森崴能源", "TW"),
    ("1514", "亞力", "TW"), ("8996", "高力", "TW"),
    
    # 航運 / 航空
    ("2603", "長榮", "TW"), ("2609", "陽明", "TW"), ("2615", "萬海", "TW"), 
    ("2618", "長榮航", "TW"), ("2610", "華航", "TW"), ("2637", "慧洋-KY", "TW"),
    
    # 自動化 / 工具機
    ("2359", "所羅門", "TW"), ("4562", "穎漢", "TW"), ("8374", "羅昇", "TW"),
    ("2464", "盟立", "TW"), ("1590", "亞德客-KY", "TW"),
    
    # 金融股
    ("2881", "富邦金", "TW"), ("2882", "國泰金", "TW"), ("2891", "中信金", "TW"), 
    ("2886", "兆豐金", "TW"), ("2884", "玉山金", "TW"), ("2885", "元大金", "TW"),
    ("2892", "第一金", "TW"), ("5880", "合庫金", "TW"), ("2883", "開發金", "TW"),
    
    # 傳產 / 塑化 / 生技
    ("2002", "中鋼", "TW"), ("1101", "台泥", "TW"), ("1301", "台塑", "TW"), 
    ("1303", "南亞", "TW"), ("2912", "統一超", "TW"), ("1216", "統一", "TW"),
    ("6446", "藥華藥", "TWO"), ("1795", "美時", "TW"), ("4743", "合一", "TWO")
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

    ticker_list = [f"{sid}.{mkt}" for sid, _, mkt in STOCK_POOL]
    meta_dict = {f"{sid}.{mkt}": (sid, name) for sid, name, mkt in STOCK_POOL}

    print(f"正在批次抓取 {len(ticker_list)} 檔標的行情...")
    all_data = yf.download(ticker_list, period="3mo", interval="1d", group_by="ticker", progress=False)

    for ticker in ticker_list:
        sid, name = meta_dict[ticker]
        try:
            if ticker not in all_data.columns.levels[0]:
                continue
            
            df = all_data[ticker].dropna()
            if len(df) < 25:
                continue

            latest_trade_date = df.index[-1].strftime("%Y-%m-%d")

            close_s = df['Close']
            high_s = df['High']
            low_s = df['Low']
            open_s = df['Open']
            vol_s = df['Volume']

            today_close = float(close_s.iloc[-1])
            today_high = float(high_s.iloc[-1])
            today_low = float(low_s.iloc[-1])
            today_open = float(open_s.iloc[-1])
            today_vol = float(vol_s.iloc[-1])

            ma5 = float(close_s.rolling(5).mean().iloc[-1])
            ma10 = float(close_s.rolling(10).mean().iloc[-1])
            ma20_s = close_s.rolling(20).mean()
            ma20 = float(ma20_s.iloc[-1])
            ma20_slope = ma20 - float(ma20_s.iloc[-2])
            vol_ma5 = float(vol_s.rolling(5).mean().iloc[-1])

            # 基礎門檻：站上月線且非長黑
            if today_close < ma20 or today_close < today_open * 0.99:
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

            # 扣分：上影線過長
            if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                score -= 15

            # ================= 波段合理價位計算 (6%~8% 安全防守) =================
            # 1. 進場區間：回踩 1.0% ~ 現價平盤 +0.3%
            entry_low = round(today_close * 0.99, 1)
            entry_high = round(today_close * 1.003, 1)

            # 2. 波段安全止損 (SL)：
            # 參考近 5 日波段低點或 10MA，距離進場下緣約 6.0% ~ 8.0%
            support_low = min(float(low_s.iloc[-5:].min()), ma10)
            # 限制止損距離在 6% ~ 8% 區間內
            sl_price = round(max(support_low * 0.99, entry_low * 0.925), 1)
            if sl_price > entry_low * 0.94:
                sl_price = round(entry_low * 0.935, 1)  # 保持至少 6.5% 的安全波動距離

            # 3. 結構性止盈 (TP)：
            past_60d_high = float(high_s.iloc[-60:-1].max()) if len(high_s) >= 60 else float(high_s.iloc[:-1].max())
            if past_60d_high > today_close * 1.04:
                tp_price = round(past_60d_high, 1)
            else:
                # 創新高時按 1:2 風報比或近 15 日波動空間向上延伸
                swing_range = today_close - float(low_s.iloc[-15:].min())
                tp_price = round(today_close + max(swing_range, (entry_high - sl_price) * 1.8), 1)

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

    top_picks = sorted(scored_results, key=lambda x: x["score"], reverse=True)[:10]
    
    # 建立強制作為「雙欄（2 Column）」的排版結構
    fields = []
    for i, item in enumerate(top_picks):
        fields.append({
            "name": f"📌 {item['sid']} {item['name']}",
            "value": (
                f"> **進場**: `{item['entry']}`\n"
                f"> **止盈 (TP)**: `{item['tp']}`\n"
                f"> **止損 (SL)**: `{item['sl']}`\n"
                f"> **特徵**: `{item['tags']}`"
            ),
            "inline": True
        })
        # 每 2 個標的插入 1 個空白欄位，強制 Discord 換行（固定左、右雙欄）
        if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    # 判斷是盤前還是盤後標題
    hour_utc = datetime.utcnow().hour
    session_title = "盤前精選" if hour_utc < 5 else "盤後精選"

    payload = {
        "username": "台股量化選股",
        "embeds": [{
            "title": f"📈 台股{session_title} Top 10 ({latest_trade_date})",
            "color": 3447003,
            "fields": fields if fields else [{"name": "提示", "value": "今日無符合條件個股"}]
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
