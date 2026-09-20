import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

# ==================== 1. 回測環境與標的設定 (統一 V6 邏輯) ====================
# 不再需要區分 mode，全資產統一採用 V6 POC 突破回踩策略
SYMBOLS = {
    'BTC':   {'interval': '15m'},
    'ETH':   {'interval': '15m'},
    'SOL':   {'interval': '15m'},
    'BNB':   {'interval': '15m'},
    'DOGE':  {'interval': '15m'},
    
    'XAU':   {'interval': '4h'},  # 依你要求，維持幣安合約抓取
    
    'MSFT':  {'interval': '1h'},
    'MU':    {'interval': '1h'},
    'TSM':   {'interval': '1h'},
    'NVDA':  {'interval': '1h'},
    'AMD':   {'interval': '1h'},
    'AAPL':  {'interval': '1h'},
    'GOOGL': {'interval': '1h'},
    'AMZN':  {'interval': '1h'},
    'META':  {'interval': '1h'},
    'TSLA':  {'interval': '1h'},
    'GLW':   {'interval': '1h'},
    'SPCX':  {'interval': '1h'},
    'SNDK':  {'interval': '1h'}
}

# 隱藏 Webhook，自 GitHub Secrets 讀取
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ==================== 2. 歷史資料獲取模組 (雙資料源智慧路由) ====================
def fetch_historical_data(sym_key, cfg, days=365):
    interval = cfg['interval']
    crypto_list = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE']
    
    # 幣安節點：加密貨幣走 Spot，黃金 XAU 走 Futures
    if sym_key in crypto_list or sym_key == 'XAU':
        symbol = f"{sym_key}USDT"
        end_time = int(time.time() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)
        all_klines = []
        print(f"下載 {symbol} (Binance {interval}) {days}天...", end="", flush=True)
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        while True:
            if sym_key == 'XAU':
                url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=1500&startTime={start_time}"
            else:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000&startTime={start_time}"
                
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code != 200:
                    print(f" HTTP {res.status_code} 失敗", end="")
                    break
                data = res.json()
                if not isinstance(data, list) or len(data) == 0: break
                all_klines.extend(data)
                start_time = data[-1][0] + 1 
                if start_time >= end_time: break
                time.sleep(0.3)
            except Exception as e:
                print(f" Error: {e}", end="")
                break
                
        if not all_klines:
            print(" 無資料")
            return None
            
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_klines, columns=cols)
        for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        df = df.set_index('time')[['o', 'h', 'l', 'c', 'v']]
        df = df[~df.index.duplicated(keep='first')]
        print(f" 完成 ({len(df)} 根K線)")
        return df

    else:
        # Yahoo Finance 節點：避開美國 IP 的美股合約阻擋 (HTTP 451)
        print(f"下載 {sym_key} (Yahoo {interval}) {days}天...", end="", flush=True)
        try:
            tk = yf.Ticker(sym_key)
            df = tk.history(period=f"{days}d", interval=interval)
            if df.empty:
                print(" 失敗 (無資料)")
                return None
                
            df = df.reset_index()
            col_name = 'Datetime' if 'Datetime' in df.columns else 'Date'
            df['time'] = pd.to_datetime(df[col_name], utc=True).dt.tz_localize(None)
            df = df.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'})
            df = df.set_index('time')[['o', 'h', 'l', 'c', 'v']]
            print(f" 完成 ({len(df)} 根K線)")
            return df
        except Exception as e:
            print(f" 失敗 ({e})")
            return None

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL: return
    try:
        if len(content) <= 1900:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
        else:
            lines = content.split('\n')
            chunk, in_code_block = "", False
            for line in lines:
                if "```" in line: in_code_block = not in_code_block
                if len(chunk) + len(line) > 1900:
                    if in_code_block: chunk += "```\n"
                    requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=8)
                    chunk = ("```text\n" if in_code_block else "") + line + "\n"
                    time.sleep(0.5)
                else: chunk += line + "\n"
            if chunk.strip(): requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=8)
    except Exception:
        pass

