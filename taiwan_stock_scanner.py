import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timezone, timedelta

# 關閉 yfinance 煩人的警告訊息
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# 🚨 安全性升級：請將你的新 Webhook 設定在系統環境變數 "DISCORD_WEBHOOK_URL" 中
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

TARGET_THEMES = {
    "矽晶圓": ["6488", "5483", "3532", "6182", "3016"],
    "AI伺服器": ["2382", "3231", "6669", "2356", "2376", "2317", "2301", "3017", "2421"],
    "重電": ["1519", "1513", "1504", "1503", "1609", "1605"],
    "矽光子": ["3450", "3081", "4979", "6442", "4908", "3163", "6530", "2455"],
    "散熱PCB": ["3037", "8046", "3189", "2368", "2383", "6274", "3017", "3324", "2421", "3653", "8996"],
    "軍工": ["2634", "8222", "2645", "5284", "4572", "3004"],
    "機器人": ["2359", "4566", "2049", "8374", "4583", "1590", "2464", "4562"],
    "特殊化學": ["4749", "4772", "4755", "1773", "4722", "5234", "1727"],
    "ABF載板": ["3037", "8046", "3189"],
    "功率元件": ["3707", "6438", "3675", "5425", "8255", "2481"],
    "被動元件": ["2327", "2492", "3026", "2478", "2456", "6173"],
    "玻璃相關": ["1802", "1809", "1810", "1817"],
    "CoWoS": ["3131", "3583", "6187", "2467", "6640", "2330", "3711", "2449", "3374"],
    "權值股": ["2330", "2454", "2317", "2308", "2881", "2882", "2886", "2891", "2412", "1301", "1303", "2002"],
    "塑膠": ["1301", "1303", "1326", "1304", "1308", "1305", "1314", "1309"],
    "AOI檢測": ["3455", "5450", "3030", "6223", "2467", "6640"]
}

ALLOWED_MONSTER_INDUSTRIES = [
    "半導體業", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", 
    "電子通路業", "資訊服務業", "其他電子業", "生技醫療業", "電機機械"
]

def send_msg(payload):
    if not WEBHOOK_URL:
        print("錯誤：找不到 Webhook URL 環境變數！")
        return
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

def get_session_info():
    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    
    event_name = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    trigger_type = "排程" if event_name == "schedule" else "手動"

    time_val = now_tw.hour * 100 + now_tw.minute
    if time_val < 900: 
        session_name = "盤前"
    elif 900 <= time_val <= 1330: 
        session_name = "盤中"
    elif 1330 < time_val < 1745: 
        session_name = "盤後"
    else: 
        session_name = "籌碼"

    return session_name, trigger_type, now_tw.strftime("%Y-%m-%d")

def identify_theme(sid, original_ind):
    for theme, sids in TARGET_THEMES.items():
        if sid in sids:
            return theme
    return original_ind if original_ind and original_ind != "其他" else "一般產業"

