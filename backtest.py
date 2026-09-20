import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import math

# ==================== 1. 回測環境與標的設定 (完整 19 檔) ====================
SYMBOLS = {
    'BTC':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'ETH':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'SOL':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'BNB':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'DOGE':  {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian'},
    'MSFT':  {'interval': '1h',  'mode': 'stock_pullback'},
    'MU':    {'interval': '1h',  'mode': 'stock_pullback'},
    'TSM':   {'interval': '1h',  'mode': 'stock_pullback'},
    'NVDA':  {'interval': '1h',  'mode': 'stock_pullback'},
    'AMD':   {'interval': '1h',  'mode': 'stock_pullback'},
    'AAPL':  {'interval': '1h',  'mode': 'stock_pullback'},
    'GOOGL': {'interval': '1h',  'mode': 'stock_pullback'},
    'AMZN':  {'interval': '1h',  'mode': 'stock_pullback'},
    'META':  {'interval': '1h',  'mode': 'stock_pullback'},
    'TSLA':  {'interval': '1h',  'mode': 'stock_pullback'},
    'GLW':   {'interval': '1h',  'mode': 'stock_pullback'},
    'SPCX':  {'interval': '1h',  'mode': 'stock_pullback'},
    'SNDK':  {'interval': '1h',  'mode': 'stock_pullback'}
}

# ==================== 2. 歷史資料獲取模組 ====================
def fetch_binance_data(symbol, interval, days=30):
    """透過 Binance 公開 API 抓取歷史 K 線資料 (處理 1500 筆上限)"""
    symbol = symbol if 'USDT' in symbol else f"{symbol}USDT"
    if symbol == 'XAUUSDT': symbol = 'PAXGUSDT'
    
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_klines = []
    print(f"下載 {symbol} ({interval}) {days}天資料...", end="", flush=True)
    
    while True:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=1500&startTime={start_time}"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            
            all_klines.extend(res)
            start_time = res[-1][0] + 1 # 從最後一根 K 線的時間往後推
            
            if start_time >= end_time:
                break
            time.sleep(0.1) # 避免 API 頻率限制
        except Exception as e:
            print(f" Error: {e}", end="")
            break
            
    if not all_klines:
        print(" 失敗")
        return None
        
    cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
    df = pd.DataFrame(all_klines, columns=cols)
    for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
    df['time'] = pd.to_datetime(df['t'], unit='ms')
    df = df.set_index('time')[['o', 'h', 'l', 'c', 'v']]
    df = df[~df.index.duplicated(keep='first')] # 移除重複時間
    print(f" 完成 ({len(df)} 根K線)")
    return df

# ==================== 3. 指標與核心邏輯預處理 ====================
def prepare_backtest_indicators(df, mode):
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    # 完美還原實盤 POC 演算法 (滾動 200 根 K 線，50 個區間)
    poc_list = [np.nan] * len(df)
    for i in range(200, len(df)):
        window = df.iloc[i-200:i]
        bins = pd.cut(window['c'], bins=50)
        poc = window.groupby(bins, observed=False)['v'].sum().idxmax().mid
        poc_list[i] = poc
    df['poc'] = poc_list
    
    if mode == 'gold_macro_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
        df['macro_trend_ma'] = df['c'].rolling(60).mean() # 模擬日線MA60趨勢
        
    elif mode == 'crypto_ict_fvg':
        df['acc_high'] = df['h'].rolling(25).max()
        df['acc_low'] = df['l'].rolling(25).min()
        
    return df.dropna()

# ==================== 4. 核心回測引擎 (V6 邏輯) ====================
class V6Backtester:
    def __init__(self, data_dict, initial_capital=1000, pool_mode='isolated'):
        self.data = data_dict
        self.pool_mode = pool_mode
        self.initial_capital = initial_capital
        
        if pool_mode == 'isolated':
            self.balances = {sym: initial_capital for sym in data_dict.keys()}
        else:
            self.shared_balance = initial_capital
            
        self.positions = {sym: None for sym in data_dict.keys()}
        self.trade_history = []

    def get_balance(self, sym):
        return self.balances[sym] if self.pool_mode == 'isolated' else self.shared_balance

    def update_balance(self, sym, pnl):
        if self.pool_mode == 'isolated':
            self.balances[sym] += pnl
        else:
            self.shared_balance += pnl

    def run_simulation(self):
        all_times = sorted(list(set(t for df in self.data.values() for t in df.index)))
        
        for current_time in all_times:
            for sym, df in self.data.items():
                if current_time not in df.index: continue
                
                bar = df.loc[current_time]
                pos = self.positions[sym]
                mode = SYMBOLS[sym]['mode']
                
                # --- A. 平倉邏輯 (動態 3R/6R + 保本) ---
                if pos:
                    pnl = 0
                    is_closed = False
                    close_reason = ""
                    
                    if (pos['side'] == 'LONG' and bar['l'] <= pos['sl']) or \
                       (pos['side'] == 'SHORT' and bar['h'] >= pos['sl']):
                        pnl = (pos['sl'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                        is_closed = True
                        close_reason = "SL/BE 觸發"
                    
                    elif not pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and bar['h'] >= pos['tp1']) or \
                           (pos['side'] == 'SHORT' and bar['l'] <= pos['tp1']):
                            realized_pnl = (pos['tp1'] - pos['entry']) * (pos['qty'] * 0.5) * (1 if pos['side'] == 'LONG' else -1)
                            self.update_balance(sym, realized_pnl)
                            pos['qty'] *= 0.5
                            pos['tp1_hit'] = True
                            pos['sl'] = pos['be_target'] # 保本平移
                    
                    elif pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and bar['h'] >= pos['tp2']) or \
                           (pos['side'] == 'SHORT' and bar['l'] <= pos['tp2']):
                            pnl = (pos['tp2'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                            is_closed = True
                            close_reason = "TP2 達標"

                    if is_closed:
                        self.update_balance(sym, pnl)
                        self.trade_history.append({
                            'symbol': sym, 'exit_time': current_time, 'pnl': pnl, 
                            'reason': close_reason, 'balance': self.get_balance(sym)
                        })
                        self.positions[sym] = None
                        continue

                # --- B. 進場邏輯 (POC 共振 & 箱體極值止損) ---
                if not self.positions[sym]:
                    current_balance = self.get_balance(sym)
                    if current_balance <= 50: continue # 破產保護
                    
                    sig_side, entry, sl, be_tgt, tp1, tp2 = None, 0, 0, 0, 0, 0
                    
                    if mode == 'gold_macro_donchian':
                        macro_trend = 1 if bar['c'] > bar['macro_trend_ma'] else -1
                        if macro_trend == 1 and bar['c'] > bar['dc_high'] and bar['poc'] < bar['c']:
                            sig_side, entry = 'LONG', bar['c']
                            sl = min(bar['dc_low'], bar['poc']) * 0.998
                        elif macro_trend == -1 and bar['c'] < bar['dc_low'] and bar['poc'] > bar['c']:
                            sig_side, entry = 'SHORT', bar['c']
                            sl = max(bar['dc_high'], bar['poc']) * 1.002
                            
                    elif mode == 'crypto_ict_fvg':
                        # 簡化回測中的 Bias 判斷：以 200 EMA 作為大級別偏見
                        bias = 'LONG' if bar['c'] > bar['ema200'] else 'SHORT'
                        
                        if bias == 'LONG':
                            if bar['c'] >= bar['ema20'] and bar['l'] <= bar['ema50']: # 回踩判定
                                poc_dist = abs(bar['poc'] - bar['c']) / bar['c']
                                if poc_dist < 0.008:
                                    defense_line = min(bar['acc_low'], bar['poc'])
                                    if (bar['c'] - defense_line) / bar['c'] <= 0.035:
                                        sig_side, entry = 'LONG', bar['c']
                                        sl = defense_line * 0.998
                        elif bias == 'SHORT':
                            if bar['c'] <= bar['ema20'] and bar['h'] >= bar['ema50']:
                                poc_dist = abs(bar['poc'] - bar['c']) / bar['c']
                                if poc_dist < 0.008:
                                    defense_line = max(bar['acc_high'], bar['poc'])
                                    if (defense_line - bar['c']) / bar['c'] <= 0.035:
                                        sig_side, entry = 'SHORT', bar['c']
                                        sl = defense_line * 1.002

                    elif mode == 'stock_pullback':
                        poc_dist_ema50 = abs(bar['poc'] - bar['ema50']) / bar['ema50']
                        if bar['ema20'] > bar['ema50'] > bar['ema200']:
                            if bar['l'] <= bar['ema20'] and bar['c'] >= bar['ema20']:
                                if poc_dist_ema50 < 0.015 and bar['poc'] < bar['c']:
                                    sig_side, entry = 'LONG', bar['c']
                                    sl = min(bar['ema50'], bar['poc']) * 0.995
                        elif bar['ema20'] < bar['ema50'] < bar['ema200']:
                            if bar['h'] >= bar['ema20'] and bar['c'] <= bar['ema20']:
                                if poc_dist_ema50 < 0.015 and bar['poc'] > bar['c']:
                                    sig_side, entry = 'SHORT', bar['c']
                                    sl = max(bar['ema50'], bar['poc']) * 1.005

                    # 執行 3% 風控開倉
                    if sig_side:
                        risk_dist = abs(entry - sl)
                        if risk_dist > 0:
                            be_tgt = entry + (risk_dist * 2.0) * (1 if sig_side=='LONG' else -1)
                            tp1 = entry + (risk_dist * 4.0) * (1 if sig_side=='LONG' else -1)
                            tp2 = entry + (risk_dist * 7.0) * (1 if sig_side=='LONG' else -1)
                            
                            risk_amount = current_balance * 0.03
                            qty = risk_amount / risk_dist
                            
                            self.positions[sym] = {
                                'side': sig_side, 'entry': entry, 'qty': qty,
                                'sl': sl, 'be_target': be_tgt, 'tp1': tp1, 'tp2': tp2,
                                'tp1_hit': False, 'entry_time': current_time
                            }

    def generate_report(self):
        df_trades = pd.DataFrame(self.trade_history)
        if df_trades.empty:
            return f"[{self.pool_mode}] 模式: 無交易紀錄"
        
        total_trades = len(df_trades)
        win_rate = len(df_trades[df_trades['pnl'] > 0]) / total_trades * 100
        
        if self.pool_mode == 'isolated':
            final_cap = sum(self.balances.values())
            init_cap = len(self.balances) * self.initial_capital
        else:
            final_cap = self.shared_balance
            init_cap = self.initial_capital
            
        report = (
            f"========== 回測報表 ({self.pool_mode.upper()} 模式) ==========\n"
            f"總交易次數: {total_trades} | 整體勝率: {win_rate:.1f}%\n"
            f"初始總資金: {init_cap} USDT -> 最終總資金: {final_cap:.2f} USDT\n"
            f"總報酬率: {((final_cap - init_cap) / init_cap) * 100:.2f}%\n"
            f"--------------------------------------------------\n"
        )
        return report

# ==================== 5. 主執行區塊 (GitHub Actions 的進入點) ====================
if __name__ == '__main__':
    print("🚀 開始準備歷史數據 (設定為 30 天測試)...")
    BACKTEST_DAYS = 30
    
    data_dict = {}
    for sym, cfg in SYMBOLS.items():
        df_raw = fetch_binance_data(sym, cfg['interval'], days=BACKTEST_DAYS)
        if df_raw is not None and not df_raw.empty:
            df_processed = prepare_backtest_indicators(df_raw, cfg['mode'])
            data_dict[sym] = df_processed

    if not data_dict:
        print("❌ 無法獲取任何資料，程式結束。")
    else:
        print("\n📈 數據準備完成，開始執行回測引擎...")
        
        # 執行情境 A: 1000u 個別獨立運作 (19檔 = 總本金 19000u)
        print("\n>>> 啟動 Isolated (個別資金池) 回測...")
        bt_isolated = V6Backtester(data_dict, initial_capital=1000, pool_mode='isolated')
        bt_isolated.run_simulation()
        print(bt_isolated.generate_report())

        # 執行情境 B: 1000u 全部共享資金池 (19檔 共用 1000u)
        print("\n>>> 啟動 Shared (共享資金池) 回測...")
        bt_shared = V6Backtester(data_dict, initial_capital=1000, pool_mode='shared')
        bt_shared.run_simulation()
        print(bt_shared.generate_report())
        
        print("\n✅ 所有回測任務執行完畢！")
