import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import hmac
import hashlib
import math
from datetime import datetime, timezone, timedelta

# Binance & Discord Setup
BINANCE_API_KEY = "JfNAskj9UacTumBXxlQ6eB4JZpYgLaHQXhWnSSmoRWmM3cw5h15mH7H5tnhPb91Z"
BINANCE_API_SECRET = "dHQPbgX70J1wffzL5TkSf1xquppT9FCUGyKJL9FgI0F7EzjdYy8W9eePQeL6mVTJ"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"

BASE_URL = "https://fapi.binance.com"
TZ_TW = timezone(timedelta(hours=8))

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'lev': 100.0, 'trade': True},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'lev': 100.0, 'trade': True},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'lev': 100.0, 'trade': True},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'lev': 100.0, 'trade': True},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'lev': 100.0, 'trade': True},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'lev': 100.0, 'trade': True},
    'CLU':   {'t': 'stock',   's': 'CL=F',     'lev': 100.0, 'trade': True},
    'TSM':   {'t': 'stock',   's': 'TSM',      'lev': 20.0,  'trade': True},
    'NVDA':  {'t': 'stock',   's': 'NVDA',     'lev': 20.0,  'trade': True},
    'AMD':   {'t': 'stock',   's': 'AMD',      'lev': 20.0,  'trade': True},
    'MSFT':  {'t': 'stock',   's': 'MSFT',     'lev': 20.0,  'trade': True},
    'AAPL':  {'t': 'stock',   's': 'AAPL',     'lev': 20.0,  'trade': True},
    'GOOGL': {'t': 'stock',   's': 'GOOGL',    'lev': 20.0,  'trade': True},
    'AMZN':  {'t': 'stock',   's': 'AMZN',     'lev': 20.0,  'trade': True},
    'META':  {'t': 'stock',   's': 'META',     'lev': 20.0,  'trade': True},
    'TSLA':  {'t': 'stock',   's': 'TSLA',     'lev': 20.0,  'trade': True},
    'MU':    {'t': 'stock',   's': 'MU',       'lev': 20.0,  'trade': True},
    'GLW':   {'t': 'stock',   's': 'GLW',      'lev': 20.0,  'trade': True},
    'SPCX':  {'t': 'stock',   's': 'SPCX',     'lev': 20.0,  'trade': True},
    'SNDK':  {'t': 'stock',   's': 'SNDK',     'lev': 20.0,  'trade': True}
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

def get_symbol_filter_rules(symbol):
    qty_step = 0.01
    price_tick = 0.01
    min_qty = 0.01
    try:
        ei = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=6).json()
        for s in ei.get('symbols', []):
            if s['symbol'] == symbol:
                for f in s.get('filters', []):
                    if f['filterType'] == 'LOT_SIZE':
                        qty_step = float(f['stepSize'])
                        min_qty = float(f.get('minQty', 0.01))
                    if f['filterType'] == 'PRICE_FILTER':
                        price_tick = float(f['tickSize'])
                break
    except Exception:
        pass
    return qty_step, price_tick, min_qty

def format_by_step(value, step):
    if step <= 0:
        return str(value)
    precision = max(0, int(round(-math.log10(step))))
    rounded = math.floor(float(value) / step) * step
    return f"{rounded:.{precision}f}"

def get_existing_positions():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return {}
    try:
        headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
        ts = int(time.time() * 1000)
        qs = sign_query({'timestamp': ts})
        pos_res = requests.get(f"{BASE_URL}/fapi/v2/positionRisk?{qs}", headers=headers, timeout=6).json()
        
        pos_dict = {}
        if isinstance(pos_res, list):
            for p in pos_res:
                amt = float(p.get('positionAmt', 0))
                if abs(amt) > 0:
                    pos_dict[p['symbol']] = {
                        'amt': abs(amt),
                        'side': 'LONG' if amt > 0 else 'SHORT',
                        'pos_side': p.get('positionSide', 'LONG' if amt > 0 else 'SHORT'),
                        'entry': float(p.get('entryPrice', 0)),
                        'pnl': float(p.get('unRealizedProfit', 0))
                    }
        return pos_dict
    except Exception:
        return {}

# 標準限價/市價下單
def post_futures_order(params):
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    ts = int(time.time() * 1000)
    params['timestamp'] = ts
    qs = sign_query(params)
    try:
        res = requests.post(f"{BASE_URL}/fapi/v1/order?{qs}", headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if 'orderId' in data:
                return True, "已掛"
            return False, data.get('msg', 'Err')
        else:
            try:
                err_data = res.json()
                return False, err_data.get('msg', f"HTTP {res.status_code}")
            except Exception:
                return False, f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)