def get_dynamic_all_stocks():
    stock_dict = {}
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, market in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            resp.encoding = "big5-hkscs"
            dfs = pd.read_html(resp.text)
            if not dfs: continue
            df = dfs[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            
            for _, row in df.iterrows():
                val_0 = str(row.iloc[0]).strip()
                if "\u3000" in val_0:
                    parts = val_0.split("\u3000")
                    sid = parts[0].strip()
                    name = parts[1].strip()
                    if len(sid) == 4 and sid.isdigit():
                        original_ind = "其他"
                        for val in row.values:
                            val_str = str(val).strip()
                            if val_str in ["水泥工業", "食品工業", "塑膠工業", "紡織纖維", "電機機械", "電器電纜", "化學工業", "生技醫療業", "玻璃陶瓷", "造紙工業", "鋼鐵工業", "橡膠工業", "汽車工業", "電子通路業", "資訊服務業", "其他電子業", "建材營造", "航運業", "觀光餐旅", "金融保險業", "貿易百貨", "油電燃氣業", "綜合企業", "其他業", "半導體業", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", "電子用品"]:
                                original_ind = val_str
                                break
                        theme_str = identify_theme(sid, original_ind)
                        stock_dict[f"{sid}.{market}"] = (sid, name, theme_str, original_ind)
        except Exception:
            continue
            
    if not stock_dict:
        fallback_list = [
            ("2330", "台積電", "CoWoS", "半導體業", "TW"), ("2454", "聯發科", "權值股", "半導體業", "TW"),
            ("2317", "鴻海", "AI伺服器", "其他電子業", "TW"), ("2308", "台達電", "重電", "電機機械", "TW")
        ]
        for sid, name, theme, ind, mkt in fallback_list:
            stock_dict[f"{sid}.{mkt}"] = (sid, name, theme, ind)
    return stock_dict

def get_market_info():
    res = {}
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    try:
        session.get("https://mis.twse.com.tw/stock/index.jsp", timeout=3)
        timestamp = int(datetime.now().timestamp() * 1000)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&_={timestamp}"
        r = session.get(url, timeout=5)
        if r.status_code == 200:
            msg_arr = r.json().get('msgArray', [])
            if msg_arr:
                t00 = msg_arr[0]
                z_str = t00.get('z', '')
                y_str = t00.get('y', '')
                spot_close = float(z_str.replace(',', '')) if z_str != '-' else float(y_str.replace(',', ''))
                prev_close = float(y_str.replace(',', ''))
                res['spot_close'] = spot_close
                res['pts'] = spot_close - prev_close
                res['pct'] = (res['pts'] / prev_close) * 100 if prev_close > 0 else 0.0
    except Exception:
        pass

    if 'spot_close' not in res:
        try:
            r_anue = requests.get("https://ws.api.cnyes.com/ws/api/v1/quote/quotes/TWS:TSE01:INDEX", timeout=5)
            if r_anue.status_code == 200:
                data = r_anue.json().get('data', [])[0]
                res['spot_close'] = float(data.get('200009', 0))
                res['pts'] = float(data.get('200011', 0))
                res['pct'] = float(data.get('200012', 0))
        except Exception:
            pass

    ma20 = None
    try:
        twii = yf.Ticker("^TWII")
        df_t = twii.history(period="1mo", interval="1d", auto_adjust=False)
        if not df_t.empty and len(df_t) >= 15:
            ma20 = float(df_t['Close'].rolling(20).mean().iloc[-1])
    except Exception:
        pass

    if 'spot_close' not in res:
        res['spot_close'], res['pts'], res['pct'] = 22500.0, 0.0, 0.0

    if ma20 is None or pd.isna(ma20):
        ma20 = res['spot_close'] * 0.98

    res['ma20'] = ma20
    res['trend'] = "多頭控盤" if res['spot_close'] >= ma20 else "弱勢整理"
    res['emoji'] = "🟢" if res['pts'] >= 0 else "🔴"

    return res

def calculate_atr(df, period=14):
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift(1)).abs()
    tr3 = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = tr.rolling(period).mean().iloc[-1]
    return float(atr_val) if not pd.isna(atr_val) else float(df['High'].iloc[-1] - df['Low'].iloc[-1])

def analyze_pattern_stages(df, c_price, atr_14):
    ma20 = float(df['Close'].rolling(20).mean().iloc[-1])
    if c_price < ma20: return None

    low_40d = df['Low'].iloc[-40:]
    head_idx = low_40d.idxmin()
    head_pos = low_40d.index.get_loc(head_idx)
    head_price = float(low_40d.min())
    
    right_foot = float(low_40d.iloc[head_pos+1:].min()) if head_pos < len(low_40d)-1 else head_price
    neck_high = float(df['High'].loc[low_40d.index[head_pos]:].max())
    neck_low = round(neck_high * 0.985, 2)
    recent_low_5d = float(df['Low'].iloc[-5:].min())

    if c_price >= neck_high:
        desc, status, score = "多頭破頸線 (階梯墊高)", "突破頸線 (轉強發動)", 90
    elif c_price >= neck_low:
        desc, status, score = "強勢箱型蓄勢 (回測支撐)", "突破後回測 (支撐確認)", 82
    else:
        return None

    sl_price = round(max(recent_low_5d * 0.99, c_price - atr_14 * 1.5, c_price * 0.94), 2)
    sl_pct = round(((sl_price - c_price) / c_price) * 100, 2)

    box_height = neck_high - head_price
    tp_price = round(c_price + max(box_height, atr_14 * 2.5), 2)
    tp_pct = round(((tp_price - c_price) / c_price) * 100, 2)

    return {
        "status_text": f"{status} ｜ `{desc}`",
        "neck_zone": f"{neck_low:.2f} ~ {neck_high:.2f}",
        "left_strat": f"`{right_foot:.2f}` 已過",
        "right_strat": f"突破 `{neck_high:.2f}` 站穩加碼 ｜ 回測 `{neck_low:.2f}` 承接",
        "tp": f"{tp_price} (+{tp_pct}%)",
        "sl": f"{sl_price} ({sl_pct}%)",
        "entry": f"{round(c_price * 0.992, 2):.2f} ~ {round(c_price * 1.006, 2):.2f}",
        "score": score
    }

def main():
    session_name, trigger_type, date_str = get_session_info()
    market_info = get_market_info()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers: return

    scored_results = []
    monster_candidates = []

    chunk_size = 150
    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            # 批次下載日線與15分線
            df_batch_1d = yf.download(chunk, period="3mo", interval="1d", auto_adjust=True, progress=False)
            df_batch_15m = yf.download(chunk, period="5d", interval="15m", progress=False)
            
            for ticker in chunk:
                df_1d = pd.DataFrame()
                df_15m = pd.DataFrame()
                
                # 處理 1d 資料萃取
                if isinstance(df_batch_1d.columns, pd.MultiIndex):
                    if ticker in df_batch_1d.columns.get_level_values(1):
                        df_1d['Close'] = df_batch_1d['Close'][ticker]
                        df_1d['High'] = df_batch_1d['High'][ticker]
                        df_1d['Low'] = df_batch_1d['Low'][ticker]
                        df_1d['Volume'] = df_batch_1d['Volume'][ticker]
                else:
                    if len(chunk) == 1: df_1d = df_batch_1d.copy()
                
                # 處理 15m 資料萃取
                if isinstance(df_batch_15m.columns, pd.MultiIndex):
                    if ticker in df_batch_15m.columns.get_level_values(1):
                        df_15m['Volume'] = df_batch_15m['Volume'][ticker]
                else:
                    if len(chunk) == 1: df_15m = df_batch_15m.copy()
                
                df_1d = df_1d.dropna()
                if df_1d.empty or len(df_1d) < 25: continue

                sid, name, theme_str, original_ind = stock_dict[ticker]
                today_close = float(df_1d['Close'].iloc[-1])
                today_vol = float(df_1d['Volume'].iloc[-1])
                
                est_money_mil = (today_close * today_vol) / 100_000_000
                if est_money_mil < 1.0 or today_close < 10.0:
                    continue
                
                atr_14 = calculate_atr(df_1d, 14)

                # --- 1. 妖股分析：開盤半小時放量邏輯 ---
                if original_ind in ALLOWED_MONSTER_INDUSTRIES and not df_15m.empty:
                    df_1d_dates = df_1d.index.date
                    df_15m_dates = df_15m.index.date
                    today_date = df_1d_dates[-1]
                    
                    df_1d_past = df_1d[df_1d_dates < today_date]
                    df_15m_today = df_15m[df_15m_dates == today_date]
                    
                    if not df_1d_past.empty and not df_15m_today.empty:
                        # 過去 5 天均量
                        past_5d_vol = df_1d_past['Volume'].iloc[-5:].mean()
                        # 今天前兩根 15分K (09:00~09:30) 的量
                        today_30m_vol = df_15m_today['Volume'].iloc[:2].sum()
                        
                        threshold = past_5d_vol * 0.3
                        if past_5d_vol > 0 and today_30m_vol > threshold:
                            vol_ratio = today_30m_vol / past_5d_vol
                            m_sl = round(max(float(df_1d['Low'].iloc[-5:].min()) * 0.99, today_close - atr_14 * 1.5), 2)
                            m_tp = round(today_close + atr_14 * 3.5, 2)
                            monster_candidates.append({
                                "sid": sid, "name": name, "industry": original_ind,
                                "close": f"{today_close:.2f}", 
                                "today_30m_vol": int(today_30m_vol),
                                "past_5d_vol": int(past_5d_vol),
                                "vol_ratio": f"{vol_ratio*100:.1f}%",
                                "entry": f"{round(today_close*0.992,2)} ~ {round(today_close*1.006,2)}",
                                "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100,2)}%)",
                                "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100,2)}%)",
                                "score": vol_ratio
                            })

                # --- 2. TOP 6 篩選：排除金融股 ---
                if original_ind != "金融保險業":
                    p_res = analyze_pattern_stages(df_1d, today_close, atr_14)
                    if p_res:
                        score = p_res["score"] + (15 if theme_str != original_ind else 0)
                        scored_results.append({
                            "sid": sid, "name": name, "industry": original_ind,
                            "close": f"{today_close:.2f}", "score": score, **p_res
                        })
                        
        except Exception as e:
            print(f"處理區塊發生錯誤: {e}")
            continue

    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    top_picks = sorted_all[:6]
    
    # 妖股上限改為 4 組
    top_monsters = sorted(monster_candidates, key=lambda x: x["score"], reverse=True)[:4]

    fields = []
    fields.append({
        "name": f" 📊 加權指數大盤解析 ({market_info['trend']})",
        "value": (
            f"> **收盤點位**: `{market_info['spot_close']:,.2f}`\n"
            f"> **單日漲跌**: `{market_info['pts']:+,.2f}` ({market_info['pct']:+.2f}%) {market_info['emoji']}\n"
            f"> **防守月線**: `{market_info['ma20']:,.2f}`"
        ),
        "inline": False
    })
    
    fields.append({"name": f"───────── 🎯 {session_name}精選 Top 6 (已排除金融) ─────────", "value": "\u200b", "inline": False})
    if top_picks:
        for i, item in enumerate(top_picks):
            fields.append({
                "name": f" 📌 {item['sid']} {item['name']} ｜ 現價 : {item['close']}",
                "value": (
                    f"> **產業**: `{item['industry']}`\n"
                    f"> **進場區間**: `{item['entry']}`\n"
                    f"> **止盈 (TP)**: `{item['tp']}`\n"
                    f"> **止損 (SL)**: `{item['sl']}`\n"
                    f"> **頸線區間**: `{item['neck_zone']}`\n"
                    f"> **左側策略**: {item['left_strat']}\n"
                    f"> **右側策略**: {item['right_strat']}\n"
                    f"> **結構狀態**: {item['status_text']}"
                ),
                "inline": True
            })
            if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
                fields.append({"name": "\u200b", "value": "\u200b", "inline": False})
    else:
        fields.append({"name": " 狀態提示", "value": "> 掃描區間內暫無符合條件標的", "inline": False})

    fields.append({"name": f"───────── 🚀 開盤半小時爆量妖股預警 (Top 4) ─────────", "value": "\u200b", "inline": False})
    if top_monsters:
        for m in top_monsters:
            fields.append({
                "name": f" 🔥 {m['sid']} {m['name']} ｜ 現價 : {m['close']}",
                "value": (
                    f"> **產業**: `{m['industry']}`\n"
                    f"> **半小時量**: `{m['today_30m_vol']}` / 均量: `{m['past_5d_vol']}`\n"
                    f"> **爆量比例**: `{m['vol_ratio']}`\n"
                    f"> **進場區間**: `{m['entry']}`\n"
                    f"> **止盈**: `{m['tp']}` ｜ **止損**: `{m['sl']}`"
                ),
                "inline": True
            })
    else:
        fields.append({"name": " 狀態提示", "value": "> 今日無符合開盤半小時高動能爆量之標的", "inline": False})

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股{session_name}分析報告 ({trigger_type})\n[{date_str}]",
            "description": "TOP6精選股(非金融) ｜ 半小時爆量分析",
            "color": 3447003,
            "fields": fields
        }]
    }
    
    send_msg(payload)

if __name__ == "__main__":
    main()
