import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import ccxt

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

RISK_PERCENT = 0.01      # 動態 1% 風控
DEFAULT_BALANCE = 100.0  # 無 API Key 時之預設參考本金

SYMBOLS = {
    # 1. 加密貨幣 (100x 槓桿 / 實盤全自動下單)
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'ccxt_s': 'BTC/USDT:USDT',  'lev': 100.0, 'trade': True},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'ccxt_s': 'ETH/USDT:USDT',  'lev': 100.0, 'trade': True},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'ccxt_s': 'SOL/USDT:USDT',  'lev': 100.0, 'trade': True},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'ccxt_s': 'BNB/USDT:USDT',  'lev': 100.0, 'trade': True},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'ccxt_s': 'DOGE/USDT:USDT', 'lev': 100.0, 'trade': True},
    
    # 2. 大宗商品 & 貴金屬 (100x 槓桿 / 僅推播)
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'ccxt_s': 'PAXG/USDT:USDT', 'lev': 100.0, 'trade': False},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0, 'trade': False},
    
    # 3. 美股龍頭 (20x 槓桿 / 僅推播)
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

def get_exchange():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return None
    return ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_API_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

def get_wallet_usdt(exchange):
    if not exchange:
        return DEFAULT_BALANCE
    try:
        bal = exchange.fetch_balance()
        free_usdt = float(bal['free'].get('USDT', 0.0))
        return free_usdt if free_usdt > 0 else DEFAULT_BALANCE
    except Exception as e:
        print(f"獲取錢包餘額受限，使用預設本金: {e}")
        return DEFAULT_BALANCE

def place_order_with_sl_tp(exchange, sym_key, cfg, side, entry_p, sl_p, tp1_p, tp2_p, risk_usd):
    if not cfg.get('trade', False):
        return "未開單: 該標的未開啟實盤功能 (僅推播)"
    if not exchange:
        return "未開單: 未配置幣安 API Key"

    market_sym = cfg.get('ccxt_s', f"{sym_key}/USDT:USDT")
    try:
        exchange.load_markets()
        market = exchange.market(market_sym)

        # 1. 設置槓桿
        try:
            exchange.set_leverage(int(cfg['lev']), market_sym)
        except Exception as err:
            return f"開單失敗 (槓桿設定異常: {err})"

        # 2. 計算數量 (動態 1% 風控)
        sl_pct = max(abs(entry_p - sl_p) / entry_p, 0.002)
        notional = risk_usd / sl_pct
        raw_qty = notional / entry_p
        qty = float(exchange.amount_to_precision(market_sym, raw_qty))

        if qty * entry_p < 5.0:
            return f"未開單: 開倉價值 (${qty * entry_p:.2f} USDT) 低於幣安 5 USDT 門檻"

        order_side = 'buy' if side == 'LONG' else 'sell'
        close_side = 'sell' if side == 'LONG' else 'buy'
        sl_price_str = float(exchange.price_to_precision(market_sym, sl_p))

        # 3. 市價開倉
        try:
            order = exchange.create_order(symbol=market_sym, type='market', side=order_side, amount=qty)
            order_id = str(order.get('id', 'N/A'))
        except Exception as err:
            return f"開單失敗 (市價開倉失敗: {err})"

        # 4. SL 掛單 (100% 倉位止損) - 若失敗立即市價平倉撤出
        try:
            exchange.create_order(
                symbol=market_sym,
                type='STOP_MARKET',
                side=close_side,
                amount=qty,
                params={'stopPrice': sl_price_str, 'reduceOnly': True}
            )
        except Exception as err:
            try:
                # 緊急撤出平倉
                exchange.create_order(symbol=market_sym, type='market', side=close_side, amount=qty)
            except Exception:
                pass
            return f"開單失敗 (SL 止損單掛單失敗，已緊急撤出平倉: {err})"

        # 5. 第一止盈 (50% 倉位)
        tp1_qty = float(exchange.amount_to_precision(market_sym, qty * 0.5))
        if tp1_qty > 0:
            try:
                tp1_price_str = float(exchange.price_to_precision(market_sym, tp1_p))
                exchange.create_order(
                    symbol=market_sym,
                    type='TAKE_PROFIT_MARKET',
                    side=close_side,
                    amount=tp1_qty,
                    params={'stopPrice': tp1_price_str, 'reduceOnly': True}
                )
            except Exception as err:
                print(f"第一止盈掛單失敗: {err}")

        # 6. 第二止盈 (剩餘 50% 倉位)
        tp2_qty = float(exchange.amount_to_precision(market_sym, qty - tp1_qty))
        if tp2_qty > 0:
            try:
                tp2_price_str = float(exchange.price_to_precision(market_sym, tp2_p))
                exchange.create_order(
                    symbol=market_sym,
                    type='TAKE_PROFIT_MARKET',
                    side=close_side,
                    amount=tp2_qty,
                    params={'stopPrice': tp2_price_str, 'reduceOnly': True}
                )
            except Exception as err:
                print(f"第二止盈掛單失敗: {err}")

        return f"✅ 開倉成功 (ID: {order_id}) / SL與第一第二止盈均已部署"
    except Exception as err:
        return f"開單失敗: {err}"

