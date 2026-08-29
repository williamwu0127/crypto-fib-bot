import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

TARGET_SYMBOLS = [
    'BTC', 'ETH', 'XAU', 'TSM', 'MU', 'SPCX', 'CLU', 
    'GOOGL', 'SAMSUNG', 'NVDA', 'GLW', 'TSLA', 'AAPL', 
    'LAB', 'PLAY', 'AMZN', '币安人生'
]

TIMEFRAME = '15m'
FETCH_LIMIT = 800

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        # 避免 Discord 單則訊息超過 2000 字限制
        if len(content) > 1900:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=10)
                time.sleep(0.5)
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print("推播失敗:", err)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def resolve_symbol_and_fetch(perp_ex, spot_ex, raw_name):
    """跨合約與現貨市場嘗試所有可能的代號格式"""
    candidates = []
    
    if raw_name.upper() == 'XAU':
        candidates = ['PAXG/USDT:USDT', 'PAXG/USDT', 'XAU/USDT:USDT', 'XAUUSDT']
    elif raw_name.upper() == 'CLU':
        candidates = ['CLU/USDT:USDT', 'CL/USDT:USDT', 'OIL/USDT:USDT', 'CLU/USDT', 'USO/USDT:USDT']
    else:
        candidates = [
            f"{raw_name}/USDT:USDT",
            f"{raw_name}/USDT",
            f"{raw_name}USDT",
            f"1000{raw_name}/USDT:USDT",
            f"{raw_name.upper()}/USDT:USDT",
            f"{raw_name.upper()}/USDT"
        ]

    # 1. 優先嘗試合約
    for sym in candidates:
        try:
            ohlcv = perp_ex.fetch_ohlcv(sym, TIMEFRAME, limit=FETCH_LIMIT)
            if ohlcv and len(ohlcv) >= 60:
                return f"合約:{sym}", ohlcv
        except Exception:
            pass

    # 2. 次要嘗試現貨
    for sym in candidates:
        try:
            ohlcv = spot_ex.fetch_ohlcv(sym, TIMEFRAME, limit=FETCH_LIMIT)
            if ohlcv and len(ohlcv) >= 60:
                return f"現貨:{sym}", ohlcv
        except Exception:
            pass

    return None, None

def run_backtest():
    send_discord_alert("🧪 **[BACKTEST] 啟動全透明診斷回測（掃描 17 檔標的）...**")
    
    perp_ex = ccxt.binanceusdm({'enableRateLimit': True})
    spot_ex = ccxt.binance({'enableRateLimit': True})
    
    status_log = []
    all_trades = []

    for name in TARGET_SYMBOLS:
        resolved_sym, ohlcv = resolve_symbol_and_fetch(perp_ex, spot_ex, name)
        
        if not ohlcv:
            status_log.append(f"❌ {name:<8} : 抓取失敗 (查無對應合約/現貨代碼)")
            continue

        status_log.append(f"✅ {name:<8} : 成功 ({resolved_sym}, {len(ohlcv)} 根 K 線)")

        # 執行 Fib 回測計算
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
        df['rsi'] = calculate_rsi(df['close'], period=14)

        i = 25
        while i < len(df) - 1:
            sub = df.iloc[i-20:i+1]
            sw_high = sub['high'].max()
            sw_low = sub['low'].min()
            wave = sw_high - sw_low

            if wave <= 0 or (wave / sw_low) < 0.003:
                i += 1
                continue

            candle = df.iloc[i]
            entry_price = candle['close']

            fib_long_0618 = sw_high - (wave * 0.618)
            fib_short_0618 = sw_low + (wave * 0.618)
            fib_long_0382 = sw_high - (wave * 0.382)
            fib_short_0382 = sw_low + (wave * 0.382)

            trade_side = None
            stop_loss = 0
            tp_1 = 0
            tp_2 = 0

            # 多單判定
            if candle['low'] <= fib_long_0618 * 1.002 and candle['close'] >= sw_low:
                trade_side = "LONG"
                stop_loss = sw_low * 0.997
                tp_1 = fib_long_0382
                tp_2 = sw_high

            # 空單判定
            elif candle['high'] >= fib_short_0618 * 0.998 and candle['close'] <= sw_high:
                trade_side = "SHORT"
                stop_loss = sw_high * 1.003
                tp_1 = fib_short_0382
                tp_2 = sw_low

            if trade_side:
                outcome = "HOLDING"
                bars_held = 0

                for j in range(i + 1, min(i + 33, len(df))):
                    fbar = df.iloc[j]
                    bars_held += 1

                    if trade_side == "LONG":
                        if fbar['low'] <= stop_loss:
                            outcome = "SL"
                            break
                        elif fbar['high'] >= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif fbar['high'] >= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"
                    else:
                        if fbar['high'] >= stop_loss:
                            outcome = "SL"
                            break
                        elif fbar['low'] <= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif fbar['low'] <= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"

                all_trades.append({
                    'Symbol': name,
                    'Side': trade_side,
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'Result': outcome
                })

                i += max(bars_held, 2)
            else:
                i += 1
        time.sleep(0.1)

    # 1. 發送 17 檔標的連線狀態報告
    status_msg = "🔍 **[標的連線與數據診斷報告]**\n```text\n" + "\n".join(status_log) + "\n```"
    send_discord_alert(status_msg)

    # 2. 發送回測結果報告
    if not all_trades:
        send_discord_alert("📋 **[策略統計]** 所有成功連線的標的在此區間皆未觸發進場訊號。")
        return

    res_df = pd.DataFrame(all_trades)
    total_trades = len(res_df)
    long_trades = len(res_df[res_df['Side'] == 'LONG'])
    short_trades = len(res_df[res_df['Side'] == 'SHORT'])

    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    trade_details = ""
    for _, r in res_df.head(10).iterrows():
        trade_details += f"[{r['Time']}] {r['Side']} {r['Symbol']} @ ${r['Entry']:.2f} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 斐波那契回測結果 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次 (多: {long_trades} / 空: {short_trades})\n"
        f"TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次\n"
        f"SL 停損離場 : {sl_count} 次\n"
        f"持倉/未觸發 : {holding_count} 次\n"
        f"----------------------------------------\n"
        f"近期交易明細 (前10筆):\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)

if __name__ == '__main__':
    run_backtest()
