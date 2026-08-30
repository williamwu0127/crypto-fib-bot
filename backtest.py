import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0},
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0},
    'TSM':  {'t': 'stock',   's': 'TSM',      'lev': 20.0},
    'NVDA': {'t': 'stock',   's': 'NVDA',     'lev': 20.0},
    'AMD':  {'t': 'stock',   's': 'AMD',      'lev': 20.0},
    'MSFT': {'t': 'stock',   's': 'MSFT',     'lev': 20.0},
    'AAPL': {'t': 'stock',   's': 'AAPL',     'lev': 20.0},
    'GOOGL':{'t': 'stock',   's': 'GOOGL',    'lev': 20.0},
    'AMZN': {'t': 'stock',   's': 'AMZN',     'lev': 20.0},
    'META': {'t': 'stock',   's': 'META',     'lev': 20.0},
    'TSLA': {'t': 'stock',   's': 'TSLA',     'lev': 20.0},
    'MU':   {'t': 'stock',   's': 'MU',       'lev': 20.0},
    'GLW':  {'t': 'stock',   's': 'GLW',      'lev': 20.0},
    'SPCX': {'t': 'stock',   's': 'SPCX',     'lev': 20.0},
    'SNDK': {'t': 'stock',   's': 'SNDK',     'lev': 20.0}
}

def get_1year_historical_data(cfg):
    try:
        if cfg['t'] == 'binance':
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (365 * 24 * 60 * 60 * 1000)
            all_klines = []
            curr_start = start_ms
            
            while curr_start < now_ms:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&startTime={curr_start}&limit=1000"
                res = requests.get(url, timeout=10).json()
                if not isinstance(res, list) or len(res) == 0:
                    break
                all_klines.extend(res)
                curr_start = res[-1][0] + (15 * 60 * 1000)
                time.sleep(0.04)
            
            if len(all_klines) > 200:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(all_klines, columns=cols)
                df = df.drop_duplicates(subset=['t'])
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="60d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                df['time'] = df.index.tz_convert('Asia/Taipei') if df.index.tz else df.index
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    res_df['time'] = df['time'].values
                    return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def run_backtest_1year():
    initial_balance = 100.0
    balance = initial_balance
    total_trades = 0
    total_wins = 0
    symbol_reports = []

    print(">>> 開始執行原始邏輯 1 年期回測...")

    for sym, cfg in SYMBOLS.items():
        print(f"正在分析標的: {sym.ljust(5)} ...", end=" ")
        df = get_1year_historical_data(cfg)
        if df is None or len(df) < 50:
            print("資料不足略過")
            continue

        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

        sym_trades = 0
        sym_wins = 0

        # 保留原本 10 根 K 線結算邏輯
        for i in range(50, len(df) - 15):
            current_risk = balance * 0.01
            bar = df.iloc[i]
            
            sub = df.iloc[i-25:i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            
            if wave <= 0 or (wave / l) < 0.005:
                continue
                
            fib_0618_l = h - (wave * 0.618)
            entry_price = bar['c']
            
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002)
            
            if cond_long:
                sl = min(l, entry_price - (bar['atr'] * 1.5))
                tp1 = entry_price + abs(entry_price - sl)
                
                trade_won = False
                hit_target = False
                for j in range(1, 11):
                    future_bar = df.iloc[i + j]
                    if future_bar['l'] <= sl:
                        balance -= current_risk
                        hit_target = True
                        break
                    elif future_bar['h'] >= tp1:
                        balance += current_risk * 1.5
                        trade_won = True
                        hit_target = True
                        break
                
                if hit_target:
                    total_trades += 1
                    sym_trades += 1
                    if trade_won:
                        total_wins += 1
                        sym_wins += 1

        win_rate = (sym_wins / sym_trades * 100) if sym_trades > 0 else 0
        if sym_trades > 0:
            symbol_reports.append(f"{sym.ljust(5)} | 交易: {str(sym_trades).rjust(4)}次 | 勝率: {win_rate:5.1f}%")
        print(f"完成 ({sym_trades} 次交易 | 勝率 {win_rate:.1f}%)")

    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    profit_loss_pct = ((balance - initial_balance) / initial_balance) * 100

    report = [
        "📊 **[20檔標的 15m 原始複利回測報告 (1年期)]**",
        "```text",
        f"初始資金: ${initial_balance:.2f} USDT",
        f"最終結餘: ${balance:.2f} USDT ({profit_loss_pct:+.2f}%)",
        f"總交易次數: {total_trades} 次",
        f"綜合勝率: {overall_win_rate:.1f}%",
        "----------------------------------------------------",
        "\n".join(symbol_reports),
        "```"
    ]
    
    msg = "\n".join(report)
    
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "你的Discord網址":
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=8)
        except Exception:
            pass

    print("\n" + msg)

if __name__ == '__main__':
    run_backtest_1year()
