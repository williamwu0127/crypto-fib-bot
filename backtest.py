import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==================== 1. 設定與標的 ====================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_ob',      'lev': 100.0},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_ob',      'lev': 20.0},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 10.0},
    'MSFT':  {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',     'lev': 10.0},
    'MU':    {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',     'lev': 10.0}
}

# ==================== 2. 工具函式 ====================
def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        if abs(f) >= 1000: return f"{f:.1f}"
        elif abs(f) >= 1: return f"{f:.2f}"
        else: return f"{f:.4f}"
    except Exception: return str(val)

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL: return
    try: requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
    except Exception: pass

# ==================== 3. 歷史資料抓取與指標處理 ====================
def fetch_historical_data(cfg, days):
    try:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
        all_klines = []
        curr_start = start_ms
        
        while curr_start < now_ms:
            # 統一改回 v1 實盤使用的 fapi 合約終端
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr_start}&limit=1000"
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                break
            
            data = res.json()
            if not isinstance(data, list) or len(data) == 0: break
            all_klines.extend(data)
            if len(data) < 1000: break
            curr_start = int(data[-1][0]) + 1
            time.sleep(0.05)
            
        if len(all_klines) > 10:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(all_klines, columns=cols)
            df = df.drop_duplicates(subset=['t']).sort_values('t').reset_index(drop=True)
            for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
            return df[['time', 'o', 'h', 'l', 'c']]
    except Exception as e:
        print(f"⚠️ {cfg['s']} 獲取失敗: {e}")
    return None

def prepare_indicators(df, mode):
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    if mode == 'gold_macro_donchian':
        df['ma360'] = df['c'].rolling(360).mean()
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
    elif mode == 'crypto_ict_ob':
        df['recent_l_80'] = df['l'].rolling(80).min().shift(1)
        df['recent_h_80'] = df['h'].rolling(80).max().shift(1)
        df['sweep_long'] = (df['l'] < df['recent_l_80']) & (df['c'] > df['recent_l_80'])
        df['sweep_short'] = (df['h'] > df['recent_h_80']) & (df['c'] < df['recent_h_80'])
    return df

