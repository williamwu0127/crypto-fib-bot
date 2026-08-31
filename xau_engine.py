"""
XAU/USD Dual-Track Multi-Pool Comparison Engine
- Macro 4H Track: 10% Risk | 10x Leverage | 2.0R BE -> 5.0R TP (Dominant)
- Micro 1H Track:  4% Risk |  8x Leverage | 2.0R BE -> 4.0R TP (SNR Pinbar Retest)
Comparison Modes:
1. 'ISOLATED': $100 per track (Total $200) - Risk Isolated
2. 'COMBINED': $100 Shared Dynamic Compounding Pool
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

INITIAL_PER_TRACK = 100.0
FEE_RATE = 0.0004

def format_full_num(val, max_dec=4):
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
            return None, None

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
        df_1h['d_date'] = df_1h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)
        df_1h['macro_filter'] = df_1h['d_date'].map(d_map).ffill().fillna(0)

        # 4H 指標
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr_4h = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr_4h.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        # 1H 指標
        df_1h['dc_high'] = df_1h['h'].shift(1).rolling(20).max()
        df_1h['dc_low'] = df_1h['l'].shift(1).rolling(20).min()
        tr_1h = np.maximum(df_1h['h'] - df_1h['l'], np.maximum(abs(df_1h['h'] - df_1h['c'].shift(1)), abs(df_1h['l'] - df_1h['c'].shift(1))))
        df_1h['atr'] = tr_1h.rolling(14).mean().fillna(df_1h['c'] * 0.01)

        return df_4h, df_1h
    except Exception as e:
        print("[!] 數據抓取失敗: " + str(e))
        return None, None

def run_backtest_pool(days=365, mode='COMBINED'):
    period_title = "1 年期" if days >= 365 else str(days) + " 天期"
    df_4h, df_1h = fetch_gold_data(days=days)
    if df_4h is None or df_1h is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')

    df_4h = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    df_1h = df_1h[df_1h['time'] >= start_filter_time].reset_index(drop=True)
    if df_4h.empty or df_1h.empty:
        return

    start_date = df_1h.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df_1h.iloc[-1]['time'].strftime("%Y-%m-%d")

    events = []
    for idx in range(1, len(df_4h)):
        events.append((df_4h.iloc[idx]['time'], 'TRACK_4H', idx))
    for idx in range(1, len(df_1h)):
        events.append((df_1h.iloc[idx]['time'], 'TRACK_1H', idx))
    events.sort(key=lambda x: x[0])

    if mode == 'COMBINED':
        total_wallet = float(INITIAL_PER_TRACK)
        wallets = {}
    else:
        total_wallet = 0.0
        wallets = {'TRACK_4H': float(INITIAL_PER_TRACK), 'TRACK_1H': float(INITIAL_PER_TRACK)}

    pos_4h = None
    pos_1h = None
    recent_1h_high = None
    recent_1h_low = None

    stats = {
        'TRACK_4H': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'TRACK_1H': {'trades': 0, 'wins': 0, 'pnl': 0.0}
    }

    for event_time, track_type, idx in events:
        cur_w_4h = total_wallet if mode == 'COMBINED' else wallets['TRACK_4H']
        cur_w_1h = total_wallet if mode == 'COMBINED' else wallets['TRACK_1H']

        # ---------------- 4H 長線模組 (10% 風險 / 10x 槓桿) ----------------
        if track_type == 'TRACK_4H':
            bar = df_4h.iloc[idx]
            if pos_4h is not None:
                side, entry, sl, tp, be_tgt, qty, be_done = (
                    pos_4h['side'], pos_4h['entry'], pos_4h['sl'], pos_4h['tp'],
                    pos_4h['be_target'], pos_4h['qty'], pos_4h['is_be_moved']
                )
                if side == 'LONG':
                    if not be_done and bar['h'] >= be_tgt:
                        pos_4h['sl'] = entry
                        pos_4h['is_be_moved'] = True
                    if bar['l'] <= pos_4h['sl']:
                        pnl = qty * (pos_4h['sl'] - entry) - qty * (entry + pos_4h['sl']) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_4H'] += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_4H']['wins'] += 1
                        pos_4h = None
                    elif bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_4H'] += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['wins'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        pos_4h = None
                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos_4h['sl'] = entry
                        pos_4h['is_be_moved'] = True
                    if bar['h'] >= pos_4h['sl']:
                        pnl = qty * (entry - pos_4h['sl']) - qty * (entry + pos_4h['sl']) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_4H'] += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_4H']['wins'] += 1
                        pos_4h = None
                    elif bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_4H'] += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['wins'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        pos_4h = None

            cur_w_4h = total_wallet if mode == 'COMBINED' else wallets['TRACK_4H']
            if pos_4h is None and cur_w_4h > 5.0:
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
                    qty = (cur_w_4h * 0.10) / risk_dist
                    if (qty * entry) > (cur_w_4h * 10.0):
                        qty = (cur_w_4h * 10.0) / entry
                    pos_4h = {
                        'side': sig, 'entry': entry, 'sl': sl,
                        'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                    }

        # ---------------- 1H 短線模組 (4% 風險 / 8x 槓桿) ----------------
        elif track_type == 'TRACK_1H':
            bar = df_1h.iloc[idx]
            prev_bar = df_1h.iloc[idx - 1]

            if pos_1h is not None:
                side, entry, sl, tp, be_tgt, qty, be_done = (
                    pos_1h['side'], pos_1h['entry'], pos_1h['sl'], pos_1h['tp'],
                    pos_1h['be_target'], pos_1h['qty'], pos_1h['is_be_moved']
                )
                if side == 'LONG':
                    if not be_done and bar['h'] >= be_tgt:
                        pos_1h['sl'] = entry
                        pos_1h['is_be_moved'] = True
                    if bar['l'] <= pos_1h['sl']:
                        pnl = qty * (pos_1h['sl'] - entry) - qty * (entry + pos_1h['sl']) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_1H'] += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_1H']['wins'] += 1
                        pos_1h = None
                    elif bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_1H'] += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['wins'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        pos_1h = None
                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos_1h['sl'] = entry
                        pos_1h['is_be_moved'] = True
                    if bar['h'] >= pos_1h['sl']:
                        pnl = qty * (entry - pos_1h['sl']) - qty * (entry + pos_1h['sl']) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_1H'] += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_1H']['wins'] += 1
                        pos_1h = None
                    elif bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        if mode == 'COMBINED': total_wallet += pnl
                        else: wallets['TRACK_1H'] += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['wins'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        pos_1h = None

            if prev_bar['c'] > prev_bar['dc_high']:
                recent_1h_high = prev_bar['dc_high']
            if prev_bar['c'] < prev_bar['dc_low']:
                recent_1h_low = prev_bar['dc_low']

            hour_utc = bar['time'].hour
            is_active_session = 6 <= hour_utc <= 20

            cur_w_1h = total_wallet if mode == 'COMBINED' else wallets['TRACK_1H']
            if pos_1h is None and cur_w_1h > 5.0 and is_active_session:
                trend = bar['macro_filter']
                atr_val = bar['atr']
                body = abs(bar['c'] - bar['o'])
                lower_shadow = min(bar['c'], bar['o']) - bar['l']
                upper_shadow = bar['h'] - max(bar['c'], bar['o'])
                sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

                if trend == 1 and (pos_4h is None or pos_4h['side'] == 'LONG') and recent_1h_high is not None:
                    retest_top = recent_1h_high + (atr_val * 0.6)
                    is_bull_pinbar = (lower_shadow >= 1.2 * body) and (bar['c'] >= (bar['h'] + bar['l']) / 2)
                    if (bar['l'] <= retest_top) and (bar['c'] > recent_1h_high) and is_bull_pinbar:
                        sig, entry = 'LONG', bar['c']
                        sl = bar['l'] - (atr_val * 0.9)
                        risk_dist = entry - sl
                        if risk_dist > (atr_val * 0.35):
                            be_tgt = entry + (risk_dist * 2.0)
                            tp = entry + (risk_dist * 4.0)
                            recent_1h_high = None

                elif trend == -1 and (pos_4h is None or pos_4h['side'] == 'SHORT') and recent_1h_low is not None:
                    retest_bot = recent_1h_low - (atr_val * 0.6)
                    is_bear_pinbar = (upper_shadow >= 1.2 * body) and (bar['c'] <= (bar['h'] + bar['l']) / 2)
                    if (bar['h'] >= retest_bot) and (bar['c'] < recent_1h_low) and is_bear_pinbar:
                        sig, entry = 'SHORT', bar['c']
                        sl = bar['h'] + (atr_val * 0.9)
                        risk_dist = sl - entry
                        if risk_dist > (atr_val * 0.35):
                            be_tgt = entry - (risk_dist * 2.0)
                            tp = entry - (risk_dist * 4.0)
                            recent_1h_low = None

                if sig and risk_dist > 0:
                    qty = (cur_w_1h * 0.04) / risk_dist
                    if (qty * entry) > (cur_w_1h * 8.0):
                        qty = (cur_w_1h * 8.0) / entry
                    pos_1h = {
                        'side': sig, 'entry': entry, 'sl': sl,
                        'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                    }

    # 輸出報表
    total_trades = stats['TRACK_4H']['trades'] + stats['TRACK_1H']['trades']
    total_wins = stats['TRACK_4H']['wins'] + stats['TRACK_1H']['wins']
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0

    if mode == 'COMBINED':
        total_roi = ((total_wallet - INITIAL_PER_TRACK) / INITIAL_PER_TRACK) * 100
        mode_title = "【雙軌合併共享複利池 (長線 10% / 短線 4%)】"
        init_str = "$" + format_full_num(INITIAL_PER_TRACK) + " USD"
        final_str = "$" + format_full_num(total_wallet, 2) + " USD (" + ("%+0.2f" % total_roi) + "%)"
    else:
        tot_final = wallets['TRACK_4H'] + wallets['TRACK_1H']
        total_roi = ((tot_final - 200.0) / 200.0) * 100
        mode_title = "【雙軌獨立分池帳戶 (各 $100 完全隔離)】"
        init_str = "$200.00 USD (長線 $100 / 短線 $100)"
        w_4h_str = "%.2f" % wallets['TRACK_4H']
        w_1h_str = "%.2f" % wallets['TRACK_1H']
        final_str = "$" + format_full_num(tot_final, 2) + " USD (" + ("%+0.2f" % total_roi) + "%)\n(各軌結餘: 長線4H=$" + w_4h_str + " \vert{} 短線1H=$" + w_1h_str + ")"

    track_lines = []
    for t_key, name in [('TRACK_4H', '4H 長線波段 (10%風險 / 10x槓桿 / 5.0R)'),
                        ('TRACK_1H', '1H 歐美短線 ( 4%風險 /  8x槓桿 / 4.0R全平)')]:
        st = stats[t_key]
        c, w, pnl = st['trades'], st['wins'], st['pnl']
        wr = (w / c * 100) if c > 0 else 0.0
        pnl_str = "%+0.2f" % pnl
        wr_str = "%5.2f" % wr
        track_lines.append("• " + name + "\n  └ 交易: " + str(c).rjust(2) + "次 | 勝率: " + wr_str + "% | 收益貢獻: " + pnl_str)

    report_text = (
        "```text\n"
        + "判定邏輯: " + mode_title + "\n"
        + "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        + "初始資金: " + init_str + "\n"
        + "最終結餘: " + final_str + "\n"
        + "總交易次數: " + str(total_trades) + " 次 | 綜合勝率: " + ("%.2f" % overall_wr) + "%\n"
        + "----------------------------------------------------\n"
        + "\n".join(track_lines) + "\n"
        + "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_backtest_pool(days=30, mode='ISOLATED')
    time.sleep(2)
    run_backtest_pool(days=365, mode='ISOLATED')
    time.sleep(2)
    run_backtest_pool(days=30, mode='COMBINED')
    time.sleep(2)
    run_backtest_pool(days=365, mode='COMBINED')
