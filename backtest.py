import os
import time
import requests
import urllib.parse

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 18 檔指定標的配置 (指定市場屬性：現貨 spot 或 合約 futures)
SYMBOL_CONFIG = {
    # 現貨市場標的
    'BTC': {'type': 'spot', 'symbols': ['BTCUSDT']},
    'ETH': {'type': 'spot', 'symbols': ['ETHUSDT']},
    'XAU': {'type': 'spot', 'symbols': ['PAXGUSDT']},
    '币安人生': {'type': 'spot', 'symbols': ['币安人生USDT']},

    # 合約 / 股票合約市場標的
    'PLAY': {'type': 'futures', 'symbols': ['PLAYUSDT', '1000PLAYUSDT']},
    'LAB': {'type': 'futures', 'symbols': ['LABUSDT', '1000LABUSDT']},
    'TSM': {'type': 'futures', 'symbols': ['TSMUSDT']},
    'NVDA': {'type': 'futures', 'symbols': ['NVDAUSDT']},
    'TSLA': {'type': 'futures', 'symbols': ['TSLAUSDT']},
    'AAPL': {'type': 'futures', 'symbols': ['AAPLUSDT']},
    'GOOGL': {'type': 'futures', 'symbols': ['GOOGLUSDT']},
    'MU': {'type': 'futures', 'symbols': ['MUUSDT']},
    'AMZN': {'type': 'futures', 'symbols': ['AMZNUSDT']},
    'GLW': {'type': 'futures', 'symbols': ['GLWUSDT']},
    'SPCX': {'type': 'futures', 'symbols': ['SPCXUSDT']},
    'CLU': {'type': 'futures', 'symbols': ['CLUSDT', 'CLUUSDT', 'OILUSDT']},
    'SNDK': {'type': 'futures', 'symbols': ['SNDKUSDT']},
    'SAMSUNG': {'type': 'futures', 'symbols': ['SAMSUNGUSDT']}
}

TIMEFRAME = '15m'
FETCH_LIMIT = 60

# 免區域限制之公共鏡像端點
SPOT_MIRRORS = [
    "https://data-api.binance.vision/api/v3/klines",
    "https://api1.binance.com/api/v3/klines"
]

FUTURES_MIRRORS = [
    "https://fapi.binance.com/fapi/v1/klines",
    "https://fapi.binance.vision/fapi/v1/klines"
]

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

def fetch_binance_data(market_type, symbols):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    endpoints = FUTURES_MIRRORS if market_type == 'futures' else SPOT_MIRRORS
    
    for sym in symbols:
        encoded_sym = urllib.parse.quote(sym)
        for base_url in endpoints:
            url = f"{base_url}?symbol={encoded_sym}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
            try:
                res = requests.get(url, headers=headers, timeout=6)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        latest_close = float(data[-1][4])
                        return True, sym, len(data), latest_close, "Binance-合約" if market_type == 'futures' else "Binance-現貨"
            except Exception:
                continue
    return False, symbols[0], 0, None, "無法抓取"

def main():
    send_discord_alert("📡 **[全標的現貨/合約自動分流測試] 開始執行...**")
    
    results = []
    success_count = 0

    for name, cfg in SYMBOL_CONFIG.items():
        ok, matched_sym, count, price, label = fetch_binance_data(cfg['type'], cfg['symbols'])
        
        if ok:
            success_count += 1
            if price < 1.0:
                price_str = f"${price:.5f}"
            else:
                price_str = f"${price:,.2f}"
            results.append(f"✅ {name:<8} [{label:<12}] -> {matched_sym:<12} | {count:2d} 根 | 最新價: {price_str} USDT")
        else:
            results.append(f"❌ {name:<8} [{cfg['type']:<12}] -> {matched_sym:<12} | 抓取失敗")
        time.sleep(0.1)

    summary_text = (
        f"📋 **[幣安現貨/合約分流測試總覽]**\n"
        f"成功抓取: {success_count} / {len(SYMBOL_CONFIG)}\n"
        f"```text\n"
        + "\n".join(results) +
        f"\n```"
    )
    
    send_discord_alert(summary_text)
    print("=== 測試完成 ===")

if __name__ == '__main__':
    main()
