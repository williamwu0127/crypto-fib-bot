import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 2. 加密貨幣監控清單 (Binance 現貨/永續合約通用)
CRYPTO_SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'PAXG/USDT',      # 黃金代幣 (XAU)
    'PLAY/USDT',
    'LAB/USDT',
    'CLU/USDT',
    '币安人生/USDT'
]

# 3. 幣安美股永續合約監控清單 (TradFi Perps)
STOCK_PERP_SYMBOLS = [
    'TSM/USDT:USDT',    # 台積電
    'NVDA/USDT:USDT',   # 輝達
    'TSLA/USDT:USDT',   # 特斯拉
    'AAPL/USDT:USDT',   # 蘋果
    'GOOGL/USDT:USDT',  # 谷歌
    'MU/USDT:USDT',     # 美光
    'AMZN/USDT:USDT',   # 亞馬遜
    'MSFT/USDT:USDT',   # 微軟
    'META/USDT:USDT',   # Meta
    'PLTR/USDT:USDT',   # Palantir
    'COIN/USDT:USDT',   # Coinbase
    'MSTR/USDT:USDT'    # 微策略
]

TIMEFRAME = '15m'
FETCH_LIMIT = 800

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
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

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def run_backtest_on_symbol(exchange, symbol, market_name):
    display_name = symbol.split(':')[0]
    records = []
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=FETCH_LIMIT)
        if not ohlcv or len(ohlcv) < 60:
            return records

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['atr'] = calculate_atr(df, period=14)
        
        # 布林通道 (20, 2.0)
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2.0)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2.0)

        i = 30
        while i < len(df) - 1:
            candle = df.iloc[i]
            entry_price = candle['close']
            atr_val = candle['atr'] if not np.isnan(candle['atr']) else entry_price * 0.005

            lower_wick = min(candle['open'], candle['close']) - candle['low']
            upper_wick = candle['high'] - max(candle['open'], candle['close'])
            body_size = abs(candle['close'] - candle['open'])

            # 多單訊號：觸及/跌破布林下軌 + RSI 超賣 (<= 38) + 下影線承接或陽線收復
            long_signal = (candle['low'] <= candle['bb_lower']) and (candle['rsi'] <= 38) and ((lower_wick >= body_size * 0.7) or (candle['close'] > candle['open']))
            
            # 空單訊號：觸及/突破布林上軌 + RSI 超買 (>= 62) + 上影線承壓或陰線回落
            short_signal = (candle['high'] >= candle['bb_upper']) and (candle['rsi'] >= 62) and ((upper_wick >= body_size * 0.7) or (candle['close'] < candle['open']))

            trade_side = None
            if long_signal:
                trade_side = "LONG"
                stop_loss = candle['low'] - (atr_val * 1.5)
                tp_1 = candle['bb_mid']
                tp_2 = candle['bb_upper']
            elif short_signal:
                trade_side = "SHORT"
                stop_loss = candle['high'] + (atr_val * 1.5)
                tp_1 = candle['bb_mid']
                tp_2 = candle['bb_lower']

            if trade_side:
                outcome = "HOLDING"
                bars_held = 0

                for j in range(i + 1, min(i + 49, len(df))):
                    future_bar = df.iloc[j]
                    bars_held += 1

                    if trade_side == "LONG":
                        if future_bar['low'] <= stop_loss:
                            outcome = "SL"
                            break
                        elif future_bar['high'] >= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif future_bar['high'] >= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"
                    else:
                        if future_bar['high'] >= stop_loss:
                            outcome = "SL"
                            break
                        elif future_bar['low'] <= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif future_bar['low'] <= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"

                records.append({
                    'Symbol': display_name,
                    'Side': trade_side,
                    'Market': market_name,
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'Result': outcome
                })

                i += max(bars_held, 2)
            else:
                i += 1

    except Exception as e:
        print(f"回測 {symbol} 略過: {e}")

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 執行「布林通道 + RSI 極值 + ATR 防守」7 天回測...**")
    
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()
    all_results = []

    for sym in CRYPTO_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(spot_exchange, sym, "現貨"))
        time.sleep(0.15)

    for sym in STOCK_PERP_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(perp_exchange, sym, "合約"))
        time.sleep(0.15)

    if not all_results:
        send_discord_alert("📋 **[BACKTEST REPORT]** 本輪未產生訊號。")
        return

    res_df = pd.DataFrame(all_results)
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
        f"📊 **[BACKTEST REPORT] 布林極值反轉 7 天回測報告 (15m)**\n"
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
    print("=== 回測完成 ===")

if __name__ == '__main__':
    main()
