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

WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

# 交易摩擦成本（現貨手續費+稅金 + 期貨成本 ≈ 0.40%）
FRICTION_COST_PCT = 0.40

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
    else:
        session_name = "盤後"

    title_str = f"全方位{session_name}分析報告 ({trigger_type})"
    return session_name, title_str, now_tw.strftime("%Y-%m-%d")

def refine_industry(name, original_industry):
    orig_str = str(original_industry).strip() if original_industry else ""
    if orig_str and orig_str not in ["其他", "nan", "其他業"]:
        return orig_str
        
    name_str = str(name)
    if any(k in name_str for k in ["生技", "藥", "醫", "基因", "針劑"]):
        return "生技醫療業"
    elif any(k in name_str for k in ["能源", "綠能", "太陽能", "風電", "電力", "環保"]):
        return "綠能環保業"
    elif any(k in name_str for k in ["投控", "控股", "投資", "集團"]):
        return "投資控股業"
    elif any(k in name_str for k in ["建設", "開發", "營造", "置地"]):
        return "建材營造"
    elif any(k in name_str for k in ["軟體", "資訊", "網路", "雲端", "系統"]):
        return "資訊服務業"
    elif any(k in name_str for k in ["航運", "海運", "航空", "物流"]):
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
                        ind_str = refine_industry(name, original_ind)
                        ticker = f"{sid}.{market}"
                        stock_dict[ticker] = (sid, name, ind_str)
        except Exception:
            continue
    return stock_dict

