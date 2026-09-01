"""
Multi-Asset ICT/SMC Pro Quantitative Backtest Engine (365 Days)
================================================================================
【優化配置說明】
1. 分級風控 (Tiered Risk Management):
   - 主流幣 (BTC, ETH, BNB): 設定 2.5% 風控，降低震盪洗盤期的磨損回撤。
   - 高彈性山寨幣 (SOL, DOGE): 設定 4.0% 風控，放大趨勢單邊的複利爆發力。
   - 貴金屬 (XAU): 維持 5.0% 風控 / 10x 槓桿。
2. 損益與出清結構優化 (Profit-Run Scaling):
   - TP1 (2.0R): 僅平倉 30% 部位鎖定手續費與基本利潤，並將剩餘 70% 部位止損推至保本 (BE)。
   - TP2 (5.0R): 剩餘 70% 部位全數平倉，大幅提升單筆大趨勢的吃肉量。
3. 防守與進場模型:
   - 4H 趨勢定錨 + 1H 流動性獵取/OB/FVG + 15m OTE (0.618~0.79) 尊重收盤確認。
   - 止損錨定 OB/結構外側 + 0.2% 緩衝區 (Buffer)。
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0, 'risk': 0.025},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0, 'risk': 0.025},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0, 'risk': 0.040},
    'BNB':  {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0, 'risk': 0.025},
    'DOGE': {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0, 'risk': 0.040},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian', 'lev': 10.0, 'risk': 0.050}
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

def run_independent_sandbox_backtest():
    days = 365
    period_title = "365 天期 (分級風控 + 70%奔跑止盈 + 獨立100U沙盒)"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】多資產獨立資金回測...")
    print(f"==================================================")

    asset_results = {}
    sorted_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XAU']

    for sym in sorted_symbols:
        cfg = SYMBOLS[sym]
        wallet = float(INITIAL_WALLET_PER_ASSET)
        completed_trades = []
        print(f"獨立跑背測標的: {sym} (起始資金: ${wallet:.2f} USDT | 風控: {cfg['risk']*100:.1f}%)...", flush=True)
        
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
                            qty = (wallet * cfg['risk']) / risk_dist
                            if (qty * entry) > (wallet * cfg['lev']):
                                qty = (wallet * cfg['lev']) / entry
                            pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': entry + (risk_dist * 5.0), 'be_target': entry + (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}
                    elif not bull and bar['c'] < bar['dc_low']:
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        risk_dist = sl - entry
                        if risk_dist > 0:
                            qty = (wallet * cfg['risk']) / risk_dist
                            if (qty * entry) > (wallet * cfg['lev']):
                                qty = (wallet * cfg['lev']) / entry
                            pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': entry - (risk_dist * 5.0), 'be_target': entry - (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}

        # 2. 加密貨幣 ICT/SMC Pro 策略 (分級風控 + 30%/70% 分批)
        elif cfg['mode'] == 'crypto_ict_pro':
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)
            if df_15m is None or df_1h is None or df_4h is None:
                continue

            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()
            df_4h['h_date'] = df_4h['time'].dt.floor('H')
            h4_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()

            df_1h['swing_high'] = df_1h['h'].rolling(5).max()
            df_1h['swing_low']  = df_1h['l'].rolling(5).min()

            h1_ict_map = {}
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

                h1_ict_map[h_time] = {
                    'bull_fvg': bull_fvg, 'bear_fvg': bear_fvg,
                    'bull_ob': bull_ob,   'bear_ob': bear_ob,
                    'sweep_low': sweep_low, 'sweep_high': sweep_high,
                    'ob_bull_low': b_prev['l'],
                    'ob_bear_high': b_prev['h'],
                    'fvg_bull_zone': (b_prev2['h'], b_curr['l']) if bull_fvg else (b_prev['l'], b_curr['h']),
                    'fvg_bear_zone': (b_curr['h'], b_prev2['l']) if bear_fvg else (b_curr['l'], b_prev['h'])
                }

            pos = None
            for i in range(25, len(df_15m)):
                bar = df_15m.iloc[i]
                prev_bar = df_15m.iloc[i-1]

                if pos is not None:
                    side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit']
                    if side == 'LONG':
                        if bar['l'] <= sl:
                            rem_qty = qty * 0.7 if tp1_hit else qty
                            pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['h'] >= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.3) * (tp1 - entry) - (qty * 0.3) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = entry
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['h'] >= tp2:
                            pnl_tp2 = (qty * 0.7) * (tp2 - entry) - (qty * 0.7) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if bar['h'] >= sl:
                            rem_qty = qty * 0.7 if tp1_hit else qty
                            pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['l'] <= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.3) * (entry - tp1) - (qty * 0.3) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = entry
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['l'] <= tp2:
                            pnl_tp2 = (qty * 0.7) * (entry - tp2) - (qty * 0.7) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    t_hour = bar['time'].floor('H')
                    h4_bull = h4_map.get(t_hour, True)
                    ict_info = h1_ict_map.get(t_hour, None)
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
                            h4_bull and
                            (ict_info['bull_fvg'] or ict_info['bull_ob'] or ict_info['sweep_low']) and
                            (bar['l'] <= ote_bull_high and bar['c'] >= ote_bull_low) and
                            (bar['c'] > prev_bar['c'] and bar['c'] > bar['o'])
                        )

                        short_trigger = (
                            not h4_bull and
                            (ict_info['bear_fvg'] or ict_info['bear_ob'] or ict_info['sweep_high']) and
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
                                if (qty * entry) > (wallet * cfg['lev']):
                                    qty = (wallet * cfg['lev']) / entry
                                tp1 = entry + (risk_dist * 2.0)
                                tp2 = entry + (risk_dist * 5.0)
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}
                        elif short_trigger:
                            entry = bar['c']
                            sl_anchor = max(ict_info['ob_bear_high'], h_wave)
                            sl = sl_anchor * (1.0 + 0.002)
                            risk_dist = sl - entry
                            if risk_dist > 0:
                                qty = (wallet * cfg['risk']) / risk_dist
                                if (qty * entry) > (wallet * cfg['lev']):
                                    qty = (wallet * cfg['lev']) / entry
                                tp1 = entry - (risk_dist * 2.0)
                                tp2 = entry - (risk_dist * 5.0)
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
        f"【多資產獨立 100U ICT/SMC Pro 沙盒回測報告 - {period_title}】",
        "--------------------------------------------------------------------",
        "資金配置: 每種標的各自獨立 100.0 USDT 帳戶",
        "加密貨幣: BTC, ETH, BNB (2.5% 風控) | SOL, DOGE (4.0% 風控) | 10x 槓桿",
        "貴金屬:   XAU (5.0% 風控 / 10x 槓桿 / 4H 唐奇安策略)",
        "--------------------------------------------------------------------",
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
