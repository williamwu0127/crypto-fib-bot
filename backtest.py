import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0
RISK_PER_TRADE = 150.0

SYMBOLS = {
    'BTC': {'t': 'binance', 's': 'BTCUSDT', 'm': 1500},
    'ETH': {'t': 'binance', 's': 'ETHUSDT', 'm': 1200},
    'XAU': {'t': 'binance', 's': 'PAXGUSDT', 'm': 1800},
    'CLU': {'t': 'stock', 's': 'CL=F', 'm': 1000},
    'TSM': {'t': 'stock', 's': 'TSM', 'm': 1500},
    'NVDA': {'t': 'stock', 's': 'NVDA', 'm': 2000},
    'TSLA': {'t': 'stock', 's': 'TSLA', 'm': 1800},
    'AAPL': {'t': 'stock', 's': 'AAPL', 'm': 1500},
    'GOOGL': {'t': 'stock', 's': 'GOOGL', 'm': 1500},
    'MU': {'t': 'stock', 's': 'MU', 'm': 1200},
    'AMZN': {'t': 'stock', 's': 'AMZN', 'm': 1600},
    'GLW': {'t': 'stock', 's': 'GLW', 'm': 1000},
    'SPCX': {'t': 'stock', 's': 'SPCX', 'm': 800},
    'SNDK': {'t': 'stock', 's': 'SNDK', 'm': 1500}
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
            if isinstance(res, list) and len(res) >= 50:
                df = pd.DataFrame(res, columns=['t','o','h','l','c','v','ct','q','n','tb','tq','i'])
                for c in ['o','h','l','c','v']:
                    df[c] = df[c].astype(float)
                return df[['o','h','l','c','v']]
        else:
            df = yf.download(cfg['s'], period="5d", interval="15m", progress=False)
            if not df.empty and len(df) >= 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                return df[['open','high','low','close','volume']].rename(
                    columns={'open':'o','high':'h','low':'l','close':'c','volume':'v'}
                ).reset_index(drop=True)
    except Exception:
        pass
    return None

def backtest():
    all_trades = []
    
    for sym, cfg in SYMBOLS.items():
        df = get_data(cfg)
        if df is None or len(df) < 60:
            continue

        # 計算指標
        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
        
        # ATR (14) 計算動態安全止損距離
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

        # RSI (14)
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

        i = 40
        while i < len(df) - 1:
            sub = df.iloc[i-25:i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            
            if wave <= 0 or (wave / l) < 0.005:
                i += 1
                continue

            bar = df.iloc[i]
            fib_0618_l = h - (wave * 0.618)
            fib_0382_l = h - (wave * 0.382)
            fib_0618_s = l + (wave * 0.618)
            fib_0382_s = l + (wave * 0.382)
            
            body = abs(bar['c'] - bar['o'])
            lower_wick = min(bar['o'], bar['c']) - bar['l']
            upper_wick = bar['h'] - max(bar['o'], bar['c'])
            atr_val = bar['atr']

            side = None
            # 多單：EMA50 > EMA200 (大順勢) + 回踩 0.618 + 下影線反彈 + RSI <= 50
            if (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l):
                if (lower_wick >= body * 0.5 or bar['c'] > bar['o']) and (bar['rsi'] <= 55):
                    side = "LONG"
                    sl = min(l, bar['c'] - (atr_val * 1.5))
                    tp1 = fib_0382_l
                    tp2 = h

            # 空單：EMA50 < EMA200 (大順勢) + 反彈 0.618 + 上影線受阻 + RSI >= 50
            elif (bar['c'] <= bar['ema50']) and (bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h):
                if (upper_wick >= body * 0.5 or bar['c'] < bar['o']) and (bar['rsi'] >= 45):
                    side = "SHORT"
                    sl = max(h, bar['c'] + (atr_val * 1.5))
                    tp1 = fib_0382_s
                    tp2 = l

            if side:
                r_profit = 0.0
                step = 1
                hit_tp1 = False

                for j in range(i + 1, min(i + 35, len(df))):
                    fb = df.iloc[j]
                    step += 1
                    
                    if side == "LONG":
                        if fb['l'] <= (bar['c'] if hit_tp1 else sl):
                            r_profit = 1.0 if hit_tp1 else -1.0
                            break
                        if fb['h'] >= tp2:
                            r_profit = 2.8
                            break
                        elif fb['h'] >= tp1:
                            hit_tp1 = True
                    else:
                        if fb['h'] >= (bar['c'] if hit_tp1 else sl):
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
                    'm': cfg['m']
                })
                i += max(step, 3)
            else:
                i += 1

    if not all_trades:
        send_discord("⚠️ 本週期嚴格篩選下無觸發交易。")
        return

    res = pd.DataFrame(all_trades)
    total = len(res)
    win = len(res[res['r'] > 0])
    loss = len(res[res['r'] < 0])
    winrate = (win / total) * 100 if total > 0 else 0
    total_r = res['r'].sum()
    total_usd = res['usd'].sum()
    roi = (total_usd / ACCOUNT_BALANCE) * 100

    grp = res.groupby('sym').agg({'r': ['count', lambda x: (x > 0).sum()], 'usd': 'sum', 'm': 'first'})
    grp.columns = ['cnt', 'wins', 'usd', 'm']
    
    rows = []
    for s, r in grp.iterrows():
        row_line = "%-5s | %2d筆 (勝%2d) | 押 $%4d | %+8.1f USD" % (s, int(r['cnt']), int(r['wins']), int(r['m']), r['usd'])
        rows.append(row_line)
    
    table_str = "\n".join(rows)
    line1 = "本金規模: $" + str(int(ACCOUNT_BALANCE)) + " USD \vert{} 單筆風控: $" + str(int(RISK_PER_TRADE)) + " USD (1.5%)"
    line2 = "交易統計: 共 " + str(total) + " 筆 (勝 " + str(win) + " / 負 " + str(loss) + ") | 勝率: %.1f%%" % winrate
    line3 = "累計收益: %+.1f R | 淨利: %+.1f USD (ROI: %+.1f%%)" % (total_r, total_usd, roi)

    report = (
        "📊 **[BACKTEST REPORT] 主流/美股波段績效報告 (嚴格風控優化版)**\n"
        "```text\n"
        + line1 + "\n"
        + line2 + "\n"
        + line3 + "\n"
        "-----------------------------------------\n"
        + table_str + "\n"
        "```"
    )
    send_discord(report)
    print("=== 完成 ===")

if __name__ == '__main__':
    backtest()
