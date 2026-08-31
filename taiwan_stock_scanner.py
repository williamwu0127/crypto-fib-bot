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
            print(f"發送警示回應: {r.text}")
    except Exception as e:
        print(f"Webhook 發送失敗: {e}")

def get_session_info():
    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    
    event_name = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    trigger_type = "排程推播" if event_name == "schedule" else "手動觸發"

    time_val = now_tw.hour * 100 + now_tw.minute
    if time_val < 900:
        session = "盤前掃描"
    elif 900 <= time_val <= 1330:
        session = "盤中分析"
    else:
        session = "盤後總結"

    return f"{session} ｜ {trigger_type}", now_tw.strftime("%Y-%m-%d %H:%M")

def refine_industry(name, original_industry):
    orig_str = str(original_industry).strip() if original_industry else ""
    if orig_str and orig_str not in ["其他", "nan", "其他業"]:
        return orig_str
        
    name_str = str(name)
    if any(k in name_str for k in ["生技", "藥", "醫", "基因", "針劑"]):
        return "生技醫療"
    elif any(k in name_str for k in ["能源", "綠能", "太陽能", "風電", "電力", "環保"]):
        return "綠能環保"
    elif any(k in name_str for k in ["投控", "控股", "投資", "集團"]):
        return "投資控股"
    elif any(k in name_str for k in ["建設", "開發", "營造", "置地"]):
        return "營建開發"
    elif any(k in name_str for k in ["軟體", "資訊", "網路", "雲端", "系統"]):
        return "資訊服務"
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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

def analyze_pattern_stages(df):
    try:
        close_s = df['Close']
        high_s = df['High']
        low_s = df['Low']
        
        c_price = float(close_s.iloc[-1])
        ma20 = float(close_s.rolling(20).mean().iloc[-1])
        
        low_40d = low_s.iloc[-40:]
        head_idx = low_40d.idxmin()
        head_pos = low_40d.index.get_loc(head_idx)
        head_price = float(low_40d.min())
        
        if head_pos < 5 or head_pos > len(low_40d) - 4:
            return None
            
        right_foot = float(low_40d.iloc[head_pos+1:].min())
        neck_high = float(high_s.loc[low_40d.index[head_pos]:].max())
        neck_low = round(neck_high * 0.985, 2)
        stop_loss = round(head_price * 0.97, 2)
        
        if c_price >= neck_high:
            stage = "🟢 突破頸線"
            action = f"破 `{neck_high:.2f}` 站穩加碼 ｜ 回測 `{neck_low:.2f}` 承接"
            score = 95
        elif c_price >= neck_low and c_price < neck_high:
            stage = "🟡 突破後回測"
            action = f"回測 `{neck_low:.2f}` 不破進 ｜ 跌破放棄"
            score = 88
        elif right_foot >= head_price and c_price > ma20:
            stage = "🟢 左右腳完成 (W底)"
            action = f"左側 `{right_foot*1.01:.2f}` 試單 ｜ 突破 `{neck_high:.2f}` 加碼"
            score = 82
        elif right_foot >= head_price:
            stage = "🟡 右腳形成中"
            action = f"左側 `{right_foot*1.01:.2f}` 分批接 ｜ 突破 `{neck_high:.2f}` 確認"
            score = 75
        else:
            return None

        return {
            "stage": stage,
            "neck_zone": f"{neck_low:.2f}~{neck_high:.2f}",
            "stop_loss": f"{stop_loss:.2f}",
            "action": action,
            "score": score
        }
    except Exception:
        return None

def get_market_and_futures():
    """獲取加權指數與台指期行情，並精確計算正逆價差"""
    res = {}
    spot_close = 0.0
    
    # 1. 加權指數
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
            
            res['spot_close'] = spot_close
            res['spot_str'] = f"`{spot_close:,.2f}` ({pts:+,.2f}點 / {pct:+.2f}%) ｜ {trend}"
            res['ma20'] = f"`{ma20:,.2f}`"
    except Exception as e:
        print(f"大盤獲取失敗: {e}")

    # 2. 台指期貨（透過 yfinance 穩健獲取近月台指期）
    f_price = 0.0
    f_pts = 0.0
    f_pct = 0.0
    futures_found = False

    for symbol in ["WTX&", "TX=F", "^TWII"]:
        try:
            tx = yf.Ticker(symbol)
            df_f = tx.history(period="5d", interval="1d")
            if not df_f.empty and len(df_f) >= 2:
                f_price = float(df_f['Close'].iloc[-1])
                f_prev = float(df_f['Close'].iloc[-2])
                f_pts = f_price - f_prev
                f_pct = (f_pts / f_prev) * 100
                if f_price > 5000:
                    futures_found = True
                    break
        except Exception:
            continue

    if futures_found and spot_close > 0:
        diff_pts = f_price - spot_close
        diff_type = "正價差" if diff_pts >= 0 else "逆價差"
        res['futures_str'] = f"`{f_price:,.2f}` ({f_pts:+,.2f}點 / {f_pct:+.2f}%) ｜ {diff_type} `{abs(diff_pts):,.2f}`點"
    else:
        res['futures_str'] = "盤中即時撮合中"

    return res

