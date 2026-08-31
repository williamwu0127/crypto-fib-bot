"""
XAU/USD (Gold) Multi-Timeframe High-Frequency Intraday Quant Engine
Structure: 1D Trend Filter -> 4H & 1H Alignment -> 15m Donchian/ATR Entry
Sessions: London & NY Open (14:30 - 23:30 UTC+8) + EOD Forced Exit at 03:00 UTC+8
Risk: 3% per trade | Discord Push Enabled
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. Webhook 設定 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.03       # 單筆風險 3%
FEE_RATE = 0.0004     # 黃金現貨手續費與點差約萬分之四
MAX_LEVERAGE = 15.0   # 15m 日內最高槓桿保護

def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        return f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
    except Exception:
        return str(val)

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

# ==================== 2. 數據抓取與重採樣 ====================
def fetch_gold_multitimeframe_data(days=365):
    try:
        ticker = yf.Ticker("GC=F")
        period_str = f"{min(days + 60, 700)}d" if days <= 600 else "2y"
        
        # 1. 抓取 15m 基準 K 線
        # 注意: Yahoo Finance 的 15m 數據受限於 60 天內，若超過 60 天請改用 1h 進行長期測試
        fetch_itv = "15m" if days <= 55 else "1h"
        df_base = ticker.history(period=f"{min(days+10, 58)}d" if fetch_itv == "15m" else period_str, interval=fetch_itv)
        
        if df_base.empty:
            return None, None, None, None
            
        df_base = df_base.reset_index()
        date_col = 'Datetime' if 'Datetime' in df_base.columns else 'Date'
        df_base['time'] = pd.to_datetime(df_base[date_col]).dt.tz_localize(None)
        df_base.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_base.set_index('time', inplace=True)

        # 重採樣 1H 與 4H
        df_15m = df_base.resample('15min').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'}).dropna().reset_index()
        df_1h = df_base.resample('1h').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'}).dropna().reset_index()
        df_4h = df_base.resample('4h').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'}).dropna().reset_index()

        # 抓取 1D 日線
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)

        return df_15m, df_1h, df_4h, df_1d
    except Exception as e:
        print(f"[!] 數據拉取異常: {e}")
        return None, None, None, None

# ==================== 3. 指標對齊與計算 ====================
def prepare_indicators(df_15m, df_1h, df_4h, df_1d):
    # 1. 日線 (1D) MA60 趨勢定錨
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['trend_1d'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)
    df_1d['join_date'] = df_1d['time'].dt.floor('D')
    map_1d = df_1d.drop_duplicates('join_date').set_index('join_date')['trend_1d'].to_dict()

    # 2. 4小時 (4H) EMA20 / EMA60 共振確認
    df_4h['ema20_4h'] = df_4h['c'].ewm(span=20, adjust=False).mean()
    df_4h['ema60_4h'] = df_4h['c'].ewm(span=60, adjust=False).mean()
    df_4h['trend_4h'] = np.where(df_4h['ema20_4h'] > df_4h['ema60_4h'], 1, -1)
    df_4h['join_4h'] = df_4h['time'].dt.floor('4h')
    map_4h = df_4h.drop_duplicates('join_4h').set_index('join_4h')['trend_4h'].to_dict()

    # 3. 1小時 (1H) EMA20 / EMA60 共振確認
    df_1h['ema20_1h'] = df_1h['c'].ewm(span=20, adjust=False).mean()
    df_1h['ema60_1h'] = df_1h['c'].ewm(span=60, adjust=False).mean()
    df_1h['trend_1h'] = np.where(df_1h['ema20_1h'] > df_1h['ema60_1h'], 1, -1)
    df_1h['join_1h'] = df_1h['time'].dt.floor('h')
    map_1h = df_1h.drop_duplicates('join_1h').set_index('join_1h')['trend_1h'].to_dict()

    # 4. 15分鐘 (15m) 操作指標 (Donchian 20 + ATR 14)
    df_15m['dc_high'] = df_15m['h'].shift(1).rolling(20).max()
    df_15m['dc_low'] = df_15m['l'].shift(1).rolling(20).min()
    tr = np.maximum(df_15m['h'] - df_15m['l'], np.maximum(abs(df_15m['h'] - df_15m['c'].shift(1)), abs(df_15m['l'] - df_15m['c'].shift(1))))
    df_15m['atr'] = tr.rolling(14).mean().fillna(df_15m['c'] * 0.005)

    # 將大級別信號 map 回 15m
    df_15m['join_date'] = df_15m['time'].dt.floor('D')
    df_15m['join_4h'] = df_15m['time'].dt.floor('4h')
    df_15m['join_1h'] = df_15m['time'].dt.floor('h')

    df_15m['trend_1d'] = df_15m['join_date'].map(map_1d).ffill().fillna(0)
    df_15m['trend_4h'] = df_15m['join_4h'].map(map_4h).ffill().fillna(0)
    df_15m['trend_1h'] = df_15m['join_1h'].map(map_1h).ffill().fillna(0)

    return df_15m

# ==================== 4. 時區過濾與日內結算判定 ====================
def is_trade_window(dt):
    """
    台北時間 (UTC+8) 14:30 ~ 23:30 (對應 UTC 06:30 ~ 15:30)
    """
    # 假設 Yahoo 數據時間為 UTC
    utc_hour = dt.hour + (dt.minute / 60.0)
    # 06:30 <= UTC <= 15:30 即 台北時間 14:30 <= TPE <= 23:30
    return (6.5 <= utc_hour <= 15.5)

def is_eod_exit_time(dt):
    """
    台北時間 (UTC+8) 凌晨 03:00 (對應 UTC 19:00) 進行日內了結
    """
    return (dt.hour == 19 and dt.minute >= 0) or (dt.hour > 19)

# ==================== 5. 主撮合回測程序 ====================
def run_xau_intraday_backtest(days=30):
    period_title = f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【XAU/USD 4重多週期 + 時區過濾 + 日內了結】{period_title}回測")
    print(f">>> 風控比例: {RISK_PCT*100}% | 日內強制結算: 台北 03:00 | 交易視窗: 台北 14:30-23:30")
    print("=" * 65 + "\n")

    df_15m, df_1h, df_4h, df_1d = fetch_gold_multitimeframe_data(days=days)
    if df_15m is None or len(df_15m) < 40:
        print("[!] 數據不足，無法執行回測。")
        return

    df = prepare_indicators(df_15m, df_1h, df_4h, df_1d)
    
    # 截取回測區間
    now_ms = int(time.time() * 1000)
    start_filter = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')
    df = df[df['time'] >= start_filter].reset_index(drop=True)

    if df.empty:
        print("[!] 該區間無可用 K 線。")
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d %H:%M")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d %H:%M")

    current_wallet = float(INITIAL_WALLET)
    position = None
    completed_trades = []

    for idx in range(1, len(df)):
        bar = df.iloc[idx]
        bar_time = bar['time']

        # --- 1. 持倉處理 ---
        if position is not None:
            side = position['side']
            entry = position['entry']
            tp = position['tp']
            be_target = position['be_target']
            qty = position['qty']
            is_be_moved = position['is_be_moved']

            # A. 日內強制結算 (EOD Exit)
            if is_eod_exit_time(bar_time):
                exit_price = bar['c']
                pnl = (qty * (exit_price - entry) if side == 'LONG' else qty * (entry - exit_price)) - (qty * (entry + exit_price) * FEE_RATE)
                current_wallet += pnl
                completed_trades.append({'side': side, 'pnl': pnl, 'type': 'EOD Close', 'time': bar_time})
                position = None
                continue

            # B. 多單出場檢驗
            if side == 'LONG':
                if not is_be_moved and bar['h'] >= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                if bar['l'] <= position['sl']:
                    exit_price = position['sl']
                    pnl = qty * (exit_price - entry) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': bar_time})
                    position = None
                    continue

                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'TP (3.0R)', 'time': bar_time})
                    position = None
                    continue

            # C. 空單出場檢驗
            elif side == 'SHORT':
                if not is_be_moved and bar['l'] <= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                if bar['h'] >= position['sl']:
                    exit_price = position['sl']
                    pnl = qty * (entry - exit_price) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': bar_time})
                    position = None
                    continue

                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP (3.0R)', 'time': bar_time})
                    position = None
                    continue

        # --- 2. 開倉判定 (僅在時區視窗內) ---
        if position is None and current_wallet > 5.0 and is_trade_window(bar_time):
            t_1d = bar['trend_1d']
            t_4h = bar['trend_4h']
            t_1h = bar['trend_1h']

            sig_side = None
            entry, sl, tp, be_target = 0.0, 0.0, 0.0, 0.0

            # 做多共振：1D 看多 + 4H 看多 + 1H 看多 + 15m 突破 Donchian 高點
            if (t_1d == 1 and t_4h == 1 and t_1h == 1) and (bar['c'] > bar['dc_high']):
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (bar['atr'] * 1.5)
                r = entry - sl
                be_target = entry + (r * 1.5)
                tp = entry + (r * 3.0)

            # 做空共振：1D 看空 + 4H 看空 + 1H 看空 + 15m 跌破 Donchian 低點
            elif (t_1d == -1 and t_4h == -1 and t_1h == -1) and (bar['c'] < bar['dc_low']):
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (bar['atr'] * 1.5)
                r = sl - entry
                be_target = entry - (r * 1.5)
                tp = entry - (r * 3.0)

            if sig_side and r > 0:
                qty = (current_wallet * RISK_PCT) / r
                # 槓桿上限限制
                if (qty * entry) > (current_wallet * MAX_LEVERAGE):
                    qty = (current_wallet * MAX_LEVERAGE) / entry

                position = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_target, 'is_be_moved': False, 'qty': qty
                }

    # 輸出績效
    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金高頻日內量化策略】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USD\n"
        f"最終結餘: ${format_full_num(current_wallet, 2)} USD ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 策略勝率: {win_rate:.2f}%\n"
        f"風控設定: 單筆 {RISK_PCT*100}% | 風報比 1:3.0 (1.5R保本) | 台北03:00強制平倉\n"
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    # 執行 30 天 15m 高頻日內回測
    run_xau_intraday_backtest(days=30)
