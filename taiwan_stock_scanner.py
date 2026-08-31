import os
import re
import logging
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

# 抑制 yfinance 報錯日誌
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Discord Webhook
WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

# 交易摩擦成本（現貨+期貨來回手續費與稅金 ≈ 0.40%）
FRICTION_COST_PCT = 0.40

# 指定 15 大核心聚焦族群庫 (Top 6 專屬池)
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

# 飆股排除低波動族群
NON_MONSTER_INDUSTRIES = ["金融保險業", "水泥工業", "食品工業", "鋼鐵工業", "建材營造", "油電燃氣業", "觀光餐旅"]

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
        session_name = "盤前"
    elif 900 <= time_val <= 1330:
        session_name = "盤中"
    elif 1330 < time_val < 1745:
        session_name = "盤後"
    else:
        session_name = "籌碼"

    title_str = f"全方位{session_name}分析報告 ({trigger_type})"
    return session_name, title_str, now_tw.strftime("%Y-%m-%d"), (session_name == "籌碼")

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
            if not dfs:
                continue
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
                        ticker = f"{sid}.{market}"
                        stock_dict[ticker] = (sid, name, theme_str, original_ind)
        except Exception:
            continue
    return stock_dict

def get_institutional_data(date_str):
    """抓取 18:00 盤後三大法人買賣超統計與個股籌碼"""
    market_chips = {}
    stock_chips = {}
    date_nodash = date_str.replace("-", "")
    try:
        url_mkt = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={date_nodash}&type=day&response=json"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url_mkt, headers=headers, timeout=5)
        if r.status_code == 200:
            res_json = r.json()
            if res_json.get("stat") == "OK":
                for row in res_json.get("data", []):
                    name = row[0].strip()
                    net_val = float(str(row[3]).replace(",", "")) / 100_000_000
                    if "外資" in name:
                        market_chips["外資"] = net_val
                    elif "投信" in name:
                        market_chips["投信"] = net_val
                    elif "自營商" in name:
                        market_chips["自營商"] = market_chips.get("自營商", 0.0) + net_val

        url_t86 = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_nodash}&selectType=ALL&response=json"
        r_t86 = requests.get(url_t86, headers=headers, timeout=5)
        if r_t86.status_code == 200:
            res_t86 = r_t86.json()
            if res_t86.get("stat") == "OK":
                for row in res_t86.get("data", []):
                    sid = row[0].strip()
                    foreign_net = int(str(row[4]).replace(",", "")) // 1000
                    trust_net = int(str(row[10]).replace(",", "")) // 1000
                    stock_chips[sid] = {"foreign": foreign_net, "trust": trust_net}
    except Exception:
        pass
    return market_chips, stock_chips

def calculate_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = tr.rolling(period).mean().iloc[-1]
    return float(atr_val) if not pd.isna(atr_val) else float(high.iloc[-1] - low.iloc[-1])

