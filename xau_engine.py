"""
XAU/USD SNR Multi-Logic Dedicated Quant Engine
- Logic A: 4H Donchian Breakout (Exact 409.92% Original Match) | 2.0R BE -> 5.0R TP
- Logic B: 4H SNR Flip Retest   | 1.5R BE -> 3.5R TP
Capital: $100 Isolated per Logic | 5% Risk per Trade | 10x Max Leverage
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ==================== 1. Webhook 與交易風控配置 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.05
FEE_RATE = 0.0004
MAX_LEVERAGE = 10.0

def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        return f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
    except Exception:
        return str(val)

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

# ==================== 2. 原版黃金數據與指標計算 ====================
def get_gold_dataframe(days=365):
    ticker = yf.Ticker("GC=F")
    
    # 抓取 1H 並合成標準 4H K 線
    df_1h = ticker.history(period="2y", interval="1h").reset_index()
    if df_1h.empty:
        return None
    date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
    df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
    df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
    df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)
    
    df_4h = df_1h.set_index('time').resample('4h').agg({
        'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
    }).dropna().reset_index()

    # 抓取日線 MA60
    df_1d = ticker.history(period="2y", interval="1d").reset_index()
    date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
    df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
    df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
    df_1d['ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

    df_4h['d_date'] = df_4h['time'].dt.floor('D')
    df_1d['d_date'] = df_1d['time'].dt.floor('D')
    d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
    df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)

    # 4H 唐奇安(20) & ATR(14)
    df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
    df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
    tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
    df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

    return df_4h

# ==================== 3. 獨立回測撮合器 ====================
def run_exact_logic_a(df):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []

    for i in range(1, len(df)):
        bar = df.iloc[i]
        if pos is not None:
            side, entry, sl, tp, be_tgt, qty, be_done = (
                pos['side'], pos['entry'], pos['sl'], pos['tp'],
                pos['be_target'], pos['qty'], pos['is_be_moved']
            )
            if side == 'LONG':
                if not be_done and bar['h'] >= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True
                if bar['l'] <= pos['sl']:
                    pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
            elif side == 'SHORT':
                if not be_done and bar['l'] <= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True
                if bar['h'] >= pos['sl']:
                    pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

        if pos is None and wallet > 5.0:
            trend = bar['macro_filter']
            sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0
            if trend == 1 and bar['c'] > bar['dc_high']:
                sig, entry = 'LONG', bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_tgt = entry + (risk_dist * 2.0)
                tp = entry + (risk_dist * 5.0)
            elif trend == -1 and bar['c'] < bar['dc_low']:
                sig, entry = 'SHORT', bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_tgt = entry - (risk_dist * 2.0)
                tp = entry - (risk_dist * 5.0)

            if sig and risk_dist > 0:
                qty = (wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (wallet * MAX_LEVERAGE):
                    qty = (wallet * MAX_LEVERAGE) / entry
                pos = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100
    return wallet, roi_pct, total_trades, win_rate

def run_exact_logic_b(df):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []
    recent_sr_high = None
    recent_sr_low = None

    for i in range(1, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        if pos is not None:
            side, entry, sl, tp, be_tgt, qty, be_done = (
                pos['side'], pos['entry'], pos['sl'], pos['tp'],
                pos['be_target'], pos['qty'], pos['is_be_moved']
            )
            if side == 'LONG':
                if not be_done and bar['h'] >= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True
                if bar['l'] <= pos['sl']:
                    pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
            elif side == 'SHORT':
                if not be_done and bar['l'] <= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True
                if bar['h'] >= pos['sl']:
                    pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue
                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

        # 更新支撐阻力位
        if prev_bar['c'] > prev_bar['dc_high']:
            recent_sr_high = prev_bar['dc_high']
        if prev_bar['c'] < prev_bar['dc_low']:
            recent_sr_low = prev_bar['dc_low']

        if pos is None and wallet > 5.0:
            trend = bar['macro_filter']
            atr_val = bar['atr']
            sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

            if trend == 1 and recent_sr_high is not None:
                retest_top = recent_sr_high + (atr_val * 0.5)
                if (bar['l'] <= retest_top) and (bar['c'] > recent_sr_high) and (bar['c'] > bar['o']):
                    sig, entry = 'LONG', bar['c']
                    sl = bar['l'] - (atr_val * 0.8)
                    risk_dist = entry - sl
                    if risk_dist > (atr_val * 0.4):
                        be_tgt = entry + (risk_dist * 1.5)
                        tp = entry + (risk_dist * 3.5)
                        recent_sr_high = None

            elif trend == -1 and recent_sr_low is not None:
                retest_bot = recent_sr_low - (atr_val * 0.5)
                if (bar['h'] >= retest_bot) and (bar['c'] < recent_sr_low) and (bar['c'] < bar['o']):
                    sig, entry = 'SHORT', bar['c']
                    sl = bar['h'] + (atr_val * 0.8)
                    risk_dist = sl - entry
                    if risk_dist > (atr_val * 0.4):
                        be_tgt = entry - (risk_dist * 1.5)
                        tp = entry - (risk_dist * 3.5)
                        recent_sr_low = None

            if sig and risk_dist > 0:
                qty = (wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (wallet * MAX_LEVERAGE):
                    qty = (wallet * MAX_LEVERAGE) / entry
                pos = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100
    return wallet, roi_pct, total_trades, win_rate

# ==================== 4. 主執行程序 ====================
def run_snr_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    df_4h = get_gold_dataframe(days=days)
    if df_4h is None:
        return

    # 精確錨定回測時間
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    w_a, roi_a, t_a, wr_a = run_exact_logic_a(df.copy())
    w_b, roi_b, t_b, wr_b = run_exact_logic_b(df.copy())

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金 - SNR 雙邏輯獨立測試報表】\n"
        "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        "初始本金: $" + format_full_num(INITIAL_WALLET) + " USD (每套邏輯獨立 $100)\n"
        "----------------------------------------------------\n"
        "【邏輯 A：4H 順勢結構突破 (2.0R保本 / 5.0R止盈)】\n"
        "• 結餘: $" + format_full_num(w_a, 2) + " USD (" + f"{roi_a:+.2f}" + "%)\n"
        "• 交易: " + str(t_a).rjust(2) + " 次 | 勝率: " + f"{wr_a:5.2f}" + "%\n\n"
        "【邏輯 B：4H SNR 互換回踩 (1.5R保本 / 3.5R止盈)】\n"
        "• 結餘: $" + format_full_num(w_b, 2) + " USD (" + f"{roi_b:+.2f}" + "%)\n"
        "• 交易: " + str(t_b).rjust(2) + " 次 | 勝率: " + f"{wr_b:5.2f}" + "%\n"
        "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_snr_backtest(days=30)
    time.sleep(2)
    run_snr_backtest(days=365)
