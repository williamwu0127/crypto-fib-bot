import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import hmac
import hashlib
from datetime import datetime

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

BASE_URL = "https://fapi.binance.com"

SYMBOLS = {
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0, 'trade': True},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0, 'trade': True},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0, 'trade': True},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0, 'trade': True},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0, 'trade': True},
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0, 'trade': False},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0, 'trade': False},
    'TSM':  {'t': 'stock',   's': 'TSM',      'lev': 20.0,  'trade': False},
    'NVDA': {'t': 'stock',   's': 'NVDA',     'lev': 20.0,  'trade': False},
    'AMD':  {'t': 'stock',   's': 'AMD',      'lev': 20.0,  'trade': False},
    'MSFT': {'t': 'stock',   's': 'MSFT',     'lev': 20.0,  'trade': False},
    'AAPL': {'t': 'stock',   's': 'AAPL',     'lev': 20.0,  'trade': False},
    'GOOGL':{'t': 'stock',   's': 'GOOGL',    'lev': 20.0,  'trade': False},
    'AMZN': {'t': 'stock',   's': 'AMZN',     'lev': 20.0,  'trade': False},
    'META': {'t': 'stock',   's': 'META',     'lev': 20.0,  'trade': False},
    'TSLA': {'t': 'stock',   's': 'TSLA',     'lev': 20.0,  'trade': False},
    'MU':   {'t': 'stock',   's': 'MU',       'lev': 20.0,  'trade': False},
    'GLW':  {'t': 'stock',   's': 'GLW',      'lev': 20.0,  'trade': False},
    'SPCX': {'t': 'stock',   's': 'SPCX',     'lev': 20.0,  'trade': False},
    'SNDK': {'t': 'stock',   's': 'SNDK',     'lev': 20.0,  'trade': False}
}

def sign_query(params):
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(BINANCE_API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def get_wallet_balance():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return 100.0
    try:
        ts = int(time.time() * 1000)
        qs = sign_query({'timestamp': ts})
        headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
        r = requests.get(f"{BASE_URL}/fapi/v2/account?{qs}", headers=headers, timeout=6).json()
        for a in r.get('assets', []):
            if a['asset'] == 'USDT':
                return float(a['walletBalance'])
    except Exception:
        pass
    return 100.0

def set_leverage(symbol, target_leverage=100):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return target_leverage
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    for lev in [target_leverage, 75, 50, 25, 20, 10, 5]:
        try:
            ts = int(time.time() * 1000)
            qs = sign_query({'symbol': symbol, 'leverage': int(lev), 'timestamp': ts})
            r = requests.post(f"{BASE_URL}/fapi/v1/leverage?{qs}", headers=headers, timeout=6).json()
            if 'leverage' in r:
                return int(r['leverage'])
        except Exception:
            pass
    return 20

def place_binance_trade(symbol, side, entry_price, sl_price, wallet_balance):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return "僅推播 (未設定 API Key)"
    
    actual_lev = set_leverage(symbol, 100)
    risk_amount = wallet_balance * 0.01
    price_diff = abs(entry_price - sl_price)
    if price_diff <= 0:
        return "下單失敗: 止損距離異常"
    
    target_qty = risk_amount / price_diff
    position_value = target_qty * entry_price
    
    if position_value < 5.5:
        target_qty = 5.5 / entry_price
        position_value = 5.5
        sl_price = entry_price - (risk_amount / target_qty) if side == 'BUY' else entry_price + (risk_amount / target_qty)
    
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    try:
        ei = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=6).json()
        qty_precision = 2
        for s in ei.get('symbols', []):
            if s['symbol'] == symbol:
                qty_precision = s['quantityPrecision']
                break
        
        qty_str = f"{target_qty:.{qty_precision}f}"
        ts = int(time.time() * 1000)
        qs = sign_query({
            'symbol': symbol,
            'side': side,
            'type': 'MARKET',
            'quantity': qty_str,
            'timestamp': ts
        })
        order_res = requests.post(f"{BASE_URL}/fapi/v1/order?{qs}", headers=headers, timeout=6).json()
        
        if 'orderId' in order_res:
            opp_side = 'SELL' if side == 'BUY' else 'BUY'
            ts_sl = int(time.time() * 1000)
            qs_sl = sign_query({
                'symbol': symbol,
                'side': opp_side,
                'type': 'STOP_MARKET',
                'stopPrice': f"{sl_price:.2f}",
                'closePosition': 'true',
                'timestamp': ts_sl
            })
            requests.post(f"{BASE_URL}/fapi/v1/order?{qs_sl}", headers=headers, timeout=6)
            return f"實盤開單成功 ({actual_lev}x | 數量: {qty_str} | 風控鎖定 1%)"
        else:
            return f"開單失敗: {order_res.get('msg', '未知錯誤')}"
    except Exception as e:
        return f"開單異常: {str(e)}"

