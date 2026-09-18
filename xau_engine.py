"""
XAU/USD Gold Donchian Breakout Engine (Set 1 Reconstruction)
Strategy: 
1. Macro Filter: 1D MA60 Trend Alignment
2. Entry Logic: 4H Close > Donchian(20) High (Long) / Close < Donchian(20) Low (Short)
3. Exit Logic: 
   - SL: Opposite side of Donchian Channel
   - TP1: Entry + 1x Channel Width (Close 50%)
   - TP2: Entry + 2x Channel Width (Close Remaining 50%)
- Capital: $100 | Risk: 1% per trade | 10x Max Leverage
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. Webhook 與交易配置 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.01  # 第一套使用 1% 風險
FEE_RATE = 0.0004
MAX_LEVERAGE = 10.0

def format_full_num(val, max_dec=2):
    try:
        f = float(val)
        return ("{:.%df}" % max_dec).format(f).rstrip('0').rstrip('.')
    except Exception:
        return str(val)

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

# ==================== 2. 數據獲取與指標模組 ====================
def fetch_donchian_data(days=365):
    try:
        period_str = str(days + 90) + "d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        # 1. 獲取 1H 數據並重採樣至 4H (對齊第三套格式)
        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        df_4h = df_1h.set_index('time').resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 2. 獲取 1D 日線 MA60 (宏觀過濾)
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

        # 3. 映射日線趨勢至 4H
        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)

        # 4. 計算唐奇安通道 (Donchian Channel 20)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()

        return df_4h
    except Exception as e:
        print("[!] 數據抓取失敗: " + str(e))
        return None

# ==================== 3. 撮合回測引擎 ====================
def simulate_donchian_v1(df):
    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []

    for i in range(1, len(df)):
        bar = df.iloc[i]

        # 1. 持倉處理
        if pos is not None:
            side, entry, sl, tp1, tp2, qty, is_tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], 
                pos['tp2'], pos['qty'], pos['is_tp1_hit']
            )

            if side == 'LONG':
                # 觸發 TP1 (1x Range) -> 平倉 50%
                if not is_tp1_hit and bar['h'] >= tp1:
                    half_qty = qty * 0.5
                    pnl_half = half_qty * (tp1 - entry) - half_qty * (entry + tp1) * FEE_RATE
                    wallet += pnl_half
                    pos['qty'] = qty * 0.5
                    pos['is_tp1_hit'] = True

                # 觸發止損 (跌破通道低點)
                if bar['l'] <= sl:
                    rem_qty = pos['qty']
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

                # 觸發 TP2 (2x Range) -> 全額止盈
                if bar['h'] >= tp2:
                    rem_qty = pos['qty']
                    pnl = rem_qty * (tp2 - entry) - rem_qty * (entry + tp2) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

            elif side == 'SHORT':
                # 觸發 TP1
                if not is_tp1_hit and bar['l'] <= tp1:
                    half_qty = qty * 0.5
                    pnl_half = half_qty * (entry - tp1) - half_qty * (entry + tp1) * FEE_RATE
                    wallet += pnl_half
                    pos['qty'] = qty * 0.5
                    pos['is_tp1_hit'] = True

                # 觸發止損 (突破通道高點)
                if bar['h'] >= sl:
                    rem_qty = pos['qty']
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

                # 觸發 TP2
                if bar['l'] <= tp2:
                    rem_qty = pos['qty']
                    pnl = rem_qty * (entry - tp2) - rem_qty * (entry + tp2) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

        # 2. 開倉判定
        if pos is None and wallet > 5.0:
            trend = bar['macro_filter']
            
            # 做多: 日線多頭 + 突破 20 週期最高價
            if trend == 1 and bar['c'] > bar['dc_high']:
                entry = bar['c']
                sl = bar['dc_low']
                channel_width = bar['dc_high'] - bar['dc_low']
                if channel_width > 0:
                    tp1 = entry + channel_width
                    tp2 = entry + (channel_width * 2)
                    
                    risk_dist = entry - sl
                    qty = (wallet * RISK_PCT) / risk_dist if risk_dist > 0 else 0
                    if (qty * entry) > (wallet * MAX_LEVERAGE):
                        qty = (wallet * MAX_LEVERAGE) / entry
                    
                    pos = {
                        'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'qty': qty, 'is_tp1_hit': False
                    }

            # 做空: 日線空頭 + 跌破 20 週期最低價
            elif trend == -1 and bar['c'] < bar['dc_low']:
                entry = bar['c']
                sl = bar['dc_high']
                channel_width = bar['dc_high'] - bar['dc_low']
                if channel_width > 0:
                    tp1 = entry - channel_width
                    tp2 = entry - (channel_width * 2)
                    
                    risk_dist = sl - entry
                    qty = (wallet * RISK_PCT) / risk_dist if risk_dist > 0 else 0
                    if (qty * entry) > (wallet * MAX_LEVERAGE):
                        qty = (wallet * MAX_LEVERAGE) / entry
                    
                    pos = {
                        'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'qty': qty, 'is_tp1_hit': False
                    }

    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    return wallet, roi_pct, total_trades, win_rate

# ==================== 4. 主執行程序 ====================
def run_donchian_backtest(days=365):
    period_title = "1 年期" if days >= 365 else str(days) + " 天期"
    df = fetch_donchian_data(days=days)
    if df is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')
    df = df[df['time'] >= start_filter_time].reset_index(drop=True)
    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime('%Y-%m-%d')
    end_date = df.iloc[-1]['time'].strftime('%Y-%m-%d')

    wallet, roi_pct, trades, wr = simulate_donchian_v1(df.copy())

    report_text = (
        "```text\n"
        + "【XAU/USD 黃金 - 唐奇安突破 V1 重製版報表】\n"
        + "核心邏輯: 1D MA60宏觀過濾 + 4H Donchian(20) 突破 + 通道端止損\n"
        + "出場機制: TP1 (1x Range 出50%) / TP2 (2x Range 結清)\n"
        + "回測週期: " + period_title + " (" + str(start_date) + " ~ " + str(end_date) + ")\n"
        + "初始本金: $" + format_full_num(INITIAL_WALLET) + " USD (單筆 1% 風險 / 10x 槓桿)\n"
        + "------------------------------------------------------------\n"
        + "• 最終結餘: $" + format_full_num(wallet, 2) + " USD (" + ("%+0.2f" % roi_pct) + "%)\n"
        + "• 總交易次數: " + str(trades).rjust(2) + " 次 | 勝率: " + ("%5.2f" % wr) + "%\n"
        + "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    # 執行 30 天短週期與 365 天長週期回測
    run_donchian_backtest(days=30)
    time.sleep(2)
    run_donchian_backtest(days=365)
