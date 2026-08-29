import os
import time
import requests
import urllib.parse
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ACCOUNT_BALANCE = 10000.0  # 模擬本金 10,000 USD
RISK_PER_TRADE = 150.0     # 單筆固定風險 1.5% = 150 USD

# 14 檔主流與美股資產配置 (已移除迷因幣)
SYMBOL_CONFIG = {
    'BTC': {'type': 'binance', 'pair': 'BTCUSDT', 'curr': 'USDT', 'margin': 1500},
    'ETH': {'type': 'binance', 'pair': 'ETHUSDT', 'curr': 'USDT', 'margin': 1200},
    'XAU': {'type': 'binance', 'pair': 'PAXGUSDT', 'curr': 'USDT', 'margin': 1800},
    'CLU': {'type': 'stock', 'ticker': 'CL=F', 'curr': 'USD', 'margin': 1000},
    'TSM': {'type': 'stock', 'ticker': 'TSM', 'curr': 'USD', 'margin': 1500},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA', 'curr': 'USD', 'margin': 2000},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA', 'curr': 'USD', 'margin': 1800},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL', 'curr': 'USD', 'margin': 1500},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL', 'curr': 'USD', 'margin': 1500},
    'MU': {'type': 'stock', 'ticker': 'MU', 'curr': 'USD', 'margin': 1200},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN', 'curr': 'USD', 'margin': 1600},
    'GLW': {'type': 'stock', 'ticker': 'GLW', 'curr': 'USD', 'margin': 1000},
    'SPCX': {'type': 'stock', 'ticker': 'SPCX', 'curr': 'USD', 'margin': 800},
    'SNDK': {'type': 'stock', 'ticker': 'SNDK', 'curr': 'USD', 'margin': 1500}
}

TIMEFRAME = '15m'
FETCH_LIMIT = 500
BINANCE_MIRROR = "https://data-api.binance.vision/api/v3/klines"

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print(content)
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

def get_kline_df(cfg):
    t = cfg['type']
    if t == 'binance':
        encoded_pair = urllib.parse.quote(cfg['pair'])
        url = f"{BINANCE_MIRROR}?symbol={encoded_pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 50:
                    df = pd.DataFrame(data, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                    ])
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = df[col].astype(float)
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
                    return df
        except Exception:
            pass

    elif t == 'stock':
        try:
            df = yf.download(cfg['ticker'], period="5d", interval="15m", progress=False)
            if not df.empty and len(df) >= 50:
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                
                time_col = 'datetime' if 'datetime' in df.columns else 'date'
                df['datetime'] = pd.to_datetime(df[time_col]).dt.strftime('%m/%d %H:%M')
                return df[['datetime', 'open', 'high', 'low', 'close', 'volume']]
        except Exception:
            pass

    return None

