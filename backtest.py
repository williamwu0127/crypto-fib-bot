"""
XAU & MSFT Tri-Track Production Engine
- Track 1: XAU Swing (4H)  | 1D MA60 + 4H Donchian(20) | 2.0R BE -> 5.0R TP
- Track 2: XAU Fast  (1H)  | 1D MA60 + 1H Donchian(20) | 1.5R BE -> 3.0R TP
- Track 3: MSFT Swing (4H) | 1D MA60 + 4H Donchian(20) | 1.5R BE -> 3.0R TP
Modes: 'ISOLATED' ($100 per track) | 'COMBINED' ($100 shared compounding)
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

INITIAL_CAPITAL = 100.0  # 基礎起始本金
RISK_PCT = 0.05         # 單筆固定承擔 5% 風險
FEE_RATE = 0.0004       # 綜合點差與手續費 (萬分之四)
MAX_LEVERAGE = 10.0     # 10 倍實質槓桿上限

# 三軌自訂參數配置
STRATEGY_TRACKS = {
    'XAU_4H':  {'name': 'XAU 長線 (4H)',  'sym': 'GC=F', 'itv': '4h', 'dc_w': 20, 'be_r': 2.0, 'tp_r': 5.0},
    'XAU_1H':  {'name': 'XAU 短線 (1H)',  'sym': 'GC=F', 'itv': '1h', 'dc_w': 20, 'be_r': 1.5, 'tp_r': 3.0},
    'MSFT_4H': {'name': 'MSFT 波段 (4H)', 'sym': 'MSFT', 'itv': '4h', 'dc_w': 20, 'be_r': 1.5, 'tp_r': 3.0}
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
def fetch_raw_data(ticker_sym, days=365):
    try:
        period_str = f"{days + 90}d" if days <= 600 else "2y"
        ticker = yf.Ticker(ticker_sym)

        # 抓取 1H K 線
        df_1h = ticker.history(period=period_str, interval="1h")
        if df_1h.empty:
            return None, None, None

        df_1h = df_1h.reset_index()
        date_col = 'Datetime' if 'Datetime' in df_1h.columns else 'Date'
        df_1h['time'] = pd.to_datetime(df_1h[date_col]).dt.tz_localize(None)
        df_1h.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
        df_1h = df_1h.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        # 合成 4H K 線
        df_1h_indexed = df_1h.set_index('time')
        df_4h = df_1h_indexed.resample('4h').agg({
            'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'
        }).dropna().reset_index()

        # 抓取 1D 日線數據
        df_1d = ticker.history(period=period_str, interval="1d").reset_index()
        date_col_d = 'Datetime' if 'Datetime' in df_1d.columns else 'Date'
        df_1d['time'] = pd.to_datetime(df_1d[date_col_d]).dt.tz_localize(None)
        df_1d.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c'}, inplace=True)
        df_1d = df_1d.dropna(subset=['c']).sort_values('time').reset_index(drop=True)

        return df_1h[['time', 'o', 'h', 'l', 'c', 'v']], df_4h[['time', 'o', 'h', 'l', 'c', 'v']], df_1d[['time', 'o', 'h', 'l', 'c']]
    except Exception as e:
        print(f"[!] 數據抓取失敗 ({ticker_sym}): {e}")
        return None, None, None

# ==================== 3. 指標計算模組 ====================
def prepare_indicators(df_trade, df_1d, dc_window=20):
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)

    df_trade['daily_date'] = df_trade['time'].dt.floor('D')
    df_1d['daily_date'] = df_1d['time'].dt.floor('D')
    daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
    df_trade['macro_filter'] = df_trade['daily_date'].map(daily_map).ffill().fillna(0)

    # 唐奇安通道
    df_trade['dc_high'] = df_trade['h'].shift(1).rolling(dc_window).max()
    df_trade['dc_low'] = df_trade['l'].shift(1).rolling(dc_window).min()

    # ATR(14)
    tr = np.maximum(df_trade['h'] - df_trade['l'], np.maximum(abs(df_trade['h'] - df_trade['c'].shift(1)), abs(df_trade['l'] - df_trade['c'].shift(1))))
    df_trade['atr'] = tr.rolling(14).mean().fillna(df_trade['c'] * 0.015)

    return df_trade

# ==================== 4. 撮合回測核心 ====================
def run_unified_backtest(days=365, mode='COMBINED'):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')

    # 1. 抓取數據
    gold_1h, gold_4h, gold_1d = fetch_raw_data("GC=F", days=days)
    msft_1h, msft_4h, msft_1d = fetch_raw_data("MSFT", days=days)

    if gold_1h is None or msft_1h is None:
        print("[!] 數據不足。")
        return

    track_dfs = {
        'XAU_4H':  prepare_indicators(gold_4h.copy(), gold_1d.copy(), dc_window=20),
        'XAU_1H':  prepare_indicators(gold_1h.copy(), gold_1d.copy(), dc_window=20),
        'MSFT_4H': prepare_indicators(msft_4h.copy(), msft_1d.copy(), dc_window=20)
    }

    # 2. 構建事件隊列
    events = []
    earliest_start, latest_end = None, None

    for t_key, df in track_dfs.items():
        df_filtered = df[df['time'] >= start_filter_time].reset_index(drop=True)
        track_dfs[t_key] = df_filtered

        if len(df_filtered) > 0:
            s_date = pd.to_datetime(df_filtered.iloc[0]['time']).strftime("%Y-%m-%d")
            e_date = pd.to_datetime(df_filtered.iloc[-1]['time']).strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start: earliest_start = s_date
            if latest_end is None or e_date > latest_end: latest_end = e_date

            for idx in range(1, len(df_filtered)):
                events.append((df_filtered.iloc[idx]['time'], t_key, idx))

    events.sort(key=lambda x: x[0])

    # 3. 資金狀態初始化
    if mode == 'COMBINED':
        total_wallet = float(INITIAL_CAPITAL)
        wallets = {}
    else:
        total_wallet = 0.0
        wallets = {t_key: float(INITIAL_CAPITAL) for t_key in STRATEGY_TRACKS.keys()}

    positions = {}
    completed_trades = []
    track_stats = {t: {'trades': 0, 'wins': 0, 'pnl': 0.0} for t in STRATEGY_TRACKS.keys()}

    # 4. 時間序列撮合
    for event_time, t_key, idx in events:
        df = track_dfs[t_key]
        bar = df.iloc[idx]
        cfg = STRATEGY_TRACKS[t_key]
        current_w = total_wallet if mode == 'COMBINED' else wallets[t_key]

        # 4.1 持倉處理 (移保本 + 止盈)
        if t_key in positions:
            pos = positions[t_key]
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
                    exit_price = pos['sl']
                    pnl = qty * (exit_price - entry) - (qty * (entry + exit_price) * FEE_RATE)
                    if mode == 'COMBINED': total_wallet += pnl
                    else: wallets[t_key] += pnl
                    track_stats[t_key]['trades'] += 1
                    track_stats[t_key]['pnl'] += pnl
                    if pnl > 0: track_stats[t_key]['wins'] += 1
                    completed_trades.append({'track': t_key, 'pnl': pnl, 'type': 'SL/BE'})
                    del positions[t_key]
                    continue

                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - (qty * (entry + tp) * FEE_RATE)
                    if mode == 'COMBINED': total_wallet += pnl
                    else: wallets[t_key] += pnl
                    track_stats[t_key]['trades'] += 1
                    track_stats[t_key]['wins'] += 1
                    track_stats[t_key]['pnl'] += pnl
                    completed_trades.append({'track': t_key, 'pnl': pnl, 'type': 'TP'})
                    del positions[t_key]
                    continue

            elif side == 'SHORT':
                if not is_be_moved and bar['l'] <= be_target:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True

                if bar['h'] >= pos['sl']:
                    exit_price = pos['sl']
                    pnl = qty * (entry - exit_price) - (qty * (entry + exit_price) * FEE_RATE)
                    if mode == 'COMBINED': total_wallet += pnl
                    else: wallets[t_key] += pnl
                    track_stats[t_key]['trades'] += 1
                    track_stats[t_key]['pnl'] += pnl
                    if pnl > 0: track_stats[t_key]['wins'] += 1
                    completed_trades.append({'track': t_key, 'pnl': pnl, 'type': 'SL/BE'})
                    del positions[t_key]
                    continue

                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - (qty * (entry + tp) * FEE_RATE)
                    if mode == 'COMBINED': total_wallet += pnl
                    else: wallets[t_key] += pnl
                    track_stats[t_key]['trades'] += 1
                    track_stats[t_key]['wins'] += 1
                    track_stats[t_key]['pnl'] += pnl
                    completed_trades.append({'track': t_key, 'pnl': pnl, 'type': 'TP'})
                    del positions[t_key]
                    continue

        # 4.2 開倉判定
        current_w = total_wallet if mode == 'COMBINED' else wallets[t_key]
        if t_key not in positions and current_w > 5.0:
            macro_trend = bar['macro_filter']
            sig_side = None
            entry, sl, tp, be_target = 0.0, 0.0, 0.0, 0.0
            be_r = cfg['be_r']
            tp_r = cfg['tp_r']

            if macro_trend == 1 and bar['c'] > bar['dc_high']:
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_target = entry + (risk_dist * be_r)
                tp = entry + (risk_dist * tp_r)

            elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_target = entry - (risk_dist * be_r)
                tp = entry - (risk_dist * tp_r)

            if sig_side and risk_dist > 0:
                qty = (current_w * RISK_PCT) / risk_dist
                if (qty * entry) > (current_w * MAX_LEVERAGE):
                    qty = (current_w * MAX_LEVERAGE) / entry

                positions[t_key] = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_target, 'is_be_moved': False, 'qty': qty
                }

    # 5. 統計與格式化報表
    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0]) if total_trades > 0 else 0
    overall_win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0

    if mode == 'COMBINED':
        roi_pct = ((total_wallet - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
        final_str = f"${format_full_num(total_wallet, 2)} USD ({roi_pct:+.2f}%)"
        init_str = f"${format_full_num(INITIAL_CAPITAL)} USD"
    else:
        tot_init = INITIAL_CAPITAL * 3
        tot_final = sum(wallets.values())
        roi_pct = ((tot_final - tot_init) / tot_init) * 100
        w1 = wallets['XAU_4H']
        w2 = wallets['XAU_1H']
        w3 = wallets['MSFT_4H']
        final_str = f"${format_full_num(tot_final, 2)} USD ({roi_pct:+.2f}\%)\n(各軌結餘: XAU_4H=${w1:.2f} | XAU_1H=${w2:.2f} \vert{} MSFT_4H=${w3:.2f})"
        init_str = f"${format_full_num(tot_init)} USD (每軌各 $100)"

    mode_title = "【三軌合併共享資金池 (極致動態複利)】" if mode == 'COMBINED' else "【三軌獨立帳戶 (風險完全隔離)】"

    track_lines = []
    for t_key, r in track_stats.items():
        name = STRATEGY_TRACKS[t_key]['name']
        c = r['trades']
        w = r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        pnl_val = r['pnl']
        track_lines.append(f"• {name.ljust(15)} | 交易: {str(c).rjust(3)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {pnl_val:+10.2f}")

    report_text = (
        "```text\n"
        f"判定邏輯: {mode_title}\n"
        f"回測週期: {period_title} ({earliest_start} ~ {latest_end})\n"
        f"初始資金: {init_str}\n"
        f"最終結餘: {final_str}\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.2f}%\n"
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
    # 1. 執行【獨立帳戶模式】(30 天 & 365 天)
    print("==================== 執行：三軌獨立帳戶回測 ====================")
    run_unified_backtest(days=30, mode='ISOLATED')
    time.sleep(2)
    run_unified_backtest(days=365, mode='ISOLATED')
    time.sleep(3)

    # 2. 執行【合併共享資金池模式】(30 天 & 365 天)
    print("\n==================== 執行：三軌合併共享資金池回測 ====================")
    run_unified_backtest(days=30, mode='COMBINED')
    time.sleep(2)
    run_unified_backtest(days=365, mode='COMBINED')
