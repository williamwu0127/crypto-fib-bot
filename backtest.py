import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_fib'},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '15m', 'mode': 'crypto_fib'},
    'CLU':   {'t': 'stock',   's': 'CL=F',     'interval': '4h',  'mode': 'stock_breakout'},
    'TSM':   {'t': 'stock',   's': 'TSM',      'interval': '4h',  'mode': 'stock_breakout'},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'interval': '4h',  'mode': 'stock_breakout'},
    'AMD':   {'t': 'stock',   's': 'AMD',      'interval': '4h',  'mode': 'stock_breakout'},
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'interval': '4h',  'mode': 'stock_breakout'},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'interval': '4h',  'mode': 'stock_breakout'},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'interval': '4h',  'mode': 'stock_breakout'},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'interval': '4h',  'mode': 'stock_breakout'},
    'META':  {'t': 'stock',   's': 'META',     'interval': '4h',  'mode': 'stock_breakout'},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'interval': '4h',  'mode': 'stock_breakout'},
    'MU':    {'t': 'stock',   's': 'MU',       'interval': '4h',  'mode': 'stock_breakout'},
    'GLW':   {'t': 'stock',   's': 'GLW',      'interval': '4h',  'mode': 'stock_breakout'},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'interval': '4h',  'mode': 'stock_breakout'},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'interval': '4h',  'mode': 'stock_breakout'}
}

INITIAL_WALLET = 100.0
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

def fetch_1year_historical_data(cfg):
    try:
        if cfg['t'] == 'binance':
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (365 * 24 * 60 * 60 * 1000)
            all_klines = []
            curr_start = start_ms
            
            while curr_start < now_ms:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr_start}&limit=1000"
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
                df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="1y", interval="1h", progress=False)
            if df is not None and not df.empty and len(df) > 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                t_idx = pd.to_datetime(df.index)
                if t_idx.tz is not None:
                    t_idx = t_idx.tz_localize(None)
                df['time'] = t_idx
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    res_df['time'] = df['time'].values
                    res_df = res_df.set_index('time')
                    res_df_4h = res_df.resample('4h').agg({
                        'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
                    }).dropna().reset_index()
                    return res_df_4h
    except Exception:
        pass
    return None

def prepare_indicators(df):
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()
    df['vol_ma20'] = df['v'].rolling(20).mean().fillna(df['v'])
    
    df['bb_mid'] = df['c'].rolling(20).mean()
    df['bb_std'] = df['c'].rolling(20).std().fillna(0)
    df['bb_upper'] = df['bb_mid'] + (2 * df['bb_std'])
    df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
    return df