def backtest_strategy(name, cfg):
    df = get_kline_df(cfg)
    if df is None or len(df) < 50:
        return f"❌ {name:<8} : 數據抓取失敗", []

    df['rsi'] = calculate_rsi(df['close'], period=14)
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    trades = []
    i = 35
    while i < len(df) - 1:
        sub = df.iloc[i-25:i+1]
        sw_high = sub['high'].max()
        sw_low = sub['low'].min()
        wave = sw_high - sw_low

        if wave <= 0 or (wave / sw_low) < 0.003:
            i += 1
            continue

        candle = df.iloc[i]
        entry_price = candle['close']

        fib_0618_long = sw_high - (wave * 0.618)
        fib_0382_long = sw_high - (wave * 0.382)
        fib_0618_short = sw_low + (wave * 0.618)
        fib_0382_short = sw_low + (wave * 0.382)

        body_size = abs(candle['close'] - candle['open'])
        lower_wick = min(candle['open'], candle['close']) - candle['low']
        upper_wick = candle['high'] - max(candle['open'], candle['close'])

        trade_side = None
        stop_loss = 0
        tp1 = 0
        tp2 = 0

        trend_bullish = candle['close'] >= candle['ema50']
        trend_bearish = candle['close'] <= candle['ema50']

        rejection_long = (lower_wick >= body_size * 0.6) or (candle['close'] > candle['open'])
        if trend_bullish and (candle['low'] <= fib_0618_long * 1.002) and (candle['close'] >= sw_low) and rejection_long and (candle['rsi'] <= 50):
            trade_side = "LONG"
            stop_loss = sw_low * 0.997
            tp1 = fib_0382_long
            tp2 = sw_high

        rejection_short = (upper_wick >= body_size * 0.6) or (candle['close'] < candle['open'])
        if trend_bearish and (candle['high'] >= fib_0618_short * 0.998) and (candle['close'] <= sw_high) and rejection_short and (candle['rsi'] >= 50):
            trade_side = "SHORT"
            stop_loss = sw_high * 1.003
            tp1 = fib_0382_short
            tp2 = sw_low

        if trade_side:
            outcome = "HOLDING"
            r_profit = 0.0
            bars_held = 0

            for j in range(i + 1, min(i + 33, len(df))):
                fbar = df.iloc[j]
                bars_held += 1

                if trade_side == "LONG":
                    if fbar['low'] <= stop_loss:
                        outcome = "SL"
                        r_profit = -1.0
                        break
                    elif fbar['high'] >= tp2:
                        outcome = "TP2_FULL"
                        r_profit = 2.8
                        break
                    elif fbar['high'] >= tp1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"
                        r_profit = 1.0
                else:
                    if fbar['high'] >= stop_loss:
                        outcome = "SL"
                        r_profit = -1.0
                        break
                    elif fbar['low'] <= tp2:
                        outcome = "TP2_FULL"
                        r_profit = 2.8
                        break
                    elif fbar['low'] <= tp1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"
                        r_profit = 1.0

            trades.append({
                'Symbol': name,
                'Side': trade_side,
                'Time': candle['datetime'],
                'Entry': entry_price,
                'Result': outcome,
                'R_Profit': r_profit,
                'USD_Profit': r_profit * RISK_PER_TRADE,
                'Margin': cfg['margin'],
                'Curr': cfg['curr']
            })

            i += max(bars_held, 3)
        else:
            i += 1

    status_msg = f"✅ {name:<8} [{cfg['type']:<7}] : 載入 {len(df):3d} 根 K 線 | 觸發 {len(trades):2d} 次交易"
    return status_msg, trades

def main():
    send_discord_alert("🧪 **[主流/美股資產趨勢回測] 啟動成本與收益預期計算...**")
    
    status_log = []
    all_trades = []

    for name, cfg in SYMBOL_CONFIG.items():
        log_line, trades = backtest_strategy(name, cfg)
        status_log.append(log_line)
        all_trades.extend(trades)
        time.sleep(0.1)

    status_summary = "📋 **[標的數據與訊號掃描總覽]**\n```text\n" + "\n".join(status_log) + "\n```"
    send_discord_alert(status_summary)

    if not all_trades:
        send_discord_alert("📊 **[回測結果]** 本週期內無符合條件之進場點。")
        return

    res_df = pd.DataFrame(all_trades)
    total_trades = len(res_df)
    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    total_net_usd = res_df['USD_Profit'].sum()
    total_r = res_df['R_Profit'].sum()
    roi_percent = (total_net_usd / ACCOUNT_BALANCE) * 100

    # 彙總各幣種投入與收益
    sym_group = res_df.groupby('Symbol').agg({
        'Result': 'count',
        'Margin': 'first',
        'R_Profit': 'sum',
        'USD_Profit': 'sum'
    }).reset_index()

    breakdown_text = f"{'標的':<6} | {'次數':<4} | {'預估保證金':<9} | {'淨收益 (USD)'}\n"
    breakdown_text += "-" * 42 + "\n"
    for _, row in sym_group.iterrows():
        breakdown_text += f"{row['Symbol']:<6} | {row['Result']:<4} | ${row['Margin']:<7} | {row['USD_Profit']:>+9.2f} USD\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 主流/美股波段收益與資金報告**\n"
        f"```text\n"
        f"帳戶本金規模: ${ACCOUNT_BALANCE:,.2f} USD \vert{} 單筆固定風險: ${RISK_PER_TRADE:,.2f} USD (1.5%)\n"
        f"總進場次數  : {total_trades} 次 | TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次 | SL 停損: {sl_count} 次 | 未結: {holding_count} 次\n"
        f"單週累計 R 數: {total_r:+.1f} R\n"
        f"預期總淨利潤: {total_net_usd:+,.2f} USD (本金收益率: {roi_percent:+.1f}%)\n"
        f"------------------------------------------\n"
        f"各資產投入成本與收益明細:\n"
        f"{breakdown_text}"
        f"```"
    )
    send_discord_alert(report_msg)
    print("=== 回測完成 ===")

if __name__ == '__main__':
    main()
