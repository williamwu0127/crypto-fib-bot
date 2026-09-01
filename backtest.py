"""
Multi-Asset Independent Sandbox Backtest Engine (365 Days)
- Assets: BTC, ETH, SOL, BNB, DOGE, XAU (PAXG)
- Capital: Each asset has an independent 100.0 USDT starting pool
- Gold Strategy: 1D MA60 -> 4H Donchian(20) -> 1.5 ATR -> 2.0R BE -> 5.0R TP (5% Risk / 10x)
- Crypto Strategy: 1D EMA50 -> 4H EMA Trend -> 15m Fibonacci 0.618 (1% Risk)
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_triple_screen'},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_triple_screen'},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_triple_screen'},
    'BNB':  {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_triple_screen'},
    'DOGE': {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_triple_screen'},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian'}
}

INITIAL_WALLET_PER_ASSET = 100.0
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

def run_independent_sandbox_backtest():
    days = 365
    period_title = "365 天期 (獨立 100U 沙盒回測)"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】多資產獨立資金回測...")
    print(f"==================================================")

    asset_results = {}

    for sym, cfg in SYMBOLS.items():
        wallet = float(INITIAL_WALLET_PER_ASSET)
        completed_trades = []
        print(f"獨立跑背測標的: {sym} (起始資金: ${wallet:.2f} USDT)...", flush=True)
        
        if cfg['mode'] == 'gold_macro_donchian':
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
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if bar['h'] >= tp:
                            pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if not be_done and bar['l'] <= be_tgt:
                            pos['sl'] = entry
                            pos['is_be_moved'] = True
                        if bar['h'] >= pos['sl']:
                            pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if bar['l'] <= tp:
                            pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    bull = bar['macro_bull']
                    if bull and bar['c'] > bar['dc_high']:
                        entry = bar['c']
                        sl = entry - (bar['atr'] * 1.5)
                        risk_dist = entry - sl
                        if risk_dist > 0:
                            qty = (wallet * 0.05) / risk_dist
                            if (qty * entry) > (wallet * 10.0):
                                qty = (wallet * 10.0) / entry
                            pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': entry + (risk_dist * 5.0), 'be_target': entry + (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}
                    elif not bull and bar['c'] < bar['dc_low']:
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        risk_dist = sl - entry
                        if risk_dist > 0:
                            qty = (wallet * 0.05) / risk_dist
                            if (qty * entry) > (wallet * 10.0):
                                qty = (wallet * 10.0) / entry
                            pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': entry - (risk_dist * 5.0), 'be_target': entry - (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}

        elif cfg['mode'] == 'crypto_triple_screen':
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
            delta = df_15m['c'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            df_15m['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
            df_15m['rsi_ema'] = df_15m['rsi'].ewm(span=9, adjust=False).mean()

            pos = None
            for i in range(30, len(df_15m)):
                bar = df_15m.iloc[i]
                if pos is not None:
                    side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit']
                    if side == 'LONG':
                        if bar['l'] <= sl:
                            rem_qty = qty * 0.5 if tp1_hit else qty
                            pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['h'] >= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = tp1
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['h'] >= tp2:
                            pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if bar['h'] >= sl:
                            rem_qty = qty * 0.5 if tp1_hit else qty
                            pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['l'] <= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = tp1
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['l'] <= tp2:
                            pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    t_day = bar['time'].floor('D')
                    t_hour = bar['time'].floor('H')
                    d1_bull = d_map.get(t_day, True)
                    h4_bull = h4_map.get(t_hour, True)

                    sub = df_15m.iloc[i-25:i+1]
                    h, l = sub['h'].max(), sub['l'].min()
                    wave = h - l
                    if wave > 0 and (wave / l) >= 0.005:
                        fib_0618_l = h - (wave * 0.618)
                        fib_0618_s = l + (wave * 0.618)
                        prev_rsi = df_15m.iloc[i-1]['rsi']
                        rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_rsi)
                        rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_rsi)

                        if d1_bull and h4_bull and (bar['c'] >= bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and rsi_bull:
                            entry = bar['c']
                            sl = min(l, entry - (bar['atr'] * 1.5))
                            risk_dist = abs(entry - sl)
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                tp1 = h if h > entry else entry + risk_dist
                                tp2 = h + (wave * 0.272)
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}
                        elif not d1_bull and not h4_bull and (bar['c'] <= bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and rsi_bear:
                            entry = bar['c']
                            sl = max(h, entry + (bar['atr'] * 1.5))
                            risk_dist = abs(entry - sl)
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                tp1 = l if l < entry else entry - risk_dist
                                tp2 = l - (wave * 0.272)
                                pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}

        tot_t = len(completed_trades)
        wins = sum(1 for t in completed_trades if t['pnl'] > 0)
        wr = (wins / tot_t * 100) if tot_t > 0 else 0.0
        net_pnl = wallet - INITIAL_WALLET_PER_ASSET
        roi = (net_pnl / INITIAL_WALLET_PER_ASSET) * 100

        asset_results[sym] = {
            'total': tot_t, 'wins': wins, 'wr': wr, 'final_wallet': wallet, 'net_pnl': net_pnl, 'roi': roi
        }

    # 排序：加密貨幣在前 (BTC, ETH, SOL, BNB, DOGE)，黃金在後 (XAU)
    sorted_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XAU']

    report_lines = [
        "```text",
        f"【多資產獨立 100U 沙盒回測報告 - {period_title}】",
        "----------------------------------------------------",
        "資金配置: 每種標的各自獨立 100.0 USDT 帳戶",
        "加密貨幣: BTC, ETH, SOL, BNB, DOGE (1% 風控 / 15m 斐波策略)",
        "貴金屬:   XAU (5% 風控 / 10x 槓桿 / 4H 唐奇安策略)",
        "----------------------------------------------------",
        "各標的獨立帳戶績效排序:"
    ]
    
    for sym in sorted_symbols:
        if sym in asset_results:
            st = asset_results[sym]
            report_lines.append(f" - {sym.ljust(5)} | 次數: {str(st['total']).ljust(3)} 筆 | 勝率: {st['wr']:6.2f}% | 最終餘額: ${st['final_wallet']:7.2f} ({st['roi']:+.2f}%)")
    
    report_lines.append("```")
    report = "\n".join(report_lines)
    
    print(report)
    send_discord(report)

if __name__ == '__main__':
    run_independent_sandbox_backtest()
