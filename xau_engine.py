"""
XAU/USD Dual-Track Quant Engine
Track 1 (Swing 4H): 1D MA60 + 4H Donchian(20) | 1.5R BE -> 3.0R TP | 5% Risk ($100 Wallet)
Track 2 (Fast 1H) : 1D MA60 + 1H Donchian(20) | 1.2R BE -> 2.5R TP | 5% Risk ($100 Wallet)
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
RISK_PCT = 0.05        # 單筆承擔 5% 風險
FEE_RATE = 0.0004      # 黃金手續費與點差 (萬分之四)
MAX_LEVERAGE = 10.0    # 10 倍實質槓桿上限

# 雙軌參數配置
TRACKS = {
    'TRACK_4H': {
        'name': '4H 中波段穩健軌',
        'itv': '4h',
        'dc_window': 20,
        'be_r': 1.5,
        'tp_r': 3.0
    },
    'TRACK_1H': {
        'name': '1H 高頻短波段軌',
        'itv': '1h',
        'dc_window': 20,
        'be_r': 1.2,
        'tp_r': 2.5
    }
}

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

# ==================== 2. 數據抓取模組 ====================
def fetch_gold_data(days=365):
    try:
        period_str = f"{days + 90}d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")
        
        # 1. 抓取 1H K 線
        df_1h = ticker.history(period=period_str, interval="1h")
        if df_1h.empty:
            return None, None, None
            
        df_1h = df_1h.reset_index()
        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.sort_values('time').reset_index(drop=True)
        
        # 2. 合成 4H K 線
        df_1h_indexed = df_1h.set_index('time')
        df_4h = df_1h_indexed.resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 3. 抓取 1D 日線數據 (宏觀定錨)
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1d = df_1d.sort_values('time').reset_index(drop=True)

        return df_1h[['time', 'o', 'h', 'l', 'c', 'v']], df_4h[['time', 'o', 'h', 'l', 'c', 'v']], df_1d[['time', 'o', 'h', 'l', 'c', 'v']]
    except Exception as e:
        print(f"[!] 黃金數據拉取失敗: {e}")
        return None, None, None

# ==================== 3. 指標計算模組 ====================
def prepare_indicators(df_trade, df_1d, dc_window=20):
    # 1. 日線 MA60 大趨勢濾網
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)
    
    df_trade['daily_date'] = df_trade['time'].dt.floor('D')
    df_1d['daily_date'] = df_1d['time'].dt.floor('D')
    daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
    df_trade['macro_filter'] = df_trade['daily_date'].map(daily_map).ffill().fillna(0)

    # 2. 唐奇安通道
    df_trade['dc_high'] = df_trade['h'].shift(1).rolling(dc_window).max()
    df_trade['dc_low'] = df_trade['l'].shift(1).rolling(dc_window).min()

    # 3. ATR(14) 計算
    tr = np.maximum(df_trade['h'] - df_trade['l'], np.maximum(abs(df_trade['h'] - df_trade['c'].shift(1)), abs(df_trade['l'] - df_trade['c'].shift(1))))
    df_trade['atr'] = tr.rolling(14).mean().fillna(df_trade['c'] * 0.01)

    return df_trade

# ==================== 4. 單軌回測撮合器 ====================
def run_single_track(df, cfg, days=365):
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')
    df = df[df['time'] >= start_filter_time].reset_index(drop=True)

    if df.empty:
        return None

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    current_wallet = float(INITIAL_WALLET)
    position = None
    completed_trades = []

    for idx in range(1, len(df)):
        bar = df.iloc[idx]

        # 1. 持倉處理 (移保本 + 止盈)
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
                    completed_trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'TP', 'time': bar['time']})
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
                    completed_trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP', 'time': bar['time']})
                    position = None
                    continue

        # 2. 開倉判定
        if position is None and current_wallet > 5.0:
            macro_trend = bar['macro_filter']
            sig_side = None
            entry, sl, tp, be_target = 0.0, 0.0, 0.0, 0.0

            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_target = entry + (risk_dist * cfg['be_r'])
                tp = entry + (risk_dist * cfg['tp_r'])

            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_target = entry - (risk_dist * cfg['be_r'])
                tp = entry - (risk_dist * cfg['tp_r'])

            if sig_side and risk_dist > 0:
                qty = (current_wallet * RISK_PCT) / risk_dist
                if (qty * entry) > (current_wallet * MAX_LEVERAGE):
                    qty = (current_wallet * MAX_LEVERAGE) / entry

                position = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_target, 'is_be_moved': False, 'qty': qty
                }

    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    return {
        'start_date': start_date, 'end_date': end_date,
        'final_wallet': current_wallet, 'roi_pct': roi_pct,
        'total_trades': total_trades, 'win_rate': win_rate
    }

# ==================== 5. 雙軌回測與即時推播 ====================
def run_dual_track_system(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【XAU/USD 現貨黃金 雙軌並行量化引擎】{period_title}回測")
    print("=" * 65 + "\n")

    df_1h, df_4h, df_1d = fetch_gold_data(days=days)
    if df_1h is None or df_4h is None or df_1d is None:
        print("[!] 數據抓取異常。")
        return

    # 準備指標
    df_4h_prep = prepare_indicators(df_4h.copy(), df_1d.copy(), dc_window=TRACKS['TRACK_4H']['dc_window'])
    df_1h_prep = prepare_indicators(df_1h.copy(), df_1d.copy(), dc_window=TRACKS['TRACK_1H']['dc_window'])

    res_4h = run_single_track(df_4h_prep, TRACKS['TRACK_4H'], days=days)
    res_1h = run_single_track(df_1h_prep, TRACKS['TRACK_1H'], days=days)

    if not res_4h or not res_1h:
        print("[!] 回測執行失敗。")
        return

    # 計算雙軌合併資產總結
    combined_start = INITIAL_WALLET * 2
    combined_end = res_4h['final_wallet'] + res_1h['final_wallet']
    combined_roi = ((combined_end - combined_start) / combined_start) * 100
    combined_trades = res_4h['total_trades'] + res_1h['total_trades']

    report_text = (
        "```text\n"
        f"【XAU/USD 現貨黃金 - 雙軌並行量化系統】\n"
        f"回測週期: {period_title} ({res_4h['start_date']} ~ {res_4h['end_date']})\n"
        f"總投入本金: ${format_full_num(combined_start)} USD (每軌各 $100)\n"
        f"雙軌合併結餘: ${format_full_num(combined_end, 2)} USD ({combined_roi:+.2f}%)\n"
        f"全系統總交易: {combined_trades} 次\n"
        "----------------------------------------------------\n"
        f"【軌道 1：4H 中波段穩健軌】(1.5R保本 / 3.0R止盈)\n"
        f"• 結餘: ${format_full_num(res_4h['final_wallet'], 2)} USD ({res_4h['roi_pct']:+.2f}%)\n"
        f"• 交易: {res_4h['total_trades']} 次 | 勝率: {res_4h['win_rate']:.2f}%\n"
        "\n"
        f"【軌道 2：1H 高頻短波段軌】(1.2R保本 / 2.5R止盈)\n"
        f"• 結餘: ${format_full_num(res_1h['final_wallet'], 2)} USD ({res_1h['roi_pct']:+.2f}%)\n"
        f"• 交易: {res_1h['total_trades']} 次 | 勝率: {res_1h['win_rate']:.2f}%\n"
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    # 執行 30 天與 365 天回測
    run_dual_track_system(days=30)
    time.sleep(2)
    run_dual_track_system(days=365)
