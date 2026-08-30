import os
import io
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_dynamic_all_stocks():
    """動態向台灣證交所官方 ISIN 系統抓取全部現存上市與上櫃普通股（免 Token、全自動）"""
    stock_dict = {}  # { '2330.TW': '台積電', '3324.TWO': '雙鴻' }
    
    # 模式 2 為上市，模式 4 為上櫃
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    
    for url, market in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "big5-hkscs"
            dfs = pd.read_html(io.StringIO(resp.text))
            if not dfs:
                continue
            df = dfs[0]
            # 設定標準欄位
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            
            for item in df["有價證券代號及名稱"].dropna():
                parts = str(item).split("\u3000")  # 依全形空白分割代號與名稱
                if len(parts) >= 2:
                    sid = parts[0].strip()
                    name = parts[1].strip()
                    # 只抓 4 位純數字的普通股（排除權證 6 碼、特種股、ETF 等）
                    if len(sid) == 4 and sid.isdigit():
                        ticker = f"{sid}.{market}"
                        stock_dict[ticker] = (sid, name)
        except Exception as e:
            print(f"動態獲取 {market} 股票名冊異常: {e}")
            
    return stock_dict

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
    print("【步驟 1】即時動態向證交所抓取台股全市場名單...")
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    print(f"成功取得台股上市櫃全市場共 {len(all_tickers)} 檔股票。")

    if not all_tickers:
        print("未獲取到股票清單，結束執行。")
        return

    print("【步驟 2】批次下載全市場歷史量價進行第一階段快篩與指標計算...")
    # 分批次下載（每次 200 檔）防止請求封包過大
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
                sid, name = stock_dict[ticker]

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

                # 估算成交金額（億元）
                est_money_mil = (today_close * today_vol) / 100_000_000

                # 【第一階段動態過濾】：成交額 >= 0.8 億、站上月線、非長黑
                if est_money_mil < 0.8 or today_close < ma20 or today_close < today_open * 0.99:
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

                # 4. 實體紅 K 品質 (+15)
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

                # 波段合理價位計算
                entry_low = round(today_close * 0.99, 1)
                entry_high = round(today_close * 1.003, 1)

                support_low = min(float(low_s.iloc[-5:].min()), ma10)
                sl_price = round(max(support_low * 0.99, entry_low * 0.925), 1)
                if sl_price > entry_low * 0.94:
                    sl_price = round(entry_low * 0.935, 1)

                past_60d_high = float(high_s.iloc[-60:-1].max()) if len(high_s) >= 60 else float(high_s.iloc[:-1].max())
                if past_60d_high > today_close * 1.04:
                    tp_price = round(past_60d_high, 1)
                else:
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

        except Exception as e:
            print(f"處理批次 {i} 出現問題: {e}")
            continue

    print(f"【步驟 3】全市場掃描完成，符合條件標的共 {len(scored_results)} 檔。")
    top_picks = sorted(scored_results, key=lambda x: x["score"], reverse=True)[:10]

    # 建立雙欄排版
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
            "description": f"已完成全台股（上市＋上櫃 1,800+ 檔）動態掃描，精選綜合評分最高 10 檔：",
            "color": 3447003,
            "fields": fields if fields else [{"name": "提示", "value": "今日無符合條件個股"}]
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