# 幣安最新標準 AlgoOrder 條件止損
def post_algo_sl_order(symbol, side, pos_side, trigger_price, qty):
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    ts = int(time.time() * 1000)
    
    algo_params = {
        'symbol': symbol,
        'side': side,
        'positionSide': pos_side,
        'algoType': 'CONDITIONAL',
        'type': 'STOP_MARKET',
        'triggerPrice': trigger_price,
        'quantity': qty,
        'workingType': 'MARK_PRICE',
        'timestamp': ts
    }
    qs = sign_query(algo_params)
    try:
        res = requests.post(f"{BASE_URL}/fapi/v1/algoOrder?{qs}", headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if 'algoId' in data or 'clientAlgoId' in data or data.get('code') == 200 or 'orderId' in data:
                return True, "已掛"
            return False, data.get('msg', 'Err')
        else:
            try:
                err_data = res.json()
                return False, err_data.get('msg', f"HTTP {res.status_code}")
            except Exception:
                return False, f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)

def place_binance_trade(raw_symbol, side, entry_price, sl_price, tp1_price, tp2_price, wallet_balance, target_lev=100):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return "僅推播 (未設定 API Key)"
    
    clean_sym = raw_symbol.replace("=F", "")
    binance_symbol = clean_sym if clean_sym.endswith("USDT") else f"{clean_sym}USDT"
    
    # 嚴格防重開
    current_positions = get_existing_positions()
    if binance_symbol in current_positions:
        return f"已略過: 目前已持有 {binance_symbol} (數量: {current_positions[binance_symbol]['amt']})"

    actual_lev = set_leverage(binance_symbol, int(target_lev))
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
    
    qty_step, price_tick, min_qty = get_symbol_filter_rules(binance_symbol)
    
    qty_str = format_by_step(target_qty, qty_step)
    actual_total_qty = float(qty_str)
    
    half_qty_val = actual_total_qty / 2
    if half_qty_val < min_qty:
        half_1 = qty_str
        half_2 = "0"
    else:
        half_1 = format_by_step(half_qty_val, qty_step)
        half_2 = format_by_step(actual_total_qty - float(half_1), qty_step)
    
    sl_str = format_by_step(sl_price, price_tick)
    tp1_str = format_by_step(tp1_price, price_tick)
    tp2_str = format_by_step(tp2_price, price_tick)

    pos_side = 'LONG' if side == 'BUY' else 'SHORT'
    
    # 1. 市價開倉
    ok_market, res_market = post_futures_order({
        'symbol': binance_symbol,
        'side': side,
        'positionSide': pos_side,
        'type': 'MARKET',
        'quantity': qty_str
    })
    
    if not ok_market:
        return f"市價開單失敗: {res_market}"
        
    opp_side = 'SELL' if side == 'BUY' else 'BUY'
    logs = []

    # 2. 條件止損 (SL)
    ok_sl, msg_sl = post_algo_sl_order(binance_symbol, opp_side, pos_side, sl_str, qty_str)
    logs.append(f"SL{msg_sl if ok_sl else f'失敗({msg_sl})'}")

    # 3. TP1 LIMIT 限價止盈
    ok_tp1, msg_tp1 = post_futures_order({
        'symbol': binance_symbol,
        'side': opp_side,
        'positionSide': pos_side,
        'type': 'LIMIT',
        'price': tp1_str,
        'quantity': half_1,
        'timeInForce': 'GTC'
    })
    logs.append(f"TP1{msg_tp1 if ok_tp1 else f'失敗({msg_tp1})'}")

    # 4. TP2 LIMIT 限價止盈
    if float(half_2) >= min_qty:
        ok_tp2, msg_tp2 = post_futures_order({
            'symbol': binance_symbol,
            'side': opp_side,
            'positionSide': pos_side,
            'type': 'LIMIT',
            'price': tp2_str,
            'quantity': half_2,
            'timeInForce': 'GTC'
        })
        logs.append(f"TP2{msg_tp2 if ok_tp2 else f'失敗({msg_tp2})'}")

    return f"實盤開單成功 ({actual_lev}x | 數量: {qty_str}) -> 附單: {' | '.join(logs)}"

