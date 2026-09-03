import time
import requests
import pandas as pd
import numpy as np

# ==================== 參數與代理設定 ====================
BASE_URL = "https://fapi.binance.com"
FRICTION_RATE = 0.0004  # 單邊摩擦成本 (手續費 + 滑價) 預設為萬分之四

# 如果你的伺服器位於美國/歐洲等受限機房（會報 451 錯誤），
# 請在此處填入你未受限地區（如台灣/日本/新加坡）的 Proxy 代理，例如：
# PROXIES = {
#     'http': 'http://your_proxy_ip:port',
#     'https': 'http://your_proxy_ip:port'
# }
PROXIES = None 

SYMBOLS = {
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'trade': True},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'trade': True},
    'XAU':   {'s': 'XAUUSDT',  'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'trade': True}
}

def fetch_historical_data(symbol, interval, days):
    print(f"📥 正在下載 {symbol} ({interval}) 過去 {days} 天歷史數據...")
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_klines = []
    current_start = start_time
    
    while current_start < end_time:
        try:
            url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={current_start}&limit=1500"
            res = requests.get(url, proxies=PROXIES, timeout=10)
            
            if res.status_code != 200:
                print(f"❌ [API 錯誤] 伺服器回應狀態碼 {res.status_code}，可能遭地區阻擋。內容: {res.text[:200]}")
                break
                
            data = res.json()
            if not data or not isinstance(data, list): 
                break
                
            all_klines.extend(data)
            current_start = data[-1][0] + 1
            time.sleep(0.1)
        except Exception as e:
            print(f"❌ [連線例外] 下載 {symbol} 失敗: {e}")
            break

    if not all_klines:
        print(f"⚠️ {symbol} 未能成功抓取任何 K 線數據！")
        return pd.DataFrame()

    cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
    df = pd.DataFrame(all_klines, columns=cols)
    for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
    df['time'] = pd.to_datetime(df['t'], unit='ms')
    return df.drop_duplicates(subset=['t']).reset_index(drop=True)

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
                
                # 扣除雙邊手續費與滑價
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
    print(f"\n{'='*25} 啟動 {days} 天期合併倉回測 {'='*25}")
    all_trades = []
    
    for sym, cfg in SYMBOLS.items():
        if not cfg['trade']: continue
        df = fetch_historical_data(cfg['s'], cfg['interval'], days)
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