def analyze_pattern_stages(df, sid, theme_str):
    try:
        close_s = df['Close']
        high_s = df['High']
        low_s = df['Low']
        
        c_price = float(close_s.iloc[-1])
        ma10 = float(close_s.rolling(10).mean().iloc[-1])
        ma20 = float(close_s.rolling(20).mean().iloc[-1])
        ma20_s = close_s.rolling(20).mean()
        ma20_slope = ma20 - float(ma20_s.iloc[-3])
        atr_14 = calculate_atr(df, 14)
        
        if c_price < ma20 or ma20_slope < 0:
            return None

        low_40d = low_s.iloc[-40:]
        head_idx = low_40d.idxmin()
        head_pos = low_40d.index.get_loc(head_idx)
        head_price = float(low_40d.min())
        
        if head_pos < 3 or head_pos > len(low_40d) - 3:
            return None
            
        left_foot = float(low_40d.iloc[:head_pos].min())
        right_foot = float(low_40d.iloc[head_pos+1:].min())
        
        neck_high = float(high_s.loc[low_40d.index[head_pos]:].max())
        neck_low = round(neck_high * 0.985, 2)
        neck_zone = f"{neck_low:.2f} ~ {neck_high:.2f}"
        
        recent_low_5d = float(low_s.iloc[-5:].min())
        
        if c_price >= neck_high and right_foot >= left_foot:
            structure_desc = "多頭破頸線 (突破20日高, 階梯墊高發動)"
            status_text = "🟢 突破頸線 (波段轉強)"
            left_strat = f"`{right_foot*1.01:.2f}` 左腳已成"
            right_strat = f"突破 `{neck_high:.2f}` 站穩加碼 ｜ 回測 `{neck_low:.2f}` 承接"
            score = 96
        elif c_price >= neck_low and c_price < neck_high:
            structure_desc = "強勢箱型蓄勢 (回測頸線支撐帶, 浮額清洗)"
            status_text = "🟡 突破後回測 (支撐確認)"
            left_strat = f"`{neck_low:.2f}` 支撐帶試單"
            right_strat = f"回測 `{neck_low:.2f}` 不破進場 ｜ 跌破放棄"
            score = 89
        elif right_foot >= head_price and c_price > ma10:
            pattern_type = "W底" if abs(left_foot - right_foot) / left_foot <= 0.035 else "右腳墊高築底"
            structure_desc = f"{pattern_type} (均線多頭排列, 右腳支撐確立)"
            status_text = f"🟢 左右腳成型 ({pattern_type})"
            left_strat = f"`{right_foot*1.01:.2f}` 附近低接試單"
            right_strat = f"帶量突破 `{neck_high:.2f}` 確認順勢加碼"
            score = 84
        elif right_foot >= head_price:
            structure_desc = "底部二度回測 (右腳築底中, 均線糾結轉折)"
            status_text = "🟡 右腳形成中 (轉折觀察)"
            left_strat = f"`{right_foot*1.01:.2f}` 分批承接"
            right_strat = f"突破 `{neck_high:.2f}` 確認後加碼"
            score = 76
        else:
            return None

        is_target_theme = any(sid in sids for sids in TARGET_THEMES.values())
        if is_target_theme:
            score += 15

        # 每檔獨立動態 SL（取最貼近之有效支撐 max）
        support_levels = [recent_low_5d * 0.992, c_price - atr_14 * 1.5]
        if c_price >= neck_low:
            support_levels.append(neck_low * 0.988)
            
        sl_price = round(max(support_levels), 2)
        sl_price = min(sl_price, round(c_price * 0.975, 2))
        sl_price = max(sl_price, round(c_price * 0.920, 2))
        sl_pct = round(((sl_price - c_price) / c_price) * 100, 2)

        # 每檔獨立動態 TP（純形態學等幅測幅）
        box_height = neck_high - right_foot
        pattern_target = round(c_price + max(box_height, atr_14 * 2.2), 2)
        tp_price = pattern_target
        tp_pct = round(((tp_price - c_price) / c_price) * 100, 2)

        entry_low = round(c_price * 0.992, 2)
        entry_high = round(c_price * 1.006, 2)

        return {
            "status_text": f"{status_text}\n> **結構敘述**: `{structure_desc}`",
            "neck_zone": neck_zone,
            "left_strat": left_strat,
            "right_strat": right_strat,
            "tp": f"{tp_price} (+{tp_pct}%)",
            "sl": f"{sl_price} ({sl_pct}%)",
            "entry": f"{entry_low:.2f} ~ {entry_high:.2f}",
            "score": score,
            "is_target_theme": is_target_theme
        }
    except Exception:
        return None

def parse_price(val, default_val=0.0):
    try:
        p = float(str(val).replace(',', '').strip())
        return p if p > 0 else default_val
    except Exception:
        return default_val

