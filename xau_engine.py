"""
XAU/USD 4H Macro Trend Breakout - Leverage Sweep Engine
- Strategy: 1D MA60 + 4H Donchian(20) Breakout | 2.0R BE -> 5.0R TP
- Leverages Tested: 3x, 5x, 10x, 50x, 100x
- Risk per Trade: 5% (Position sized by Risk / Distance, capped by Leverage)
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.05
FEE_RATE = 0.0004
LEVERAGE_LIST = [3.0, 5.0, 10.0, 50.0, 100.0]

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

def fetch_gold_data(days=365):
    try:
        period_str = str(days + 90) + "d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        df_4h = df_1h.set_index('time').resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)

        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr_4h = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr_4h.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        return df_4h
    except Exception as e:
        print("[!] 數據抓取失敗: " + str(e))
        return None

def simulate_single_leverage(df, max_lev):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []
    is_liquidated = False

    for i in range(1, len(df)):
        if wallet <= 1.0:
            is_liquidated = True
            break

        bar = df.iloc[i]

        # 1. 撮合平倉
        if pos is not None:
            side, entry, sl, tp, be_tgt, qty, be_done = (
                pos['side'], pos['entry'], pos['sl'], pos['tp'],
                pos['be_target'], pos['qty'], pos['is_be_moved']
            )

            # 強平線判定 (本金虧損達 90% 即強制清算)
            if side == 'LONG':
                liq_price = entry - (wallet * 0.90 / qty)
                if bar['l'] <= liq_price:
                    wallet = 0.0
                    is_liquidated = True
                    trades.append(-INITIAL_WALLET)
                    break

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
                liq_price = entry + (wallet * 0.90 / qty)
                if bar['h'] >= liq_price:
                    wallet = 0.0
                    is_liquidated = True
                    trades.append(-INITIAL_WALLET)
                    break

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

        # 2. 開倉信號
        if pos is None and wallet > 5.0:
            trend = bar['macro_filter']
            atr_val = bar['atr']
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
                # 以 5% 風險定部位，並受最大槓桿約束
                qty = (wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (wallet * max_lev):
                    qty = (wallet * max_lev) / entry

                pos = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    return wallet, roi_pct, total_trades, win_rate, is_liquidated

def run_leverage_sweep(days=365):
    period_title = "1 年期" if days >= 365 else str(days) + " 天期"
    df_4h = fetch_gold_data(days=days)
    if df_4h is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    result_lines = []
    for lev in LEVERAGE_LIST:
        wallet, roi_pct, trades, wr, is_liq = simulate_single_leverage(df.copy(), lev)
        lev_str = (str(int(lev)) + "x").rjust(4)
        if is_liq or wallet <= 1.0:
            status_str = "【爆倉破產 LIQUIDATED】"
            res_str = "結餘: $0.00 (-100.00%) | 交易: " + str(trades).rjust(2) + "次"
        else:
            status_str = "結餘: $" + format_full_num(wallet, 2).rjust(8) + " USD (" + ("%+0.2f" % roi_pct).rjust(8) + "%)"
            res_str = status_str + " | 交易: " + str(trades).rjust(2) + "次 | 勝率: " + ("%5.2f" % wr) + "%"

        result_lines.append("• 槓桿 " + lev_str + " │ " + res_str)

    report_text = (
        "```text\n"
        + "【XAU/USD 黃金 4H 長線波段 - 多槓桿倍率壓力回測】\n"
        + "策略邏輯: 1D MA60 + 4H 唐奇安(20) 突破 (2.0R保本 / 5.0R止盈)\n"
        + "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        + "初始本金: $" + format_full_num(INITIAL_WALLET) + " USD (每種槓桿獨立起始)\n"
        + "單筆風控: 固定 5% 帳戶風險 (受槓桿上限約束)\n"
        + "------------------------------------------------------------\n"
        + "\n".join(result_lines) + "\n"
        + "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_leverage_sweep(days=30)
    time.sleep(2)
    run_leverage_sweep(days=365)
