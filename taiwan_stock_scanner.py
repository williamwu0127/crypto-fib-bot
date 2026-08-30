import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

def get_dynamic_all_stocks():
    """動態向台灣證交所官方 ISIN 系統抓取全部現存上市與上櫃普通股及所屬產業"""
    stock_dict = {}
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, market in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = "big5-hkscs"
            dfs = pd.read_html(resp.text)
            if not dfs:
                continue
            df = dfs[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            
            for _, row in df.iterrows():
                item = row.get("有價證券代號及名稱", None)
                industry = row.get("產業別", "其他")
                if pd.isna(item):
                    continue
                parts = str(item).split("\u3000")
                if len(parts) >= 2:
                    sid = parts[0].strip()
                    name = parts[1].strip()
                    if len(sid) == 4 and sid.isdigit():
                        ticker = f"{sid}.{market}"
                        # 簡化產業名稱
                        ind_str = str(industry).strip() if not pd.isna(industry) else "其他"
                        stock_dict[ticker] = (sid, name, ind_str)
        except Exception as e:
            print(f"動態獲取 {market} 股票名冊異常: {e}")
            
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

def main():
    print("【步驟 1】即時動態向證交所抓取台股全市場名單與產業別...")
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    print(f"成功取得台股上市櫃全市場共 {len(all_tickers)} 檔股票。")

    if not all_tickers:
        print("未獲取到股票清單，結束執行。")
        return

    print("【步驟 2】批次下載全市場歷史量價進行第一階段快篩與指標計算...")
    chunk_size = 200
    scored_results = []
    latest_trade_date = datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            df_batch = yf.download(chunk, period="3mo", interval="1d", group_by="ticker", progress=False)
            
            for ticker in chunk:
                if ticker not in df_batch.columns.levels[0]:
                    continue
                
                df = df_batch[ticker].dropna()
                if len(df) < 25:
                    continue

                latest_trade_date = df.index[-1].strftime("%Y-%m-%d")
                sid, name, industry = stock_dict[ticker]

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

                est_money_mil = (today_close * today_vol) / 100_000_000

                # 初篩門檻
                if est_money_mil < 0.8 or today_close < ma20 or today_close < today_open * 0.99:
                    continue

                score = 0
                reasons = []

                if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                    score += 25
                    reasons.append("均線多頭")

                high_20d = float(high_s.iloc[-21:-1].max())
                if today_close > high_20d:
                    score += 20
                    reasons.append("突破20日高")

                if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.2:
                    score += 20
                    reasons.append(f"爆量 {round(today_vol/vol_ma5, 1)}x")

                k_range = today_high - today_low
                if k_range > 0 and (today_close - today_low) / k_range >= 0.7:
                    score += 15
                    reasons.append("紅K實體強")

                rsi = float(calculate_rsi(close_s).iloc[-1])
                _, _, hist = calculate_macd(close_s)
                if 50 <= rsi <= 75 and hist.iloc[-1] > 0:
                    score += 20
                    reasons.append("MACD偏多")

                if k_range > 0 and (today_high - today_close) / k_range > 0.4:
                    score -= 15

                # 價位計算
                entry_low = round(today_close * 0.99, 2)
                entry_high = round(today_close * 1.003, 2)

                support_low = min(float(low_s.iloc[-5:].min()), ma10)
                sl_price = round(max(support_low * 0.99, entry_low * 0.925), 2)
                if sl_price > entry_low * 0.94:
                    sl_price = round(entry_low * 0.935, 2)

                past_60d_high = float(high_s.iloc[-60:-1].max()) if len(high_s) >= 60 else float(high_s.iloc[:-1].max())
                if past_60d_high > today_close * 1.04:
                    tp_price = round(past_60d_high, 2)
                else:
                    swing_range = today_close - float(low_s.iloc[-15:].min())
                    tp_price = round(today_close + max(swing_range, (entry_high - sl_price) * 1.8), 2)

                scored_results.append({
                    "sid": sid,
                    "name": name,
                    "industry": industry,
                    "close": f"{today_close:.2f}",
                    "entry": f"{entry_low:.2f} ~ {entry_high:.2f}",
                    "tp": f"{tp_price:.2f}",
                    "sl": f"{sl_price:.2f}",
                    "score": score,
                    "tags": " ‧ ".join(reasons) if reasons else "多頭結構"
                })

        except Exception as e:
            print(f"處理批次出錯: {e}")
            continue

    # 【步驟 4】產業權重去重篩選：同產業最多取前 2 高分標的
    print("【步驟 4】執行產業分散與分級過濾...")
    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    
    industry_count = {}
    top_picks = []
    
    for item in sorted_all:
        ind = item["industry"]
        if ind not in industry_count:
            industry_count[ind] = 0
            
        # 每個產業最多取 2 檔
        if industry_count[ind] < 2:
            industry_count[ind] += 1
            top_picks.append(item)
            
        if len(top_picks) >= 10:
            break

    fields = []
    for i, item in enumerate(top_picks):
        fields.append({
            "name": f"📌 {item['sid']} {item['name']}  現價 : {item['close']}",
            "value": (
                f"> **產業**: `{item['industry']}`\n"
                f"> **進場**: `{item['entry']}`\n"
                f"> **止盈 (TP)**: `{item['tp']}`\n"
                f"> **止損 (SL)**: `{item['sl']}`\n"
                f"> **特徵**: `{item['tags']}`"
            ),
            "inline": True
        })
        if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    hour_utc = datetime.utcnow().hour
    session_title = "盤前精選" if hour_utc < 5 else "盤後精選"

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股{session_title} Top 10 ({latest_trade_date})",
            "description": f"已完成全台股動態掃描與產業分散（同產業上限 2 檔），精選 Top 10：",
            "color": 3447003,
            "fields": fields if fields else [{"name": "提示", "value": "今日無符合條件個股"}]
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
