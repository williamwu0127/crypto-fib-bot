import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT'},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT'},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT'},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT'},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT'},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT'},
    'CLU':   {'t': 'stock',   's': 'CL=F'},
    'TSM':   {'t': 'stock',   's': 'TSM'},
    'NVDA':  {'t': 'stock',   's': 'NVDA'},
    'AMD':   {'t': 'stock',   's': 'AMD'},
    'MSFT':  {'t': 'stock',   's': 'MSFT'},
    'AAPL':  {'t': 'stock',   's': 'AAPL'},
    'GOOGL': {'t': 'stock',   's': 'GOOGL'},
    'AMZN':  {'t': 'stock',   's': 'AMZN'},
    'META':  {'t': 'stock',   's': 'META'},
    'TSLA':  {'t': 'stock',   's': 'TSLA'},
    'MU':    {'t': 'stock',   's': 'MU'},
    'GLW':   {'t': 'stock',   's': 'GLW'},
    'SPCX':  {'t': 'stock',   's': 'SPCX'},
    'SNDK':  {'t': 'stock',   's': 'SNDK'}
}

START_BALANCE = 100.0
RISK_PCT = 0.01

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        if len(content) <= 1900:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
        else:
            parts = [content[i:i+1800] for i in range(0, len(content), 1800)]
            for p in parts:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": p}, timeout=8)
                time.sleep(0.5)
    except Exception:
        pass

def fetch_historical_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=1h&limit=750"
            res = requests.get(url, timeout=10).json()
            if isinstance(res, list) and len(res) > 100:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="1mo", interval="1h", progress=False)
            if df is not None and not df.empty and len(df) > 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                df['time'] = df.index.tz_convert('Asia/Taipei') if df.index.tz else df.index
                res_df = df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
                res_df.columns = ['time', 'o', 'h', 'l', 'c', 'v']
                return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def backtest_single_symbol(sym, cfg):
    df = fetch_historical_data(cfg)
    if df is None or len(df) < 60:
        return [], None, None

    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

    start_date = df.iloc[50]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    trades = []
    in_position = False
    entry_price, sl_price, tp1_price, tp2_price = 0, 0, 0, 0
    tp1_hit = False
    qty = 0
    entry_time = None

    for i in range(50, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        if in_position:
            if bar['l'] <= sl_price:
                exit_price = sl_price
                loss_per_unit = exit_price - entry_price
                remaining_qty = qty * 0.5 if tp1_hit else qty
                pnl = remaining_qty * loss_per_unit
                trades.append({
                    'symbol': sym, 'entry_time': entry_time, 'exit_time': bar['time'],
                    'entry': entry_price, 'exit': exit_price, 'pnl': pnl, 'type': 'SL'
                })
                in_position = False
                continue

            if not tp1_hit and bar['h'] >= tp1_price:
                tp1_hit = True
                gain_per_unit = tp1_price - entry_price
                trades.append({
                    'symbol': sym, 'entry_time': entry_time, 'exit_time': bar['time'],
                    'entry': entry_price, 'exit': tp1_price, 'pnl': (qty * 0.5) * gain_per_unit, 'type': 'TP1'
                })

            if tp1_hit and bar['h'] >= tp2_price:
                gain_per_unit = tp2_price - entry_price
                trades.append({
                    'symbol': sym, 'entry_time': entry_time, 'exit_time': bar['time'],
                    'entry': entry_price, 'exit': tp2_price, 'pnl': (qty * 0.5) * gain_per_unit, 'type': 'TP2'
                })
                in_position = False
                continue

        if not in_position:
            sub = df.iloc[max(0, i-35):i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            if wave <= 0 or (wave / l) < 0.01:
                continue

            fib_0618_l = h - (wave * 0.618)
            rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull

            if cond_long:
                entry_price = bar['c']
                sl_price = min(l, entry_price - (bar['atr'] * 1.5))
                tp1_price = h if h > entry_price else entry_price + abs(entry_price - sl_price)
                tp2_price = h + (wave * 0.382)
                if tp2_price <= tp1_price:
                    tp2_price = tp1_price + abs(entry_price - sl_price)

                price_diff = abs(entry_price - sl_price)
                if price_diff > 0:
                    qty = (START_BALANCE * RISK_PCT) / price_diff
                    in_position = True
                    tp1_hit = False
                    entry_time = bar['time']

    return trades, start_date, end_date

def run_full_backtest():
    all_trades = []
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        t_list, s_date, e_date = backtest_single_symbol(sym, cfg)
        if s_date and (earliest_start is None or s_date < earliest_start):
            earliest_start = s_date
        if e_date and (latest_end is None or e_date > latest_end):
            latest_end = e_date
        all_trades.extend(t_list)

    if not all_trades:
        return

    df_res = pd.DataFrame(all_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
    total_pnl = df_res['pnl'].sum()
    final_balance = START_BALANCE + total_pnl
    roi_pct = (total_pnl / START_BALANCE) * 100

    symbol_lines = []
    for sym in SYMBOLS.keys():
        sub = df_res[df_res['symbol'] == sym]
        c = len(sub)
        w = len(sub[sub['pnl'] > 0])
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(3)}次 | 勝率: {wr:5.1f}%")

    report_text = (
        "```text\n"
        "判定邏輯: 1hr K線 | EMA50/200趨勢 + Fib 0.618回撤 + RSI動能\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${START_BALANCE:.1f} USDT\n"
        f"最終結餘: ${final_balance:.2f} USDT ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.1f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print(report_text)
    send_discord_safe(report_text)

if __name__ == '__main__':
    run_full_backtest()
