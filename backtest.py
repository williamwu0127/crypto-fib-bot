import os
import time
import json
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ==================== 1. 回測環境與標的配置 ====================
BASE_URL = "https://fapi.binance.com"

SYMBOLS_CONFIG = {
    'BTC':   {'s': 'BTCUSDT',   'interval': '15m', 'mode': 'ict_crypto',         'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'ETH':   {'s': 'ETHUSDT',   'interval': '15m', 'mode': 'ict_crypto',         'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'XAU':   {'s': 'PAXGUSDT',  'interval': '4h',  'mode': 'gold_donchian',      'lev': 10.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.0, 'trade': True},
    'TSM':   {'s': 'TSMUSDT',   'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'NVDA':  {'s': 'NVDAUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'AMD':   {'s': 'AMDUSDT',   'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'MSFT':  {'s': 'MSFTUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'AAPL':  {'s': 'AAPLUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'GOOGL': {'s': 'GOOGLUSDT', 'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'AMZN':  {'s': 'AMZNUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'META':  {'s': 'METAUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'TSLA':  {'s': 'TSLAUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'MU':    {'s': 'MUUSDT',    'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'GLW':   {'s': 'GLWUSDT',   'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'SPCX':  {'s': 'SPCXUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'SNDK':  {'s': 'SNDKUSDT',  'interval': '1h',  'mode': 'ict_stock_observe',  'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True}
}

def fetch_historical_klines(symbol, interval, days=365):
    print(f"📥 正在下載 {symbol} ({interval}) 最近 {days} 天歷史數據...", flush=True)
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    all_res = []
    
    current_start = start_time
    while current_start < end_time:
        url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={current_start}&limit=1500"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            all_res.extend(res)
            current_start = int(res[-1][0]) + 1
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ 下載 {symbol} 歷史數據出錯: {e}", flush=True)
            break
            
    if len(all_res) > 0:
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_res, columns=cols)
        for col in ['o', 'h', 'l', 'c', 'v']:
            df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        return df[['time', 'o', 'h', 'l', 'c', 'v']]
    return None

def run_backtest_for_symbol(sym_key, cfg):
    symbol = cfg['s']
    interval = cfg['interval']
    mode = cfg['mode']
    
    df = fetch_historical_klines(symbol, interval, days=365)
    df_4h = fetch_historical_klines(symbol, '4h', days=365)
    df_1d = fetch_historical_klines(symbol, '1d', days=365) if mode == 'gold_donchian' else None
    
    if df is None or len(df) < 100 or df_4h is None:
        print(f"❌ {sym_key} 歷史數據不足，跳過回測。") # 已修正變數名稱
        return None

    wallet = 100.0
    initial_wallet = 100.0
    position = None
    trades_history = []

    for i in range(50, len(df)):
        current_bar = df.iloc[i]
        curr_time = current_bar['time']
        price = current_bar['c']
        
        ny_time = curr_time.tz_localize('UTC').tz_convert('America/New_York') if curr_time.tz is None else curr_time.tz_convert('America/New_York')
        hour = ny_time.hour
        in_kill_zone = (2 <= hour < 5) or (7 <= hour < 10)

        if position is not None:
            side = position['side']
            entry = position['entry']
            sl = position['sl']
            tp1 = position['tp1']
            tp2 = position['tp2']
            qty = position['qty']
            
            hit_sl = (current_bar['l'] <= sl) if side == 'LONG' else (current_bar['h'] >= sl)
            hit_tp1 = (current_bar['h'] >= tp1) if side == 'LONG' else (current_bar['l'] <= tp1)
            hit_tp2 = (current_bar['h'] >= tp2) if side == 'LONG' else (current_bar['l'] <= tp2)

            if hit_sl:
                pnl = (sl - entry) * qty if side == 'LONG' else (entry - sl) * qty
                wallet += pnl
                trades_history.append({'type': 'SL', 'pnl': pnl})
                position = None
            elif hit_tp1 and not position.get('tp1_hit', False):
                position['tp1_hit'] = True
                position['sl'] = entry
                pnl_part = (tp1 - entry) * (qty * cfg['tp1_ratio']) if side == 'LONG' else (entry - tp1) * (qty * cfg['tp1_ratio'])
                wallet += pnl_part
                trades_history.append({'type': 'TP1', 'pnl': pnl_part})
            elif hit_tp2:
                rem_ratio = (1.0 - cfg['tp1_ratio']) if mode != 'gold_donchian' else 1.0
                pnl = (tp2 - entry) * (qty * rem_ratio) if side == 'LONG' else (entry - tp2) * (qty * rem_ratio)
                wallet += pnl
                trades_history.append({'type': 'TP2', 'pnl': pnl})
                position = None

        if position is None and in_kill_zone:
            sig_side = None
            entry_p, sl_p, tp1_p, tp2_p = 0, 0, 0, 0
            
            if mode != 'gold_donchian':
                sub = df.iloc[max(0, i-20):i]
                h_w, l_w = sub['h'].max(), sub['l'].min()
                wave = h_w - l_w
                
                if wave > 0:
                    if current_bar['c'] > current_bar['o'] and current_bar['l'] <= l_w + (wave * 0.382):
                        sig_side = 'LONG'
                        entry_p = price
                        sl_p = l_w * 0.998
                        risk_d = entry_p - sl_p
                        if risk_d > 0:
                            tp1_p = entry_p + (risk_d * cfg['tp1_r'])
                            tp2_p = entry_p + (risk_d * cfg['tp2_r'])
                    elif current_bar['c'] < current_bar['o'] and current_bar['h'] >= h_w - (wave * 0.382):
                        sig_side = 'SHORT'
                        entry_p = price
                        sl_p = h_w * 1.002
                        risk_d = sl_p - entry_p
                        if risk_d > 0:
                            tp1_p = entry_p - (risk_d * cfg['tp1_r'])
                            tp2_p = entry_p - (risk_d * cfg['tp2_r'])

            if sig_side and entry_p != sl_p:
                price_diff = abs(entry_p - sl_p)
                risk_amt = wallet * cfg['risk']
                target_qty = risk_amt / price_diff
                
                max_margin = wallet * 0.30
                max_val = max_margin * cfg['lev']
                if (target_qty * entry_p) > max_val:
                    target_qty = max_val / entry_p
                
                position = {
                    'side': sig_side,
                    'entry': entry_p,
                    'sl': sl_p,
                    'tp1': tp1_p,
                    'tp2': tp2_p,
                    'qty': target_qty,
                    'tp1_hit': False
                }

    total_trades = len(trades_history)
    wins = sum(1 for t in trades_history if t['pnl'] > 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    net_profit = wallet - initial_wallet
    
    return {
        'symbol': sym_key,
        'initial': initial_wallet,
        'final': wallet,
        'net_profit': net_profit,
        'return_pct': (net_profit / initial_wallet) * 100,
        'total_trades': total_trades,
        'win_rate': win_rate
    }

if __name__ == '__main__':
    print("=" * 65)
    print("🚀 啟動全標的一年期歷史回測引擎 (各 100 USDT 隔離資金)...")
    print("=" * 65)
    
    results = []
    for sym_key, cfg in SYMBOLS_CONFIG.items():
        res = run_backtest_for_symbol(sym_key, cfg)
        if res:
            results.append(res)
            print(f"📊 標的: {sym_key.ljust(5)} | 最終資金: {res['final']:>8.2f} USDT | 收益率: {res['return_pct']:>6.2f}% | 交易次數: {res['total_trades']:>3} | 勝率: {res['win_rate']:>5.1f}%")

    print("\n" + "=" * 65)
    print("🎯 一年期回測總結報告已完成！")
    print("=" * 65)