def calculate_atr(df, period=14):
    """計算真實波動區間 ATR"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def analyze_pattern_stages(df):
    """
    動態個股專屬：形態學 4 步驟 ＋ 結構判定 ＋ 依個股 ATR/形態滿足點計算 TP/SL
    """
    try:
        close_s = df['Close']
        high_s = df['High']
        low_s = df['Low']
        
        c_price = float(close_s.iloc[-1])
        ma5 = float(close_s.rolling(5).mean().iloc[-1])
        ma10 = float(close_s.rolling(10).mean().iloc[-1])
        ma20 = float(close_s.rolling(20).mean().iloc[-1])
        atr_14 = calculate_atr(df, 14)
        
        # 尋找過去 40 天結構
        low_40d = low_s.iloc[-40:]
        head_idx = low_40d.idxmin()
        head_pos = low_40d.index.get_loc(head_idx)
        head_price = float(low_40d.min())
        
        if head_pos < 4 or head_pos > len(low_40d) - 3:
            return None
            
        left_foot = float(low_40d.iloc[:head_pos].min())
        right_foot = float(low_40d.iloc[head_pos+1:].min())
        
        # 頸線高點與回測支撐帶
        neck_high = float(high_s.loc[low_40d.index[head_pos]:].max())
        neck_low = round(neck_high * 0.985, 2)
        neck_zone = f"{neck_low:.2f} ~ {neck_high:.2f}"
        
        # ----------------- 結構判定 -----------------
        recent_low_5d = float(low_s.iloc[-5:].min())
        
        if c_price >= neck_high and right_foot > left_foot:
            structure_tag = "多頭破頸線 (階梯墊高)"
            status_text = "🟢 突破頸線 (轉強發動)"
            left_strat = f"`{right_foot*1.01:.2f}` 已過"
            right_strat = f"突破 `{neck_high:.2f}` 站穩加碼 ｜ 回測 `{neck_low:.2f}` 承接"
            score = 95
        elif c_price >= neck_low and c_price < neck_high:
            structure_tag = "強勢箱型整理 (蓄勢突破)"
            status_text = "🟡 突破後回測 (確認支撐)"
            left_strat = f"`{neck_low:.2f}` 支撐小量試單"
            right_strat = f"回測 `{neck_low:.2f}` 不破進場 ｜ 跌破放棄"
            score = 88
        elif right_foot >= head_price and c_price > ma20:
            pattern_type = "W底" if abs(left_foot - right_foot) / left_foot <= 0.03 else "破底翻轉折"
            structure_tag = f"{pattern_type} (右腳確立)"
            status_text = f"🟢 左右腳完成 ({pattern_type})"
            left_strat = f"`{right_foot*1.01:.2f}` 附近試單"
            right_strat = f"帶量突破 `{neck_high:.2f}` 順勢加碼"
            score = 82
        elif right_foot >= head_price:
            structure_tag = "底部築底中 (觀察防守)"
            status_text = "🟡 右腳形成中 (轉折觀察)"
            left_strat = f"`{right_foot*1.01:.2f}` 分批承接"
            right_strat = f"等待突破 `{neck_high:.2f}` 確認"
            score = 75
        else:
            return None

        # ----------------- 個股專屬動態 SL（止損）-----------------
        # 邏輯：取 (近 5 日波段低點, 頸線下緣回測點, 右腳支撐) 之有效防守點，並給予 1.0~1.2 倍 ATR 呼吸空間
        structural_support = min(recent_low_5d, neck_low if c_price >= neck_low else right_foot)
        sl_price = round(min(structural_support * 0.99, c_price - atr_14 * 1.2), 2)
        sl_pct = round(((sl_price - c_price) / c_price) * 100, 2)

        # ----------------- 個股專屬動態 TP（形態 1:1 等幅測幅滿足點）-----------------
        # 邏輯：目標價 = 頸線高點 + (頸線高點 - 底部最低點)
        pattern_height = neck_high - head_price
        target_by_pattern = neck_high + pattern_height
        target_by_risk_reward = c_price + (c_price - sl_price) * 2.2
        
        # 綜合形態滿足點與風控比
        tp_price = round(max(target_by_pattern, target_by_risk_reward), 2)
        tp_pct = round(((tp_price - c_price) / c_price) * 100, 2)

        entry_low = round(c_price * 0.992, 2)
        entry_high = round(c_price * 1.005, 2)

        return {
            "status_text": f"{status_text} ｜ `{structure_tag}`",
            "neck_zone": neck_zone,
            "left_strat": left_strat,
            "right_strat": right_strat,
            "tp": f"{tp_price} (+{tp_pct}%)",
            "sl": f"{sl_price} ({sl_pct}%)",
            "entry": f"{entry_low:.2f} ~ {entry_high:.2f}",
            "score": score
        }
    except Exception:
        return None

def get_taifex_quotes():
    """解析期交所 API：提取台指期與個股期近遠月合約"""
    tx_quote = None
    stock_futures = {}
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/json"
        }
        
        # 1. 期貨即時行情（含台指期）
        r = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json={"MarketType":"0","SymbolType":"F"}, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json().get('RtData', {}).get('QuoteList', [])
            for item in data:
                sym = item.get('SymbolID', '')
                price = float(item.get('CLastPrice', 0))
                diff = float(item.get('CDiff', 0))
                rate = float(item.get('CDiffRate', 0))
                
                if sym.startswith('TX') and '-' not in sym and price > 5000 and not tx_quote:
                    tx_quote = {"price": price, "diff": diff, "rate": rate}

                und_id = str(item.get('UnderlyingId', '')).strip()
                if und_id.isdigit() and len(und_id) == 4 and price > 0 and '-' not in sym:
                    if und_id not in stock_futures:
                        stock_futures[und_id] = {"near": {"price": price, "diff": diff, "rate": rate}, "far": None}
                    elif stock_futures[und_id]["far"] is None and price != stock_futures[und_id]["near"]["price"]:
                        stock_futures[und_id]["far"] = {"price": price, "diff": diff, "rate": rate}

        # 2. 股票期貨專區
        r_stk = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json={"MarketType":"0","SymbolType":"S"}, headers=headers, timeout=5)
        if r_stk.status_code == 200:
            data_stk = r_stk.json().get('RtData', {}).get('QuoteList', [])
            for item in data_stk:
                und_id = str(item.get('UnderlyingId', '')).strip()
                price = float(item.get('CLastPrice', 0))
                diff = float(item.get('CDiff', 0))
                rate = float(item.get('CDiffRate', 0))
                sym = item.get('SymbolID', '')
                
                if und_id.isdigit() and len(und_id) == 4 and price > 0 and '-' not in sym:
                    if und_id not in stock_futures:
                        stock_futures[und_id] = {"near": {"price": price, "diff": diff, "rate": rate}, "far": None}
                    elif stock_futures[und_id]["far"] is None:
                        stock_futures[und_id]["far"] = {"price": price, "diff": diff, "rate": rate}
    except Exception:
        pass
    return tx_quote, stock_futures

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
    session_name, title_suffix, date_str = get_session_info()
    market_info, stock_futures = get_market_and_futures()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers:
        print("未獲取到股票清單，結束。")
        return

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

                    sid, name, industry = stock_dict[ticker]
                    close_s = df['Close']
                    high_s = df['High']
                    low_s = df['Low']
                    vol_s = df['Volume']

                    today_close = float(close_s.iloc[-1])
                    prev_close = float(close_s.iloc[-2])
                    today_vol = float(vol_s.iloc[-1])
                    vol_ma5 = float(vol_s.rolling(5).mean().iloc[-1])

                    # 1. 排除鎖死無買點標的
                    if is_limit_up_locked_over_hour(df, today_close, prev_close):
                        continue

                    # 2. 期現價差計算
                    if sid in stock_futures and today_close > 0:
                        f_dict = stock_futures[sid]
                        near_f = f_dict.get("near")
                        far_f = f_dict.get("far")
                        
                        if near_f:
                            near_p = near_f['price']
                            diff_val = near_p - today_close
                            gross_pct = abs(diff_val / today_close) * 100
                            net_pct = gross_pct - FRICTION_COST_PCT
                            cost_ratio = (FRICTION_COST_PCT / gross_pct * 100) if gross_pct > 0 else 100.0
                            
                            if far_f:
                                far_p = far_f['price']
                                cal_diff = far_p - near_p
                                cal_pct = (cal_diff / near_p) * 100
                                far_str = f"`{far_p:,.2f}` ｜ 跨月 `{'+' if cal_diff>=0 else ''}{cal_diff:.2f}` ({cal_pct:+.2f}%)"
                            else:
                                far_str = "無遠月撮合"

                            if diff_val > 0 and net_pct >= 0.2:
                                signal = f"實質淨正價差 +{net_pct:.2f}% (成本佔 {cost_ratio:.0f}%)"
                            elif diff_val < 0 and net_pct >= 0.2:
                                signal = f"實質淨逆價差 -{net_pct:.2f}% (成本佔 {cost_ratio:.0f}%)"
                            else:
                                signal = f"成本摩擦偏高 (佔 {min(cost_ratio, 99):.0f}%) ｜ 邊際利潤"

                            if gross_pct >= 0.45:
                                spread_candidates.append({
                                    "sid": sid,
                                    "name": name,
                                    "industry": industry,
                                    "spot_p": f"{today_close:,.2f}",
                                    "near_p": f"{near_p:,.2f}",
                                    "far_str": far_str,
                                    "diff_val": diff_val,
                                    "net_pct": net_pct,
                                    "diff_str": f"{'+' if diff_val>=0 else ''}{diff_val:.2f} ({'+' if diff_val>=0 else ''}{(diff_val/today_close)*100:.2f}%)",
                                    "dtype": "🟢 正價差" if diff_val >= 0 else "🔴 逆價差",
                                    "signal": signal
                                })

                    est_money_mil = (today_close * today_vol) / 100_000_000
                    if est_money_mil < 0.8:
                        continue

                    gain_5d = ((today_close - float(close_s.iloc[-6])) / float(close_s.iloc[-6])) * 100
                    yesterday_pct = ((prev_close - float(close_s.iloc[-3])) / float(close_s.iloc[-3])) * 100
                    if gain_5d > 25.0 and yesterday_pct >= 9.0:
                        continue

                    # 3. 妖股獵人判斷
                    recent_high_20d = float(high_s.iloc[-21:-1].max())
                    recent_low_20d = float(low_s.iloc[-21:-1].min())
                    box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d if recent_low_20d > 0 else 99
                    
                    if box_range_pct <= 0.25 and vol_ma5 > 0 and (today_vol / vol_ma5) >= 2.5 and today_close >= recent_high_20d * 0.98 and gain_5d <= 22.0:
                        atr_m = calculate_atr(df, 14)
                        m_entry_low = round(today_close * 0.992, 2)
                        m_entry_high = round(today_close * 1.005, 2)
                        m_sl = round(max(recent_low_20d * 0.99, today_close - atr_m * 1.5), 2)
                        m_tp = round(today_close + (recent_high_20d - recent_low_20d) * 2.5, 2)

                        monster_stocks.append({
                            "sid": sid,
                            "name": name,
                            "industry": industry,
                            "close": f"{today_close:.2f}",
                            "vol_ratio": round(today_vol / vol_ma5, 1),
                            "entry": f"{m_entry_low:.2f} ~ {m_entry_high:.2f}",
                            "tp": f"{m_tp} (+{round(((m_tp-today_close)/today_close)*100, 2)}%)",
                            "sl": f"{m_sl} ({round(((m_sl-today_close)/today_close)*100, 2)}%)"
                        })

                    # 4. 形態 ＋ 結構判讀
                    p_res = analyze_pattern_stages(df)
                    if p_res:
                        scored_results.append({
                            "sid": sid,
                            "name": name,
                            "industry": industry,
                            "close": f"{today_close:.2f}",
                            **p_res
                        })
                except Exception:
                    continue
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

    pos_spreads = sorted([s for s in spread_candidates if s['diff_val'] > 0], key=lambda x: x['net_pct'], reverse=True)[:2]
    neg_spreads = sorted([s for s in spread_candidates if s['diff_val'] < 0], key=lambda x: x['net_pct'], reverse=True)[:2]
    top_4_spreads = pos_spreads + neg_spreads

    fields = []
    
    # 1. 大盤
    if 'spot_close' in market_info:
        fut_text = f"\n> **台指期貨**: {market_info.get('futures_str', '即時撮合中')}"
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
    
    # 2. 精選 Top 10 (含各股專屬 TP/SL、頸線、策略與結構狀態)
    fields.append({
        "name": f"───────── 🎯 {session_name}精選 Top 10 ─────────",
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
                f"> **頸線區間**: `{item['neck_zone']}`\n"
                f"> **左側策略**: {item['left_strat']}\n"
                f"> **右側策略**: {item['right_strat']}\n"
                f"> **結構狀態**: {item['status_text']}"
            ),
            "inline": True
        })
        if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    # 3. 價差焦點 Top 4
    fields.append({
        "name": "───────── ⚡ 個股期現 ＆ 跨月價差焦點 Top 4 ─────────",
        "value": "\u200b",
        "inline": False
    })

    if top_4_spreads:
        for i, item in enumerate(top_4_spreads):
            fields.append({
                "name": f"⚡ {item['sid']} {item['name']} ｜ {item['industry']}",
                "value": (
                    f"> **現貨價位**: `{item['spot_p']}`\n"
                    f"> **近月期 / 價差**: `{item['near_p']}` ｜ {item['dtype']} `{item['diff_str']}`\n"
                    f"> **遠月期 / 跨月**: {item['far_str']}\n"
                    f"> **成本與實質淨利**: `{item['signal']}`"
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
            "value": "> 今日全市場扣除交易摩擦成本（0.40%）後，暫無顯著超額淨價差標的。",
            "inline": False
        })

    # 4. 妖股獵人
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
