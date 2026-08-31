"""
XAU/USD Hierarchical Dual-Track Production Engine
- Macro Level  (4H Track): Donchian Breakout | 5% Risk | 10x Lev | 2.0R BE -> 5.0R TP (Priority Dominant)
- Micro Level  (1H Track): London/NY S/R Pullback | 3% Risk | 6x Lev | 1.5R Split TP & BE -> 3.0R TP
Wallet: Shared Compounding Pool ($100 Starting Capital)
"""

import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ==================== 1. 核心參數與 Webhook ====================
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

# ==================== 2. 數據獲取與多週期指標 ====================
def fetch_multi_timeframe_gold(days=365):
    try:
        period_str = f"{days + 90}d" if days <= 600 else "2y"
        ticker = yf.Ticker("GC=F")

        # 1H K 線
        df_1h = ticker.history(period=period_str, interval="1h").reset_index()
        if df_1h.empty:
            return None, None

        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        # 4H K 線
        df_4h = df_1h.set_index('time').resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 1D 日線計算 MA60
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d['ma60'] = df_1d['c'].rolling(60).mean()
        df_1d['macro_trend'] = np.where(df_1d['c'] > df_1d['ma60'], 1, -1)

        # 對齊宏觀定錨
        df_4h['d_date'] = df_4h['time'].dt.floor('D')
        df_1h['d_date'] = df_1h['time'].dt.floor('D')
        df_1d['d_date'] = df_1d['time'].dt.floor('D')
        d_map = df_1d.drop_duplicates('d_date').set_index('d_date')['macro_trend'].to_dict()
        df_4h['macro_filter'] = df_4h['d_date'].map(d_map).ffill().fillna(0)
        df_1h['macro_filter'] = df_1h['d_date'].map(d_map).ffill().fillna(0)

        # 4H 指標 (長線突破用)
        df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
        df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
        tr_4h = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
        df_4h['atr'] = tr_4h.rolling(14).mean().fillna(df_4h['c'] * 0.015)

        # 1H 指標 (短線回踩用)
        df_1h['dc_high'] = df_1h['h'].shift(1).rolling(20).max()
        df_1h['dc_low'] = df_1h['l'].shift(1).rolling(20).min()
        tr_1h = np.maximum(df_1h['h'] - df_1h['l'], np.maximum(abs(df_1h['h'] - df_1h['c'].shift(1)), abs(df_1h['l'] - df_1h['c'].shift(1))))
        df_1h['atr'] = tr_1h.rolling(14).mean().fillna(df_1h['c'] * 0.01)

        return df_4h, df_1h
    except Exception as e:
        print(f"[!] 數據抓取異常: {e}")
        return None, None

