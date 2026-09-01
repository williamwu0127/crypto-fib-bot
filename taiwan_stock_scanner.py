import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timezone, timedelta

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)
FRICTION_COST_PCT = 0.40

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
    if time_val < 900: session_name = "盤前"
    elif 900 <= time_val <= 1330: session_name = "盤中"
    elif 1330 < time_val < 1745: session_name = "盤後"
    else: session_name = "籌碼"

    return session_name, f"全方位{session_name}分析報告 ({trigger_type})", now_tw.strftime("%Y-%m-%d"), (session_name == "籌碼")

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
        except:
            continue
            
    if not stock_dict:
        fallback_list = [
            ("2330", "台積電", "CoWoS", "半導體業", "TW"), ("2454", "聯發科", "權值股", "半導體業", "TW"),
            ("2317", "鴻海", "AI伺服器", "其他電子業", "TW"), ("2308", "台達電", "重電", "電機機械", "TW")
        ]
        for sid, name, theme, ind, mkt in fallback_list:
            stock_dict[f"{sid}.{mkt}"] = (sid, name, theme, ind)
    return stock_dict

def get_market_and_futures():
    res = {}
    
    # 1. 透過證交所官方 MIS 系統抓取大盤即時/盤後精準報價 (tse_t00.tw)
    try:
        url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            msg_arr = r.json().get('msgArray', [])
            if msg_arr:
                t00 = msg_arr[0]
                z_str = t00.get('z', '')
                y_str = t00.get('y', '')
                
                spot_close = float(z_str.replace(',', '')) if z_str != '-' else float(y_str.replace(',', ''))
                prev_close = float(y_str.replace(',', ''))
                
                pts = spot_close - prev_close
                pct = (pts / prev_close) * 100 if prev_close > 0 else 0.0
                
                res['spot_close'] = spot_close
                res['pts'] = pts
                res['pct'] = pct
    except Exception:
        pass

    # 2. 用 yfinance 輔助取得 20 日均線 (若失敗則防呆)
    ma20 = None
    try:
        twii = yf.Ticker("^TWII")
        df_t = twii.history(period="1mo", interval="1d", auto_adjust=False)
        if not df_t.empty and len(df_t) >= 15:
            ma20 = float(df_t['Close'].rolling(20).mean().iloc[-1])
    except Exception:
        pass

    # 防呆機制
    if 'spot_close' not in res:
        res['spot_close'] = 22500.0
        res['pts'] = 0.0
        res['pct'] = 0.0
        
    if ma20 is None or pd.isna(ma20):
        ma20 = res['spot_close'] * 0.98

    res['ma20'] = ma20
    res['trend'] = "🟢 多頭控盤" if res['spot_close'] >= ma20 else "🔴 弱勢整理"
    res['emoji'] = "📈" if res['pts'] >= 0 else "📉"

    # 3. 台指期貨抓取
    tx_quote = None
    stock_futures = {}
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        r = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json={"MarketType":"0","SymbolType":"F"}, headers=headers, timeout=5)
        if r.status_code == 200:
            for item in r.json().get('RtData', {}).get('QuoteList', []):
                sym = item.get('SymbolID', '')
                last_p = float(str(item.get('CLastPrice', '0')).replace(',', ''))
                diff = float(str(item.get('CDiff', '0')).replace(',', ''))
                rate = float(str(item.get('CDiffRate', '0')).replace(',', ''))
                if sym.startswith('TX') and '-' not in sym and last_p > 5000 and not tx_quote:
                    tx_quote = {"price": last_p, "diff": diff, "rate": rate}
                und_id = str(item.get('UnderlyingId', '')).strip()
                if und_id.isdigit() and len(und_id) == 4 and last_p > 0 and '-' not in sym:
                    if und_id not in stock_futures:
                        stock_futures[und_id] = {"near": {"price": last_p}}
    except Exception:
        pass

    if tx_quote and res['spot_close'] > 0:
        diff = tx_quote['price'] - res['spot_close']
        dtype = "正價差" if diff >= 0 else "逆價差"
        res['futures_str'] = f"`{tx_quote['price']:,.2f}` ({tx_quote['diff']:+,.2f} / {tx_quote['rate']:+.2f}%) ｜ {dtype} `{abs(diff):,.2f}` 點"
    else:
        res['futures_str'] = "即時撮合中"

    return res, stock_futures

