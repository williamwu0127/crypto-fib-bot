"""
Crypto & Gold Backtest Engine (1D Trend Filter + 4H Donchian/ATR + 1:5.0 High RR)
Optimized for 1-Month and 1-Year Backtesting with Discord Webhook Notifications.
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

# 標的配置：保留主力加密貨幣與現貨黃金
SYMBOLS = {
    'BTC':  {'src': 'binance', 's': 'BTCUSDT', 'interval': '4h'},
    'ETH':  {'src': 'binance', 's': 'ETHUSDT', 'interval': '4h'},
    'SOL':  {'src': 'binance', 's': 'SOLUSDT', 'interval': '4h'},
    'BNB':  {'src': 'binance', 's': 'BNBUSDT', 'interval': '4h'},
    'DOGE': {'src': 'binance', 's': 'DOGEUSDT', 'interval': '4h'},
    'XAU':  {'src': 'yahoo',   's': 'GC=F',    'interval': '1h'}  # Yahoo 國際現貨黃金
}

INITIAL_WALLET = 100.0
RISK_PCT = 0.05       # 單筆風險 5%
FEE_RATE = 0.0005     # 綜合滑價與手續費
MAX_LEVERAGE = 10.0   # 槓桿保護上限

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

# ==================== 2. 數據拉取模組 ====================
def fetch_historical_data(cfg, interval=None, days=365):
    itv = interval if interval else cfg['interval']
    
    if cfg['src'] == 'binance':
        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - ((days + 90) * 24 * 60 * 60 * 1000)
            all_klines = []
            curr_start = start_ms
            step_ms = 4 * 60 * 60 * 1000 if itv == '4h' else 24 * 60 * 60 * 1000
            
            while curr_start < now_ms:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval={itv}&startTime={curr_start}&limit=1000"
                res = requests.get(url, timeout=10).json()
                if not isinstance(res, list) or len(res) == 0:
                    break
                all_klines.extend(res)
                curr_start = res[-1][0] + step_ms
                time.sleep(0.04)
            
            if len(all_klines) > 50:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(all_klines, columns=cols)
                df = df.drop_duplicates(subset=['t'])
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms')
                return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
        except Exception:
            pass

    elif cfg['src'] == 'yahoo':
        try:
            period_str = f"{days + 90}d" if days <= 600 else "2y"
            yf_itv = '1h' if itv in ['4h', '1h'] else '1d'
            ticker = yf.Ticker(cfg['s'])
            df_y = ticker.history(period=period_str, interval=yf_itv)
            if not df_y.empty:
                df_y = df_y.reset_index()
                date_col = 'Datetime' if 'Datetime' in df_y.columns else 'Date'
                df_y['time'] = pd.to_datetime(df_y[date_col]).dt.tz_localize(None)
                df_y.rename(columns={'Open': 'o', 'High': 'h', 'Low': 'l', 'Close': 'c', 'Volume': 'v'}, inplace=True)
                
                if itv == '4h':
                    df_y.set_index('time', inplace=True)
                    df_res = df_y.resample('4h').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'}).dropna().reset_index()
                    return df_res[['time', 'o', 'h', 'l', 'c', 'v']]
                return df_y[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
        except Exception:
            pass

    return None

# ==================== 3. 指標計算 ====================
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

    # 4. 量能濾網
    df_4h['vol_ma20'] = df_4h['v'].rolling(20).mean().fillna(0)
    df_4h['vol_surge'] = (df_4h['v'] >= (1.15 * df_4h['vol_ma20'])) | (df_4h['v'] == 0)

    return df_4h

# ==================== 4. 撮合回測引擎 ====================
def run_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 65)
    print(f">>> 啟動【加密貨幣+現貨黃金 (日線定錨 + Donchian + 1:5.0 RR版)】{period_title}回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USDT | 單筆風控: {RISK_PCT*100}% | 盈虧比: 1:5.0 (2.0R保本)")
    print("=" * 65 + "\n")

    dfs_trade = {}
    events = []
    earliest_start, latest_end = None, None
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')

    for sym, cfg in SYMBOLS.items():
        print(f"拉取數據: {sym.ljust(5)} (4h + 1d MTF) ...", end=" ", flush=True)
        df_4h = fetch_historical_data(cfg, interval='4h', days=days)
        df_1d = fetch_historical_data(cfg, interval='1d', days=days)
        
        if df_4h is not None and len(df_4h) > 60 and df_1d is not None and len(df_1d) > 30:
            df_prepared = prepare_indicators(df_4h, df_1d)
            df_trade = df_prepared[df_prepared['time'] >= start_filter_time].reset_index(drop=True)
            dfs_trade[sym] = df_trade

            if len(df_trade) > 0:
                s_date = pd.to_datetime(df_trade.iloc[0]['time']).strftime("%Y-%m-%d")
                e_date = pd.to_datetime(df_trade.iloc[-1]['time']).strftime("%Y-%m-%d")
                if earliest_start is None or s_date < earliest_start:
                    earliest_start = s_date
                if latest_end is None or e_date > latest_end:
                    latest_end = e_date

                for idx in range(1, len(df_trade)):
                    events.append((df_trade.iloc[idx]['time'], sym, idx))
                print(f"完成 ({len(df_trade)} 根 4H K 線)")
        else:
            print("❌ 資料不足略過")

    if not events:
        print("無可用數據。")
        return

    events.sort(key=lambda x: x[0])
    current_wallet = float(INITIAL_WALLET)
    positions = {}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    for event_time, sym, idx in events:
        df = dfs_trade[sym]
        bar = df.iloc[idx]

        # 1. 持倉狀態檢查與平倉 (2.0R 移保本，5.0R 止盈)
        if sym in positions:
            pos = positions[sym]
            side = pos['side']
            entry = pos['entry']
            tp = pos['tp']
            be_target = pos['be_target']
            qty = pos['qty']
            is_be_moved = pos['is_be_moved']

            if side == 'LONG':
                # 達 2.0R 移動止損至開倉價保本
                if not is_be_moved and bar['h'] >= be_target:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True

                # 觸發止損 / 保本損
                if bar['l'] <= pos['sl']:
                    exit_price = pos['sl']
                    pnl = qty * (exit_price - entry) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0:
                        symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': event_time})
                    del positions[sym]
                    continue

                # 觸發 1:5.0 止盈
                if bar['h'] >= tp:
                    pnl = qty * (tp - entry) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'TP (1:5.0)', 'time': event_time})
                    del positions[sym]
                    continue

            elif side == 'SHORT':
                if not is_be_moved and bar['l'] <= be_target:
                    pos['sl'] = entry
                    pos['is_be_moved'] = True

                if bar['h'] >= pos['sl']:
                    exit_price = pos['sl']
                    pnl = qty * (entry - exit_price) - (qty * (entry + exit_price) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0:
                        symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': event_time})
                    del positions[sym]
                    continue

                if bar['l'] <= tp:
                    pnl = qty * (entry - tp) - (qty * (entry + tp) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'TP (1:5.0)', 'time': event_time})
                    del positions[sym]
                    continue

        # 2. 開倉信號判定 (4H Donchian 突破 + 1.5 ATR 止損)
        if sym not in positions and current_wallet > 5.0:
            sig_side = None
            entry, sl, tp, be_target = 0.0, 0.0, 0.0, 0.0
            macro_trend = bar['macro_filter']

            # 做多：日線多頭 + 突破 4H Donchian 高點 + 放量
            if macro_trend == 1 and bar['c'] > bar['dc_high'] and bar['vol_surge']:
                sig_side = 'LONG'
                entry = bar['c']
                sl = entry - (bar['atr'] * 1.5)
                risk_dist = entry - sl
                be_target = entry + (risk_dist * 2.0)  # 2.0R 移保本
                tp = entry + (risk_dist * 5.0)         # 5.0R 止盈

            # 做空：日線空頭 + 跌破 4H Donchian 低點 + 放量
            elif macro_trend == -1 and bar['c'] < bar['dc_low'] and bar['vol_surge']:
                sig_side = 'SHORT'
                entry = bar['c']
                sl = entry + (bar['atr'] * 1.5)
                risk_dist = sl - entry
                be_target = entry - (risk_dist * 2.0)
                tp = entry - (risk_dist * 5.0)

            if sig_side and risk_dist > 0:
                qty = (current_wallet * RISK_PCT) / risk_dist
                # 槓桿上限保護
                if (qty * entry) > (current_wallet * MAX_LEVERAGE):
                    qty = (current_wallet * MAX_LEVERAGE) / entry

                positions[sym] = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp': tp, 'be_target': be_target, 'is_be_moved': False, 'qty': qty
                }

    if not completed_trades:
        print(f"[{period_title}] 回測期間內無交易產生。")
        return

    df_res = pd.DataFrame(completed_trades)
    total_trades = len(df_res)
    win_trades = len(df_res[df_res['pnl'] > 0])
    overall_win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    roi_pct = ((current_wallet - INITIAL_WALLET) / INITIAL_WALLET) * 100

    symbol_lines = []
    for sym, r in symbol_stats.items():
        c = r['trades']
        w = r['wins']
        wr = (w / c * 100) if c > 0 else 0.0
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(3)}次 | 勝率: {wr:5.2f}% | 收益: {r['pnl']:+10.4f}")

    report_text = (
        "```text\n"
        f"判定邏輯: 加密貨幣+現貨黃金 (日線定錨 + Donchian + 1:5.0 RR高賠率版)\n"
        f"回測週期: {period_title} ({earliest_start} ~ {latest_end})\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 4)} USDT ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.2f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print("\n" + report_text)
    print(">>> 正在發送至 Discord...", end=" ", flush=True)
    send_discord_safe(report_text)
    print("完成！\n", flush=True)

if __name__ == '__main__':
    # 執行 1 個月 (30天) 回測
    run_backtest(days=30)
    time.sleep(2)
    # 執行 1 年 (365天) 回測
    run_backtest(days=365)
