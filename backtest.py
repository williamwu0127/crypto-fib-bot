import io
import zipfile
import datetime
import requests
import pandas as pd
import numpy as np

# ==================== 參數設定 ====================
FRICTION_RATE = 0.0004  # 單邊摩擦成本 (手續費 + 滑價) 預設為萬分之四

SYMBOLS = {
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': True},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'XAU':   {'s': 'XAUUSDT',  'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'trade': True}
}

def fetch_binance_vision_data(symbol, interval, days):
    print(f"📥 正在從 Binance Data Vision 下載 {symbol} ({interval}) 過去 {days} 天歷史資料...")
    end_date = datetime.date.today() - datetime.timedelta(days=1) # 避免抓取當天或未完成的當月
    start_date = end_date - datetime.timedelta(days=days)
    
    current = start_date.replace(day=1)
    months_to_fetch = []
    while current <= end_date:
        months_to_fetch.append((current.year, current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    all_dfs = []
    for year, month in months_to_fetch:
        url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"
        try:
            res = requests.get(url, timeout=30)
            if res.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                    for filename in z.namelist():
                        with z.open(filename) as f:
                            # 讀取 CSV，自動適應有沒有 header
                            df_month = pd.read_csv(f, header=None)
                            all_dfs.append(df_month)
            else:
                print(f"⚠️ 找不到 {symbol} {year}-{month:02d} 的月度公開數據檔案 (狀態碼 {res.status_code})")
        except Exception as e:
            print(f"❌ 下載 {symbol} {year}-{month:02d} 失敗: {e}")
    
    if not all_dfs:
        print(f"⚠️ {symbol} 未能成功取得任何 CSV 歷史資料。")
        return pd.DataFrame()
        
    df = pd.concat(all_dfs, ignore_index=True)
    
    # 清理掉可能存在的字串表頭行 (將非數字的行過濾掉)
    df = df.iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ['t', 'o', 'h', 'l', 'c', 'v']
    
    # 強制轉型，並把無法轉成數字的標題列（如 'open' 等字串）自動轉為 NaN 並濾除
    for col in ['t', 'o', 'h', 'l', 'c', 'v']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna().reset_index(drop=True)
    
    df['time'] = pd.to_datetime(df['t'], unit='ms')
    
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    df = df[(df['time'] >= start_ts) & (df['time'] < end_ts)]
    
    return df.drop_duplicates(subset=['t']).sort_values('t').reset_index(drop=True)

def prepare_indicators(df, mode):
    if df.empty: return df
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    if mode == 'gold_macro_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.015)
    return df

def generate_trades(symbol, cfg, df_main):
    if df_main.empty: return []
    trades = []
    mode = cfg['mode']
    in_position = False
    entry_price, sl_price, tp_price, position_side = 0, 0, 0, None
    
    for i in range(50, len(df_main)):
        bar = df_main.iloc[i]
        
        if in_position:
            is_win = False
            is_loss = False
            if position_side == 'LONG':
                if bar['l'] <= sl_price: is_loss = True
                elif bar['h'] >= tp_price: is_win = True
            else:
                if bar['h'] >= sl_price: is_loss = True
                elif bar['l'] <= tp_price: is_win = True
                
            if is_win or is_loss:
                exit_price = sl_price if is_loss else tp_price
                raw_pnl_pct = ((exit_price - entry_price) / entry_price) if position_side == 'LONG' else ((entry_price - exit_price) / entry_price)
                
                net_pnl_pct = raw_pnl_pct - (FRICTION_RATE * 2) 
                
                trades.append({
                    'symbol': symbol,
                    'entry_time': current_entry_time,
                    'exit_time': bar['time'],
                    'side': position_side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': net_pnl_pct
                })
                in_position = False
            continue

        if mode == 'gold_macro_donchian':
            if bar['c'] > bar['dc_high']:
                position_side, entry_price = 'LONG', bar['c']
                sl_price = entry_price - (bar['atr'] * 1.5)
                tp_price = entry_price + (entry_price - sl_price) * 5.0
                in_position, current_entry_time = True, bar['time']
            elif bar['c'] < bar['dc_low']:
                position_side, entry_price = 'SHORT', bar['c']
                sl_price = entry_price + (bar['atr'] * 1.5)
                tp_price = entry_price - (sl_price - entry_price) * 5.0
                in_position, current_entry_time = True, bar['time']
                
        elif mode == 'crypto_ict_fvg':
            ob_condition = (bar['c'] < bar['o']) if df_main.iloc[i-1]['c'] > df_main.iloc[i-1]['ema20'] else (bar['c'] > bar['o'])
            if ob_condition:
                if df_main.iloc[i-1]['c'] > df_main.iloc[i-1]['ema20']:
                    position_side, entry_price = 'LONG', bar['c']
                    sl_price, tp_price = bar['l'] * 0.999, entry_price * 1.02
                else:
                    position_side, entry_price = 'SHORT', bar['c']
                    sl_price, tp_price = bar['h'] * 1.001, entry_price * 0.98
                in_position, current_entry_time = True, bar['time']

    return trades

def simulate_portfolio(trades, initial_balances):
    if not trades: return {b: {'balance': b, 'peak': b, 'mdd': 0.0} for b in initial_balances}
    trades.sort(key=lambda x: x['exit_time'])
    
    results = {b: {'balance': b, 'peak': b, 'mdd': 0.0} for b in initial_balances}
    
    for t in trades:
        for b in initial_balances:
            if results[b]['balance'] <= 0: continue
            
            lev = SYMBOLS[t['symbol']]['lev']
            trade_margin = results[b]['balance'] * 0.01
            position_size = trade_margin * lev
            
            pnl_val = position_size * t['pnl_pct']
            results[b]['balance'] += pnl_val
            
            if results[b]['balance'] < 0: 
                results[b]['balance'] = 0
            
            if results[b]['balance'] > results[b]['peak']:
                results[b]['peak'] = results[b]['balance']
            
            current_dd = (results[b]['peak'] - results[b]['balance']) / results[b]['peak'] if results[b]['peak'] > 0 else 0
            if current_dd > results[b]['mdd']:
                results[b]['mdd'] = current_dd
                
    return results

def run_backtest(days):
    print(f"\n{'='*25} 啟動 {days} 天期合併倉回測 (Binance Vision CSV) {'='*25}")
    all_trades = []
    
    for sym, cfg in SYMBOLS.items():
        if not cfg['trade']: continue
        df = fetch_binance_vision_data(cfg['s'], cfg['interval'], days)
        df = prepare_indicators(df, cfg['mode'])
        trades = generate_trades(sym, cfg, df)
        all_trades.extend(trades)
        print(f"📊 {sym} 共產生 {len(trades)} 筆交易信號")

    initial_balances = [100, 1000, 10000]
    final_results = simulate_portfolio(all_trades, initial_balances)
    
    print("\n" + "-"*70)
    print(f"📅 回測期間: 過去 {days} 天 | 總交易次數: {len(all_trades)} 筆")
    print(f"{'初始本金 (USDT)':<15} | {'最終權益 (USDT)':<15} | {'總報酬率':<12} | {'最大回撤 (MDD)':<10}")
    print("-" * 70)
    for b in initial_balances:
        final_val = final_results[b]['balance']
        mdd = final_results[b]['mdd'] * 100
        roi = ((final_val - b) / b) * 100
        status = "💀 破產清算" if final_val <= 0 else f"{roi:+.2f}%"
        print(f"{b:<18} | {final_val:<19.2f} | {status:<14} | {mdd:.2f}%")
    print("-" * 70 + "\n")

if __name__ == '__main__':
    run_backtest(30)
    run_backtest(365)
