import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0  # 帳戶本金
RISK_PER_TRADE = 100.0     # 單筆固定 1% 風控 (100 USDT)
LEVERAGE = 10.0            # 10x 槓桿

# 14 檔標的現貨數據源配置
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

def send_discord(content):
    if not DISCORD_WEBHOOK_URL:
        print("[Console Log]\n", content)
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
    except Exception as e:
        print("Webhook Error:", e)

def get_latest_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = "https://data-api.binance.vision/api/v3/klines?symbol=" + cfg['s'] + "&interval=15m&limit=100"
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) >= 60:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms').dt.strftime('%H:%M')
                return df[['time', 'o', 'h', 'l', 'c', 'v']]
        else:
            df = yf.download(cfg['s'], period="2d", interval="15m", progress=False)
            if not df.empty and len(df) >= 60:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                df = df.reset_index()
                time_col = 'datetime' if 'datetime' in df.columns else 'date'
                df['time'] = pd.to_datetime(df[time_col]).dt.strftime('%H:%M')
                rename_map = {'open': 'o', 'high': 'h', 'low': 'l', 'close': 'c', 'volume': 'v'}
                return df[['time', 'open', 'high', 'low', 'close', 'volume']].rename(columns=rename_map)
    except Exception:
        pass
    return None

def scan_signal(sym, cfg):
    df = get_latest_data(cfg)
    if df is None or len(df) < 60:
        return None

    # 指標運算
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

    # 取已確認收盤的 K 棒 (倒數第 2 筆)
    idx = len(df) - 2
    sub = df.iloc[idx-25:idx+1]
    h, l = sub['h'].max(), sub['l'].min()
    wave = h - l

    if wave <= 0 or (wave / l) < 0.005:
        return None

    bar = df.iloc[idx]
    prev_bar = df.iloc[idx-1]
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

    # 多頭訊號判定
    rsi_bull = (30 <= bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
    cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l)
    
    # 空頭訊號判定
    rsi_bear = (45 <= bar['rsi'] <= 70) and (bar['rsi'] <= bar['rsi_ema'] or bar['rsi'] < prev_bar['rsi'])
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
        sl_pct = max(sl_pct, 0.002)
        pos_val = RISK_PER_TRADE / sl_pct  # 名義開倉總價值 (建議倉位)

        return {
            'sym': sym,
            'side': side,
            'time': bar['time'],
            'entry': entry_price,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'sl_pct': sl_pct * 100,
            'pos_val': pos_val,
            'rsi': bar['rsi']
        }
    return None

def main():
    detected_signals = []
    
    for sym, cfg in SYMBOLS.items():
        sig = scan_signal(sym, cfg)
        if sig:
            detected_signals.append(sig)
        time.sleep(0.05)

    if not detected_signals:
        print("[No Signal] 14 檔標的目前無符合交易條件之訊號。")
        return

    for s in detected_signals:
        side_tag = "🟢 [LONG / 做多]" if s['side'] == 'LONG' else "🔴 [SHORT / 做空]"
        msg = (
            side_tag + " **" + s['sym'] + "** (15m 趨勢觸發)\n"
            "```text\n"
            "進場時間 : " + s['time'] + " UTC\n"
            "進場價格 : $" + ("%.2f" % s['entry']) + "\n"
            "停損價格 : $" + ("%.2f" % s['sl']) + " (-" + ("%.2f" % s['sl_pct']) + "% | ATR 防插針)\n"
            "第一目標 : $" + ("%.2f" % s['tp1']) + " (Fib 0.382 / 減半保本)\n"
            "終極目標 : $" + ("%.2f" % s['tp2']) + " (前波極值 / 清倉)\n"
            "-----------------------------------------\n"
            "建議倉位 : $" + ("{:,.0f}".format(s['pos_val'])) + " USDT (10x 槓桿)\n"
            "風險鎖定 : 固定虧損 -$100 USDT (1.0%)\n"
            "動態指標 : RSI(14) = " + ("%.1f" % s['rsi']) + "\n"
            "```"
        )
        send_discord(msg)

if __name__ == '__main__':
    main()
