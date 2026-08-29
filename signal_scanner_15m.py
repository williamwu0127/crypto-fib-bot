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

RISK_PERCENT = 0.01  # 單筆固定 1% 風控 (動態依據合約錢包餘額)
DEFAULT_BALANCE = 100.0  # 預設基準餘額 (若無 API Key 時使用)

# 20 檔標的配置 (加密貨幣 trade=True 支援幣安實盤全自動下單)
SYMBOLS = {
    # 1. 主流加密貨幣 (Binance 100x / 實盤自動開單)
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'ccxt_s': 'BTC/USDT:USDT',  'lev': 100.0, 'cat': '加密貨幣', 'trade': True},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'ccxt_s': 'ETH/USDT:USDT',  'lev': 100.0, 'cat': '加密貨幣', 'trade': True},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'ccxt_s': 'SOL/USDT:USDT',  'lev': 100.0, 'cat': '加密貨幣', 'trade': True},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'ccxt_s': 'BNB/USDT:USDT',  'lev': 100.0, 'cat': '加密貨幣', 'trade': True},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'ccxt_s': 'DOGE/USDT:USDT', 'lev': 100.0, 'cat': '加密貨幣', 'trade': True},
    
    # 2. 大宗商品 & 貴金屬 (Binance 100x)
    'XAU':  {'t': 'binance', 's': 'PAXGUSDT', 'ccxt_s': 'PAXG/USDT:USDT', 'lev': 100.0, 'cat': '貴金屬',   'trade': False},
    'CLU':  {'t': 'stock',   's': 'CL=F',     'lev': 100.0, 'cat': '原油商品', 'trade': False},
    
    # 3. 美股龍頭 (Binance 20x / 僅推播)
    'TSM':  {'t': 'stock',   's': 'TSM',      'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'NVDA': {'t': 'stock',   's': 'NVDA',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'AMD':  {'t': 'stock',   's': 'AMD',      'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'MSFT': {'t': 'stock',   's': 'MSFT',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'AAPL': {'t': 'stock',   's': 'AAPL',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'GOOGL':{'t': 'stock',   's': 'GOOGL',    'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'AMZN': {'t': 'stock',   's': 'AMZN',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'META': {'t': 'stock',   's': 'META',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'TSLA': {'t': 'stock',   's': 'TSLA',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'MU':   {'t': 'stock',   's': 'MU',       'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'GLW':  {'t': 'stock',   's': 'GLW',      'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'SPCX': {'t': 'stock',   's': 'SPCX',     'lev': 20.0,  'cat': '美股代幣', 'trade': False},
    'SNDK': {'t': 'stock',   's': 'SNDK',     'lev': 20.0,  'cat': '美股代幣', 'trade': False}
}

def get_binance_client():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return None
    return ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_API_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

def get_wallet_balance(exchange):
    """取得幣安合約錢包 USDT 可用餘額"""
    try:
        bal = exchange.fetch_balance()
        usdt_free = float(bal['free'].get('USDT', 0.0))
        return usdt_free if usdt_free > 0 else DEFAULT_BALANCE
    except Exception as e:
        print(f"取得合約錢包餘額失敗: {e}")
        return DEFAULT_BALANCE

def execute_binance_order(sym_key, cfg, side, entry_price, sl_price, tp1_price, tp2_price, risk_amount):
    """市價開倉並掛上 SL (100%)、TP1 (50%)、TP2 (50%)"""
    if not cfg.get('trade', False):
        return "未開單: 該標的未開啟實盤功能 (僅推播)"
    
    exchange = get_binance_client()
    if exchange is None:
        return "未開單: 未檢測到 BINANCE_API_KEY / SECRET"

    market_sym = cfg.get('ccxt_s', f"{sym_key}/USDT:USDT")
    try:
        exchange.load_markets()
        market = exchange.market(market_sym)

        # 1. 設定槓桿倍數
        try:
            exchange.set_leverage(int(cfg['lev']), market_sym)
        except Exception as lev_err:
            return f"開單失敗 [設定槓桿錯誤]: {lev_err}"

        # 2. 計算動態名義開倉數量
        sl_pct = abs(entry_price - sl_price) / entry_price
        sl_pct = max(sl_pct, 0.002)
        pos_notional = risk_amount / sl_pct
        raw_qty = pos_notional / entry_price
        
        qty = float(exchange.amount_to_precision(market_sym, raw_qty))
        
        # 幣安最小名義金額防護 (需 >= 5 USDT)
        if qty * entry_price < 5.0:
            return f"未開單: 開倉價值 (${qty * entry_price:.2f} USDT) 低於幣安 5 USDT 限制"

        # 3. 市價開倉
        order_side = 'buy' if side == 'LONG' else 'sell'
        close_side = 'sell' if side == 'LONG' else 'buy'
        
        try:
            entry_res = exchange.create_order(symbol=market_sym, type='market', side=order_side, amount=qty)
            order_id = entry_res.get('id', 'N/A')
        except ccxt.InsufficientFunds as e:
            return f"開單失敗 [合約保證金不足]: {e}"
        except ccxt.ExchangeError as e:
            return f"開單失敗 [交易所拒絕]: {e}"
        except Exception as e:
            return f"開單失敗 [市價下單異常]: {e}"

        # 4. 掛全倉 SL 條件止損單 (Stop-Market / 100% 倉位)
        sl_err_note = ""
        try:
            sl_p_str = float(exchange.price_to_precision(market_sym, sl_price))
            exchange.create_order(
                symbol=market_sym,
                type='STOP_MARKET',
                side=close_side,
                amount=qty,
                params={'stopPrice': sl_p_str, 'reduceOnly': True}
            )
        except Exception as e:
            sl_err_note = f" (SL掛單失敗: {e})"

        # 5. 掛 TP1 條件止盈單 (Take-Profit-Market / 50% 倉位)
        tp1_qty = float(exchange.amount_to_precision(market_sym, qty * 0.5))
        tp_err_note = ""
        if tp1_qty > 0:
            try:
                tp1_p_str = float(exchange.price_to_precision(market_sym, tp1_price))
                exchange.create_order(
                    symbol=market_sym,
                    type='TAKE_PROFIT_MARKET',
                    side=close_side,
                    amount=tp1_qty,
                    params={'stopPrice': tp1_p_str, 'reduceOnly': True}
                )
            except Exception as e:
                tp_err_note += f" (TP1掛單失敗: {e})"

        # 6. 掛 TP2 條件止盈單 (Take-Profit-Market / 剩餘 50% 倉位)
        tp2_qty = float(exchange.amount_to_precision(market_sym, qty - tp1_qty))
        if tp2_qty > 0:
            try:
                tp2_p_str = float(exchange.price_to_precision(market_sym, tp2_price))
                exchange.create_order(
                    symbol=market_sym,
                    type='TAKE_PROFIT_MARKET',
                    side=close_side,
                    amount=tp2_qty,
                    params={'stopPrice': tp2_p_str, 'reduceOnly': True}
                )
            except Exception as e:
                tp_err_note += f" (TP2掛單失敗: {e})"

        return f"✅ 開倉成功 (ID: {order_id}) | SL/TP1/TP2 條件單已全數部署{sl_err_note}{tp_err_note}"
    except Exception as e:
        return f"開單失敗 [底層異常]: {e}"

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
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&limit=100"
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
        print(f"Fetch error {cfg['s']}: {e}")
    return None

def scan_symbol(sym, cfg, current_risk):
    df = get_latest_data(cfg)
    if df is None or len(df) < 60:
        return None, f"{sym:<5} | 休市/無數據"

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
    status_summary = f"{sym:<5} | 現價: {entry_price:8.2f} USDT | EMA: {trend_label} | RSI: {bar['rsi']:4.1f}{market_flag}"

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
        pos_val = current_risk / sl_pct
        lev = cfg['lev']
        margin_req = pos_val / lev

        order_status = execute_binance_order(sym, cfg, side, entry_price, sl, tp1, tp2, current_risk)

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
            'order_status': order_status,
            'rsi': bar['rsi']
        }, status_summary

    return None, status_summary

def main():
    tw_now = pd.to_datetime('now', utc=True).tz_convert('Asia/Taipei')
    
    exchange = get_binance_client()
    wallet_balance = get_wallet_balance(exchange) if exchange else DEFAULT_BALANCE
    current_risk = wallet_balance * RISK_PERCENT

    detected_signals = []
    market_status = []

    for sym, cfg in SYMBOLS.items():
        sig, stat = scan_symbol(sym, cfg, current_risk)
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

            p_fmt = "{:.4f}" if s['entry'] < 1 else "{:.2f}"
            entry_s = p_fmt.format(s['entry'])
            sl_s = p_fmt.format(s['sl'])
            tp1_s = p_fmt.format(s['tp1'])
            tp2_s = p_fmt.format(s['tp2'])
            
            msg = (
                f"{side_tag} **{s['sym']}** (15m 趨勢觸發)\n"
                f"```text\n"
                f"進場時間 : {s['time']} (台灣時間)\n"
                f"進場價格 : ${entry_s} USDT\n"
                f"停損價格 : ${sl_s} USDT (-{s['sl_pct']:.2f}% | 100% 止損)\n"
                f"第一目標 : ${tp1_s} USDT (Fib 0.382 | 50% 止盈)\n"
                f"終極目標 : ${tp2_s} USDT (前波極值 | 50% 止盈)\n"
                f"----------------------------------------------------\n"
                f"合約錢包 : ${wallet_balance:.2f} USDT | 單筆動態風控 1%: ${current_risk:.2f} USDT\n"
                f"各槓桿所需保證金與損耗比:\n"
                f"• 10x  : 押 ${m10:5.2f} USDT | 損耗保證金 {loss10:5.1f}%\n"
                f"• 20x  : 押 ${m20:5.2f} USDT | 損耗保證金 {loss20:5.1f}%\n"
                f"• 50x  : 押 ${m50:5.2f} USDT | 損耗保證金 {loss50:5.1f}%\n"
                f"• 100x : 押 ${m100:5.2f} USDT | 損耗保證金 {loss100:5.1f}%\n"
                f"----------------------------------------------------\n"
                f"實盤執行 : {s['order_status']}\n"
                f"指標數據 : RSI(14) = {s['rsi']:.1f}\n"
                f"```"
            )
            send_discord(msg)
    else:
        status_table = "\n".join(market_status)
        heartbeat_msg = (
            f"📡 **[15m 掃描完成] 目前無觸發訊號**\n"
            f"```text\n"
            f"掃描時間: {tw_now.strftime('%H:%M')} (台灣時間) | 標的數: 20 檔\n"
            f"合約錢包: ${wallet_balance:.2f} USDT \vert{} 動態風控: 1\% (${current_risk:.2f} USDT)\n"
            f"----------------------------------------------------\n"
            f"{status_table}\n"
            f"```"
        )
        send_discord(heartbeat_msg)

if __name__ == '__main__':
    main()