# ==================== 3. 指標與核心邏輯預處理 (純正 V6 邏輯) ====================
def prepare_backtest_indicators(df):
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    # 建立 50 根 K 線的盤整箱體 (Accumulation Box) 與 POC
    acc_window = 50
    c_vals = df['c'].values
    v_vals = df['v'].values
    h_vals = df['h'].values
    l_vals = df['l'].values
    
    poc_list = np.full(len(df), np.nan)
    acc_high_list = np.full(len(df), np.nan)
    acc_low_list = np.full(len(df), np.nan)
    
    for i in range(acc_window, len(df)):
        # 過去 50 根的箱體高低點
        acc_high_list[i] = np.max(h_vals[i-acc_window : i])
        acc_low_list[i] = np.min(l_vals[i-acc_window : i])
        
        # 過去 50 根的籌碼密集區 POC (NumPy 極速陣列計算)
        p_win = c_vals[i-acc_window : i]
        v_win = v_vals[i-acc_window : i]
        hist, bin_edges = np.histogram(p_win, bins=50, weights=v_win)
        max_idx = np.argmax(hist)
        poc_list[i] = (bin_edges[max_idx] + bin_edges[max_idx+1]) / 2
        
    df['poc'] = poc_list
    df['acc_high'] = acc_high_list
    df['acc_low'] = acc_low_list
    
    return df.dropna()

