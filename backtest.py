import os, time, requests, pandas as pd, numpy as np, yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")
INITIAL_WALLET, RISK_PCT = 100.0, 0.01

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'min_wave': 0.008},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'interval': '15m', 'min_wave': 0.005},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'interval': '15m', 'min_wave': 0.005},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'interval': '15m', 'min_wave': 0.005},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'interval': '15m', 'min_wave': 0.008},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '15m', 'min_wave': 0.005},
    'TSM':   {'t': 'stock',   's': 'TSM',      'interval': '1h',  'min_wave': 0.015},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'interval': '1h',  'min_wave': 0.015},
    'AMD':   {'t': 'stock',   's': 'AMD',      'interval': '1h',  'min_wave': 0.015},
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'interval': '1h',  'min_wave': 0.015},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'interval': '1h',  'min_wave': 0.015},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'interval': '1h',  'min_wave': 0.015},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'interval': '1h',  'min_wave': 0.015},
    'META':  {'t': 'stock',   's': 'META',     'interval': '1h',  'min_wave': 0.015},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'interval': '1h',  'min_wave': 0.015},
    'MU':    {'t': 'stock',   's': 'MU',       'interval': '1h',  'min_wave': 0.015},
    'GLW':   {'t': 'stock',   's': 'GLW',      'interval': '1h',  'min_wave': 0.015},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'interval': '1h',  'min_wave': 0.015},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'interval': '1h',  'min_wave': 0.015}
}

def format_num(val, dec=8):
    return f"{float(val):.{dec}f}".rstrip('0').rstrip('.') or "0"

def send_discord(content):
    if not DISCORD_WEBHOOK_URL: return
    for i in range(0, len(content), 1800):
        try: requests.post(DISCORD_WEBHOOK_URL, json={"content": content[i:i+1800]}, timeout=8); time.sleep(0.3)
        except Exception: pass

