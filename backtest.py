"""
Multi-Asset Quantitative Backtest Engine (365 Days - Breakout Hunter Edition)
============================================================
【實盤策略規則說明】
1. BTC / ETH 實盤策略 (1% 風控 - 4H 突破獵人模式):
   - 宏觀定錨: 1D 日線 EMA50 (價格 >= EMA50 僅做多，反之僅做空)
   - 突破進場: 4H 唐奇安通道 (Donchian 20) 突破 + RSI 動能確認
   - 風控防守: 1.5 ATR 初始止損 (給予大波段足夠呼吸空間)
   - 動態保本: 浮盈達到 2.0R 時自動將止損平移至開倉價 (保本)
   - 終極止盈: 追求 5.0R 盈虧比全額止盈 (大魚吃小蝦，捕捉狂暴大趨勢)

2. XAU (黃金) 實盤策略 (5% 風控 / 10x 槓桿):
   - 宏觀定錨: 1D 日線 MA60 -> 4H 唐奇安突破 -> 1.5 ATR (2.0R保本/5.0R止盈)[span_0](start_span)[span_0](end_span)
============================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS = {
    'BTC': {'s': 'BTCUSDT', 'interval': '4h', 'mode': 'crypto_breakout'},
    'ETH': {'s': 'ETHUSDT', 'interval': '4h', 'mode': 'crypto_breakout'},
    'XAU': {'s': 'PAXGUSDT', 'interval': '4h', 'mode': 'gold_macro_donchian'}
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
    
    step_ms = (4 * 60 * 60 * 1000) if interval == '4h' else (24 * 60 * 60 * 1000)

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

def run_365d_backtest():
    days = 365
    period_title = "365 天期 (突破獵人策略版)"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】多資產量化回測...")
    print(f"==================================================")

    wallet = float(INITIAL_WALLET)
    completed_trades = []

    for sym, cfg in SYMBOLS.items():
        print(f"拉取 {sym} 歷史數據 (回測天數: {days} 天)...", flush=True)
        
        # 共用突破獵人與日線過濾邏輯
        df_4h = fetch_binance_klines(cfg['s'], '4h', days=days + 30)
        df_1d = fetch_binance_klines(cfg['s'], '1d', days=days + 60)
        if df_4h is None or df_1d is None:
            continue

        if sym == 'XAU':
            df_1d['ma60'] = df_1d['c'].rolling(60).mean()
            df_1d['d_date'] = df_1d['time'].dt.floor('D')
            d_map = df_1d.set_index('d_date')['c'].gt(df_1d.set_index('d_date')['ma60']).to_dict()
            risk_pct = 0.05  # 黃金 5% 風險
        else:
            df_1d['ema50'] = df_1d['c'].ewm(span=50, adjust=False).mean()
            df_1d['d_date'] = df_1d['time'].dt.floor('D')
            d_map = df_1d.set_index('d_date')['c'].ge(df_1d.set_index('d_date')['ema50']).to_dict()
            risk_pct = 0.01  # 加密貨幣 1% 風險

        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_4h['macro_bull'] = df_4h['d_date'].map(d_map).ffill().fillna(True)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        
        tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        # 計算 RSI 輔助動能確認
        delta = df_4h['c'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df_4h['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

        pos = None
        for i in range(30, len(df_4h)):
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
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True
                    if bar['h'] >= pos['sl']:
                        pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                        wallet += pnl
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue
                    if bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        pos = None
                        continue

            if pos is None and wallet > 5.0:
                bull = bar['macro_bull']
                rsi_val = bar['rsi']
                
                # 多頭突破 + RSI 動能確認
                if bull and bar['c'] > bar['dc_high'] and rsi_val > 55:
                    entry = bar['c']
                    sl = entry - (bar['atr'] * 1.5)
                    risk_dist = entry - sl
                    if risk_dist > 0:
                        qty = (wallet * risk_pct) / risk_dist
                        if sym == 'XAU' and (qty * entry) > (wallet * 10.0):
                            qty = (wallet * 10.0) / entry
                        pos = {
                            'side': 'LONG', 'entry': entry, 'sl': sl, 
                            'tp': entry + (risk_dist * 5.0), 
                            'be_target': entry + (risk_dist * 2.0), 
                            'qty': qty, 'is_be_moved': False
                        }
                # 空頭跌破 + RSI 動能確認
                elif not bull and bar['c'] < bar['dc_low'] and rsi_val < 45:
                    entry = bar['c']
                    sl = entry + (bar['atr'] * 1.5)
                    risk_dist = sl - entry
                    if risk_dist > 0:
                        qty = (wallet * risk_pct) / risk_dist
                        if sym == 'XAU' and (qty * entry) > (wallet * 10.0):
                            qty = (wallet * 10.0) / entry
                        pos = {
                            'side': 'SHORT', 'entry': entry, 'sl': sl, 
                            'tp': entry - (risk_dist * 5.0), 
                            'be_target': entry - (risk_dist * 2.0), 
                            'qty': qty, 'is_be_moved': False
                        }

    total_trades = len(completed_trades)
    win_trades = sum(1 for t in completed_trades if t['pnl'] > 0)
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_stats = {}
    for sym in SYMBOLS.keys():
        sym_trades = [t for t in completed_trades if t['sym'] == sym]
        sym_total = len(sym_trades)
        sym_wins = sum(1 for t in sym_trades if t['pnl'] > 0)
        sym_wr = (sym_wins / sym_total * 100) if sym_total > 0 else 0.0
        sym_pnl = sum(t['pnl'] for t in sym_trades)
        symbol_stats[sym] = {'total': sym_total, 'wins': sym_wins, 'wr': sym_wr, 'pnl': sym_pnl}

    report = (
        f"```text\n"
        f"【量化策略回測報告 - {period_title}】\n"
        f"----------------------------------------------------\n"
        f"策略架構:\n"
        f" - BTC/ETH: 1D 日線過濾 -> 4H 唐奇安突破 + RSI (1% 風控 / 5R目標)\n"
        f" - XAU(黃金): 1D MA60 -> 4H 唐奇安突破 -> 1.5 ATR (5% 風控/10x)[span_1](start_span)[span_1](end_span)\n"
        f"----------------------------------------------------\n"
        f"初始資金: ${INITIAL_WALLET:.2f} USDT\n"
        f"最終結餘: ${wallet:.2f} USDT ({roi:+.2f}%)\n"
        f"總成交次數: {total_trades} 次\n"
        f"總勝場數: {win_trades} 次 | 總敗場數: {loss_trades} 次\n"
        f"整體策略勝率: {win_rate:.2f}%\n"
        f"----------------------------------------------------\n"
        f"各標的績效與勝率統計:\n"
    )
    
    for sym, st in symbol_stats.items():
        report += f" - {sym.ljust(4)} | 次數: {str(st['total']).ljust(3)} 筆 | 勝率: {st['wr']:6.2f}% | 淨利: {st['pnl']:+6.2f} USDT\n"
    
    report += "```"
    
    print(report)
    send_discord(report)

if __name__ == '__main__':
    run_365d_backtest()
