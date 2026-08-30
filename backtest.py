"""
Crypto & Gold 1-Year Optimized Backtest Engine
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

# 專注於加密貨幣與黃金（共 6 檔標的），XAU 與 BTC 同步採用 btc_opt 獲取最佳化勝率
SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'mode': 'btc_opt'},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_fib'},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_fib'},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '15m', 'mode': 'btc_opt'}      # 黃金採用 btc_opt 模型防雜訊
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
            for p in [content[i:i+1800] for i in range(0, len(content), 1800)]:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": p}, timeout=8)
                time.sleep(0.5)
    except Exception:
        pass

def fetch_historical_data(cfg):
    try:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (365 * 24 * 60 * 60 * 1000)  # 完整 1 年歷史數據
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
            df['time'] = pd.to_datetime(df['t'], unit='ms')
            return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
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
    return df

def run_backtest():
    dfs, events = {}, []
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        df = fetch_historical_data(cfg)
        if df is not None and len(df) > 30:
            df = prepare_indicators(df)
            dfs[sym] = df
            s_date = pd.to_datetime(df.iloc[25]['time']).strftime("%Y-%m-%d")
            e_date = pd.to_datetime(df.iloc[-1]['time']).strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start: earliest_start = s_date
            if latest_end is None or e_date > latest_end: latest_end = e_date
            for idx in range(25, len(df)):
                events.append((df.iloc[idx]['time'], sym, idx))

    if not events: return
    events.sort(key=lambda x: x[0])
    current_wallet = float(INITIAL_WALLET)
    positions = {}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    for event_time, sym, idx in events:
        df = dfs[sym]
        bar = df.iloc[idx]
        prev_bar = df.iloc[idx - 1]
        cfg = SYMBOLS[sym]
        mode = cfg['mode']

        if sym in positions:
            pos = positions[sym]
            side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit']

            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry); current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0: symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL', 'time': event_time})
                    del positions[sym]; continue
                if not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry); current_wallet += pnl_tp1; pos['sl'] = tp1
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['wins'] += 1; symbol_stats[sym]['pnl'] += pnl_tp1
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp1, 'type': 'TP1', 'time': event_time})
                if pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry); current_wallet += pnl_tp2
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['wins'] += 1; symbol_stats[sym]['pnl'] += pnl_tp2
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp2, 'type': 'TP2', 'time': event_time})
                    del positions[sym]; continue

            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl); current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0: symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL', 'time': event_time})
                    del positions[sym]; continue
                if not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1); current_wallet += pnl_tp1; pos['sl'] = tp1
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['wins'] += 1; symbol_stats[sym]['pnl'] += pnl_tp1
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp1, 'type': 'TP1', 'time': event_time})
                if pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2); current_wallet += pnl_tp2
                    symbol_stats[sym]['trades'] += 1; symbol_stats[sym]['wins'] += 1; symbol_stats[sym]['pnl'] += pnl_tp2
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp2, 'type': 'TP2', 'time': event_time})
                    del positions[sym]; continue

        if sym not in positions and current_wallet > 5.0:
            sig_side = None; entry, sl, tp1, tp2 = 0, 0, 0, 0

            if mode == 'btc_opt':
                sub = df.iloc[max(0, idx-25):idx+1]
                h, l = sub['h'].max(), sub['l'].min(); wave = h - l
                if wave > 0 and (wave / l) >= 0.008:
                    fib_0618_l = h - (wave * 0.618); fib_0618_s = l + (wave * 0.618)
                    rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
                    rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])
                    cond_long = (bar['c'] >= bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull
                    cond_short = (bar['c'] <= bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h) and rsi_bear

                    if cond_long:
                        sig_side = 'LONG'; entry = bar['c']
                        sl = min(l, entry - (bar['atr'] * 1.5))
                        r = abs(entry - sl); tp1 = entry + (r * 1.2); tp2 = entry + (r * 2.5)
                    elif cond_short:
                        sig_side = 'SHORT'; entry = bar['c']
                        sl = max(h, entry + (bar['atr'] * 1.5))
                        r = abs(sl - entry); tp1 = entry - (r * 1.2); tp2 = entry - (r * 2.5)
            else:
                sub = df.iloc[max(0, idx-25):idx+1]
                h, l = sub['h'].max(), sub['l'].min(); wave = h - l
                if wave > 0 and (wave / l) >= 0.005:
                    fib_0618_l = h - (wave * 0.618); fib_0618_s = l + (wave * 0.618)
                    rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
                    rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])
                    cond_long = (bar['c'] >= bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull
                    cond_short = (bar['c'] <= bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h) and rsi_bear

                    if cond_long:
                        sig_side = 'LONG'; entry = bar['c']
                        sl = min(l, entry - (bar['atr'] * 1.5))
                        tp1 = h if h > entry else entry + abs(entry - sl)
                        tp2 = h + (wave * 0.272)
                        if tp2 <= tp1: tp2 = tp1 + abs(entry - sl)
                    elif cond_short:
                        sig_side = 'SHORT'; entry = bar['c']
                        sl = max(h, entry + (bar['atr'] * 1.5))
                        tp1 = l if l < entry else entry - abs(sl - entry)
                        tp2 = l - (wave * 0.272)
                        if tp2 >= tp1: tp2 = tp1 - abs(sl - entry)

            if sig_side:
                price_diff = abs(entry - sl)
                if price_diff > 0:
                    qty = (current_wallet * RISK_PCT) / price_diff
                    positions[sym] = {'side': sig_side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}

    if not completed_trades: return
    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, r in symbol_stats.items():
        c, w = r['trades'], r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {r['pnl']:+12.6f}")

    report_text = (
        "```text\n"
        "判定邏輯: 加密貨幣與黃金專屬最佳化版 + 複利 (1年期回測)\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 6)} USDT ({roi_pct:+.4f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )
    send_discord_safe(report_text)

if __name__ == '__main__':
    run_backtest()
