def get_dynamic_all_stocks():
    """動態向台灣證交所官方 ISIN 系統抓取全部現存上市與上櫃普通股及所屬產業（具備多重防護）"""
    stock_dict = {}
    urls = [
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
        ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO")
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for url, market in urls:
        success = False
        for parser in ["lxml", "html5lib", "bs4"]:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.encoding = "big5-hkscs"
                dfs = pd.read_html(resp.text, flavor=parser)
                if not dfs:
                    continue
                df = dfs[0]
                df.columns = df.iloc[0]
                df = df.iloc[1:]
                
                for _, row in df.iterrows():
                    original_ind = "其他"
                    for val in row.values:
                        val_str = str(val).strip()
                        if val_str in ["水泥工業", "食品工業", "塑膠工業", "紡織纖維", "電機機械", "電器電纜", "化學工業", "生技醫療業", "玻璃陶瓷", "造紙工業", "鋼鐵工業", "橡膠工業", "汽車工業", "電子通路業", "資訊服務業", "其他電子業", "建材營造", "航運業", "觀光餐旅", "金融保險業", "貿易百貨", "油電燃氣業", "綜合企業", "其他業", "半導體業", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", "電子用品"]:
                            original_ind = val_str
                            break

                    for val in row.values:
                        val_str = str(val).strip()
                        if "\u3000" in val_str:
                            parts = val_str.split("\u3000")
                            if len(parts) >= 2:
                                sid = parts[0].strip()
                                name = parts[1].strip()
                                if len(sid) == 4 and sid.isdigit():
                                    ticker = f"{sid}.{market}"
                                    ind_str = refine_industry(name, original_ind)
                                    stock_dict[ticker] = (sid, name, ind_str)
                success = True
                break # 成功解析就跳出 parser 迴圈
            except Exception as e:
                continue
                
        if not success:
            print(f"警告: 透過 pandas 解析 {market} 失敗，改用備用正規表達式提取...")
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.encoding = "big5-hkscs"
                import re
                # 備用方案：直接用正則抓取 4位數代號 　 股票名稱
                matches = re.findall(r'>(\d{4})&#12288;([^<]+)</td>', resp.text)
                for sid, name in matches:
                    ticker = f"{sid}.{market}"
                    stock_dict[ticker] = (sid, name.strip(), "一般產業")
            except Exception as e2:
                print(f"動態獲取 {market} 股票名冊完全失敗: {e2}")
                
    return stock_dict
