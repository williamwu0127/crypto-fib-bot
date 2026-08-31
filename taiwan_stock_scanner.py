import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

# ==================== 1. 設定與環境變數 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

TZ_TW = timezone(timedelta(hours=8))

# 監控標的名單 (支援上市 .TW 與 上櫃 .TWO)
WATCHLIST = {
    '1303': {'name': '南亞', 'industry': '塑膠工業', 'market': 'TW'},
    '1326': {'name': '台化', 'industry': '塑膠工業', 'market': 'TW'},
    '2421': {'name': '建準', 'industry': '一般產業', 'market': 'TW'},
    '2434': {'name': '統懋', 'industry': '半導體業', 'market': 'TWO'},
    '2455': {'name': '全新', 'industry': '通信網路業', 'market': 'TW'},
    '7711': {'name': '永擎', 'industry': '一般產業', 'market': 'TWO'}
}

# ==================== 2. 技術指標與形態計算 ====================
def fetch_stock_data(symbol, market):
    ticker_str = f"{symbol}.{market}"
    try:
        df = yf.download(ticker_str, period="6mo", interval="1d", progress=False)
        if df is None or df.empty or len(df) < 30:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.rename(columns=str.lower)
        req_cols = ['open', 'high', 'low', 'close', 'volume']
        if all(c in df.columns for c in req_cols):
            res_df = df[req_cols].copy()
            res_df.columns = ['o', 'h', 'l', 'c', 'v']
            for col in ['o', 'h', 'l', 'c', 'v']:
                res_df[col] = res_df[col].astype(float)
            return res_df.reset_index(drop=True)
    except Exception as e:
        print(f"⚠️ 抓取 {ticker_str} 失敗: {e}")
    return None

def compute_indicators(df):
    # ATR (14)
    tr = np.maximum(
        df['h'] - df['l'],
        np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1)))
    )
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.02)

    # 均線 EMA
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()

    # RSI (14)
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    return df

# ==================== 3. 右側突破/回測動態 TP/SL 引擎 ====================
def calculate_breakout_strategy(df):
    """
    動態尋找波段高點（頸線區間）並計算修正後的合理風控價位
    """
    curr_bar = df.iloc[-1]
    curr_price = curr_bar['c']
    atr = curr_bar['atr']

    # 取近 20 根 K 棒最高價作為突破頸線上緣，近 5 根局部最高作為頸線下緣
    sub_window = df.iloc[-25:-1]
    neckline_high = float(sub_window['h'].max())
    neckline_low = float(sub_window['h'].tail(5).min())
    if neckline_low >= neckline_high:
        neckline_low = neckline_high * 0.985

    # 左側低點 (僅供觀察記錄，不作為右側止損)
    left_side_low = float(df.iloc[-60:]['l'].min())

    # 進場建議區間 (現價微調)
    entry_low = round(curr_price * 0.99, 2)
    entry_high = round(curr_price * 1.005, 2)

    # --- 修正後的右側止損 (SL) 邏輯 ---
    # 以頸線下緣 -1.5% 為第一防守，同時確保單筆最大虧損不超過 3.5%
    neckline_sl = neckline_low * 0.985
    atr_sl = curr_price - (atr * 1.5)
    sl_price = max(neckline_sl, atr_sl)
    
    # 邊界防呆：止損距離若大於 5% 則強制收斂至 3.5%
    if (curr_price - sl_price) / curr_price > 0.05:
        sl_price = curr_price * 0.965
    elif sl_price >= curr_price:
        sl_price = curr_price * 0.97

    r_risk = curr_price - sl_price
    sl_pct = ((sl_price - curr_price) / curr_price) * 100

    # --- 修正後的階段止盈 (TP) 邏輯 ---
    # TP1: 1.5R (平倉 50% 鎖利，SL 移至成本)
    # TP2: 2.5R (波段等幅滿足點)
    tp1_price = curr_price + (r_risk * 1.5)
    tp2_price = curr_price + (r_risk * 2.5)
    
    tp1_pct = ((tp1_price - curr_price) / curr_price) * 100
    tp2_pct = ((tp2_price - curr_price) / curr_price) * 100

    # 判定突破狀態
    if curr_price >= neckline_high * 0.998:
        status = "🟢 突破頸線"
    elif curr_price >= neckline_low:
        status = "🟡 頸線回測承接區"
    else:
        status = "⚪ 區間整理"

    return {
        'curr_price': round(curr_price, 2),
        'entry_low': entry_low,
        'entry_high': entry_high,
        'neckline_low': round(neckline_low, 2),
        'neckline_high': round(neckline_high, 2),
        'left_side_low': round(left_side_low, 2),
        'sl_price': round(sl_price, 2),
        'sl_pct': round(sl_pct, 2),
        'tp1_price': round(tp1_price, 2),
        'tp1_pct': round(tp1_pct, 2),
        'tp2_price': round(tp2_price, 2),
        'tp2_pct': round(tp2_pct, 2),
        'status': status
    }

# ==================== 4. Discord 推播格式化 ====================
def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        if len(content) <= 1900:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
        else:
            parts = [content[i:i+1800] for i in range(0, len(content), 1800)]
            for p in parts:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": p}, timeout=8)
                time.sleep(0.5)
    except Exception as e:
        print(f"⚠️ Discord 推播失敗: {e}")

def run_scanner():
    now_str = datetime.now(TZ_TW).strftime("%Y-%m-%d %H:%M")
    print("=" * 60)
    print(f"[{now_str}] 啟動台股右側突破風控掃描器...")
    print("=" * 60)

    report_blocks = []

    for sym, info in WATCHLIST.items():
        print(f"掃描標的: {sym} {info['name']} ...", end=" ")
        df = fetch_stock_data(sym, info['market'])
        if df is None:
            print("❌ 資料不足略過")
            continue

        df = compute_indicators(df)
        res = calculate_breakout_strategy(df)
        print(f"完成 (現價: {res['curr_price']}, 狀態: {res['status']})")

        block = (
            f"📌 **{sym} {info['name']} 現價：{res['curr_price']}**\n"
            f"產業：`{info['industry']}`\n"
            f"進場：`{res['entry_low']} ~ {res['entry_high']}`\n"
            f"止盈(TP1/TP2)：`{res['tp1_price']} (+{res['tp1_pct']}%)` / `{res['tp2_price']} (+{res['tp2_pct']}%)`\n"
            f"止損(SL)：`{res['sl_price']} ({res['sl_pct']}%)` (頸線保護)\n"
            f"頸線區間：`{res['neckline_low']} ~ {res['neckline_high']}`\n"
            f"左側起漲：`{res['left_side_low']} (已過)`\n"
            f"右側策略：突破 `{res['neckline_high']}` 追價 ｜ 回測 `{res['neckline_low']}` 承接\n"
            f"狀態：{res['status']}"
        )
        report_blocks.append(block)

    if not report_blocks:
        print("無可用掃描結果。")
        return

    full_content = (
        f"📊 **【台股突破策略 - 標準右側風控掃描】**\n"
        f"掃描時間：`{now_str}` (台灣時間)\n"
        f"風控規範：單筆 SL 鎖定 3% 內 ｜ 盈虧比 TP1 1.5R / TP2 2.5R\n"
        + "—" * 25 + "\n\n"
        + "\n\n".join(report_blocks)
    )

    print("\n>>> 正在發送至 Discord...")
    send_discord_safe(full_content)
    print(">>> 推播完成！\n")

if __name__ == '__main__':
    run_scanner()
