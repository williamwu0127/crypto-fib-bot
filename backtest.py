import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543232326446616587/jD-7MeG_ODq-jUjqqHHOi90g0NaiDWzl-ykTZQxlQA_DdWqaQHk1fS4dOdem8Rp5XDJB")

SYMBOLS = {
    'BTC':   {'t': 'binance', 's': 'BTCUSDT'},
    'ETH':   {'t': 'binance', 's': 'ETHUSDT'},
    'SOL':   {'t': 'binance', 's': 'SOLUSDT'},
    'BNB':   {'t': 'binance', 's': 'BNBUSDT'},
    'DOGE':  {'t': 'binance', 's': 'DOGEUSDT'},
    'XAU':   {'t': 'binance', 's': 'PAXGUSDT'},
    'CLU':   {'t': 'stock',   's': 'CL=F'},
    'TSM':   {'t': 'stock',   's': 'TSM'},
    'NVDA':  {'t': 'stock',   's': 'NVDA'},
    'AMD':   {'t': 'stock',   's': 'AMD'},
    'MSFT':  {'t': 'stock',   's': 'MSFT'},
    'AAPL':  {'t': 'stock',   's': 'AAPL'},
    'GOOGL': {'t': 'stock',   's': 'GOOGL'},
    'AMZN':  {'t': 'stock',   's': 'AMZN'},
    'META':  {'t': 'stock',   's': 'META'},
    'TSLA':  {'t': 'stock',   's': 'TSLA'},
    'MU':    {'t': 'stock',   's': 'MU'},
    'GLW':   {'t': 'stock',   's': 'GLW'},
    'SPCX':  {'t': 'stock',   's': 'SPCX'},
    'SNDK':  {'t': 'stock',   's': 'SNDK'}
}

INITIAL_WALLET = 100.0  # 總倉位初始本金 100 USDT
RISK_PCT = 0.01         # 單筆動態風控 1%

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