def auto_repair_existing_sl():
    existing_pos = get_existing_positions()
    if not existing_pos:
        return []
    
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    ts = int(time.time() * 1000)
    
    try:
        ord_res = requests.get(f"{BASE_URL}/fapi/v1/openOrders?{sign_query({'timestamp': ts})}", headers=headers, timeout=6).json()
        all_orders = ord_res if isinstance(ord_res, list) else []
    except Exception:
        all_orders = []

    try:
        ts2 = int(time.time() * 1000)
        algo_res = requests.get(f"{BASE_URL}/fapi/v1/openAlgoOrders?{sign_query({'timestamp': ts2})}", headers=headers, timeout=6).json()
        if isinstance(algo_res, dict) and 'orders' in algo_res:
            all_orders.extend(algo_res['orders'])
        elif isinstance(algo_res, list):
            all_orders.extend(algo_res)
    except Exception:
        pass
    
    repair_logs = []
    for sym, p_info in existing_pos.items():
        has_sl = any(o.get('symbol') == sym and 'STOP' in str(o.get('type') or o.get('algoType') or o.get('orderType', '')) for o in all_orders)
        if not has_sl:
            qty_step, price_tick, _ = get_symbol_filter_rules(sym)
            sl_p = p_info['entry'] * 0.985 if p_info['side'] == 'LONG' else p_info['entry'] * 1.015
            sl_str = format_by_step(sl_p, price_tick)
            qty_str = format_by_step(p_info['amt'], qty_step)
            opp_side = 'SELL' if p_info['side'] == 'LONG' else 'BUY'
            
            ok, msg = post_algo_sl_order(sym, opp_side, p_info['pos_side'], sl_str, qty_str)
            if ok:
                repair_logs.append(f"🛡️ 已為 **{sym}** 自動補掛保底止損價: ${sl_str}")
    return repair_logs

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

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        if len(content) <= 1900:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
        else:
            parts = [content[i:i+1800] for i in range(0, len(content), 1800)]
            for p in parts:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": p}, timeout=8)
                time.sleep(0.5)
    except Exception:
        pass

def scan_signals():
    print(">>> 開始掃描 20 檔標的...")
    wallet_balance = get_wallet_balance()
    risk_amount = wallet_balance * 0.01
    now_tw = datetime.now(TZ_TW)
    now_str = now_tw.strftime("%H:%M")
    
    repair_logs = auto_repair_existing_sl()
    summary_lines = []
    trade_signals = []

    for sym, cfg in SYMBOLS.items():
        print(f"正在分析: {sym}...")
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
        summary_lines.append(f"{sym.ljust(5)} | 現價: {bar['c']:>9.2f} USDT | EMA: {ema_status} | RSI: {bar['rsi']:.1f}")

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
            
            tp1 = h if h > entry else entry + abs(entry - sl)
            tp2 = h + (wave * 0.272)
            if tp2 <= tp1:
                tp2 = tp1 + abs(entry - sl)
            
            exec_status = "僅推播 (未開啟自動開單)"
            if cfg['trade']:
                exec_status = place_binance_trade(cfg['s'], 'BUY', entry, sl, tp1, tp2, wallet_balance, cfg['lev'])
            
            trade_signals.append(
                f"🟢 [LONG / 做多] **{sym}** 實盤開單:\n"
                f"進場時間 : {now_str} (台灣時間)\n"
                f"進場價格 : ${entry:.2f} USDT\n"
                f"停損價格 : ${sl:.2f} USDT\n"
                f"第一止盈 : ${tp1:.2f} USDT\n"
                f"第二止盈 : ${tp2:.2f} USDT\n"
                f"實盤執行 : {exec_status}\n"
                f"指標數據 : RSI(14) = {bar['rsi']:.1f}"
            )

    # 取得最新持倉即時回報
    existing_pos = get_existing_positions()
    pos_report = []
    if existing_pos:
        pos_report.append("📌 **[當前實盤持倉監控]**")
        for sym_k, p_data in existing_pos.items():
            pos_report.append(
                f"• **{sym_k}** ({p_data['side']} {p_data['amt']}) | 開倉價: {p_data['entry']:.2f} | "
                f"未實現盈虧: {p_data['pnl']:+.2f} USDT"
            )
    else:
        pos_report.append("📌 **[當前實盤持倉監控]**\n• 目前無持倉")

    full_report = (
        "📊 **[15m 綜合掃描報告]**\n"
        "```text\n"
        f"掃描時間: {now_str} (台灣時間) | 標的數: 20 檔\n"
        f"合約錢包: {wallet_balance:.2f} USDT | 動態風控: 1% (${risk_amount:.2f} USDT)\n"
        "----------------------------------------------------\n"
        + "\n".join(summary_lines) + "\n"
        "----------------------------------------------------\n"
        "```\n"
        + "\n".join(pos_report) + "\n"
        + ("\n" + "\n".join(repair_logs) + "\n" if repair_logs else "") + "\n"
        + ("\n\n".join(trade_signals) if trade_signals else "當前無觸發新單。")
    )

    print(">>> 正在發送至 Discord...")
    send_discord_safe(full_report)
    print(">>> 完成發送！")

if __name__ == '__main__':
    scan_signals()
