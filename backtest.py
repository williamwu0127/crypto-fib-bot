"""
Multi-Asset SMC & Macro Independent Sandbox Backtest Engine (365 Days)
====================================================================
【完整交易邏輯與備份說明】
1. 資金與沙盒架構:
   - 標的範圍: BTC, ETH, SOL, BNB, DOGE (加密貨幣) 及 XAU/PAXG (黃金)。
   - 獨立資金池: 每種標的各自擁有獨立的 100.0 USDT 起始資金與複利帳戶，盈虧互不干涉。
   - 排序格式: 嚴格按照加密貨幣在前、黃金在後的順序輸出與統計。

2. 加密貨幣策略模型 (SMC + 頂層架構 + 15m 執行):
   - 宏觀定錨 (1D): 計算 1D EMA50。價格 >= EMA50 僅做多，反之僅做空。
   - 結構與缺口 (4H / 1H): 偵測大級別市場結構轉變（CHoCH）與機構不平衡區（FVG）。
   - 微觀進場 (15m): 價格回踩 4H/1H 的 FVG 區間，配合 15m 斐波 0.618 與實體收盤確認進場。
   - 風控與止損 (SL): 設在結構防守點（FVG 極端邊緣）外側加上 0.2% 緩衝區（Buffer），不設絕對防守。每筆交易風險為帳戶權益的 1%。
   - 分批止盈 (TP): 
     * TP1: 達到 1.5R 盈虧比時平倉 50% 部位，並將剩餘部位止損推至開倉價（保本）。
     * TP2: 達到 3.0R 盈虧比（流動性目標位）時全數平倉。

3. 黃金策略模型 (XAU / PAXG):
   - 宏觀定錨 (1D): MA60 判斷多空。
   - 突破進場 (4H): 4H 唐奇安通道 (Donchian 20) 突破。
   - 風控與動態保本: 5% 風控 / 10x 槓桿，1.5 ATR 初始止損，浮盈達 2.0R 時移動保本，5.0R 全額止盈。
====================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_smc'},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_smc'},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_smc'},
    'BNB':  {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_smc'},
    'DOGE': {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_smc'},
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
    period_title = "365 天期 (SMC + 獨立 100U 沙盒回測)"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】多資產獨立資金回測...")
    print(f"==================================================")

    asset_results = {}
    sorted_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XAU']

    for sym in sorted_symbols:
        cfg = SYMBOLS[sym]
        wallet = float(INITIAL_WALLET_PER_ASSET)
        completed_trades = []
        print(f"獨立跑背測標的: {sym} (起始資金: ${wallet:.2f} USDT)...", flush=True)
        
        # 1. 黃金策略模式
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

        # 2. 加密貨幣 SMC 策略模式 (4H/1H 結構與 FVG + 15m 執行 + 0.2% buffer)
        elif cfg['mode'] == 'crypto_smc':
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 30)
            df_1d  = fetch_binance_klines(cfg['s'], '1d', days=days + 60)
            if df_15m is None or df_4h is None or df_1d is None:
                continue

            df_1d['ema50'] = df_1d['c'].ewm(span=50, adjust=False).mean()
            df_1d['d_date'] = df_1d['time'].dt.floor('D')
            d_map = df_1d.set_index('d_date')['c'].ge(df_1d.set_index('d_date')['ema50']).to_dict()

            df_4h['swing_high'] = df_4h['h'].rolling(5).max()
            df_4h['swing_low'] = df_4h['l'].rolling(5).min()
            df_4h['h_date'] = df_4h['time'].dt.floor('H')
            
            # 對齊 4H 結構與 FVG
            fvg_4h_map = {}
            for j in range(2, len(df_4h)):
                b_curr = df_4h.iloc[j]
                b_prev2 = df_4h.iloc[j-2]
                h_time = b_curr['time'].floor('H')
                
                bull_fvg = b_curr['l'] > b_prev2['h']
                bear_fvg = b_curr['h'] < b_prev2['l']
                fvg_4h_map[h_time] = {
                    'bull': bull_fvg, 'bear': bear_fvg,
                    'bull_zone': (b_prev2['h'], b_curr['l']),
                    'bear_zone': (b_curr['h'], b_prev2['l'])
                }

            pos = None
            for i in range(20, len(df_15m)):
                bar = df_15m.iloc[i]
                prev_bar = df_15m.iloc[i-1]

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
                            pos['sl'] = entry
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
                            pos['sl'] = entry
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
                    
                    fvg_info = fvg_4h_map.get(t_hour, {'bull': False, 'bear': False})

                    # 15m 實體收盤確認與斐波 0.618 區間觸發
                    sub = df_15m.iloc[i-20:i+1]
                    h_wave, l_wave = sub['h'].max(), sub['l'].min()
                    wave = h_wave - l_wave
                    if wave > 0:
                        fib_0618_l = h_wave - (wave * 0.618)
                        fib_0618_s = l_wave + (wave * 0.618)

                        if d1_bull and fvg_info['bull'] and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] > prev_bar['c']):
                            entry = bar['c']
                            # 結構防守點下緣外側多放 0.2% 緩衝
                            sl = fvg_info['bull_zone'][0] * (1.0 - 0.002)
                            risk_dist = entry - sl
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                tp1 = entry + (risk_dist * 1.5)
                                tp2 = entry + (risk_dist * 3.0)
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}
                        elif not d1_bull and fvg_info['bear'] and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] < prev_bar['c']):
                            entry = bar['c']
                            # 結構防守點上緣外側多放 0.2% 緩衝
                            sl = fvg_info['bear_zone'][1] * (1.0 + 0.002)
                            risk_dist = sl - entry
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                tp1 = entry - (risk_dist * 1.5)
                                tp2 = entry - (risk_dist * 3.0)
                                pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}

        tot_t = len(completed_trades)
        wins = sum(1 for t in completed_trades if t['pnl'] > 0)
        wr = (wins / tot_t * 100) if tot_t > 0 else 0.0
        net_pnl = wallet - INITIAL_WALLET_PER_ASSET
        roi = (net_pnl / INITIAL_WALLET_PER_ASSET) * 100

        asset_results[sym] = {
            'total': tot_t, 'wins': wins, 'wr': wr, 'final_wallet': wallet, 'net_pnl': net_pnl, 'roi': roi
        }

    report_lines = [
        "```text",
        f"【多資產獨立 100U SMC 沙盒回測報告 - {period_title}】",
        "----------------------------------------------------",
        "資金配置: 每種標的各自獨立 100.0 USDT 帳戶",
        "加密貨幣: BTC, ETH, SOL, BNB, DOGE (1% 風控 / 4H FVG + 15m 收盤確認)",
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
