import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))

# 回測標的清單（與實盤配置 100% 一致）
SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0},
    'CLU':   {'t': 'stock',   's': 'CL=F',     'lev': 100.0},
    'TSM':   {'t': 'stock',   's': 'TSM',      'lev': 20.0},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'lev': 20.0},
    'AMD':   {'t': 'stock',   's': 'AMD',      'lev': 20.0},
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'lev': 20.0},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'lev': 20.0},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'lev': 20.0},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'lev': 20.0},
    'META':  {'t': 'stock',   's': 'META',     'lev': 20.0},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'lev': 20.0},
    'MU':    {'t': 'stock',   's': 'MU',       'lev': 20.0},
    'GLW':   {'t': 'stock',   's': 'GLW',      'lev': 20.0},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'lev': 20.0},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'lev': 20.0}
}

START_BALANCE = 100.0  # 初始本金 (USDT)
RISK_PCT = 0.01        # 單筆風控 1%

def fetch_historical_data(cfg):
    """取得過去 30 天 15m K 線數據"""
    try:
        if cfg['t'] == 'binance':
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&limit=1000"
            res = requests.get(url, timeout=10).json()
            if isinstance(res, list) and len(res) > 200:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="1mo", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) > 100:
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
    if df is None or len(df) < 100:
        return []

    # 計算技術指標
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

    trades = []
    in_position = False
    entry_price, sl_price, tp1_price, tp2_price = 0, 0, 0, 0
    tp1_hit = False
    qty = 0
    entry_time = None

    for i in range(50, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        # 1. 持倉狀態管理 (檢查 SL 與 分批 TP)
        if in_position:
            # 觸發止損
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

            # 觸發 TP1 (平倉 50%)
            if not tp1_hit and bar['h'] >= tp1_price:
                tp1_hit = True
                gain_per_unit = tp1_price - entry_price
                trades.append({
                    'symbol': sym, 'entry_time': entry_time, 'exit_time': bar['time'],
                    'entry': entry_price, 'exit': tp1_price, 'pnl': (qty * 0.5) * gain_per_unit, 'type': 'TP1'
                })

            # 觸發 TP2 (平倉剩餘 50%)
            if tp1_hit and bar['h'] >= tp2_price:
                gain_per_unit = tp2_price - entry_price
                trades.append({
                    'symbol': sym, 'entry_time': entry_time, 'exit_time': bar['time'],
                    'entry': entry_price, 'exit': tp2_price, 'pnl': (qty * 0.5) * gain_per_unit, 'type': 'TP2'
                })
                in_position = False
                continue

        # 2. 開倉信號掃描 (無持倉時)
        if not in_position:
            sub = df.iloc[max(0, i-25):i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            if wave <= 0 or (wave / l) < 0.005:
                continue

            fib_0618_l = h - (wave * 0.618)
            rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull

            if cond_long:
                entry_price = bar['c']
                sl_price = min(l, entry_price - (bar['atr'] * 1.5))
                tp1_price = h if h > entry_price else entry_price + abs(entry_price - sl_price)
                tp2_price = h + (wave * 0.272)
                if tp2_price <= tp1_price:
                    tp2_price = tp1_price + abs(entry_price - sl_price)

                price_diff = abs(entry_price - sl_price)
                if price_diff > 0:
                    qty = (START_BALANCE * RISK_PCT) / price_diff  # 1% 動態風控倉位
                    in_position = True
                    tp1_hit = False
                    entry_time = bar['time']

    return trades

def run_full_backtest():
    print("==================================================")
    print(">>> 啟動 1 個月歷史回測 (15m Timeframe / 20 檔標的)")
    print(f">>> 初始本金: ${START_BALANCE:.2f} USDT | 單筆風控: {RISK_PCT*100:.1f}%")
    print("==================================================\n")

    all_trades = []
    for sym, cfg in SYMBOLS.items():
        print(f"正在回測: {sym.ljust(5)} ...", end=" ")
        t_list = backtest_single_symbol(sym, cfg)
        print(f"完成 (產生 {len(t_list)} 筆成交)")
        all_trades.extend(t_list)

    if not all_trades:
        print("\n回測期間內無觸發交易。")
        return

    df_res = pd.DataFrame(all_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0])
    loss_trades = len(df_res[df_res['pnl'] < 0])
    win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
    total_pnl = df_res['pnl'].sum()
    final_balance = START_BALANCE + total_pnl
    roi = (total_pnl / START_BALANCE) * 100

    print("\n================== [回測綜合統計] ==================")
    print(f"總平倉次數 : {total_trades} 次")
    print(f"勝率 (Win Rate)  : {win_rate:.2f}% (勝: {win_trades} / 負: {loss_trades})")
    print(f"總淨盈虧 (PnL)   : {total_pnl:+.2f} USDT")
    print(f"最終資金餘額     : ${final_balance:.2f} USDT (報酬率: {roi:+.2f}%)")
    print("====================================================\n")

    print("各標的詳細表現:")
    summary_by_sym = df_res.groupby('symbol').agg(
        trades=('pnl', 'count'),
        wins=('pnl', lambda x: (x > 0).sum()),
        pnl=('pnl', 'sum')
    )
    summary_by_sym['win_rate'] = (summary_by_sym['wins'] / summary_by_sym['trades']) * 100
    print(summary_by_sym[['trades', 'wins', 'win_rate', 'pnl']].to_string())

if __name__ == '__main__':
    run_full_backtest()
