import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

INITIAL_WALLET = 100.0
RISK_PCT = 0.01

# 交易成本設定 (Taker Fee + Slippage)
COST_CONFIG = {
    'binance': {'fee': 0.0005, 'slippage': 0.0003}, # 0.05% 費率 + 0.03% 滑點
    'stock':   {'fee': 0.0002, 'slippage': 0.0005}  # 0.02% 交易費 + 0.05% 開盤滑點
}

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_fib',     'min_wave': 0.012},
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
    print(">>> 啟動【嚴格機構級回測引擎 (N+1開盤進場 + 同K保守SL + 交易摩擦成本 + R-Multiple)】")
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
    
    positions = {}        # 當前持倉
    pending_signals = {}  # N 根產生信號 -> 等待 N+1 根 Open 進場
    completed_trades = [] # 真正以 1 Position Cycle 統計的 Trade-level 紀錄
    
    # 分解統計容器
    symbol_stats = {
        sym: {
            'trades': 0, 'wins': 0, 'pnl': 0.0, 'total_r': 0.0,
            'long_trades': 0, 'long_wins': 0, 'long_pnl': 0.0, 'long_r': 0.0,
            'short_trades': 0, 'short_wins': 0, 'short_pnl': 0.0, 'short_r': 0.0,
            'tp1_hits': 0, 'tp2_hits': 0, 'sl_hits': 0
        } for sym in SYMBOLS.keys()
    }

    print(f"\n>>> 共有 {len(all_timestamps)} 個時間節點，開始嚴格撮合...\n")

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

            # =========================================================================
            # 1. 處理待進場掛單 (N+1 根 K 棒以 Open + Slippage 執行進場)
            # =========================================================================
            if sym in pending_signals and sym not in positions:
                sig = pending_signals.pop(sym)
                side = sig['side']
                target_sl = sig['sl']
                target_tp1 = sig['tp1']
                target_tp2 = sig['tp2']
                risk_usdt = sig['risk_usdt']

                # 納入開盤滑點
                actual_entry = bar['o'] * (1 + slip_rate) if side == 'LONG' else bar['o'] * (1 - slip_rate)
                
                # 計算實際風險距離與倉位
                price_diff = abs(actual_entry - target_sl)
                if price_diff > 0:
                    qty = risk_usdt / price_diff
                    # 進場手續費
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
                        'initial_r_dist': price_diff,
                        'tp1_hit': False,
                        'accum_pnl': -entry_fee, # 扣除進場成本
                        'entry_time': curr_time
                    }

            # =========================================================================
            # 2. 持倉撮合與衝突處理 (同 K 棒同時碰 SL/TP 時，強制判為 SL 先到)
            # =========================================================================
            if sym in positions:
                pos = positions[sym]
                side = pos['side']
                entry = pos['entry']
                sl = pos['sl']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                qty = pos['qty']
                tp1_hit = pos['tp1_hit']
                r_dist = pos['initial_r_dist']

                is_long = (side == 'LONG')
                
                # 判定本根 K 棒是否觸發點位
                hit_sl = (bar['l'] <= sl) if is_long else (bar['h'] >= sl)
                hit_tp1 = (not tp1_hit) and ((bar['h'] >= tp1) if is_long else (bar['l'] <= tp1))
                hit_tp2 = tp1_hit and ((bar['h'] >= tp2) if is_long else (bar['l'] <= tp2))

                # 衝突處理：如果同 K 同時碰到 SL 與 TP，保守原則 -> 強制判 SL
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
                    
                    # 結算整筆 Trade
                    realized_r = pos['accum_pnl'] / pos['risk_usdt'] if pos['risk_usdt'] > 0 else -1.0
                    is_win = pos['accum_pnl'] > 0
                    
                    # 統計紀錄
                    st = symbol_stats[sym]
                    st['trades'] += 1
                    st['pnl'] += pos['accum_pnl']
                    st['total_r'] += realized_r
                    if is_win: st['wins'] += 1
                    
                    if is_long:
                        st['long_trades'] += 1
                        st['long_pnl'] += pos['accum_pnl']
                        st['long_r'] += realized_r
                        if is_win: st['long_wins'] += 1
                    else:
                        st['short_trades'] += 1
                        st['short_pnl'] += pos['accum_pnl']
                        st['short_r'] += realized_r
                        if is_win: st['short_wins'] += 1

                    if tp1_hit:
                        # 這是被保本或移動止損打掉
                        pass
                    else:
                        st['sl_hits'] += 1

                    completed_trades.append({
                        'symbol': sym, 'side': side, 'entry_time': pos['entry_time'], 'exit_time': curr_time,
                        'pnl': pos['accum_pnl'], 'r': realized_r, 'win': is_win, 'exit_type': 'TP1_TRAIL_SL' if tp1_hit else 'FULL_SL'
                    })
                    del positions[sym]
                    continue

                # 狀況 B: 觸發 TP1 (平 50% 鎖利，SL 移動至 TP1 保留利潤)
                if hit_tp1:
                    pos['tp1_hit'] = True
                    symbol_stats[sym]['tp1_hits'] += 1
                    close_qty = pos['initial_qty'] * 0.5
                    pos['qty'] -= close_qty
                    
                    exit_price = tp1 * (1 - slip_rate) if is_long else tp1 * (1 + slip_rate)
                    exit_fee = close_qty * exit_price * fee_rate
                    half_pnl = (close_qty * (exit_price - entry) if is_long else close_qty * (entry - exit_price)) - exit_fee
                    
                    pos['accum_pnl'] += half_pnl
                    current_wallet += (close_qty * (exit_price - entry) if is_long else close_qty * (entry - exit_price)) - exit_fee
                    pos['sl'] = tp1 # 鎖死在 TP1

                # 狀況 C: 觸發 TP2 (平剩餘 50%，全額離場)
                if hit_tp2:
                    symbol_stats[sym]['tp2_hits'] += 1
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
                        st['long_r'] += realized_r
                        if is_win: st['long_wins'] += 1
                    else:
                        st['short_trades'] += 1
                        st['short_pnl'] += pos['accum_pnl']
                        st['short_r'] += realized_r
                        if is_win: st['short_wins'] += 1

                    completed_trades.append({
                        'symbol': sym, 'side': side, 'entry_time': pos['entry_time'], 'exit_time': curr_time,
                        'pnl': pos['accum_pnl'], 'r': realized_r, 'win': is_win, 'exit_type': 'TP2_FULL_HIT'
                    })
                    del positions[sym]
                    continue

            # 資金曲線與 Max Drawdown 即時追蹤
            if current_wallet > peak_wallet:
                peak_wallet = current_wallet
            dd_usdt = peak_wallet - current_wallet
            dd_pct = (dd_usdt / peak_wallet) * 100 if peak_wallet > 0 else 0.0
            if dd_usdt > max_drawdown_usdt: max_drawdown_usdt = dd_usdt
            if dd_pct > max_drawdown_pct: max_drawdown_pct = dd_pct

            # =========================================================================
            # 3. 產生進場信號 (於 Bar N 判定，存入 pending_signals，等待 Bar N+1 進場)
            # =========================================================================
            if sym not in positions and sym not in pending_signals and current_wallet > 5.0:
                sig_side = None
                entry_ref = bar['c']
                sl_ref, tp1_ref, tp2_ref = 0, 0, 0

                # 美股 1h 均線回踩 (放量收陽/收陰確認)
                if mode == 'stock_pullback':
                    trend_bull = (bar['ema20'] > bar['ema50']) and (bar['c'] > bar['ema200'])
                    trend_bear = (bar['ema20'] < bar['ema50']) and (bar['c'] < bar['ema200'])
                    vol_ok = bar['v'] >= (bar['vol_ma20'] * 0.9)
                    
                    pullback_long = (bar['l'] <= bar['ema20']) and (bar['l'] >= bar['ema50'] * 0.992) and (bar['c'] > bar['o']) and (bar['rsi'] >= 45 and bar['rsi'] <= 60) and vol_ok
                    pullback_short = (bar['h'] >= bar['ema20']) and (bar['h'] <= bar['ema50'] * 1.008) and (bar['c'] < bar['o']) and (bar['rsi'] <= 55 and bar['rsi'] >= 40) and vol_ok

                    if trend_bull and pullback_long:
                        sig_side = 'LONG'
                        sl_ref = min(bar['l'], bar['ema50'] - (bar['atr'] * 1.5))
                        r = abs(entry_ref - sl_ref)
                        tp1_ref = entry_ref + (r * 1.5)
                        tp2_ref = entry_ref + (r * 3.0)
                    elif trend_bear and pullback_short:
                        sig_side = 'SHORT'
                        sl_ref = max(bar['h'], bar['ema50'] + (bar['atr'] * 1.5))
                        r = abs(sl_ref - entry_ref)
                        tp1_ref = entry_ref - (r * 1.5)
                        tp2_ref = entry_ref - (r * 3.0)

                # 加密貨幣 (15m 斐波順勢)
                else:
                    sub = df.iloc[max(0, idx-25):idx+1]
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
                            min_tp1 = entry_ref + abs(entry_ref - sl_ref) * 1.2
                            tp1_ref = max(h, min_tp1)
                            tp2_ref = max(h + (wave * 0.272), tp1_ref + abs(entry_ref - sl_ref))
                        elif cond_short:
                            sig_side = 'SHORT'
                            sl_ref = max(h, entry_ref + (bar['atr'] * 1.5))
                            min_tp1 = entry_ref - abs(sl_ref - entry_ref) * 1.2
                            tp1_ref = min(l, min_tp1)
                            tp2_ref = min(l - (wave * 0.272), tp1_ref - abs(sl_ref - entry_ref))

                if sig_side:
                    pending_signals[sym] = {
                        'side': sig_side, 'sl': sl_ref, 'tp1': tp1_ref, 'tp2': tp2_ref,
                        'risk_usdt': current_wallet * RISK_PCT
                    }

    # =========================================================================
    # 4. 生成全維度統計指標 (R-Multiple, PF, Expectancy, Monthly, In/Out-Sample)
    # =========================================================================
    if not completed_trades:
        print("回測期間內無交易產生。")
        return

    df_trades = pd.DataFrame(completed_trades)
    total_trades = len(df_trades)
    win_trades = len(df_trades[df_trades['win']])
    loss_trades = total_trades - win_trades
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    # 盈虧金額統計
    gross_profit = df_trades[df_trades['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.99
    
    avg_win_usdt = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if win_trades > 0 else 0.0
    avg_loss_usdt = abs(df_trades[df_trades['pnl'] < 0]['pnl'].mean()) if loss_trades > 0 else 0.0
    payoff_ratio = (avg_win_usdt / avg_loss_usdt) if avg_loss_usdt > 0 else 0.0

    # R-Multiple 統計
    total_r = df_trades['r'].sum()
    avg_r = df_trades['r'].mean()
    expectancy_r = ( (win_trades/total_trades) * (df_trades[df_trades['win']]['r'].mean() if win_trades > 0 else 0) ) + \
                   ( (loss_trades/total_trades) * (df_trades[~df_trades['win']]['r'].mean() if loss_trades > 0 else 0) )

    # 最大連續虧損
    df_trades['is_loss'] = ~df_trades['win']
    loss_streaks = df_trades['is_loss'].groupby((~df_trades['is_loss']).cumsum()).sum()
    max_consecutive_losses = int(loss_streaks.max()) if not loss_streaks.empty else 0

    # 月度績效統計 (Monthly Breakdown)
    df_trades['year_month'] = pd.to_datetime(df_trades['exit_time']).dt.strftime('%Y-%m')
    monthly_rows = []
    for ym, m_df in df_trades.groupby('year_month'):
        m_t = len(m_df)
        m_w = len(m_df[m_df['win']])
        m_wr = (m_w / m_t * 100) if m_t > 0 else 0.0
        m_pnl = m_df['pnl'].sum()
        m_r = m_df['r'].sum()
        monthly_rows.append(f"{ym} | 交易: {str(m_t).rjust(3)}次 | 勝率: {m_wr:5.1f}% | PnL: {m_pnl:+9.2f} U | R: {m_r:+6.1f}R")

    # In-Sample (前8個月) vs Out-of-Sample (後4個月) 統計
    split_date = pd.to_datetime(earliest_start) + timedelta(days=240)
    split_str = split_date.strftime('%Y-%m-%d')
    in_sample_df = df_trades[pd.to_datetime(df_trades['exit_time']) < split_date]
    out_sample_df = df_trades[pd.to_datetime(df_trades['exit_time']) >= split_date]

    def get_split_stats(sub_df, name):
        if sub_df.empty: return f"{name}: 無交易"
        t = len(sub_df)
        w = len(sub_df[sub_df['win']])
        wr = (w / t) * 100
        pnl = sub_df['pnl'].sum()
        r = sub_df['r'].sum()
        gp = sub_df[sub_df['pnl'] > 0]['pnl'].sum()
        gl = abs(sub_df[sub_df['pnl'] < 0]['pnl'].sum())
        pf = (gp / gl) if gl > 0 else 99.99
        return f"[{name}] 交易: {t}次 | 勝率: {wr:.1f}% | PnL: {pnl:+.2f} U | R: {r:+.1f}R | PF: {pf:.2f}"

    in_sample_report = get_split_stats(in_sample_df, f"Train (前8月 ~ {split_str})")
    out_sample_report = get_split_stats(out_sample_df, f"Test  (後4月 {split_str} ~ )")

    # 標的細分清單 (多空拆分 + R值)
    symbol_lines = []
    for sym, st in symbol_stats.items():
        c = st['trades']
        if c == 0: continue
        w = st['wins']
        wr = (w / c * 100)
        l_wr = (st['long_wins'] / st['long_trades'] * 100) if st['long_trades'] > 0 else 0.0
        s_wr = (st['short_wins'] / st['short_trades'] * 100) if st['short_trades'] > 0 else 0.0
        
        symbol_lines.append(
            f"{sym.ljust(5)} | 總: {str(c).rjust(3)}次 ({wr:4.1f}%) | "
            f"多: {str(st['long_trades']).rjust(3)}次 ({l_wr:4.1f}%) | "
            f"空: {str(st['short_trades']).rjust(3)}次 ({s_wr:4.1f}%) | "
            f"R: {st['total_r']:+6.1f}R | PnL: {st['pnl']:+9.2f} U"
        )

    # 完整綜合報表
    report_text = (
        "```text\n"
        "==================【嚴格機構級回測報告 (無前瞻偏差)】==================\n"
        f"回測區間 : {earliest_start} ~ {latest_end}\n"
        f"撮合規則 : N+1開盤進場 | 同K保守SL優先 | 全手續費+滑點內扣\n"
        f"初始資金 : ${format_full_num(INITIAL_WALLET)} USDT  ➔  最終結餘: ${format_full_num(current_wallet, 2)} USDT ({roi_pct:+.2f}%)\n"
        f"最大回撤 : -${max_drawdown_usdt:.2f} USDT (-{max_drawdown_pct:.2f}%) | 最大連續虧損: {max_consecutive_losses} 次\n"
        f"總交易數 : {total_trades} 筆 (獨立持倉週期) | 綜合勝率: {overall_win_rate:.2f}%\n"
        f"獲利因子 : {profit_factor:.2f} (PF) | 盈虧比: {payoff_ratio:.2f} | 期望值: {expectancy_r:+.2f} R/Trade\n"
        f"累計 R值 : {total_r:+.1f} R (平均每筆: {avg_r:+.2f} R)\n"
        "--------------------------------------------------------------------\n"
        "【樣本內外檢驗 (In-Sample / Out-of-Sample)】\n"
        f"• {in_sample_report}\n"
        f"• {out_sample_report}\n"
        "--------------------------------------------------------------------\n"
        "【每月績效分解 (Monthly Breakdown)】\n"
        + "\n".join(monthly_rows) + "\n"
        "--------------------------------------------------------------------\n"
        "【各標的獨立診斷 (多空拆解 & R貢獻)】\n"
        + "\n".join(symbol_lines) + "\n"
        "====================================================================\n"
        "```"
    )

    print("\n" + report_text)
    print(">>> 正在發送專業報告至 Discord...")
    send_discord_safe(report_text)
    print(">>> 推播完成！")

if __name__ == '__main__':
    run_backtest()
