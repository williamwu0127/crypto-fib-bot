import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timezone, timedelta

# 關閉 yfinance 煩人的警告訊息
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# 🚨 環境變數設定 (包含 Discord 與 Notion)
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# 這裡是你鎖定的「精選股」專屬題材池
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

# 這是「妖股」的全市場寬鬆掃描池
ALLOWED_MONSTER_INDUSTRIES = [
    "半導體業", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", 
    "電子通路業", "資訊服務業", "其他電子業", "生技醫療業", "電機機械"
]

def send_msg(payload):
    if not WEBHOOK_URL:
        print("警告：找不到 Discord Webhook URL！")
        return
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Discord 發送失敗: {e}")

# ==================== 全新 Notion OMS 訂單管理引擎 ====================
def manage_notion_orders(date_str, session_name, top_monsters, top_picks, stock_dict):
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("提示：未設定 Notion 變數，跳過寫入資料庫。")
        return

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    ticker_map = {info[0]: tkr for tkr, info in stock_dict.items()}

    # === 步驟 1：查詢目前「🟢 持倉中」的庫存 ===
    print("正在與 Notion 同步當前庫存...")
    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"filter": {"property": "交易狀態", "select": {"equals": "🟢 持倉中"}}}
    
    open_positions = {}
    try:
        res = requests.post(query_url, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            for page in res.json().get('results', []):
                page_id = page['id']
                props = page['properties']
                name_str = props.get('名稱', {}).get('title', [])
                if not name_str: continue
                sid = name_str[0]['text']['content'].split(" ")[0]
                
                tp = props.get('停利價', {}).get('number')
                sl = props.get('停損價', {}).get('number')
                open_positions[sid] = {"id": page_id, "tp": tp, "sl": sl}
    except Exception as e:
        print(f"查詢 Notion 庫存失敗: {e}")
        return

    # === 步驟 2：盤後全面更新庫存報價與判定平倉 ===
    if session_name == "盤後" and open_positions:
        print("正在執行盤後庫存盤點與更新...")
        tkrs_to_fetch = [ticker_map[sid] for sid in open_positions.keys() if sid in ticker_map]
        
        if tkrs_to_fetch:
            try:
                df_open = yf.download(tkrs_to_fetch, period="1d", progress=False)
                for sid, pos_info in open_positions.items():
                    tkr = ticker_map.get(sid)
                    if not tkr: continue
                    
                    try:
                        if len(tkrs_to_fetch) == 1:
                            c_price = float(df_open['Close'].iloc[-1])
                        else:
                            c_price = float(df_open['Close'][tkr].iloc[-1])
                            
                        if pd.isna(c_price): continue
                        
                        patch_url = f"https://api.notion.com/v1/pages/{pos_info['id']}"
                        patch_props = {"最新市價": {"number": c_price}}
                        
                        tp, sl = pos_info['tp'], pos_info['sl']
                        if (tp and c_price >= tp) or (sl and c_price <= sl):
                            patch_props["交易狀態"] = {"select": {"name": "⚫ 已平倉"}}
                            patch_props["出場價格"] = {"number": c_price}
                            patch_props["出場日期"] = {"date": {"start": date_str}}
                            print(f"[{sid}] 觸發出場條件，已自動平倉！")
                            
                        requests.patch(patch_url, headers=headers, json={"properties": patch_props})
                        time.sleep(0.4) 
                    except Exception as e:
                        print(f"更新 {sid} 失敗: {e}")
            except Exception as e:
                print(f"抓取庫存最新報價失敗: {e}")

    # === 步驟 3：寫入新進場訊號 (防重複建單) ===
    def create_new_order(item, reason):
        if item['sid'] in open_positions:
            print(f"[{item['sid']}] 庫存中已有持倉，略過重複建單。")
            return
            
        print(f"寫入新單：[{item['sid']}] {item['name']}")
        post_url = "https://api.notion.com/v1/pages"
        new_page_payload = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                "名稱": {"title": [{"text": {"content": f"{item['sid']} {item['name']}"}}]},
                "產業": {"select": {"name": item['industry']}},  # 自動寫入產業欄位
                "交易狀態": {"select": {"name": "🟢 持倉中"}},
                "進場日期": {"date": {"start": date_str}},
                "進場價格": {"number": float(item['close'])},
                "最新市價": {"number": float(item['close'])},
                "停利價": {"number": item['tp_num']},
                "停損價": {"number": item['sl_num']},
                "進場依據": {"rich_text": [{"text": {"content": reason}}]}
            }
        }
        try:
            requests.post(post_url, headers=headers, json=new_page_payload)
            time.sleep(0.4)
        except Exception as e:
            print(f"建立新單失敗: {e}")

    if session_name == "早盤動能" and top_monsters:
        for m in top_monsters:
            create_new_order(m, f"早盤爆量 {m['vol_ratio']}")
            
    elif session_name == "盤後" and top_picks:
        for p in top_picks:
            clean_reason = p['status_text'].replace('`', '')
            create_new_order(p, clean_reason)

