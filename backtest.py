"""
Multi-Asset 365-Day Shared Pool Backtest Engine (GitHub Edition)
================================================================================
【GitHub 365 天回測專用版本 - 合併共用資金池架構】
1. 資金架構:
   - 模式: 所有標的合併共用單一 100.0 USDT 初始資金池，動態連鎖複利[cite: 2]。
   - 排序: 嚴格保持 BTC -> ETH -> SOL -> BNB -> DOGE -> XAU[cite: 2]。

2. 各幣種專屬最佳化配置:
   - BTC : 1.0% 風控 / 1x / 4H EMA20/50 + 1H FVG + 15m 斐波0.618 / 1.5R (平50%) + 3.0R (全平)[cite: 2]
   - ETH : 1.0% 風控 / 1x / 4H EMA20/50 + 1H FVG + 15m 斐波0.618 / 1.5R (平50%) + 3.0R (全平)[cite: 2]
   - SOL : 5.0% 風控 / 10x / 1H 流動性+OB+FVG+OTE / 2.0R (平50%移保本) + 5.0R (全平)[cite: 2]
   - BNB : 2.5% 風控 / 10x / 1H 流動性+OB+FVG+OTE / 2.0R (平30%移保本) + 5.0R (平70%)[cite: 2]
   - DOGE: 5.0% 風控 / 10x / 1H 流動性+OB+FVG+OTE / 2.0R (平50%移保本) + 5.0R (全平)[cite: 2]
   - XAU : 5.0% 風控 / 10x / 1D MA60 + 4H 唐奇安(20) / 1.5 ATR / 2.0R 保本 / 5.0R 全平[cite: 2]
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS_CONFIG = {
    'BTC': {
        's': 'BTCUSDT', 'interval': '15m', 'mode': 'smc_conservative',
        'lev': 1.0, 'risk': 0.01, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5
    },
    'ETH': {
        's': 'ETHUSDT', 'interval': '15m', 'mode': 'smc_conservative',
        'lev': 1.0, 'risk': 0.01, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5
    },
    'SOL': {
        's': 'SOLUSDT', 'interval': '15m', 'mode': 'ict_aggressive',
        'lev': 10.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'BNB': {
        's': 'BNBUSDT', 'interval': '15m', 'mode': 'ict_hybrid',
        'lev': 10.0, 'risk': 0.025, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.3
    },
    'DOGE': {
        's': 'DOGEUSDT', 'interval': '15m', 'mode': 'ict_aggressive',
        'lev': 10.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'XAU': {
        's': 'PAXGUSDT', 'interval': '4h', 'mode': 'gold_donchian',
        'lev': 10.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.0
    }
}

INITIAL_SHARED_WALLET = 100.0[cite: 2]
FEE_RATE = 0.0004[cite: 2]

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)[cite: 2]
        except Exception:
            pass

def fetch_binance_klines(symbol, interval, days=365):
    now_ms = int(time.time() * 1000)[cite: 2]
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)[cite: 2]
    all_klines = [][cite: 2]
    curr_start = start_ms[cite: 2]
    
    step_ms = (15 * 60 * 1000) if interval == '15m' else (60 * 60 * 1000 if interval == '1h' else (4 * 60 * 60 * 1000))[cite: 2]
    if interval == '1d':
        step_ms = 24 * 60 * 60 * 1000[cite: 2]

    while curr_start < now_ms:[cite: 2]
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"[cite: 2]
        try:
            res = requests.get(url, timeout=10).json()[cite: 2]
            if not isinstance(res, list) or len(res) == 0:[cite: 2]
                break
            all_klines.extend(res)[cite: 2]
            curr_start = res[-1][0] + step_ms[cite: 2]
            time.sleep(0.03)[cite: 2]
        except Exception:
            break

    if len(all_klines) > 0:[cite: 2]
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i'][cite: 2]
        df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])[cite: 2]
        for col in ['o', 'h', 'l', 'c', 'v']:[cite: 2]
            df[col] = df[col].astype(float)[cite: 2]
        df['time'] = pd.to_datetime(df['t'], unit='ms')[cite: 2]
        return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)[cite: 2]
    return None[cite: 2]

def run_shared_portfolio_backtest():
    days = 365[cite: 2]
    period_title = "365 天期 (各幣種專屬最佳策略 - 合併共用 100U 資金池)"
    print("\n==================================================")
    print(f">>> 開始執行【{period_title}】合併資金池回測...")
    print("==================================================")

    shared_wallet = float(INITIAL_SHARED_WALLET)[cite: 2]
    asset_performance = {}[cite: 2]
    sorted_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XAU'][cite: 2]

    for sym in sorted_symbols:[cite: 2]
        cfg = SYMBOLS_CONFIG[sym][cite: 2]
        start_wallet_for_sym = shared_wallet[cite: 2]
        completed_trades = [][cite: 2]
        print(f"執行標的: {sym.ljust(5)} | 策略模式: {cfg['mode'].ljust(16)} | 當前共用資金池: ${shared_wallet:.2f} USDT...", flush=True)[cite: 2]

        # ---------------- 1. 黃金專屬：唐奇安趨勢 ----------------
        if cfg['mode'] == 'gold_donchian':[cite: 2]
            df_4h = fetch_binance_klines(cfg['s'], '4h', days=days + 30)[cite: 2]
            df_1d = fetch_binance_klines(cfg['s'], '1d', days=days + 60)[cite: 2]
            if df_4h is None or df_1d is None:[cite: 2]
                continue

            df_1d['ma60'] = df_1d['c'].rolling(60).mean()[cite: 2]
            df_1d['d_date'] = df_1d['time'].dt.floor('D')[cite: 2]
            d_map = df_1d.set_index('d_date')['c'].gt(df_1d.set_index('d_date')['ma60']).to_dict()[cite: 2]

            df_4h['d_date'] = df_4h['time'].dt.floor('D')[cite: 2]
            df_4h['macro_bull'] = df_4h['d_date'].map(d_map).ffill().fillna(True)[cite: 2]
            df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()[cite: 2]
            df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()[cite: 2]
            tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))[cite: 2]
            df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)[cite: 2]

            pos = None[cite: 2]
            for i in range(25, len(df_4h)):[cite: 2]
                bar = df_4h.iloc[i][cite: 2]
                if pos is not None:[cite: 2]
                    side, entry, sl, tp, be_tgt, qty, be_done = pos['side'], pos['entry'], pos['sl'], pos['tp'], pos['be_target'], pos['qty'], pos['is_be_moved'][cite: 2]
                    if side == 'LONG':[cite: 2]
                        if not be_done and bar['h'] >= be_tgt:[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            pos['is_be_moved'] = True[cite: 2]
                        if bar['l'] <= pos['sl']:[cite: 2]
                            pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if bar['h'] >= tp:[cite: 2]
                            pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                    elif side == 'SHORT':[cite: 2]
                        if not be_done and bar['l'] <= be_tgt:[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            pos['is_be_moved'] = True[cite: 2]
                        if bar['h'] >= pos['sl']:[cite: 2]
                            pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if bar['l'] <= tp:[cite: 2]
                            pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue

                if pos is None and shared_wallet > 5.0:[cite: 2]
                    bull = bar['macro_bull'][cite: 2]
                    if bull and bar['c'] > bar['dc_high']:[cite: 2]
                        entry = bar['c'][cite: 2]
                        sl = entry - (bar['atr'] * 1.5)[cite: 2]
                        risk_dist = entry - sl[cite: 2]
                        if risk_dist > 0:[cite: 2]
                            qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                            if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                            pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': entry + (risk_dist * cfg['tp2_r']), 'be_target': entry + (risk_dist * cfg['tp1_r']), 'qty': qty, 'is_be_moved': False}[cite: 2]
                    elif not bull and bar['c'] < bar['dc_low']:[cite: 2]
                        entry = bar['c'][cite: 2]
                        sl = entry + (bar['atr'] * 1.5)[cite: 2]
                        risk_dist = sl - entry[cite: 2]
                        if risk_dist > 0:[cite: 2]
                            qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                            if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                            pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': entry - (risk_dist * cfg['tp2_r']), 'be_target': entry - (risk_dist * cfg['tp1_r']), 'qty': qty, 'is_be_moved': False}[cite: 2]

        # ---------------- 2. 加密貨幣：BTC / ETH 穩健 SMC (1.5R/3.0R) ----------------
        elif cfg['mode'] == 'smc_conservative':[cite: 2]
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)[cite: 2]
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)[cite: 2]
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)[cite: 2]
            if df_15m is None or df_1h is None or df_4h is None:[cite: 2]
                continue

            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()[cite: 2]
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()[cite: 2]
            df_4h['h_date'] = df_4h['time'].dt.floor('H')[cite: 2]
            h4_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()[cite: 2]

            fvg_1h_map = {}[cite: 2]
            for j in range(2, len(df_1h)):[cite: 2]
                b_curr = df_1h.iloc[j][cite: 2]
                b_prev2 = df_1h.iloc[j-2][cite: 2]
                h_time = b_curr['time'].floor('H')[cite: 2]
                bull_fvg = b_curr['l'] > b_prev2['h'][cite: 2]
                bear_fvg = b_curr['h'] < b_prev2['l'][cite: 2]
                fvg_1h_map[h_time] = {
                    'bull': bull_fvg, 'bear': bear_fvg,
                    'bull_zone': (b_prev2['h'], b_curr['l']),
                    'bear_zone': (b_curr['h'], b_prev2['l'])
                }[cite: 2]

            pos = None[cite: 2]
            for i in range(20, len(df_15m)):[cite: 2]
                bar = df_15m.iloc[i][cite: 2]
                prev_bar = df_15m.iloc[i-1][cite: 2]

                if pos is not None:[cite: 2]
                    side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit'][cite: 2]
                    if side == 'LONG':[cite: 2]
                        if bar['l'] <= sl:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty[cite: 2]
                            pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if not tp1_hit and bar['h'] >= tp1:[cite: 2]
                            pos['tp1_hit'] = True[cite: 2]
                            pnl_tp1 = (qty * cfg['tp1_ratio']) * (tp1 - entry) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp1[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            completed_trades.append({'pnl': pnl_tp1})[cite: 2]
                        if pos['tp1_hit'] and bar['h'] >= tp2:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio'])[cite: 2]
                            pnl_tp2 = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp2[cite: 2]
                            completed_trades.append({'pnl': pnl_tp2})[cite: 2]
                            pos = None[cite: 2]
                            continue
                    elif side == 'SHORT':[cite: 2]
                        if bar['h'] >= sl:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty[cite: 2]
                            pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if not tp1_hit and bar['l'] <= tp1:[cite: 2]
                            pos['tp1_hit'] = True[cite: 2]
                            pnl_tp1 = (qty * cfg['tp1_ratio']) * (entry - tp1) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp1[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            completed_trades.append({'pnl': pnl_tp1})[cite: 2]
                        if pos['tp1_hit'] and bar['l'] <= tp2:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio'])[cite: 2]
                            pnl_tp2 = rem_qty * (entry - tp2) - rem_qty * (entry + tp2) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp2[cite: 2]
                            completed_trades.append({'pnl': pnl_tp2})[cite: 2]
                            pos = None[cite: 2]
                            continue

                if pos is None and shared_wallet > 5.0:[cite: 2]
                    t_hour = bar['time'].floor('H')[cite: 2]
                    h4_bull = h4_map.get(t_hour, True)[cite: 2]
                    fvg_info = fvg_1h_map.get(t_hour, {'bull': False, 'bear': False})[cite: 2]

                    sub = df_15m.iloc[i-20:i+1][cite: 2]
                    h_wave, l_wave = sub['h'].max(), sub['l'].min()[cite: 2]
                    wave = h_wave - l_wave[cite: 2]
                    if wave > 0:[cite: 2]
                        fib_0618_l = h_wave - (wave * 0.618)[cite: 2]
                        fib_0618_s = l_wave + (wave * 0.618)[cite: 2]

                        if h4_bull and fvg_info['bull'] and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] > prev_bar['c']):[cite: 2]
                            entry = bar['c'][cite: 2]
                            sl = fvg_info['bull_zone'][0] * (1.0 - 0.002)[cite: 2]
                            risk_dist = entry - sl[cite: 2]
                            if risk_dist > 0:[cite: 2]
                                qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                                if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                    qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                                tp1 = entry + (risk_dist * cfg['tp1_r'])[cite: 2]
                                tp2 = entry + (risk_dist * cfg['tp2_r'])[cite: 2]
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}[cite: 2]
                        elif not h4_bull and fvg_info['bear'] and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] < prev_bar['c']):[cite: 2]
                            entry = bar['c'][cite: 2]
                            sl = fvg_info['bear_zone'][1] * (1.0 + 0.002)[cite: 2]
                            risk_dist = sl - entry[cite: 2]
                            if risk_dist > 0:[cite: 2]
                                qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                                if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                    qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                                tp1 = entry - (risk_dist * cfg['tp1_r'])[cite: 2]
                                tp2 = entry - (risk_dist * cfg['tp2_r'])[cite: 2]
                                pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}[cite: 2]

        # ---------------- 3. 加密貨幣：SOL / BNB / DOGE ICT Pro 體系 ----------------
        elif cfg['mode'] in ['ict_aggressive', 'ict_hybrid']:[cite: 2]
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)[cite: 2]
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)[cite: 2]
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)[cite: 2]
            if df_15m is None or df_1h is None or df_4h is None:[cite: 2]
                continue

            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()[cite: 2]
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()[cite: 2]
            df_4h['h_date'] = df_4h['time'].dt.floor('H')[cite: 2]
            h4_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()[cite: 2]

            df_1h['swing_high'] = df_1h['h'].rolling(5).max()[cite: 2]
            df_1h['swing_low']  = df_1h['l'].rolling(5).min()[cite: 2]

            h1_ict_map = {}[cite: 2]
            for j in range(3, len(df_1h)):[cite: 2]
                b_curr = df_1h.iloc[j][cite: 2]
                b_prev = df_1h.iloc[j-1][cite: 2]
                b_prev2 = df_1h.iloc[j-2][cite: 2]
                b_prev3 = df_1h.iloc[j-3][cite: 2]
                h_time = b_curr['time'].floor('H')[cite: 2]

                bull_fvg = b_curr['l'] > b_prev2['h'][cite: 2]
                bear_fvg = b_curr['h'] < b_prev2['l'][cite: 2]

                bull_ob = (b_prev['c'] < b_prev['o']) and (b_curr['c'] > b_prev['h'])[cite: 2]
                bear_ob = (b_prev['c'] > b_prev['o']) and (b_curr['c'] < b_prev['l'])[cite: 2]

                sweep_low = (b_curr['l'] < b_prev3['swing_low']) and (b_curr['c'] > b_prev3['swing_low'])[cite: 2]
                sweep_high = (b_curr['h'] > b_prev3['swing_high']) and (b_curr['c'] < b_prev3['swing_high'])[cite: 2]

                h1_ict_map[h_time] = {
                    'bull_fvg': bull_fvg, 'bear_fvg': bear_fvg,
                    'bull_ob': bull_ob,   'bear_ob': bear_ob,
                    'sweep_low': sweep_low, 'sweep_high': sweep_high,
                    'ob_bull_low': b_prev['l'],
                    'ob_bear_high': b_prev['h'],
                    'fvg_bull_zone': (b_prev2['h'], b_curr['l']) if bull_fvg else (b_prev['l'], b_curr['h']),
                    'fvg_bear_zone': (b_curr['h'], b_prev2['l']) if bear_fvg else (b_curr['l'], b_prev['h'])
                }[cite: 2]

            pos = None[cite: 2]
            for i in range(25, len(df_15m)):[cite: 2]
                bar = df_15m.iloc[i][cite: 2]
                prev_bar = df_15m.iloc[i-1][cite: 2]

                if pos is not None:[cite: 2]
                    side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit'][cite: 2]
                    if side == 'LONG':[cite: 2]
                        if bar['l'] <= sl:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty[cite: 2]
                            pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if not tp1_hit and bar['h'] >= tp1:[cite: 2]
                            pos['tp1_hit'] = True[cite: 2]
                            pnl_tp1 = (qty * cfg['tp1_ratio']) * (tp1 - entry) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp1[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            completed_trades.append({'pnl': pnl_tp1})[cite: 2]
                        if pos['tp1_hit'] and bar['h'] >= tp2:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio'])[cite: 2]
                            pnl_tp2 = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp2[cite: 2]
                            completed_trades.append({'pnl': pnl_tp2})[cite: 2]
                            pos = None[cite: 2]
                            continue
                    elif side == 'SHORT':[cite: 2]
                        if bar['h'] >= sl:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty[cite: 2]
                            pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE[cite: 2]
                            shared_wallet += pnl[cite: 2]
                            completed_trades.append({'pnl': pnl})[cite: 2]
                            pos = None[cite: 2]
                            continue
                        if not tp1_hit and bar['l'] <= tp1:[cite: 2]
                            pos['tp1_hit'] = True[cite: 2]
                            pnl_tp1 = (qty * cfg['tp1_ratio']) * (entry - tp1) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp1[cite: 2]
                            pos['sl'] = entry[cite: 2]
                            completed_trades.append({'pnl': pnl_tp1})[cite: 2]
                        if pos['tp1_hit'] and bar['l'] <= tp2:[cite: 2]
                            rem_qty = qty * (1.0 - cfg['tp1_ratio'])[cite: 2]
                            pnl_tp2 = rem_qty * (entry - tp2) - rem_qty * (entry + tp2) * FEE_RATE[cite: 2]
                            shared_wallet += pnl_tp2[cite: 2]
                            completed_trades.append({'pnl': pnl_tp2})[cite: 2]
                            pos = None[cite: 2]
                            continue

                if pos is None and shared_wallet > 5.0:[cite: 2]
                    t_hour = bar['time'].floor('H')[cite: 2]
                    h4_bull = h4_map.get(t_hour, True)[cite: 2]
                    ict_info = h1_ict_map.get(t_hour, None)[cite: 2]
                    if ict_info is None:[cite: 2]
                        continue

                    sub = df_15m.iloc[i-25:i+1][cite: 2]
                    h_wave, l_wave = sub['h'].max(), sub['l'].min()[cite: 2]
                    wave = h_wave - l_wave[cite: 2]
                    if wave > 0:[cite: 2]
                        ote_bull_high = h_wave - (wave * 0.618)[cite: 2]
                        ote_bull_low  = h_wave - (wave * 0.790)[cite: 2]
                        ote_bear_low  = l_wave + (wave * 0.618)[cite: 2]
                        ote_bear_high = l_wave + (wave * 0.790)[cite: 2]

                        long_trigger = (
                            h4_bull and
                            (ict_info['bull_fvg'] or ict_info['bull_ob'] or ict_info['sweep_low']) and
                            (bar['l'] <= ote_bull_high and bar['c'] >= ote_bull_low) and
                            (bar['c'] > prev_bar['c'] and bar['c'] > bar['o'])
                        )[cite: 2]

                        short_trigger = (
                            not h4_bull and
                            (ict_info['bear_fvg'] or ict_info['bear_ob'] or ict_info['sweep_high']) and
                            (bar['h'] >= ote_bear_low and bar['c'] <= ote_bear_high) and
                            (bar['c'] < prev_bar['c'] and bar['c'] < bar['o'])
                        )[cite: 2]

                        if long_trigger:[cite: 2]
                            entry = bar['c'][cite: 2]
                            sl_anchor = min(ict_info['ob_bull_low'], l_wave)[cite: 2]
                            sl = sl_anchor * (1.0 - 0.002)[cite: 2]
                            risk_dist = entry - sl[cite: 2]
                            if risk_dist > 0:[cite: 2]
                                qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                                if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                    qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                                tp1 = entry + (risk_dist * cfg['tp1_r'])[cite: 2]
                                tp2 = entry + (risk_dist * cfg['tp2_r'])[cite: 2]
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}[cite: 2]
                        elif short_trigger:[cite: 2]
                            entry = bar['c'][cite: 2]
                            sl_anchor = max(ict_info['ob_bear_high'], h_wave)[cite: 2]
                            sl = sl_anchor * (1.0 + 0.002)[cite: 2]
                            risk_dist = sl - entry[cite: 2]
                            if risk_dist > 0:[cite: 2]
                                qty = (shared_wallet * cfg['risk']) / risk_dist[cite: 2]
                                if (qty * entry) > (shared_wallet * cfg['lev']):[cite: 2]
                                    qty = (shared_wallet * cfg['lev']) / entry[cite: 2]
                                tp1 = entry - (risk_dist * cfg['tp1_r'])[cite: 2]
                                tp2 = entry - (risk_dist * cfg['tp2_r'])[cite: 2]
                                pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}[cite: 2]

        tot_t = len(completed_trades)[cite: 2]
        wins = sum(1 for t in completed_trades if t['pnl'] > 0)[cite: 2]
        wr = (wins / tot_t * 100) if tot_t > 0 else 0.0[cite: 2]
        seg_pnl = shared_wallet - start_wallet_for_sym[cite: 2]
        seg_roi = (seg_pnl / start_wallet_for_sym * 100) if start_wallet_for_sym > 0 else 0.0[cite: 2]

        asset_performance[sym] = {
            'total': tot_t, 'wins': wins, 'wr': wr,
            'start_wallet': start_wallet_for_sym, 'end_wallet': shared_wallet,
            'seg_pnl': seg_pnl, 'seg_roi': seg_roi
        }[cite: 2]

    total_net_pnl = shared_wallet - INITIAL_SHARED_WALLET[cite: 2]
    total_roi = (total_net_pnl / INITIAL_SHARED_WALLET) * 100[cite: 2]

    report_lines = [
        "```text",
        f"【多資產共用 100U 最佳化策略回測報告 - {period_title}】",
        "====================================================================",
        f"初始共用資金: ${INITIAL_SHARED_WALLET:.2f} USDT | 最終共用資金: ${shared_wallet:.2f} USDT ({total_roi:+.2f}%)",
        "--------------------------------------------------------------------",
        "各標的專屬配置與接力表現:"
    ][cite: 2]

    for sym in sorted_symbols:[cite: 2]
        if sym in asset_performance:[cite: 2]
            st = asset_performance[sym][cite: 2]
            report_lines.append(
                f" - {sym.ljust(5)} | 次數: {str(st['total']).ljust(3)} 筆 | 勝率: {st['wr']:6.2f}% | "
                f"結算資金: ${st['end_wallet']:7.2f} (階段貢獻: {st['seg_roi']:+.2f}%)"
            )[cite: 2]

    report_lines.append("====================================================================")[cite: 2]
    report_lines.append("```")[cite: 2]
    report = "\n".join(report_lines)[cite: 2]

    print(report)[cite: 2]
    send_discord(report)[cite: 2]

if __name__ == '__main__':
    run_shared_portfolio_backtest()
