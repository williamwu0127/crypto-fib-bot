import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# Discord Webhook 網址
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

# 精選台股熱門流動性大池（台灣50 + 中型100 + 近期強勢權值股）
STOCK_POOL = [
    # 半導體 / 電子代工 / AI 概念
    ("2330", "台積電"), ("2454", "聯發科"), ("2317", "鴻海"), ("2382", "廣達"), ("3231", "緯創"),
    ("6669", "緯穎"), ("2376", "技嘉"), ("2357", "華碩"), ("2308", "台達電"), ("2303", "聯電"),
    ("3711", "日月光投控"), ("3034", "聯詠"), ("2408", "南亞科"), ("3443", "創意"), ("3661", "世芯-KY"),
    ("3037", "欣興"), ("8046", "南電"), ("3035", "智原"), ("2345", "智邦"), ("2379", "瑞昱"),
    ("3017", "奇鋐"), ("3324", "雙鴻"), ("3529", "力旺"), ("6415", "矽力*-KY"), ("5269", "祥碩"),
    # 重電 / 綠能 / 航運 / 傳統龍頭
    ("1519", "華城"), ("1513", "中興電"), ("1504", "東元"), ("1503", "士電"), ("1609", "大亞"),
    ("2603", "長榮"), ("2609", "陽明"), ("2615", "萬海"), ("2618", "長榮航"), ("2610", "華航"),
    # 金融 / 傳產
    ("2881", "富邦金"), ("2882", "國泰金"), ("2891", "中信金"), ("2886", "兆豐金"), ("2884", "玉山金"),
    ("2002", "中鋼"), ("1101", "台泥"), ("1301", "台塑"), ("1303", "南亞"), ("2912", "統一超")
]

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

def scan_stocks():
    tickers = [f"{sid}.TW" for sid, _ in STOCK_POOL]
    name_map = {f"{sid}.TW": (sid, name) for sid, name in STOCK_POOL}

    print(f"正在批次下載 {len(tickers)} 檔標的歷史 K 線數據...")
    # 下載近 3 個月日 K
    df_data = yf.download(tickers, period="3mo", interval="1d", group_by="ticker", progress=False)

    scored_results = []
    latest_trade_date = ""

    for ticker in tickers:
        sid, name = name_map[ticker]
        try:
            if ticker not in df_data.columns.levels[0]:
                continue
            
            df_k = df_data[ticker].dropna()
            if len(df_k) < 25:
                continue

            latest_trade_date = df_k.index[-1].strftime("%Y-%m-%d")

            close_s = df_k["Close"]
            high_s = df_k["High"]
            low_s = df_k["Low"]
            vol_s = df_k["Volume"]

            today_close = float(close_s.iloc[-1])
            today_high = float(high_s.iloc[-1])
            today_low = float(low_s.iloc[-1])
            today_vol = float(vol_s.iloc[-1])

            # 計算均線
            ma5 = float(close_s.rolling(5).mean().iloc[-1])
            ma10 = float(close_s.rolling(10).mean().iloc[-1])
            ma20_s = close_s.rolling(20).mean()
            ma20 = float(ma20_s.iloc[-1])
            ma20_slope = ma20 - float(ma20_s.iloc[-2])
            vol_ma5 = float(vol_s.rolling(5).mean().iloc[-1])

            # 估算成交金額（億元）
            est_turnover_mil = (today_close * today_vol) / 100_000_000

            # 門檻安全閥：收盤價 >= 20MA 且 成交額 >= 0.5 億
            if today_close < ma20 or est_turnover_mil < 0.5:
                continue

            score = 0
            reasons = []

            # 1. 均線多頭排列 (+25)
            if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                score += 25
                reasons.append("均線多頭排列 (20MA向上)")

            # 2. 創 20 日新高 (+20)
            high_20d = float(close_s.iloc[-21:-1].max())
            if today_close > high_20d:
                score += 20
                reasons.append("突破近20日新高")

            # 3. 量能爆發 (+20)
            if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.3:
                score += 20
                reasons.append(f"爆量表態 (量比 {round(today_vol/vol_ma5, 1)}x)")

            # 4. 實體紅 K 品質 (+15)
            k_range = today_high - today_low
            if k_range > 0 and (today_close - today_low) / k_range >= 0.75:
                score += 15
                reasons.append("實體紅 K 收高")

            # 5. MACD / RSI 動能 (+20)
            rsi = float(calculate_rsi(close_s).iloc[-1])
            _, _, hist = calculate_macd(close_s)
            if 50 <= rsi <= 75 and hist.iloc[-1] > 0:
                score += 20
                reasons.append("MACD 偏多 / RSI 處強勢區")

            # 風險扣分機制
            if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                score -= 15
                reasons.append("上影線偏長 (-15)")
            if rsi > 80:
                score -= 10
                reasons.append("RSI 過熱超買 (-10)")

            scored_results.append({
                "sid": sid,
                "name": name,
                "close": round(today_close, 2),
                "ma20": round(ma20, 2),
                "turnover_mil": round(est_turnover_mil, 2),
                "score": score,
                "reasons": reasons
            })

        except Exception as e:
            continue

    return scored_results, latest_trade_date

def send_discord(results, trade_date):
    if not results:
        payload = {
            "username": "台股量化選股機器人",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
            "embeds": [{
                "title": f"📊 台股策略掃描報告 ({trade_date})",
                "description": "今日盤後掃描完成，核心標的池中暫無符合高分條件之個股。",
                "color": 8421504,
                "footer": {"text": "量化篩選系統 • 僅供策略參考"}
            }]
        }
    else:
        # 按總分排序取前 5
        top_picks = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
        fields = []
        for item in top_picks:
            reasons_str = "、".join(item["reasons"]) if item["reasons"] else "無"
            fields.append({
                "name": f"🎯 【{item['sid']} {item['name']}】 總評分: {item['score']} 分",
                "value": f"• **收盤價**: `{item['close']}` 元 (防守 20MA: `{item['ma20']}`)\n• **成交金額**: `{item['turnover_mil']}` 億元\n• **觸發特徵**: {reasons_str}",
                "inline": False
            })

        payload = {
            "username": "台股量化選股機器人",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
            "embeds": [{
                "title": f"📊 每日台股高勝率篩選報告 ({trade_date})",
                "description": f"掃描時間：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n已完成指標多維度計算，精選高分標的：",
                "color": 15158332 if top_picks[0]["score"] >= 70 else 3066993,
                "fields": fields,
                "footer": {"text": "量化篩選系統 • 僅供策略參考"}
            }]
        }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    print(f"Discord 推播回應狀態: {resp.status_code}")

def main():
    print("開始執行台股掃描...")
    results, trade_date = scan_stocks()
    print(f"計算完成！共有 {len(results)} 檔符合基礎門檻。")
    send_discord(results, trade_date)

if __name__ == "__main__":
    main()