# ====================================================================

def get_session_info():
    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    
    event_name = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    trigger_type = "排程" if event_name == "schedule" else "手動"

    time_val = now_tw.hour * 100 + now_tw.minute
    if time_val < 900: 
        session_name = "盤前"
    elif 900 <= time_val <= 1030: 
        session_name = "早盤動能"
    elif 1030 < time_val <= 1330: 
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

def analyze_smc_fibo(df, c_price, atr_14):
    if len(df) < 60: return None
    
    ma20 = float(df['Close'].rolling(20).mean().iloc[-1])
    ma60 = float(df['Close'].rolling(60).mean().iloc[-1])
    
    if ma20 < ma60 or c_price < ma60:
        return None
        
    vol_ma3 = float(df['Volume'].iloc[-3:].mean())
    vol_ma20 = float(df['Volume'].rolling(20).mean().iloc[-1])
    
    if vol_ma3 > vol_ma20 * 0.75:
        return None 
        
    recent_40d = df.iloc[-40:]
    swing_low_idx = recent_40d['Low'].idxmin()
    swing_low = float(recent_40d['Low'].min())
    
    post_low_data = df.loc[swing_low_idx:]
    if len(post_low_data) < 5: 
        return None 
        
    swing_high = float(post_low_data['High'].max())
    
    if (swing_high - swing_low) / swing_low < 0.08:
        return None
        
    move_range = swing_high - swing_low
    fibo_382 = swing_high - move_range * 0.382
    fibo_500 = swing_high - move_range * 0.500
    fibo_618 = swing_high - move_range * 0.618
    fibo_786 = swing_high - move_range * 0.786
    
    bullish_fvgs = []
    for i in range(2, len(post_low_data)):
        k1_high = float(post_low_data['High'].iloc[i-2])
        k3_low = float(post_low_data['Low'].iloc[i])
        if k3_low > k1_high:
            gap_size = k3_low - k1_high
            if gap_size / c_price > 0.005: 
                bullish_fvgs.append((round(k1_high, 2), round(k3_low, 2)))
    
    score = 0
    status = ""
    desc = ""
    
    if c_price > fibo_382:
        return None 
        
    elif fibo_786 <= c_price <= fibo_382:
        status = "黃金折價區 (Discount)"
        if fibo_618 <= c_price <= fibo_500:
            desc = "落入 0.5~0.618 打擊區"
            score = 90
        elif c_price < fibo_618:
            desc = "落入 0.618~0.786 防守區"
            score = 85
        else:
            desc = "落入 0.382~0.5 淺回撤區"
            score = 80
    else:
        return None 
        
    fvg_match = "無明顯未補缺口"
    for fvg in bullish_fvgs:
        if fvg[0] * 0.985 <= c_price <= fvg[1] * 1.015:
            score += 15 
            fvg_match = f"{fvg[0]} ~ {fvg[1]}"
            desc += " ＋ 踩入 FVG"
            break
            
    sl_price = round(max(swing_low * 0.98, c_price - atr_14 * 1.5), 2)
    sl_pct = round(((sl_price - c_price) / c_price) * 100, 2)
    
    tp_price = round(swing_high * 1.02, 2)
    tp_pct = round(((tp_price - c_price) / c_price) * 100, 2)
    
    return {
        "status_text": f"{status} ｜ `{desc}`",
        "fibo_level": f"{fibo_618:.2f} ~ {fibo_500:.2f}",
        "fvg_zone": fvg_match,
        "tp": f"{tp_price} (+{tp_pct}%)",
        "sl": f"{sl_price} ({sl_pct}%)",
        "tp_num": tp_price,
        "sl_num": sl_price,
        "entry": f"{round(c_price * 0.99, 2):.2f} ~ {round(c_price * 1.01, 2):.2f}",
        "score": min(score, 99)
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
            df_batch_1d = yf.download(chunk, period="6mo", interval="1d", auto_adjust=True, progress=False)
            df_batch_15m = yf.download(chunk, period="5d", interval="15m", progress=False)
            
            for ticker in chunk:
                df_1d = pd.DataFrame()
                df_15m = pd.DataFrame()
                
                if isinstance(df_batch_1d.columns, pd.MultiIndex):
                    if ticker in df_batch_1d.columns.get_level_values(1):
                        df_1d['Close'] = df_batch_1d['Close'][ticker]
                        df_1d['High'] = df_batch_1d['High'][ticker]
                        df_1d['Low'] = df_batch_1d['Low'][ticker]
                        df_1d['Volume'] = df_batch_1d['Volume'][ticker]
                else:
                    if len(chunk) == 1: df_1d = df_batch_1d.copy()
                
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
                prev_close = float(df_1d['Close'].iloc[-2]) if len(df_1d) >= 2 else today_close
                today_pct = ((today_close - prev_close) / prev_close) * 100
                
                est_money_mil = (today_close * today_vol) / 100_000_000
                if est_money_mil < 1.0 or today_close < 10.0:
                    continue
                
                atr_14 = calculate_atr(df_1d, 14)

                # --- 1. 妖股分析 (維持全市場掃描) ---
                if original_ind in ALLOWED_MONSTER_INDUSTRIES and not df_15m.empty:
                    df_1d_dates = df_1d.index.date
                    df_15m_dates = df_15m.index.date
                    today_date = df_1d_dates[-1]
                    
                    df_1d_past = df_1d[df_1d_dates < today_date]
                    df_15m_today = df_15m[df_15m_dates == today_date]
                    
                    if not df_1d_past.empty and not df_15m_today.empty:
                        past_5d_vol = df_1d_past['Volume'].iloc[-5:].mean()
                        today_30m_vol = df_15m_today['Volume'].iloc[:2].sum()
                        
                        threshold = past_5d_vol * 0.3
                        if past_5d_vol > 0 and today_30m_vol > threshold:
                            vol_ratio = today_30m_vol / past_5d_vol
                            m_sl = round(max(float(df_1d['Low'].iloc[-5:].min()) * 0.99, today_close - atr_14 * 1.5), 2)
                            m_tp = round(today_close + atr_14 * 3.5, 2)
                            monster_candidates.append({
                                "sid": sid, "name": name, "industry": original_ind,
                                "close": f"{today_close:.2f}", 
                                "today_pct": today_pct, 
                                "today_30m_vol": int(today_30m_vol),
                                "past_5d_vol": int(past_5d_vol),
                                "vol_ratio": f"{vol_ratio*100:.1f}%",
                                "entry": f"{round(today_close*0.992,2)} ~ {round(today_close*1.006,2)}",
                                "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100,2)}%)",
                                "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100,2)}%)",
                                "tp_num": m_tp, "sl_num": m_sl,
                                "score": vol_ratio
                            })

                # --- 2. TOP 8 精選股 (嚴格限制在 TARGET_THEMES 題材池內) ---
                if theme_str in TARGET_THEMES:
                    p_res = analyze_smc_fibo(df_1d, today_close, atr_14)
                    if p_res:
                        # 只要進得來，就代表是熱門題材，固定給予 +15 分
                        score = p_res["score"] + 15 
                        scored_results.append({
                            "sid": sid, "name": name, "industry": original_ind,
                            "close": f"{today_close:.2f}", "score": score, **p_res
                        })
                        
        except Exception as e:
            continue

    # 排序與切片
    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    top_picks = sorted_all[:8]
    top_monsters = sorted(monster_candidates, key=lambda x: x["score"], reverse=True)[:6]

    # ========== 觸發 Notion 交易引擎 ==========
    if session_name in ["早盤動能", "盤後"]:
        manage_notion_orders(date_str, session_name, top_monsters, top_picks, stock_dict)
    # ==========================================

    # --- 發送到 Discord 的排版邏輯 ---
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
    
    if session_name == "早盤動能":
        description_text = "📣 早盤高動能妖股專屬通報"
        fields.append({"name": f"───────── 📣 09:50 爆量妖股通報 (Top 6) ─────────", "value": "\u200b", "inline": False})
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
            fields.append({"name": " 狀態提示", "value": "> 今日早盤無符合開盤半小時高動能爆量之標的", "inline": False})

    else:
        description_text = "TOP8精選股(嚴選主流題材) ｜ 早盤妖股驗證追蹤"
        fields.append({"name": f"───────── 🎯 {session_name}精選 Top 8  ─────────", "value": "\u200b", "inline": False})
        if top_picks:
            for i, item in enumerate(top_picks):
                fields.append({
                    "name": f" 📌 {item['sid']} {item['name']} ｜ 現價 : {item['close']}",
                    "value": (
                        f"> **產業**: `{item['industry']}`\n"
                        f"> **進場區間**: `{item['entry']}`\n"
                        f"> **止盈 (TP)**: `{item['tp']}`\n"
                        f"> **止損 (SL)**: `{item['sl']}`\n"
                        f"> **Fibo 區間**: `{item['fibo_level']}`\n"
                        f"> **FVG 缺口**: `{item['fvg_zone']}`\n"
                        f"> **結構狀態**: {item['status_text']}"
                    ),
                    "inline": True
                })
                if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
                    fields.append({"name": "\u200b", "value": "\u200b", "inline": False})
        else:
            fields.append({"name": " 狀態提示", "value": "> 掃描區間內暫無符合條件標的", "inline": False})

        if session_name == "盤前":
            fields.append({"name": f"───────── 🚀 開盤半小時爆量妖股預警 ─────────", "value": "\u200b", "inline": False})
            fields.append({"name": " 狀態提示", "value": "> 股市尚未開盤，目前無今日動能數據", "inline": False})
        else:
            fields.append({"name": f"───────── 🚀 早盤妖股盤中表現驗證 (Top 6) ─────────", "value": "\u200b", "inline": False})
            if top_monsters:
                for m in top_monsters:
                    if m['today_pct'] >= 9.5:
                        perf_str = f"🎯 **漲停鎖死** (`+{m['today_pct']:.2f}%`)"
                    elif m['today_pct'] > 0:
                        perf_str = f"📈 上漲 (`+{m['today_pct']:.2f}%`)"
                    elif m['today_pct'] < 0:
                        perf_str = f"📉 下跌 (`{m['today_pct']:.2f}%`)"
                    else:
                        perf_str = "平盤 (`0.00%`)"
                        
                    fields.append({
                        "name": f" 🔥 {m['sid']} {m['name']} ｜ 現價 : {m['close']}",
                        "value": (
                            f"> **產業**: `{m['industry']}`\n"
                            f"> **爆量比例**: `{m['vol_ratio']}`\n"
                            f"> **目前表現**: {perf_str}\n"
                            f"> **進場區間**: `{m['entry']}`\n"
                            f"> **止盈**: `{m['tp']}` ｜ **止損**: `{m['sl']}`"
                        ),
                        "inline": True
                    })
            else:
                fields.append({"name": " 狀態提示", "value": "> 今日無符合高動能爆量之標的", "inline": False})

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股{session_name}分析報告 ({trigger_type})\n[{date_str}]",
            "description": description_text,
            "color": 3447003,
            "fields": fields
        }]
    }
    
    send_msg(payload)

if __name__ == "__main__":
    main()
