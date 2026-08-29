import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 100.0   # 帳戶本金 100 USDT
RISK_PER_TRADE = 1.0      # 單筆固定 1% 風控 ($1.0 USDT)

# 20 檔標的與幣安合約專用槓桿配置 (加密/商品 100x，美股 20x)
SYMBOLS = {
    # 1. 主流加密貨幣 (Binance 100x)
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0, 'cat': '加密貨幣 (100x)'},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0, 'cat': '加密貨幣 (100x)'},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0, 'cat': '加密貨幣 (100x)'},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0, 'cat': '加密貨幣 (100x)'},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0, 'cat': '加密貨幣 (100x)'},
    
    # 2. 大宗商品 & 貴金屬 (Binance 100x)
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0, 'cat': '貴金屬 (100x)'},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0, 'cat': '原油商品 (100x)'},
    
    # 3. 美股龍頭 (Binance 20x)
    'TSM':  {'t': 'stock',   's': 'TSM',      'lev': 20.0,  'cat': '美股合約 (20x)'},
    'NVDA': {'t': 'stock',   's': 'NVDA',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'AMD':  {'t': 'stock',   's': 'AMD',      'lev': 20.0,  'cat': '美股合約 (20x)'},
    'MSFT': {'t': 'stock',   's': 'MSFT',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'AAPL': {'t': 'stock',   's': 'AAPL',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'GOOGL':{'t': 'stock',   's': 'GOOGL',    'lev': 20.0,  'cat': '美股合約 (20x)'},
    'AMZN': {'t': 'stock',   's': 'AMZN',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'META': {'t': 'stock',   's': 'META',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'TSLA': {'t': 'stock',   's': 'TSLA',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'MU':   {'t': 'stock',   's': 'MU',       'lev': 20.0,  'cat': '美股合約 (20x)'},
    'GLW':  {'t': 'stock',   's': 'GLW',      'lev': 20.0,  'cat': '美股合約 (20x)'},
    'SPCX': {'t': 'stock',   's': 'SPCX',     'lev': 20.0,  'cat': '美股合約 (20x)'},
    'SNDK': {'t': 'stock',   's': 'SNDK',     'lev': 20.0,  'cat': '美股合約 (20x)'}
}

def send_discord(content):
    if not DISCORD_WEBHOOK_URL:
        print("[No Webhook URL]\n", content)
        return False
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": content[:1900]}, timeout=8)
        return res.status_code in [200, 204]
    except Exception as e:
        print("Webhook Error:", e)
        return False

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
                
                dt_tw = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
                df['time'] = dt_tw.dt.strftime('%H:%M')
                return df[['time', 'o', 'h', 'l', 'c', 'v']]
        else:
            df = yf.download(cfg['s'], period="7d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 60:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    
                    idx = df.index
                    if idx.tz is None:
                        dt_tw = idx.tz_localize('UTC').tz_convert('Asia/Taipei')
                    else:
                        dt_tw = idx.tz_convert('Asia/Taipei')
                    res_df['time'] = dt_tw.strftime('%H:%M')
                    return res_df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
    except Exception as e:
        print("Fetch error " + str(cfg['s']) + ": " + str(e))
    return None

def scan_symbol(sym, cfg):
    df = get_latest_data(cfg)
    if df is None or len(df) < 60:
        return None, "%-5s | 休市/無數據" % sym

    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()

    idx = len(df) - 2
    sub = df.iloc[idx-25:idx+1]
    h, l = sub['h'].max(), sub['l'].min()
    wave = h - l

    bar = df.iloc[idx]
    prev_bar = df.iloc[idx-1]
    entry_price = bar['c']

    trend_label = "多頭" if bar['ema50'] >= bar['ema200'] else "空頭"
    market_flag = " (休市)" if (cfg['t'] == 'stock' and pd.to_datetime('now').weekday() in [5, 6]) else ""
    status_summary = "%-5s | 價: %8.2f | EMA: %s | RSI: %4.1f%s" % (sym, entry_price, trend_label, bar['rsi'], market_flag)

    if wave <= 0 or (wave / l) < 0.005:
        return None, status_summary

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
        sl_pct = max(sl_pct, 0.002)
        pos_val = RISK_PER_TRADE / sl_pct
        lev = cfg['lev']
        margin_req = pos_val / lev

        return {
            'sym': sym,
            'cat': cfg['cat'],
            'lev': int(lev),
            'side': side,
            'time': bar['time'],
            'entry': entry_price,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'sl_pct': sl_pct * 100,
            'pos_val': pos_val,
            'margin': margin_req,
            'rsi': bar['rsi']
        }, status_summary

    return None, status_summary

def main():
    tw_now = pd.to_datetime('now', utc=True).tz_convert('Asia/Taipei')
    detected_signals = []
    market_status = []

    for sym, cfg in SYMBOLS.items():
        sig, stat = scan_symbol(sym, cfg)
        if sig:
            detected_signals.append(sig)
        market_status.append(stat)
        time.sleep(0.05)

    if detected_signals:
        for s in detected_signals:
            side_tag = "🟢 [LONG / 做多]" if s['side'] == 'LONG' else "🔴 [SHORT / 做空]"
            price_fmt = "%.4f" if s['entry'] < 1 else "%.2f"
            
            msg = (
                "%s **%s** (%s)\n"
                "```text\n"
                "進場時間 : %s (台灣時間)\n"
                "進場價格 : $%s\n"
                "停損價格 : $%s (-%.2f%% | ATR 緩衝防插針)\n"
                "第一目標 : $%s (Fib 0.382 | 平倉50%% + 設保本損)\n"
                "終極目標 : $%s (前波極值 | 全平)\n"
                "----------------------------------------------------\n"
                "幣安合約參數設定 (固定風控 $1.0 USDT):\n"
                "• 槓桿倍數 : %dx 槓桿\n"
                "• 名義開倉 : $%5.1f USDT\n"
                "• 應押保證金: $%5.2f USDT (佔帳戶 %.2f%%)\n"
                "----------------------------------------------------\n"
                "指標數據 : RSI(14) = %.1f\n"
                "```" % (
                    side_tag, s['sym'], s['cat'],
                    s['time'],
                    price_fmt % s['entry'], price_fmt % s['sl'], s['sl_pct'],
                    price_fmt % s['tp1'], price_fmt % s['tp2'],
                    s['lev'], s['pos_val'], s['margin'], (s['margin'] / ACCOUNT_BALANCE) * 100,
                    s['rsi']
                )
            )
            send_discord(msg)
    else:
        status_table = "\n".join(market_status)
        heartbeat_msg = (
            "📡 **[15m 掃描完成] 目前無觸發訊號**\n"
            "```text\n"
            "掃描時間: " + tw_now.strftime('%H:%M') + " (台灣時間) | 標的數: 20 檔\n"
            "合約規格: 加密/商品 100x | 美股 20x | 風控: 1% ($1.0 USDT)\n"
            "----------------------------------------------------\n"
            + status_table + "\n"
            "```"
        )
        send_discord(heartbeat_msg)

if __name__ == '__main__':
    main()
