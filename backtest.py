import os
import time
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ==================== 1. 回測環境與標的配置 (改用現貨 API 確保數據穩定) ====================
BASE_URL = "https://api.binance.com"

SYMBOLS_CONFIG = {
    'BTC':   {'s': 'BTCUSDT',   'interval': '15m', 'mode': 'ict_crypto',         'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'ETH':   {'s': 'ETHUSDT',   'interval': '15m', 'mode': 'ict_crypto',         'lev': 10.0, 'risk': 0.05, 'tp1_r': 1.5, 'tp2_r': 3.0, 'tp1_ratio': 0.5, 'trade': True},
    'XAU':   {'s': 'PAXGUSDT',  'interval': '4h',  'mode': 'gold_donchian',      'lev': 10.0, 'risk': 0.05, 'tp1_r': 2.0, 'tp2_r': 5.0, 'tp1_ratio': 0.0, 'trade': True},
}

# ==================== 2. 現貨歷史數據抓取函式 ====================
def get_market_data(symbol, interval, limit=1000):
    try:
        url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=10).json()
        if isinstance(res, list) and len(res) > 0:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(res, columns=cols)
            for col in ['o', 'h', 'l', 'c', 'v']:
                df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms')
            print(f"✅ {symbol} ({interval}) 成功載入 {len(df)} 筆歷史 K 線。", flush=True)
            return df[['time', 'o', 'h', 'l', 'c', 'v']]
    except Exception as e:
        print(f"⚠️ {symbol} ({interval}) 行情獲取失敗: {e}", flush=True)
    return None

# ==================== 3. 模擬回測核心引擎 ====================
def run_backtest_for_symbol(sym_key, cfg):
    symbol = cfg['s']
    interval = cfg['interval']
    mode = cfg['mode']
    
    df = get_market_data(symbol, interval, limit=1000)
    
    if df is None or len(df) < 50:
        print(f"❌ {sym_key} 歷史數據不足，跳過回測。")
        return None

    wallet = 100.0
    initial_wallet = 100.0
    position = None
    trades_history = []

    for i in range(20, len(df)):
        current_bar = df.iloc[i]
        curr_time = current_bar['time']
        price = current_bar['c']
        
        # 時區轉換與 Kill Zone 判定
        ny_time = curr_time.tz_localize('UTC').tz_convert('America/New_York') if curr_time.tz is None else curr_time.tz_convert('America/New_York')
        hour = ny_time.hour
        in_kill_zone = (2 <= hour < 5) or (7 <= hour < 10)

        # 1. 持倉防守檢查 (SL / TP)
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

        # 2. 無持倉時在 Kill Zone 尋找進場訊號
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
    print("🚀 啟動幣安現貨歷史數據回測引擎 (各 100 USDT 隔離資金)...")
    print("=" * 65)
    
    results = []
    for sym_key, cfg in SYMBOLS_CONFIG.items():
        res = run_backtest_for_symbol(sym_key, cfg)
        if res:
            results.append(res)
            print(f"📊 標的: {sym_key.ljust(5)} | 最終資金: {res['final']:>8.2f} USDT | 收益率: {res['return_pct']:>6.2f}% | 交易次數: {res['total_trades']:>3} | 勝率: {res['win_rate']:>5.1f}%")

    print("\n" + "=" * 65)
    print("🎯 回測總結報告已完成！")
    print("=" * 65)