def get_taifex_quotes():
    tx_quote = None
    stock_futures = {}
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/json"
        }
        r = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json={"MarketType":"0","SymbolType":"F"}, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json().get('RtData', {}).get('QuoteList', [])
            for item in data:
                sym = item.get('SymbolID', '')
                last_p = parse_price(item.get('CLastPrice'))
                bid_p = parse_price(item.get('CBidPrice'), last_p)
                ask_p = parse_price(item.get('CAskPrice'), last_p)
                diff = parse_price(item.get('CDiff'))
                rate = parse_price(item.get('CDiffRate'))
                
                if sym.startswith('TX') and '-' not in sym and last_p > 5000 and not tx_quote:
                    tx_quote = {"price": last_p, "bid": bid_p, "ask": ask_p, "diff": diff, "rate": rate}

                und_id = str(item.get('UnderlyingId', '')).strip()
                if und_id.isdigit() and len(und_id) == 4 and last_p > 0 and '-' not in sym:
                    f_obj = {"price": last_p, "bid": bid_p, "ask": ask_p, "diff": diff, "rate": rate}
                    if und_id not in stock_futures:
                        stock_futures[und_id] = {"near": f_obj, "far": None}
                    elif stock_futures[und_id]["far"] is None and last_p != stock_futures[und_id]["near"]["price"]:
                        stock_futures[und_id]["far"] = f_obj

        r_stk = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json={"MarketType":"0","SymbolType":"S"}, headers=headers, timeout=5)
        if r_stk.status_code == 200:
            data_stk = r_stk.json().get('RtData', {}).get('QuoteList', [])
            for item in data_stk:
                und_id = str(item.get('UnderlyingId', '')).strip()
                last_p = parse_price(item.get('CLastPrice'))
                bid_p = parse_price(item.get('CBidPrice'), last_p)
                ask_p = parse_price(item.get('CAskPrice'), last_p)
                diff = parse_price(item.get('CDiff'))
                rate = parse_price(item.get('CDiffRate'))
                sym = item.get('SymbolID', '')
                
                if und_id.isdigit() and len(und_id) == 4 and last_p > 0 and '-' not in sym:
                    f_obj = {"price": last_p, "bid": bid_p, "ask": ask_p, "diff": diff, "rate": rate}
                    if und_id not in stock_futures:
                        stock_futures[und_id] = {"near": f_obj, "far": None}
                    elif stock_futures[und_id]["far"] is None:
                        stock_futures[und_id]["far"] = f_obj
    except Exception:
        pass
    return tx_quote, stock_futures

