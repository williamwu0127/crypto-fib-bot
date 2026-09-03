"""
Multi-Tier Quantitative Backtest Engine (30 Days & 365 Days)
================================================================================
【多資金水位比較回測程序 (100U / 1000U / 10000U)】
1. 策略配置:
   - ETH / SOL (crypto_ict_fvg): ICT 核心流動性獵取與 FVG 回踩 / 20x 槓桿 / 1% 風控
   - XAU (gold_macro_donchian): 4H 唐奇安通道突破 / 20x 槓桿 / 1% 風控 / 5.0R 止盈
   - MSFT / MU (stock_pullback): 1H 均線回撤 / 10x 槓桿 / 1% 風控
2. 資金水位:
   - Tier 1: 100.0 USDT (低本金起步，受限於幣安 5 USDT 名義價值下限的磨損效應)
   - Tier 2: 1,000.0 USDT (標準個人資金水位，複利曲線穩定)
   - Tier 3: 10,000.0 USDT (機構/大資金水位，受流動性與滑點影響較小)
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

# 回測標的與交易邏輯映射
BACKTEST_SYMBOLS = {
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0, 'risk': 0.01},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0, 'risk': 0.01},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0, 'risk': 0.01},
    'MSFT': {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0, 'risk': 0.01},
    'MU':   {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0, 'risk': 0.01}
}

CAPITAL_TIERS = [100.0, 1000.0, 10000.0]
TEST_PERIODS = [30, 365] # 30天與365天
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

def run_simulation_for_asset(df, mode, lev, risk_pct, initial_wallet):
    wallet = float(initial_wallet)
    completed_trades = []
    pos = None

    for i in range(25, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i-1]

        # 1. 現有持倉管理
        if pos is not None:
            side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
            )

            # 強平檢查
            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                wallet = 0.0
                completed_trades.append({'pnl': -wallet, 'is_liq': True})
                break

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
                    pos['sl'] = entry # 移動至保本
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

        # 2. 開倉信號掃描
        if pos is None and wallet > 10.0:
            sig_side, entry, sl, tp1, tp2 = None, 0, 0, 0, 0

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
                ema20 = bar['c'] # 簡化向量比對
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
                risk_amount = wallet * risk_pct
                risk_dist = abs(entry - sl)
                target_qty = risk_amount / risk_dist
                
                # 幣安名義價值限制防護 (>= 25 USDT)
                if (target_qty * entry) < 25.0:
                    target_qty = 25.0 / entry

                # 確保不超過可用槓桿保證金上限
                max_qty = (wallet * lev) / entry
                if target_qty > max_qty: target_qty = max_qty

                liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE) if sig_side == 'LONG' else entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                
                pos = {
                    'side': sig_side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'qty': target_qty, 'liq_price': liq_price, 'tp1_hit': False
                }

    net_pnl = wallet - initial_wallet
    roi = (net_pnl / initial_wallet) * 100
    is_liq = wallet <= 0.0
    return wallet, roi, is_liq

def master_multi_tier_backtest():
    print("==========================================================================")
    print(" >>> 啟動多資產實盤策略【30天與365天 × 100U / 1000U / 10000U】對比回測...")
    print("==========================================================================")

    matrix_results = {}

    for days in TEST_PERIODS:
        matrix_results[days] = {}
        print(f"\n---------------- 正在計算 {days} 天期回測數據 ----------------")
        
        for sym, cfg in BACKTEST_SYMBOLS.items():
            df = fetch_binance_klines(cfg['s'], cfg['interval'], days=days + 15)
            if df is None or df.empty: continue
            
            matrix_results[days][sym] = {}
            for tier in CAPITAL_TIERS:
                final_w, roi, is_liq = run_simulation_for_asset(df, cfg['mode'], cfg['lev'], cfg['risk'], tier)
                matrix_results[days][sym][tier] = {'final': final_w, 'roi': roi, 'liq': is_liq}
                status_txt = "爆倉" if is_liq else f"${final_w:.1f} ({roi:+.1f}%)"
                print(f"[{days}d] {sym:<5} | 水位 ${tier:<6.0f} -> 結算: {status_txt}")

    # 組合 Markdown 比較報表
    report_lines = [
        "```text",
        "【實盤策略多資金水位與週期比較回測報告】",
        "==========================================================================",
        f"{'週期':<6} | {'標的':<5} | {'100U 水位結算 (ROI)':<22} | {'1000U 水位結算 (ROI)':<22} | {'10000U 水位結算 (ROI)':<23}",
        "--------------------------------------------------------------------------"
    ]

    for days in TEST_PERIODS:
        for sym in BACKTEST_SYMBOLS.keys():
            if days in matrix_results and sym in matrix_results[days]:
                row_items = [f"{days}d".ljust(6), sym.ljust(5)]
                for tier in CAPITAL_TIERS:
                    res = matrix_results[days][sym][tier]
                    if res['liq']: val_str = "爆倉清算 ($0)"
                    else: val_str = f"${res['final']:.1f} ({res['roi']:+.1f}%)"
                    row_items.append(f"{val_str:<22}")
                report_lines.append(" | ".join(row_items))

    report_lines.append("==========================================================================")
    report_lines.append("配置說明: ETH/SOL/XAU (20x槓桿, 1%風控) | MSFT/MU (10x槓桿, 1%風控)")
    report_lines.append("```")

    final_report = "\n".join(report_lines)
    print("\n" + final_report)
    send_discord(final_report)

if __name__ == '__main__':
    master_multi_tier_backtest()