# ==================== 4. 核心回測引擎 ====================
def run_simulation(data_records, all_times, mode_type="isolated"):
    if mode_type == "isolated":
        wallets = {sym: 100.0 for sym in SYMBOLS.keys()}
    else:
        shared_wallet = 100.0

    positions = {}
    completed_trades = []
    stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    fast_data = {}
    for sym, df in data_records.items():
        fast_data[sym] = df.set_index('time').to_dict('index')

    for t in all_times:
        for sym, cfg in SYMBOLS.items():
            # 【修復】安全跳過未抓取到資料的標的，防止 KeyError 崩潰
            if sym not in fast_data or t not in fast_data[sym]: 
                continue
                
            row = fast_data[sym][t]
            current_bal = wallets[sym] if mode_type == "isolated" else shared_wallet
            
            if sym in positions:
                pos = positions[sym]
                side, entry, qty = pos['side'], pos['entry'], pos['qty']
                sl, tp1, tp2 = pos['sl'], pos['tp1'], pos['tp2']
                tp1_hit = pos['tp1_hit']

                if side == 'LONG':
                    if row['l'] <= sl:
                        pnl = qty * (sl - entry)
                        if mode_type == "isolated": wallets[sym] += pnl
                        else: shared_wallet += pnl
                        
                        stats[sym]['trades'] += 1
                        stats[sym]['pnl'] += pnl
                        if pnl > 0: stats[sym]['wins'] += 1
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        del positions[sym]
                        continue
                    
                    if 'be_tgt' in pos and not pos['be_moved'] and row['h'] >= pos['be_tgt']:
                        pos['sl'] = entry
                        pos['be_moved'] = True

                    if not tp1_hit and row['h'] >= tp1:
                        pnl_tp1 = (qty * 0.5) * (tp1 - entry)
                        if mode_type == "isolated": wallets[sym] += pnl_tp1
                        else: shared_wallet += pnl_tp1
                        pos['tp1_hit'] = True
                        pos['sl'] = entry
                        stats[sym]['trades'] += 1
                        stats[sym]['wins'] += 1
                        stats[sym]['pnl'] += pnl_tp1
                        
                        if cfg['mode'] == 'gold_macro_donchian':
                            completed_trades.append({'sym': sym, 'pnl': pnl_tp1})
                            del positions[sym]
                            continue
                            
                    if pos['tp1_hit'] and row['h'] >= tp2:
                        pnl_tp2 = (qty * 0.5) * (tp2 - entry)
                        if mode_type == "isolated": wallets[sym] += pnl_tp2
                        else: shared_wallet += pnl_tp2
                        stats[sym]['trades'] += 1
                        stats[sym]['wins'] += 1
                        stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'sym': sym, 'pnl': pnl_tp2})
                        del positions[sym]
                        continue

                elif side == 'SHORT':
                    if row['h'] >= sl:
                        pnl = qty * (entry - sl)
                        if mode_type == "isolated": wallets[sym] += pnl
                        else: shared_wallet += pnl
                        stats[sym]['trades'] += 1
                        stats[sym]['pnl'] += pnl
                        if pnl > 0: stats[sym]['wins'] += 1
                        completed_trades.append({'sym': sym, 'pnl': pnl})
                        del positions[sym]
                        continue
                        
                    if 'be_tgt' in pos and not pos['be_moved'] and row['l'] <= pos['be_tgt']:
                        pos['sl'] = entry
                        pos['be_moved'] = True

                    if not tp1_hit and row['l'] <= tp1:
                        pnl_tp1 = (qty * 0.5) * (entry - tp1)
                        if mode_type == "isolated": wallets[sym] += pnl_tp1
                        else: shared_wallet += pnl_tp1
                        pos['tp1_hit'] = True
                        pos['sl'] = entry
                        stats[sym]['trades'] += 1
                        stats[sym]['wins'] += 1
                        stats[sym]['pnl'] += pnl_tp1
                        
                        if cfg['mode'] == 'gold_macro_donchian':
                            completed_trades.append({'sym': sym, 'pnl': pnl_tp1})
                            del positions[sym]
                            continue

                    if pos['tp1_hit'] and row['l'] <= tp2:
                        pnl_tp2 = (qty * 0.5) * (entry - tp2)
                        if mode_type == "isolated": wallets[sym] += pnl_tp2
                        else: shared_wallet += pnl_tp2
                        stats[sym]['trades'] += 1
                        stats[sym]['wins'] += 1
                        stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'sym': sym, 'pnl': pnl_tp2})
                        del positions[sym]
                        continue

            if sym not in positions and current_bal > 5.0:
                sig_side, entry, sl, tp1, tp2, be_tgt = None, 0, 0, 0, 0, 0
                mode = cfg['mode']

                if mode == 'gold_macro_donchian':
                    if pd.isna(row['ma360']): continue
                    macro_trend = 1 if row['c'] > row['ma360'] else -1
                    if macro_trend == 1 and row['c'] > row['dc_high']:
                        sig_side, entry = 'LONG', row['c']
                        sl = entry - (row['atr'] * 1.5)
                        be_tgt, tp1 = entry + (entry - sl) * 2.0, entry + (entry - sl) * 5.0
                        tp2 = tp1
                    elif macro_trend == -1 and row['c'] < row['dc_low']:
                        sig_side, entry = 'SHORT', row['c']
                        sl = entry + (row['atr'] * 1.5)
                        be_tgt, tp1 = entry - (sl - entry) * 2.0, entry - (sl - entry) * 5.0
                        tp2 = tp1

                elif mode == 'crypto_ict_ob':
                    df = data_records[sym]
                    idx_arr = df.index[df['time'] == t].tolist()
                    if not idx_arr or idx_arr[0] < 25: continue
                    idx = idx_arr[0]
                    
                    sub = df.iloc[idx-20:idx]
                    if sub['sweep_long'].any():
                        ob_reds = sub[sub['c'] < sub['o']]
                        if not ob_reds.empty:
                            ob = ob_reds.loc[ob_reds['l'].idxmin()]
                            if row['l'] <= ob['h'] and row['c'] >= ob['l'] * 0.999:
                                sig_side, entry = 'LONG', row['c']
                                sl = ob['l'] * 0.999
                                tp1, tp2 = entry + (entry - sl)*2, entry + (entry - sl)*4
                    elif sub['sweep_short'].any():
                        ob_grns = sub[sub['c'] > sub['o']]
                        if not ob_grns.empty:
                            ob = ob_grns.loc[ob_grns['h'].idxmax()]
                            if row['h'] >= ob['l'] and row['c'] <= ob['h'] * 1.001:
                                sig_side, entry = 'SHORT', row['c']
                                sl = ob['h'] * 1.001
                                tp1, tp2 = entry - (sl - entry)*2, entry - (sl - entry)*4

                elif mode == 'stock_pullback':
                    trend_bull = (row['ema20'] > row['ema50']) and (row['c'] > row['ema200'])
                    trend_bear = (row['ema20'] < row['ema50']) and (row['c'] < row['ema200'])
                    if trend_bull and row['l'] <= row['ema20'] and 45 <= row['rsi'] <= 60:
                        sig_side, entry = 'LONG', row['c']
                        sl = min(row['l'], row['ema50'] - row['atr'])
                        tp1, tp2 = entry + (entry - sl)*1.5, entry + (entry - sl)*3.0
                    elif trend_bear and row['h'] >= row['ema20'] and 40 <= row['rsi'] <= 55:
                        sig_side, entry = 'SHORT', row['c']
                        sl = max(row['h'], row['ema50'] + row['atr'])
                        tp1, tp2 = entry - (sl - entry)*1.5, entry - (sl - entry)*3.0

                if sig_side:
                    notional = (current_bal * 0.01) * cfg['lev']
                    qty = notional / entry
                    positions[sym] = {
                        'side': sig_side, 'entry': entry, 'qty': qty,
                        'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'tp1_hit': False, 'be_tgt': be_tgt, 'be_moved': False
                    }

    final_balance = shared_wallet if mode_type == "combined" else sum(wallets.values())
    initial_balance = 100.0 if mode_type == "combined" else len(SYMBOLS) * 100.0
    return final_balance, initial_balance, completed_trades, stats