def get_market_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&limit=120"
            res = requests.get(url, timeout=6).json()
            if isinstance(res, list) and len(res) >= 60:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(res, columns=cols)
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                return df[['o', 'h', 'l', 'c', 'v']]
        else:
            df = yf.download(cfg['s'], period="5d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) >= 30:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                req_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in req_cols):
                    res_df = df[req_cols].copy()
                    res_df.columns = ['o', 'h', 'l', 'c', 'v']
                    return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def scan_signals():
    wallet_balance = get_wallet_balance()
    risk_amount = wallet_balance * 0.01
    now_str = datetime.now().strftime("%H:%M")
    
    summary_lines = []
    trade_signals = []

    for sym, cfg in SYMBOLS.items():
        df = get_market_data(cfg)
        if df is None or len(df) < 50:
            summary_lines.append(f"{sym.ljust(5)} | 現價: {'N/A':>10} | 資料不足")
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

        bar = df.iloc[-1]
        prev_bar = df.iloc[-2]
        ema_status = "多頭" if bar['ema50'] >= bar['ema200'] else "空頭"
        market_status = " (休市)" if (cfg['t'] == 'stock' and (datetime.now().weekday() >= 5)) else ""
        summary_lines.append(f"{sym.ljust(5)} | 現價: {bar['c']:>9.2f} USDT | EMA: {ema_status} | RSI: {bar['rsi']:.1f}{market_status}")

        sub = df.iloc[-25:]
        h, l = sub['h'].max(), sub['l'].min()
        wave = h - l
        if wave <= 0 or (wave / l) < 0.005:
            continue

        fib_0618_l = h - (wave * 0.618)
        rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
        cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull

        if cond_long:
            entry = bar['c']
            sl = min(l, entry - (bar['atr'] * 1.5))
            tp1 = entry + abs(entry - sl)
            tp2 = h
            
            exec_status = "僅推播 (未開啟自動開單)"
            if cfg['trade']:
                exec_status = place_binance_trade(cfg['s'], 'BUY', entry, sl, wallet_balance)
            
            trade_signals.append(
                f"🟢 [LONG / 做多] **{sym}** 交易建議:\n"
                f"進場時間 : {now_str} (台灣時間)\n"
                f"進場價格 : ${entry:.2f} USDT\n"
                f"停損價格 : ${sl:.2f} USDT (動態風控 1% 鎖定)\n"
                f"第一止盈 : ${tp1:.2f} USDT (獲利目標 / 50% 倉位)\n"
                f"第二止盈 : ${tp2:.2f} USDT (前波極值 / 50% 倉位)\n"
                f"實盤執行 : {exec_status}\n"
                f"指標數據 : RSI(14) = {bar['rsi']:.1f}"
            )

    report1 = (
        "📊 **[15m 綜合掃描報告] 發現觸發訊號**\n"
        "```text\n"
        f"掃描時間: {now_str} (台灣時間) | 標的數: 20 檔\n"
        f"合約錢包: {wallet_balance:.2f} USDT | 動態風控: 1% (${risk_amount:.2f} USDT)\n"
        "----------------------------------------------------\n"
        + "\n".join(summary_lines[:10]) + "\n"
        "```"
    )

    report2 = (
        "```text\n"
        + "\n".join(summary_lines[10:]) + "\n"
        "----------------------------------------------------\n"
        "```\n"
        + ("\n\n".join(trade_signals) if trade_signals else "當前無觸發新單。")
    )

    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": report1}, timeout=8)
            requests.post(DISCORD_WEBHOOK_URL, json={"content": report2}, timeout=8)
        except Exception:
            pass

if __name__ == '__main__':
    scan_signals()