def main():
    session_title, date_time_str = get_session_info()
    print(f"啟動台股掃描：{session_title} ({date_time_str})")
    
    market_info = get_market_and_futures()
    stock_dict = get_dynamic_all_stocks()
    all_tickers = list(stock_dict.keys())
    
    if not all_tickers:
        print("未獲取到股票清單，結束執行。")
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
                c_price = float(df['Close'].iloc[-1])
                c_vol = float(df['Volume'].iloc[-1])
                vol_ma5 = float(df['Volume'].rolling(5).mean().iloc[-1])
                
                if (c_price * c_vol) / 100_000_000 < 0.8:
                    continue

                recent_high_20d = float(df['High'].iloc[-21:-1].max())
                recent_low_20d = float(df['Low'].iloc[-21:-1].min())
                box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d if recent_low_20d > 0 else 99
                
                if box_range_pct <= 0.25 and vol_ma5 > 0 and (c_vol / vol_ma5) >= 2.5 and c_price >= recent_high_20d * 0.98:
                    monster_stocks.append({
                        "sid": sid,
                        "name": name,
                        "close": f"{c_price:,.2f}",
                        "vol_ratio": round(c_vol / vol_ma5, 1)
                    })

                p_res = analyze_pattern_stages(df)
                if p_res:
                    scored_results.append({
                        "sid": sid,
                        "name": name,
                        "industry": industry,
                        "close": f"{c_price:,.2f}",
                        **p_res
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

    fields = []
    
    # 1. 大盤與台指期
    if 'spot_str' in market_info:
        fields.append({
            "name": "📊 大盤 ＆ 台指期解析",
            "value": (
                f"> • **加權指數**: {market_info['spot_str']}\n"
                f"> • **台指期貨**: {market_info.get('futures_str', '即時連線中')}\n"
                f"> • **防守月線**: {market_info.get('ma20', '無')}"
            ),
            "inline": False
        })

    # 2. 一行一項極簡 Top 10
    if top_picks:
        top_lines_1 = []
        for item in top_picks[:5]:
            top_lines_1.append(
                f"📌 **{item['sid']} {item['name']}** ({item['industry']}) ｜ 現價 `{item['close']}`\n"
                f"> • 狀態: {item['stage']} ｜ 頸線 `{item['neck_zone']}` ｜ 停損 `{item['stop_loss']}`\n"
                f"> • 策略: {item['action']}"
            )
        fields.append({
            "name": "🎯 精選 Top 10（型態與策略 1-5）",
            "value": "\n\n".join(top_lines_1),
            "inline": False
        })

        if len(top_picks) > 5:
            top_lines_2 = []
            for item in top_picks[5:10]:
                top_lines_2.append(
                    f"📌 **{item['sid']} {item['name']}** ({item['industry']}) ｜ 現價 `{item['close']}`\n"
                    f"> • 狀態: {item['stage']} ｜ 頸線 `{item['neck_zone']}` ｜ 停損 `{item['stop_loss']}`\n"
                    f"> • 策略: {item['action']}"
                )
            fields.append({
                "name": "🎯 精選 Top 10（型態與策略 6-10）",
                "value": "\n\n".join(top_lines_2),
                "inline": False
            })
    else:
        fields.append({
            "name": "🎯 精選 Top 10（型態與策略）",
            "value": "> 今日全市場暫無符合型態結構之標的",
            "inline": False
        })

    # 3. 妖股獵人
    if monster_stocks:
        m_lines = "\n".join([f"> • 🔥 **{m['sid']} {m['name']}** ｜ 現價 `{m['close']}` ｜ 爆量 `{m['vol_ratio']}x`" for m in monster_stocks[:3]])
        fields.append({
            "name": "🚨 妖股獵人 (飆股狂飆預警)",
            "value": m_lines,
            "inline": False
        })
    else:
        fields.append({
            "name": "🚨 妖股獵人 (飆股狂飆預警)",
            "value": "> • **狀態**：暫無符合",
            "inline": False
        })

    payload = {
        "username": "台股型態量化監控",
        "embeds": [{
            "title": f"📈 台股型態量化監控報告（{session_title}）",
            "description": f"**資料時間**：`{date_time_str}`",
            "color": 3447003,
            "fields": fields
        }]
    }

    send_msg(payload)

if __name__ == "__main__":
    main()
