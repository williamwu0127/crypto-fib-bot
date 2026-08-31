"""
XAU/USD (Gold) Unlimited Trend Engine (1D Trend + 4H Donchian + 4H EMA20 Trailing Exit)
Strategy: 2.0R Breakeven -> 3.0R Scale-Out 30% -> Remaining 70% Trail 4H EMA20
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. 設定與風控 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET = 100.0
RISK_PCT = 0.05        # 單筆固定承擔 5% 結構風險
FEE_RATE = 0.0004      # 黃金手續費與點差 (萬分之四)

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

        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)

        return df_4h[['time', 'o', 'h', 'l', 'c', 'v']], df_1d[['time', 'o', 'h', 'l', 'c', 'v']]
    except Exception as e:
        print(f"[!] 數據抓取失敗: {e}")
        return None, None

def prepare_indicators(df_4h, df_1d):
    # 日線 MA60 趨勢定錨
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)
    
    df_4h['daily_date'] = df_4h['time'].dt.floor('D')
    df_1d['daily_date'] = df_1d['time'].dt.floor('D')
    daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
    df_4h['macro_filter'] = df_4h['daily_date'].map(daily_map).ffill().fillna(0)

    # 4H 唐奇安通道與 EMA20 移動追蹤均線
    df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
    df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
    df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()

    # 前 3 根 K 棒波段低高點
    df_4h['swing_low_3'] = df_4h['l'].rolling(3).min()
    df_4h['swing_high_3'] = df_4h['h'].rolling(3).max()

    return df_4h

# ==================== 3. 撮合回測程序 ====================
def run_gold_unlimited_backtest(days=365, leverage=10.0):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【XAU/USD 現貨黃金 (無上限波段版 | 槓桿 {leverage}x)】{period_title}回測")
    print(f">>> 出場規則: 2.0R保本 -> 3.0R平30% -> 剩餘70%追蹤4H EMA20")
    print("=" * 65 + "\n")

    df_4h, df_1d = fetch_gold_data(days=days)
    if df_4h is None or len(df_4h) < 60:
        print("[!] 無法獲取足夠數據。")
        return

    df = prepare_indicators(df_4h, df_1d)
    
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
        prev_bar = df.iloc[idx - 1]

        # 1. 持倉狀態監控
        if position is not None:
            side = position['side']
            entry = position['entry']
            sl = position['sl']
            tp1 = position['tp1']
            be_target = position['be_target']
            qty = position['qty']
            tp1_hit = position['tp1_hit']
            is_be_moved = position['is_be_moved']

            if side == 'LONG':
                # (1) 達 2.0R 移保本
                if not is_be_moved and bar['h'] >= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                # (2) 止損 / 保本損觸發
                if bar['l'] <= position['sl']:
                    exit_price = position['sl']
                    rem_qty = qty * 0.7 if tp1_hit else qty
                    pnl = rem_qty * (exit_price - entry) - (rem_qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                    position = None
                    continue

                # (3) 觸發 3.0R (平倉 30% 鎖利)
                if not tp1_hit and bar['h'] >= tp1:
                    position['tp1_hit'] = True
                    position['sl'] = entry
                    position['is_be_moved'] = True
                    pnl_tp1 = (qty * 0.3) * (tp1 - entry) - ((qty * 0.3) * (entry + tp1) * FEE_RATE)
                    current_wallet += pnl_tp1
                    completed_trades.append({'side': 'LONG', 'pnl': pnl_tp1, 'type': 'TP1 (3.0R 30%)', 'time': bar['time']})

                # (4) 剩餘 70% 追蹤 4H EMA20 離場 (收盤實體跌破 EMA20)
                if position is not None and position['tp1_hit']:
                    if bar['c'] < bar['ema20']:
                        exit_price = bar['c']
                        rem_qty = qty * 0.7
                        pnl_rem = rem_qty * (exit_price - entry) - (rem_qty * (entry + exit_price) * FEE_RATE)
                        current_wallet += pnl_rem
                        completed_trades.append({'side': 'LONG', 'pnl': pnl_rem, 'type': 'EMA20 Trail Exit', 'time': bar['time']})
                        position = None
                        continue

            elif side == 'SHORT':
                if not is_be_moved and bar['l'] <= be_target:
                    position['sl'] = entry
                    position['is_be_moved'] = True

                if bar['h'] >= position['sl']:
                    exit_price = position['sl']
                    rem_qty = qty * 0.7 if tp1_hit else qty
                    pnl = rem_qty * (entry - exit_price) - (rem_qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                    position = None
                    continue

                if not tp1_hit and bar['l'] <= tp1:
                    position['tp1_hit'] = True
                    position['sl'] = entry
                    position['is_be_moved'] = True
                    pnl_tp1 = (qty * 0.3) * (entry - tp1) - ((qty * 0.3) * (entry + tp1) * FEE_RATE)
                    current_wallet += pnl_tp1
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl_tp1, 'type': 'TP1 (3.0R 30%)', 'time': bar['time']})

                if position is not None and position['tp1_hit']:
                    if bar['c'] > bar['ema20']:
                        exit_price = bar['c']
                        rem_qty = qty * 0.7
                        pnl_rem = rem_qty * (entry - exit_price) - (rem_qty * (entry + exit_price) * FEE_RATE)
                        current_wallet += pnl_rem
                        completed_trades.append({'side': 'SHORT', 'pnl': pnl_rem, 'type': 'EMA20 Trail Exit', 'time': bar['time']})
                        position = None
                        continue

        # 2. 開倉判定 (4H 唐奇安突破 + 結構止損)
        if position is None and current_wallet > 5.0:
            macro_trend = bar['macro_filter']
            sig_side = None
            entry, sl, tp1, be_target = 0.0, 0.0, 0.0, 0.0

            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side = 'LONG'
                entry = bar['c']
                structural_low = min(bar['l'], bar['swing_low_3'])
                sl = structural_low * 0.998
                risk_dist = entry - sl
                if risk_dist > 0 and (risk_dist / entry) >= 0.002:
                    be_target = entry + (risk_dist * 2.0)
                    tp1 = entry + (risk_dist * 3.0)  # 3.0R 平 30%
                else:
                    sig_side = None

            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side = 'SHORT'
                entry = bar['c']
                structural_high = max(bar['h'], bar['swing_high_3'])
                sl = structural_high * 1.002
                risk_dist = sl - entry
                if risk_dist > 0 and (risk_dist / entry) >= 0.002:
                    be_target = entry - (risk_dist * 2.0)
                    tp1 = entry - (risk_dist * 3.0)
                else:
                    sig_side = None

            if sig_side and risk_dist > 0:
                qty = (current_wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (current_wallet * leverage):
                    qty = (current_wallet * leverage) / entry

                position = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp1': tp1, 'be_target': be_target,
                    'tp1_hit': False, 'is_be_moved': False, 'qty': qty
                }

    # 輸出績效
    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    report_text = (
        "```text\n"
        f"【XAU/USD 現貨黃金 (無上限波段版 | 槓桿 {leverage}x)】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USD\n"
        f"最終結餘: ${format_full_num(current_wallet, 2)} USD ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 策略勝率: {win_rate:.2f}%\n"
        f"規則: 2.0R保本 -> 3.0R平30% -> 剩餘70%追蹤4H EMA20\n"
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    # 1. 跑 10 倍槓桿 (1 個月與 1 年)
    run_gold_unlimited_backtest(days=30, leverage=10.0)
    time.sleep(2)
    run_gold_unlimited_backtest(days=365, leverage=10.0)
    time.sleep(2)

    # 2. 跑 100 倍槓桿 (1 個月與 1 年)
    run_gold_unlimited_backtest(days=30, leverage=100.0)
    time.sleep(2)
    run_gold_unlimited_backtest(days=365, leverage=100.0)
