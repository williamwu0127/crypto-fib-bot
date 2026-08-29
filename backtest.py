import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 100.0   # 帳戶本金 100 USDT
RISK_PER_TRADE = 1.0      # 單筆固定 1% 風控 ($1.0 USDT)

SYMBOLS = {
    # 1. 主流加密貨幣 (Binance 100x)
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0},
    
    # 2. 大宗商品 & 貴金屬 (Binance 100x)
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0},
    
    # 3. 美股龍頭 (Binance 20x)
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

def send_discord(msg):
    if not DISCORD_WEBHOOK_URL:
        print("[No Webhook URL]\n", msg)
        return
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg[:1900]}, timeout=8)
        if res.status_code not in [200, 204]:
            print("Webhook Status Code:", res.status_code, res.text)
    except Exception as e:
        print("Webhook Error:", e)

def get_binance_1mo_data(symbol):
    """分頁抓取近 30 天 15m K 線 (約 2880 根)"""
    all_rows = []
    end_time = int(time.time() * 1000)
    for _ in range(3):
        url = "https://data-api.binance.vision/api/v3/klines?symbol=" + symbol + "&interval=15m&limit=1000&endTime=" + str(end_time)
        try:
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) > 0:
                all_rows = res + all_rows
                end_time = res[0][0] - 1
            else:
                break
        except Exception:
            break
        time.sleep(0.05)

    if not all_rows:
        return None

    cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
    df = pd.DataFrame(all_rows, columns=cols).drop_duplicates(subset=['t']).sort_values('t')
    for col in ['o', 'h', 'l', 'c', 'v']:
        df[col] = df[col].astype(float)
    return df[['o', 'h', 'l', 'c', 'v']].reset_index(drop=True)

def get_data(cfg):
    try:
        if cfg['t'] == 'binance':
            return get_binance_1mo_data(cfg['s'])
        else:
            df = yf.download(cfg['s'], period="1mo", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 60:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    return res_df.reset_index(drop=True)
    except Exception as e:
        print("Error loading " + str(cfg['s']) + ": " + str(e))
    return None

def backtest():
    all_trades = []
    
    for sym, cfg in SYMBOLS.items():
        df = get_data(cfg)
        if df is None or len(df) < 60:
            continue

        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
        
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

        i = 40
        while i < len(df) - 1:
            sub = df.iloc[i-25:i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            
            if wave <= 0 or (wave / l) < 0.005:
                i += 1
                continue

            bar = df.iloc[i]
            prev_bar = df.iloc[i-1]
            entry_price = bar['c']

            fib_0618_l = h - (wave * 0.618)
            fib_0382_l = h - (wave * 0.382)
            fib_0618_s = l + (wave * 0.618)
            fib_0382_s = l + (wave * 0.382)
            
            body = abs(bar['c'] - bar['o'])
            lower_wick = min(bar['o'], bar['c']) - bar['l']
            upper_wick = bar['h'] - max(bar['o'], bar['c'])
            atr_val = bar['atr']

            side = None
            sl, tp1, tp2 = 0.0, 0.0, 0.0

            rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l)
            
            rsi_bear = (bar['rsi'] >= 45) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])
            cond_short = (bar['c'] <= bar['ema50']) and (bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h)

            if cond_long and (lower_wick >= body * 0.5 or bar['c'] > bar['o']) and rsi_bull:
                side = "LONG"
                sl = min(l, entry_price - (atr_val * 1.5))
                tp1 = fib_0382_l
                tp2 = h
            elif cond_short and (upper_wick >= body * 0.5 or bar['c'] < bar['o']) and rsi_bear:
                side = "SHORT"
                sl = max(h, entry_price + (atr_val * 1.5))
                tp1 = fib_0382_s
                tp2 = l

            if side:
                sl_pct = abs(entry_price - sl) / entry_price
                if sl_pct < 0.002:
                    sl_pct = 0.002
                
                pos_value = RISK_PER_TRADE / sl_pct
                margin_used = pos_value / cfg['lev']

                r_profit = 0.0
                step = 1
                hit_tp1 = False

                for j in range(i + 1, min(i + 35, len(df))):
                    fb = df.iloc[j]
                    step += 1
                    
                    if side == "LONG":
                        curr_sl = entry_price if hit_tp1 else sl
                        if fb['l'] <= curr_sl:
                            r_profit = 1.0 if hit_tp1 else -1.0
                            break
                        if fb['h'] >= tp2:
                            r_profit = 2.8
                            break
                        elif fb['h'] >= tp1:
                            hit_tp1 = True
                    else:
                        curr_sl = entry_price if hit_tp1 else sl
                        if fb['h'] >= curr_sl:
                            r_profit = 1.0 if hit_tp1 else -1.0
                            break
                        if fb['l'] <= tp2:
                            r_profit = 2.8
                            break
                        elif fb['l'] <= tp1:
                            hit_tp1 = True

                all_trades.append({
                    'sym': sym,
                    'lev': int(cfg['lev']),
                    'r': r_profit,
                    'usd': r_profit * RISK_PER_TRADE,
                    'margin': margin_used
                })
                i += max(step, 3)
            else:
                i += 1

    if not all_trades:
        send_discord("⚠️ 近 30 天無觸發交易。")
        return

    res = pd.DataFrame(all_trades)
    total = len(res)
    win = len(res[res['r'] > 0])
    loss = len(res[res['r'] < 0])
    winrate = (win / total) * 100.0 if total > 0 else 0.0
    total_r = res['r'].sum()
    total_usd = res['usd'].sum()
    roi = (total_usd / ACCOUNT_BALANCE) * 100.0

    grp = res.groupby('sym').agg({
        'r': ['count', lambda x: (x > 0).sum()],
        'usd': 'sum',
        'margin': 'mean',
        'lev': 'first'
    })
    grp.columns = ['cnt', 'wins', 'usd', 'avg_margin', 'lev']
    
    rows = []
    for s, r in grp.iterrows():
        row_line = "%-5s | %2d筆 (勝%2d) | %3dx均保證金 $%4.1f | %+7.1f USD" % (
            s, int(r['cnt']), int(r['wins']), int(r['lev']), float(r['avg_margin']), float(r['usd'])
        )
        rows.append(row_line)
    
    table_str = "\n".join(rows)
    line1 = "帳戶規模: $\%d USDT \vert{} 單筆固定風險: $%.1f USDT (1%%)" % (int(ACCOUNT_BALANCE), RISK_PER_TRADE)
    line2 = "幣安槓桿: 加密/商品 100x 槓桿 | 美股合約 20x 槓桿"
    line3 = "交易統計: 共 %d 筆 (勝 %d / 負 %d) | 勝率: %.1f%%" % (total, win, loss, winrate)
    line4 = "累計績效: %+.1f R | 淨利潤: %+.1f USD (ROI: %+.1f%%)" % (total_r, total_usd, roi)

    report = (
        "📊 **[BACKTEST REPORT] 幣安永續合約波段回測 (100U本金 / 30天)**\n"
        "```text\n"
        + line1 + "\n"
        + line2 + "\n"
        + line3 + "\n"
        + line4 + "\n"
        "--------------------------------------------------\n"
        + table_str + "\n"
        "```"
    )
    send_discord(report)
    print("=== 100U 帳戶 30 天回測完成 ===")

if __name__ == '__main__':
    backtest()