def send_discord(content):
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": content[:1900]}, timeout=8)
        return res.status_code in [200, 204]
    except Exception as e:
        print(f"Webhook Error: {e}")
        return False

def get_latest_data(cfg):
    try:
        if cfg['t'] == 'binance':
            url = f"[https://data-api.binance.vision/api/v3/klines?symbol=](https://data-api.binance.vision/api/v3/klines?symbol=){cfg['s']}&interval=15m&limit=100"
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
                    dt_tw = idx.tz_localize('UTC').tz_convert('Asia/Taipei') if idx.tz is None else idx.tz_convert('Asia/Taipei')
                    res_df['time'] = dt_tw.strftime('%H:%M')
                    return res_df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
    except Exception as e:
        print(f"抓取數據異常 {cfg['s']}: {e}")
    return None

def scan_symbol(sym, cfg, exchange, current_risk):
    df = get_latest_data(cfg)
    if df is None or len(df) < 60:
        return None, f"{sym:<5} / 休市無數據"

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
    status_summary = f"{sym:<5} / 現價: {entry_price:8.2f} USDT / EMA: {trend_label} / RSI: {bar['rsi']:4.1f}{market_flag}"

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
        sl_pct = max(abs(entry_price - sl) / entry_price, 0.002)
        pos_val = current_risk / sl_pct

        order_status = place_order_with_sl_tp(exchange, sym, cfg, side, entry_price, sl, tp1, tp2, current_risk)

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
            'order_status': order_status,
            'rsi': bar['rsi']
        }, status_summary

    return None, status_summary

def main():
    tw_now = pd.to_datetime('now', utc=True).tz_convert('Asia/Taipei')
    
    exchange = get_exchange()
    wallet_balance = get_wallet_usdt(exchange)
    current_risk = wallet_balance * RISK_PERCENT

    detected_signals = []
    market_status = []

    for sym, cfg in SYMBOLS.items():
        sig, stat = scan_symbol(sym, cfg, exchange, current_risk)
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

            entry_str = f"{s['entry']:.4f}" if s['entry'] < 1 else f"{s['entry']:.2f}"
            sl_str = f"{s['sl']:.4f}" if s['sl'] < 1 else f"{s['sl']:.2f}"
            tp1_str = f"{s['tp1']:.4f}" if s['tp1'] < 1 else f"{s['tp1']:.2f}"
            tp2_str = f"{s['tp2']:.4f}" if s['tp2'] < 1 else f"{s['tp2']:.2f}"

            msg = (
                f"{side_tag} **{s['sym']}** (15m 趨勢觸發)\n"
                "```text\n"
                f"進場時間 : {s['time']} (台灣時間)\n"
                f"現價     : ${entry_str} USDT\n"
                f"停損價格 : ${sl_str} USDT (-{s['sl_pct']:.2f}% / 100% 止損)\n"
                f"第一止盈 : ${tp1_str} USDT (Fib 0.382 / 50% 倉位)\n"
                f"第二止盈 : ${tp2_str} USDT (前波極值 / 50% 倉位)\n"
                "----------------------------------------------------\n"
                f"合約錢包 : ${wallet_balance:.2f} USDT / 動態風控 1%: ${current_risk:.2f} USDT\n"
                "各槓桿所需倉位保證金與損耗比:\n"
                f"• 10x  : 倉位 ${m10:5.2f} USDT / 損耗保證金 {loss10:5.1f}%\n"
                f"• 20x  : 倉位 ${m20:5.2f} USDT / 損耗保證金 {loss20:5.1f}%\n"
                f"• 50x  : 倉位 ${m50:5.2f} USDT / 損耗保證金 {loss50:5.1f}%\n"
                f"• 100x : 倉位 ${m100:5.2f} USDT / 損耗保證金 {loss100:5.1f}%\n"
                "----------------------------------------------------\n"
                f"實盤執行 : {s['order_status']}\n"
                f"指標數據 : RSI(14) = {s['rsi']:.1f}\n"
                "```"
            )
            send_discord(msg)
    else:
        status_table = "\n".join(market_status)
        heartbeat_msg = (
            "📡 **[15m 掃描完成] 目前無觸發訊號**\n"
            "```text\n"
            f"掃描時間: {tw_now.strftime('%H:%M')} (台灣時間) / 標的數: 20 檔\n"
            f"合約錢包: ${wallet_balance:.2f} USDT / 動態風控: 1% (${current_risk:.2f} USDT)\n"
            "----------------------------------------------------\n"
            f"{status_table}\n"
            "```"
        )
        send_discord(heartbeat_msg)

if __name__ == '__main__':
    main()
