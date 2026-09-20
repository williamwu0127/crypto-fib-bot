import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import math

# ==================== 1. 回測環境與標的設定 ====================
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

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

# ==================== 2. 歷史資料獲取模組 (智慧路由版) ====================
def fetch_binance_data(symbol_key, cfg, days=365):
    """根據商品屬性自動路由至現貨或合約 API"""
    symbol = cfg.get('s', f"{symbol_key}USDT")
    interval = cfg['interval']
    mode = cfg['mode']
    
    # 判斷是否為美股合約標的
    is_futures_only = (mode == 'stock_pullback') or (symbol_key in ['MSFT', 'MU', 'TSM', 'NVDA'])
    
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_klines = []
    print(f"下載 {symbol} ({interval}) {days}天資料...", end="", flush=True)
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    while True:
        if is_futures_only:
            # 美股標的路由至 fapi (合約)
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=1500&startTime={start_time}"
        else:
            # 加密貨幣路由至 data-api (現貨)
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000&startTime={start_time}"
            
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f" HTTP {res.status_code} 失敗", end="")
                break
                
            data = res.json()
            if not isinstance(data, list) or len(data) == 0:
                break
            
            all_klines.extend(data)
            start_time = data[-1][0] + 1 
            
            if start_time >= end_time:
                break
            time.sleep(0.3) # 避免觸發限流
        except Exception as e:
            print(f" Error: {e}", end="")
            break
            
    if not all_klines:
        print("")
        return None
        
    cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
    df = pd.DataFrame(all_klines, columns=cols)
    for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
    df['time'] = pd.to_datetime(df['t'], unit='ms')
    df = df.set_index('time')[['o', 'h', 'l', 'c', 'v']]
    df = df[~df.index.duplicated(keep='first')]
    print(f" 完成 ({len(df)} 根K線)")
    return df

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
    except Exception as e:
        print(f"Discord 推播失敗: {e}")

# ==================== 3. 指標與核心邏輯預處理 ====================
def prepare_backtest_indicators(df, mode):
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
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
        df['macro_trend_ma'] = df['c'].rolling(60).mean() 
        
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
                            pos['sl'] = pos['be_target'] 
                    
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

                if not self.positions[sym]:
                    current_balance = self.get_balance(sym)
                    if current_balance <= 50: continue 
                    
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
                        bias = 'LONG' if bar['c'] > bar['ema200'] else 'SHORT'
                        if bias == 'LONG':
                            if bar['c'] >= bar['ema20'] and bar['l'] <= bar['ema50']: 
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

# ==================== 5. 主執行區塊 ====================
if __name__ == '__main__':
    BACKTEST_DAYS = 365
    print(f"🚀 開始準備歷史數據 (設定為 {BACKTEST_DAYS} 天測試)...")
    
    data_dict = {}
    for sym_key, cfg in SYMBOLS.items():
        df_raw = fetch_binance_data(sym_key, cfg, days=BACKTEST_DAYS)
        if df_raw is not None and not df_raw.empty:
            df_processed = prepare_backtest_indicators(df_raw, cfg['mode'])
            data_dict[sym_key] = df_processed

    if not data_dict:
        print("❌ 無法獲取任何資料，程式結束。")
    else:
        print("\n📈 數據準備完成，開始執行回測引擎...")
        
        # 執行情境 A: 1000u 個別獨立運作
        print("\n>>> 啟動 Isolated (個別資金池) 回測...")
        bt_isolated = V6Backtester(data_dict, initial_capital=1000, pool_mode='isolated')
        bt_isolated.run_simulation()
        report_isolated = bt_isolated.generate_report()
        print(report_isolated)

        # 執行情境 B: 1000u 全部共享資金池
        print("\n>>> 啟動 Shared (共享資金池) 回測...")
        bt_shared = V6Backtester(data_dict, initial_capital=1000, pool_mode='shared')
        bt_shared.run_simulation()
        report_shared = bt_shared.generate_report()
        print(report_shared)
        
        print("\n✅ 所有回測任務執行完畢！正在推播至 Discord...")
        
        # 組合 Discord 推播內容
        discord_msg = f"```text\n🏆 【V6 POC 共振量化回測完成】 (回測期間: {BACKTEST_DAYS} 天)\n\n"
        discord_msg += report_isolated + "\n" + report_shared
        discord_msg += "```"
        send_discord_safe(discord_msg)
