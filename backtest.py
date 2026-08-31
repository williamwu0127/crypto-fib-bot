"""
Crypto & Gold Backtest Engine (1D Macro Trend Filter + 4H Dual-MA System)
Supporting 1-Month and 1-Year Backtesting with Discord Webhook Notifications.
"""

import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ==================== 1. Webhook 設定 ====================
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB"
)

# ==================== 2. 標的配置 (純加密貨幣與黃金) ====================
SYMBOLS = {
    'BTC':  {'t': 'binance', 's': 'BTCUSDT',  'interval': '4h'},
    'ETH':  {'t': 'binance', 's': 'ETHUSDT',  'interval': '4h'},
    'SOL':  {'t': 'binance', 's': 'SOLUSDT',  'interval': '4h'},
    'BNB':  {'t': 'binance', 's': 'BNBUSDT',  'interval': '4h'},
    'DOGE': {'t': 'binance', 's': 'DOGEUSDT', 'interval': '4h'},
    'XAU':  {'t': 'binance', 's': 'XAUUSDT', 'interval': '4h'}
}

INITIAL_WALLET = 100.0
RISK_PCT = 0.01  # 單筆風險 1%
FEE_RATE = 0.0006  # 萬分之六單邊手續費與滑價

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

# ==================== 3. 數據抓取與雙均線指標計算 ====================
def fetch_historical_data(cfg, interval=None, days=365):
    itv = interval if interval else cfg['interval']
    try:
        now_ms = int(time.time() * 1000)
        # 多抓 90 天以確保 MA120 及日線 MA60 有足夠 K 棒初始化
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
    return None

def prepare_indicators(df_4h, df_1d):
    # 1. 4H 雙均線系統配置 (MA / EMA 20, 60, 120 共 6 條線)
    df_4h['ma20'] = df_4h['c'].rolling(20).mean()
    df_4h['ma60'] = df_4h['c'].rolling(60).mean()
    df_4h['ma120'] = df_4h['c'].rolling(120).mean()

    df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
    df_4h['ema60'] = df_4h['c'].ewm(span=60, adjust=False).mean()
    df_4h['ema120'] = df_4h['c'].ewm(span=120, adjust=False).mean()

    # 均線密集帶 (MA Band)
    df_4h['band_top'] = df_4h[['ma20', 'ema20', 'ma60', 'ema60', 'ma120', 'ema120']].max(axis=1)
    df_4h['band_bot'] = df_4h[['ma20', 'ema20', 'ma60', 'ema60', 'ma120', 'ema120']].min(axis=1)
    
    # 密集判定：6 條均線最大與最小落差在收盤價 3.5% 內
    df_4h['is_squeeze'] = (df_4h['band_top'] - df_4h['band_bot']) / df_4h['c'] < 0.035

    # 均線發散判定
    df_4h['bull_div'] = (df_4h['ema20'] > df_4h['ema60']) & (df_4h['ema60'] > df_4h['ema120']) & (df_4h['ma20'] > df_4h['ma60'])
    df_4h['bear_div'] = (df_4h['ema20'] < df_4h['ema60']) & (df_4h['ema60'] < df_4h['ema120']) & (df_4h['ma20'] < df_4h['ma60'])

    # 成交量防濾網 (大於 20 期均量 1.2 倍)
    df_4h['vol_ma20'] = df_4h['v'].rolling(20).mean()
    df_4h['vol_surge'] = df_4h['v'] >= (1.2 * df_4h['vol_ma20'])

    # 2. 日線趨勢濾網 (日線 MA60 / EMA120)
    df_1d['daily_ma60'] = df_1d['c'].rolling(60).mean()
    df_1d['daily_trend'] = np.where(df_1d['c'] > df_1d['daily_ma60'], 1, -1)

    df_4h['daily_date'] = df_4h['time'].dt.floor('D')
    df_1d['daily_date'] = df_1d['time'].dt.floor('D')
    daily_map = df_1d.drop_duplicates(subset=['daily_date']).set_index('daily_date')['daily_trend'].to_dict()
    df_4h['macro_filter'] = df_4h['daily_date'].map(daily_map).ffill().fillna(0)

    return df_4h

