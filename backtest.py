import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

# Discord Webhook
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

INITIAL_WALLET = 100.0
RISK_PCT = 0.01

# 交易摩擦成本 (Taker Fee + 開盤滑點)
COST_CONFIG = {
    'binance': {'fee': 0.0005, 'slippage': 0.0003}, # 0.05% 費率 + 0.03% 滑點
    'stock':   {'fee': 0.0002, 'slippage': 0.0005}  # 0.02% 交易費 + 0.05% 滑點
}

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.008},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.005},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.005},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.005},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.008},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.005},
    'TSM':   {'t': 'stock',   's': 'TSM',      'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'AMD':   {'t': 'stock',   's': 'AMD',      'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'META':  {'t': 'stock',   's': 'META',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'MU':    {'t': 'stock',   's': 'MU',       'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'GLW':   {'t': 'stock',   's': 'GLW',      'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'interval': '1h',  'mode': 'stock_pullback', 'min_wave': 0.015}
}

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
                time.sleep(0.03)
            
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
                    return res_df.reset_index(drop=True)
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
    df['vol_ma20'] = df['v'].rolling(20).mean().fillna(0)
    return df

def run_backtest():
    print("================================================================================")
    print(">>> 啟動【嚴格 1:1 對齊回測 (N+1開盤進場 + 獨立風控 + 50/50 雙軌)】1 年期回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USDT | 單筆風控: 1.0%")
    print("================================================================================\n")

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
    current_wallet = float(INITIAL_WALLET)
    peak_wallet = float(INITIAL_WALLET)
    max_drawdown_usdt = 0.0
    max_drawdown_pct = 0.0
    
    positions = {}
    pending_signals = {}
    completed_trades = []
    
    symbol_stats = {
        sym: {
            'trades': 0, 'wins': 0, 'pnl': 0.0, 'total_r': 0.0,
            'long_trades': 0, 'long_wins': 0, 'long_pnl': 0.0,
            'short_trades': 0, 'short_wins': 0, 'short_pnl': 0.0
        } for sym in SYMBOLS.keys()
    }

    print(f"\n>>> 共有 {len(all_timestamps)} 個時間節點，開始撮合...\n")

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
            cfg = SYMBOLS[sym]
            mode = cfg['mode']
            cost_cfg = COST_CONFIG[cfg['t']]
            fee_rate = cost_cfg['fee']
            slip_rate = cost_cfg['slippage']

            # 1. 處理待進場掛單 (第 N+1 根 K 棒 Open 價格進場)
            if sym in pending_signals and sym not in positions:
                sig = pending_signals.pop(sym)
                side = sig['side']
                target_sl = sig['sl']
                target_tp1 = sig['tp1']
                target_tp2 = sig['tp2']
                risk_usdt = sig['risk_usdt']

                actual_entry = bar['o'] * (1 + slip_rate) if side == 'LONG' else bar['o'] * (1 - slip_rate)
                price_diff = abs(actual_entry - target_sl)
                
                if price_diff > 0:
                    qty = risk_usdt / price_diff
                    entry_fee = qty * actual_entry * fee_rate
                    current_wallet -= entry_fee

                    positions[sym] = {
                        'side': side,
                        'entry': actual_entry,
                        'sl': target_sl,
                        'tp1': target_tp1,
                        'tp2': target_tp2,
                        'qty': qty,
                        'initial_qty': qty,
                        'risk_usdt': risk_usdt,
                        'tp1_hit': False,
                        'accum_pnl': -entry_fee,
                        'entry_time': curr_time
                    }

            # 2. 持倉撮合 (50% TP1 鎖利 + 50% TP2 / SL 移至 TP1)
            if sym in positions:
                pos = positions[sym]
                side = pos['side']
                entry = pos['entry']
                sl = pos['sl']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                qty = pos['qty']
                tp1_hit = pos['tp1_hit']
                is_long = (side == 'LONG')

                hit_sl = (bar['l'] <= sl) if is_long else (bar['h'] >= sl)
                hit_tp1 = (not tp1_hit) and ((bar['h'] >= tp1) if is_long else (bar['l'] <= tp1))
                hit_tp2 = tp1_hit and ((bar['h'] >= tp2) if is_long else (bar['l'] <= tp2))

                # 保守原則：同 K 同時碰到 SL 與 TP 時，強制判 SL 優先
                if hit_sl and (hit_tp1 or hit_tp2):
                    hit_tp1 = False
                    hit_tp2 = False

                # 狀況 A: 觸發止損 (SL)
                if hit_sl:
                    exit_price = sl * (1 - slip_rate) if is_long else sl * (1 + slip_rate)
                    rem_qty = qty
                    exit_fee = rem_qty * exit_price * fee_rate
                    trade_pnl = (rem_qty * (exit_price - entry) if is_long else rem_qty * (entry - exit_price)) - exit_fee
                    
                    pos['accum_pnl'] += trade_pnl
                    current_wallet += (rem_qty * (exit_price - entry) if is_long else rem_qty * (entry - exit_price)) - exit_fee
                    
                    realized_r = pos['accum_pnl'] / pos['risk_usdt'] if pos['risk_usdt'] > 0 else -1.0
                    is_win = pos['accum_pnl'] > 0
                    
                    st = symbol_stats[sym]
                    st['trades'] += 1
                    st['pnl'] += pos['accum_pnl']
                    st['total_r'] += realized_r
                    if is_win: st['wins'] += 1
                    
                    if is_long:
                        st['long_trades'] += 1
                        st['long_pnl'] += pos['accum_pnl']
                        if is_win: st['long_wins'] += 1
                    else:
                        st['short_trades'] += 1
                        st['short_pnl'] += pos['accum_pnl']
                        if is_win: st['short_wins'] += 1

                    completed_trades.append({
                        'symbol': sym, 'side': side, 'entry_time': pos['entry_time'], 'exit_time': curr_time,
                        'pnl': pos['accum_pnl'], 'r': realized_r, 'win': is_win
                    })
                    del positions[sym]
                    continue

                # 狀況 B: 觸發 TP1 (平 50% 鎖利，SL 移動至 TP1 價位)
                if hit_tp1:
                    pos['tp1_hit'] = True
                    close_qty = pos['initial_qty'] * 0.50
                    pos['qty'] -= close_qty
                    
                    exit_price = tp1 * (1 - slip_rate) if is_long else tp1 * (1 + slip_rate)
                    exit_fee = close_qty * exit_price * fee_rate
                    half_pnl = (close_qty * (exit_price - entry) if is_long else close_qty * (entry - exit_price)) - exit_fee
                    
                    pos['accum_pnl'] += half_pnl
                    current_wallet += (close_qty * (exit_price - entry) if is_long else close_qty * (entry - exit_price)) - exit_fee
                    pos['sl'] = tp1 # 移動 SL 至 TP1

                # 狀況 C: 觸發 TP2 (平剩餘 50%，全額獲利出場)
                if hit_tp2:
                    rem_qty = pos['qty']
                    exit_price = tp2 * (1 - slip_rate) if is_long else tp2 * (1 + slip_rate)
                    exit_fee = rem_qty * exit_price * fee_rate
                    final_pnl = (rem_qty * (exit_price - entry) if is_long else rem_qty * (entry - exit_price)) - exit_fee
                    
                    pos['accum_pnl'] += final_pnl
                    current_wallet += (rem_qty * (exit_price - entry) if is_long else rem_qty * (entry - exit_price)) - exit_fee
                    
                    realized_r = pos['accum_pnl'] / pos['risk_usdt'] if pos['risk_usdt'] > 0 else 1.0
                    is_win = pos['accum_pnl'] > 0

                    st = symbol_stats[sym]
                    st['trades'] += 1
                    st['pnl'] += pos['accum_pnl']
                    st['total_r'] += realized_r
                    if is_win: st['wins'] += 1

                    if is_long:
                        st['long_trades'] += 1
                        st['long_pnl'] += pos['accum_pnl']
                        if is_win: st['long_wins'] += 1
                    else:
                        st['short_trades'] += 1
                        st['short_pnl'] += pos['accum_pnl']
                        if is_win: st['short_wins'] += 1

                    completed_trades.append({
                        'symbol': sym, 'side': side, 'entry_time': pos['entry_time'], 'exit_time': curr_time,
                        'pnl': pos['accum_pnl'], 'r': realized_r, 'win': is_win
                    })
                    del positions[sym]
                    continue

            # 資金曲線與 MDD 追蹤
            if current_wallet > peak_wallet:
                peak_wallet = current_wallet
            dd_usdt = peak_wallet - current_wallet
            dd_pct = (dd_usdt / peak_wallet) * 100 if peak_wallet > 0 else 0.0
            if dd_usdt > max_drawdown_usdt: max_drawdown_usdt = dd_usdt
            if dd_pct > max_drawdown_pct: max_drawdown_pct = dd_pct

            # 3. 產生進場信號 (在已封閉的 K 棒判定，存入 pending_signals 等待下一根 Open 進場)
            if sym not in positions and sym not in pending_signals and current_wallet > 5.0:
                sig_side = None
                entry_ref = bar['c']
                sl_ref, tp1_ref, tp2_ref = 0, 0, 0

                # 美股 1h 均線回踩 (1.5R / 3.0R)
                if mode == 'stock_pullback':
                    trend_bull = (bar['ema20'] > bar['ema50']) and (bar['c'] > bar['ema200'])
                    trend_bear = (bar['ema20'] < bar['ema50']) and (bar['c'] < bar['ema200'])
                    vol_ok = bar['v'] >= (bar['vol_ma20'] * 0.9)
                    
                    pullback_long = (bar['l'] <= bar['ema20']) and (bar['l'] >= bar['ema50'] * 0.992) and (bar['c'] > bar['o']) and (bar['rsi'] >= 45 and bar['rsi'] <= 60) and vol_ok
                    pullback_short = (bar['h'] >= bar['ema20']) and (bar['h'] <= bar['ema50'] * 1.008) and (bar['c'] < bar['o']) and (bar['rsi'] <= 55 and bar['rsi'] >= 40) and vol_ok

                    if trend_bull and pullback_long:
                        sig_side = 'LONG'
                        sl_ref = min(bar['l'], bar['ema50'] - (bar['atr'] * 1.2))
                        r = abs(entry_ref - sl_ref)
                        tp1_ref = entry_ref + (r * 1.5)
                        tp2_ref = entry_ref + (r * 3.0)
                    elif trend_bear and pullback_short:
                        sig_side = 'SHORT'
                        sl_ref = max(bar['h'], bar['ema50'] + (bar['atr'] * 1.2))
                        r = abs(sl_ref - entry_ref)
                        tp1_ref = entry_ref - (r * 1.5)
                        tp2_ref = entry_ref - (r * 3.0)

                # 加密貨幣 (Fib 鎖定過去 25 根已完成 K 棒，消除自我參照)
                else:
                    sub = df.iloc[max(0, idx-26):idx]
                    h, l = sub['h'].max(), sub['l'].min()
                    wave = h - l
                    min_wave_req = cfg['min_wave']
                    
                    if wave > 0 and (wave / l) >= min_wave_req:
                        fib_0618_l = h - (wave * 0.618)
                        fib_0618_s = l + (wave * 0.618)
                        rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
                        rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])

                        cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull
                        cond_short = (bar['c'] <= bar['ema50']) and (bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h) and rsi_bear

                        if cond_long:
                            sig_side = 'LONG'
                            sl_ref = min(l, entry_ref - (bar['atr'] * 1.5))
                            r = abs(entry_ref - sl_ref)
                            tp1_ref = max(h, entry_ref + r * 1.2)
                            tp2_ref = max(h + (wave * 0.272), tp1_ref + r)
                        elif cond_short:
                            sig_side = 'SHORT'
                            sl_ref = max(h, entry_ref + (bar['atr'] * 1.5))
                            r = abs(sl_ref - entry_ref)
                            tp1_ref = min(l, entry_ref - r * 1.2)
                            tp2_ref = min(l - (wave * 0.272), tp1_ref - r)

                if sig_side:
                    pending_signals[sym] = {
                        'side': sig_side, 'sl': sl_ref, 'tp1': tp1_ref, 'tp2': tp2_ref,
                        'risk_usdt': current_wallet * RISK_PCT
                    }

    # 4. 生成統計
    if not completed_trades:
        print("回測期間內無交易產生。")
        return

    df_trades = pd.DataFrame(completed_trades)
    total_trades = len(df_trades)
    win_trades = len(df_trades[df_trades['win']])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, st in symbol_stats.items():
        c = st['trades']
        if c == 0: continue
        w = st['wins']
        wr = (w / c * 100)
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {st['pnl']:+12.6f} (R: {st['total_r']:+6.1f}R)")

    report_text = (
        "```text\n"
        "判定邏輯: 嚴格1:1對齊 (N+1開盤進場 + 摩擦成本 + 50/50鎖利雙軌) 全域高精度複利\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 6)} USDT ({roi_pct:+.4f}%)\n"
        f"最大回撤: -${max_drawdown_usdt:.2f} USDT (-{max_drawdown_pct:.2f}%)\n"
        f"總交易次數: {total_trades} 次 (獨立持倉週期) | 綜合勝率: {overall_win_rate:.2f}%\n"
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
