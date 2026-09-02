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
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_donchian'}, # 黃金維持幣安 4H 唐奇安
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'interval': '1h',  'mode': 'gold_donchian'}, # 美股統一改由 stock (yfinance) 抓取並套用黃金唐奇安策略
    'TSM':   {'t': 'stock',   's': 'TSM',      'interval': '1h',  'mode': 'gold_donchian'},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'interval': '1h',  'mode': 'gold_donchian'},
    'AMD':   {'t': 'stock',   's': 'AMD',      'interval': '1h',  'mode': 'gold_donchian'},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'interval': '1h',  'mode': 'gold_donchian'},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'interval': '1h',  'mode': 'gold_donchian'},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'interval': '1h',  'mode': 'gold_donchian'},
    'META':  {'t': 'stock',   's': 'META',     'interval': '1h',  'mode': 'gold_donchian'},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'interval': '1h',  'mode': 'gold_donchian'},
    'MU':    {'t': 'stock',   's': 'MU',       'interval': '1h',  'mode': 'gold_donchian'},
    'GLW':   {'t': 'stock',   's': 'GLW',      'interval': '1h',  'mode': 'gold_donchian'},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'interval': '1h',  'mode': 'gold_donchian'},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'interval': '1h',  'mode': 'gold_donchian'}
}

INITIAL_WALLET = 100.0
RISK_PCT = 0.01

def format_full_num(val, max_dec=8):
    try:
        f = float(val)
        s = f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
        return s if s else "0"
    except Exception:
        return str(val)

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

def fetch_historical_data(cfg, days=365):
    try:
        if cfg['t'] == 'binance':
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
            all_klines = []
            curr_start = start_ms
            
            while curr_start < now_ms:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr_start}&limit=1000"
                res = requests.get(url, timeout=10).json()
                if not isinstance(res, list) or len(res) == 0:
                    break
                all_klines.extend(res)
                if len(res) < 1000:
                    break
                curr_start = int(res[-1][0]) + 1
                time.sleep(0.04)
            
            if len(all_klines) > 10:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(all_klines, columns=cols)
                df = df.drop_duplicates(subset=['t']).sort_values('t').reset_index(drop=True)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            period_str = "1mo" if days <= 30 else "1y"
            df = yf.download(cfg['s'], period=period_str, interval="1h", progress=False)
            if df is not None and not df.empty and len(df) > 10:
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
                    return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def prepare_indicators(df, mode):
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
    
    if mode == 'gold_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
    return df

