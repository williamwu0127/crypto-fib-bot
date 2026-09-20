import pandas as pd
import numpy as np
from datetime import timedelta

# ==================== 1. 回測環境與標的設定 (完整 19 檔) ====================
SYMBOLS = {
    'BTC':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'ETH':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'SOL':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'BNB':   {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    'DOGE':  {'interval': '15m', 'mode': 'crypto_ict_fvg'},
    
    'XAU':   {'interval': '4h',  'mode': 'gold_macro_donchian'},
    'MSFT':  {'interval': '1h',  'mode': 'gold_macro_donchian'},
    'MU':    {'interval': '1h',  'mode': 'gold_macro_donchian'},
    'TSM':   {'interval': '1h',  'mode': 'gold_macro_donchian'},
    'NVDA':  {'interval': '1h',  'mode': 'gold_macro_donchian'},
    
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
# ==================== 2. 指標與核心邏輯預處理 ====================
def calculate_order_density(series, bins=50):
    """計算 POC (簡化版，用於 Pandas 滾動運算)"""
    counts, bin_edges = np.histogram(series, bins=bins)
    max_idx = np.argmax(counts)
    return (bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2

def prepare_backtest_indicators(df, mode):
    """將 v6 的即時指標邏輯轉換為全歷史數據的向量化預處理"""
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    # 計算 200 根 K 線的滾動 POC (使用 pandas rolling 與 apply)
    df['poc'] = df['c'].rolling(200, min_periods=50).apply(lambda x: calculate_order_density(x), raw=True)
    
    if mode == 'gold_macro_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
        # 模擬 1D MA60 的大趨勢 (4H圖上約等於 360T MA)
        df['macro_trend_ma'] = df['c'].rolling(360).mean() 
        
    elif mode == 'crypto_ict_fvg':
        # 預計算 25 根 K 線的箱體極值
        df['acc_high'] = df['h'].rolling(25).max()
        df['acc_low'] = df['l'].rolling(25).min()
        
    return df.dropna()

# ==================== 3. 核心回測引擎 (支援雙模式) ====================
class V6Backtester:
    def __init__(self, data_dict, initial_capital=1000, pool_mode='isolated'):
        """
        pool_mode: 
          - 'isolated': 每個幣種獨立 1000u (1000u 個別操作)
          - 'shared': 所有幣種共用 1000u (全部1000u 共享資金池)
        """
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
        # 將所有標的的數據對齊時間軸，進行時間步進推進
        all_times = sorted(list(set(t for df in self.data.values() for t in df.index)))
        
        for current_time in all_times:
            for sym, df in self.data.items():
                if current_time not in df.index: continue
                
                bar = df.loc[current_time]
                pos = self.positions[sym]
                mode = SYMBOLS[sym]['mode']
                
                # --- 1. 部位管理 (出場邏輯) ---
                if pos:
                    pnl = 0
                    is_closed = False
                    close_reason = ""
                    
                    # 檢查停損 (SL) 或保本 (BE)
                    if (pos['side'] == 'LONG' and bar['l'] <= pos['sl']) or \
                       (pos['side'] == 'SHORT' and bar['h'] >= pos['sl']):
                        pnl = (pos['sl'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                        is_closed = True
                        close_reason = "SL/BE 觸發"
                    
                    # 檢查 TP1 (平倉 50%)
                    elif not pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and bar['h'] >= pos['tp1']) or \
                           (pos['side'] == 'SHORT' and bar['l'] <= pos['tp1']):
                            # 獲利了結一半，並將 SL 移至保本點 (BE)
                            realized_pnl = (pos['tp1'] - pos['entry']) * (pos['qty'] * 0.5) * (1 if pos['side'] == 'LONG' else -1)
                            self.update_balance(sym, realized_pnl)
                            pos['qty'] *= 0.5
                            pos['tp1_hit'] = True
                            pos['sl'] = pos['be_target'] # 保本平移
                    
                    # 檢查 TP2 (剩餘 50% 放飛)
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
                        continue # 剛平倉這根 K 線不開新倉

                # --- 2. 訊號掃描 (進場邏輯 - 擷取 v6 核心) ---
                if not self.positions[sym]:
                    current_balance = self.get_balance(sym)
                    if current_balance <= 0: continue
                    
                    sig_side, entry, sl, be_tgt, tp1, tp2 = None, 0, 0, 0, 0, 0
                    
                    if mode == 'gold_macro_donchian':
                        macro_trend = 1 if bar['c'] > bar['macro_trend_ma'] else -1
                        if macro_trend == 1 and bar['c'] > bar['dc_high'] and bar['poc'] < bar['c']:
                            sig_side, entry = 'LONG', bar['c']
                            sl = min(bar['dc_low'], bar['poc']) * 0.998
                        elif macro_trend == -1 and bar['c'] < bar['dc_low'] and bar['poc'] > bar['c']:
                            sig_side, entry = 'SHORT', bar['c']
                            sl = max(bar['dc_high'], bar['poc']) * 1.002
                            
                        if sig_side:
                            risk_dist = abs(entry - sl)
                            be_tgt = entry + (risk_dist * 1.5) * (1 if sig_side=='LONG' else -1)
                            tp1 = entry + (risk_dist * 3.0) * (1 if sig_side=='LONG' else -1)
                            tp2 = entry + (risk_dist * 6.0) * (1 if sig_side=='LONG' else -1)

                    # (此處省略 crypto_ict_fvg 與 stock_pullback 的進場細節，邏輯同 v6 實盤)
                    
                    # --- 3. 執行開倉與 3% 風控 ---
                    if sig_side:
                        price_diff = abs(entry - sl)
                        if price_diff > 0:
                            # 3% 固定風險控管
                            risk_amount = current_balance * 0.03
                            qty = risk_amount / price_diff
                            
                            self.positions[sym] = {
                                'side': sig_side, 'entry': entry, 'qty': qty,
                                'sl': sl, 'be_target': be_tgt, 'tp1': tp1, 'tp2': tp2,
                                'tp1_hit': False, 'entry_time': current_time
                            }

    def generate_report(self):
        df_trades = pd.DataFrame(self.trade_history)
        if df_trades.empty:
            return "無交易紀錄"
        
        total_trades = len(df_trades)
        win_rate = len(df_trades[df_trades['pnl'] > 0]) / total_trades * 100
        
        if self.pool_mode == 'isolated':
            final_cap = sum(self.balances.values())
            init_cap = len(self.balances) * self.initial_capital
        else:
            final_cap = self.shared_balance
            init_cap = self.initial_capital
            
        return (f"回測模式: {self.pool_mode} | 總交易次數: {total_trades} | 勝率: {win_rate:.1f}%\n"
                f"初始總資金: {init_cap} USDT -> 最終總資金: {final_cap:.2f} USDT\n"
                f"總報酬率: {((final_cap - init_cap) / init_cap) * 100:.2f}%")

# ==================== 4. 啟動回測 (30d / 365d 控制) ====================
# 假設 data_dict 是一個包含歷史 dataframe 的字典: {'XAU': df_xau, 'ETH': df_eth}
# 控制 30 天或 365 天回測，只需在餵入資料時裁切 DataFrame：
# df_30d = df_raw.loc[df_raw.index >= (df_raw.index[-1] - pd.Timedelta(days=30))]
# df_365d = df_raw.loc[df_raw.index >= (df_raw.index[-1] - pd.Timedelta(days=365))]

# 執行情境 A: 1000u 個別獨立運作 (三個標的需要 3000u 總本金)
# backtester_isolated = V6Backtester(data_dict, initial_capital=1000, pool_mode='isolated')
# backtester_isolated.run_simulation()
# print(backtester_isolated.generate_report())

# 執行情境 B: 1000u 全部共享資金池 (三個標的共用 1000u)
# backtester_shared = V6Backtester(data_dict, initial_capital=1000, pool_mode='shared')
# backtester_shared.run_simulation()
# print(backtester_shared.generate_report())
