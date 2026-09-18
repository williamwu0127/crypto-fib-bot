import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ==============================================================================
# 1. 核心參數設定 (v5 實盤完全對齊)
# ==============================================================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

BACKTEST_SYMBOLS = {
    'BTC':   {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': False},
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': True},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'trade': True},
    'MSFT':  {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'trade': False},
    'MU':    {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'trade': False},
    'BNB':   {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': False},
    'DOGE':  {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': False},
    'NVDA':  {'s': 'NVDAUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 20.0,  'trade': False},
    'AAPL':  {'s': 'AAPLUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 20.0,  'trade': False}
}

TEST_DAYS = 365
INITIAL_CAPITAL = 1000.0
RISK_PCT = 0.01
FEE_RATE = 0.0004
MIN_NOTIONAL = 25.0

# ==============================================================================
# 2. 資料獲取與多時區 (MTF) K 線重採樣
# ==============================================================================
def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=10)
        except:
            pass

def fetch_binance_klines(symbol, interval, days):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    endpoints = [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://data-api.binance.vision/api/v3/klines",
        "https://api-gcp.binance.com/api/v3/klines"
    ]
    
    for base_url in endpoints:
        all_klines = []
        curr_start = start_ms
        success = True
        
        while curr_start < end_ms:
            url = f"{base_url}?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
            try:
                res = requests.get(url, headers=headers, timeout=8)
                if res.status_code != 200:
                    success = False
                    break
                data = res.json()
                if not isinstance(data, list) or len(data) == 0:
                    break
                all_klines.extend(data)
                curr_start = data[-1][0] + 1
                time.sleep(0.04)
            except:
                success = False
                break
                
        if success and len(all_klines) > 0:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
            for col in ['o', 'h', 'l', 'c', 'v']:
                df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms')
            return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
            
    return None

def resample_klines(df, rule):
    df_res = df.set_index('time').resample(rule).agg({
        'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
    }).dropna().reset_index()
    return df_res

# ==============================================================================
# 3. v5 策略事件提取 (ICT 與黃金唐奇安)
# ==============================================================================
def get_ict_htf_signals(df_htf):
    biases, fvgs, exts = [], [], []
    for i in range(len(df_htf)):
        if i < 25:
            biases.append(None); fvgs.append(0); exts.append(0)
            continue
            
        recent_low = df_htf['l'].iloc[i-21:i-2].min()
        recent_high = df_htf['h'].iloc[i-21:i-2].max()
        curr = df_htf.iloc[i]
        prev = df_htf.iloc[i-1]
        b, f, e = None, 0, 0
        
        if (prev['l'] < recent_low and prev['c'] > recent_low) or (curr['l'] < recent_low and curr['c'] > recent_low):
            for j in range(i-5, i-1):
                if df_htf['l'].iloc[j] > df_htf['h'].iloc[j-2]:
                    b = 'LONG'
                    f = df_htf['h'].iloc[j-2] + (df_htf['l'].iloc[j] - df_htf['h'].iloc[j-2]) * 0.618
                    e = recent_high
                    break
        elif (prev['h'] > recent_high and prev['c'] < recent_high) or (curr['h'] > recent_high and curr['c'] < recent_high):
            for j in range(i-5, i-1):
                if df_htf['h'].iloc[j] < df_htf['l'].iloc[j-2]:
                    b = 'SHORT'
                    f = df_htf['h'].iloc[j] + (df_htf['l'].iloc[j-2] - df_htf['h'].iloc[j]) * 0.618
                    e = recent_low
                    break
                    
        biases.append(b); fvgs.append(f); exts.append(e)
        
    return pd.DataFrame({'time': df_htf['time'], 'bias': biases, 'fvg': fvgs, 'ext': exts})

def extract_crypto_ict_trades(sym, df_15m, cfg):
    df_4h = resample_klines(df_15m, '4h')
    df_1h = resample_klines(df_15m, '1h')
    
    sig_4h = get_ict_htf_signals(df_4h)
    sig_1h = get_ict_htf_signals(df_1h)
    
    sig_4h['valid_time'] = sig_4h['time'] + pd.Timedelta(hours=4)
    sig_1h['valid_time'] = sig_1h['time'] + pd.Timedelta(hours=1)
    
    sig_4h_merge = sig_4h.drop(columns=['time']).rename(columns={'bias':'b4', 'fvg':'f4', 'ext':'e4'})
    sig_1h_merge = sig_1h.drop(columns=['time']).rename(columns={'bias':'b1', 'fvg':'f1', 'ext':'e1'})
    
    df = pd.merge_asof(df_15m, sig_4h_merge, left_on='time', right_on='valid_time', direction='backward')
    df = pd.merge_asof(df, sig_1h_merge, left_on='time', right_on='valid_time', direction='backward')
    
    trades = []
    pos = None
    
    for i in range(25, len(df)):
        bar = df.iloc[i]
        
        if pos is not None:
            side, entry, sl = pos['side'], pos['entry'], pos['sl']
            tp1, tp2 = pos['tp1'], pos['tp2']
            closed = False
            
            if side == 'LONG':
                if bar['l'] <= pos['sl']:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': pos['tp1_hit']})
                    closed = True
                elif not pos['tp1_hit'] and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pos['sl'] = entry
                    pos['saved_exit1'] = tp1
                elif pos['tp1_hit'] and bar['h'] >= tp2:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['saved_exit1'], 'exit2': tp2, 'split': True})
                    closed = True
            else:
                if bar['h'] >= pos['sl']:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': pos['tp1_hit']})
                    closed = True
                elif not pos['tp1_hit'] and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pos['sl'] = entry
                    pos['saved_exit1'] = tp1
                elif pos['tp1_hit'] and bar['l'] <= tp2:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['saved_exit1'], 'exit2': tp2, 'split': True})
                    closed = True
            if closed: pos = None
            
        if pos is None:
            bias = bar['b4'] if pd.notna(bar['b4']) else bar['b1']
            if pd.isna(bias): continue
            fvg = bar['f4'] if pd.notna(bar['b4']) else bar['f1']
            ext = bar['e4'] if pd.notna(bar['b4']) else bar['e1']
            
            if bias == 'LONG':
                window = df.iloc[max(0, i-24):i]
                min_idx = window['l'].idxmin()
                ob_window = df.iloc[max(0, min_idx-3):min(len(df), min_idx+3)]
                ob_reds = ob_window[ob_window['c'] < ob_window['o']]
                if not ob_reds.empty:
                    ob = ob_reds.iloc[-1]
                    if bar['l'] <= ob['h'] and bar['c'] >= ob['l']:
                        sl_price = ob['l'] * 0.999
                        pos = {'side': 'LONG', 'entry': bar['c'], 'init_sl': sl_price, 'sl': sl_price, 'tp1': fvg, 'tp2': ext, 'tp1_hit': False, 'entry_time': bar['time']}
            elif bias == 'SHORT':
                window = df.iloc[max(0, i-24):i]
                max_idx = window['h'].idxmax()
                ob_window = df.iloc[max(0, max_idx-3):min(len(df), max_idx+3)]
                ob_grns = ob_window[ob_window['c'] > ob_window['o']]
                if not ob_grns.empty:
                    ob = ob_grns.iloc[-1]
                    if bar['h'] >= ob['l'] and bar['c'] <= ob['h']:
                        sl_price = ob['h'] * 1.001
                        pos = {'side': 'SHORT', 'entry': bar['c'], 'init_sl': sl_price, 'sl': sl_price, 'tp1': fvg, 'tp2': ext, 'tp1_hit': False, 'entry_time': bar['time']}

    return trades

