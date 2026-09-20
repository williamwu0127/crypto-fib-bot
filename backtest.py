import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import zoneinfo
from datetime import datetime, timezone, timedelta

# ==================== 1. 回測環境與標的設定 ====================
SYMBOLS = {
    'BTC':   {'interval': '15m'},
    'ETH':   {'interval': '15m'},
    'SOL':   {'interval': '15m'},
    'BNB':   {'interval': '15m'},
    'DOGE':  {'interval': '15m'},
    'XAU':   {'interval': '4h'},  
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

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ==================== 2. 歷史資料獲取模組 ====================
def fetch_historical_data(sym_key, cfg, days=365):
    interval = cfg['interval']
    crypto_list = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE']
    
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
                if res.status_code != 200: break
                data = res.json()
                if not isinstance(data, list) or len(data) == 0: break
                all_klines.extend(data)
                start_time = data[-1][0] + 1 
                if start_time >= end_time: break
                time.sleep(0.3)
            except: break
                
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
        print(f"下載 {sym_key} (Yahoo {interval}) {days}天...", end="", flush=True)
        try:
            tk = yf.Ticker(sym_key)
            df = tk.history(period=f"{days}d", interval=interval)
            if df.empty:
                print(" 失敗")
                return None
                
            df = df.reset_index()
            col_name = 'Datetime' if 'Datetime' in df.columns else 'Date'
            df['time'] = pd.to_datetime(df[col_name], utc=True).dt.tz_localize(None)
            df = df.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'})
            df = df.set_index('time')[['o', 'h', 'l', 'c', 'v']]
            print(f" 完成 ({len(df)} 根K線)")
            return df
        except:
            print(" 失敗")
            return None

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL: return
    try:
        if len(content) <= 1900: requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
        else:
            chunk = ""
            for line in content.split('\n'):
                if len(chunk) + len(line) > 1900:
                    requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=8)
                    chunk, time.sleep(0.5) = line + "\n", None
                else: chunk += line + "\n"
            if chunk.strip(): requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=8)
    except: pass

# ==================== 3. 指標與核心邏輯預處理 ====================
def prepare_backtest_indicators(df, sym_key):
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    acc_window = 50
    c_vals, v_vals, h_vals, l_vals = df['c'].values, df['v'].values, df['h'].values, df['l'].values
    poc_list, acc_high_list, acc_low_list = np.full(len(df), np.nan), np.full(len(df), np.nan), np.full(len(df), np.nan)
    
    for i in range(acc_window, len(df)):
        acc_high_list[i], acc_low_list[i] = np.max(h_vals[i-acc_window : i]), np.min(l_vals[i-acc_window : i])
        hist, bin_edges = np.histogram(c_vals[i-acc_window : i], bins=50, weights=v_vals[i-acc_window : i])
        poc_list[i] = (bin_edges[np.argmax(hist)] + bin_edges[np.argmax(hist)+1]) / 2
        
    df['poc'], df['acc_high'], df['acc_low'] = poc_list, acc_high_list, acc_low_list
    
    # 效能升級：向量化交易時段過濾，取代迴圈計算
    ny_time = df.index.tz_localize('UTC').tz_convert('America/New_York')
    if sym_key in ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE']:
        df['is_tradable'] = True
    elif sym_key == 'XAU':
        is_closed = ((ny_time.weekday == 4) & (ny_time.hour >= 17)) | (ny_time.weekday == 5) | \
                    ((ny_time.weekday == 6) & (ny_time.hour < 18)) | (ny_time.hour == 17)
        df['is_tradable'] = ~is_closed
    else:
        time_val = ny_time.hour + ny_time.minute / 60.0
        df['is_tradable'] = (ny_time.weekday < 5) & (time_val >= 9.5) & (time_val < 16.0)

    # 效能升級與防斷流：ICT 流動性指標 cummax().ffill()
    df['date'] = ny_time.date
    is_ldn = (ny_time.hour >= 2) & (ny_time.hour < 5)
    is_ny = (ny_time.hour >= 7) & (ny_time.hour < 10)
    
    df['ldn_h'] = df['h'].where(is_ldn).groupby(df['date']).cummax().ffill()
    df['ldn_l'] = df['l'].where(is_ldn).groupby(df['date']).cummin().ffill()
    df['ny_h'] = df['h'].where(is_ny).groupby(df['date']).cummax().ffill()
    df['ny_l'] = df['l'].where(is_ny).groupby(df['date']).cummin().ffill()
    
    return df.dropna(subset=['ema200', 'poc'])

