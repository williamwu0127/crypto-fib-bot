import time
import requests
import pandas as pd
import numpy as np

BACKTEST_SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'risk': 0.01},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 100.0, 'risk': 0.01},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_fvg',     'lev': 20.0,  'risk': 0.01},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian','lev': 20.0,  'risk': 0.01},
    'MSFT': {'s': 'MSFTUSDT', 'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'risk': 0.01},
    'MU':   {'s': 'MUUSDT',   'interval': '1h',  'mode': 'stock_pullback',    'lev': 10.0,  'risk': 0.01}
}

TEST_PERIODS = [30, 365]
INITIAL_SHARED_CAPITAL = 1000.0
FEE_RATE = 0.0004
MAINTENANCE_MARGIN_RATE = 0.005

def fetch_binance_klines(symbol, interval, days=365):
    all_klines = []
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    curr_start = start_ms

    while curr_start < end_ms:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            all_klines.extend(res)
            curr_start = res[-1][0] + 1
            time.sleep(0.03)
        except Exception:
            break

    if len(all_klines) > 0:
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
        for col in ['o', 'h', 'l', 'c', 'v']:
            df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
    return None

def run_v3_combined_simulation(days):
    dfs = {}
    data_status = {}
    max_len = 0
    
    for sym, cfg in BACKTEST_SYMBOLS.items():
        df = fetch_binance_klines(cfg['s'], cfg['interval'], days=days + 15)
        if df is not None and not df.empty:
            dfs[sym] = df
            data_status[sym] = '🟢'
            if len(df) > max_len: 
                max_len = len(df)
        else:
            data_status[sym] = '🔴'

    shared_wallet = float(INITIAL_SHARED_CAPITAL)
    active_positions = {}
    combined_trades = []
    asset_trade_stats = {sym: {'trades': 0, 'wins': 0, 'pnl': 0.0} for sym in BACKTEST_SYMBOLS.keys()}

    for i in range(25, max_len):
        if shared_wallet <= 10.0: 
            break

        for sym in list(active_positions.keys()):
            pos = active_positions[sym]
            df = dfs.get(sym)
            if df is None or i >= len(df): continue
            bar = df.iloc[i]
            
            side, entry, sl, tp1, tp2, qty, liq_p, tp1_hit = (
                pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['liq_price'], pos['tp1_hit']
            )

            if (side == 'LONG' and bar['l'] <= liq_p) or (side == 'SHORT' and bar['h'] >= liq_p):
                loss_val = (qty * entry) / pos['lev']
                shared_wallet = max(0.0, shared_wallet - loss_val)
                combined_trades.append({'sym': sym, 'pnl': -loss_val})
                asset_trade_stats[sym]['trades'] += 1
                asset_trade_stats[sym]['pnl'] -= loss_val
                del active_positions[sym]
                continue

            closed = False
            if side == 'LONG':
                if bar['l'] <= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    combined_trades.append({'sym': sym, 'pnl': pnl})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl
                    if pnl > 0: asset_trade_stats[sym]['wins'] += 1
                    closed = True
                elif not tp1_hit and bar['h'] >= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp1})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl_tp1
                    if pnl_tp1 > 0: asset_trade_stats[sym]['wins'] += 1
                elif pos['tp1_hit'] and bar['h'] >= tp2:
                    pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp2})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl_tp2
                    if pnl_tp2 > 0: asset_trade_stats[sym]['wins'] += 1
                    closed = True
            elif side == 'SHORT':
                if bar['h'] >= sl:
                    rem_qty = qty * 0.5 if tp1_hit else qty
                    pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                    shared_wallet += pnl
                    combined_trades.append({'sym': sym, 'pnl': pnl})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl
                    if pnl > 0: asset_trade_stats[sym]['wins'] += 1
                    closed = True
                elif not tp1_hit and bar['l'] <= tp1:
                    pos['tp1_hit'] = True
                    pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                    shared_wallet += pnl_tp1
                    pos['sl'] = entry
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp1})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl_tp1
                    if pnl_tp1 > 0: asset_trade_stats[sym]['wins'] += 1
                elif pos['tp1_hit'] and bar['l'] <= tp2:
                    pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                    shared_wallet += pnl_tp2
                    combined_trades.append({'sym': sym, 'pnl': pnl_tp2})
                    asset_trade_stats[sym]['trades'] += 1
                    asset_trade_stats[sym]['pnl'] += pnl_tp2
                    if pnl_tp2 > 0: asset_trade_stats[sym]['wins'] += 1
                    closed = True
            if closed: del active_positions[sym]

        for sym, cfg in BACKTEST_SYMBOLS.items():
            if sym in active_positions: continue
            df = dfs.get(sym)
            if df is None or i >= len(df): continue
            bar = df.iloc[i]
            prev_bar = df.iloc[i-1]
            sig_side, entry, sl, tp1, tp2 = None, 0, 0, 0, 0
            mode = cfg['mode']

            if mode == 'gold_macro_donchian':
                if i >= 20:
                    dc_high = df['h'].iloc[i-20:i].max()
                    dc_low = df['l'].iloc[i-20:i].min()
                    atr = (df['h'] - df['l']).rolling(14).mean().iloc[i]
                    if pd.isna(atr): atr = bar['c'] * 0.015
                    if bar['c'] > dc_high:
                        sig_side, entry = 'LONG', bar['c']
                        sl = entry - (atr * 1.5)
                        tp1 = tp2 = entry + ((entry - sl) * 5.0)
                    elif bar['c'] < dc_low:
                        sig_side, entry = 'SHORT', bar['c']
                        sl = entry + (atr * 1.5)
                        tp1 = tp2 = entry - ((sl - entry) * 5.0)
            elif mode in ['crypto_ict_fvg', 'stock_pullback']:
                recent_low = df['l'].iloc[max(0, i-20):i].min()
                recent_high = df['h'].iloc[max(0, i-20):i].max()
                if bar['l'] <= recent_low * 1.005 and bar['c'] > prev_bar['c']:
                    sig_side, entry = 'LONG', bar['c']
                    sl = recent_low * 0.995
                    tp1 = entry + (entry - sl) * 2.0
                    tp2 = recent_high
                elif bar['h'] >= recent_high * 0.995 and bar['c'] < prev_bar['c']:
                    sig_side, entry = 'SHORT', bar['c']
                    sl = recent_high * 1.005
                    tp1 = entry - (sl - entry) * 2.0
                    tp2 = recent_low

            if sig_side and abs(entry - sl) > 0:
                risk_amount = shared_wallet * cfg['risk']
                risk_dist = abs(entry - sl)
                target_qty = risk_amount / risk_dist
                if (target_qty * entry) < 25.0: target_qty = 25.0 / entry
                max_qty = (shared_wallet * cfg['lev']) / entry
                if target_qty > max_qty: target_qty = max_qty

                lev = cfg['lev']
                liq_price = entry * (1.0 - (1.0 / lev) + MAINTENANCE_MARGIN_RATE) if sig_side == 'LONG' else entry * (1.0 + (1.0 / lev) - MAINTENANCE_MARGIN_RATE)
                active_positions[sym] = {
                    'side': sig_side, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'qty': target_qty, 'liq_price': liq_price, 'tp1_hit': False, 'lev': lev
                }

    net_pnl = shared_wallet - INITIAL_SHARED_CAPITAL
    roi = (net_pnl / INITIAL_SHARED_CAPITAL) * 100
    total_trades = len(combined_trades)
    wins = sum(1 for t in combined_trades if t.get('pnl', 0) > 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    return {
        'final': shared_wallet,
        'net': net_pnl,
        'roi': roi,
        'trades': total_trades,
        'wr': win_rate,
        'stats': asset_trade_stats,
        'status': data_status
    }

def run_v3_backtest_report():
    print("==========================================================================")
    print(" >>> 啟動 v3 版【共享 1000U 資金池】30d 與 365d 回測...")
    print("==========================================================================")

    for days in TEST_PERIODS:
        print(f"\n正在計算 {days} 天期回測...")
        res = run_v3_combined_simulation(days)
        
        status_str = " | ".join([f"{sym}: {res['status'].get(sym, '🔴')}" for sym in BACKTEST_SYMBOLS.keys()])
        
        lines = [
            "```text",
            f"📈 【實戰策略 v3 版 {days} 天高淨值回測報告】",
            f"數據狀態: {status_str}",
            "==========================================================================",
            f"【共享資金池 1000U (Combined) 模式 ({days}d)】",
            f"回測區間: 動態近 {days} 天",
            f"初始資金: ${INITIAL_SHARED_CAPITAL:.2f} USDT",
            f"最終結餘: ${res['final']:.2f} USDT ({res['roi']:+.2f}%)",
            f"總交易次數: {res['trades']} 次 | 綜合勝率: {res['wr']:.2f}%",
            "--------------------------------------------------------------------------"
        ]

        for sym in BACKTEST_SYMBOLS.keys():
            st = res['stats'][sym]
            s_wr = (st['wins'] / st['trades'] * 100) if st['trades'] > 0 else 0.0
            lines.append(f"{sym:<5} | 交易: {str(st['trades']).ljust(4)}次 | 勝率: {s_wr:6.2f}% | 收益: {st['pnl']:+8.2f} U")

        lines.extend([
            "=========================================================================="
        ])
        lines.append("```")

        print("\n" + "\n".join(lines))

if __name__ == '__main__':
    run_v3_backtest_report()
