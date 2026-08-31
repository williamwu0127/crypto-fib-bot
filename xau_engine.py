"""
XAU/USD SMC Pullback Strategy (Python Replication Engine)
- Pine Script Logic:
    Trend: Close > EMA(21) & Close > Previous Daily Low
    Entry: Low <= EMA(21) and Close > Open and Close > High[1]
    SL: Close - 2.0 * ATR(14)
    TP1: 1.5R (Exit 50%)
    TP2: 2.5R (Exit 50%)
- Comparison: 'Original Pine (No BE)' vs 'Optimized (TP1 with BE)'
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. Webhook 與交易配置 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.05        # 單筆承擔 5% 風險
FEE_RATE = 0.0004      # 點差與手續費
MAX_LEVERAGE = 10.0    # 10 倍實質槓桿

def format_full_num(val, max_dec=2):
    try:
        f = float(val)
        return ("{:.%df}" % max_dec).format(f).rstrip('0').rstrip('.')
    except Exception:
        return str(val)

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

# ==================== 2. 數據獲取與 SMC 指標計算 ====================
def fetch_smc_data(days=365):
    try:
        period_str = str(days + 90) + "d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        # 抓取 1H K 線
        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        # 抓取日線前一日低點 (Previous Daily Low)
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Low': 'daily_l'}, inplace=True)
        df_1d['prev_daily_low'] = df_1d['daily_l'].shift(1)

        # 映射至 1H
        df_1h['d_date'] = df_1h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['prev_daily_low'].to_dict()
        df_1h['daily_low'] = df_1h['d_date'].map(d_map).ffill()

        # EMA(21)
        df_1h['ema21'] = df_1h['c'].ewm(span=21, adjust=False).mean()

        # ATR(14)
        tr = np.maximum(df_1h['h'] - df_1h['l'], np.maximum(abs(df_1h['h'] - df_1h['c'].shift(1)), abs(df_1h['l'] - df_1h['c'].shift(1))))
        df_1h['atr'] = tr.rolling(14).mean().fillna(df_1h['c'] * 0.01)

        return df_1h
    except Exception as e:
        print("[!] 數據抓取失敗: " + str(e))
        return None

# ==================== 3. 撮合回測引擎 (支援保本與不保本模式) ====================
def simulate_smc_pullback(df, enable_be=False):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []

    for i in range(1, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        # 1. 持倉處理 (TP1 50% / TP2 50%)
        if pos is not None:
            entry, sl, tp1, tp2, qty, is_tp1_hit = (
                pos['entry'], pos['sl'], pos['tp1'], pos['tp2'],
                pos['qty'], pos['is_tp1_hit']
            )

            # 達到 TP1 (1.5R) -> 平倉 50%
            if not is_tp1_hit and bar['h'] >= tp1:
                half_qty = qty * 0.5
                pnl_half = half_qty * (tp1 - entry) - half_qty * (entry + tp1) * FEE_RATE
                wallet += pnl_half
                pos['qty'] = qty * 0.5
                pos['is_tp1_hit'] = True
                if enable_be:
                    pos['sl'] = entry  # 優化版：移至保本

            # 觸發止損
            if bar['l'] <= pos['sl']:
                rem_qty = pos['qty']
                pnl = rem_qty * (pos['sl'] - entry) - rem_qty * (entry + pos['sl']) * FEE_RATE
                wallet += pnl
                trades.append(pnl)
                pos = None
                continue

            # 達到 TP2 (2.5R) -> 結清剩餘 50%
            if bar['h'] >= tp2:
                rem_qty = pos['qty']
                pnl = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE
                wallet += pnl
                trades.append(pnl)
                pos = None
                continue

        # 2. 開倉判定 (Pine Script 原版條件)
        if pos is None and wallet > 5.0:
            bullish_trend = bar['c'] > bar['ema21']
            pullback_bounce = (bar['l'] <= bar['ema21']) and (bar['c'] > bar['o']) and (bar['c'] > prev_bar['h'])
            above_daily_low = bar['c'] > bar['daily_low'] if pd.notnull(bar['daily_low']) else True

            if bullish_trend and pullback_bounce and above_daily_low:
                entry = bar['c']
                sl = entry - (bar['atr'] * 2.0)  # 2.0 ATR 停損
                risk_dist = entry - sl

                if risk_dist > 0:
                    tp1 = entry + (risk_dist * 1.5)  # 1.5R
                    tp2 = entry + (risk_dist * 2.5)  # 2.5R

                    qty = (wallet * RISK_PCT) / risk_dist
                    if (qty * entry) > (wallet * MAX_LEVERAGE):
                        qty = (wallet * MAX_LEVERAGE) / entry

                    pos = {
                        'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'qty': qty, 'is_tp1_hit': False
                    }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    return wallet, roi_pct, total_trades, win_rate

# ==================== 4. 主執行程序 ====================
def run_smc_backtest(days=365):
    period_title = "1 年期" if days >= 365 else str(days) + " 天期"
    df_1h = fetch_smc_data(days=days)
    if df_1h is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df_1h[df_1h['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    w_orig, roi_orig, t_orig, wr_orig = simulate_smc_pullback(df.copy(), enable_be=False)
    w_opt, roi_opt, t_opt, wr_opt = simulate_smc_pullback(df.copy(), enable_be=True)

    report_text = (
        "```text\n"
        + "【XAU/USD 現貨黃金 - SMC 均線回踩分批止盈回測報表】\n"
        + "策略邏輯: Close>EMA21 + 回踩EMA21收陽破前高 + 2.0 ATR止損\n"
        + "階梯出場: TP1 (1.5R 出50%) / TP2 (2.5R 結清)\n"
        + "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        + "初始本金: $" + format_full_num(INITIAL_WALLET) + " USD (單筆 5% 風險 / 10x 槓桿)\n"
        + "------------------------------------------------------------\n"
        + "【模式一：原版 Pine Script (TP1 後不移保本)】\n"
        + "• 結餘: $" + format_full_num(w_orig, 2) + " USD (" + ("%+0.2f" % roi_orig) + "%)\n"
        + "• 交易: " + str(t_orig).rjust(2) + " 次 | 勝率: " + ("%5.2f" % wr_orig) + "%\n\n"
        + "【模式二：實戰優化版 (TP1 觸發後同步移保本)】\n"
        + "• 結餘: $" + format_full_num(w_opt, 2) + " USD (" + ("%+0.2f" % roi_opt) + "%)\n"
        + "• 交易: " + str(t_opt).rjust(2) + " 次 | 勝率: " + ("%5.2f" % wr_opt) + "%\n"
        + "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_smc_backtest(days=30)
    time.sleep(2)
    run_smc_backtest(days=365)
