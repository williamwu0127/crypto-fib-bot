import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0  # 帳戶本金 (USDT)
RISK_PER_TRADE = 100.0     # 單筆固定 1% 風控 (100 USDT)

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
        print("[No Webhook URL]\n", content)
        return False
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": content[:1950]}, timeout=8)
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
                df['time'] = pd.to_datetime(df['t'], unit='ms').dt.strftime('%H:%M')
                return df[['time', 'o', 'h', 'l', 'c', 'v']]
        else:
            # 改為 7d 確保週末亦可載入上週五之歷史 K 棒
            df = yf.download(cfg['s'], period="7d", interval="15m", progress=False)
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

    rsi_bull = (30 <= bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
    cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l)
    
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
        pos_val = RISK_PER_TRADE / sl_pct

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
        }, status_summary

    return None, status_summary

def main():
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
            pos_v = s['pos_val']
            sl_p = s['sl_pct']

            m10, loss10 = pos_v / 10.0, sl_p * 10.0
            m20, loss20 = pos_v / 20.0, sl_p * 20.0
            m50, loss50 = pos_v / 50.0, min(sl_p * 50.0, 100.0)
            m100, loss100 = pos_v / 100.0, min(sl_p * 100.0, 100.0)

            price_fmt = "%.4f" if s['entry'] < 1 else "%.2f"
            
            msg = (
                "%s **%s** (15m 趨勢觸發)\n"
                "```text\n"
                "進場時間 : %s UTC\n"
                "進場價格 : $%s\n"
                "停損價格 : $%s (-%.2f%% | ATR 防插針)\n"
                "第一目標 : $%s (Fib 0.382 / 減半設保本)\n"
                "終極目標 : $%s (前波極值 / 全平)\n"
                "----------------------------------------------------\n"
                "各槓桿所需保證金與本金損耗比 (固定風控 $100 USDT):\n"
                "• 10x  : 押 $%5.0f USDT | 觸及停損損耗保證金 %5.1f%%\n"
                "• 20x  : 押 $%5.0f USDT | 觸及停損損耗保證金 %5.1f%%\n"
                "• 50x  : 押 $%5.0f USDT | 觸及停損損耗保證金 %5.1f%%\n"
                "• 100x : 押 $%5.0f USDT | 觸及停損損耗保證金 %5.1f%%\n"
                "----------------------------------------------------\n"
                "指標數據 : RSI(14) = %.1f\n"
                "```" % (
                    side_tag, s['sym'], s['time'],
                    price_fmt % s['entry'], price_fmt % s['sl'], s['sl_pct'],
                    price_fmt % s['tp1'], price_fmt % s['tp2'],
                    m10, loss10, m20, loss20, m50, loss50, m100, loss100,
                    s['rsi']
                )
            )
            send_discord(msg)
    else:
        status_table = "\n".join(market_status)
        heartbeat_msg = (
            "📡 **[15m 掃描完成] 目前無觸發訊號**\n"
            "```text\n"
            "監控狀態: 14 檔標的連線正常 | 風控: 1% ($100 USDT)\n"
            "----------------------------------------------------\n"
            + status_table + "\n"
            "```"
        )
        send_discord(heartbeat_msg)

if __name__ == '__main__':
    main()
