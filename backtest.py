"""
Multi-Asset Custom Risk & Leverage Backtest Engine (365 Days)
================================================================================
【專屬自訂配置回測架構】
1. 標的與槓桿設定:
   - XAU (黃金)  : 20x 槓桿 / 5.0% 風控 / 4H 唐奇安(20) / 1.5 ATR / 2.0R 保本 / 5.0R 止盈
   - SOL        :  5x 槓桿 / 5.0% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R/5.0R)
   - BNB        :  5x 槓桿 / 2.5% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R/5.0R)
   - DOGE       :  5x 槓桿 / 5.0% 風控 / 1H ICT (Sweep+OB+FVG) + 15m OTE (2.0R/5.0R)

2. 總倉位與保證金防護機制:
   - 開倉保證金上限 (Margin Cap): 單筆佔用保證金嚴格限制為當前可用資金的 10% (MAX_MARGIN_RATIO = 0.10)。
   - 預估強平價檢查 (Liquidation Check): 納入維持保證金比例 (MMR = 0.5%)，精確評估 20x 槓桿耐受度。
   - 資金架構: 每檔標的各自獨立 100.0 USDT 初始資金進行動態複利。
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
        'lev': 5.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'BNB': {
        's': 'BNBUSDT', 'interval': '15m', 'mode': 'ict_hybrid',
        'lev': 5.0, 'risk': 0.025, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.3
    },
    'DOGE': {
        's': 'DOGEUSDT', 'interval': '15m', 'mode': 'ict_aggressive',
        'lev': 5.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.5
    },
    'XAU': {
        's': 'PAXGUSDT', 'interval': '4h', 'mode': 'gold_donchian',
        'lev': 20.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.0
    }
}

INITIAL_WALLET = 100.0
FEE_RATE = 0.0004
MAINTENANCE_MARGIN_RATE = 0.005
MAX_MARGIN_RATIO = 0.10  # 單筆佔用保證金最多 10% 總權益

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

def run_custom_backtest():
    days = 365
    print("\n==========================================================================")
    print(">>> 開始執行【黃金 20x + 加密貨幣 5x + 10% 保證金限制】365天回測...")
    print("==========================================================================")

    results = {}
    sorted_symbols = ['SOL', 'BNB', 'DOGE', 'XAU']

    for sym in sorted_symbols:
        cfg = SYMBOLS_CONFIG[sym]
        lev = cfg['lev']
        wallet = float(INITIAL_WALLET)
        completed_trades = []
        pos = None
        
        print(f"正在執行 {sym.ljust(5)} (槓桿: {int(lev)}x | 風控: {cfg['risk']*100:.1f}% | 保證金上限: {int(MAX_MARGIN_RATIO*100)}%)...", flush=True)

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

            for i in range(25, len(df_4h)):
                bar = df_4h.iloc[i]
                if pos is not None:
                    side, entry, sl, tp1, tp2, qty, liq_p, be_done = (
                        pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['is_be_moved']
                    )

                    # 強平檢查
                    if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                        wallet = 0.0
                        completed_trades.append({'pnl': -INITIAL_WALLET, 'is_liq': True})
                        break

                    if side == 'LONG':
                        if not be_done and bar['h'] >= tp1:
                            pos['sl'] = entry
                            pos['is_be_moved'] = True
                        if bar['l'] <= pos['sl']:
                            pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl, 'is_liq': False})
                            pos = None
                            continue
                        if bar['h'] >= tp2:
                            pnl = qty * (tp2 - entry) - qty * (entry + tp2) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl, 'is_liq': False})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if not be_done and bar['l'] <= tp1:
                            pos['sl'] = entry
                            pos['is_be_moved'] = True
                        if bar['h'] >= pos['sl']:
                            pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl, 'is_liq': False})
                            pos = None
                            continue
                        if bar['l'] <= tp2:
                            pnl = qty * (entry - tp2) - qty * (entry + tp2) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl, 'is_liq': False})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    bull = bar['macro_bull']
                    entry, sl, risk_dist, side = None, None, None, None
                    if bull and bar['c'] > bar['dc_high']:
                        entry = bar['c']
                        sl = entry - (bar['atr'] * 1.5)
                        risk_dist = entry - sl
                        side = 'LONG'
                    elif not bull and bar['c'] < bar['dc_low']:
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        risk_dist = sl - entry
                        side = 'SHORT'

                    if entry and risk_dist > 0:
                        qty = (wallet * cfg['risk']) / risk_dist
                        # 10% 保證金上限防護 (保證金 = 名義價值 / 槓桿 <= wallet * 10%)
                        max_allowed_qty = (wallet * MAX_MARGIN_RATIO * lev) / entry
                        if qty > max_allowed_qty:
                            qty = max_allowed_qty

                        if side == 'LONG':
                            liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE)
                            pos = {
                                'side': 'LONG', 'entry': entry, 'sl': sl,
                                'tp1': entry + (risk_dist * cfg['tp1_r']),
                                'tp2': entry + (risk_dist * cfg['tp2_r']),
                                'qty': qty, 'liq_price': liq_price, 'is_be_moved': False
                            }
                        else:
                            liq_price = entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                            pos = {
                                'side': 'SHORT', 'entry': entry, 'sl': sl,
                                'tp1': entry - (risk_dist * cfg['tp1_r']),
                                'tp2': entry - (risk_dist * cfg['tp2_r']),
                                'qty': qty, 'liq_price': liq_price, 'is_be_moved': False
                            }

        else:
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)
            if df_15m is None or df_1h is None or df_4h is None:
                continue

            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()
            df_4h['h_date'] = df_4h['time'].dt.floor('h')
            h4_trend_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()

            df_1h['swing_high'] = df_1h['h'].rolling(5).max()
            df_1h['swing_low']  = df_1h['l'].rolling(5).min()

            ict_info_map = {}
            for j in range(3, len(df_1h)):
                b_curr, b_prev, b_prev2, b_prev3 = df_1h.iloc[j], df_1h.iloc[j-1], df_1h.iloc[j-2], df_1h.iloc[j-3]
                h_time = b_curr['time'].floor('h')

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

            for i in range(25, len(df_15m)):
                bar = df_15m.iloc[i]
                prev_bar = df_15m.iloc[i-1]

                if pos is not None:
                    side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                        pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
                    )

                    if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                        wallet = 0.0
                        completed_trades.append({'pnl': -INITIAL_WALLET, 'is_liq': True})
                        break

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

                if pos is None and wallet > 5.0:
                    t_hour = bar['time'].floor('h')
                    h4_bull = h4_trend_map.get(t_hour, True)
                    ict_info = ict_info_map.get(t_hour, None)
                    if ict_info is None:
                        continue

                    sub = df_15m.iloc[i-25:i+1]
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
                                max_allowed_qty = (wallet * MAX_MARGIN_RATIO * lev) / entry
                                if qty > max_allowed_qty:
                                    qty = max_allowed_qty
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
                                max_allowed_qty = (wallet * MAX_MARGIN_RATIO * lev) / entry
                                if qty > max_allowed_qty:
                                    qty = max_allowed_qty
                                liq_price = entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                                pos = {
                                    'side': 'SHORT', 'entry': entry, 'sl': sl,
                                    'tp1': entry - (risk_dist * cfg['tp1_r']),
                                    'tp2': entry - (risk_dist * cfg['tp2_r']),
                                    'tp1_hit': False, 'qty': qty, 'liq_price': liq_price
                                }

        tot_t = len(completed_trades)
        wins = sum(1 for t in completed_trades if t['pnl'] > 0)
        wr = (wins / tot_t * 100) if tot_t > 0 else 0.0
        net_pnl = wallet - INITIAL_WALLET
        roi = (net_pnl / INITIAL_WALLET) * 100
        is_liq = any(t.get('is_liq', False) for t in completed_trades)

        results[sym] = {
            'total': tot_t, 'wins': wins, 'wr': wr,
            'final_wallet': wallet, 'roi': roi, 'is_liq': is_liq
        }

    report_lines = [
        "```text",
        "【多資產自訂配置回測報告 - 黃金20x / 加密5x / 10%保證金限制】",
        "==========================================================================",
        "資金架構: 每標的獨立 100.0 USDT | 單筆保證金上限: 10% 總權益",
        "黃金 (XAU): 20x 槓桿 | 5.0% 風控 | 4H 唐奇安 (2.0R 保本 / 5.0R 止盈)",
        "加密貨幣:   5x 槓桿 | SOL/DOGE (5% 風控) | BNB (2.5% 風控) | 1H ICT",
        "--------------------------------------------------------------------------",
        "各標的回測結算績效:"
    ]

    for sym in sorted_symbols:
        st = results[sym]
        status = "💀 爆倉清算" if st['is_liq'] else f"${st['final_wallet']:.2f} ({st['roi']:+.2f}%)"
        report_lines.append(
            f" - {sym.ljust(5)} | 槓桿: {int(SYMBOLS_CONFIG[sym]['lev']):2d}x | 次數: {str(st['total']).ljust(3)} 筆 | 勝率: {st['wr']:6.2f}% | 結算: {status}"
        )

    report_lines.append("==========================================================================")
    report_lines.append("```")

    report = "\n".join(report_lines)
    print("\n" + report)
    send_discord(report)

if __name__ == '__main__':
    run_custom_backtest()
