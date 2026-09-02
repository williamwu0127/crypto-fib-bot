import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'ETH':   {'s': 'ETHUSDT',  'interval': '15m', 'lev': 100.0, 'mode': 'ict_2022'},
    'SOL':   {'s': 'SOLUSDT',  'interval': '15m', 'lev': 20.0,  'mode': 'ict_2022'},
    'XAU':   {'s': 'PAXGUSDT', 'interval': '4h',  'lev': 10.0,  'mode': 'gold_donchian'},
    'MSFT':  {'s': 'MSFTUSDT', 'interval': '4h',  'lev': 10.0,  'mode': 'gold_donchian'},
    'MU':    {'s': 'MUUSDT',   'interval': '4h',  'lev': 10.0,  'mode': 'gold_donchian'}
}

INITIAL_WALLET = 100.0

def format_full_num(val, max_dec=8):
    try:
        f = float(val)
        s = f"{f:.{max_dec}f}".rstrip('0').rstrip('.')
        return s if s else "0"
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

def fetch_historical_data(cfg, days=365):
    try:
        fetch_days = 60 if days <= 30 else days
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (fetch_days * 24 * 60 * 60 * 1000)
        all_klines = []
        curr_start = start_ms
        
        while curr_start < now_ms:
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={cfg['interval']}&startTime={curr_start}&limit=1000"
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            all_klines.extend(res)
            if len(res) < 1000:
                break
            curr_start = int(res[-1][0]) + 1
            time.sleep(0.04)
        
        if len(all_klines) > 10:
            cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
            df = pd.DataFrame(all_klines, columns=cols)
            df = df.drop_duplicates(subset=['t']).sort_values('t').reset_index(drop=True)
            for col in ['o', 'h', 'l', 'c', 'v']:
                df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize(None)
            
            if days <= 30:
                cutoff_time = df['time'].max() - timedelta(days=30)
                df = df[df['time'] >= cutoff_time].reset_index(drop=True)
            return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
    except Exception:
        pass
    return None

def prepare_indicators(df, mode):
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    # ICT FVG 偵測：當前 K 線與兩根前 K 線之間是否有價格缺口
    df['fvg_bull'] = (df['l'] > df['h'].shift(2))
    df['fvg_bear'] = (df['h'] < df['l'].shift(2))
    
    if mode == 'gold_donchian':
        df['dc_high'] = df['h'].shift(1).rolling(20).max()
        df['dc_low'] = df['l'].shift(1).rolling(20).min()
    return df

