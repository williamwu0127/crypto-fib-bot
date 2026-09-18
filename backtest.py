import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ==============================================================================
# 1. 核心參數與設定
# ==============================================================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

BACKTEST_SYMBOLS = {
    'BTC':   {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': True},
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': True},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'trade': True},
    'MSFT':  {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'trade': True},
    'MU':    {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'trade': True},
    'BNB':   {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'DOGE':  {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'NVDA':  {'s': 'NVDAUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 20.0,  'trade': True},
    'AAPL':  {'s': 'AAPLUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 20.0,  'trade': True}
}

TEST_DAYS = 365
INITIAL_CAPITAL = 1000.0
RISK_PCT = 0.01
FEE_RATE = 0.0004
MAINTENANCE_MARGIN_RATE = 0.005

# ==============================================================================
# 2. 抗雲端阻擋之幣安 API 抓取模組
# ==============================================================================
def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=10)
        except Exception:
            pass

def fetch_binance_stealth_klines(symbol, interval, days):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    
    # 偽裝成常規瀏覽器以繞過 Cloudflare
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Referer': 'https://www.binance.com/'
    }
    
    # 優先使用 fapi (合約 API)，備用 GCP 與 Vision 節點
    endpoints = [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api-gcp.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines"
    ]
    
    for base_url in endpoints:
        all_klines = []
        curr_start = start_ms
        success = True
        
        while curr_start < end_ms:
            url = f"{base_url}?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code != 200:
                    success = False
                    break
                data = res.json()
                if not isinstance(data, list) or len(data) == 0:
                    break
                all_klines.extend(data)
                curr_start = data[-1][0] + 1
                time.sleep(0.05)
            except Exception:
                success = False
                break
        
        if success and len(all_klines) > 0:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
            for col in ['o', 'h', 'l', 'c']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms')
            return df[['time', 'o', 'h', 'l', 'c']].sort_values('time').reset_index(drop=True)
            
    return None

def prepare_indicators(df, mode):
    if mode == 'gold_macro_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
        df['ma_trend'] = df['c'].rolling(360).mean() # 近似 1D MA60
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.015)
    elif mode in ['crypto_ict_fvg', 'stock_pullback']:
        df['recent_low'] = df['l'].rolling(20).min().shift(1)
        df['recent_high'] = df['h'].rolling(20).max().shift(1)
    return df

# ==============================================================================
# 3. 獨立交易訊號萃取引擎 (Event Extractor)
# ==============================================================================
def extract_symbol_trades(sym, df, cfg):
    trades = []
    pos = None
    
    for i in range(365, len(df)):
        bar = df.iloc[i]
        prev = df.iloc[i-1]
        
        if pos is not None:
            side, entry = pos['side'], pos['entry']
            sl, be_tgt = pos['sl'], pos['be_target']
            tp1, tp2 = pos.get('tp1'), pos.get('tp2')
            tp = pos.get('tp')
            
            liq_p = entry * (1 - 1/cfg['lev'] + MAINTENANCE_MARGIN_RATE) if side == 'LONG' else entry * (1 + 1/cfg['lev'] - MAINTENANCE_MARGIN_RATE)
            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': liq_p, 'exit2': liq_p, 'split': False})
                pos = None
                continue
                
            closed = False
            
            if pos['type'] == 'single':
                if side == 'LONG':
                    if not pos['be_moved'] and bar['h'] >= be_tgt:
                        pos['sl'] = entry
                        pos['be_moved'] = True
                    if bar['l'] <= pos['sl']:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': False})
                        closed = True
                    elif bar['h'] >= tp:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': tp, 'exit2': tp, 'split': False})
                        closed = True
                else:
                    if not pos['be_moved'] and bar['l'] <= be_tgt:
                        pos['sl'] = entry
                        pos['be_moved'] = True
                    if bar['h'] >= pos['sl']:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': False})
                        closed = True
                    elif bar['l'] <= tp:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': tp, 'exit2': tp, 'split': False})
                        closed = True
                        
            elif pos['type'] == 'split':
                if side == 'LONG':
                    if bar['l'] <= pos['sl']:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': pos['tp1_hit']})
                        closed = True
                    elif not pos['tp1_hit'] and bar['h'] >= tp1:
                        pos['tp1_hit'] = True
                        pos['sl'] = entry
                        pos['saved_exit1'] = tp1
                    elif pos['tp1_hit'] and bar['h'] >= tp2:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['saved_exit1'], 'exit2': tp2, 'split': True})
                        closed = True
                else:
                    if bar['h'] >= pos['sl']:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['sl'], 'exit2': pos['sl'], 'split': pos['tp1_hit']})
                        closed = True
                    elif not pos['tp1_hit'] and bar['l'] <= tp1:
                        pos['tp1_hit'] = True
                        pos['sl'] = entry
                        pos['saved_exit1'] = tp1
                    elif pos['tp1_hit'] and bar['l'] <= tp2:
                        trades.append({'sym': sym, 'entry_time': pos['entry_time'], 'side': side, 'entry': entry, 'exit1': pos['saved_exit1'], 'exit2': tp2, 'split': True})
                        closed = True
                        
            if closed: pos = None
            
        if pos is None:
            sig = None
            if cfg['mode'] == 'gold_macro_donchian':
                ma = bar['ma_trend']
                dc_h, dc_l = bar['dc_high'], bar['dc_low']
                atr = bar['atr']
                if not pd.isna(ma) and not pd.isna(dc_h):
                    if bar['c'] > ma and bar['c'] > dc_h:
                        sig, entry = 'LONG', bar['c']
                        sl = entry - (atr * 1.5)
                        risk = entry - sl
                        pos = {'type': 'single', 'side': sig, 'entry': entry, 'sl': sl, 'be_target': entry + (risk * 2.0), 'tp': entry + (risk * 5.0), 'entry_time': bar['time'], 'be_moved': False}
                    elif bar['c'] < ma and bar['c'] < dc_l:
                        sig, entry = 'SHORT', bar['c']
                        sl = entry + (atr * 1.5)
                        risk = sl - entry
                        pos = {'type': 'single', 'side': sig, 'entry': entry, 'sl': sl, 'be_target': entry - (risk * 2.0), 'tp': entry - (risk * 5.0), 'entry_time': bar['time'], 'be_moved': False}
            
            elif cfg['mode'] in ['crypto_ict_fvg', 'stock_pullback']:
                rl, rh = bar['recent_low'], bar['recent_high']
                if not pd.isna(rl) and not pd.isna(rh):
                    if bar['l'] <= rl * 1.005 and bar['c'] > prev['c']:
                        sig, entry = 'LONG', bar['c']
                        sl = rl * 0.995
                        pos = {'type': 'split', 'side': sig, 'entry': entry, 'sl': sl, 'be_target': entry + (entry - sl)*2.0, 'tp1': entry + (entry - sl)*2.0, 'tp2': rh, 'entry_time': bar['time'], 'tp1_hit': False}
                    elif bar['h'] >= rh * 0.995 and bar['c'] < prev['c']:
                        sig, entry = 'SHORT', bar['c']
                        sl = rh * 1.005
                        pos = {'type': 'split', 'side': sig, 'entry': entry, 'sl': sl, 'be_target': entry - (sl - entry)*2.0, 'tp1': entry - (sl - entry)*2.0, 'tp2': rl, 'entry_time': bar['time'], 'tp1_hit': False}

    return trades