def fetch_1year_historical_data(cfg):
    try:
        if cfg['t'] == 'binance':
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (365 * 24 * 60 * 60 * 1000)
            all_klines = []
            curr_start = start_ms
            
            while curr_start < now_ms:
                url = f"https://data-api.binance.vision/api/v3/klines?symbol={cfg['s']}&interval=15m&startTime={curr_start}&limit=1000"
                res = requests.get(url, timeout=10).json()
                if not isinstance(res, list) or len(res) == 0:
                    break
                all_klines.extend(res)
                curr_start = res[-1][0] + (15 * 60 * 1000)
                time.sleep(0.04)
            
            if len(all_klines) > 200:
                cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
                df = pd.DataFrame(all_klines, columns=cols)
                df = df.drop_duplicates(subset=['t'])
                for col in ['o', 'h', 'l', 'c', 'v']:
                    df[col] = df[col].astype(float)
                df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('Asia/Taipei')
                return df[['time', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
        else:
            df = yf.download(cfg['s'], period="60d", interval="15m", progress=False)
            if df is not None and not df.empty and len(df) > 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                df['time'] = df.index.tz_convert('Asia/Taipei') if df.index.tz else df.index
                res_df = df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
                res_df.columns = ['time', 'o', 'h', 'l', 'c', 'v']
                return res_df.reset_index(drop=True)
    except Exception:
        pass
    return None

def prepare_market_indicators(df):
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    tr = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
    df['atr'] = tr.rolling(14).mean().fillna(df['c'] * 0.01)

    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df['rsi_ema'] = df['rsi'].ewm(span=9, adjust=False).mean()
    return df

def run_portfolio_compounding_backtest():
    print("==================================================")
    print(">>> 啟動【總倉位 100U + 20 檔標的全域複利滾動】1 年期回測")
    print(f">>> 初始總資金: ${INITIAL_WALLET:.2f} USDT | 單筆動態風控: 1%")
    print("==================================================\n")

    dfs = {}
    earliest_start, latest_end = None, None

    for sym, cfg in SYMBOLS.items():
        print(f"正在拉取數據: {sym.ljust(5)} ...", end=" ")
        df = fetch_1year_historical_data(cfg)
        if df is not None and len(df) > 100:
            df = prepare_market_indicators(df)
            dfs[sym] = df
            s_date = df.iloc[50]['time'].strftime("%Y-%m-%d")
            e_date = df.iloc[-1]['time'].strftime("%Y-%m-%d")
            if earliest_start is None or s_date < earliest_start:
                earliest_start = s_date
            if latest_end is None or e_date > latest_end:
                latest_end = e_date
            print(f"完成 ({len(df)} 根 K 線)")
        else:
            print("資料不足略過")

    if not dfs:
        print("無可用數據。")
        return

    # 全局時間軸統一排程
    all_timestamps = sorted(list(set([t for df in dfs.values() for t in df['time']])))
    current_wallet = INITIAL_WALLET
    positions = {}  # {sym: {entry, sl, tp1, tp2, tp1_hit, qty}}
    completed_trades = []
    symbol_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in SYMBOLS.keys()}

    print(f"\n>>> 共有 {len(all_timestamps)} 個 15m 時間切片，開始逐根時間撮合與複利滾動...")

    for curr_time in all_timestamps:
        for sym, df in dfs.items():
            match_row = df[df['time'] == curr_time]
            if match_row.empty:
                continue
            idx = match_row.index[0]
            if idx < 50:
                continue
            
            bar = match_row.iloc[0]
            prev_bar = df.iloc[idx - 1]

            # 1. 持倉處理 (含 SL 上移至 TP1 鎖利機制)
            if sym in positions:
                pos = positions[sym]
                entry = pos['entry']
                sl = pos['sl']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                qty = pos['qty']
                tp1_hit = pos['tp1_hit']

                # 觸發止損 (若已碰過 TP1，此處 sl 已鎖死在 tp1 價位)
                if bar['l'] <= sl:
                    exit_price = sl
                    remaining_qty = qty * 0.5 if tp1_hit else qty
                    pnl = remaining_qty * (exit_price - entry)
                    current_wallet += pnl
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['pnl'] += pnl
                    if pnl > 0:
                        symbol_stats[sym]['wins'] += 1
                    completed_trades.append({'symbol': sym, 'pnl': pnl, 'type': 'TP1_TRAIL_SL' if tp1_hit else 'SL', 'time': curr_time})
                    del positions[sym]
                    continue

                # 觸發第一止盈 TP1 (平 50%，並立即將剩餘 50% 倉位止損上移至 TP1 鎖死利潤)
                if not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry)
                    current_wallet += pnl_tp1
                    pos['sl'] = tp1  # 止損上移至 TP1 鎖死利潤！
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp1
                    completed_trades.append({'symbol': sym, 'pnl': pnl_tp1, 'type': 'TP1', 'time': curr_time})

                # 觸發第二止盈 TP2 (平剩餘 50%)
                if pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry)
                    current_wallet += pnl_tp2
                    symbol_stats[sym]['trades'] += 1
                    symbol_stats[sym]['wins'] += 1
                    symbol_stats[sym]['pnl'] += pnl_tp2
                    completed_trades.append({'symbol': sym, 'pnl': pnl_tp2, 'type': 'TP2', 'time': curr_time})
                    del positions[sym]
                    continue

            # 2. 開倉信號判定 (單幣嚴格單持倉，以最新滾動錢包計算 1% 風險)
            if sym not in positions and current_wallet > 5.0:
                sub = df.iloc[max(0, idx-25):idx+1]
                h, l = sub['h'].max(), sub['l'].min()
                wave = h - l
                if wave <= 0 or (wave / l) < 0.005:
                    continue

                fib_0618_l = h - (wave * 0.618)
                rsi_bull = (bar['rsi'] <= 55) and (bar['rsi'] >= bar['rsi_ema'] or bar['rsi'] > prev_bar['rsi'])
                cond_long = (bar['c'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['l'] <= fib_0618_l * 1.002) and (bar['c'] >= l) and rsi_bull

                if cond_long:
                    entry = bar['c']
                    sl = min(l, entry - (bar['atr'] * 1.5))
                    tp1 = h if h > entry else entry + abs(entry - sl)
                    tp2 = h + (wave * 0.272)
                    if tp2 <= tp1:
                        tp2 = tp1 + abs(entry - sl)

                    price_diff = abs(entry - sl)
                    if price_diff > 0:
                        # 全域動態複利核心：依當前總結餘動態計算下單數量
                        dynamic_risk = current_wallet * RISK_PCT
                        qty = dynamic_risk / price_diff
                        positions[sym] = {
                            'entry': entry, 'sl': sl, 'tp1': tp1,
                            'tp2': tp2, 'tp1_hit': False, 'qty': qty
                        }

    if not completed_trades:
        print("回測期間內無交易產生。")
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
        symbol_lines.append(f"{sym.ljust(5)} | 交易: {str(c).rjust(4)}次 | 勝率: {wr:5.1f}% | 收益貢獻: {r['pnl']:+9.2f}")

    report_text = (
        "```text\n"
        "判定邏輯: 15m K線 | 總倉位100U全域複利 + 觸發TP1後SL鎖利 (1年期回測)\n"
        f"回測區間: {earliest_start} ~ {latest_end}\n"
        f"初始資金: ${INITIAL_WALLET:.1f} USDT\n"
        f"最終結餘: ${current_wallet:.2f} USDT ({roi_pct:+.2f}%)\n"
        f"總交易次數: {total_trades} 次 | 綜合勝率: {overall_win_rate:.1f}%\n"
        "----------------------------------------------------\n"
        + "\n".join(symbol_lines) + "\n"
        "```"
    )

    print("\n" + report_text)
    print(">>> 正在發送至 Discord...")
    send_discord_safe(report_text)
    print(">>> 完成推播！")

if __name__ == '__main__':
    run_portfolio_compounding_backtest()
