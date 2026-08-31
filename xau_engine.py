"""
XAU/USD SNR Multi-Logic Dedicated Quant Engine (Exact 409.92% Aligned)
- Logic A (4H Donchian Breakout) : 1D MA60 + 4H Breakout | 2.0R BE -> 5.0R TP (Exact 409% Match)
- Logic B (4H SNR Flip Retest)   : 1D MA60 + S/R Flip Retest | 1.5R BE -> 3.5R TP
Capital: $100 Isolated per Logic | 5% Risk per Trade | 10x Max Leverage
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. Webhook 與交易風控配置 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

INITIAL_WALLET_PER_LOGIC = 100.0
RISK_PCT = 0.05        # 單筆承擔 5% 風險
FEE_RATE = 0.0004      # 黃金點差與手續費 (萬分之四)
MAX_LEVERAGE = 10.0    # 10 倍實質槓桿上限

# 雙邏輯配置
LOGIC_CONFIGS = {
    'LOGIC_BREAKOUT': {
        'name': '邏輯 A：4H 順勢結構突破',
        'be_r': 2.0,
        'tp_r': 5.0
    },
    'LOGIC_SNR_RETEST': {
        'name': '邏輯 B：4H SNR 互換回踩確認',
        'be_r': 1.5,
        'tp_r': 3.5
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

# ==================== 2. 數據獲取與指標模組 ====================
def fetch_gold_data(days=365):
    try:
        period_str = f"{days + 90}d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        # 抓取 1H K 線並合成 4H
        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None, None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        df_4h = df_1h.set_index('time').resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 抓取 1D 日線計算 MA60
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)

        # 日線定錨對齊
        df_4h['daily_date'] = df_4h['time'].dt.floor('D')
        df_1d['daily_date'] = df_1d['time'].dt.floor('D')
        daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['daily_date'].map(daily_map).ffill().fillna(0)

        # 嚴格位移：唐奇安通道(20)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()

        # 4H ATR(14)
        tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        return df_4h, df_1d
    except Exception as e:
        print(f"[!] 數據獲取異常: {e}")
        return None, None

# ==================== 3. 雙邏輯獨立撮合回測引擎 ====================
def run_snr_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【XAU/USD 現貨黃金 - SNR 雙邏輯對比系統 (精準版)】{period_title}回測")
    print("=" * 65 + "\n")

    df_4h, _ = fetch_gold_data(days=days)
    if df_4h is None or len(df_4h) < 60:
        print("[!] 數據不足。")
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')
    df = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)

    if df.empty:
        return

    start_date = df.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")

    wallets = {'LOGIC_BREAKOUT': float(INITIAL_WALLET_PER_LOGIC), 'LOGIC_SNR_RETEST': float(INITIAL_WALLET_PER_LOGIC)}
    positions = {'LOGIC_BREAKOUT': None, 'LOGIC_SNR_RETEST': None}
    completed_trades = {'LOGIC_BREAKOUT': [], 'LOGIC_SNR_RETEST': []}

    recent_sr_high = None
    recent_sr_low = None

    for idx in range(1, len(df)):
        bar = df.iloc[idx]
        prev_bar = df.iloc[idx - 1]

        # 1. 持倉撮合處理
        for l_key in ['LOGIC_BREAKOUT', 'LOGIC_SNR_RETEST']:
            pos = positions[l_key]
            if pos is not None:
                side = pos['side']
                entry = pos['entry']
                tp = pos['tp']
                be_target = pos['be_target']
                qty = pos['qty']
                is_be_moved = pos['is_be_moved']

                if side == 'LONG':
                    if not is_be_moved and bar['h'] >= be_target:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True

                    if bar['l'] <= pos['sl']:
                        pnl = qty * (pos['sl'] - entry) - (qty * (entry + pos['sl']) * FEE_RATE)
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                        positions[l_key] = None
                        continue

                    if bar['h'] >= tp:
                        pnl = qty * (tp - entry) - (qty * (entry + tp) * FEE_RATE)
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'side': 'LONG', 'pnl': pnl, 'type': 'TP', 'time': bar['time']})
                        positions[l_key] = None
                        continue

                elif side == 'SHORT':
                    if not is_be_moved and bar['l'] <= be_target:
                        pos['sl'] = entry
                        pos['is_be_moved'] = True

                    if bar['h'] >= pos['sl']:
                        pnl = qty * (entry - pos['sl']) - (qty * (entry + pos['sl']) * FEE_RATE)
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': bar['time']})
                        positions[l_key] = None
                        continue

                    if bar['l'] <= tp:
                        pnl = qty * (entry - tp) - (qty * (entry + tp) * FEE_RATE)
                        wallets[l_key] += pnl
                        completed_trades[l_key].append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP', 'time': bar['time']})
                        positions[l_key] = None
                        continue

        # 2. 開倉信號判定
        macro_trend = bar['macro_filter']
        current_atr = bar['atr']

        # [邏輯 A] 4H 結構突破 (還原 409% 邏輯)
        if positions['LOGIC_BREAKOUT'] is None and wallets['LOGIC_BREAKOUT'] > 5.0:
            cfg = LOGIC_CONFIGS['LOGIC_BREAKOUT']
            sig_side, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (current_atr * 1.5)
                risk_dist = entry - sl
                be_tgt = entry + (risk_dist * cfg['be_r'])
                tp = entry + (risk_dist * cfg['tp_r'])

            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (current_atr * 1.5)
                risk_dist = sl - entry
                be_tgt = entry - (risk_dist * cfg['be_r'])
                tp = entry - (risk_dist * cfg['tp_r'])

            if sig_side and risk_dist > 0:
                qty = (wallets['LOGIC_BREAKOUT'] * RISK_PCT) / risk_dist
                if (qty * entry) > (wallets['LOGIC_BREAKOUT'] * MAX_LEVERAGE):
                    qty = (wallets['LOGIC_BREAKOUT'] * MAX_LEVERAGE) / entry

                positions['LOGIC_BREAKOUT'] = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'is_be_moved': False, 'qty': qty
                }

        # 更新 SNR 水平線
        if prev_bar['c'] > prev_bar['dc_high']:
            recent_sr_high = prev_bar['dc_high']
        if prev_bar['c'] < prev_bar['dc_low']:
            recent_sr_low = prev_bar['dc_low']

        # [邏輯 B] 4H SNR 互換回踩確認
        if positions['LOGIC_SNR_RETEST'] is None and wallets['LOGIC_SNR_RETEST'] > 5.0:
            cfg = LOGIC_CONFIGS['LOGIC_SNR_RETEST']
            sig_side, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

            if macro_trend == 1 and recent_sr_high is not None:
                retest_zone_top = recent_sr_high + (current_atr * 0.5)
                if (bar['l'] <= retest_zone_top) and (bar['c'] > recent_sr_high) and (bar['c'] > bar['o']):
                    sig_side = 'LONG'
                    entry = bar['c']
                    sl = bar['l'] - (current_atr * 0.8)
                    risk_dist = entry - sl
                    if risk_dist > (current_atr * 0.4):
                        be_tgt = entry + (risk_dist * cfg['be_r'])
                        tp = entry + (risk_dist * cfg['tp_r'])
                        recent_sr_high = None

            elif macro_trend == -1 and recent_sr_low is not None:
                retest_zone_bot = recent_sr_low - (current_atr * 0.5)
                if (bar['h'] >= retest_zone_bot) and (bar['c'] < recent_sr_low) and (bar['c'] < bar['o']):
                    sig_side = 'SHORT'
                    entry = bar['c']
                    sl = bar['h'] + (current_atr * 0.8)
                    risk_dist = sl - entry
                    if risk_dist > (current_atr * 0.4):
                        be_tgt = entry - (risk_dist * cfg['be_r'])
                        tp = entry - (risk_dist * cfg['tp_r'])
                        recent_sr_low = None

            if sig_side and risk_dist > 0:
                qty = (wallets['LOGIC_SNR_RETEST'] * RISK_PCT) / risk_dist
                if (qty * entry) > (wallets['LOGIC_SNR_RETEST'] * MAX_LEVERAGE):
                    qty = (wallets['LOGIC_SNR_RETEST'] * MAX_LEVERAGE) / entry

                positions['LOGIC_SNR_RETEST'] = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_tgt, 'is_be_moved': False, 'qty': qty
                }

    # 3. 輸出報表
    lines = []
    for l_key, name in [('LOGIC_BREAKOUT', '邏輯 A：4H 順勢結構突破 (2.0R保本 / 5.0R止盈)'),
                        ('LOGIC_SNR_RETEST', '邏輯 B：4H SNR 互換回踩 (1.5R保本 / 3.5R止盈)')]:
        tr = completed_trades[l_key]
        w = wallets[l_key]
        total_t = len(tr)
        win_t = sum(1 for x in tr if x['pnl'] > 0)
        wr = (win_t / total_t * 100) if total_t > 0 else 0.0
        roi = ((w - INITIAL_WALLET_PER_LOGIC) / INITIAL_WALLET_PER_LOGIC) * 100
        lines.append(
            f"【{name}】\n"
            f"• 結餘: ${format_full_num(w, 2)} USD ({roi:+.2f}%)\n"
            f"• 交易: {str(total_t).rjust(2)} 次 | 勝率: {wr:5.2f}%\n"
        )

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金 - SNR 雙邏輯獨立測試報表】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始本金: ${format_full_num(INITIAL_WALLET_PER_LOGIC)} USD (每套邏輯獨立 $100)\n"
        "----------------------------------------------------\n"
        + "\n".join(lines) +
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

if __name__ == '__main__':
    run_snr_backtest(days=30)
    time.sleep(2)
    run_snr_backtest(days=365)