# ==============================================================================
# 4. 資金結算與風控引擎
# ==============================================================================
def calc_trade_pnl(wallet, trade, cfg):
    entry, side, split = trade['entry'], trade['side'], trade['split']
    exit1, exit2 = trade['exit1'], trade['exit2']
    
    # v4 核心 1% 風險名目價值算法 (支援最低門檻 25U 防呆)
    notional = wallet * RISK_PCT * cfg['lev']
    if notional < 25.0: notional = 25.0
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

def run_v4_github_actions_backtest():
    print("=" * 70)
    print(f" >>> 啟動 v4 版【365天期全資產】量化回測引擎 (純幣安直連版)...")
    print("=" * 70)

    data_status = {}
    master_trades = []

    for sym, cfg in BACKTEST_SYMBOLS.items():
        if not cfg['trade']: continue
        print(f"📥 正在抓取並運算 {sym} ({cfg['interval']})...")
        df = fetch_binance_stealth_klines(cfg['s'], cfg['interval'], TEST_DAYS + 30)
        
        if df is not None and not df.empty:
            data_status[sym] = '🟢'
            df = prepare_indicators(df, cfg['mode'])
            sym_trades = extract_symbol_trades(sym, df, cfg)
            master_trades.extend(sym_trades)
        else:
            data_status[sym] = '🔴'

    iso_results = {}
    iso_total_final = 0.0
    
    for sym, cfg in BACKTEST_SYMBOLS.items():
        if data_status.get(sym) == '🔴': continue
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

    status_str = " | ".join([f"{sym}: {data_status.get(sym, '🔴')}" for sym in BACKTEST_SYMBOLS.keys()])
    
    lines = [
        "```text",
        f"📈 【實戰策略 v4 版 365 天高淨值回測報告】",
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
    run_v4_github_actions_backtest()