def get_spot_orderbook(ticker_list):
    book_dict = {}
    if not ticker_list:
        return book_dict
    try:
        query_keys = []
        for t in ticker_list:
            sid, mkt = t.split('.')
            prefix = "tse" if mkt == "TW" else "otc"
            query_keys.append(f"{prefix}_{sid}.tw")

        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={'|'.join(query_keys)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            msg_arr = r.json().get('msgArray', [])
            for m in msg_arr:
                sid = m.get('c', '')
                ask_str = m.get('a', '_').split('_')[0]
                last_str = m.get('z', '_')
                
                last_p = parse_price(last_str)
                ask_p = parse_price(ask_str, last_p)
                
                if sid:
                    book_dict[sid] = {"ask1": ask_p, "last": last_p}
    except Exception:
        pass
    return book_dict

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
    except Exception:
        pass

    tx_quote, stock_futures = get_taifex_quotes()
    if tx_quote and spot_close > 0:
        f_price = tx_quote['price']
        f_pts = tx_quote['diff']
        f_pct = tx_quote['rate']
        diff = f_price - spot_close
        dtype = "正價差" if diff >= 0 else "逆價差"
        res['futures_str'] = f"`{f_price:,.2f}` ({f_pts:+,.2f} / {f_pct:+.2f}%) ｜ {dtype} `{abs(diff):,.2f}` 點"
    else:
        res['futures_str'] = "即時撮合中"

    return res, stock_futures

def is_limit_up_locked_over_hour(df, today_close, prev_close):
    try:
        today_pct = ((today_close - prev_close) / prev_close) * 100
        if today_pct < 9.5:
            return False
        today_high = float(df['High'].iloc[-1])
        today_low = float(df['Low'].iloc[-1])
        if today_high == today_close and (today_high - today_low) / prev_close < 0.01:
            return True
        return False
    except Exception:
        return False

def main():
    session_name, title_suffix, date_str, is_chips_session = get_session_info()
    market_info, stock_futures = get_market_and_futures()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers:
        print("未獲取到股票清單，結束。")
        return

    market_chips, stock_chips = get_institutional_data(date_str) if is_chips_session else ({}, {})

    futures_sids = list(stock_futures.keys())
    target_spot_tickers = [t for t in all_tickers if t.split('.')[0] in futures_sids]
    spot_book = get_spot_orderbook(target_spot_tickers)

    chunk_size = 150
    scored_results = []
    monster_stocks = []
    spread_candidates = []

    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            df_batch = yf.download(chunk, period="3mo", interval="1d", group_by="ticker", progress=False, threads=True)
            
            for ticker in chunk:
                try:
                    df = df_batch[ticker].dropna() if len(chunk) > 1 else df_batch.dropna()
                    if df.empty or len(df) < 45:
                        continue

                    sid, name, theme_str, original_ind = stock_dict[ticker]
                    close_s = df['Close']
                    high_s = df['High']
                    low_s = df['Low']
                    vol_s = df['Volume']

                    today_close = float(close_s.iloc[-1])
                    prev_close = float(close_s.iloc[-2])
                    today_vol = float(vol_s.iloc[-1])
                    vol_ma5 = float(vol_s.rolling(5).mean().iloc[-1])
                    atr_14 = calculate_atr(df, 14)
                    atr_pct = (atr_14 / today_close) * 100

                    if is_limit_up_locked_over_hour(df, today_close, prev_close):
                        continue

                    # 遠月正價差全域掃描
                    if sid in stock_futures and today_close > 0:
                        f_dict = stock_futures[sid]
                        far_f = f_dict.get("far")
                        
                        if far_f:
                            book_info = spot_book.get(sid, {})
                            spot_ask = book_info.get('ask1', today_close)
                            fut_bid = far_f['bid']
                            pos_diff = fut_bid - spot_ask
                            
                            if pos_diff >= 0:
                                diff_val = pos_diff
                                base_spot = spot_ask
                                gross_pct = (diff_val / base_spot) * 100 if base_spot > 0 else 0.0
                                net_pct = gross_pct - FRICTION_COST_PCT
                                cost_ratio = (FRICTION_COST_PCT / gross_pct * 100) if gross_pct > 0 else 100.0
                                
                                if net_pct >= 0.2:
                                    signal = f"實質淨正價差 +{net_pct:.2f}% (成本佔 {cost_ratio:.0f}%)"
                                else:
                                    signal = f"成本摩擦偏高 (佔 {min(cost_ratio, 99):.0f}%) ｜ 邊際利潤"

                                if gross_pct >= 0.45:
                                    spread_candidates.append({
                                        "sid": sid,
                                        "name": name,
                                        "industry": theme_str,
                                        "spot_p": f"{base_spot:,.2f}",
                                        "far_p": f"{far_f['price']:,.2f}",
                                        "diff_val": diff_val,
                                        "net_pct": net_pct,
                                        "diff_str": f"+{diff_val:.2f} (+{(diff_val/base_spot)*100:.2f}%)",
                                        "signal": signal
                                    })

                    est_money_mil = (today_close * today_vol) / 100_000_000
                    if est_money_mil < 0.8:
                        continue

                    gain_5d = ((today_close - float(close_s.iloc[-6])) / float(close_s.iloc[-6])) * 100
                    yesterday_pct = ((prev_close - float(close_s.iloc[-3])) / float(close_s.iloc[-3])) * 100
                    if gain_5d > 25.0 and yesterday_pct >= 9.0:
                        continue

                    # 全域推薦（排除低波動 + ATR% >= 3.0% 飆股特徵）
                    recent_high_20d = float(high_s.iloc[-21:-1].max())
                    recent_low_20d = float(low_s.iloc[-21:-1].min())
                    box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d if recent_low_20d > 0 else 99
                    
                    is_excluded_industry = (original_ind in NON_MONSTER_INDUSTRIES) or (theme_str in ["金融保險業", "水泥工業", "食品工業"])
                    
                    if (not is_excluded_industry) and atr_pct >= 3.0 and box_range_pct <= 0.28 and vol_ma5 > 0 and (today_vol / vol_ma5) >= 2.2 and today_close >= recent_high_20d * 0.98 and gain_5d <= 22.0:
                        m_entry_low = round(today_close * 0.992, 2)
                        m_entry_high = round(today_close * 1.006, 2)
                        m_sl = round(max(recent_low_20d * 0.99, today_close - atr_14 * 1.4), 2)
                        m_tp = round(today_close + max(recent_high_20d - recent_low_20d, atr_14 * 3.5), 2)

                        monster_stocks.append({
                            "sid": sid,
                            "name": name,
                            "industry": theme_str,
                            "close": f"{today_close:.2f}",
                            "vol_ratio": round(today_vol / vol_ma5, 1),
                            "entry": f"{m_entry_low:.2f} ~ {m_entry_high:.2f}",
                            "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100, 2)}%)",
                            "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100, 2)}%)"
                        })

                    # 波段評分
                    p_res = analyze_pattern_stages(df, sid, theme_str)
                    if p_res:
                        scored_results.append({
                            "sid": sid,
                            "name": name,
                            "industry": theme_str,
                            "close": f"{today_close:.2f}",
                            **p_res
                        })
                except Exception:
                    continue
        except Exception:
            continue

    target_results = [x for x in scored_results if x["is_target_theme"]]
    if len(target_results) < 6:
        target_results += [x for x in scored_results if not x["is_target_theme"]]

    sorted_all = sorted(target_results, key=lambda x: x["score"], reverse=True)
    industry_count = {}
    top_picks = []
    
    for item in sorted_all:
        ind = item["industry"]
        if industry_count.get(ind, 0) < 2:
            industry_count[ind] = industry_count.get(ind, 0) + 1
            top_picks.append(item)
            
        if len(top_picks) >= 6:
            break

    top_4_spreads = sorted(spread_candidates, key=lambda x: x['net_pct'], reverse=True)[:4]

    fields = []
    
    # 1. 大盤解析（含 18:00 三大法人籌碼匯總）
    if 'spot_close' in market_info:
        fut_text = f"\n> **台指期貨**: {market_info.get('futures_str', '即時撮合中')}"
        chips_summary_text = ""
        if is_chips_session and market_chips:
            f_net = market_chips.get('外資', 0.0)
            t_net = market_chips.get('投信', 0.0)
            d_net = market_chips.get('自營商', 0.0)
            total_net = f_net + t_net + d_net
            chips_summary_text = (
                f"\n> **法人籌碼**: 外資 `{f_net:+,.1f}億` ｜ 投信 `{t_net:+,.1f}億` ｜ 自營 `{d_net:+,.1f}億`\n"
                f"> **三大法人合計**: `{total_net:+,.1f}億` ({'🟢 法人同步作多' if total_net > 0 else '🔴 法人偏空調節'})"
            )

        fields.append({
            "name": f"📊 加權指數大盤解析 ({market_info['trend']})",
            "value": (
                f"> **收盤點位**: `{market_info['spot_close']:,.2f}`\n"
                f"> **單日漲跌**: `{market_info['pts']:+,.2f}` ({market_info['pct']:+.2f}%) {market_info['emoji']}\n"
                f"> **防守月線**: `{market_info['ma20']:,.2f}`"
                f"{fut_text}"
                f"{chips_summary_text}"
            ),
            "inline": False
        })
    
    # 2. 波段精選 Top 6（族群置於標題列）
    fields.append({
        "name": f"───────── 🎯 {session_name}波段精選 Top 6 (核心族群) ─────────",
        "value": "\u200b",
        "inline": False
    })
    
    for i, item in enumerate(top_picks):
        chip_line = ""
        if is_chips_session and item['sid'] in stock_chips:
            c_info = stock_chips[item['sid']]
            f_cnt = c_info['foreign']
            t_cnt = c_info['trust']
            tag = "土洋同買 🔥" if f_cnt > 0 and t_cnt > 0 else ("投信認養 🟢" if t_cnt > 0 else "法人調節 🔴")
            chip_line = f"\n> **法人籌碼**: 外資 `{f_cnt:+d}張` ｜ 投信 `{t_cnt:+d}張` ({tag})"

        fields.append({
            "name": f"📌 {item['sid']} {item['name']} ｜ {item['industry']}  現價 : {item['close']}",
            "value": (
                f"> **進場區間**: `{item['entry']}`\n"
                f"> **動態止盈 (TP)**: `{item['tp']}`\n"
                f"> **動態止損 (SL)**: `{item['sl']}`\n"
                f"> **頸線區間**: `{item['neck_zone']}`\n"
                f"> **左側策略**: {item['left_strat']}\n"
                f"> **右側策略**: {item['right_strat']}\n"
                f"> **結構狀態**: {item['status_text']}"
                f"{chip_line}"
            ),
            "inline": True
        })
        if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    # 3. 全域推薦（飆股狂飆預警）
    fields.append({
        "name": "───────── 🚨 全域推薦 (飆股狂飆預警) ─────────",
        "value": "\u200b",
        "inline": False
    })
    
    if monster_stocks:
        top_monsters = sorted(monster_stocks, key=lambda x: x["vol_ratio"], reverse=True)[:3]
        for m in top_monsters:
            m_chip_line = ""
            if is_chips_session and m['sid'] in stock_chips:
                c_info = stock_chips[m['sid']]
                m_chip_line = f"\n> **法人籌碼**: 外資 `{c_info['foreign']:+d}張` ｜ 投信 `{c_info['trust']:+d}張`"

            fields.append({
                "name": f"🔥 {m['sid']} {m['name']} ｜ {m['industry']}  現價 : {m['close']}",
                "value": (
                    f"> **爆量倍數**: `{m['vol_ratio']}x`\n"
                    f"> **進場**: `{m['entry']}`\n"
                    f"> **止盈 (TP)**: `{m['tp']}`\n"
                    f"> **止損 (SL)**: `{m['sl']}`"
                    f"{m_chip_line}"
                ),
                "inline": True
            })
    else:
        fields.append({
            "name": "⚡ 狀態提示",
            "value": "> 今日全市場暫無符合高波動起漲特徵之標的",
            "inline": False
        })

    # 4. 期現貨正價差套利焦點
    fields.append({
        "name": "───────── ⚡ 期現貨正價差套利焦點 ─────────",
        "value": "\u200b",
        "inline": False
    })

    if top_4_spreads:
        for i, item in enumerate(top_4_spreads):
            fields.append({
                "name": f"⚡ {item['sid']} {item['name']} ｜ {item['industry']}",
                "value": (
                    f"> **現貨最佳賣價 (Ask)**: `{item['spot_p']}`\n"
                    f"> **遠月期貨買價 (Bid)**: `{item['far_p']}`\n"
                    f"> **實質遠月正價差**: 🟢 `{item['diff_str']}`\n"
                    f"> **淨利 (扣摩擦成本)**: `{item['signal']}`"
                ),
                "inline": True
            })
            if (i + 1) % 2 == 0 and (i + 1) < len(top_4_spreads):
                fields.append({
                    "name": "\u200b",
                    "value": "\u200b",
                    "inline": False
                })
    else:
        fields.append({
            "name": "⚡ 狀態提示",
            "value": "> 今日全市場扣除交易摩擦成本（0.40%）後，暫無顯著遠月期現實質正價差標的。",
            "inline": False
        })

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股{title_suffix} ({date_str})",
            "description": "已完成大盤結構判定、15大核心族群波段掃描與全域飆股預警：",
            "color": 3447003,
            "fields": fields
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
