import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "你的Discord網址")

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

def get_historical_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = "https://data-api.binance.vision/api/v3/klines?symbol=" + cfg['s'] + "&interval=15m&limit=1000"
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) >= 100:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                return df[['o', 'h', 'l', 'c', 'v']]
        else:
            df = yf.download(cfg['s'], period="60d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def run_backtest():
    initial_balance = 100.0
    balance = initial_balance
    total_trades = 0
    total_wins = 0
    symbol_reports = []

    for sym, cfg in SYMBOLS.items():
        df = get_historical_data(cfg)
        if df is None or len(df) < 100:
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

        for i in range(50, len(df) - 1):
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
                
                next_bar = df.iloc[i+1]
                total_trades += 1
                sym_trades += 1
                if next_bar['l'] <= sl:
                    balance -= current_risk
                elif next_bar['h'] >= tp1:
                    balance += current_risk * 1.5
                    total_wins += 1
                    sym_wins += 1

        win_rate = (sym_wins / sym_trades * 100) if sym_trades > 0 else 0
        symbol_reports.append(sym + " | 交易: " + str(sym_trades) + "次 | 勝率: " + str(round(win_rate, 1)) + "%")

    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    profit_loss_pct = ((balance - initial_balance) / initial_balance) * 100

    report = [
        "📊 **[20檔標的 15m 綜合回測報告]**",
        "```text",
        "初始資金: $" + str(round(initial_balance, 2)) + " USDT",
        "最終結餘: $" + str(round(balance, 2)) + " USDT (" + str(round(profit_loss_pct, 2)) + "%)",
        "總交易次數: " + str(total_trades) + " 次",
        "綜合勝率: " + str(round(overall_win_rate, 1)) + "%",
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

    print(msg)

if __name__ == '__main__':
    run_backtest()
