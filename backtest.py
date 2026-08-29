import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0  # 帳戶本金 10,000 USDT
RISK_PER_TRADE = 100.0     # 單筆固定 1% 風控 ($100 USDT)
LEVERAGE = 10.0            # 統一 10x 槓桿

SYMBOLS = {
    'BTC': {'t': 'binance', 's': 'BTCUSDT'},
    'ETH': {'t': 'binance', 's': 'ETHUSDT'},
    'XAU': {'t': 'binance', 's': 'PAXGUSDT'},
    'CLU': {'t': 'stock', 's': 'CL=F'},
    'TSM': {'t': 'stock', 's': 'TSM'},
    'NVDA': {'t': 'stock', 's': 'NVDA'},
    'TSLA': {'t': 'stock', 's': 'TSLA'},
    'AAPL': {'t': 'stock', 's': 'AAPL'},
    'GOOGL': {'t': 'stock', 's': 'GOOGL'},
    'MU': {'t': 'stock', 's': 'MU'},
    'AMZN': {'t': 'stock', 's': 'AMZN'},
    'GLW': {'t': 'stock', 's': 'GLW'},
    'SPCX': {'t': 'stock', 's': 'SPCX'},
    'SNDK': {'t': 'stock', 's': 'SNDK'}
}

def send_discord(msg):
    if not DISCORD_WEBHOOK_URL:
        print(msg)
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg[:1950]}, timeout=8)
    except Exception as e:
        print("Webhook Error:", e)

def get_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = "https://data-api.binance.vision/api/v3/klines?symbol=" + cfg['s'] + "&interval=15m&limit=400"
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) >= 60:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                return df[['o', 'h', 'l', 'c', 'v']]
        else:
            df = yf.download(cfg['s'], period="7d", interval="15m", progress=False)
            if not df.empty and len(df) >= 60:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                rename_map = {'open': 'o', 'high': 'h', 'low': 'l', 'close': 'c', 'volume': 'v'}
                return df[['open', 'high', 'low', 'close', 'volume']].rename(columns=rename_map).reset_index(drop=True)
    except Exception:
        pass
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

            # 🟢 多單條件：EMA50 > EMA200 + 回踩 0.618 + 下影線拒絕或收陽 + RSI 翻揚且 <= 55
            rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l)
            
            # 🔴 空單條件：EMA50 < EMA200 + 反彈 0.618 + 上影線受阻或收陰 + RSI 轉弱且 >= 45
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
                margin_used = pos_value / LEVERAGE

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
                    'r': r_profit,
                    'usd': r_profit * RISK_PER_TRADE,
                    'margin': margin_used
                })
                i += max(step, 3)
            else:
                i += 1

    if not all_trades:
        send_discord("⚠️ 本週期無觸發交易。")
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
        'margin': 'mean'
    })
    grp.columns = ['cnt', 'wins', 'usd', 'avg_margin']
    
    rows = []
    for s, r in grp.iterrows():
        row_line = "%-5s | %2d筆 (勝%2d) | 10x均保證金 $%4.0f | %+8.1f USD" % (
            s, int(r['cnt']), int(r['wins']), float(r['avg_margin']), float(r['usd'])
        )
        rows.append(row_line)
    
    table_str = "\n".join(rows)
    line1 = "帳戶規模: $\%d USDT \vert{} 單筆固定風險: $%d USDT (1%%)" % (int(ACCOUNT_BALANCE), int(RISK_PER_TRADE))
    line2 = "進場機制: 順勢斐波 0.618 回踩 + RSI 轉折動態確認 (均衡最佳版)"
    line3 = "交易統計: 共 %d 筆 (勝 %d / 負 %d) | 勝率: %.1f%%" % (total, win, loss, winrate)
    line4 = "累計績效: %+.1f R | 淨利潤: %+.1f USD (ROI: %+.1f%%)" % (total_r, total_usd, roi)

    report = (
        "📊 **[BACKTEST REPORT] 10x 合約波段回測 (均衡最佳版)**\n"
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
    print("=== 完成 ===")

if __name__ == '__main__':
    backtest()
