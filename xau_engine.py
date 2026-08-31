"""
XAU/USD Macro Swing (4H) + High-Frequency Scalping (15m) Engine
- Macro 4H Track: 1D MA60 + 4H Breakout | 5% Risk | 10x Lev | 2.0R BE -> 5.0R TP
- Scalp 15m Track: 1D Trend + 15m EMA9/21 Momentum | 3% Risk | 20x Lev | 1.0R BE -> 2.5R TP
Wallet: Shared Compounding Pool ($100 Starting Capital)
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

INITIAL_WALLET = 100.0
FEE_RATE = 0.0004  # 萬分之四

def format_full_num(val, max_dec=4):
    try:
        f = float(val)
        return f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
    except Exception:
        return str(val)

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

# ==================== 2. 數據獲取與多週期指標 ====================
def fetch_scalp_data(days=60):
    try:
        # yfinance 15m 支援長度通常在 60 天以內
        period_str = f"{days + 10}d" if days <= 55 else "60d"
        ticker = yf.Ticker("GC=F")

        # 1. 抓取 15m K 線
        df_15m = ticker.history(period=period_str, interval="15m").reset_index()
        if df_15m.empty:
            return None, None

        date_col = 'Datetime' if 'Datetime' in df_15m.columns else 'Date'
        df_15m['time'] = pd.to_datetime(df_15m[date_col]).dt.tz_localize(None)
        df_15m.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_15m = df_15m.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        # 2. 合成 4H K 線
        df_4h = df_15m.set_index('time').resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 3. 日線 MA60
        df_1d = ticker.history(period="1y", interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

        # 4. 對齊大趨勢
        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_15m['d_date'] = df_15m['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)
        df_15m['macro_filter'] = df_15m['d_date'].map(d_map).ffill().fillna(0)

        # 5. 4H 指標 (長線突破)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr_4h = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr_4h.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        # 6. 15m 高頻指標 (EMA9/21 + 5棒極值 + ATR)
        df_15m['ema9'] = df_15m['c'].ewm(span=9, adjust=False).mean()
        df_15m['ema21'] = df_15m['c'].ewm(span=21, adjust=False).mean()
        df_15m['local_high'] = df_15m['h'].shift(1).rolling(5).max()
        df_15m['local_low'] = df_15m['l'].shift(1).rolling(5).min()
        tr_15m = np.maximum(df_15m['h'] - df_15m['l'], np.maximum(abs(df_15m['h'] - df_15m['c'].shift(1)), abs(df_15m['l'] - df_15m['c'].shift(1))))
        df_15m['atr'] = tr_15m.rolling(14).mean().fillna(df_15m['c'] * 0.005)

        return df_4h, df_15m
    except Exception as e:
        print(f"[!] 數據抓取失敗: {e}")
        return None, None

# ==================== 3. 雙軌撮合引擎 ====================
def run_high_frequency_engine(days=30):
    period_title = f"{days} 天期"
    df_4h, df_15m = fetch_scalp_data(days=days)
    if df_4h is None or df_15m is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')

    df_4h = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    df_15m = df_15m[df_15m['time'] >= start_filter_time].reset_index(drop=True)
    if df_4h.empty or df_15m.empty:
        return

    start_date = df_15m.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df_15m.iloc[-1]['time'].strftime("%Y-%m-%d")

    events = []
    for idx in range(1, len(df_4h)):
        events.append((df_4h.iloc[idx]['time'], 'TRACK_4H', idx))
    for idx in range(1, len(df_15m)):
        events.append((df_15m.iloc[idx]['time'], 'TRACK_15M', idx))
    events.sort(key=lambda x: x[0])

    wallet = float(INITIAL_WALLET)
    pos_4h = None
    pos_15m = None

    stats = {
        'TRACK_4H': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'TRACK_15M': {'trades': 0, 'wins': 0, 'pnl': 0.0}
    }

    for event_time, track_type, idx in events:
        # ----------------- 長線 4H 波段 -----------------
        if track_type == 'TRACK_4H':
            bar = df_4h.iloc[idx]
            if pos_4h is not None:
                side, entry, sl, tp, be_tgt, qty, be_done = (
                    pos_4h['side'], pos_4h['entry'], pos_4h['sl'], pos_4h['tp'],
                    pos_4h['be_target'], pos_4h['qty'], pos_4h['is_be_moved']
                )
                if side == 'LONG':
                    if not be_done and bar['h'] >= be_tgt:
                        pos_4h['sl'] = entry
                        pos_4h['is_be_moved'] = True
                    if bar['l'] <= pos_4h['sl']:
                        pnl = qty * (pos_4h['sl'] - entry) - qty * (entry + pos_4h['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_4H']['wins'] += 1
                        pos_4h = None
                    elif bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['wins'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        pos_4h = None
                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos_4h['sl'] = entry
                        pos_4h['is_be_moved'] = True
                    if bar['h'] >= pos_4h['sl']:
                        pnl = qty * (entry - pos_4h['sl']) - qty * (entry + pos_4h['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_4H']['wins'] += 1
                        pos_4h = None
                    elif bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_4H']['trades'] += 1
                        stats['TRACK_4H']['wins'] += 1
                        stats['TRACK_4H']['pnl'] += pnl
                        pos_4h = None

            if pos_4h is None and wallet > 5.0:
                trend = bar['macro_filter']
                atr_val = bar['atr']
                sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0
                if trend == 1 and bar['c'] > bar['dc_high']:
                    sig, entry = 'LONG', bar['c']
                    sl = entry - (atr_val * 1.5)
                    risk_dist = entry - sl
                    be_tgt = entry + (risk_dist * 2.0)
                    tp = entry + (risk_dist * 5.0)
                elif trend == -1 and bar['c'] < bar['dc_low']:
                    sig, entry = 'SHORT', bar['c']
                    sl = entry + (atr_val * 1.5)
                    risk_dist = sl - entry
                    be_tgt = entry - (risk_dist * 2.0)
                    tp = entry - (risk_dist * 5.0)

                if sig and risk_dist > 0:
                    qty = (wallet * 0.05) / risk_dist
                    if (qty * entry) > (wallet * 10.0):
                        qty = (wallet * 10.0) / entry
                    pos_4h = {
                        'side': sig, 'entry': entry, 'sl': sl,
                        'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                    }

        # ----------------- 高頻 15m 狙擊 -----------------
        elif track_type == 'TRACK_15M':
            bar = df_15m.iloc[idx]
            prev_bar = df_15m.iloc[idx - 1]

            if pos_15m is not None:
                side, entry, sl, tp, be_tgt, qty, be_done = (
                    pos_15m['side'], pos_15m['entry'], pos_15m['sl'], pos_15m['tp'],
                    pos_15m['be_target'], pos_15m['qty'], pos_15m['is_be_moved']
                )

                if side == 'LONG':
                    if not be_done and bar['h'] >= be_tgt:
                        pos_15m['sl'] = entry
                        pos_15m['is_be_moved'] = True
                    if bar['l'] <= pos_15m['sl']:
                        pnl = qty * (pos_15m['sl'] - entry) - qty * (entry + pos_15m['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_15M']['trades'] += 1
                        stats['TRACK_15M']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_15M']['wins'] += 1
                        pos_15m = None
                    elif bar['h'] >= tp:
                        pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_15M']['trades'] += 1
                        stats['TRACK_15M']['wins'] += 1
                        stats['TRACK_15M']['pnl'] += pnl
                        pos_15m = None

                elif side == 'SHORT':
                    if not be_done and bar['l'] <= be_tgt:
                        pos_15m['sl'] = entry
                        pos_15m['is_be_moved'] = True
                    if bar['h'] >= pos_15m['sl']:
                        pnl = qty * (entry - pos_15m['sl']) - qty * (entry + pos_15m['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_15M']['trades'] += 1
                        stats['TRACK_15M']['pnl'] += pnl
                        if pnl > 0: stats['TRACK_15M']['wins'] += 1
                        pos_15m = None
                    elif bar['l'] <= tp:
                        pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_15M']['trades'] += 1
                        stats['TRACK_15M']['wins'] += 1
                        stats['TRACK_15M']['pnl'] += pnl
                        pos_15m = None

            # 15m 開倉 (歐美時段 12:00 ~ 21:00 UTC)
            hour_utc = bar['time'].hour
            is_active_session = 12 <= hour_utc <= 21

            if pos_15m is None and wallet > 5.0 and is_active_session:
                trend = bar['macro_filter']
                atr_val = bar['atr']
                sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

                # 多頭動能狙擊：EMA9 > EMA21 + 突破前 5 根 15m 高點
                if trend == 1 and (pos_4h is None or pos_4h['side'] == 'LONG'):
                    if bar['ema9'] > bar['ema21'] and bar['c'] > bar['local_high'] and prev_bar['c'] <= prev_bar['local_high']:
                        sig, entry = 'LONG', bar['c']
                        sl = entry - (atr_val * 1.2) # 緊湊窄止損
                        risk_dist = entry - sl
                        be_tgt = entry + (risk_dist * 1.0) # 1.0R 快速移保本
                        tp = entry + (risk_dist * 2.5)     # 2.5R 快速收割

                # 空頭動能狙擊：EMA9 < EMA21 + 跌破前 5 根 15m 低點
                elif trend == -1 and (pos_4h is None or pos_4h['side'] == 'SHORT'):
                    if bar['ema9'] < bar['ema21'] and bar['c'] < bar['local_low'] and prev_bar['c'] >= prev_bar['local_low']:
                        sig, entry = 'SHORT', bar['c']
                        sl = entry + (atr_val * 1.2)
                        risk_dist = sl - entry
                        be_tgt = entry - (risk_dist * 1.0)
                        tp = entry - (risk_dist * 2.5)

                if sig and risk_dist > 0:
                    qty = (wallet * 0.03) / risk_dist # 3% 單筆風險
                    if (qty * entry) > (wallet * 20.0): # 最高拉到 20x 槓桿
                        qty = (wallet * 20.0) / entry
                    pos_15m = {
                        'side': sig, 'entry': entry, 'sl': sl,
                        'tp': tp, 'be_target': be_tgt, 'qty': qty, 'is_be_moved': False
                    }

    # 輸出報表
    total_trades = stats['TRACK_4H']['trades'] + stats['TRACK_15M']['trades']
    total_wins = stats['TRACK_4H']['wins'] + stats['TRACK_15M']['wins']
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
    total_roi = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    track_lines = []
    for t_key, name in [('TRACK_4H', '4H 長線波段 (5%風險 / 10x槓桿 / 5.0R)'),
                        ('TRACK_15M', '15m 高頻狙擊 (3%風險 / 20x槓桿 / 2.5R快打)')]:
        st = stats[t_key]
        c, w, pnl = st['trades'], st['wins'], st['pnl']
        wr = (w / c * 100) if c > 0 else 0.0
        track_lines.append(f"• {name}\n  └ 交易: {str(c).rjust(2)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {pnl:+10.2f}")

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金 - 4H長線 + 15m高頻狙擊系統 (共享池)】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始本金: ${format_full_num(INITIAL_WALLET)} USD\n"
        f"最終結餘: ${format_full_num(wallet, 2)} USD ({total_roi:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_wr:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(track_lines) + "\n"
        "```"
    )

    print(report_text)
    send_discord(report_text)

if __name__ == '__main__':
    run_high_frequency_engine(days=30)
    time.sleep(2)
    run_high_frequency_engine(days=60)