def get_spot_orderbook(ticker_list):
    book_dict = {}
    if not ticker_list: return book_dict
    try:
        query_keys = [f"{'tse' if t.split('.')[1] == 'TW' else 'otc'}_{t.split('.')[0]}.tw" for t in ticker_list]
        r = requests.get(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={'|'.join(query_keys)}", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            for m in r.json().get('msgArray', []):
                sid = m.get('c', '')
                ask_str = m.get('a', '_').split('_')[0]
                last_p = float(m.get('z', '0')) if m.get('z', '0') != '-' else 0.0
                ask_p = float(ask_str) if ask_str.replace('.', '', 1).isdigit() else last_p
                if sid: book_dict[sid] = {"ask1": ask_p, "last": last_p}
    except Exception:
        pass
    return book_dict

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
        desc, status, score = "多頭破頸線 (階梯墊高)", "🟢 突破頸線 (轉強發動)", 90
    elif c_price >= neck_low:
        desc, status, score = "強勢箱型蓄勢 (回測支撐)", "🟡 突破後回測 (支撐確認)", 82
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
    session_name, title_suffix, date_str, is_chips_session = get_session_info()
    market_info, stock_futures = get_market_and_futures()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers: return

    target_spot_tickers = [t for t in all_tickers if t.split('.')[0] in stock_futures]
    spot_book = get_spot_orderbook(target_spot_tickers)

    scored_results = []
    monster_candidates = []
    spread_candidates = []

    chunk_size = 150
    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            df_batch = yf.download(chunk, period="3mo", interval="1d", auto_adjust=True, progress=False)
            
            for ticker in chunk:
                df = pd.DataFrame()
                if isinstance(df_batch.columns, pd.MultiIndex):
                    if ticker in df_batch.columns.get_level_values(1):
                        df['Close'] = df_batch['Close'][ticker]
                        df['High'] = df_batch['High'][ticker]
                        df['Low'] = df_batch['Low'][ticker]
                        df['Volume'] = df_batch['Volume'][ticker]
                else:
                    if len(chunk) == 1: df = df_batch.copy()
                
                df = df.dropna()
                if df.empty or len(df) < 25: continue

                sid, name, theme_str, original_ind = stock_dict[ticker]
                today_close = float(df['Close'].iloc[-1])
                today_vol = float(df['Volume'].iloc[-1])
                
                est_money_mil = (today_close * today_vol) / 100_000_000
                if est_money_mil < 1.0 or today_close < 10.0:
                    continue

                vol_ma5 = float(df['Volume'].rolling(5).mean().iloc[-1]) if len(df) >= 5 else today_vol
                atr_14 = calculate_atr(df, 14)
                atr_pct = (atr_14 / today_close) * 100

                # 高動能妖股篩選
                if original_ind in ALLOWED_MONSTER_INDUSTRIES and vol_ma5 > 0:
                    vol_ratio = round(today_vol / vol_ma5, 1)
                    if vol_ratio >= 2.5 and atr_pct >= 3.5:
                        m_sl = round(max(float(df['Low'].iloc[-5:].min()) * 0.99, today_close - atr_14 * 1.5), 2)
                        m_tp = round(today_close + atr_14 * 3.5, 2)
                        monster_candidates.append({
                            "sid": sid, "name": name, "industry": original_ind,
                            "close": f"{today_close:.2f}", "vol_ratio": vol_ratio,
                            "entry": f"{round(today_close*0.992,2)} ~ {round(today_close*1.006,2)}",
                            "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100,2)}%)",
                            "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100,2)}%)",
                            "score": vol_ratio * atr_pct
                        })

                # 正逆價差套利
                if sid in stock_futures:
                    near_f = stock_futures[sid].get("near")
                    if near_f:
                        spot_p = spot_book.get(sid, {}).get('last', today_close)
                        fut_p = near_f['price']
                        diff_val = fut_p - spot_p
                        net_pct = (diff_val / spot_p) * 100 - FRICTION_COST_PCT
                        if diff_val != 0 and abs((diff_val / spot_p) * 100) >= 0.5:
                            spread_candidates.append({
                                "sid": sid, "name": name, "industry": original_ind,
                                "spot_p": f"{spot_p:,.2f}", "fut_p": f"{fut_p:,.2f}",
                                "diff_str": f"{diff_val:+,.2f} ({net_pct:+.2f}%)",
                                "signal": "🟢 正價差套利" if diff_val > 0 else "🔴 逆價差套利",
                                "net_pct_abs": abs(net_pct)
                            })

                # 波段結構篩選
                p_res = analyze_pattern_stages(df, today_close, atr_14)
                if p_res:
                    score = p_res["score"] + (15 if theme_str != original_ind else 0)
                    scored_results.append({
                        "sid": sid, "name": name, "industry": original_ind,
                        "close": f"{today_close:.2f}", "score": score, **p_res
                    })
        except Exception:
            continue

    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    top_picks = sorted_all[:6]
    top_monsters = sorted(monster_candidates, key=lambda x: x["score"], reverse=True)[:2]
    top_spreads = sorted(spread_candidates, key=lambda x: x['net_pct_abs'], reverse=True)[:1]

    fields = []
    fields.append({
        "name": f"📊 加權指數大盤解析 ({market_info['trend']})",
        "value": (
            f"> **收盤點位**: `{market_info['spot_close']:,.2f}`\n"
            f"> **單日漲跌**: `{market_info['pts']:+,.2f}` ({market_info['pct']:+.2f}%) {market_info['emoji']}\n"
            f"> **防守月線**: `{market_info['ma20']:,.2f}`\n"
            f"> **台指期貨**: {market_info.get('futures_str', '即時撮合中')}"
        ),
        "inline": False
    })
    
    fields.append({"name": f"───────── 🎯 盤後精選 Top 6 ─────────", "value": "\u200b", "inline": False})
    if top_picks:
        for i, item in enumerate(top_picks):
            fields.append({
                "name": f"📌 {item['sid']} {item['name']} ｜ 現價 : {item['close']}",
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
        fields.append({"name": "⚡ 狀態提示", "value": "> 掃描區間內暫無符合條件標的", "inline": False})

    fields.append({"name": f"───────── 🚨 高動能妖股預警 (Top 2) ─────────", "value": "\u200b", "inline": False})
    if top_monsters:
        for m in top_monsters:
            fields.append({
                "name": f"🔥 {m['sid']} {m['name']} ｜ 現價 : {m['close']}",
                "value": f"> **產業**: `{m['industry']}`\n> **爆量倍數**: `{m['vol_ratio']}x`\n> **進場區間**: `{m['entry']}`\n> **止盈 (TP)**: `{m['tp']}`\n> **止損 (SL)**: `{m['sl']}`",
                "inline": True
            })
    else:
        fields.append({"name": "⚡ 狀態提示", "value": "> 今日無符合高動能妖股特徵之標的", "inline": False})

    fields.append({"name": f"───────── ⚡ 期現貨價差套利焦點 ─────────", "value": "\u200b", "inline": False})
    if top_spreads:
        ts = top_spreads[0]
        fields.append({
            "name": f"⚡ {ts['sid']} {ts['name']} ｜ {ts['signal']}",
            "value": f"> **現貨價格**: `{ts['spot_p']}`\n> **期貨價格**: `{ts['fut_p']}`\n> **價差與淨利**: `{ts['diff_str']}`",
            "inline": False
        })
    else:
        fields.append({"name": "⚡ 狀態提示", "value": "> 暫無顯著正逆價差套利標的", "inline": False})

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股盤後分析報告 (手動) ({date_str})",
            "description": "已修復價格抓取、過濾無量標的，並完成 Top 6 與妖股精選：",
            "color": 3447003,
            "fields": fields
        }]
    }
    send_msg(payload)

if __name__ == "__main__":
    main()
