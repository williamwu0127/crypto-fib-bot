import os
import time
import requests
import urllib.parse
import pandas as pd
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0
RISK_PER_TRADE = 150.0

# 14 檔主流與美股標的配置
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
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&limit=300"
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) >= 40:
                df = pd.DataFrame(res, columns=['t','o','h','l','c','v','ct','q','n','tb','tq','i'])
                for c in ['o','h','l','c','v']:
                    df[c] = df[c].astype(float)
                return df[['o','h','l','c','v']]
        else:
            df = yf.download(cfg['s'], period="5d", interval="15m", progress=False)
            if not df.empty and len(df) >= 40:
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
        if df is None:
            continue

        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        
        i = 30
        while i < len(df) - 1:
            sub = df.iloc[i-20:i+1]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            if wave <= 0 or (wave / l) < 0.003:
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

            side = None
            if bar['c'] >= df['ema50'].iloc[i] and bar['l'] <= fib_0618_l * 1.002 and (lower_wick >= body * 0.5 or bar['c'] > bar['o']):
                side, sl, tp1, tp2 = "LONG", l * 0.997, fib_0382_l, h
            elif bar['c'] <= df['ema50'].iloc[i] and bar['h'] >= fib_0618_s * 0.998 and (upper_wick >= body * 0.5 or bar['c'] < bar['o']):
                side, sl, tp1, tp2 = "SHORT", h * 1.003, fib_0382_s, l

            if side:
                r_profit = 0.0
                step = 1
                for j in range(i + 1, min(i + 25, len(df))):
                    fb = df.iloc[j]
                    step += 1
                    if side == "LONG":
                        if fb['l'] <= sl: r_profit = -1.0; break
                        elif fb['h'] >= tp2: r_profit = 2.8; break
                        elif fb['h'] >= tp1: r_profit = 1.0
                    else:
                        if fb['h'] <= sl: r_profit = -1.0; break
                        elif fb['l'] <= tp2: r_profit = 2.8; break
                        elif fb['l'] <= tp1: r_profit = 1.0

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
        send_discord("⚠️ 本週期無觸發交易。")
        return

    res = pd.DataFrame(all_trades)
    total = len(res)
    win = len(res[res['r'] > 0])
    loss = len(res[res['r'] < 0])
    winrate = (win / total) * 100 if total > 0 else 0
    total_r = res['r'].sum()
    total_usd = res['usd'].sum()
    roi = (total_usd / ACCOUNT_BALANCE) * 100

    # 標的分組統計
    grp = res.groupby('sym').agg({'r': ['count', lambda x: (x > 0).sum()], 'usd': 'sum', 'm': 'first'})
    grp.columns = ['cnt', 'wins', 'usd', 'm']
    
    rows = []
    for s, r in grp.iterrows():
        rows.append(f"{s:<5} | {int(r['cnt']):<3}筆 (勝{int(r['wins'])}) | 押 ${int(r['m']):<4} | {r['usd']:>+8.1f} U")
    
    table_str = "\n".join(rows)

    report = (
        f"📊 **[BACKTEST REPORT] 主流/美股波段績效報告**\n"
        f"```text\n"
        f"本金規模: ${ACCOUNT_BALANCE:,.0f} USD \vert{} 單筆風控: ${RISK_PER_TRADE:,.0f} USD (1.5%)\n"
        f"交易統計: 共 {total} 筆 (勝 {win} / 負 {loss}) | 勝率: {winrate:.1f}%\n"
        f"累計收益: {total_r:+.1f} R | 淨利: {total_usd:+,.1f} USD (ROI: {roi:+.1f}%)\n"
        f"-----------------------------------------\n"
        f"{table_str}\n"
        f"```"
    )
    send_discord(report)
    print("=== 完成 ===")

if __name__ == '__main__':
    backtest()
