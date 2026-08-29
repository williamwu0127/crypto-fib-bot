import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0  # 模擬帳戶本金 10,000 USDT
RISK_PER_TRADE = 100.0     # 單筆固定風險 1% = 100 USDT
LEVERAGE = 10.0            # 統一 10x 槓桿

# 14 檔主流加密幣、大宗商品與美股標的 (純現貨數據源)
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
                df = pd.DataFrame(res, columns=['t','o','h','l','c','v','ct','q','n','tb','tq','i'])
                for c in ['o','h','l','c','v']:
                    df[c] = df[c].astype(float)
                return df[['o','h','l','c','v']]
        else:
            df = yf.download(cfg['s'], period="5d", interval="15m", progress=False)
            if not df.empty and len(df) >= 60:
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

        # 1. 均線系統 (EMA 50, EMA 200)
        df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
        
        # 2. 波動度 ATR (14) 動態停損計算
        tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

        # 3. RSI (14) 指標與均線 RSI_EMA (9)
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
            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0

            rsi_bullish_signal = (30 <= bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
            if (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l):
                if (lower_wick >= body * 0.5 or bar['c'] > bar['o']) and rsi_bullish_signal:
                    side = "LONG"
                    sl = min(l, entry_price - (atr_val * 1.5))
                    tp1 = fib_0382_l
                    tp2 = h

            rsi_bearish_signal = (45 <= bar['rsi'] <= 70) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])
            elif (bar['c'] <= bar['ema50']) and (bar['ema50'] <= bar['ema200']) and (bar['h'] >= fib_0618_s * 0.998) and (bar['c'] <= h):
                if (upper_wick >= body * 0.5 or bar['c'] < bar['o']) and rsi_bearish_signal:
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
                        if fb['l'] <= (entry_price if hit_tp1 else sl):
                            r_profit = 1.0 if hit_tp1 else -1.0
                            break
                        if fb['h'] >= tp2:
                            r_profit = 2.8
                            break
                        elif fb['h'] >= tp1:
                            hit_tp1 = True
                    else:
                        if fb['h'] >= (entry_price if hit_tp1 else sl):
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

    grp = res.groupby('sym').agg({
        'r': ['count', lambda x: (x > 0).sum()],
        'usd': 'sum',
        'margin': 'mean'
    })
    grp.columns = ['cnt', 'wins', 'usd', 'avg_margin']
    
    rows = []
    for s, r in grp.iterrows():
        row_line = "%-5s | %2d筆 (勝%2d) | 10x均保證金 $%4.0f | %+8.1f USD" % (
            s, int(r['cnt']), int(r['wins']), r['avg_margin'], r['usd']
        )
        rows.append(row_line)
    
    table_str = "\n".join(rows)
    line1 = "帳戶規模: $" + str(int(ACCOUNT_BALANCE)) + " USDT \vert{} 單筆固定風險: $" + str(int(RISK_PER_TRADE)) + " USDT (1%)"
    line2 = "合約機制: 統一 10x 槓桿 | TP1 保本分批 + TP2 終極止盈"
    line3 = "交易統計: 共 " + str(total) + " 筆 (勝 " + str(win) + " / 負 " + str(loss) + ") | 勝率: %.1f%%" % winrate
    line4 = "累計績效: %+.1f R | 淨利潤: %+.1f USD (ROI: %+.1f%%)" % (total_r, total_usd, roi)

    report = (
        "📊 **[BACKTEST REPORT] 10x 合約多空趨勢回測 (RSI 深度整合版)**\n"
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
