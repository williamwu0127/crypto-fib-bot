import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==================== 1. 設定與實戰標的 ====================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'BTC':   {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',      'lev': 100.0},
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',      'lev': 100.0},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',      'lev': 20.0},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0},
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
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    
    endpoints = [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines"
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for base_url in endpoints:
        try:
            all_klines = []
            curr_start = start_ms
            is_failed = False
            
            while curr_start < now_ms:
                url = f"{base_url}?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr_start}&limit=1000"
                res = requests.get(url, headers=headers, timeout=10)
                
                if res.status_code != 200:
                    is_failed = True
                    break
                
                data = res.json()
                if not isinstance(data, list) or len(data) == 0: break
                all_klines.extend(data)
                if len(data) < 1000: break
                curr_start = int(data[-1][0]) + 1
                time.sleep(0.05)
                
            if not is_failed and len(all_klines) > 10:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(all_klines, columns=cols)
                df = df.drop_duplicates(subset=['t']).sort_values('t').reset_index(drop=True)
                for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
                return df[['time', 'o', 'h', 'l', 'c']]
        except Exception:
            continue
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
        df['ma360'] = df['c'].rolling(360).mean() # 近似日線MA60
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
    elif mode == 'crypto_ict_fvg':
        df['recent_l_80'] = df['l'].rolling(80).min().shift(1)
        df['recent_h_80'] = df['h'].rolling(80).max().shift(1)
        df['sweep_long'] = (df['l'] < df['recent_l_80']) & (df['c'] > df['recent_l_80'])
        df['sweep_short'] = (df['h'] > df['recent_h_80']) & (df['c'] < df['recent_h_80'])
    return df

# ==================== 4. 核心回測引擎 ====================
def run_simulation(data_records, all_times, mode_type="isolated"):
    # 設定大資金 1000U 基準
    if mode_type == "isolated":
        wallets = {sym: 1000.0 for sym in SYMBOLS.keys()}
    else:
        shared_wallet = 1000.0

    positions = {}
    completed_trades = []
    stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}
    
    last_entry_idx = {sym: 0 for sym in SYMBOLS.keys()}
    fast_data = {sym: df.set_index('time').to_dict('index') for sym, df in data_records.items()}

    for t in all_times:
        for sym, cfg in SYMBOLS.items():
            if sym not in fast_data or t not in fast_data[sym]: continue
                
            row = fast_data[sym][t]
            current_bal = wallets[sym] if mode_type == "isolated" else shared_wallet
            
            # 1. 持倉管理與出場邏輯
            if sym in positions:
                pos = positions[sym]
                side, entry, qty = pos['side'], pos['entry'], pos['qty']
                sl, tp1, tp2 = pos['sl'], pos['tp1'], pos['tp2']
                tp1_hit = pos['tp1_hit']

                if side == 'LONG':
                    # 止損觸發
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
                    
                    # 黃金 2.0R 保本平移
                    if 'be_tgt' in pos and not pos['be_moved'] and row['h'] >= pos['be_tgt']:
                        pos['sl'] = entry
                        pos['be_moved'] = True

                    # 觸及 TP1
                    if not tp1_hit and row['h'] >= tp1:
                        if cfg['mode'] == 'gold_macro_donchian':
                            # 黃金 5R 滿倉平倉結算
                            pnl_full = qty * (tp1 - entry)
                            if mode_type == "isolated": wallets[sym] += pnl_full
                            else: shared_wallet += pnl_full
                            stats[sym]['trades'] += 1
                            stats[sym]['wins'] += 1
                            stats[sym]['pnl'] += pnl_full
                            completed_trades.append({'sym': sym, 'pnl': pnl_full})
                            del positions[sym]
                            continue
                        else:
                            # Crypto / Stock: 50% 倉位止盈
                            pnl_tp1 = (qty * 0.5) * (tp1 - entry)
                            if mode_type == "isolated": wallets[sym] += pnl_tp1
                            else: shared_wallet += pnl_tp1
                            
                            pos['tp1_hit'] = True
                            # ✅ 關鍵更新：ICT 策略達到 TP1 (FVG 0.618) 後，剩餘倉位止損上移至 TP1 鎖利
                            if cfg['mode'] == 'crypto_ict_fvg':
                                pos['sl'] = tp1
                            else:
                                pos['sl'] = entry
                                
                            stats[sym]['trades'] += 1
                            stats[sym]['wins'] += 1
                            stats[sym]['pnl'] += pnl_tp1
                            
                    # 觸及 TP2
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
                    # 止損觸發
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
                        
                    # 黃金 2.0R 保本平移
                    if 'be_tgt' in pos and not pos['be_moved'] and row['l'] <= pos['be_tgt']:
                        pos['sl'] = entry
                        pos['be_moved'] = True

                    # 觸及 TP1
                    if not tp1_hit and row['l'] <= tp1:
                        if cfg['mode'] == 'gold_macro_donchian':
                            # 黃金 5R 滿倉平倉結算
                            pnl_full = qty * (entry - tp1)
                            if mode_type == "isolated": wallets[sym] += pnl_full
                            else: shared_wallet += pnl_full
                            stats[sym]['trades'] += 1
                            stats[sym]['wins'] += 1
                            stats[sym]['pnl'] += pnl_full
                            completed_trades.append({'sym': sym, 'pnl': pnl_full})
                            del positions[sym]
                            continue
                        else:
                            # Crypto / Stock: 50% 倉位止盈
                            pnl_tp1 = (qty * 0.5) * (entry - tp1)
                            if mode_type == "isolated": wallets[sym] += pnl_tp1
                            else: shared_wallet += pnl_tp1
                            
                            pos['tp1_hit'] = True
                            # ✅ 關鍵更新：ICT 策略達到 TP1 (FVG 0.618) 後，剩餘倉位止損下移至 TP1 鎖利
                            if cfg['mode'] == 'crypto_ict_fvg':
                                pos['sl'] = tp1
                            else:
                                pos['sl'] = entry
                                
                            stats[sym]['trades'] += 1
                            stats[sym]['wins'] += 1
                            stats[sym]['pnl'] += pnl_tp1

                    # 觸及 TP2
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

            # 2. 開倉信號判定
            df = data_records[sym]
            idx_arr = df.index[df['time'] == t].tolist()
            if not idx_arr or idx_arr[0] < 25: continue
            idx = idx_arr[0]

            if sym not in positions and current_bal > 10.0:
                # 實施 8 根 K 線冷卻防呆 (大約 2 小時)
                if idx - last_entry_idx[sym] < 8:
                    continue

                sig_side, entry, sl, tp1, tp2, be_tgt = None, 0, 0, 0, 0, 0
                mode = cfg['mode']

                if mode == 'gold_macro_donchian':
                    if pd.isna(row['ma360']): continue
                    macro_trend = 1 if row['c'] > row['ma360'] else -1
                    if macro_trend == 1 and row['c'] > row['dc_high']:
                        sig_side, entry = 'LONG', row['c']
                        sl = entry - (row['atr'] * 1.5)
                        be_tgt = entry + (entry - sl) * 2.0
                        tp1 = entry + (entry - sl) * 5.0 # 滿倉 TP
                        tp2 = tp1
                    elif macro_trend == -1 and row['c'] < row['dc_low']:
                        sig_side, entry = 'SHORT', row['c']
                        sl = entry + (row['atr'] * 1.5)
                        be_tgt = entry - (sl - entry) * 2.0
                        tp1 = entry - (sl - entry) * 5.0 # 滿倉 TP
                        tp2 = tp1

                elif mode == 'crypto_ict_fvg':
                    sub = df.iloc[idx-5:idx] # 只檢查最近 5 根是否有 Sweep 發生
                    if sub['sweep_long'].any():
                        ob_reds = sub[sub['c'] < sub['o']]
                        if not ob_reds.empty:
                            ob = ob_reds.loc[ob_reds['l'].idxmin()]
                            if row['l'] <= ob['h'] and row['c'] >= ob['l']:
                                sig_side, entry = 'LONG', row['c']
                                sl = ob['l'] * 0.998 # 針尖極值下方作為絕對防守
                                fvg_dist = (df.iloc[idx-5:idx]['h'].max() - entry) * 0.618
                                tp1 = entry + fvg_dist # FVG 0.618
                                tp2 = df.iloc[idx-20:idx]['h'].max() # 前方結構高點極值
                    elif sub['sweep_short'].any():
                        ob_grns = sub[sub['c'] > sub['o']]
                        if not ob_grns.empty:
                            ob = ob_grns.loc[ob_grns['h'].idxmax()]
                            if row['h'] >= ob['l'] and row['c'] <= ob['h']:
                                sig_side, entry = 'SHORT', row['c']
                                sl = ob['h'] * 1.002 # 針尖極值上方作為絕對防守
                                fvg_dist = (entry - df.iloc[idx-5:idx]['l'].min()) * 0.618
                                tp1 = entry - fvg_dist # FVG 0.618
                                tp2 = df.iloc[idx-20:idx]['l'].min() # 前方結構低點極值

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
                    # ✅ 資金 1% 與 21.0 U 最小下單防呆機制
                    notional = (current_bal * 0.01) * cfg['lev']
                    if notional < 21.0: notional = 21.0
                    
                    qty = notional / entry
                    positions[sym] = {
                        'side': sig_side, 'entry': entry, 'qty': qty,
                        'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'tp1_hit': False, 'be_tgt': be_tgt, 'be_moved': False
                    }
                    last_entry_idx[sym] = idx

    final_balance = shared_wallet if mode_type == "combined" else sum(wallets.values())
    initial_balance = 1000.0 if mode_type == "combined" else len(SYMBOLS) * 1000.0
    return final_balance, initial_balance, completed_trades, stats

