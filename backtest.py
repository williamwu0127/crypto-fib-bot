"""
Multi-Asset Quantitative Backtest Engine (30D & 365D - Separated Capital Pools)
============================================================
【策略架構調整】
- Crypto 資金池 (BTC/ETH): 獨立 $100 USDT | 1D EMA50 -> 4H EMA趨勢 -> 15m 支撐回踩
- XAU 資金池 (黃金): 獨立 $100 USDT | 1D MA60 -> 4H 唐奇安突破 (高 RR 獵人模式)
============================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS_CRYPTO = {
    'BTC': {'s': 'BTCUSDT', 'interval': '15m'},
    'ETH': {'s': 'ETHUSDT', 'interval': '15m'}
}

SYMBOLS_GOLD = {
    'XAU': {'s': 'PAXGUSDT', 'interval': '4h'}
}

INITIAL_WALLET = 100.0
FEE_RATE = 0.0004

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

def fetch_binance_klines(symbol, interval, days=365):
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    all_klines = []
    curr_start = start_ms
    
    step_ms = (15 * 60 * 1000) if interval == '15m' else (4 * 60 * 60 * 1000)
    if interval == '1d':
        step_ms = 24 * 60 * 60 * 1000

    while curr_start < now_ms:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            all_klines.extend(res)
            curr_start = res[-1][0] + step_ms
            time.sleep(0.03)
        except Exception:
            break

    if len(all_klines) > 0:
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
        for col in ['o', 'h', 'l', 'c', 'v']:
            df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
    return None

def run_backtest_period(days=365):
    period_title = f"{days} 天期獨立資金池回測"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】...")
    print(f"==================================================")

    # 1. 黃金獨立池回測
    gold_wallet = float(INITIAL_WALLET)
    gold_trades = []
    for sym, cfg in SYMBOLS_GOLD.items():
        df_4h = fetch_binance_klines(cfg['s'], '4h', days=days + 30)
        df_1d = fetch_binance_klines(cfg['s'], '1d', days=days + 60)
        if df_4h is None or df_1d is None:
            continue

        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.set_index('d_date')['c'].gt(df_1d.set_index('d_date')['ma60']).to_dict()

        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_4h['macro_bull'] = df_4h['d_date'].map(d_map).ffill().fillna(True)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        pos = None
        for i in range(25, len(df_4h)):
            bar = df_4h.iloc[i]
            if pos is not None:
                side, entry, sl, tp, be_tgt, qty, be_done = pos['side'], pos['entry'], pos['sl'], pos['tp'], pos['be_target'], pos['qty'], pos['is_be_moved']
                if side == 'LONG':
                    if not be_done and bar['h'] >= be_tgt:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True
                    if bar['l'] <= pos['sl']:
                        pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                        gold_wallet += pnl
                        gold_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        gold_wallet += pnl
                        gold_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True
                    if bar['h'] >= pos['sl']:
                        pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                        gold_wallet += pnl
                        gold_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        gold_wallet += pnl
                        gold_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue

            if pos is None and gold_wallet > 5.0:
                bull = bar['macro_bull']
                if bull and bar['c'] > bar['dc_high']:
                    entry = bar['c']
                    sl = entry - (bar['atr'] * 1.5)
                    risk_dist = entry - sl
                    if risk_dist > 0:
                        qty = (gold_wallet * 0.05) / risk_dist
                        if (qty * entry) > (gold_wallet * 10.0):
                            qty = (gold_wallet * 10.0) / entry
                        pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': entry + (risk_dist * 5.0), 'be_target': entry + (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}
                elif not bull and bar['c'] < bar['dc_low']:
                    entry = bar['c']
                    sl = entry + (bar['atr'] * 1.5)
                    risk_dist = sl - entry
                    if risk_dist > 0:
                        qty = (gold_wallet * 0.05) / risk_dist
                        if (qty * entry) > (gold_wallet * 10.0):
                            qty = (gold_wallet * 10.0) / entry
                        pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': entry - (risk_dist * 5.0), 'be_target': entry - (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}

    # 2. 加密貨幣獨立池回測 (BTC/ETH 採優化回踩支撐架構)
    crypto_wallet = float(INITIAL_WALLET)
    crypto_trades = []
    for sym, cfg in SYMBOLS_CRYPTO.items():
        df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
        df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 30)
        df_1d  = fetch_binance_klines(cfg['s'], '1d', days=days + 60)
        if df_15m is None or df_4h is None or df_1d is None:
            continue

        df_1d['ema50'] = df_1d['c'].ewm(span=50, adjust=False).mean()
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.set_index('d_date')['c'].ge(df_1d.set_index('d_date')['ema50']).to_dict()

        df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
        df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()
        df_4h['h_date'] = df_4h['time'].dt.floor('H')
        h4_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()

        df_15m['ema50'] = df_15m['c'].ewm(span=50, adjust=False).mean()
        df_15m['ema200'] = df_15m['c'].ewm(span=200, adjust=False).mean()
        tr = np.maximum(df_15m['h'] - df_15m['l'], np.maximum(abs(df_15m['h'] - df_15m['c'].shift(1)), abs(df_15m['l'] - df_15m['c'].shift(1))))
        df_15m['atr'] = tr.rolling(14).mean().fillna(df_15m['c'] * 0.01)

        pos = None
        for i in range(30, len(df_15m)):
            bar = df_15m.iloc[i]
            if pos is not None:
                side, entry, sl, tp, qty = pos['side'], pos['entry'], pos['sl'], pos['tp'], pos['qty']
                if side == 'LONG':
                    if bar['l'] <= sl:
                        pnl = qty * (sl - entry) - qty * (entry + sl) * FEE_RATE
                        crypto_wallet += pnl
                        crypto_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        crypto_wallet += pnl
                        crypto_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                elif side == 'SHORT':
                    if bar['h'] >= sl:
                        pnl = qty * (entry - sl) - qty * (entry + sl) * FEE_RATE
                        crypto_wallet += pnl
                        crypto_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        crypto_wallet += pnl
                        crypto_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue

            if pos is None and crypto_wallet > 5.0:
                t_day = bar['time'].floor('D')
                t_hour = bar['time'].floor('H')
                d1_bull = d_map.get(t_day, True)
                h4_bull = h4_map.get(t_hour, True)

                sub = df_15m.iloc[i-20:i+1]
                h, l = sub['h'].max(), sub['l'].min()
                wave = h - l
                if wave > 0 and (wave / l) >= 0.008:
                    fib_0618_l = h - (wave * 0.618)
                    fib_0618_s = l + (wave * 0.618)
                    if d1_bull and h4_bull and (bar['c'] >= bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002):
                        entry = bar['c']
                        sl = min(l, entry - (bar['atr'] * 1.5))
                        risk_dist = abs(entry - sl)
                        if risk_dist > 0:
                            qty = (crypto_wallet * 0.01) / risk_dist
                            tp = entry + (risk_dist * 2.5)
                            pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': tp, 'qty': qty}
                    elif not d1_bull and not h4_bull and (bar['c'] <= bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998):
                        entry = bar['c']
                        sl = max(h, entry + (bar['atr'] * 1.5))
                        risk_dist = abs(entry - sl)
                        if risk_dist > 0:
                            qty = (crypto_wallet * 0.01) / risk_dist
                            tp = entry - (risk_dist * 2.5)
                            pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': tp, 'qty': qty}

    all_trades = gold_trades + crypto_trades
    total_trades = len(all_trades)
    win_trades = sum(1 for t in all_trades if t['pnl'] > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0

    report = (
        f"```text\n"
        f"【獨立資金池回測報告 - {period_title}】\n"
        f"----------------------------------------------------\n"
        f"資金池配置 ($100 各自獨立):\n"
        f" - Crypto 池 (BTC/ETH): 結餘 ${crypto_wallet:.2f} ({((crypto_wallet-INITIAL_WALLET)/INITIAL_WALLET)*100:+.2f}%)\n"
        f" - XAU 池 (黃金): 結餘 ${gold_wallet:.2f} ({((gold_wallet-INITIAL_WALLET)/INITIAL_WALLET)*100:+.2f}%)\n"
        f"----------------------------------------------------\n"
        f"總成交次數: {total_trades} 筆 | 總勝率: {win_rate:.2f}%\n"
        f"================================================----\n"
        f"各標的績效統計:\n"
    )

    for sym, wallet_val in [('BTC', crypto_wallet), ('ETH', crypto_wallet), ('XAU', gold_wallet)]:
        sym_trades = [t for t in all_trades if t['sym'] == sym]
        t_cnt = len(sym_trades)
        t_wins = sum(1 for t in sym_trades if t['pnl'] > 0)
        t_wr = (t_wins / t_cnt * 100) if t_cnt > 0 else 0.0
        t_pnl = sum(t['pnl'] for t in sym_trades)
        report += f" - {sym.ljust(4)} | 次數: {str(t_cnt).ljust(3)} 筆 | 勝率: {t_wr:6.2f}% | 淨利: {t_pnl:+6.2f} USDT\n"
    
    report += "