def execute_backtest_run(days_target, label_str):
    print("==================================================")
    print(f">>> 啟動【混合穩定數據源】{label_str} 歷史回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USDT | 風控: 1.0%")
    print("==================================================\n")

    dfs = {}
    fetch_status = []
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        print(f"拉取數據 [{label_str}]: {sym.ljust(5)} ({cfg['interval']}) ...", end=" ")
        df = fetch_historical_data(cfg, days=days_target)
        if df is not None and len(df) > 10:
            df = prepare_indicators(df, cfg['mode'])
            dfs[sym] = df
            s_date = pd.to_datetime(df.iloc[min(20, len(df)-1)]['time']).strftime("%Y-%m-%d")
            e_date = pd.to_datetime(df.iloc[-1]['time']).strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start:
                earliest_start = s_date
            if latest_end is None or e_date > latest_end:
                latest_end = e_date
            print(f"成功 ({len(df)} 根)")
            fetch_status.append(f"{sym}: 🟢")
        else:
            print("失敗 (資料不足)")
            fetch_status.append(f"{sym}: 🔴")

    if not dfs:
        print(f"[{label_str}] 無可用數據。")
        return

    all_timestamps = sorted(list(set([t for df in dfs.values() for t in df['time']])))
    current_wallet = float(INITIAL_WALLET)
    positions = {}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    for curr_time in all_timestamps:
        for sym, df in dfs.items():
            match_row = df[df['time'] == curr_time]
            if match_row.empty:
                continue
            idx = match_row.index[0]
            if idx < 20:
                continue
            
            bar = match_row.iloc[0]
            prev_bar = df.iloc[idx - 1]
            cfg = SYMBOLS[sym]
            mode = cfg['mode']

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

                if mode == 'gold_donchian':
                    if side == 'LONG':
                        if bar['l'] <= sl:
                            pnl = qty * (sl - entry)
                            current_wallet += pnl
                            symbol_stats[sym]['trades'] += 1
                            symbol_stats[sym]['pnl'] += pnl
                            if pnl > 0:
                                symbol_stats[sym]['wins'] += 1
                            completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL_OR_BE', 'time': curr_time})
                            del positions[sym]
                            continue
                        if not tp1_hit and bar['h'] >= pos['be_target']:
                            pos['tp1_hit'] = True
                            pos['sl'] = entry
                        if bar['h'] >= tp2:
                            pnl = qty * (tp2 - entry)
                            current_wallet += pnl
                            symbol_stats[sym]['trades'] += 1
                            symbol_stats[sym]['wins'] += 1
                            symbol_stats[sym]['pnl'] += pnl
                            completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'GOLD_TP_5R', 'time': curr_time})
                            del positions[sym]
                            continue
                    else:
                        if bar['h'] >= sl:
                            pnl = qty * (entry - sl)
                            current_wallet += pnl
                            symbol_stats[sym]['trades'] += 1
                            symbol_stats[sym]['pnl'] += pnl
                            if pnl > 0:
                                symbol_stats[sym]['wins'] += 1
                            completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL_OR_BE', 'time': curr_time})
                            del positions[sym]
                            continue
                        if not tp1_hit and bar['l'] <= pos['be_target']:
                            pos['tp1_hit'] = True
                            pos['sl'] = entry
                        if bar['l'] <= tp2:
                            pnl = qty * (entry - tp2)
                            current_wallet += pnl
                            symbol_stats[sym]['trades'] += 1
                            symbol_stats[sym]['wins'] += 1
                            symbol_stats[sym]['pnl'] += pnl
                            completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'GOLD_TP_5R', 'time': curr_time})
                            del positions[sym]
                            continue
                else:
                    if side == 'LONG':
                        if bar['l'] <= sl:
                            rem_qty = qty * 0.5 if tp1_hit else qty
                            pnl = rem_qty * (sl - entry)
                            current_wallet += pnl
                            symbol_stats[sym]['trades'] += 1
                            symbol_stats[sym]['pnl'] += pnl
                            if pnl > 0:
                                symbol_stats[sym]['wins'] += 1
                            completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'TP1_TRAIL_SL' if tp1_hit else 'SL', 'time': curr_time})
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
                            completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp1, 'type': 'TP1', 'time': curr_time})
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
                            completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'TP1_TRAIL_SL' if tp1_hit else 'SL', 'time': curr_time})
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

            # 2. 開倉信號判定
            if sym not in positions and current_wallet > 5.0:
                sig_side = None
                entry, sl, tp1, tp2 = 0, 0, 0, 0
                be_target = 0

                if mode == 'gold_donchian':
                    macro_trend = 1 if bar['c'] > bar['ema200'] else -1
                    if macro_trend == 1 and bar['c'] > bar['dc_high']:
                        sig_side = 'LONG'
                        entry = bar['c']
                        sl = entry - (bar['atr'] * 1.5)
                        risk_dist = entry - sl
                        be_target = entry + (risk_dist * 2.0)
                        tp2 = entry + (risk_dist * 5.0)
                    elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                        sig_side = 'SHORT'
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        risk_dist = sl - entry
                        be_target = entry - (risk_dist * 2.0)
                        tp2 = entry - (risk_dist * 5.0)
                else:
                    sub = df.iloc[max(0, idx-25):idx+1]
                    h, l = sub['h'].max(), sub['l'].min()
                    wave = h - l
                    if wave > 0 and (wave / l) >= 0.005:
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

                if sig_side:
                    price_diff = abs(entry - sl)
                    if price_diff > 0:
                        qty = (current_wallet * RISK_PCT) / price_diff
                        positions[sym] = {
                            'side': sig_side, 'entry': entry, 'sl': sl,
                            'tp1': tp1, 'tp2': tp2, 'be_target': be_target, 'tp1_hit': False, 'qty': qty
                        }

    total_trades = len(completed_trades)
    win_trades = len([t for t in completed_trades if t['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, r in symbol_stats.items():
        c = r['trades']
        w = r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {r['pnl']:+12.6f}")

    status_block = " | ".join(fetch_status)

    report_text = (
        "```text\n"
        f"【抓取狀態 ({label_str})】\n"
        + status_block + "\n"
        "----------------------------------------------------\n"
        f"判定邏輯: XAU/美股唐奇安策略 + {label_str}回測\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 6)} USDT ({roi_pct:+.4f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print("\n" + report_text)
    print(f">>> 正在發送 [{label_str}] 報告至 Discord...")
    send_discord_safe(report_text)
    print(f">>> [{label_str}] 完成推播！\n")

if __name__ == '__main__':
    execute_backtest_run(30, "30d")
    execute_backtest_run(365, "365d")
