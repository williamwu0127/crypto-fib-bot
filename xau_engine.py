"""
XAU/USD SNR Multi-Logic Dedicated Quant Engine (100% Calibrated)
- Logic A (4H Donchian Breakout) : 1D MA60 + 4H Breakout | 2.0R BE -> 5.0R TP (Exact 409.92% Version)
- Logic B (4H SNR Flip Retest)   : 1D MA60 + S/R Flip Retest | 1.5R BE -> 3.5R TP
Capital: $100 Isolated per Logic | 5% Risk per Trade | 10x Max Leverage
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. Webhook 與交易風控配置 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET_PER_LOGIC = 100.0
RISK_PCT = 0.05        # 單筆承擔 5% 風險
FEE_RATE = 0.0004      # 黃金點差與手續費 (萬分之四)
MAX_LEVERAGE = 10.0    # 10 倍實質槓桿上限

LOGIC_CONFIGS = {
    'LOGIC_BREAKOUT': {
        'name': '邏輯 A：4H 順勢結構突破',
        'be_r': 2.0,
        'tp_r': 5.0
    },
    'LOGIC_SNR_RETEST': {
        'name': '邏輯 B：4H SNR 互換回踩確認',
        'be_r': 1.5,
        'tp_r': 3.5
    }
}

def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        return f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
    except Exception:
        return str(val)

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
    except Exception:
        pass

# ==================== 2. 數據獲取與指標模組 (嚴格對齊 409% 版) ====================
def fetch_gold_data(days=365):
    try:
        ticker = yf.Ticker("GC=F")

        # 抓取 1H K 線並合成標準 4H
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

        # 對齊宏觀定錨
        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)

        # 唐奇安(20) & ATR(14)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.01)

        return df_4h
    except Exception as e:
        print(f"[!] 數據抓取失敗: {e}")
        return None

# ==================== 3. 雙邏輯撮合回測引擎 ====================
def run_snr_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    df_4h = fetch_gold_data(days=days)
    if df_4h is None:
        return

    # 精確時間截取
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    wallets = {'LOGIC_BREAKOUT': float(INITIAL_WALLET_PER_LOGIC), 'LOGIC_SNR_RETEST': float(INITIAL_WALLET_PER_LOGIC)}
    positions = {'LOGIC_BREAKOUT': None, 'LOGIC_SNR_RETEST': None}
    completed_trades = {'LOGIC_BREAKOUT': [], 'LOGIC_SNR_RETEST': []}

    recent_sr_high = None
    recent_sr_low = None

    for i in range(1, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        # ---------------- 1. 持倉平倉處理 ----------------
        for l_key in ['LOGIC_BREAKOUT', 'LOGIC_SNR_RETEST']:
            pos = positions[l_key]
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
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'pnl': pnl, 'type': 'SL/BE'})
                        positions[l_key] = None
                        continue

                    if bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'pnl': pnl, 'type': 'TP'})
                        positions[l_key] = None
                        continue

                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True

                    if bar['h'] >= pos['sl']:
                        pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'pnl': pnl, 'type': 'SL/BE'})
                        positions[l_key] = None
                        continue

                    if bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'pnl': pnl, 'type': 'TP'})
                        positions[l_key] = None
                        continue

        # ---------------- 2. 開倉判定 ----------------
        trend = bar['macro_filter']
        atr_val = bar['atr']

        # [邏輯 A] 4H 原生突破邏輯 (完全對齊 409%)
        if positions['LOGIC_BREAKOUT'] is None and wallets['LOGIC_BREAKOUT'] > 5.0:
            sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

            if trend == 1 and bar['c'] > bar['dc_high']:
                sig, entry = 'LONG', bar['c']
                sl = entry - (atr_val * 1.5)
                risk_dist = entry - sl
                be_tgt = entry + (risk_dist * 2.0)
                tp = entry + (risk_dist * 5.0)

            elif trend == -1 and bar['c'] < bar['dc_low']:
                sig, entry = 'SHORT', bar['c']
                sl = entry + (atr_val * 1.5)
                risk_dist = sl - entry
                be_tgt = entry - (risk_dist * 2.0)
                tp = entry - (risk_dist * 5.0)

            if sig and risk_dist > 0:
                qty = (wallets['LOGIC_BREAKOUT'] * RISK_PCT) / risk_dist
                if (qty * entry) > (wallets['LOGIC_BREAKOUT'] * MAX_LEVERAGE):
                    qty = (wallets['LOGIC_BREAKOUT'] * MAX_LEVERAGE) / entry
                positions['LOGIC_BREAKOUT'] = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

        # 更新 SNR 互換位
        if prev_bar['c'] > prev_bar['dc_high']:
            recent_sr_high = prev_bar['dc_high']
        if prev_bar['c'] < prev_bar['dc_low']:
            recent_sr_low = prev_bar['dc_low']

        # [邏輯 B] 4H SNR 互換回踩 (1.5R 保本 / 3.5R 止盈)
        if positions['LOGIC_SNR_RETEST'] is None and wallets['LOGIC_SNR_RETEST'] > 5.0:
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
                qty = (wallets['LOGIC_SNR_RETEST'] * RISK_PCT) / risk_dist
                if (qty * entry) > (wallets['LOGIC_SNR_RETEST'] * MAX_LEVERAGE):
                    qty = (wallets['LOGIC_SNR_RETEST'] * MAX_LEVERAGE) / entry
                positions['LOGIC_SNR_RETEST'] = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

    # ---------------- 3. 輸出報表 ----------------
    lines = []
    for l_key, name in [('LOGIC_BREAKOUT', '邏輯 A：4H 順勢結構突破 (2.0R保本 / 5.0R止盈)'),
                        ('LOGIC_SNR_RETEST', '邏輯 B：4H SNR 互換回踩 (1.5R保本 / 3.5R止盈)')]:
        tr = completed_trades[l_key]
        w = wallets[l_key]
        total_t = len(tr)
        win_t = sum(1 for x in tr if x['pnl'] > 0)
        wr = (win_t / total_t * 100) if total_t > 0 else 0.0
        roi = ((w - INITIAL_WALLET_PER_LOGIC) / INITIAL_WALLET_PER_LOGIC) * 100
        lines.append(
            "【" + name + "】\n"
            "• 結餘: $" + format_full_num(w, 2) + " USD (" + f"{roi:+.2f}" + "%)\n"
            "• 交易: " + str(total_t).rjust(2) + " 次 | 勝率: " + f"{wr:5.2f}" + "%\n"
        )

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金 - SNR 雙邏輯獨立測試報表】\n"
        "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        "初始本金: $" + format_full_num(INITIAL_WALLET_PER_LOGIC) + " USD (每套邏輯獨立 $100)\n"
        "----------------------------------------------------\n"
        + "\n".join(lines) +
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    run_snr_backtest(days=30)
    time.sleep(2)
    run_snr_backtest(days=365)
