"""
XAU/USD Gold Dedicated Quant Engine (Clean & Production-Ready)
Strategy: 1D MA60 Macro + 4H Donchian(20) Breakout + 1.5 ATR SL -> 2.0R BE -> 5.0R TP
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ==================== 1. 核心參數與 Webhook ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0  # 初始本金
RISK_PCT = 0.05         # 單筆風險 5%
FEE_RATE = 0.0004       # 點差與手續費 (萬分之四)
MAX_LEVERAGE = 10.0     # 槓桿上限 10x

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

# ==================== 2. 數據獲取與指標計算 ====================
def get_gold_dataframe(days=365):
    period = f"{days + 90}d" if days <= 600 else "2y"
    ticker = yf.Ticker("GC=F")

    # 1. 抓取 1H 並重採樣為 4H K 線
    df_1h = ticker.history(period=period, interval="1h").reset_index()
    if df_1h.empty:
        return None
    date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
    df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
    df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
    df_4h = df_1h.set_index('time').resample('4h').agg({
        'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
    }).dropna().reset_index()

    # 2. 抓取 1D 日線計算 MA60 大趨勢
    df_1d = ticker.history(period=period, interval="1d").reset_index()
    date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
    df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
    df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
    df_1d['ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

    # 3. 對齊宏觀濾網
    df_4h['d_date'] = df_4h['time'].dt.floor('D')
    df_1d['d_date'] = df_1d['time'].dt.floor('D')
    d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
    df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)

    # 4. 4H 唐奇安通道(20) & ATR(14)
    df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
    df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
    tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
    df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

    return df_4h

# ==================== 3. 撮合回測主引擎 ====================
def run_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    df = get_gold_dataframe(days)
    if df is None:
        print("[!] 獲取黃金數據失敗")
        return

    # 截取指定天數區間
    start_time = pd.to_datetime(int(time.time() * 1000) - (days * 86400000), unit='ms')
    df = df[df['time'] >= start_time].reset_index(drop=True)
    if df.empty:
        return

    wallet = float(INITIAL_WALLET)
    pos = None
    trades = []

    for i in range(1, len(df)):
        bar = df.iloc[i]

        # 1. 持倉處理 (2.0R 移保本 / 5.0R 止盈 / 止損出場)
        if pos is not None:
            side, entry, sl, tp, be_tgt, qty, be_done = (
                pos['side'], pos['entry'], pos['sl'], pos['tp'],
                pos['be_target'], pos['qty'], pos['is_be_moved']
            )

            # 多頭檢查
            if side == 'LONG':
                if not be_done and bar['h'] >= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True

                if bar['l'] <= pos['sl']:
                    pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

            # 空頭檢查
            elif side == 'SHORT':
                if not be_done and bar['l'] <= be_tgt:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True

                if bar['h'] >= pos['sl']:
                    pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                    wallet += pnl
                    trades.append(pnl)
                    pos = None
                    continue

        # 2. 開倉判定 (4H 突破 Donchian + 1.5 ATR 止損)
        if pos is None and wallet > 5.0:
            trend = bar['macro_filter']
            sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

            if trend == 1 and bar['c'] > bar['dc_high']:  # 多頭突破
                sig, entry = 'LONG', bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_tgt = entry + (risk_dist * 2.0)
                tp = entry + (risk_dist * 5.0)

            elif trend == -1 and bar['c'] < bar['dc_low']:  # 空頭跌破
                sig, entry = 'SHORT', bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_tgt = entry - (risk_dist * 2.0)
                tp = entry - (risk_dist * 5.0)

            if sig and risk_dist > 0:
                qty = (wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (wallet * MAX_LEVERAGE):
                    qty = (wallet * MAX_LEVERAGE) / entry
                pos = {
                    'side': sig, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                }

    # 3. 輸出報表
    total_trades = len(trades)
    win_trades = sum(1 for p in trades if p > 0)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    report = (
        "```text\n"
        "【XAU/USD 現貨黃金專屬 (日線定錨 + Donchian + 1:5.0 RR高賠率版)】\n"
        f"回測週期: {period_title} ({df.iloc[0]['time'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['time'].strftime('%Y-%m-%d')})\n"
        f"初始資金: ${INITIAL_WALLET:.1f} USD\n"
        f"最終結餘: ${wallet:.2f} USD ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 策略勝率: {win_rate:.2f}%\n"
        f"單筆風險: {RISK_PCT*100:.1f}% | 風報比: 1:5.0 (2.0R保本) | 槓桿: 10x\n"
        "```"
    )

    print(report)
    send_discord(report)

# ==================== 4. 執行入口 ====================
if __name__ == '__main__':
    run_backtest(days=30)
    time.sleep(1.5)
    run_backtest(days=365)