def extract_gold_donchian_trades(sym, df_4h, cfg):
    df_1d = resample_klines(df_4h, '1d')
    df_1d['ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['valid_time'] = df_1d['time'] + pd.Timedelta(days=1)
    
    df = pd.merge_asof(df_4h, df_1d[['valid_time', 'ma60']], left_on='time', right_on='valid_time', direction='backward')
    df['dc_high'] = df['h'].shift(1).rolling(20).max()
    df['dc_low'] = df['l'].shift(1).rolling(20).min()
    
    trades = []
    pos = None
    
    for i in range(25, len(df)):
        bar = df.iloc[i]
        
        if pos is not None:
            side, entry = pos['side'], pos['entry']
            be_tgt, tp = pos['be_target'], pos['tp']
            closed = False
            
            if side == 'LONG':
                if not pos['be_moved'] and bar['h'] >= be_tgt:
                    pos['sl'] = entry
                    pos['be_moved'] = True
                if bar['l'] <= pos['sl']:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': False})
                    closed = True
                elif bar['h'] >= tp:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': tp, 'exit2': tp, 'split': False})
                    closed = True
            else:
                if not pos['be_moved'] and bar['l'] <= be_tgt:
                    pos['sl'] = entry
                    pos['be_moved'] = True
                if bar['h'] >= pos['sl']:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': False})
                    closed = True
                elif bar['l'] <= tp:
                    trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'sl': pos['init_sl'], 'exit1': tp, 'exit2': tp, 'split': False})
                    closed = True
            if closed: pos = None
            
        if pos is None:
            ma, dc_h, dc_l = bar['ma60'], bar['dc_high'], bar['dc_low']
            if pd.isna(ma) or pd.isna(dc_h) or pd.isna(dc_l): continue
            
            # v5 結構止損：對向軌 + 1.5R 保本 / 3.5R 止盈
            if bar['c'] > ma and bar['c'] > dc_h:
                entry = bar['c']
                sl = dc_l * 0.999
                risk = entry - sl
                pos = {'side': 'LONG', 'entry': entry, 'init_sl': sl, 'sl': sl, 'be_target': entry + (risk * 1.5), 'tp': entry + (risk * 3.5), 'be_moved': False, 'entry_time': bar['time']}
            elif bar['c'] < ma and bar['c'] < dc_l:
                entry = bar['c']
                sl = dc_h * 1.001
                risk = sl - entry
                pos = {'side': 'SHORT', 'entry': entry, 'init_sl': sl, 'sl': sl, 'be_target': entry - (risk * 1.5), 'tp': entry - (risk * 3.5), 'be_moved': False, 'entry_time': bar['time']}

    return trades

