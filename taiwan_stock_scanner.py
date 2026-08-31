import os
import re
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 回應狀態碼: {r.status_code}")
        if r.status_code != 204:
            print(f"回應內容: {r.text}")
    except Exception as e:
        print(f"發送失敗: {e}")

def get_session_info():
    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    
    event_name = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    trigger_type = "排程" if event_name == "schedule" else "手動"

    time_val = now_tw.hour * 100 + now_tw.minute
    if time_val < 900:
        session = "盤前掃描"
    elif 900 <= time_val <= 1330:
        session = "盤中分析"
    else:
        session = "盤後掃描"

    return f"全方位{session}報告 ({trigger_type})", now_tw.strftime("%Y-%m-%d")

def refine_industry(name, original_industry):
    orig_str = str(original_industry).strip() if original_industry else ""
    if orig_str and orig_str not in ["其他", "nan", "其他業"]:
        return orig_str
        
    name_str = str(name)
    if any(k in name_str for k in ["生技", "藥", "醫", "基因", "針劑", "臨床"]):
        return "生技醫療業"
    elif any(k in name_str for k in ["能源", "綠能", "太陽能", "風電", "電力", "環保", "水資源"]):
        return "綠能環保業"
    elif any(k in name_str for k in ["投控", "控股", "投資", "集團"]):
        return "投資控股業"
    elif any(k in name_str for k in ["建設", "開發", "營造", "置地", "工程"]):
        return "建材營造"
    elif any(k in name_str for k in ["軟體", "資訊", "網路", "雲端", "智能", "系統", "數據"]):
        return "資訊服務業"
    elif any(k in name_str for k in ["航運", "海運", "航空", "物流", "運輸"]):
        return "航運業"
    elif any(k in name_str for k in ["機電", "機械", "電機", "自動化"]):
        return "電機機械"
    return "一般產業"

