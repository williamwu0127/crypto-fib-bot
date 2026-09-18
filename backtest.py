import os
import time
import json
import requests
import pandas as pd
import numpy as np
import hmac
import hashlib
import math
from datetime import datetime, timezone, timedelta

# ==================== 1. API 與 Discord 設定 ====================

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

BASE_URL = "https://fapi.binance.com"
TZ_TW = timezone(timedelta(hours=8))
CONTEXT_SNAPSHOT_FILE = "/home/master/entry_context_snapshot.json"

# ==================== 2. 標的配置 ====================
SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_fib',      'lev': 100.0, 'trade': False},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_fib',      'lev': 100.0, 'trade': True},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_fib',      'lev': 20.0,  'trade': True},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_donchian',   'lev': 10.0,  'trade': True},
    'MSFT':  {'t': 'binance', 's': 'MSFTUSDT', 'interval': '1h',  'mode': 'gold_donchian',   'lev': 10.0,  'trade': True},
    'MU':    {'t': 'binance', 's': 'MUUSDT',   'interval': '1h',  'mode': 'gold_donchian',   'lev': 10.0,  'trade': True},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_fib',      'lev': 20.0,  'trade': False},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_fib',      'lev': 20.0,  'trade': False},
    'TSM':   {'t': 'binance', 's': 'TSMUSDT',  'interval': '1h',  'mode': 'gold_donchian',   'lev': 20.0,  'trade': False},
    'NVDA':  {'t': 'binance', 's': 'NVDAUSDT', 'interval': '1h',  'mode': 'gold_donchian',   'lev': 20.0,  'trade': False},
    'AMD':   {'t': 'binance', 's': 'AMDUSDT',  'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'AAPL':  {'t': 'binance', 's': 'AAPLUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'GOOGL': {'t': 'binance', 's': 'GOOGLUSDT','interval': '1h',  'mode': 'stock_pullback',  'lev': 10.0,  'trade': False},
    'AMZN':  {'t': 'binance', 's': 'AMZNUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'META':  {'t': 'binance', 's': 'METAUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'TSLA':  {'t': 'binance', 's': 'TSLAUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'GLW':   {'t': 'binance', 's': 'GLWUSDT',  'interval': '1h',  'mode': 'stock_pullback',  'lev': 20.0,  'trade': False},
    'SPCX':  {'t': 'binance', 's': 'SPCXUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 10.0,  'trade': False},
    'SNDK':  {'t': 'binance', 's': 'SNDKUSDT', 'interval': '1h',  'mode': 'stock_pullback',  'lev': 10.0,  'trade': False}
}

# ==================== 3. 基礎工具與帳戶權益 ====================
def sign_query(params):
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(BINANCE_API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        if abs(f) >= 1000:
            return f"{f:.1f}"
        elif abs(f) >= 1:
            return f"{f:.2f}"
        else:
            return f"{f:.4f}"
    except Exception:
        return str(val)

def get_wallet_balance():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET: return 100.0
    try:
        ts = int(time.time() * 1000)
        qs = sign_query({'timestamp': ts})
        headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
        r = requests.get(f"{BASE_URL}/fapi/v2/account?{qs}", headers=headers, timeout=6).json()
        if isinstance(r, dict):
            if 'totalMarginBalance' in r and float(r['totalMarginBalance']) > 0:
                return float(r['totalMarginBalance'])
            if 'totalWalletBalance' in r:
                return float(r['totalWalletBalance'])
            for a in r.get('assets', []):
                if a['asset'] == 'USDT':
                    return float(a.get('marginBalance', a.get('walletBalance', 100.0)))
    except Exception as e:
        print(f"⚠️ 取得錢包總權益失敗: {e}", flush=True)
    return 100.0

def set_leverage(symbol, target_leverage=100):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET: return target_leverage
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    for lev in [target_leverage, 75, 50, 25, 20, 10, 5]:
        try:
            ts = int(time.time() * 1000)
            qs = sign_query({'symbol': symbol, 'leverage': int(lev), 'timestamp': ts})
            r = requests.post(f"{BASE_URL}/fapi/v1/leverage?{qs}", headers=headers, timeout=6).json()
            if 'leverage' in r:
                print(f"🔧 [調整] {symbol} 槓桿設為 {lev}x", flush=True)
                return int(r['leverage'])
        except Exception:
            pass
    return 10

def get_symbol_filter_rules(symbol):
    qty_step, price_tick, min_qty = 0.001, 0.0001, 0.001
    try:
        ei = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=6).json()
        for s in ei.get('symbols', []):
            if s['symbol'] == symbol:
                for f in s.get('filters', []):
                    if f['filterType'] == 'LOT_SIZE': qty_step = float(f['stepSize'])
                    if f['filterType'] == 'PRICE_FILTER': price_tick = float(f['tickSize'])
                break
    except Exception:
        pass
    return qty_step, price_tick, min_qty

def format_by_step(value, step):
    if step <= 0: return format_full_num(value)
    precision = max(0, int(round(-math.log10(step))))
    rounded = math.floor(float(value) / step) * step
    return f"{rounded:.{precision}f}"

def get_existing_positions():
    if not BINANCE_API_KEY or not BINANCE_API_SECRET: return {}
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
                        'symbol': p['symbol'],
                        'amt': abs(amt),
                        'side': 'LONG' if amt > 0 else 'SHORT',
                        'pos_side': p.get('positionSide', 'LONG' if amt > 0 else 'SHORT'),
                        'entry': float(p.get('entryPrice', 0)),
                        'pnl': float(p.get('unRealizedProfit', 0)),
                        'update_time': int(p.get('updateTime', 0))
                    }
        return pos_dict
    except Exception as e:
        print(f"⚠️ [錯誤] 取得現有倉位失敗: {e}", flush=True)
        return {}

def post_futures_order(params):
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    params['timestamp'] = int(time.time() * 1000)
    qs = sign_query(params)
    try:
        res = requests.post(f"{BASE_URL}/fapi/v1/order?{qs}", headers=headers, timeout=6)
        if res.status_code == 200: return True, "已掛"
        return False, res.json().get('msg', 'Err')
    except Exception as e:
        return False, str(e)

def post_algo_sl_order(symbol, side, pos_side, trigger_price, qty):
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    algo_params = {
        'symbol': symbol, 'side': side, 'positionSide': pos_side,
        'algoType': 'CONDITIONAL', 'type': 'STOP_MARKET',
        'triggerPrice': trigger_price, 'quantity': qty,
        'workingType': 'MARK_PRICE', 'timestamp': int(time.time() * 1000)
    }
    qs = sign_query(algo_params)
    try:
        res = requests.post(f"{BASE_URL}/fapi/v1/algoOrder?{qs}", headers=headers, timeout=6)
        if res.status_code == 200: return True, "已掛"
        return False, res.json().get('msg', 'Err')
    except Exception as e:
        return False, str(e)

# ==================== 4. 下單執行模組 ====================
def place_binance_trade(raw_symbol, side, entry_price, sl_price, tp1_price, tp2_price, wallet_balance, target_lev):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET: return "僅推播"
    
    current_positions = get_existing_positions()
    if raw_symbol in current_positions:
        print(f"🛡️ [攔截] {raw_symbol} 已有持倉，略過開單")
        return "略過: 已持倉"

    actual_lev = set_leverage(raw_symbol, int(target_lev))
    notional_value = (wallet_balance * 0.01) * actual_lev
    target_qty = notional_value / entry_price

    if (target_qty * entry_price) < 5.5:
        target_qty = 5.5 / entry_price
    
    qty_step, price_tick, min_qty = get_symbol_filter_rules(raw_symbol)
    qty_str = format_by_step(target_qty, qty_step)
    
    sl_str = format_by_step(sl_price, price_tick)
    tp1_str = format_by_step(tp1_price, price_tick)
    tp2_str = format_by_step(tp2_price, price_tick)

    pos_side = 'LONG' if side == 'BUY' else 'SHORT'
    opp_side = 'SELL' if side == 'BUY' else 'BUY'

    print(f"🚀 [開倉] 發送市價單 {raw_symbol} {side} {qty_str}...")
    ok_market, res_market = post_futures_order({
        'symbol': raw_symbol, 'side': side, 'positionSide': pos_side, 'type': 'MARKET', 'quantity': qty_str
    })
    if not ok_market: return f"市價失敗: {res_market}"
        
    logs = []
    ok_sl, msg_sl = post_algo_sl_order(raw_symbol, opp_side, pos_side, sl_str, qty_str)
    logs.append(f"SL{msg_sl if ok_sl else '失敗'}")

    half_qty_val = float(qty_str) / 2
    if half_qty_val >= min_qty:
        half_1 = format_by_step(half_qty_val, qty_step)
        half_2 = format_by_step(float(qty_str) - float(half_1), qty_step)
        ok_tp1, msg_tp1 = post_futures_order({'symbol': raw_symbol, 'side': opp_side, 'positionSide': pos_side, 'type': 'LIMIT', 'price': tp1_str, 'quantity': half_1, 'timeInForce': 'GTC'})
        logs.append(f"TP1{msg_tp1 if ok_tp1 else '失敗'}")
        ok_tp2, msg_tp2 = post_futures_order({'symbol': raw_symbol, 'side': opp_side, 'positionSide': pos_side, 'type': 'LIMIT', 'price': tp2_str, 'quantity': half_2, 'timeInForce': 'GTC'})
        logs.append(f"TP2{msg_tp2 if ok_tp2 else '失敗'}")
    else:
        ok_tp1, msg_tp1 = post_futures_order({'symbol': raw_symbol, 'side': opp_side, 'positionSide': pos_side, 'type': 'LIMIT', 'price': tp1_str, 'quantity': qty_str, 'timeInForce': 'GTC'})
        logs.append(f"TP1{msg_tp1 if ok_tp1 else '失敗'}")

    snapshots = load_context_snapshots()
    snapshots[raw_symbol] = {'is_system_order': True, 'entry_time': int(time.time() * 1000)}
    save_context_snapshots(snapshots)
    print(f"✅ [完成] {raw_symbol} 附單已佈署")

    return f"開單成功 ({actual_lev}x | 數量: {qty_str}) 附單: {'|'.join(logs)}"

def get_market_data(cfg, limit=120):
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={cfg['interval']}&limit={limit}"
        res = requests.get(url, timeout=10).json()
        if isinstance(res, list) and len(res) >= 30:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(res, columns=cols)
            for col in ['o', 'h', 'l', 'c', 'v']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms')
            return df[['time', 'o', 'h', 'l', 'c', 'v']]
    except Exception as e:
        print(f"⚠️ [錯誤] {cfg['s']} 行情獲取失敗: {e}", flush=True)
    return None

def prepare_indicators(df, mode):
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()
    
    if mode == 'gold_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
    return df

def send_discord_safe(content):
    if not DISCORD_WEBHOOK_URL: return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=8)
    except Exception as e:
        print(f"⚠️ Discord 推播失敗: {e}")

def load_context_snapshots():
    if os.path.exists(CONTEXT_SNAPSHOT_FILE):
        try:
            with open(CONTEXT_SNAPSHOT_FILE, 'r') as f: return json.load(f)
        except Exception: return {}
    return {}

def save_context_snapshots(snapshots):
    try:
        with open(CONTEXT_SNAPSHOT_FILE, 'w') as f: json.dump(snapshots, f, indent=2)
    except Exception: pass

def format_holding_duration(update_time_ms):
    if not update_time_ms or update_time_ms <= 0: return "未知"
    diff_sec = max(0, int(time.time() - (update_time_ms / 1000)))
    hours, minutes = diff_sec // 3600, (diff_sec % 3600) // 60
    if hours > 24: return f"{hours // 24}天{hours % 24}小時"
    elif hours > 0: return f"{hours}小時{minutes}分"
    return f"{minutes}分鐘"

def evaluate_position_health(pos_data, df, cfg):
    """根據策略模式與即時 K 線，給出倉位健康度評估標籤"""
    bar = df.iloc[-1]
    side = pos_data['side']
    mode = cfg['mode']
    
    if mode == 'gold_donchian':
        if side == 'LONG':
            return "🟢 [健康續抱] 4H 唐奇安多頭中" if bar['c'] >= pos_data['entry'] else "🟡 [震盪回測] 通道內整理"
        else:
            return "🟢 [健康續抱] 4H 唐奇安空頭中" if bar['c'] <= pos_data['entry'] else "🟡 [震盪回測] 通道內整理"
            
    elif mode == 'crypto_fib':
        if side == 'LONG':
            if bar['c'] < bar['ema50']:
                return "🔴 [結構破壞] 跌破 EMA50 防守線"
            elif bar['rsi'] < 45:
                return "🟡 [動能轉弱] RSI 動能衰退"
            else:
                return "🟢 [健康續抱] 多頭結構完整"
        else:
            if bar['c'] > bar['ema50']:
                return "🔴 [結構破壞] 突破 EMA50 防守線"
            elif bar['rsi'] > 55:
                return "🟡 [動能轉弱] RSI 動能衰退"
            else:
                return "🟢 [健康續抱] 空頭結構完整"
                
    elif mode == 'stock_pullback':
        if side == 'LONG':
            if bar['c'] < bar['ema50']: return "🔴 [結構破壞] 跌破 EMA50"
            if bar['c'] < bar['ema20']: return "🟡 [動能轉弱] 價格落入短均線下"
            return "🟢 [健康續抱] 均線多頭排列"
        else:
            if bar['c'] > bar['ema50']: return "🔴 [結構破壞] 突破 EMA50"
            if bar['c'] > bar['ema20']: return "🟡 [動能轉弱] 價格站上短均線上"
            return "🟢 [健康續抱] 均線空頭排列"
            
    return "🟢 [狀態監控中]"

# ==================== 5. 主流程與終端機步驟回報 ====================
def scan_signals():
    now_tw = datetime.now(TZ_TW)
    now_str = now_tw.strftime("%H:%M")
    is_report_time = (now_tw.minute % 15 == 0)

    print("=" * 65)
    print(f"🔄 [系統] 啟動實盤掃描 | {now_tw.strftime('%Y-%m-%d %H:%M:%S')} (發送報表: {is_report_time})")
    
    wallet_balance = get_wallet_balance()
    print(f"💰 [資金] 當前合約總權益: {wallet_balance:.2f} USDT")
    
    existing_pos = get_existing_positions()
    snapshots = load_context_snapshots()
    for k in list(snapshots.keys()):
        if k not in existing_pos: del snapshots[k]
    save_context_snapshots(snapshots)

    summary_lines = []
    trade_signals = []
    processed_dfs = {}

    print("-" * 65)
    for sym, cfg in SYMBOLS.items():
        print(f"🔍 [掃描] 正在獲取 {sym} ({cfg['interval']}) 數據...")
        df = get_market_data(cfg, limit=100)
        if df is None or len(df) < 30:
            summary_lines.append(f"{sym:<5} | 現價: {'N/A':>8} USDT | 狀態: 資料不足")
            continue

        df = prepare_indicators(df, cfg['mode'])
        processed_dfs[sym] = df
        bar = df.iloc[-1]
        mode = cfg['mode']
        p_str = format_full_num(bar['c'])
        sig_side, entry, sl, tp1, tp2 = None, 0, 0, 0, 0
        status_str = ""

        if mode == 'gold_donchian':
            df_1d = get_market_data({'s': cfg['s'], 'interval': '1d'}, limit=60)
            if df_1d is not None and len(df_1d) >= 60:
                df_1d['ma60'] = df_1d['c'].rolling(60).mean()
                macro_trend = 1 if df_1d.iloc[-1]['c'] > df_1d.iloc[-1]['ma60'] else -1
            else:
                macro_trend = 1 if bar['c'] > bar['ema200'] else -1

            macro_dir = '多' if macro_trend == 1 else '空'
            status_str = f"日線: {macro_dir} | DC: {bar['dc_low']:.0f}~{bar['dc_high']:.0f}"
            print(f"   └ 狀態: {status_str}")
            
            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side, entry = 'BUY', bar['c']
                sl = bar['dc_low']
                tp1 = bar['dc_high'] + (bar['dc_high'] - bar['dc_low'])
                tp2 = bar['dc_high'] + ((bar['dc_high'] - bar['dc_low']) * 2)
            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side, entry = 'SELL', bar['c']
                sl = bar['dc_high']
                tp1 = bar['dc_low'] - (bar['dc_high'] - bar['dc_low'])
                tp2 = bar['dc_low'] - ((bar['dc_high'] - bar['dc_low']) * 2)

        elif mode == 'crypto_fib':
            status_str = "狀態: 策略掃描中"
            print(f"   └ {status_str}")
            
            sub = df.iloc[-26:]
            h, l = sub['h'].max(), sub['l'].min()
            wave = h - l
            if wave > 0 and (wave / l) >= 0.005:
                fib_0618_l = h - (wave * 0.618)
                fib_0618_s = l + (wave * 0.618)
                if bar['c'] >= bar['ema50'] >= bar['ema200'] and bar['l'] <= fib_0618_l * 1.002:
                    sig_side, entry = 'BUY', bar['c']
                    sl = l
                    tp1 = h
                    tp2 = h + (wave * 0.272)
                elif bar['c'] <= bar['ema50'] <= bar['ema200'] and bar['h'] >= fib_0618_s * 0.998:
                    sig_side, entry = 'SELL', bar['c']
                    sl = h
                    tp1 = l
                    tp2 = l - (wave * 0.272)

        elif mode == 'stock_pullback':
            status_str = "狀態: 觀測中"
            print(f"   └ 狀態: 觀測中")

        summary_lines.append(f"{sym:<5} | 現價: {p_str:>8} USDT | {status_str}")

        if sig_side and cfg['trade']:
            if cfg['s'] not in existing_pos:
                print(f"⚠️ [觸發] {sym} 滿足進場條件 ({sig_side})")
                exec_status = place_binance_trade(cfg['s'], 'BUY' if sig_side=='LONG' else 'SELL', entry, sl, tp1, tp2, wallet_balance, cfg['lev'])
                side_txt = "📈多" if sig_side == 'LONG' else "📉空"
                trade_signals.append(
                    f"🔥 **【系統開單】** {side_txt} {sym}\n"
                    f"進場: ${format_full_num(entry)} | 結構止損: ${format_full_num(sl)} | 目標TP: ${format_full_num(tp1)}\n"
                    f"狀態: {exec_status}"
                )

    # ---------------- 持倉健康監控與版面 ----------------
    pos_report = []
    if existing_pos:
        for sym_k, p_data in existing_pos.items():
            side_tag = "📈多" if p_data['side'] == 'LONG' else "📉空"
            entry_str = format_full_num(p_data['entry'])
            
            pnl_sign = '+' if p_data['pnl'] >= 0 else ''
            pnl_str = f"{pnl_sign}{p_data['pnl']:.2f}"
            duration_str = format_holding_duration(p_data.get('update_time', 0))
            
            # 尋找對應的標的設定進行健康度診斷
            matched_sym_key = next((k for k, v in SYMBOLS.items() if v['s'] == sym_k), None)
            is_system = sym_k in snapshots and snapshots[sym_k].get('is_system_order', False)
            
            if is_system and matched_sym_key and matched_sym_key in processed_dfs:
                status_note = evaluate_position_health(p_data, processed_dfs[matched_sym_key], SYMBOLS[matched_sym_key])
            else:
                status_note = "🟡 [手動開單] 僅提示結構狀態，不介入動作"

            pos_report.append(
                f"{side_tag} {sym_k} | 開倉價: {entry_str} | 未實現盈虧: {pnl_str} USDT\n"
                f"   └ {status_note} | 持倉時間: {duration_str}"
            )
    else:
        print("📁 [持倉] 當前無持倉")

    # ---------------- Discord 版面輸出 ----------------
    if is_report_time:
        sep_line = "-" * 52
        header_block = (
            f"掃描時間: {now_str} (台灣時間) | 標的數: {len(SYMBOLS)} 檔\n"
            f"合約總權益: {wallet_balance:.2f} USDT\n"
            f"實盤交易標的: ETH, SOL, XAU, MSFT, MU\n"
            f"手動開單保護: 已啟用 (手動倉位僅提示不介入)\n"
            f"{sep_line}"
        )

        full_report = (
            "```text\n"
            + header_block + "\n"
            + "\n".join(summary_lines) + "\n"
            "```\n"
            + "🔥 **【當前實盤持倉監控】**\n"
            + ("\n".join(pos_report) if pos_report else "當前無觸發新單。")
            + ("\n\n" + "\n".join(trade_signals) if trade_signals else "\n\n當前無觸發新單。")
        )
        print("📤 [網路] 正在推播 Discord 報表...")
        send_discord_safe(full_report)
        print("✅ [完成] 報表已發送")
    else:
        print("⏳ [跳過] 非 15 分鐘節點，僅完成背景結構檢查")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    scan_signals()
