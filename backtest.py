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

def find_matched_symbol(exchange, raw_name):
    """從已載入的市場清單中智慧匹配合適的交易對"""
    raw = raw_name.upper()
    markets = exchange.markets
    
    # 專屬別名對照
    alias_map = {
        'XAU': ['PAXG/USDT', 'PAXG/USDT:USDT', 'XAU/USDT'],
        'CLU': ['CL/USDT:USDT', 'CLU/USDT:USDT', 'OIL/USDT:USDT', 'USO/USDT:USDT'],
        '币安人生': ['LIFE/USDT', 'BINANCE/USDT']
    }
    
    if raw in alias_map:
        for candidate in alias_map[raw]:
            if candidate in markets:
                return candidate

    # 一般標的優先嘗試標準合約與現貨格式
    standard_candidates = [
        f"{raw}/USDT:USDT",
        f"{raw}/USDT",
        f"1000{raw}/USDT:USDT",
        f"{raw}USDT"
    ]
    for candidate in standard_candidates:
        if candidate in markets:
            return candidate

    # 模糊搜尋包含該名稱的 USDT 交易對
    for sym in markets.keys():
        if raw in sym and ('USDT' in sym):
            return sym

    return None

def run_backtest():
    send_discord_alert("🧪 **[BACKTEST] 初始化市場與 K 線抓取中...**")
    
    perp_ex = ccxt.binanceusdm({'enableRateLimit': True})
    spot_ex = ccxt.binance({'enableRateLimit': True})
    
    try:
        perp_ex.load_markets()
        spot_ex.load_markets()
    except Exception as e:
        send_discord_alert(f"⚠️ 市場清單載入失敗: {e}")
        return

    status_log = []
    all_trades = []

    for name in TARGET_SYMBOLS:
        ex = perp_ex
        matched_sym = find_matched_symbol(perp_ex, name)
        market_type = "合約"
        
        if not matched_sym:
            matched_sym = find_matched_symbol(spot_ex, name)
            ex = spot_ex
            market_type = "現貨"

        if not matched_sym:
            status_log.append(f"❌ {name:<8} : 幣安無對應交易對")
            continue

        try:
            ohlcv = ex.fetch_ohlcv(matched_sym, TIMEFRAME, limit=FETCH_LIMIT)
            if not ohlcv or len(ohlcv) < 50:
                status_log.append(f"⚠️ {name:<8} : K 線不足 ({matched_sym})")
                continue

            status_log.append(f"✅ {name:<8} : 成功 [{market_type}] ({matched_sym}, {len(ohlcv)} 根)")
        except Exception as err:
            status_log.append(f"❌ {name:<8} : 抓取錯誤 ({err})")
            continue

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

    # 1. 推播標的載入診斷
    status_msg = "🔍 **[標的連線與數據診斷報告]**\n```text\n" + "\n".join(status_log) + "\n```"
    send_discord_alert(status_msg)

    # 2. 推播回測統計
    if not all_trades:
        send_discord_alert("📋 **[策略統計]** 本輪成功載入之標的未產生符合條件的進場訊號。")
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
        f"近期交易明細:\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)

if __name__ == '__main__':
    run_backtest()
