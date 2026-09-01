"""
Multi-Asset Multi-Leverage Quantitative Backtest Engine (365 Days)
================================================================================
【4 檔實盤標的 × 5 種槓桿倍率 (5x, 10x, 20x, 50x, 100x) 獨立資金池回測】
1. 測試範圍: SOL, BNB, DOGE, XAU (PAXG)
2. 測試槓桿: 5x, 10x, 20x, 50x, 100x
3. 資金架構: 每組「標的 × 槓桿」各自獨立 100.0 USDT 初始資金進行動態複利
4. 風控與策略邏輯:
   - SOL : 5.0% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R保本 / 5.0R止盈)
   - BNB : 2.5% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R平30%保本 / 5.0R平70%)
   - DOGE: 5.0% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R保本 / 5.0R止盈)
   - XAU : 5.0% 風控 / 1D MA60 + 4H 唐奇安(20) / 1.5 ATR / 2.0R保本 / 5.0R止盈
5. 強制平倉機制 (Liquidation Check):
   - 納入維持保證金比例 (MMR = 0.5% ~ 1.0%)
   - 若 K 線極值觸及預估強平價，則直接判定爆倉清算 (餘額歸零)，準確評估超高槓桿風險。
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS_CONFIG = {
    'SOL': {
        's': 'SOLUSDT', 'interval': '15m', 'mode': 'ict_aggressive',
        'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'BNB': {
        's': 'BNBUSDT', 'interval': '15m', 'mode': 'ict_hybrid',
        'risk': 0.025, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.3
    },
    'DOGE': {
        's': 'DOGEUSDT', 'interval': '15m', 'mode': 'ict_aggressive',
        'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'XAU': {
        's': 'PAXGUSDT', 'interval': '4h', 'mode': 'gold_donchian',
        'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.0
    }
}

LEVERAGE_LIST = [5.0, 10.0, 20.0, 50.0, 100.0]
INITIAL_WALLET = 100.0
FEE_RATE = 0.0004
MAINTENANCE_MARGIN_RATE = 0.005  # 0.5% 維持保證金率

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
    
    step_ms = (15 * 60 * 1000) if interval == '15m' else (60 * 60 * 1000 if interval == '1h' else (4 * 60 * 60 * 1000))
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

def simulate_trades(df_entry, h4_trend_map, ict_info_map, cfg, lev):
    wallet = float(INITIAL_WALLET)
    completed_trades = []
    pos = None

    for i in range(25, len(df_entry)):
        bar = df_entry.iloc[i]
        prev_bar = df_entry.iloc[i-1]

        # ---------------- 持倉檢查 ----------------
        if pos is not None:
            side = pos['side']
            entry = pos['entry']
            sl = pos['sl']
            tp1 = pos['tp1']
            tp2 = pos['tp2']
            qty = pos['qty']
            liq_p = pos['liq_price']
            tp1_hit = pos['tp1_hit']

            # 1. 強制平倉 (Liquidation) 優先檢查
            if side == 'LONG' and bar['l'] <= liq_p:
                wallet = 0.0
                completed_trades.append({'pnl': -INITIAL_WALLET, 'is_liq': True})
                break
            elif side == 'SHORT' and bar['h'] >= liq_p:
                wallet = 0.0
                completed_trades.append({'pnl': -INITIAL_WALLET, 'is_liq': True})
                break

            # 2. 正常止損 / 止盈檢查
            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    completed_trades.append({'pnl': pnl, 'is_liq': False})
                    pos = None
                    continue
                if not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * cfg['tp1_ratio']) * (tp1 - entry) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE
                    wallet += pnl_tp1
                    pos['sl'] = entry
                    completed_trades.append({'pnl': pnl_tp1, 'is_liq': False})
                if pos['tp1_hit'] and bar['h'] >= tp2:
                    rem_qty = qty * (1.0 - cfg['tp1_ratio'])
                    pnl_tp2 = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE
                    wallet += pnl_tp2
                    completed_trades.append({'pnl': pnl_tp2, 'is_liq': False})
                    pos = None
                    continue

            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * (1.0 - cfg['tp1_ratio']) if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    completed_trades.append({'pnl': pnl, 'is_liq': False})
                    pos = None
                    continue
                if not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * cfg['tp1_ratio']) * (entry - tp1) - (qty * cfg['tp1_ratio']) * (entry + tp1) * FEE_RATE
                    wallet += pnl_tp1
                    pos['sl'] = entry
                    completed_trades.append({'pnl': pnl_tp1, 'is_liq': False})
                if pos['tp1_hit'] and bar['l'] <= tp2:
                    rem_qty = qty * (1.0 - cfg['tp1_ratio'])
                    pnl_tp2 = rem_qty * (entry - tp2) - rem_qty * (entry + tp2) * FEE_RATE
                    wallet += pnl_tp2
                    completed_trades.append({'pnl': pnl_tp2, 'is_liq': False})
                    pos = None
                    continue

        # ---------------- 開倉訊號檢查 ----------------
        if pos is None and wallet > 5.0:
            if cfg['mode'] == 'gold_donchian':
                bull = bar['macro_bull']
                if bull and bar['c'] > bar['dc_high']:
                    entry = bar['c']
                    sl = entry - (bar['atr'] * 1.5)
                    risk_dist = entry - sl
                    if risk_dist > 0:
                        qty = (wallet * cfg['risk']) / risk_dist
                        if (qty * entry) > (wallet * lev):
                            qty = (wallet * lev) / entry
                        # 計算預估強平價
                        liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE)
                        pos = {
                            'side': 'LONG', 'entry': entry, 'sl': sl,
                            'tp1': entry + (risk_dist * cfg['tp1_r']),
                            'tp2': entry + (risk_dist * cfg['tp2_r']),
                            'tp1_hit': False, 'qty': qty, 'liq_price': liq_price
                        }
                elif not bull and bar['c'] < bar['dc_low']:
                    entry = bar['c']
                    sl = entry + (bar['atr'] * 1.5)
                    risk_dist = sl - entry
                    if risk_dist > 0:
                        qty = (wallet * cfg['risk']) / risk_dist
                        if (qty * entry) > (wallet * lev):
                            qty = (wallet * lev) / entry
                        liq_price = entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                        pos = {
                            'side': 'SHORT', 'entry': entry, 'sl': sl,
                            'tp1': entry - (risk_dist * cfg['tp1_r']),
                            'tp2': entry - (risk_dist * cfg['tp2_r']),
                            'tp1_hit': False, 'qty': qty, 'liq_price': liq_price
                        }

            elif cfg['mode'] in ['ict_aggressive', 'ict_hybrid']:
                t_hour = bar['time'].floor('H')
                h4_bull = h4_trend_map.get(t_hour, True)
                ict_info = ict_info_map.get(t_hour, None)
                if ict_info is None:
                    continue

                sub = df_entry.iloc[i-25:i+1]
                h_wave, l_wave = sub['h'].max(), sub['l'].min()
                wave = h_wave - l_wave
                if wave > 0:
                    ote_bull_high = h_wave - (wave * 0.618)
                    ote_bull_low  = h_wave - (wave * 0.790)
                    ote_bear_low  = l_wave + (wave * 0.618)
                    ote_bear_high = l_wave + (wave * 0.790)

                    long_trigger = (
                        h4_bull and (ict_info['bull_fvg'] or ict_info['bull_ob'] or ict_info['sweep_low']) and
                        (bar['l'] <= ote_bull_high and bar['c'] >= ote_bull_low) and
                        (bar['c'] > prev_bar['c'] and bar['c'] > bar['o'])
                    )
                    short_trigger = (
                        not h4_bull and (ict_info['bear_fvg'] or ict_info['bear_ob'] or ict_info['sweep_high']) and
                        (bar['h'] >= ote_bear_low and bar['c'] <= ote_bear_high) and
                        (bar['c'] < prev_bar['c'] and bar['c'] < bar['o'])
                    )

                    if long_trigger:
                        entry = bar['c']
                        sl_anchor = min(ict_info['ob_bull_low'], l_wave)
                        sl = sl_anchor * (1.0 - 0.002)
                        risk_dist = entry - sl
                        if risk_dist > 0:
                            qty = (wallet * cfg['risk']) / risk_dist
                            if (qty * entry) > (wallet * lev):
                                qty = (wallet * lev) / entry
                            liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE)
                            pos = {
                                'side': 'LONG', 'entry': entry, 'sl': sl,
                                'tp1': entry + (risk_dist * cfg['tp1_r']),
                                'tp2': entry + (risk_dist * cfg['tp2_r']),
                                'tp1_hit': False, 'qty': qty, 'liq_price': liq_price
                            }
                    elif short_trigger:
                        entry = bar['c']
                        sl_anchor = max(ict_info['ob_bear_high'], h_wave)
                        sl = sl_anchor * (1.0 + 0.002)
                        risk_dist = sl - entry
                        if risk_dist > 0:
                            qty = (wallet * cfg['risk']) / risk_dist
                            if (qty * entry) > (wallet * cfg['lev']):
                                qty = (wallet * cfg['lev']) / entry
                            liq_price = entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                            pos = {
                                'side': 'SHORT', 'entry': entry, 'sl': sl,
                                'tp1': entry - (risk_dist * cfg['tp1_r']),
                                'tp2': entry - (risk_dist * cfg['tp2_r']),
                                'tp1_hit': False, 'qty': qty, 'liq_price': liq_price
                            }

    tot_trades = len(completed_trades)
    wins = sum(1 for t in completed_trades if t['pnl'] > 0)
    wr = (wins / tot_trades * 100) if tot_trades > 0 else 0.0
    net_pnl = wallet - INITIAL_WALLET
    roi = (net_pnl / INITIAL_WALLET) * 100
    is_liquidated = any(t.get('is_liq', False) for t in completed_trades)

    return {
        'total': tot_trades,
        'wins': wins,
        'wr': wr,
        'final_wallet': wallet,
        'roi': roi,
        'is_liquidated': is_liquidated
    }

def run_multi_leverage_backtest():
    days = 365
    print("\n==========================================================================")
    print(">>> 啟動【4 檔實盤標的 × 5 種槓桿倍率 (5x ~ 100x)】全維度回測...")
    print("==========================================================================")

    results_matrix = {}

    for sym in ['SOL', 'BNB', 'DOGE', 'XAU']:
        cfg = SYMBOLS_CONFIG[sym]
        print(f"\n正在抓取 {sym} 歷史數據 (365天)...", flush=True)

        if cfg['mode'] == 'gold_donchian':
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

            df_entry = df_4h
            h4_trend_map, ict_info_map = {}, {}

        else:
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)
            if df_15m is None or df_1h is None or df_4h is None:
                continue

            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()
            df_4h['h_date'] = df_4h['time'].dt.floor('H')
            h4_trend_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()

            df_1h['swing_high'] = df_1h['h'].rolling(5).max()
            df_1h['swing_low']  = df_1h['l'].rolling(5).min()

            ict_info_map = {}
            for j in range(3, len(df_1h)):
                b_curr = df_1h.iloc[j]
                b_prev = df_1h.iloc[j-1]
                b_prev2 = df_1h.iloc[j-2]
                b_prev3 = df_1h.iloc[j-3]
                h_time = b_curr['time'].floor('H')

                bull_fvg = b_curr['l'] > b_prev2['h']
                bear_fvg = b_curr['h'] < b_prev2['l']
                bull_ob = (b_prev['c'] < b_prev['o']) and (b_curr['c'] > b_prev['h'])
                bear_ob = (b_prev['c'] > b_prev['o']) and (b_curr['c'] < b_prev['l'])
                sweep_low = (b_curr['l'] < b_prev3['swing_low']) and (b_curr['c'] > b_prev3['swing_low'])
                sweep_high = (b_curr['h'] > b_prev3['swing_high']) and (b_curr['c'] < b_prev3['swing_high'])

                ict_info_map[h_time] = {
                    'bull_fvg': bull_fvg, 'bear_fvg': bear_fvg,
                    'bull_ob': bull_ob,   'bear_ob': bear_ob,
                    'sweep_low': sweep_low, 'sweep_high': sweep_high,
                    'ob_bull_low': b_prev['l'], 'ob_bear_high': b_prev['h']
                }

            df_entry = df_15m

        results_matrix[sym] = {}
        for lev in LEVERAGE_LIST:
            res = simulate_trades(df_entry, h4_trend_map, ict_info_map, cfg, lev)
            results_matrix[sym][lev] = res
            status = "💀 爆倉清算" if res['is_liquidated'] else f"${res['final_wallet']:.2f} ({res['roi']:+.2f}%)"
            print(f"  [{sym}] {int(lev)}x 槓桿 -> 交易筆數: {res['total']:3d} | 勝率: {res['wr']:5.2f}% | 結算: {status}")

    # ---------------- 組合完整矩陣報表 ----------------
    report_lines = [
        "```text",
        "【多資產多槓桿深度回測報告 - 365天獨立100U沙盒】",
        "==========================================================================",
        f"{'標的':<6} | {'5x 結算 (ROI)':<17} | {'10x 結算 (ROI)':<17} | {'20x 結算 (ROI)':<17} | {'50x 結算 (ROI)':<17} | {'100x 結算 (ROI)':<17}",
        "--------------------------------------------------------------------------"
    ]

    for sym in ['SOL', 'BNB', 'DOGE', 'XAU']:
        if sym in results_matrix:
            row_items = [sym.ljust(6)]
            for lev in LEVERAGE_LIST:
                r = results_matrix[sym][lev]
                if r['is_liquidated']:
                    val_str = "爆倉清算 ($0.0)"
                else:
                    val_str = f"${r['final_wallet']:.1f} ({r['roi']:+.1f}%)"
                row_items.append(f"{val_str:<17}")
            report_lines.append(" | ".join(row_items))

    report_lines.append("==========================================================================")
    report_lines.append("風控備註: SOL/DOGE/XAU (5% 風控) | BNB (2.5% 風控)")
    report_lines.append("```")

    full_report = "\n".join(report_lines)
    print("\n" + full_report)
    send_discord(full_report)

if __name__ == '__main__':
    run_multi_leverage_backtest()