# ==================== 5. 執行排程與報表輸出 ====================
def run_backtest_pipeline(days):
    print(f"\n{'='*50}\n🚀 啟動 {days} 天歷史數據抓取...\n{'='*50}")
    
    data_records = {}
    fetch_status = []
    start_dt, end_dt = None, None

    for sym, cfg in SYMBOLS.items():
        print(f"   └ 載入 {sym:<5} ({cfg['interval']})...", end=" ", flush=True)
        df = fetch_historical_data(cfg, days)
        if df is not None and len(df) > 100:
            df = prepare_indicators(df, cfg['mode'])
            data_records[sym] = df
            print("🟢 成功", flush=True)
            fetch_status.append(f"{sym}: 🟢")
            s_dt = df.iloc[50]['time'].strftime("%Y-%m-%d")
            e_dt = df.iloc[-1]['time'].strftime("%Y-%m-%d")
            if start_dt is None or s_dt < start_dt: start_dt = s_dt
            if end_dt is None or e_dt > end_dt: end_dt = e_dt
        else:
            print("🔴 失敗 (請確認幣安是否支援此交易對)", flush=True)
            fetch_status.append(f"{sym}: 🔴")

    if not data_records: return
    all_times = set()
    for df in data_records.values(): all_times.update(df['time'].tolist())
    all_times = sorted(list(all_times))

    print(f"\n⏳ 運算 {days} 天 [各自獨立 1000U] 模式...", flush=True)
    iso_fin, iso_ini, iso_trades, iso_stats = run_simulation(data_records, all_times, "isolated")
    
    print(f"⏳ 運算 {days} 天 [資金池共享 1000U] 模式...", flush=True)
    cmb_fin, cmb_ini, cmb_trades, cmb_stats = run_simulation(data_records, all_times, "combined")

    def build_report(mode_name, fin_bal, ini_bal, trades, stats):
        roi = ((fin_bal - ini_bal) / ini_bal) * 100
        win_rate = (len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100) if trades else 0
        
        lines = []
        for sym, r in stats.items():
            c, w = r['trades'], r['wins']
            wr = (w / c * 100) if c > 0 else 0.0
            lines.append(f"{sym:<5} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益: {r['pnl']:+8.2f} U")
            
        return (
            f"【{mode_name} 模式 ({days}d)】\n"
            f"回測區間: {start_dt} ~ {end_dt}\n"
            f"初始資金: ${ini_bal:.2f} USDT\n"
            f"最終結餘: ${fin_bal:.2f} USDT ({roi:+.2f}%)\n"
            f"總交易次數: {len(trades)} 次 | 綜合勝率: {win_rate:.2f}%\n"
            f"{'-'*47}\n" + "\n".join(lines)
        )

    iso_msg = build_report("獨立配資各 1000U (Isolated)", iso_fin, iso_ini, iso_trades, iso_stats)
    cmb_msg = build_report("共享資金池 1000U (Combined)", cmb_fin, cmb_ini, cmb_trades, cmb_stats)

    full_report = (
        f"```text\n"
        f"📊【實戰策略 {days} 天高淨值回測報告】\n"
        f"數據狀態: {' | '.join(fetch_status)}\n"
        f"{'='*50}\n\n{iso_msg}\n\n{'='*50}\n\n{cmb_msg}\n"
        f"```"
    )

    print("\n" + full_report, flush=True)
    send_discord_safe(full_report)

if __name__ == '__main__':
    run_backtest_pipeline(30)
    run_backtest_pipeline(365)