# ==================== 4. 事件驅動撮合回測引擎 ====================
def run_backtest(days=365):
    period_title = "1 年期" if days >= 365 else f"{days} 天期"
    print("=" * 60)
    print(f">>> 啟動【純加密貨幣 + 黃金 (日線大趨勢定錨 + 4H 雙均線系統 + 階梯平倉)】{period_title}回測")
    print(f">>> 初始本金: ${INITIAL_WALLET} USDT | 單筆風控: {RISK_PCT*100}% | 手續費: {FEE_RATE*100}%")
    print("=" * 60 + "\n")

    dfs_trade = {}
    events = []
    earliest_start, latest_end = None, None
    now_ms = int(time.time() * 1000)
    start_filter_time = pd.to_datetime(now_ms - (days * 24 * 60 * 60 * 1000), unit='ms')

    for sym, cfg in SYMBOLS.items():
        print(f"拉取數據: {sym.ljust(5)} (4h + 1d MTF) ...", end=" ", flush=True)
        df_4h = fetch_historical_data(cfg, interval='4h', days=days)
        df_1d = fetch_historical_data(cfg, interval='1d', days=days)
        
        if df_4h is not None and len(df_4h) > 130 and df_1d is not None and len(df_1d) > 65:
            df_prepared = prepare_indicators(df_4h, df_1d)
            # 截取所選回測期間
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

    print(f"\n>>> 共有 {len(events)} 個市場事件，開始逐根 K 線即時撮合...", flush=True)

    for event_time, sym, idx in events:
        df = dfs_trade[sym]
        bar = df.iloc[idx]
        prev_bar = df.iloc[idx - 1]

        # 1. 持倉狀態檢查與平倉 (階梯止盈：TP1 達 1:1.5 平 50% 且 SL 移至開倉價，TP2 達 1:3 全平)
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
                # 止損觸發
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - (rem_qty * (entry + sl) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0:
                        symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'type': 'SL/BE', 'time': event_time})
                    del positions[sym]
                    continue
                # TP1 觸發 (平 50%，止損移至成本線)
                if not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry) - ((qty * 0.5) * (entry + tp1) * FEE_RATE)
                    current_wallet += pnl_tp1
                    pos['sl'] = entry  # 移至保本損
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp1
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp1, 'type': 'TP1', 'time': event_time})
                # TP2 觸發 (平剩餘 50%)
                if pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry) - ((qty * 0.5) * (entry + tp2) * FEE_RATE)
                    current_wallet += pnl_tp2
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp2
                    completed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl_tp2, 'type': 'TP2', 'time': event_time})
                    del positions[sym]
                    continue

            elif side == 'SHORT':
                # 止損觸發
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - (rem_qty * (entry + sl) * FEE_RATE)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0:
                        symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'type': 'SL/BE', 'time': event_time})
                    del positions[sym]
                    continue
                # TP1 觸發
                if not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1) - ((qty * 0.5) * (entry + tp1) * FEE_RATE)
                    current_wallet += pnl_tp1
                    pos['sl'] = entry  # 移至保本損
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp1
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp1, 'type': 'TP1', 'time': event_time})
                # TP2 觸發
                if pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2) - ((qty * 0.5) * (entry + tp2) * FEE_RATE)
                    current_wallet += pnl_tp2
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp2
                    completed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl_tp2, 'type': 'TP2', 'time': event_time})
                    del positions[sym]
                    continue

        # 2. 開倉信號判定 (雙均線策略：密集突破開倉 + 首次回踩 20 均線)
        if sym not in positions and current_wallet > 5.0:
            sig_side = None
            entry, sl, tp1, tp2 = 0.0, 0.0, 0.0, 0.0
            macro_trend = bar['macro_filter']

            # --- 做多信號 ---
            if macro_trend == 1:
                # 模式 A: 均線密集向上突破 (前根密集 + 當根實體突破頂部帶 + 放量)
                if prev_bar['is_squeeze'] and bar['c'] > bar['band_top'] and bar['vol_surge']:
                    sig_side = 'LONG'
                    entry = bar['c']
                    sl = bar['band_bot']  # 止損設密集區底部
                # 模式 B: 多頭發散下首次回踩 20 均線不破 (收盤站穩 EMA20 / MA20 且最低價有觸及)
                elif bar['bull_div'] and (bar['l'] <= bar['ema20']) and (bar['c'] >= bar['ema20']) and (prev_bar['c'] > prev_bar['ema20']):
                    sig_side = 'LONG'
                    entry = bar['c']
                    sl = min(bar['ma20'], bar['ema20']) * 0.995  # 止損設 20 均線微下方

                if sig_side == 'LONG':
                    r = entry - sl
                    if r > 0 and (r / entry) >= 0.003:  # 確保止損空間合理
                        tp1 = entry + (r * 1.5)
                        tp2 = entry + (r * 3.0)
                    else:
                        sig_side = None

            # --- 做空信號 ---
            elif macro_trend == -1:
                # 模式 A: 均線密集跌破
                if prev_bar['is_squeeze'] and bar['c'] < bar['band_bot'] and bar['vol_surge']:
                    sig_side = 'SHORT'
                    entry = bar['c']
                    sl = bar['band_top']  # 止損設密集區頂部
                # 模式 B: 空頭發散下首次回踩 20 均線不破
                elif bar['bear_div'] and (bar['h'] >= bar['ema20']) and (bar['c'] <= bar['ema20']) and (prev_bar['c'] < prev_bar['ema20']):
                    sig_side = 'SHORT'
                    entry = bar['c']
                    sl = max(bar['ma20'], bar['ema20']) * 1.005

                if sig_side == 'SHORT':
                    r = sl - entry
                    if r > 0 and (r / entry) >= 0.003:
                        tp1 = entry - (r * 1.5)
                        tp2 = entry - (r * 3.0)
                    else:
                        sig_side = None

            # 計算部位大小 (依據 1% 風控金額反推，實際槓桿最高限制 5 倍)
            if sig_side:
                risk_dist = abs(entry - sl)
                qty = (current_wallet * RISK_PCT) / risk_dist
                # 限制最大實際名義名額不超過當前總資金 5 倍
                if (qty * entry) > (current_wallet * 5.0):
                    qty = (current_wallet * 5.0) / entry
                    
                positions[sym] = {
                    'side': sig_side, 'entry': entry, 'sl': sl,
                    'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty
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
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.2f}% | 收益貢獻: {r['pnl']:+12.6f}")

    report_text = (
        "```text\n"
        f"判定邏輯: 純加密貨幣+黃金 (日線大趨勢定錨 + 4H雙均線系統 + 階梯平倉)\n"
        f"回測週期: {period_title} ({earliest_start} ~ {latest_end})\n"
        f"初始資金: ${format_full_num(INITIAL_WALLET)} USDT\n"
        f"最終結餘: ${format_full_num(current_wallet, 6)} USDT ({roi_pct:+.4f}%)\n"
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
