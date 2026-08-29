import os
import time
import requests
import ccxt
import pandas as pd

# 1. 讀取 Discord Webhook URL (由 GitHub Secrets 注入)
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

TIMEFRAME = '15m'  # K 線週期：15 分鐘

def send_discord_alert(content):
    """發送 Discord 訊息"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print(f"發送 Discord 失敗: {err}")

def calculate_rsi(series, period=14):
    """計算標準 RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def evaluate_resonance(exchange, symbol, market_type="Crypto"):
    display_name = symbol.split(':')[0]
    try:
        # 抓取 100 根 K 線 (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        if len(df) < 35:
            return "INSUFFICIENT_DATA"

        # 技術指標計算
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        # 計算過去 30 根 K 線的波段高低點與斐波那契點位
        swing_high = df['high'][-30:].max()
        swing_low = df['low'][-30:].min()
        fib_range = swing_high - swing_low

        fib_0618 = swing_high - (fib_range * 0.618)
        fib_0382 = swing_high - (fib_range * 0.382)
        fib_0786 = swing_high - (fib_range * 0.786)

        candle = df.iloc[-2]  # 最新收盤完成的 K 棒
        current_price = candle['close']

        lower_wick = min(candle['open'], candle['close']) - candle['low']
        body_size = abs(candle['close'] - candle['open'])

        # 共振條件判定
        hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
        rsi_oversold = candle['rsi'] <= 35
        hammer_candle = lower_wick > (body_size * 1.5)
        vol_spike = candle['volume'] > (candle['vol_sma'] * 1.5)

        # 自動計算 TP / SL 與盈虧比
        stop_loss = min(candle['low'] * 0.998, fib_0786)
        tp_1 = fib_0382
        tp_2 = swing_high

        risk = max(current_price - stop_loss, 1e-4)
        reward_tp1 = max(tp_1 - current_price, 0)
        rr_ratio = reward_tp1 / risk

        print(f"[{market_type} | {display_name}] 現價: {current_price:.2f} | 0.618位: {fib_0618:.2f} | RSI: {candle['rsi']:.2f}")

        # 階段三：完全共振進場訊號 (附帶 TP/SL)
        if hit_fib and rsi_oversold and hammer_candle and vol_spike:
            msg = (
                f"🎯 **[SIGNAL] 共振進場確認｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Market      : {market_type}\n"
                f"Entry Price : ${current_price:.2f}\n"
                f"Stop Loss   : ${stop_loss:.2f}\n"
                f"TP1 (0.382) : ${tp_1:.2f}\n"
                f"TP2 (High)  : ${tp_2:.2f}\n"
                f"Risk/Reward : 1 : {rr_ratio:.2f}\n"
                f"Condition   : Fib 0.618 + RSI 超賣 ({candle['rsi']:.1f}) + 爆量長下影\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_3"

        # 階段二：動能預警
        elif hit_fib and rsi_oversold:
            msg = (
                f"⚡ **[ALERT] 動能反轉預警｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Market: {market_type} | Price: ${current_price:.2f} | Fib 0.618: ${fib_0618:.2f} | RSI: {candle['rsi']:.1f}\n"
                f"Status: 觸及 0.618 且 RSI 超賣，待 K 棒收線確認。\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_2"

        # 階段一：觸及支撐
        elif hit_fib:
            msg = (
                f"👀 **[WATCH] 觸及關鍵支撐｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Market: {market_type} | Price: ${current_price:.2f} \vert{} Fib 0.618:${fib_0618:.2f} | RSI: {candle['rsi']:.1f}\n"
                f"Status: 價格回落至 Fib 0.618 區間。\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_1"

        return "NO_SIGNAL"

    except Exception as e:
        print(f"檢查標的 {symbol} 略過: {e}")
        return "ERROR"

def main():
    send_discord_alert("📡 **系統啟動：開始執行市場掃描...**")
    
    # 建立幣安現貨與合約連線
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()
    triggered_count = 0

    # 1. 掃描加密貨幣
    for sym in CRYPTO_SYMBOLS:
        status = evaluate_resonance(spot_exchange, sym, market_type="Crypto")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    # 2. 掃描幣安美股永續合約
    for sym in STOCK_PERP_SYMBOLS:
        status = evaluate_resonance(perp_exchange, sym, market_type="TradFi Perp")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    # 3. 本輪無訊號彙總
    if triggered_count == 0:
        total_count = len(CRYPTO_SYMBOLS) + len(STOCK_PERP_SYMBOLS)
        send_discord_alert(f"📋 **掃描完成**：共巡檢 `{total_count}` 檔標的，目前皆無共振訊號。")
        
    print("=== 全數掃描完成 ===")

if __name__ == '__main__':
    main()