def run_backtest():
    print("==================================================")
    print(">>> 啟動【美股4h突破 + BTC波幅1%斐波 + 加密15m斐波 + 全域複利】1 年期回測")
    print(f">>> 初始本金: ${INITIAL_WALLET:.2f} USDT | 風控: 1.0%")
    print("==================================================\n")

    dfs = {}
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        print(f"拉取數據: {sym.ljust(5)} ({cfg['interval']}) ...", end=" ")
        df = fetch_1year_historical_data(cfg)
        if df is not None and len(df) > 30:
            df = prepare_indicators(df)
            dfs[sym] = df
            s_date = pd.to_datetime(df.iloc[25]['time']).strftime("%Y-%m-%d")
            e_date = pd.to_datetime(df.iloc[-1]['time']).strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start:
                earliest_start = s_date
            if latest_end is None or e_date > latest_end:
                latest_end = e_date
            print(f"完成 ({len(df)} 根 K 線)")
        else:
            print("資料不足略過")

    if not dfs:
        print("無可用數據。")
        return

    all_timestamps = sorted(list(set([t for df in dfs.values() for t in df['time']])))
    current_wallet = INITIAL_WALLET
    positions = {}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    print(f"\n>>> 共有 {len(all_timestamps)} 個時間切片，開始逐時間撮合與複利滾動...")

    for curr_time in all_timestamps:
        for sym, df in dfs.items():
            match_row = df[df['time'] == curr_time]
            if match_row.empty:
                continue
            idx = match_row.index[0]
            if idx < 30:
                continue
            
            bar = match_row.iloc[0]
            prev_bar = df.iloc[idx - 1]
            mode = SYMBOLS[sym]['mode']

            # 1. 持倉處理
            if sym in positions:
                pos = positions[sym]
                side = pos['side']
                entry = pos['entry']
                sl = pos['sl']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                qty = pos['qty']
                tp1_hit = pos['tp1_hit']

                if side == 'LONG':
                    if bar['l'] <= sl:
                        rem_qty = qty * 0.5 if tp1_hit else qty
                        pnl = rem_qty * (sl - entry)
                        current_wallet += pnl
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['pnl'] += pnl
                        if pnl > 0:
                            symbol_stats[sym]['wins'] += 1
                        completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL_OUT', 'time': curr_time})
                        del positions[sym]
                        continue
                    if not tp1_hit and bar['h'] >= tp1:
                        pos['tp1_hit'] = True
                        pnl_tp1 = (qty * 0.5) * (tp1 - entry)
                        current_wallet += pnl_tp1
                        pos['sl'] = tp1
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp1
                        completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'TP1', 'time': curr_time})
                    if pos['tp1_hit'] and bar['h'] >= tp2:
                        pnl_tp2 = (qty * 0.5) * (tp2 - entry)
                        current_wallet += pnl_tp2
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp2, 'type': 'TP2', 'time': curr_time})
                        del positions[sym]
                        continue

                elif side == 'SHORT':
                    if bar['h'] >= sl:
                        rem_qty = qty * 0.5 if tp1_hit else qty
                        pnl = rem_qty * (entry - sl)
                        current_wallet += pnl
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['pnl'] += pnl
                        if pnl > 0:
                            symbol_stats[sym]['wins'] += 1
                        completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL_OUT', 'time': curr_time})
                        del positions[sym]
                        continue
                    if not tp1_hit and bar['l'] <= tp1:
                        pos['tp1_hit'] = True
                        pnl_tp1 = (qty * 0.5) * (entry - tp1)
                        current_wallet += pnl_tp1
                        pos['sl'] = tp1
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp1
                        completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp1, 'type': 'TP1', 'time': curr_time})
                    if pos['tp1_hit'] and bar['l'] <= tp2:
                        pnl_tp2 = (qty * 0.5) * (entry - tp2)
                        current_wallet += pnl_tp2
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp2, 'type': 'TP2', 'time': curr_time})
                        del positions[sym]
                        continue

            # 2. 開倉信號判定 (全域複利)
            if sym not in positions and current_wallet > 5.0:
                sig_side = None
                entry, sl, tp1, tp2 = 0, 0, 0, 0

                # 美股 4h 突破
                if mode == 'stock_breakout':
                    trend_bull = (bar['ema20'] > bar['ema50']) and (bar['c'] > bar['ema200'])
                    trend_bear = (bar['ema20'] < bar['ema50']) and (bar['c'] < bar['ema200'])
                    breakout_up = (bar['c'] > bar['bb_upper']) and (bar['v'] > bar['vol_ma20'])
                    breakout_down = (bar['c'] < bar['bb_lower']) and (bar['v'] > bar['vol_ma20'])

                    if trend_bull and breakout_up:
                        sig_side = 'LONG'
                        entry = bar['c']
                        sl = entry - (bar['atr'] * 1.5)
                        tp1 = entry + (abs(entry - sl) * 1.5)
                        tp2 = entry + (abs(entry - sl) * 3.0)
                    elif trend_bear and breakout_down:
                        sig_side = 'SHORT'
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        tp1 = entry - (abs(sl - entry) * 1.5)
                        tp2 = entry - (abs(sl - entry) * 3.0)

                # 加密貨幣 & 黃金 15m 斐波那契回撤 (BTC 需波幅 >= 1%)
                else:
                    sub = df.iloc[max(0, idx-25):idx+1]
                    h, l = sub['h'].max(), sub['l'].min()
                    wave = h - l
                    min_wave_ratio = 0.01 if sym == 'BTC' else 0.005
                    
                    if wave > 0 and (wave / l) >= min_wave_ratio:
                        fib_0618_l = h - (wave * 0.618)
                        fib_0618_s = l + (wave * 0.618)
                        rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
                        rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])

                        cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull
                        cond_short = (bar['c'] <= bar['ema50']) and (bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h) and rsi_bear

                        if cond_long:
                            sig_side = 'LONG'
                            entry = bar['c']
                            sl = min(l, entry - (bar['atr'] * 1.5))
                            tp1 = h if h > entry else entry + abs(entry - sl)
                            tp2 = h + (wave * 0.272)
                            if tp2 <= tp1:
                                tp2 = tp1 + abs(entry - sl)
                        elif cond_short:
                            sig_side = 'SHORT'
                            entry = bar['c']
                            sl = max(h, entry + (bar['atr'] * 1.5))
                            tp1 = l if l < entry else entry - abs(sl - entry)
                            tp2 = l - (wave * 0.272)
                            if tp2 >= tp1:
                                tp2 = tp1 - abs(sl - entry)

                # 建立持倉
                if sig_side:
                    price_diff = abs(entry - sl)
                    if price_diff > 0:
                        dynamic_risk = current_wallet * RISK_PCT
                        qty = dynamic_risk / price_diff
                        positions[sym] = {
                            'side': sig_side, 'entry': entry, 'sl': sl,
                            'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty
                        }

    if not completed_trades:
        print("回測期間內無交易產生。")
        return

    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, r in symbol_stats.items():
        c = r['trades']
        w = r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.1f}% | 收益貢獻: {r['pnl']:+9.2f}")

    report_text = (
        "```text\n"
        "判定邏輯: 美股4h突破 + BTC(1%波幅)斐波 + 加密15m斐波 + 全域複利 (1年期回測)\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${INITIAL_WALLET:.1f} USDT\n"
        f"最終結餘: ${current_wallet:.2f} USDT ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.1f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print("\n" + report_text)
    print(">>> 正在發送至 Discord...")
    send_discord_safe(report_text)
    print(">>> 完成推播！")

if __name__ == '__main__':
    run_backtest()