def get_dynamic_all_stocks():
    stock_dict = {}
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, market in urls:
        success = False
        for parser in ["lxml", "html5lib"]:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.encoding = "big5-hkscs"
                dfs = pd.read_html(resp.text, flavor=parser)
                if not dfs:
                    continue
                df = dfs[0]
                df.columns = df.iloc[0]
                df = df.iloc[1:]
                
                for _, row in df.iterrows():
                    original_ind = "其他"
                    for val in row.values:
                        val_str = str(val).strip()
                        if val_str in ["水泥工業", "食品工業", "塑膠工業", "紡織纖維", "電機機械", "電器電纜", "化學工業", "生技醫療業", "玻璃陶瓷", "造紙工業", "鋼鐵工業", "橡膠工業", "汽車工業", "電子通路業", "資訊服務業", "其他電子業", "建材營造", "航運業", "觀光餐旅", "金融保險業", "貿易百貨", "油電燃氣業", "綜合企業", "其他業", "半導體業", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", "電子用品"]:
                            original_ind = val_str
                            break

                    for val in row.values:
                        val_str = str(val).strip()
                        if "\u3000" in val_str:
                            parts = val_str.split("\u3000")
                            if len(parts) >= 2:
                                sid = parts[0].strip()
                                name = parts[1].strip()
                                if len(sid) == 4 and sid.isdigit():
                                    ticker = f"{sid}.{market}"
                                    ind_str = refine_industry(name, original_ind)
                                    stock_dict[ticker] = (sid, name, ind_str)
                success = True
                break
            except Exception:
                continue
                
        if not success:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.encoding = "big5-hkscs"
                matches = re.findall(r'>(\d{4})&#12288;([^<]+)</td>', resp.text)
                for sid, name in matches:
                    ticker = f"{sid}.{market}"
                    stock_dict[ticker] = (sid, name.strip(), "一般產業")
            except Exception as e:
                print(f"獲取 {market} 清單失敗: {e}")
                
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

def get_market_and_futures():
    res = {}
    spot_close = 0.0
    try:
        twii = yf.Ticker("^TWII")
        df_t = twii.history(period="1mo", interval="1d")
        if not df_t.empty and len(df_t) >= 20:
            spot_close = float(df_t['Close'].iloc[-1])
            p_close = float(df_t['Close'].iloc[-2])
            pts = spot_close - p_close
            pct = (pts / p_close) * 100
            ma20 = float(df_t['Close'].rolling(20).mean().iloc[-1])
            trend = "🟢 多頭控盤" if spot_close > ma20 else "🔴 弱勢整理"
            emoji = "📈" if pts >= 0 else "📉"
            
            res['spot_close'] = spot_close
            res['pts'] = pts
            res['pct'] = pct
            res['trend'] = trend
            res['emoji'] = emoji
            res['ma20'] = ma20
    except Exception as e:
        print(f"大盤獲取失敗: {e}")

    # 台指期
    for sym in ["WTX&", "TX=F"]:
        try:
            tx = yf.Ticker(sym)
            df_f = tx.history(period="5d", interval="1d")
            if not df_f.empty and len(df_f) >= 2:
                f_price = float(df_f['Close'].iloc[-1])
                f_prev = float(df_f['Close'].iloc[-2])
                f_pts = f_price - f_prev
                f_pct = (f_pts / f_prev) * 100
                if f_price > 5000 and spot_close > 0:
                    diff = f_price - spot_close
                    dtype = "正價差" if diff >= 0 else "逆價差"
                    res['futures_str'] = f"`{f_price:,.2f}` ({f_pts:+,.2f} / {f_pct:+.2f}%) ｜ {dtype} `{abs(diff):.2f}`"
                    break
        except Exception:
            continue

    return res

def main():
    title_suffix, date_str = get_session_info()
    market_info = get_market_and_futures()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers:
        print("未獲取到股票清單，結束。")
        return

    chunk_size = 200
    scored_results = []
    monster_stocks = []

    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            df_batch = yf.download(chunk, period="3mo", interval="1d", group_by="ticker", progress=False)
            
            for ticker in chunk:
                if ticker not in df_batch.columns.levels[0]:
                    continue
                
                df = df_batch[ticker].dropna()
                if len(df) < 45:
                    continue

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

                # 妖股邏輯
                recent_high_20d = float(high_s.iloc[-21:-1].max())
                recent_low_20d = float(low_s.iloc[-21:-1].min())
                box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d if recent_low_20d > 0 else 99
                
                if est_money_mil >= 0.8 and box_range_pct <= 0.25 and vol_ma5 > 0 and (today_vol / vol_ma5) >= 2.5 and today_close >= recent_high_20d * 0.98:
                    m_entry_low = round(today_close * 0.99, 2)
                    m_entry_high = round(today_close * 1.003, 2)
                    m_sl = round(max(recent_low_20d * 0.99, m_entry_low * 0.94), 2)
                    box_h = recent_high_20d - recent_low_20d
                    m_tp = round(max(today_close + box_h * 3.0, today_close * 1.22), 2)

                    monster_stocks.append({
                        "sid": sid,
                        "name": name,
                        "industry": industry,
                        "close": f"{today_close:.2f}",
                        "vol_ratio": round(today_vol / vol_ma5, 1),
                        "entry": f"{m_entry_low} ~ {m_entry_high}",
                        "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100, 2)}%)",
                        "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100, 2)}%)"
                    })

                # 常規篩選
                if est_money_mil < 0.8 or today_close < ma20 or today_close < today_open * 0.99:
                    continue

                score = 0
                reasons = []

                if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
                    score += 25
                    reasons.append("均線多頭")

                if today_close > recent_high_20d:
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

                entry_low = round(today_close * 0.99, 2)
                entry_high = round(today_close * 1.003, 2)
                support_low = min(float(low_s.iloc[-5:].min()), ma10)
                sl_price = round(max(support_low * 0.99, entry_low * 0.925), 2)
                if sl_price > entry_low * 0.94:
                    sl_price = round(entry_low * 0.935, 2)

                if recent_high_20d > today_close * 1.04:
                    tp_price = round(recent_high_20d, 2)
                else:
                    swing_r = today_close - float(low_s.iloc[-15:].min())
                    tp_price = round(today_close + max(swing_r, (entry_high - sl_price) * 1.8), 2)

                scored_results.append({
                    "sid": sid,
                    "name": name,
                    "industry": industry,
                    "close": f"{today_close:.2f}",
                    "entry": f"{entry_low:.2f} ~ {entry_high:.2f}",
                    "tp": f"{tp_price} (+{round(((tp_price-today_close)/today_close)*100, 2)}%)",
                    "sl": f"{sl_price} ({round(((sl_price-today_close)/today_close)*100, 2)}%)",
                    "score": score,
                    "tags": " ‧ ".join(reasons) if reasons else "多頭結構"
                })
        except Exception:
            continue

    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    industry_count = {}
    top_picks = []
    
    for item in sorted_all:
        ind = item["industry"]
        if industry_count.get(ind, 0) < 2:
            industry_count[ind] = industry_count.get(ind, 0) + 1
            top_picks.append(item)
            
        if len(top_picks) >= 10:
            break

    # 構造 Embed Fields
    fields = []
    
    # 1. 大盤
    if 'spot_close' in market_info:
        fut_text = f"\n> **台指期貨**: {market_info.get('futures_str', '即時連線中')}" if 'futures_str' in market_info else ""
        fields.append({
            "name": f"📊 加權指數大盤解析 ({market_info['trend']})",
            "value": (
                f"> **收盤點位**: `{market_info['spot_close']:,.2f}`\n"
                f"> **單日漲跌**: `{market_info['pts']:+,.2f}` ({market_info['pct']:+.2f}%) {market_info['emoji']}\n"
                f"> **防守月線**: `{market_info['ma20']:,.2f}`"
                f"{fut_text}"
            ),
            "inline": False
        })
    
    # 2. 精選 Top 10（雙欄排版）
    fields.append({
        "name": "───────── 🎯 盤後精選 Top 10 ─────────",
        "value": "\u200b",
        "inline": False
    })
    
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

    # 3. 妖股獵人
    fields.append({
        "name": "───────── 🚨 妖股獵人 (飆股狂飆預警) ─────────",
        "value": "\u200b",
        "inline": False
    })
    
    if monster_stocks:
        top_monsters = sorted(monster_stocks, key=lambda x: x["vol_ratio"], reverse=True)[:3]
        for m in top_monsters:
            fields.append({
                "name": f"🔥 {m['sid']} {m['name']}  現價 : {m['close']}",
                "value": (
                    f"> **產業**: `{m['industry']}` | 爆量 `{m['vol_ratio']}x`\n"
                    f"> **進場**: `{m['entry']}`\n"
                    f"> **止盈 (TP)**: `{m['tp']}`\n"
                    f"> **止損 (SL)**: `{m['sl']}`"
                ),
                "inline": True
            })
    else:
        fields.append({
            "name": "⚡ 狀態提示",
            "value": "> 今日全市場暫無符合標的",
            "inline": False
        })

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股{title_suffix} ({date_str})",
            "description": "已完成大盤結構判定、全市場動態掃描與飆股潛伏預警：",
            "color": 3447003,
            "fields": fields
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