def execute_backtest_run(days_target, label_str):
    print("==================================================")
    print(f">>> 啟動【ICT 2022 模型 + 結構防守】{label_str} 回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USDT")
    print("==================================================\n")

    dfs = {}
    fetch_status = []
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        df = fetch_historical_data(cfg, days=days_target)
        if df is not None and len(df) > 10:
            df = prepare_indicators(df, cfg['mode'])
            dfs[sym] = df
            s_date = pd.to_datetime(df.iloc[min(20, len(df)-1)]['time']).strftime("%Y-%m-%d")
            e_date = pd.to_datetime(df.iloc[-1]['time']).strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start:
                earliest_start = s_date
            if latest_end is None or e_date > latest_end:
                latest_end = e_date
            fetch_status.append(f"{sym}: 🟢")
        else:
            fetch_status.append(f"{sym}: 🔴")

    if not dfs:
        return

    all_timestamps = sorted(list(set([t for df in dfs.values() for t in df['time']])))
    current_wallet = float(INITIAL_WALLET)
    positions = {}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    for curr_time in all_timestamps:
        for sym, df in dfs.items():
            match_row = df[df['time'] == curr_time]
            if match_row.empty:
                continue
            idx = match_row.index[0]
            if idx < 25:
                continue
            
            bar = match_row.iloc[0]
            cfg = SYMBOLS[sym]
            mode = cfg['mode']
            hour = pd.to_datetime(bar['time']).hour

            # ICT Killzone 篩選：紐約時段（UTC 12:00 ~ 16:00 相當於台東時間晚上 20:00 ~ 00:00）
            is_killzone = (12 <= hour <= 16) if mode == 'ict_2022' else True

            # 1. 持倉處理
            if sym in positions:
                pos = positions[sym]
                side = pos['side']
                entry = pos['entry']
                sl = pos['sl']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                qty = pos['qty']
                tp1_hit = pos['tp1_hit']

                if side == 'LONG':
                    if bar['l'] <= sl:
                        pnl = qty * (sl - entry)
                        current_wallet += pnl
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['pnl'] += pnl
                        if pnl > 0:
                            symbol_stats[sym]['wins'] += 1
                        completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL', 'time': curr_time})
                        del positions[sym]
                        continue
                    if not tp1_hit and bar['h'] >= tp1:
                        pos['tp1_hit'] = True
                        pnl_tp1 = (qty * 0.5) * (tp1 - entry)
                        current_wallet += pnl_tp1
                        pos['sl'] = entry # 移動保本
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp1
                    if pos['tp1_hit'] and bar['h'] >= tp2:
                        pnl_tp2 = (qty * 0.5) * (tp2 - entry)
                        current_wallet += pnl_tp2
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp1 + pnl_tp2, 'type': 'TP2', 'time': curr_time})
                        del positions[sym]
                        continue
                else:
                    if bar['h'] >= sl:
                        pnl = qty * (entry - sl)
                        current_wallet += pnl
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['pnl'] += pnl
                        if pnl > 0:
                            symbol_stats[sym]['wins'] += 1
                        completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL', 'time': curr_time})
                        del positions[sym]
                        continue
                    if not tp1_hit and bar['l'] <= tp1:
                        pos['tp1_hit'] = True
                        pnl_tp1 = (qty * 0.5) * (entry - tp1)
                        current_wallet += pnl_tp1
                        pos['sl'] = entry
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp1
                    if pos['tp1_hit'] and bar['l'] <= tp2:
                        pnl_tp2 = (qty * 0.5) * (entry - tp2)
                        current_wallet += pnl_tp2
                        symbol_stats[sym]['trades'] += 1
                        symbol_stats[sym]['wins'] += 1
                        symbol_stats[sym]['pnl'] += pnl_tp2
                        completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp1 + pnl_tp2, 'type': 'TP2', 'time': curr_time})
                        del positions[sym]
                        continue

            # 2. 開倉信號判定 (ICT 2022 模型)
            if sym not in positions and current_wallet > 5.0 and is_killzone:
                sig_side = None
                entry, sl, tp1, tp2 = 0, 0, 0, 0

                if mode == 'ict_2022':
                    sub = df.iloc[idx-20:idx]
                    prev_low = sub['l'].min()
                    prev_high = sub['h'].max()
                    
                    # 條件：流動性獵取（插針突破前低/前高後收回） + 伴隨 FVG 缺口
                    sweep_low = (bar['l'] < prev_low) and (bar['c'] > prev_low)
                    sweep_high = (bar['h'] > prev_high) and (bar['c'] < prev_high)

                    if sweep_low and bar['fvg_bull']:
                        sig_side = 'LONG'
                        entry = bar['c']
                        sl = bar['l'] - (bar['c'] * 0.002) # 結構防守：插針極值下方
                        tp1 = prev_high
                        tp2 = prev_high + (prev_high - entry)
                    elif sweep_high and bar['fvg_bear']:
                        sig_side = 'SHORT'
                        entry = bar['c']
                        sl = bar['h'] + (bar['c'] * 0.002) # 結構防守：插針極值上方
                        tp1 = prev_low
                        tp2 = prev_low - (entry - prev_low)
                elif mode == 'gold_donchian':
                    macro_trend = 1 if bar['c'] > bar['ema200'] else -1
                    if macro_trend == 1 and bar['c'] > bar['dc_high']:
                        sig_side = 'LONG'
                        entry = bar['c']
                        sl = bar['dc_low']
                        tp1 = bar['dc_high'] + (bar['dc_high'] - bar['dc_low'])
                        tp2 = entry + ((entry - sl) * 3.0)
                    elif macro_trend == -1 and bar['c'] < bar['dc_low']:
                        sig_side = 'SHORT'
                        entry = bar['c']
                        sl = bar['dc_high']
                        tp1 = bar['dc_low'] - (bar['dc_high'] - bar['dc_low'])
                        tp2 = entry - ((sl - entry) * 3.0)

                if sig_side:
                    target_lev = cfg['lev']
                    notional_value = (current_wallet * 0.02) * target_lev
                    qty = notional_value / entry
                    positions[sym] = {
                        'side': sig_side, 'entry': entry, 'sl': sl,
                        'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty
                    }

    total_trades = len(completed_trades)
    win_trades = len([t for t in completed_trades if t['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, r in symbol_stats.items():
        c = r['trades']
        w = r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {r['pnl']:+12.6f}")

    status_block = " | ".join(fetch_status)
    report_text = (
        "```text\n"
        f"【ICT 回測狀態 ({label_str})】\n"
        + status_block + "\n"
        "----------------------------------------------------\n"
        f"策略: ICT Killzone + FVG + 結構防守 + {label_str}回測\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 6)} USDT ({roi_pct:+.4f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print("\n" + report_text)
    send_discord_safe(report_text)

if __name__ == '__main__':
    execute_backtest_run(30, "30d")
    execute_backtest_run(365, "365d")
