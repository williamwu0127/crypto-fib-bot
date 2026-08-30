import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_twse_tpex_daily():
    """向證交所及櫃買中心官方抓取當日量價與三大法人買賣超"""
    today_str = datetime.now().strftime("%Y%m%d")
    stock_dict = {}

    # 1. 抓取上市 (TWSE) 當日收盤行情
    try:
        url_twse = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={today_str}&type=ALLBUT0999&response=json"
        res = requests.get(url_twse, headers=HEADERS, timeout=15).json()
        if res.get("stat") == "OK":
            # 找到包含股票代號、收盤價、成交金額的表格
            tables = res.get("tables", [])
            for table in tables:
                fields = table.get("fields", [])
                if "證券代號" in fields and "收盤價" in fields:
                    idx_id = fields.index("證券代號")
                    idx_name = fields.index("證券名稱")
                    idx_close = fields.index("收盤價")
                    idx_vol = fields.index("成交股數")
                    idx_money = fields.index("成交金額")
                    idx_open = fields.index("開盤價")
                    idx_high = fields.index("最高價")
                    idx_low = fields.index("最低價")

                    for row in table.get("data", []):
                        sid = row[idx_id].strip()
                        if len(sid) == 4 and sid.isdigit():
                            try:
                                close_p = float(row[idx_close].replace(",", ""))
                                money = float(row[idx_money].replace(",", ""))
                                open_p = float(row[idx_open].replace(",", ""))
                                high_p = float(row[idx_high].replace(",", ""))
                                low_p = float(row[idx_low].replace(",", ""))
                                vol = float(row[idx_vol].replace(",", ""))
                                stock_dict[sid] = {
                                    "name": row[idx_name].strip(),
                                    "close": close_p,
                                    "open": open_p,
                                    "high": high_p,
                                    "low": low_p,
                                    "turnover": money,
                                    "volume": vol,
                                    "market": "TW",
                                    "it_buy": 0,
                                    "foreign_buy": 0
                                }
                            except ValueError:
                                continue
    except Exception as e:
        print(f"TWSE 量價獲取異常: {e}")

    # 2. 抓取上市三大法人買賣超
    try:
        url_inst = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={today_str}&selectType=ALLBUT0999&response=json"
        res_inst = requests.get(url_inst, headers=HEADERS, timeout=15).json()
        if res_inst.get("stat") == "OK":
            for row in res_inst.get("data", []):
                sid = row[0].strip()
                if sid in stock_dict:
                    try:
                        foreign_diff = float(row[4].replace(",", ""))
                        it_diff = float(row[10].replace(",", ""))
                        stock_dict[sid]["foreign_buy"] = foreign_diff
                        stock_dict[sid]["it_buy"] = it_diff
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        print(f"TWSE 法人買賣超獲取異常: {e}")

    return stock_dict

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