def fetch_data(cfg):
    try:
        if cfg['t'] == 'binance':
            now_ms, start_ms = int(time.time() * 1000), int(time.time() * 1000) - 31536000000
            klines, curr = [], start_ms
            while curr < now_ms:
                r = requests.get(f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr}&limit=1000", timeout=10).json()
                if not isinstance(r, list) or not r: break
                klines.extend(r); curr = r[-1][0] + (15 * 60 * 1000); time.sleep(0.03)
            df = pd.DataFrame(klines, columns=['t','o','h','l','c','v','ct','q','n','tb','tq','i']).drop_duplicates(subset=['t'])
            for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
            return df[['time','o','h','l','c','v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="1y", interval="1h", progress=False)
            if df is not None and len(df) > 30:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                t_idx = pd.to_datetime(df.index)
                df['time'] = t_idx.tz_localize(None) if t_idx.tz is not None else t_idx
                return df[['time','open','high','low','close','volume']].rename(columns={'open':'o','high':'h','low':'l','close':'c','volume':'v'}).reset_index(drop=True)
    except Exception: pass
    return None

def add_indicators(df):
    for span in [20, 50, 200]: df[f'ema{span}'] = df['c'].ewm(span=span, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()
    return df

def run_backtest():
    print(f">>> 啟動精簡版【混和雙軌 + 全域複利】1 年期回測 | 初始本金: ${INITIAL_WALLET}")
    dfs = {sym: add_indicators(df) for sym, cfg in SYMBOLS.items() if (df := fetch_data(cfg)) is not None and len(df) > 30}
    if not dfs: return print("無可用數據")

    all_times = sorted(list(set(t for df in dfs.values() for t in df['time'])))
    current_wallet, positions, trades = float(INITIAL_WALLET), {}, []
    stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS}

    for curr_time in all_times:
        for sym, df in dfs.items():
            match = df[df['time'] == curr_time]
            if match.empty or (idx := match.index[0]) < 30: continue
            bar, prev = match.iloc[0], df.iloc[idx - 1]
            cfg, is_stock = SYMBOLS[sym], SYMBOLS[sym]['t'] == 'stock'
            trail_ema = bar['ema50'] if is_stock else bar['ema20']

            # 1. 統一持倉撮合 (多空合一)
            if sym in positions:
                p = positions[sym]
                is_long = p['side'] == 'LONG'
                hit_sl = bar['l'] <= p['sl'] if is_long else bar['h'] >= p['sl']
                hit_tp1 = bar['h'] >= p['tp1'] if is_long else bar['l'] <= p['tp1']
                trail_exit = (bar['c'] < trail_ema if is_long else bar['c'] > trail_ema) and ((bar['c'] > p['entry']) if is_long else (bar['c'] < p['entry']))

                # 停損
                if hit_sl:
                    q = p['qty'] * 0.5 if p['tp1_hit'] else p['qty']
                    pnl = q * ((p['sl'] - p['entry']) if is_long else (p['entry'] - p['sl']))
                    current_wallet += pnl; stats[sym]['trades'] += 1; stats[sym]['pnl'] += pnl
                    if pnl > 0: stats[sym]['wins'] += 1
                    trades.append({'symbol': sym, 'pnl': pnl}); del positions[sym]; continue

                # TP1 達成 (平 50%，SL 移保本)
                if not p['tp1_hit'] and hit_tp1:
                    p['tp1_hit'] = True
                    pnl_tp1 = (p['qty'] * 0.5) * ((p['tp1'] - p['entry']) if is_long else (p['entry'] - p['tp1']))
                    current_wallet += pnl_tp1; p['sl'] = p['entry']
                    stats[sym]['trades'] += 1; stats[sym]['wins'] += 1; stats[sym]['pnl'] += pnl_tp1

                # 剩餘 50% 動態追蹤
                if p['tp1_hit']:
                    p['sl'] = max(p['sl'], trail_ema) if is_long else min(p['sl'], trail_ema)
                    if trail_exit:
                        pnl_trail = (p['qty'] * 0.5) * ((bar['c'] - p['entry']) if is_long else (p['entry'] - bar['c']))
                        current_wallet += pnl_trail; stats[sym]['trades'] += 1; stats[sym]['wins'] += 1; stats[sym]['pnl'] += pnl_trail
                        trades.append({'symbol': sym, 'pnl': pnl_trail}); del positions[sym]; continue

            # 2. 開倉判定
            if sym not in positions and current_wallet > 5.0:
                side, entry, sl, tp1 = None, bar['c'], 0, 0
                if is_stock:
                    trend_l, trend_s = (bar['ema20'] > bar['ema50'] > bar['ema200']), (bar['ema20'] < bar['ema50'] < bar['ema200'])
                    pb_l = trend_l and (bar['l'] <= bar['ema20']) and (bar['l'] >= bar['ema50'] * 0.995) and (bar['c'] > bar['o']) and (45 <= bar['rsi'] <= 60)
                    pb_s = trend_s and (bar['h'] >= bar['ema20']) and (bar['h'] <= bar['ema50'] * 1.005) and (bar['c'] < bar['o']) and (40 <= bar['rsi'] <= 55)
                    if pb_l: side, sl = 'LONG', min(bar['l'], bar['ema50'] - (bar['atr'] * 1.2))
                    elif pb_s: side, sl = 'SHORT', max(bar['h'], bar['ema50'] + (bar['atr'] * 1.2))
                    if side: tp1 = entry + (abs(entry - sl) * 1.5 * (1 if side == 'LONG' else -1))
                else:
                    sub = df.iloc[max(0, idx-25):idx+1]
                    h, l = sub['h'].max(), sub['l'].min()
                    wave = h - l
                    if wave > 0 and (wave / l) >= cfg['min_wave']:
                        fib_l, fib_s = h - (wave * 0.618), l + (wave * 0.618)
                        rsi_l = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev['rsi'])
                        rsi_s = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev['rsi'])
                        if (bar['c'] >= bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_l * 1.002) and rsi_l:
                            side, sl = 'LONG', min(l, entry - (bar['atr'] * 1.5))
                        elif (bar['c'] <= bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_s * 0.998) and rsi_s:
                            side, sl = 'SHORT', max(h, entry + (bar['atr'] * 1.5))
                        if side: tp1 = entry + (abs(entry - sl) * 1.2 * (1 if side == 'LONG' else -1))

                if side and (p_diff := abs(entry - sl)) > 0:
                    positions[sym] = {'side': side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp1_hit': False, 'qty': (current_wallet * RISK_PCT) / p_diff}

    if not trades: return print("回測期間內無交易")
    df_res = pd.DataFrame(trades)
    wr = (len(df_res[df_res['pnl'] > 0]) / len(df_res)) * 100
    roi = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100
    lines = [f"{s.ljust(5)} | 交易: {str(v['trades']).rjust(4)}次 | 勝率: {(v['wins']/v['trades']*100 if v['trades'] else 0):5.2f}% | 收益: {v['pnl']:+12.6f}" for s, v in stats.items()]
    
    report = (
        "```text\n"
        "判定邏輯: 混和雙軌極簡版 (TP1平50%鎖勝率 + 50%追蹤抓到底) + 全域複利\n"
        f"初始資金: ${format_num(INITIAL_WALLET)} USDT \vert{} 最終結餘: ${format_num(current_wallet, 6)} USDT ({roi:+.4f}%)\n"
        f"總交易次數: {len(df_res)} 次 | 綜合勝率: {wr:.2f}%\n"
        "----------------------------------------------------\n" + "\n".join(lines) + "\n```"
    )
    print("\n" + report); send_discord(report); print(">>> 完成推播！")

if __name__ == '__main__':
    run_backtest()