# ==================== 3. 雙軌層級事件撮合主引擎 ====================
def run_dual_track_engine(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    df_4h, df_1h = fetch_multi_timeframe_gold(days=days)
    if df_4h is None or df_1h is None:
        return

    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 86400000), unit='ms')

    df_4h = df_4h[df_4h['time'] >= start_filter_time].reset_index(drop=True)
    df_1h = df_1h[df_1h['time'] >= start_filter_time].reset_index(drop=True)
    if df_4h.empty or df_1h.empty:
        return

    start_date = df_1h.iloc[0]['time'].strftime("%Y-%m-%d")
    end_date = df_1h.iloc[-1]['time'].strftime("%Y-%m-%d")

    # 建立事件序列隊列
    events = []
    for idx in range(1, len(df_4h)):
        events.append((df_4h.iloc[idx]['time'], 'TRACK_4H', idx))
    for idx in range(1, len(df_1h)):
        events.append((df_1h.iloc[idx]['time'], 'TRACK_1H', idx))
    events.sort(key=lambda x: x[0])

    wallet = float(INITIAL_WALLET)
    pos_4h = None
    pos_1h = None

    stats = {
        'TRACK_4H': {'trades': 0, 'wins': 0, 'pnl': 0.0},
        'TRACK_1H': {'trades': 0, 'wins': 0, 'pnl': 0.0}
    }
    recent_1h_high = None
    recent_1h_low = None

    for event_time, track_type, idx in events:
        # ----------------- 長線 4H 處理模組 -----------------
        if track_type == 'TRACK_4H':
            bar = df_4h.iloc[idx]
            
            # 持倉撮合 (2.0R 保本 / 5.0R 止盈)
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

            # 長線開倉 (5% 風險 / 10x 槓桿)
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

        # ----------------- 短線 1H 處理模組 -----------------
        elif track_type == 'TRACK_1H':
            bar = df_1h.iloc[idx]
            prev_bar = df_1h.iloc[idx - 1]

            # 持倉撮合 (階梯式 1.5R 平倉 50% 移保本 / 3.0R 終點)
            if pos_1h is not None:
                side, entry, sl, tp, be_tgt, qty, is_half_closed = (
                    pos_1h['side'], pos_1h['entry'], pos_1h['sl'], pos_1h['tp'],
                    pos_1h['be_target'], pos_1h['qty'], pos_1h['is_half_closed']
                )

                if side == 'LONG':
                    # 1.5R 分批平半倉 + 保本
                    if not is_half_closed and bar['h'] >= be_tgt:
                        half_qty = qty * 0.5
                        pnl_half = half_qty * (be_tgt - entry) - half_qty * (entry + be_tgt) * FEE_RATE
                        wallet += pnl_half
                        stats['TRACK_1H']['pnl'] += pnl_half
                        pos_1h['qty'] = qty * 0.5
                        pos_1h['sl'] = entry
                        pos_1h['is_half_closed'] = True

                    if bar['l'] <= pos_1h['sl']:
                        rem_qty = pos_1h['qty']
                        pnl = rem_qty * (pos_1h['sl'] - entry) - rem_qty * (entry + pos_1h['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        if (pnl + (stats['TRACK_1H']['pnl'] if is_half_closed else 0)) > 0:
                            stats['TRACK_1H']['wins'] += 1
                        pos_1h = None
                    elif bar['h'] >= tp:
                        rem_qty = pos_1h['qty']
                        pnl = rem_qty * (tp - entry) - rem_qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['wins'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        pos_1h = None

                elif side == 'SHORT':
                    if not is_half_closed and bar['l'] <= be_tgt:
                        half_qty = qty * 0.5
                        pnl_half = half_qty * (entry - be_tgt) - half_qty * (entry + be_tgt) * FEE_RATE
                        wallet += pnl_half
                        stats['TRACK_1H']['pnl'] += pnl_half
                        pos_1h['qty'] = qty * 0.5
                        pos_1h['sl'] = entry
                        pos_1h['is_half_closed'] = True

                    if bar['h'] >= pos_1h['sl']:
                        rem_qty = pos_1h['qty']
                        pnl = rem_qty * (entry - pos_1h['sl']) - rem_qty * (entry + pos_1h['sl']) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        if (pnl + (stats['TRACK_1H']['pnl'] if is_half_closed else 0)) > 0:
                            stats['TRACK_1H']['wins'] += 1
                        pos_1h = None
                    elif bar['l'] <= tp:
                        rem_qty = pos_1h['qty']
                        pnl = rem_qty * (entry - tp) - rem_qty * (entry + tp) * FEE_RATE
                        wallet += pnl
                        stats['TRACK_1H']['trades'] += 1
                        stats['TRACK_1H']['wins'] += 1
                        stats['TRACK_1H']['pnl'] += pnl
                        pos_1h = None

            # 記錄 1H 關鍵水平位
            if prev_bar['c'] > prev_bar['dc_high']:
                recent_1h_high = prev_bar['dc_high']
            if prev_bar['c'] < prev_bar['dc_low']:
                recent_1h_low = prev_bar['dc_low']

            # 短線開倉條件 (歐美主力時段 06:00 ~ 20:00 UTC + 長線邏輯優先過濾)
            hour_utc = bar['time'].hour
            is_active_session = 6 <= hour_utc <= 20

            if pos_1h is None and wallet > 5.0 and is_active_session:
                trend = bar['macro_filter']
                atr_val = bar['atr']
                body = abs(bar['c'] - bar['o'])
                lower_shadow = min(bar['c'], bar['o']) - bar['l']
                upper_shadow = bar['h'] - max(bar['c'], bar['o'])
                sig, entry, sl, tp, be_tgt = None, 0.0, 0.0, 0.0, 0.0

                # 宏觀偏多 (若長線有倉位，僅允許同向做多)
                if trend == 1 and (pos_4h is None or pos_4h['side'] == 'LONG') and recent_1h_high is not None:
                    retest_top = recent_1h_high + (atr_val * 0.5)
                    is_bull_pinbar = (lower_shadow >= 1.0 * body) and (bar['c'] >= (bar['h'] + bar['l']) / 2)
                    if (bar['l'] <= retest_top) and (bar['c'] > recent_1h_high) and is_bull_pinbar:
                        sig, entry = 'LONG', bar['c']
                        sl = bar['l'] - (atr_val * 0.8)
                        risk_dist = entry - sl
                        if risk_dist > (atr_val * 0.3):
                            be_tgt = entry + (risk_dist * 1.5)
                            tp = entry + (risk_dist * 3.0)
                            recent_1h_high = None

                # 宏觀偏空 (若長線有倉位，僅允許同向做空)
                elif trend == -1 and (pos_4h is None or pos_4h['side'] == 'SHORT') and recent_1h_low is not None:
                    retest_bot = recent_1h_low - (atr_val * 0.5)
                    is_bear_pinbar = (upper_shadow >= 1.0 * body) and (bar['c'] <= (bar['h'] + bar['l']) / 2)
                    if (bar['h'] >= retest_bot) and (bar['c'] < recent_1h_low) and is_bear_pinbar:
                        sig, entry = 'SHORT', bar['c']
                        sl = bar['h'] + (atr_val * 0.8)
                        risk_dist = sl - entry
                        if risk_dist > (atr_val * 0.3):
                            be_tgt = entry - (risk_dist * 1.5)
                            tp = entry - (risk_dist * 3.0)
                            recent_1h_low = None

                if sig and risk_dist > 0:
                    qty = (wallet * 0.03) / risk_dist # 短線只承擔 3% 風險
                    if (qty * entry) > (wallet * 6.0): # 短線最高 6x 槓桿
                        qty = (wallet * 6.0) / entry
                    pos_1h = {
                        'side': sig, 'entry': entry, 'sl': sl,
                        'tp': tp, 'be_target': be_tgt, 'qty': qty,
                        'is_half_closed': False
                    }

    # ==================== 4. 輸出報表 ====================
    total_trades = stats['TRACK_4H']['trades'] + stats['TRACK_1H']['trades']
    total_wins = stats['TRACK_4H']['wins'] + stats['TRACK_1H']['wins']
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
    total_roi = ((wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    track_lines = []
    for t_key, name in [('TRACK_4H', '4H 長線波段 (5%風險 / 10x槓桿 / 5.0R)'),
                        ('TRACK_1H', '1H 歐美短線 (3%風險 /  6x槓桿 / 3.0R半倉鎖利)')]:
        st = stats[t_key]
        c, w, pnl = st['trades'], st['wins'], st['pnl']
        wr = (w / c * 100) if c > 0 else 0.0
        track_lines.append(f"• {name}\n  └ 交易: {str(c).rjust(2)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {pnl:+10.2f}")

    report_text = (
        "```text\n"
        "【XAU/USD 現貨黃金 - 長短層級雙軌量化系統 (共享複利池)】\n"
        f"回測週期: {period_title} ({start_date} ~ {end_date})\n"
        f"初始本金: ${format_full_num(INITIAL_WALLET)} USD\n"
        f"最終結餘: ${format_full_num(wallet, 2)} USD ({total_roi:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_wr:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(track_lines) + "\n"
        "```"
    )

    print(report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n")

# ==================== 5. 主執行入口 ====================
if __name__ == '__main__':
    run_dual_track_engine(days=30)
    time.sleep(2)
    run_dual_track_engine(days=365)