def process_and_score(stock_dict):
    # 第一階段：硬性篩選（成交金額 >= 5000 萬）
    filtered_stocks = {k: v for k, v in stock_dict.items() if v["turnover"] >= 50_000_000}
    print(f"通過流動性門檻（成交金額 >= 5000 萬）標的數：{len(filtered_stocks)} 檔")

    if not filtered_stocks:
        return []

    # 準備批次抓取 Yahoo Finance 的代號
    tickers = [f"{sid}.TW" for sid in filtered_stocks.keys()]
    print("正在抓取歷史 K 線數據計算均線與動能指標...")
    
    # 批次下載歷史資料
    df_history = yf.download(tickers, period="3mo", interval="1d", group_by="ticker", progress=False)

    scored_results = []
    for sid, info in filtered_stocks.items():
        ticker = f"{sid}.TW"
        try:
            if ticker in df_history.columns.levels[0]:
                df_k = df_history[ticker].dropna()
            else:
                continue

            if len(df_k) < 25:
                continue

            close_series = df_k["Close"]
            vol_series = df_k["Volume"]

            ma5 = close_series.rolling(5).mean().iloc[-1]
            ma10 = close_series.rolling(10).mean().iloc[-1]
            ma20_series = close_series.rolling(20).mean()
            ma20 = ma20_series.iloc[-1]
            ma20_slope = ma20 - ma20_series.iloc[-2]
            vol_ma5 = vol_series.rolling(5).mean().iloc[-1]

            today_close = info["close"]
            today_high = info["high"]
            today_low = info["low"]
            today_vol = info["volume"]

            # 安全閥：收盤價必須在 20MA 之上
            if today_close < ma20:
                continue

            score = 0
            reasons = []

            # 籌碼面評分 (滿分 35)
            if info["it_buy"] > 0:
                score += 20
                reasons.append(f"投信買超 ({int(info['it_buy'] / 1000):,}張)")
            if info["foreign_buy"] > 0:
                score += 10
                reasons.append(f"外資買超 ({int(info['foreign_buy'] / 1000):,}張)")
            if (info["it_buy"] + info["foreign_buy"]) >= (today_vol * 0.1):
                score += 5
                reasons.append("法人買超佔比 >= 10%")

            # 量價結構評分 (滿分 30)
            if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.5:
                score += 15
                reasons.append("帶量突破 (量比 >= 1.5)")

            k_range = today_high - today_low
            if k_range > 0 and (today_close - today_low) / k_range >= 0.8:
                score += 15
                reasons.append("實體紅 K 收高")

            # 技術與均線評分 (滿分 25)
            if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                score += 15
                reasons.append("均線多頭排列 (20MA向上)")

            high_20d = close_series.iloc[-21:-1].max()
            if today_close > high_20d:
                score += 10
                reasons.append("創 20 日收盤新高")

            # 動能與指標 (滿分 10)
            rsi = calculate_rsi(close_series).iloc[-1]
            _, _, hist = calculate_macd(close_series)
            if 50 <= rsi <= 75 and hist.iloc[-1] > 0:
                score += 10
                reasons.append("MACD 柱狀偏多 / RSI 處強勢區")

            # 風險扣分
            if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                score -= 20
                reasons.append("上影線偏長 (-20)")
            if rsi > 80:
                score -= 10
                reasons.append("RSI 過熱超買 (-10)")

            scored_results.append({
                "sid": sid,
                "name": info["name"],
                "close": today_close,
                "ma20": round(ma20, 2),
                "turnover_mil": round(info["turnover"] / 100_000_000, 2),
                "score": score,
                "reasons": reasons
            })
        except Exception:
            continue

    return scored_results

def send_discord(results):
    if not results:
        print("今日盤後無符合門檻之個股。")
        return

    # 依照總分排序，取前 5 檔
    top_picks = sorted(results, key=lambda x: x["score"], reverse=True)[:5]

    fields = []
    for item in top_picks:
        reasons_str = "、".join(item["reasons"]) if item["reasons"] else "無特別亮點"
        fields.append({
            "name": f"🎯 【{item['sid']} {item['name']}】 總評分: {item['score']} 分",
            "value": f"• **收盤價**: `{item['close']}` 元 (防守 20MA: `{item['ma20']}`)\n• **成交金額**: `{item['turnover_mil']}` 億元\n• **條件觸發**: {reasons_str}",
            "inline": False
        })

    payload = {
        "username": "台股量化選股機器人 (官方開源版)",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
        "embeds": [{
            "title": "📊 每日台股高勝率篩選報告",
            "description": f"掃描時間：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n篩選來源：**證交所官方盤後數據**（成交額 $\ge 5,000$ 萬 & 多頭排列）：",
            "color": 15158332 if top_picks[0]["score"] >= 80 else 3066993,
            "fields": fields,
            "footer": {
                "text": "TWSE Open Data • 僅供量化策略參考"
            }
        }]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code in [200, 204]:
        print("Discord 訊息推播成功！")
    else:
        print(f"推播失敗: {resp.status_code} - {resp.text}")

def main():
    print("開始執行全市場盤後掃描（證交所開源直連）...")
    stock_dict = get_twse_tpex_daily()
    if not stock_dict:
        print("無法取得當日證交所資料（可能尚未開盤、非交易日或證交所維護中）。")
        return

    print(f"成功載入台股共 {len(stock_dict)} 檔市場數據。")
    results = process_and_score(stock_dict)
    send_discord(results)

if __name__ == "__main__":
    main()
