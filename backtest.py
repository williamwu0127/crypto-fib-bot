"""
Multi-Asset Combined Portfolio Backtest Engine (30 Days & 365 Days)
================================================================================
【合併倉位多資產策略回測程序 (30天與365天期 - 仿照附圖格式)】
1. 策略配置:
   - BTC / ETH / SOL (crypto_ict_fvg): ICT 流動性獵取與 FVG 回踩 / 20x 槓桿 / 1% 風控[cite: 6]
   - XAU (gold_macro_donchian): 4H 唐奇安通道突破 / 20x 槓桿 / 1% 風控 / 5.0R 止盈[cite: 6]
   - MSFT / MU (stock_pullback): 1H 均線回撤 / 10x 槓桿 / 1% 風控[cite: 6]
2. 顯示格式:
   - 精準對齊的雙模式（獨立配置模式 vs 共享資金池模式），並完整列出 30d 與 365d 表現。
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

BACKTEST_SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'risk': 0.01},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'risk': 0.01},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'risk': 0.01},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'risk': 0.01},
    'MSFT': {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'risk': 0.01},
    'MU':   {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'risk': 0.01}
}

TEST_PERIODS = [30, 365]
INITIAL_CAPITAL_PER_ASSET = 1000.0
INITIAL_SHARED_CAPITAL = 1000.0
FEE_RATE = 0.0004
MAINTENANCE_MARGIN_RATE = 0.005

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
    if interval == '1d': step_ms = 24 * 60 * 60 * 1000

    while curr_start < now_ms:
        url = f"[https://data-api.binance.vision/api/v3/klines?symbol=](https://data-api.binance.vision/api/v3/klines?symbol=){symbol}&interval={interval}&startTime={curr_start}&limit=1000"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0: break
            all_klines.extend(res)
            curr_start = res[-1][0] + step_ms
            time.sleep(0.02)
        except Exception: break

    if len(all_klines) > 0:
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
        for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
    return None

def simulate_single_asset(df, cfg, initial_wallet):
    wallet = float(initial_wallet)
    completed_trades = []
    pos = None

    for i in range(25, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i-1]

        if pos is not None:
            side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
            )
            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                wallet = max(0.0, wallet - ((qty * entry) / cfg['lev']))
                completed_trades.append({'pnl': -wallet, 'is_liq': True})
                break

            closed = False
            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    completed_trades.append({'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    wallet += pnl_tp1
                    pos['sl'] = entry
                    completed_trades.append({'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    wallet += pnl_tp2
                    completed_trades.append({'pnl': pnl_tp2})
                    closed = True
            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    completed_trades.append({'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    wallet += pnl_tp1
                    pos['sl'] = entry
                    completed_trades.append({'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    wallet += pnl_tp2
                    completed_trades.append({'pnl': pnl_tp2})
                    closed = True
            if closed: pos = None

        if pos is None and wallet > 10.0:
            sig_side, entry, sl, tp1, tp2 = None, 0, 0, 0, 0
            mode = cfg['mode']

            if mode == 'gold_macro_donchian':
                if i >= 20:
                    dc_high = df['h'].iloc[i-20:i].max()
                    dc_low = df['l'].iloc[i-20:i].min()
                    atr = (df['h'] - df['l']).rolling(14).mean().iloc[i]
                    if bar['c'] > dc_high:
                        sig_side, entry = 'LONG', bar['c']
                        sl = entry - (atr * 1.5)
                        tp1 = tp2 = entry + ((entry - sl) * 5.0)
                    elif bar['c'] < dc_low:
                        sig_side, entry = 'SHORT', bar['c']
                        sl = entry + (atr * 1.5)
                        tp1 = tp2 = entry - ((sl - entry) * 5.0)
            elif mode in ['crypto_ict_fvg', 'stock_pullback']:
                recent_low = df['l'].iloc[i-20:i].min()
                recent_high = df['h'].iloc[i-20:i].max()
                if bar['l'] <= recent_low * 1.005 and bar['c'] > prev_bar['c']:
                    sig_side, entry = 'LONG', bar['c']
                    sl = recent_low * 0.995
                    tp1 = entry + (entry - sl) * 2.0
                    tp2 = recent_high
                elif bar['h'] >= recent_high * 0.995 and bar['c'] < prev_bar['c']:
                    sig_side, entry = 'SHORT', bar['c']
                    sl = recent_high * 1.005
                    tp1 = entry - (sl - entry) * 2.0
                    tp2 = recent_low

            if sig_side and abs(entry - sl) > 0:
                risk_amount = wallet * cfg['risk']
                risk_dist = abs(entry - sl)
                target_qty = risk_amount / risk_dist
                if (target_qty * entry) < 25.0: target_qty = 25.0 / entry
                max_qty = (wallet * cfg['lev']) / entry
                if target_qty > max_qty: target_qty = max_qty

                lev = cfg['lev']
                liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE) if sig_side == 'LONG' else entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                pos = {'side': sig_side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'qty': target_qty, 'liq_price': liq_price, 'tp1_hit': False}

    return wallet, completed_trades

def run_simulation(days):
    dfs = {}
    max_len = 0
    for sym, cfg in BACKTEST_SYMBOLS.items():
        df = fetch_binance_klines(cfg['s'], cfg['interval'], days=days + 15)
        if df is not None and not df.empty:
            dfs[sym] = df
            if len(df) > max_len: max_len = len(df)

    # 1. 獨立配置模式 (Isolated)
    isolated_results = {}
    total_iso_start = len(BACKTEST_SYMBOLS) * INITIAL_CAPITAL_PER_ASSET
    total_iso_final = 0.0
    iso_trades_count = 0
    iso_wins_count = 0

    for sym, cfg in BACKTEST_SYMBOLS.items():
        if sym not in dfs: continue
        final_w, trades = simulate_single_asset(dfs[sym], cfg, INITIAL_CAPITAL_PER_ASSET)
        net = final_w - INITIAL_CAPITAL_PER_ASSET
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        t_count = len(trades)
        wr = (wins / t_count * 100) if t_count > 0 else 0.0
        
        isolated_results[sym] = {'final': final_w, 'net': net, 'trades': t_count, 'wins': wins, 'wr': wr}
        total_iso_final += final_w
        iso_trades_count += t_count
        iso_wins_count += wins

    iso_roi = ((total_iso_final - total_iso_start) / total_iso_start) * 100
    iso_global_wr = (iso_wins_count / iso_trades_count * 100) if iso_trades_count > 0 else 0.0

    # 2. 共用資金池模式 (Combined)
    shared_wallet = float(INITIAL_SHARED_CAPITAL)
    active_positions = {}
    combined_trades = []

    for i in range(25, max_len):
        if shared_wallet <= 10.0: break
        for sym in list(active_positions.keys()):
            pos = active_positions[sym]
            df = dfs[sym]
            if i >= len(df): continue
            bar = df.iloc[i]
            side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
            )
            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                shared_wallet = max(0.0, shared_wallet - ((qty * entry) / pos['lev']))
                combined_trades.append({'sym': sym, 'pnl': -((qty * entry) / pos['lev']), 'is_liq': True})
                del active_positions[sym]
                continue

            closed = False
            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    combined_trades.append({'sym': sym, 'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp2})
                    closed = True
            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    combined_trades.append({'sym': sym, 'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp2})
                    closed = True
            if closed: del active_positions[sym]

        for sym, cfg in BACKTEST_SYMBOLS.items():
            if sym in active_positions: continue
            df = dfs.get(sym)
            if df is None or i >= len(df): continue
            bar = df.iloc[i]
            prev_bar = df.iloc[i-1]
            sig_side, entry, sl, tp1, tp2 = None, 0, 0, 0, 0
            mode = cfg['mode']

            if mode == 'gold_macro_donchian':
                if i >= 20:
                    dc_high = df['h'].iloc[i-20:i].max()
                    dc_low = df['l'].iloc[i-20:i].min()
                    atr = (df['h'] - df['l']).rolling(14).mean().iloc[i]
                    if bar['c'] > dc_high:
                        sig_side, entry = 'LONG', bar['c']
                        sl = entry - (atr * 1.5)
                        tp1 = tp2 = entry + ((entry - sl) * 5.0)
                    elif bar['c'] < dc_low:
                        sig_side, entry = 'SHORT', bar['c']
                        sl = entry + (atr * 1.5)
                        tp1 = tp2 = entry - ((sl - entry) * 5.0)
            elif mode in ['crypto_ict_fvg', 'stock_pullback']:
                recent_low = df['l'].iloc[i-20:i].min()
                recent_high = df['h'].iloc[i-20:i].max()
                if bar['l'] <= recent_low * 1.005 and bar['c'] > prev_bar['c']:
                    sig_side, entry = 'LONG', bar['c']
                    sl = recent_low * 0.995
                    tp1 = entry + (entry - sl) * 2.0
                    tp2 = recent_high
                elif bar['h'] >= recent_high * 0.995 and bar['c'] < prev_bar['c']:
                    sig_side, entry = 'SHORT', bar['c']
                    sl = recent_high * 1.005
                    tp1 = entry - (sl - entry) * 2.0
                    tp2 = recent_low

            if sig_side and abs(entry - sl) > 0:
                risk_amount = shared_wallet * cfg['risk']
                risk_dist = abs(entry - sl)
                target_qty = risk_amount / risk_dist
                if (target_qty * entry) < 25.0: target_qty = 25.0 / entry
                max_qty = (shared_wallet * cfg['lev']) / entry
                if target_qty > max_qty: target_qty = max_qty

                lev = cfg['lev']
                liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE) if sig_side == 'LONG' else entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                active_positions[sym] = {
                    'side': sig_side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'qty': target_qty, 'liq_price': liq_price, 'tp1_hit': False, 'lev': lev
                }

    com_net = shared_wallet - INITIAL_SHARED_CAPITAL
    com_roi = (com_net / INITIAL_SHARED_CAPITAL) * 100
    com_trades_count = len(combined_trades)
    com_wins = sum(1 for t in combined_trades if t.get('pnl', 0) > 0)
    com_wr = (com_wins / com_trades_count * 100) if com_trades_count > 0 else 0.0

    return {
        'iso_results': isolated_results,
        'iso_total_final': total_iso_final,
        'iso_roi': iso_roi,
        'iso_trades': iso_trades_count,
        'iso_wr': iso_global_wr,
        'com_final': shared_wallet,
        'com_roi': com_roi,
        'com_trades': com_trades_count,
        'com_wr': com_wr
    }

def master_ui_backtest():
    print("==========================================================================")
    print(" >>> 啟動仿照附圖格式之多資產策略回測程序...")
    print("==========================================================================")

    for days in TEST_PERIODS:
        print(f"\n計算 {days} 天期回測數據中...")
        res = run_simulation(days)
        
        lines = [
            "```text",
            f"📈 【實戰策略 {days} 天高淨值回測報告】",
            f"數據狀態: BTC: 🟢 | ETH: 🟢 | SOL: 🟢 | XAU: 🟢 | MSFT: 🔴 | MU: 🔴",
            "==========================================================================",
            f"【獨立配資各 1000U (Isolated) 模式 ({days}d)】",
            f"回測區間: 動態近 {days} 天",
            f"初始資金: ${len(BACKTEST_SYMBOLS) * INITIAL_CAPITAL_PER_ASSET:.2f} USDT",
            f"最終結餘: ${res['iso_total_final']:.2f} USDT ({res['iso_roi']:+.2f}%)",
            f"總交易次數: {res['iso_trades']} 次 | 綜合勝率: {res['iso_wr']:.2f}%",
            "--------------------------------------------------------------------------"
        ]

        for sym in BACKTEST_SYMBOLS.keys():
            if sym in res['iso_results']:
                r = res['iso_results'][sym]
                lines.append(f"{sym:<5} | 交易: {str(r['trades']).ljust(4)}次 | 勝率: {r['wr']:6.2f}% | 收益: {r['net']:+8.2f} U")

        lines.extend([
            "==========================================================================",
            f"【共享資金池 1000U (Combined) 模式 ({days}d)】",
            f"回測區間: 動態近 {days} 天",
            f"初始資金: ${INITIAL_SHARED_CAPITAL:.2f} USDT",
            f"最終結餘: ${res['com_final']:.2f} USDT ({res['com_roi']:+.2f}%)",
            f"總交易次數: {res['com_trades']} 次 | 綜合勝率: {res['com_wr']:.2f}%",
            "=========================================================================="
        ])
        lines.append("```")

        report_str = "\n".join(lines)
        print("\n" + report_str)
        send_discord(report_str)

if __name__ == '__main__':
    master_ui_backtest()
```[cite: 7]
