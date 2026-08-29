import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# 支援從環境變數或直接讀取設定
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "你的Discord網址")

def run_backtest():
    # 抓取過去一年的比特幣 1 小時歷史數據進行回測模擬
    df = yf.download("BTC-USDT", period="1y", interval="1h", progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)

    # 計算技術指標
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()

    tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
    df['atr'] = tr.rolling(14).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    # 模擬回測
    initial_balance = 100.0
    balance = initial_balance
    trades = []
    wins = 0

    for i in range(50, len(df) - 1):
        current_risk = balance * 0.01  # 1% 動態風控
        bar = df.iloc[i]
        
        sub = df.iloc[i-25:i+1]
        h, l = sub['high'].max(), sub['low'].min()
        wave = h - l
        
        if wave <= 0:
            continue
            
        fib_0618_l = h - (wave * 0.618)
        entry_price = bar['close']
        
        # 多頭進場條件
        cond_long = (bar['close'] >= bar['ema50']) and (bar['ema50'] >= bar['ema200']) and (bar['low'] <= fib_0618_l * 1.002)
        
        if cond_long:
            sl = min(l, entry_price - (bar['atr'] * 1.5))
            tp1 = entry_price + abs(entry_price - sl)
            
            next_bar = df.iloc[i+1]
            if next_bar['low'] <= sl:
                balance -= current_risk
                trades.append(-1)
            elif next_bar['high'] >= tp1:
                balance += current_risk * 1.5
                wins += 1
                trades.append(1.5)

    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    profit_loss_pct = ((balance - initial_balance) / initial_balance) * 100

    # 組合 Discord 推播訊息
    report = [
        "📊 **[策略回測報告] 過去一年歷史模擬績效**",
        "```text",
        f"初始資金: ${initial_balance:.2f} USDT",
        f"最終結餘: ${balance:.2f} USDT ({profit_loss_pct:+.2f}%)",
        f"總交易次數: {total_trades} 次",
        f"勝率: {win_rate:.1f}%",
        "----------------------------------------------------",
        "策略核心: EMA50/200 趨勢 + Fib 0.618 回撤 + 1% 動態風控",
        "```"
    ]
    
    msg = "\n".join(report)
    
    # 發送到 Discord
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "你的Discord網址":
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=8)
        except Exception:
            pass

    print(msg)

if __name__ == '__main__':
    run_backtest()
