"""
XAU/USD (Gold) Dedicated 100x Leverage & 5% Risk Backtest Engine
Strategy: 1D Trend Filter + 4H Donchian Trend Breakout + 1.5 ATR SL + 1:5.0 High RR
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
RISK_PCT = 0.05        # 單筆風險拉至 5%
FEE_RATE = 0.0004      # 黃金現貨/期貨綜合滑價與手續費 (萬分之四)
MAX_LEVERAGE = 100.0   # 支援最高 100 倍名義槓桿上限

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

# ==================== 2. 數據抓取與指標計算 ====================
def fetch_gold_data(days=365):
    try:
        period_str = f"{days + 90}d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")
        
        # 1. 抓取 1H 並重採樣合成 4H K 線
        df_1h = ticker.history(period=period_str, interval="1h")
        if df_1h.empty:
            return None, None
            
        df_1h = df_1h.reset_index()
        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        
        df_1h.set_index('time', inplace=True)
        df_4h = df_1h.resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 2. 抓取日線數據
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)

        return df_4h[['time', 'o', 'h', 'l', 'c', 'v']], df_1d[['time', 'o', 'h', 'l', 'c', 'v']]
    except Exception as e:
        print(f"[!] 黃金數據拉取失敗: {e}")
        return None, None

def prepare_indicators(df_4h, df_1d):
    # 1. 日線 MA60 大趨勢濾網
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)
    
    df_4h['daily_date'] = df_4h['time'].dt.floor('D')
    df_1d['daily_date'] = df_1d['time'].dt.floor('D')
    daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
    df_4h['macro_filter'] = df_4h['daily_date'].map(daily_map).ffill().fillna(0)

    # 2. 4H 唐奇安通道 (前 20 期極值)
    df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
    df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()

    # 3. 4H ATR(14) 計算
    tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
    df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

    return df_4h

# ==================== 3. 撮合回測程序 ====================
def run_gold_100x_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【XAU/USD 現貨黃金 (100倍槓桿 + 5%風控 + 1:5.0 RR)】{period_title}回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USD | 風報比: 1:5.0 (2.0R保本) | 槓桿上限: {MAX_LEVERAGE}x")
    print("=" * 65 + "\n")

    df_4h, df_1d = fetch_gold_data(days=days)
    if df_4h is None or len(df_4h) < 60:
        print("[!] 無法獲取足夠的黃金歷史走勢數據。")
        return

    df = prepare_indicators(df_4h, df_1d)
    
    # 截取回測區間
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')
    df = df[df['time'] >= start_filter_time].reset_index(drop=True)

    if df.empty:
        print("[!] 該回測區間內無 K 線資料。")
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    current_wallet = float(INITIAL_WALLET)
    position = None
    completed_trades = []

    for idx in range(1, len(df)):
        bar = df.iloc[idx]

        # 1. 持倉狀態檢查 (2.0R 移保本，5.0R 止盈)
        if position is not None:
            side = position['side']
            entry = position['entry']
            tp = position['tp']
            be_target = position['be_target']
            qty = position['qty']
            is_be_moved = position['is_be_moved']

            if side == 'LONG':
                if not is_be_moved and bar['h'] >= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                if bar['l'] <= position['sl']:
                    exit_price = position['sl']
                    pnl = qty * (exit_price - entry) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                    position = None
                    continue

                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'TP (5.0R)', 'time': bar['time']})
                    position = None
                    continue

            elif side == 'SHORT':
                if not is_be_moved and bar['l'] <= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                if bar['h'] >= position['sl']:
                    exit_price = position['sl']
                    pnl = qty * (entry - exit_price) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                    position = None
                    continue

                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP (5.0R)', 'time': bar['time']})
                    position = None
                    continue

        # 2. 開倉判定 (4H Donchian 突破)
        if position is None and current_wallet > 5.0:
            macro_trend = bar['macro_filter']
            sig_side = None
            entry, sl, tp, be_target = 0.0, 0.0, 0.0, 0.0

            # 多頭突破
            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_target = entry + (risk_dist * 2.0)
                tp = entry + (risk_dist * 5.0)

            # 空頭跌破
            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_target = entry - (risk_dist * 2.0)
                tp = entry - (risk_dist * 5.0)

            if sig_side and risk_dist > 0:
                qty = (current_wallet * RISK_PCT) / risk_dist
                # 100 倍槓桿保護上限
                if (qty * entry) > (current_wallet * MAX_LEVERAGE):
                    qty = (current_wallet * MAX_LEVERAGE) / entry

                position = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_target, 'is_be_moved': False, 'qty': qty
                }

    # 輸出報表
    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金專屬 (100x槓桿 + 5%風控 + 1:5.0 RR)】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USD\n"
        f"最終結餘: ${format_full_num(current_wallet, 2)} USD ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 策略勝率: {win_rate:.2f}%\n"
        f"單筆風險: {RISK_PCT*100}% | 風報比: 1:5.0 (2.0R保本)\n"
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    # 執行 1 個月 (30天) 回測
    run_gold_100x_backtest(days=30)
    time.sleep(2)
    # 執行 1 年 (365天) 回測
    run_gold_100x_backtest(days=365)