# ==================== 4. 核心回測引擎 ====================
class V6Backtester:
    def __init__(self, data_dict, initial_capital=1000, pool_mode='isolated'):
        self.data, self.pool_mode, self.initial_capital = data_dict, pool_mode, initial_capital
        self.balances = {sym: initial_capital for sym in data_dict.keys()} if pool_mode == 'isolated' else initial_capital
        self.shared_balance = initial_capital if pool_mode != 'isolated' else 0
        self.positions, self.setup_watch, self.trade_history = {sym: None for sym in data_dict.keys()}, {sym: None for sym in data_dict.keys()}, []
        
        self.arrays = {}
        for sym, df in self.data.items():
            self.arrays[sym] = {
                'time': df.index.values, 'o': df['o'].values, 'h': df['h'].values, 'l': df['l'].values, 'c': df['c'].values, 
                'poc': df['poc'].values, 'ema200': df['ema200'].values, 'acc_high': df['acc_high'].values, 'acc_low': df['acc_low'].values,
                'is_tradable': df['is_tradable'].values
            }

    def get_balance(self, sym): return self.balances[sym] if self.pool_mode == 'isolated' else self.shared_balance

    def update_balance(self, sym, pnl):
        if self.pool_mode == 'isolated': self.balances[sym] += pnl
        else: self.shared_balance += pnl

    def run_simulation(self):
        all_times = sorted(list(set(t for df in self.data.values() for t in df.index)))
        pointers = {sym: 0 for sym in self.data.keys()}
        
        for current_time in all_times:
            for sym in self.data.keys():
                arrs, idx = self.arrays[sym], pointers[sym]
                if idx >= len(arrs['time']) or arrs['time'][idx] != current_time: continue
                
                pointers[sym] += 1
                i, pos = idx, self.positions[sym]
                
                # --- A. 平倉與保本平移邏輯 (對齊 Server) ---
                if pos:
                    step_pnl, is_closed, close_reason = 0, False, ""
                    
                    if (pos['side'] == 'LONG' and arrs['l'][i] <= pos['sl']) or (pos['side'] == 'SHORT' and arrs['h'][i] >= pos['sl']):
                        step_pnl = (pos['sl'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                        pos['accumulated_pnl'] += step_pnl
                        is_closed, close_reason = True, "SL 觸發 (含保本)"
                    
                    elif not pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and arrs['h'][i] >= pos['tp1']) or (pos['side'] == 'SHORT' and arrs['l'][i] <= pos['tp1']):
                            realized_pnl = (pos['tp1'] - pos['entry']) * (pos['qty'] * 0.5) * (1 if pos['side'] == 'LONG' else -1)
                            self.update_balance(sym, realized_pnl)
                            pos['accumulated_pnl'] += realized_pnl
                            pos['qty'] *= 0.5
                            pos['tp1_hit'] = True
                            pos['sl'] = pos['entry'] # 完美對齊：TP1 後止損移至 True Breakeven (0風險)
                    
                    elif pos['tp1_hit']:
                        if (pos['side'] == 'LONG' and arrs['h'][i] >= pos['tp2']) or (pos['side'] == 'SHORT' and arrs['l'][i] <= pos['tp2']):
                            step_pnl = (pos['tp2'] - pos['entry']) * pos['qty'] * (1 if pos['side'] == 'LONG' else -1)
                            pos['accumulated_pnl'] += step_pnl
                            is_closed, close_reason = True, "TP2 (趨勢延續) 達標"

                    if is_closed:
                        self.update_balance(sym, step_pnl)
                        self.trade_history.append({'symbol': sym, 'exit_time': current_time, 'pnl': pos['accumulated_pnl'], 'reason': close_reason, 'balance': self.get_balance(sym)})
                        self.positions[sym] = None
                        continue

                # --- B. 進場邏輯 (對齊休市過濾與限價成交) ---
                if not self.positions[sym]:
                    current_balance = self.get_balance(sym)
                    if current_balance <= 50: continue 
                    
                    sig_side, entry, sl = None, 0, 0
                    
                    if self.setup_watch[sym]:
                        watch = self.setup_watch[sym]
                        watch['ttl'] -= 1
                        if watch['ttl'] <= 0: self.setup_watch[sym] = None
                        else:
                            if watch['side'] == 'LONG' and arrs['l'][i] <= watch['poc']: sig_side, entry, sl, self.setup_watch[sym] = 'LONG', watch['poc'], watch['sl'], None
                            elif watch['side'] == 'SHORT' and arrs['h'][i] >= watch['poc']: sig_side, entry, sl, self.setup_watch[sym] = 'SHORT', watch['poc'], watch['sl'], None

                    if not sig_side and arrs['is_tradable'][i]: # 高效向量化時段檢查
                        if arrs['c'][i] > arrs['acc_high'][i] and arrs['c'][i] > arrs['ema200'][i]:
                            self.setup_watch[sym] = {'side': 'LONG', 'poc': arrs['poc'][i], 'sl': arrs['acc_low'][i] * 0.998, 'ttl': 20}
                        elif arrs['c'][i] < arrs['acc_low'][i] and arrs['c'][i] < arrs['ema200'][i]:
                            self.setup_watch[sym] = {'side': 'SHORT', 'poc': arrs['poc'][i], 'sl': arrs['acc_high'][i] * 1.002, 'ttl': 20}

                    if sig_side:
                        risk_dist = abs(entry - sl)
                        if risk_dist > 0:
                            tp1 = entry + (risk_dist * 3.0) * (1 if sig_side=='LONG' else -1)
                            tp2 = entry + (risk_dist * 6.0) * (1 if sig_side=='LONG' else -1)
                            
                            self.positions[sym] = {
                                'side': sig_side, 'entry': entry, 'qty': (current_balance * 0.03) / risk_dist,
                                'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'entry_time': current_time, 'accumulated_pnl': 0.0
                            }

    def generate_report(self):
        df_trades = pd.DataFrame(self.trade_history)
        if df_trades.empty: return f"[{self.pool_mode}] 模式: 無交易紀錄"
        
        total_trades = len(df_trades)
        win_rate = len(df_trades[df_trades['pnl'] > 0]) / total_trades * 100
        init_cap = len(self.balances) * self.initial_capital if self.pool_mode == 'isolated' else self.initial_capital
        final_cap = sum(self.balances.values()) if self.pool_mode == 'isolated' else self.shared_balance
            
        report = (
            f"========== 回測報表 ({self.pool_mode.upper()} 模式) ==========\n"
            f"總交易次數: {total_trades} | 整體勝率: {win_rate:.1f}%\n"
            f"初始總資金: {init_cap} USDT -> 最終總資金: {final_cap:.2f} USDT\n"
            f"總報酬率: {((final_cap - init_cap) / init_cap) * 100:.2f}%\n"
            f"--------------------------------------------------\n"
            f"【各項標的單獨表現】\n"
        )
        
        for sym in self.data.keys():
            sym_trades = df_trades[df_trades['symbol'] == sym] if 'symbol' in df_trades else pd.DataFrame()
            if sym_trades.empty:
                report += f"{sym:<5} | 次數: 0\n"
                continue
                
            s_count = len(sym_trades)
            s_win = len(sym_trades[sym_trades['pnl'] > 0]) / s_count * 100
            s_pnl = sym_trades['pnl'].sum()
            pnl_sign = "+" if s_pnl > 0 else ""
            
            if self.pool_mode == 'isolated':
                s_ret = ((self.balances[sym] - self.initial_capital) / self.initial_capital) * 100
                report += f"{sym:<5} | 次數: {s_count:<3} | 勝率: {s_win:>5.1f}% | 淨利: {pnl_sign}{s_pnl:.2f} USDT ({s_ret:+.2f}%)\n"
            else:
                report += f"{sym:<5} | 次數: {s_count:<3} | 勝率: {s_win:>5.1f}% | 淨利: {pnl_sign}{s_pnl:.2f} USDT\n"

        report += f"--------------------------------------------------\n"
        return report

# ==================== 5. 主執行區塊 ====================
if __name__ == '__main__':
    BACKTEST_DAYS = 365
    print(f"🚀 開始準備歷史數據 (設定為 {BACKTEST_DAYS} 天測試)...")
    
    data_dict = {}
    for sym_key, cfg in SYMBOLS.items():
        df_raw = fetch_historical_data(sym_key, cfg, days=BACKTEST_DAYS)
        if df_raw is not None and not df_raw.empty:
            df_processed = prepare_backtest_indicators(df_raw, sym_key)
            data_dict[sym_key] = df_processed

    if not data_dict: print("❌ 無法獲取任何資料，程式結束。")
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
        discord_msg = f"```text\n🏆 【純正 V6 POC 突破回測完成】 (回測期間: {BACKTEST_DAYS} 天)\n\n{report_isolated}\n{report_shared}```"
        send_discord_safe(discord_msg)
