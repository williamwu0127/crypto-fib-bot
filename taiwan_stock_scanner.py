import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf"
)

def send_msg(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Discord 狀態碼: {r.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

def refine_industry(name, original_industry):
    """智慧細分產業：若原產業為其他或未分類，透過名稱關鍵字進行精準歸類"""
    orig_str = str(original_industry).strip() if original_industry else ""
    if orig_str and orig_str != "其他" and orig_str != "nan" and orig_str != "其他業":
        return orig_str
        
    name_str = str(name)
    if any(k in name_str for k in ["生技", "藥", "醫", "基因", "針劑", "臨床"]):
        return "生技醫療業"
    elif any(k in name_str for k in ["能源", "綠能", "太陽能", "風電", "電力", "環保", "水資源", "華城", "士電", "中興電"]):
        return "綠能環保業"
    elif any(k in name_str for k in ["投控", "控股", "投資", "集團"]):
        return "投資控股業"
    elif any(k in name_str for k in ["建設", "開發", "營造", "置地", "工程"]):
        return "營建開發業"
    elif any(k in name_str for k in ["軟體", "資訊", "網路", "雲端", "智能", "系統", "數據"]):
        return "資訊服務業"
    elif any(k in name_str for k in ["航運", "海運", "航空", "物流", "運輸"]):
        return "航運業"
    elif any(k in name_str for k in ["機電", "機械", "電機", "自動化"]):
        return "電機機械業"
    
    return "一般產業"

def get_dynamic_all_stocks():
    """動態向台灣證交所官方 ISIN 系統抓取全部現存上市與上櫃普通股及所屬產業（具備多重防護）"""
    stock_dict = {}
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for url, market in urls:
        print(f"正在獲取 {market} 市場股票名冊...")
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
                print(f"透過 parser ({parser}) 成功解析 {market}，共 {len([k for k in stock_dict if k.endswith(market)] )} 檔")
                break
            except Exception as e:
                continue
                
        if not success:
            print(f"警告: 透過 pandas 解析 {market} 失敗，改用備用正規表達式提取...")
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.encoding = "big5-hkscs"
                import re
                matches = re.findall(r'>(\d{4})&#12288;([^<]+)</td>', resp.text)
                for sid, name in matches:
                    ticker = f"{sid}.{market}"
                    stock_dict[ticker] = (sid, name.strip(), "一般產業")
                print(f"備用正則提取 {market} 成功，共 {len([k for k in stock_dict if k.endswith(market)] )} 檔")
            except Exception as e2:
                print(f"動態獲取 {market} 股票名冊完全失敗: {e2}")
                
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

def get_market_analysis():
    """獲取加權指數大盤資訊"""
    try:
        twii = yf.Ticker("^TWII")
        df = twii.history(period="1mo", interval="1d")
        if df.empty or len(df) < 20:
            return None
            
        c_close = float(df['Close'].iloc[-1])
        p_close = float(df['Close'].iloc[-2])
        change_pts = c_close - p_close
        change_pct = (change_pts / p_close) * 100
        
        c_vol_bn = float(df['Volume'].iloc[-1]) / 100_000_000 if float(df['Volume'].iloc[-1]) > 0 else 0
        
        ma5 = float(df['Close'].rolling(5).mean().iloc[-1])
        ma20 = float(df['Close'].rolling(20).mean().iloc[-1])
        
        trend = "🟢 多頭控盤" if c_close > ma20 and ma5 > ma20 else "🔴 空頭弱勢" if c_close < ma20 else "🟡 震盪整理"
        emoji = "📈" if change_pts > 0 else "📉"
        
        return {
            "close": round(c_close, 2),
            "change_pts": round(change_pts, 2),
            "change_pct": round(change_pct, 2),
            "vol_bn": round(c_vol_bn, 2) if c_vol_bn > 0 else "無資料",
            "ma20": round(ma20, 2),
            "trend": trend,
            "emoji": emoji
        }
    except Exception as e:
        print(f"大盤資料獲取失敗: {e}")
        return None

def main():
    print("【步驟 1】獲取大盤行情...")
    market_data = get_market_analysis()

    print("【步驟 2】即時動態向證交所抓取台股全市場名單與智慧產業別...")
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    print(f"總共獲取到 {len(all_tickers)} 檔有效台股標的。")
    
    if not all_tickers:
        print("未獲取到股票清單，結束執行。")
        return

    print("【步驟 3】批次下載全市場歷史量價進行快篩...")
    chunk_size = 200
    scored_results = []
    monster_stocks = []
    latest_trade_date = datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        try:
            df_batch = yf.download(chunk, period="3mo", interval="1d", group_by="ticker", progress=False)
            
            for ticker in chunk:
                if ticker not in df_batch.columns.levels[0]:
                    continue
                
                df = df_batch[ticker].dropna()
                if len(df) < 60:
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

                # ----------------- 妖股獵人判斷 (嚴格條件) -----------------
                recent_high_20d = float(high_s.iloc[-21:-1].max())
                recent_low_20d = float(low_s.iloc[-21:-1].min())
                box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d if recent_low_20d > 0 else 99
                
                is_accumulating_box = box_range_pct <= 0.25
                is_pre_monster_vol = vol_ma5 > 0 and (today_vol / vol_ma5) >= 2.5
                is_breakout_edge = today_close >= recent_high_20d * 0.98
                
                if est_money_mil >= 0.8 and is_accumulating_box and is_pre_monster_vol and is_breakout_edge:
                    m_entry_low = round(today_close * 0.99, 2)
                    m_entry_high = round(today_close * 1.003, 2)
                    m_sl = round(max(recent_low_20d * 0.99, m_entry_low * 0.94), 2)
                    
                    box_height = recent_high_20d - recent_low_20d
                    m_tp = round(max(today_close + box_height * 3.0, today_close * 1.22), 2)

                    m_tp_pct = round(((m_tp - today_close) / today_close) * 100, 2)
                    m_sl_pct = round(((m_sl - today_close) / today_close) * 100, 2)

                    monster_stocks.append({
                        "sid": sid,
                        "name": name,
                        "industry": industry,
                        "close": f"{today_close:.2f}",
                        "vol_ratio": round(today_vol / vol_ma5, 1),
                        "entry": f"{m_entry_low} ~ {m_entry_high}",
                        "tp": f"{m_tp} (+{m_tp_pct}%)",
                        "sl": f"{m_sl} ({m_sl_pct}%)"
                    })

                # ----------------- 常規強勢股判斷 -----------------
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

                entry_low = round(today_close * 0.99, 2)
                entry_high = round(today_close * 1.003, 2)

                support_low = min(float(low_s.iloc[-5:].min()), ma10)
                sl_price = round(max(support_low * 0.99, entry_low * 0.925), 2)
                if sl_price > entry_low * 0.94:
                    sl_price = round(entry_low * 0.935, 2)

                if recent_high_20d > today_close * 1.04:
                    tp_price = round(recent_high_20d, 2)
                else:
                    swing_range = today_close - float(low_s.iloc[-15:].min())
                    tp_price = round(today_close + max(swing_range, (entry_high - sl_price) * 1.8), 2)

                tp_pct = round(((tp_price - today_close) / today_close) * 100, 2)
                sl_pct = round(((sl_price - today_close) / today_close) * 100, 2)

                scored_results.append({
                    "sid": sid,
                    "name": name,
                    "industry": industry,
                    "close": f"{today_close:.2f}",
                    "entry": f"{entry_low:.2f} ~ {entry_high:.2f}",
                    "tp": f"{tp_price} (+{tp_pct}%)",
                    "sl": f"{sl_price} ({sl_pct}%)",
                    "score": score,
                    "tags": " ‧ ".join(reasons) if reasons else "多頭結構"
                })

        except Exception as e:
            print(f"處理批次出錯: {e}")
            continue

    print("【步驟 4】執行產業分散與過濾...")
    sorted_all = sorted(scored_results, key=lambda x: x["score"], reverse=True)
    
    industry_count = {}
    top_picks = []
    
    for item in sorted_all:
        ind = item["industry"]
        if ind not in industry_count:
            industry_count[ind] = 0
            
        if industry_count[ind] < 2:
            industry_count[ind] += 1
            top_picks.append(item)
            
        if len(top_picks) >= 10:
            break

    fields = []
    
    if market_data:
        sign = "+" if market_data['change_pts'] > 0 else ""
        fields.append({
            "name": f"📊 加權指數大盤解析 ({market_data['trend']})",
            "value": (
                f"> **收盤點位**: `{market_data['close']}`\n"
                f"> **單日漲跌**: `{sign}{market_data['change_pts']}` ({sign}{market_data['change_pct']}%) {market_data['emoji']}\n"
                f"> **防守月線**: `{market_data['ma20']}`"
            ),
            "inline": False
        })
    
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
            "inline": True  # 恢復左右並排網格
        })
        if (i + 1) % 2 == 0 and (i + 1) < len(top_picks):
            fields.append({
                "name": "\u200b",
                "value": "\u200b",
                "inline": False
            })

    # ----------------- 妖股獵人區塊（帶有未找到時的提示） -----------------
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
            "value": "> 今日全市場暫無符合「箱體緊縮 + 2.5倍爆量突破」之極端潛伏標的，持續沉澱觀察中。",
            "inline": False
        })

    hour_utc = datetime.utcnow().hour
    session_title = "盤前掃描" if hour_utc < 5 else "盤後分析"

    payload = {
        "username": "台股全市場量化選股",
        "embeds": [{
            "title": f"📈 台股全方位{session_title}報告 ({latest_trade_date})",
            "description": "已完成大盤結構判定、全市場動態掃描與飆股潛伏預警：",
            "color": 3447003,
            "fields": fields
        }]
    }

    print("發送 Discord 訊息...")
    send_msg(payload)

if __name__ == "__main__":
    main()
