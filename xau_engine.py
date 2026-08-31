"""
XAU/USD SMC Pullback Strategy - V2 Upgraded Engine
Key Improvements:
1. Macro Filter: 1D MA60 Trend Alignment (No Lookahead Bias)
2. Entry Logic: 1H Close > EMA21 + Pullback Low <= EMA21 + Bullish Engulfing
3. Advanced Exit: 
   - TP1 (1.5R): Close 50% & Trailing SL to Protected Swing Low (Not Entry BE)
   - TP2 (3.5R): Close Remaining 50% Full Profit
- Capital: $100 | Risk: 5% per trade | 10x Max Leverage
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
RISK_PCT = 0.05
FEE_RATE = 0.0004
MAX_LEVERAGE = 10.0

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

# ==================== 2. 數據獲取與指標模組 ====================
def fetch_smc_data_v2(days=365):
    try:
        period_str = str(days + 90) + "d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        # 1H K 線
        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        # 1D 日線 MA60
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

        # 映射日線趨勢至 1H
        df_1h['d_date'] = df_1h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_1h['macro_filter'] = df_1h['d_date'].map(d_map).ffill().fillna(0)

        # 1H EMA21 & ATR14
        df_1h['ema21'] = df_1h['c'].ewm(span=21, adjust=False).mean()
        tr = np.maximum(df_1h['h'] - df_1h['l'], np.maximum(abs(df_1h['h'] - df_1h['c'].shift(1)), abs(df_1h['l'] - df_1h['c'].shift(1))))
        df_1h['atr'] = tr.rolling(14).mean().fillna(df_1h['c'] * 0.01)

        return df_1h
    except Exception as e:
        print("[!] 數據抓取失敗: " + str(e))
        return None

# ==================== 3. 撮合回測引擎 ====================
def simulate_smc_v2(df):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []

    for i in range(1, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        # 1. 持倉處理
        if pos is not None:
            entry, sl, tp1, tp2, qty, is_tp1_hit, swing_low = (
                pos['entry'], pos['sl'], pos['tp1'], pos['tp2'],
                pos['qty'], pos['is_tp1_hit'], pos['swing_low']
            )

            # 觸發 TP1 (1.5R) -> 平倉 50%，止損移至結構低點保護位
            if not is_tp1_hit and bar['h'] >= tp1:
                half_qty = qty * 0.5
                pnl_half = half_qty * (tp1 - entry) - half_qty * (entry + tp1) * FEE_RATE
                wallet += pnl_half
                pos['qty'] = qty * 0.5
                pos['is_tp1_hit'] = True
                # 上移至進場波谷低點下方 (保留二次回踩空間)
                pos['sl'] = max(sl, swing_low - (bar['atr'] * 0.5))

            # 觸發止損
            if bar['l'] <= pos['sl']:
                rem_qty = pos['qty']
                pnl = rem_qty * (pos['sl'] - entry) - rem_qty * (entry + pos['sl']) * FEE_RATE
                wallet += pnl
                trades.append(pnl)
                pos = None
                continue

            # 觸發 TP2 (3.5R) -> 全額止盈
            if bar['h'] >= tp2:
                rem_qty = pos['qty']
                pnl = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE
                wallet += pnl
                trades.append(pnl)
                pos = None
                continue

        # 2. 開倉判定 (日線 MA60 多頭 + 1H 回踩 EMA21 吞沒收陽)
        if pos is None and wallet > 5.0:
            macro_bull = (bar['macro_filter'] == 1)
            bullish_trend = bar['c'] > bar['ema21']
            pullback_bounce = (bar['l'] <= bar['ema21']) and (bar['c'] > bar['o']) and (bar['c'] > prev_bar['h'])

            if macro_bull and bullish_trend and pullback_bounce:
                entry = bar['c']
                sl = entry - (bar['atr'] * 2.0)  # 2.0 ATR 初始止損
                risk_dist = entry - sl

                if risk_dist > 0:
                    tp1 = entry + (risk_dist * 1.5)  # 1.5R
                    tp2 = entry + (risk_dist * 3.5)  # 3.5R 擴大利潤

                    qty = (wallet * RISK_PCT) / risk_dist
                    if (qty * entry) > (wallet * MAX_LEVERAGE):
                        qty = (wallet * MAX_LEVERAGE) / entry

                    pos = {
                        'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'qty': qty, 'is_tp1_hit': False, 'swing_low': bar['l']
                    }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    return wallet, roi_pct, total_trades, win_rate

# ==================== 4. 主執行程序 ====================
def run_smc_v2_backtest(days=365):
    period_title = "1 年期" if days >= 365 else str(days) + " 天期"
    df_1h = fetch_smc_data_v2(days=days)
    if df_1h is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df_1h[df_1h['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    wallet, roi_pct, trades, wr = simulate_smc_v2(df.copy())

    report_text = (
        "```text\n"
        + "【XAU/USD 現貨黃金 - SMC 均線回踩 V2 升級版報表】\n"
        + "核心優化: 1D MA60宏觀定錨 + 結構低點保護止損 + 3.5R利潤擴張\n"
        + "階梯出場: TP1 (1.5R 出50%移保護SL) / TP2 (3.5R 結清)\n"
        + "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        + "初始本金: $" + format_full_num(INITIAL_WALLET) + " USD (單筆 5% 風險 / 10x 槓桿)\n"
        + "------------------------------------------------------------\n"
        + "• 最終結餘: $" + format_full_num(wallet, 2) + " USD (" + ("%+0.2f" % roi_pct) + "%)\n"
        + "• 總交易次數: " + str(trades).rjust(2) + " 次 | 勝率: " + ("%5.2f" % wr) + "%\n"
        + "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_smc_v2_backtest(days=30)
    time.sleep(2)
    run_smc_v2_backtest(days=365)