# ==================== 5. 執行排程 ====================
def run_backtest_pipeline(days):
    print(f"\n{'='*50}\n🚀 啟動 {days} 天歷史數據抓取...\n{'='*50}")
    
    data_records = {}
    fetch_status = []
    start_dt, end_dt = None, None

    for sym, cfg in SYMBOLS.items():
        print(f"   └ 載入 {sym:<5} ({cfg['interval']})...", end=" ")
        df = fetch_historical_data(cfg, days)
        if df is not None and len(df) > 100:
            df = prepare_indicators(df, cfg['mode'])
            data_records[sym] = df
            print("🟢 成功")
            fetch_status.append(f"{sym}: 🟢")
            s_dt = df.iloc[50]['time'].strftime("%Y-%m-%d")
            e_dt = df.iloc[-1]['time'].strftime("%Y-%m-%d")
            if start_dt is None or s_dt < start_dt: start_dt = s_dt
            if end_dt is None or e_dt > end_dt: end_dt = e_dt
        else:
            print("🔴 失敗")
            fetch_status.append(f"{sym}: 🔴")

    if not data_records: return

    all_times = set()
    for df in data_records.values(): all_times.update(df['time'].tolist())
    all_times = sorted(list(all_times))

    print(f"\n⏳ 運算 {days} 天 [各自獨立 100U] 模式...")
    iso_fin, iso_ini, iso_trades, iso_stats = run_simulation(data_records, all_times, "isolated")
    
    print(f"⏳ 運算 {days} 天 [資金池共享 100U] 模式...")
    cmb_fin, cmb_ini, cmb_trades, cmb_stats = run_simulation(data_records, all_times, "combined")

    def build_report(mode_name, fin_bal, ini_bal, trades, stats):
        roi = ((fin_bal - ini_bal) / ini_bal) * 100
        win_rate = (len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100) if trades else 0
        
        lines = []
        for sym, r in stats.items():
            c, w = r['trades'], r['wins']
            wr = (w / c * 100) if c > 0 else 0.0
            lines.append(f"{sym:<5} | 交易: {str(c).rjust(3)}次 | 勝率: {wr:5.2f}% | 收益: {r['pnl']:+8.2f} U")
            
        return (
            f"【{mode_name} 模式 ({days}d)】\n"
            f"回測區間: {start_dt} ~ {end_dt}\n"
            f"初始資金: ${ini_bal:.2f} USDT\n"
            f"最終結餘: ${fin_bal:.2f} USDT ({roi:+.2f}%)\n"
            f"總交易次數: {len(trades)} 次 | 綜合勝率: {win_rate:.2f}%\n"
            f"{'-'*45}\n" + "\n".join(lines)
        )

    iso_msg = build_report("獨立配資 100U (Isolated)", iso_fin, iso_ini, iso_trades, iso_stats)
    cmb_msg = build_report("共享資金池 100U (Combined)", cmb_fin, cmb_ini, cmb_trades, cmb_stats)

    full_report = (
        f"```text\n"
        f"📊【實戰策略 {days} 天回測報告】\n"
        f"數據狀態: {' | '.join(fetch_status)}\n"
        f"{'='*50}\n\n{iso_msg}\n\n{'='*50}\n\n{cmb_msg}\n"
        f"```"
    )

    print("\n" + full_report)
    send_discord_safe(full_report)

if __name__ == '__main__':
    run_backtest_pipeline(30)
    run_backtest_pipeline(365)
