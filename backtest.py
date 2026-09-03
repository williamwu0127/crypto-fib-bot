"""
Multi-Asset Combined Portfolio Backtest Engine (30 Days & 365 Days)
================================================================================
【合併倉位多資產策略回測程序 (30天與365天期)】
1. 策略配置:
   - ETH / SOL (crypto_ict_fvg): ICT 流動性獵取與 FVG 回踩 / 20x 槓桿 / 1% 風控[cite: 6]
   - XAU (gold_macro_donchian): 4H 唐奇安通道突破 / 20x 槓桿 / 1% 風控 / 5.0R 止盈[cite: 6]
   - MSFT / MU (stock_pullback): 1H 均線回撤 / 10x 槓桿 / 1% 風控[cite: 6]
2. 合併倉位架構 (Combined Portfolio):
   - 採用單一共享 1000.0 USDT 資金池進行動態複利，所有標的共用現金與保證金，真實模擬實盤合併資金運作。
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

BACKTEST_SYMBOLS = {
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0, 'risk': 0.01},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0, 'risk': 0.01},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0, 'risk': 0.01},
    'MSFT': {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0, 'risk': 0.01},
    'MU':   {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0, 'risk': 0.01}
}

INITIAL_SHARED_CAPITAL = 1000.0
TEST_PERIODS = [30, 365]
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
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
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

def run_combined_portfolio_simulation(days):
    print(f"\n---------------- 開始執行 {days} 天期合併倉位回測 ----------------")
    
    # 載入所有標的的歷史數據
    dfs = {}
    max_len = 0
    for sym, cfg in BACKTEST_SYMBOLS.items():
        df = fetch_binance_klines(cfg['s'], cfg['interval'], days=days + 15)
        if df is not None and not df.empty:
            dfs[sym] = df
            if len(df) > max_len: max_len = len(df)

    shared_wallet = float(INITIAL_SHARED_CAPITAL)
    active_positions = {} # 記錄各標的的當前持倉
    trade_history = []

    # 模擬主迴圈（以時間軸對齊各資產）
    for i in range(25, max_len):
        if shared_wallet <= 10.0: break # 資金歸零保護

        # 1. 檢查並管理現有持倉
        for sym in list(active_positions.keys()):
            pos = active_positions[sym]
            df = dfs[sym]
            if i >= len(df): continue
            bar = df.iloc[i]
            
            side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
            )

            # 強平檢查
            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                shared_wallet -= (qty * entry) / pos['lev'] # 扣除保證金
                shared_wallet = max(0.0, shared_wallet)
                trade_history.append({'sym': sym, 'pnl': -((qty * entry) / pos['lev']), 'is_liq': True})
                del active_positions[sym]
                continue

            closed = False
            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    trade_history.append({'sym': sym, 'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry # 移動保本
                    trade_history.append({'sym': sym, 'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    trade_history.append({'sym': sym, 'pnl': pnl_tp2})
                    closed = True

            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    trade_history.append({'sym': sym, 'pnl': pnl})
                    closed = True
                elif not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry
                    trade_history.append({'sym': sym, 'pnl': pnl_tp1})
                elif pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    trade_history.append({'sym': sym, 'pnl': pnl_tp2})
                    closed = True

            if closed:
                del active_positions[sym]

        # 2. 掃描新進場訊號
        for sym, cfg in BACKTEST_SYMBOLS.items():
            if sym in active_positions: continue # 已持倉則跳過
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

    net_pnl = shared_wallet - INITIAL_SHARED_CAPITAL
    roi = (net_pnl / INITIAL_SHARED_CAPITAL) * 100
    is_liq = shared_wallet <= 10.0
    total_trades = len(trade_history)
    wins = sum(1 for t in trade_history if t.get('pnl', 0) > 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    return shared_wallet, roi, total_trades, win_rate, is_liq

def master_combined_backtest():
    print("==========================================================================")
    print(" >>> 啟動合併倉位策略【30天與365天】回測程序...")
    print("==========================================================================")

    results = {}
    for days in TEST_PERIODS:
        final_w, roi, trades, wr, is_liq = run_combined_portfolio_simulation(days)
        results[days] = {'final': final_w, 'roi': roi, 'trades': trades, 'wr': wr, 'liq': is_liq}
        status_txt = "爆倉" if is_liq else f"${final_w:.1f} ({roi:+.1f}%)"
        print(f"[{days}d] 合併倉位結算 -> 總資金: {status_txt} | 總交易筆數: {trades} | 勝率: {wr:.1f}%")

    # 組合 Markdown 報告
    report_lines = [
        "```text",
        "【合併倉位多資產策略回測報告 (共用 1000U 資金池)】",
        "==========================================================================",
        f"{'回測週期':<10} | {'最終總資金':<15} | {'總報酬率 (ROI)':<16} | {'總交易筆數':<12} | {'勝率':<8}",
        "--------------------------------------------------------------------------"
    ]

    for days in TEST_PERIODS:
        res = results[days]
        if res['liq']: val_str = "爆倉清算 ($0)"
        else: val_str = f"${res['final']:.1f}"
        roi_str = f"{res['roi']:+.1f}%"
        report_lines.append(
            f"{f'{days}天期'.ljust(10)} | {val_str.ljust(15)} | {roi_str.ljust(16)} | {str(res['trades']).ljust(12)} | {f'{res["wr"]:.1f}%'.ljust(8)}"
        )

    report_lines.append("==========================================================================")
    report_lines.append("配置說明: 合併資金池共用現金與保證金 | ETH/SOL/XAU (20x) | MSFT/MU (10x)")
    report_lines.append("```")

    final_report = "\n".join(report_lines)
    print("\n" + final_report)
    send_discord(final_report)

if __name__ == '__main__':
    master_combined_backtest()