# ==================== 4. 核心回測引擎 (狀態機精準捕捉回踩) ====================
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
        # 用於追蹤「已突破，等待回踩 POC」的狀態機
        self.setup_watch = {sym: None for sym in data_dict.keys()}
        self.trade_history = []
        
        self.arrays = {}
        for sym, df in self.data.items():
            self.arrays[sym] = {
                'time': df.index.values, 'o': df['o'].values, 'h': df['h'].values,
                'l': df['l'].values, 'c': df['c'].values, 'poc': df['poc'].values,
                'ema200': df['ema200'].values, 'acc_high': df['acc_high'].values, 'acc_low': df['acc_low'].values
            }

    def get_balance(self, sym):
        return self.balances[sym] if self.pool_mode == 'isolated' else self.shared_balance

    def update_balance(self, sym, pnl):
        if self.pool_mode == 'isolated':
            self.balances[sym] += pnl
        else:
            self.shared_balance += pnl

    def run_simulation(self):
        all_times = sorted(list(set(t for df in self.data.values() for t in df.index)))
        pointers = {sym: 0 for sym in self.data.keys()}
        
        for current_time in all_times:
            for sym in self.data.keys():
                arrs = self.arrays[sym]
                idx = pointers[sym]
                
                if idx >= len(arrs['time']) or arrs['time'][idx] != current_time:
                    continue
                
                pointers[sym] += 1
                i = idx
                pos = self.positions[sym]
                
                # --- A. 平倉邏輯 (動態 3R/6R + 保本平移) ---
                if pos:
                    pnl = 0
                    is_closed = False
                    close_reason = ""
                    
                    if (pos['side'] == 'LONG' and arrs['l'][i] <= pos['sl']) or \
                       (pos['side'] == 'SHORT' and arrs['h'][i] >= pos['sl']):
                        pnl = (pos['sl'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                        is_closed = True
                        close_reason = "SL 觸發 (含保本)"
                    
                    elif not pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and arrs['h'][i] >= pos['tp1']) or \
                           (pos['side'] == 'SHORT' and arrs['l'][i] <= pos['tp1']):
                            realized_pnl = (pos['tp1'] - pos['entry']) * (pos['qty'] * 0.5) * (1 if pos['side'] == 'LONG' else -1)
                            self.update_balance(sym, realized_pnl)
                            pos['qty'] *= 0.5
                            pos['tp1_hit'] = True
                            pos['sl'] = pos['be_target'] 
                    
                    elif pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and arrs['h'][i] >= pos['tp2']) or \
                           (pos['side'] == 'SHORT' and arrs['l'][i] <= pos['tp2']):
                            pnl = (pos['tp2'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                            is_closed = True
                            close_reason = "TP2 (趨勢延續) 達標"

                    if is_closed:
                        self.update_balance(sym, pnl)
                        self.trade_history.append({
                            'symbol': sym, 'exit_time': current_time, 'pnl': pnl, 
                            'reason': close_reason, 'balance': self.get_balance(sym)
                        })
                        self.positions[sym] = None
                        continue

                # --- B. 進場邏輯 (影片 V6 核心：突破後等待回踩) ---
                if not self.positions[sym]:
                    current_balance = self.get_balance(sym)
                    if current_balance <= 50: continue 
                    
                    sig_side, entry, sl = None, 0, 0
                    
                    # 1. 檢查是否有正在埋伏的突破單 (等待 Pullback)
                    if self.setup_watch[sym]:
                        watch = self.setup_watch[sym]
                        watch['ttl'] -= 1
                        
                        if watch['ttl'] <= 0:
                            self.setup_watch[sym] = None # 超時未回踩，放棄該次突破
                        else:
                            # 觸發回踩 POC：當 K 線最低點戳到 POC (多單)，或是最高點摸到 POC (空單)
                            if watch['side'] == 'LONG' and arrs['l'][i] <= watch['poc']:
                                sig_side = 'LONG'
                                entry = watch['poc'] # 限價 POC 完美進場
                                sl = watch['sl']
                                self.setup_watch[sym] = None
                                
                            elif watch['side'] == 'SHORT' and arrs['h'][i] >= watch['poc']:
                                sig_side = 'SHORT'
                                entry = watch['poc']
                                sl = watch['sl']
                                self.setup_watch[sym] = None

                    # 2. 若無訊號，則掃描是否產生「新突破 (Breakout)」
                    if not sig_side:
                        # 多方突破：收盤價站上箱體頂部，且大趨勢看多
                        if arrs['c'][i] > arrs['acc_high'][i] and arrs['c'][i] > arrs['ema200'][i]:
                            self.setup_watch[sym] = {
                                'side': 'LONG',
                                'poc': arrs['poc'][i],
                                'sl': arrs['acc_low'][i] * 0.998, # 止損掛在整個箱體下緣外側
                                'ttl': 20 # 給予 20 根 K 線的耐心等待回踩
                            }
                        # 空方突破：收盤價跌破箱體底部，且大趨勢看空
                        elif arrs['c'][i] < arrs['acc_low'][i] and arrs['c'][i] < arrs['ema200'][i]:
                            self.setup_watch[sym] = {
                                'side': 'SHORT',
                                'poc': arrs['poc'][i],
                                'sl': arrs['acc_high'][i] * 1.002, # 止損掛在整個箱體上緣外側
                                'ttl': 20
                            }

                    # 3. 執行 3% 風控開倉計算
                    if sig_side:
                        risk_dist = abs(entry - sl)
                        if risk_dist > 0:
                            be_tgt = entry + (risk_dist * 2.0) * (1 if sig_side=='LONG' else -1)
                            tp1 = entry + (risk_dist * 3.0) * (1 if sig_side=='LONG' else -1) # 3R 止盈一半
                            tp2 = entry + (risk_dist * 6.0) * (1 if sig_side=='LONG' else -1) # 6R 趨勢放飛
                            
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

# ==================== 5. 主執行區塊 ====================
if __name__ == '__main__':
    BACKTEST_DAYS = 365
    print(f"🚀 開始準備歷史數據 (設定為 {BACKTEST_DAYS} 天測試)...")
    
    data_dict = {}
    for sym_key, cfg in SYMBOLS.items():
        df_raw = fetch_historical_data(sym_key, cfg, days=BACKTEST_DAYS)
        if df_raw is not None and not df_raw.empty:
            df_processed = prepare_backtest_indicators(df_raw)
            data_dict[sym_key] = df_processed

    if not data_dict:
        print("❌ 無法獲取任何資料，程式結束。")
    else:
        print("\n📈 數據準備完成，開始執行回測引擎...")
        
        print("\n>>> 啟動 Isolated (個別資金池) 回測...")
        bt_isolated = V6Backtester(data_dict, initial_capital=1000, pool_mode='isolated')
        bt_isolated.run_simulation()
        report_isolated = bt_isolated.generate_report()
        print(report_isolated)

        print("\n>>> 啟動 Shared (共享資金池) 回測...")
        bt_shared = V6Backtester(data_dict, initial_capital=1000, pool_mode='shared')
        bt_shared.run_simulation()
        report_shared = bt_shared.generate_report()
        print(report_shared)
        
        print("\n✅ 所有回測任務執行完畢！正在推播至 Discord...")
        
        discord_msg = f"```text\n🏆 【純正 V6 POC 突破回測完成】 (回測期間: {BACKTEST_DAYS} 天)\n\n"
        discord_msg += report_isolated + "\n" + report_shared
        discord_msg += "```"
        send_discord_safe(discord_msg)