# ==============================================================================
# 4. v5 動態部位換算與結算
# ==============================================================================
def calc_trade_pnl(wallet, trade, cfg):
    entry, side, split = trade['entry'], trade['side'], trade['split']
    exit1, exit2 = trade['exit1'], trade['exit2']
    init_sl = trade['sl']
    
    price_diff = abs(entry - init_sl)
    if price_diff <= 0: return 0.0
    
    # 嚴格對齊 v5 動態風控模型
    risk_amount = wallet * RISK_PCT
    target_qty = risk_amount / price_diff
    notional = target_qty * entry
    
    if notional < MIN_NOTIONAL: notional = MIN_NOTIONAL
    if notional > wallet * cfg['lev']: notional = wallet * cfg['lev']
    
    if side == 'LONG':
        ret1 = (exit1 - entry) / entry
        ret2 = (exit2 - entry) / entry
    else:
        ret1 = (entry - exit1) / entry
        ret2 = (entry - exit2) / entry
        
    avg_ret = (0.5 * ret1 + 0.5 * ret2) if split else ret1
    pnl = (notional * avg_ret) - (notional * FEE_RATE * 2)
    return pnl

# ==============================================================================
# 5. 主回測執行與雙模式報表生成
# ==============================================================================
def run_v5_full_backtest():
    print("=" * 72)
    print(" >>> 啟動 v5 實盤完全體【365天期 1000U 個別/共池】量化回測引擎...")
    print("=" * 72)

    data_status = {}
    master_trades = []

    for sym, cfg in BACKTEST_SYMBOLS.items():
        if not cfg['trade']:
            data_status[sym] = '⚪ (觀測)'
            continue
            
        print(f"📥 正在抓取並計算 {sym} ({cfg['interval']})...")
        df = fetch_binance_klines(cfg['s'], cfg['interval'], TEST_DAYS + 30)
        
        if df is not None and not df.empty and len(df) > 100:
            data_status[sym] = '🟢'
            if cfg['mode'] == 'crypto_ict_fvg':
                sym_trades = extract_crypto_ict_trades(sym, df, cfg)
            else:
                sym_trades = extract_gold_donchian_trades(sym, df, cfg)
            master_trades.extend(sym_trades)
        else:
            data_status[sym] = '🔴'

    # --- A. 獨立配資模式 (Isolated 各 1000U) ---
    iso_results = {}
    iso_total_final = 0.0
    
    for sym, cfg in BACKTEST_SYMBOLS.items():
        if not cfg['trade'] or data_status.get(sym) == '🔴': continue
        w_iso = INITIAL_CAPITAL
        sym_t = [t for t in master_trades if t['sym'] == sym]
        sym_wins = 0
        
        for t in sym_t:
            pnl = calc_trade_pnl(w_iso, t, cfg)
            w_iso += pnl
            if pnl > 0: sym_wins += 1
            if w_iso <= 10.0: break
            
        trades_count = len(sym_t)
        wr = (sym_wins / trades_count * 100) if trades_count > 0 else 0.0
        iso_results[sym] = {'final': w_iso, 'net': w_iso - INITIAL_CAPITAL, 'trades': trades_count, 'wr': wr}
        iso_total_final += w_iso

    # --- B. 共享資金池模式 (Combined 總共 1000U) ---
    master_trades.sort(key=lambda x: x['entry_time'])
    com_wallet = INITIAL_CAPITAL
    com_wins = 0
    com_trades_count = 0
    
    for t in master_trades:
        if com_wallet <= 10.0: break
        cfg = BACKTEST_SYMBOLS[t['sym']]
        pnl = calc_trade_pnl(com_wallet, t, cfg)
        com_wallet += pnl
        com_trades_count += 1
        if pnl > 0: com_wins += 1

    com_net = com_wallet - INITIAL_CAPITAL
    com_roi = (com_net / INITIAL_CAPITAL) * 100
    com_wr = (com_wins / com_trades_count * 100) if com_trades_count > 0 else 0.0

    iso_start_total = len(iso_results) * INITIAL_CAPITAL
    iso_roi = ((iso_total_final - iso_start_total) / iso_start_total * 100) if iso_start_total > 0 else 0.0

    status_str = " | ".join([f"{sym}: {data_status.get(sym)}" for sym in BACKTEST_SYMBOLS.keys()])
    
    lines = [
        "```text",
        f"📈 【實戰策略 v5 完全體 365 天高淨值回測報告】",
        f"數據狀態: {status_str}",
        "==========================================================================",
        f"【獨立配資各 1000U (Isolated) 模式 (365d)】",
        f"初始總資金: ${iso_start_total:.2f} USDT",
        f"最終總結餘: ${iso_total_final:.2f} USDT ({iso_roi:+.2f}%)",
        "--------------------------------------------------------------------------"
    ]

    for sym in BACKTEST_SYMBOLS.keys():
        if sym in iso_results:
            st = iso_results[sym]
            lines.append(f"{sym:<5} | 交易: {str(st['trades']).ljust(4)}次 | 勝率: {st['wr']:6.2f}% | 收益: {st['net']:+8.2f} U")

    lines.extend([
        "==========================================================================",
        f"【共享資金池 1000U (Combined) 模式 (365d)】",
        f"回放機制: 事件驅動 (Event-Driven Chronological)",
        f"單筆風控: 總資金 1% (低標 25U 防呆)",
        f"初始資金: ${INITIAL_CAPITAL:.2f} USDT",
        f"最終結餘: ${com_wallet:.2f} USDT ({com_roi:+.2f}%)",
        f"總交易次數: {com_trades_count} 次 | 綜合勝率: {com_wr:.2f}%",
        "=========================================================================="
    ])
    lines.append("```")

    report_str = "\n".join(lines)
    print("\n" + report_str)
    send_discord(report_str)

if __name__ == '__main__':
    run_v5_full_backtest()
