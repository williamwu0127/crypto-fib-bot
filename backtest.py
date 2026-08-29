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
                df['timestamp'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
                return df[['timestamp', 'o', 'h', 'l', 'c', 'v']]
        else:
            # 使用最穩定的 59 天 15m 高頻抓取法，確保美股與商品個股完整回歸
            df = yf.download(cfg['s'], period="59d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.reset_index()
                cols_lower = [str(c).lower() for c in df.columns]
                df.columns = cols_lower
                
                time_col = 'datetime' if 'datetime' in df.columns else ('date' if 'date' in df.columns else df.columns[0])
                
                res_df = pd.DataFrame()
                res_df['timestamp'] = pd.to_datetime(df[time_col]).dt.tz_localize(None)
                
                for target, candidates in [('o', ['open']), ('h', ['high']), ('l', ['low']), ('c', ['close']), ('v', ['volume'])]:
                    found = False
                    for cand in candidates:
                        if cand in df.columns:
                            res_df[target] = df[cand].astype(float)
                            found = True
                            break
                    if not found:
                        return None
                
                res_df = res_df.dropna().reset_index(drop=True)
                if len(res_df) >= 50:
                    return res_df
    except Exception:
        pass
    return None

def run_backtest():
    all_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0} for sym in SYMBOLS.keys()}
    min_time = None
    max_time = None

    for sym, cfg in SYMBOLS.items():
        df = get_historical_data(cfg)
        if df is None or len(df) < 50:
            continue

        t_min = df['timestamp'].min()
        t_max = df['timestamp'].max()
        if min_time is None or t_min < min_time:
            min_time = t_min
        if max_time is None or t_max > max_time:
            max_time = t_max

        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

        for i in range(50, len(df) - 15):
            bar = df.iloc[i]
            prev_bar = df.iloc[i-1]
            
            sub = df.iloc[i-25:i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            
            if wave <= 0 or (wave / l) < 0.005:
                continue
                
            fib_0618_l = h - (wave * 0.618)
            entry_price = bar['c']
            
            rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull
            
            if cond_long:
                sl = min(l, entry_price - (bar['atr'] * 1.5))
                tp1 = entry_price + abs(entry_price - sl)
                
                outcome = None
                exit_idx = i
                for j in range(1, 11):
                    future_bar = df.iloc[i + j]
                    if future_bar['l'] <= sl:
                        outcome = 'LOSS'
                        exit_idx = i + j
                        break
                    elif future_bar['h'] >= tp1:
                        outcome = 'WIN'
                        exit_idx = i + j
                        break
                
                if outcome:
                    all_trades.append({
                        'sym': sym,
                        'time': bar['timestamp'],
                        'exit_time': df.iloc[exit_idx]['timestamp'],
                        'outcome': outcome
                    })

    all_trades = sorted(all_trades, key=lambda x: x['time'])

    initial_balance = 100.0
    balance = initial_balance
    total_trades = 0
    total_wins = 0

    for trade in all_trades:
        current_risk = balance * 0.01
        total_trades += 1
        symbol_stats[trade['sym']]['trades'] += 1

        if trade['outcome'] == 'WIN':
            balance += current_risk * 1.5
            total_wins += 1
            symbol_stats[trade['sym']]['wins'] += 1
        else:
            balance -= current_risk

    crypto_reports = []
    stock_reports = []
    
    for sym, stats in symbol_stats.items():
        t_cnt = stats['trades']
        w_cnt = stats['wins']
        w_rate = (w_cnt / t_cnt * 100) if t_cnt > 0 else 0
        if t_cnt > 0:
            line = sym + " | 交易: " + str(t_cnt) + "次 | 勝率: " + str(round(w_rate, 1)) + "%"
            if SYMBOLS[sym]['t'] == 'binance' or sym == 'XAU':
                crypto_reports.append(line)
            else:
                stock_reports.append(line)

    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    profit_loss_pct = ((balance - initial_balance) / initial_balance) * 100
    time_range_str = str(min_time).split()[0] + " ~ " + str(max_time).split()[0] if min_time and max_time else "N/A"

    msg1 = "\n".join([
        "📊 **[15m 高頻時間軸 + 複利滾動回測 (1/2)]**",
        "```text",
        "判定邏輯: 15m K線 | EMA50/200趨勢 + Fib 0.618回撤 + RSI動能",
        "回測區間: " + time_range_str,
        "初始資金: $" + str(round(initial_balance, 2)) + " USDT",
        "最終結餘: $" + str(round(balance, 2)) + " USDT (" + str(round(profit_loss_pct, 2)) + "%)",
        "總交易次數: " + str(total_trades) + " 次 | 綜合勝率: " + str(round(overall_win_rate, 1)) + "%",
        "----------------------------------------------------",
        "\n".join(crypto_reports),
        "```"
    ])

    msg2 = "\n".join([
        "📊 **[15m 高頻時間軸 + 複利滾動回測 (2/2) - 美股與商品]**",
        "```text",
        "\n".join(stock_reports),
        "```"
    ])
    
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "你的Discord網址":
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg1}, timeout=8)
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg2}, timeout=8)
        except Exception:
            pass

    print(msg1)
    print(msg2)

if __name__ == '__main__':
    run_backtest()
