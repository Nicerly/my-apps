
import json, os, re, time, threading, datetime, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
DIR = os.path.dirname(os.path.abspath(__file__))
WL = os.path.join(DIR, "watchlist.json")
import sys; sys.path.insert(0, DIR); import macro
import news as newsmod
DEFAULT = ["AAPL","MSFT","NVDA","TSLA","AMZN","GOOGL","META","SPY","QQQ","BTC-USD"]
SYM = re.compile(r"^[A-Za-z0-9.\-^=]{1,15}$")
RANGES = {"1D":("1d","1m"),"5D":("5d","5m"),"1M":("1mo","30m"),"6M":("6mo","1d"),"1Y":("1y","1d"),"5Y":("5y","1wk")}
DAYS = {"1D":5,"5D":10,"1M":31,"6M":183,"1Y":366,"5Y":1830}
CRYPTO = {"1D":("5m",288),"5D":("30m",240),"1M":("2h",360),"6M":("1d",183),"1Y":("1d",365),"5Y":("1w",260)}
cache = {}
pool = ThreadPoolExecutor(8)
SEM = threading.Semaphore(4)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "application/json"}
yblock = [0.0]

def fetch_json(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r: return json.load(r)

def cached(key, ttl, fn):
    now = time.time(); c = cache.get(key)
    if c and now - c[0] < ttl: return c[1]
    try:
        v = fn()
    except Exception:
        if c: return c[1]
        raise
    cache[key] = (time.time(), v); return v

def is_crypto(sym): return sym.endswith("-USD") or sym.endswith("-USDT")

def yahoo(sym, rng, iv):
    def go():
        if time.time() < yblock[0]: raise RuntimeError("yahoo rate-limited")
        last = None
        with SEM:
            for host in ("query1", "query2"):
                try:
                    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={iv}&includePrePost=false"
                    return fetch_json(url)["chart"]["result"][0]
                except Exception as e:
                    last = e
                    if getattr(e, "code", None) == 429: yblock[0] = time.time() + 60
                    if getattr(e, "code", None) in (404, 429): break
        raise last
    return cached(("y", sym, rng, iv), 5 if rng in ("1d", "5d") else 120, go)

num = lambda s: float(str(s).replace("$","").replace(",","").replace("%","").replace("+","")) if s not in (None,"","N/A","--") else None

ALIAS = {"^GSPC": "SPX", "^IXIC": "COMP", "^NDX": "NDX", "^RUT": "RUT"}
def nq(sym): return urllib.parse.quote(ALIAS.get(sym, sym))

def nasdaq_info(sym):
    def go():
        for ac in (("index",) if sym.startswith("^") else ("stocks", "etf")):
            try:
                d = fetch_json(f"https://api.nasdaq.com/api/quote/{nq(sym)}/info?assetclass={ac}")["data"]
                if d and num(d["primaryData"].get("lastSalePrice")) is not None: return ac, d
            except Exception: pass
        raise RuntimeError("not found")
    return cached(("ni", sym), 4, go)

def nasdaq_quote(sym):
    ac, d = nasdaq_info(sym)
    pd = d["primaryData"]; p = num(pd.get("lastSalePrice")); ch = num(pd.get("netChange")); pct = num(pd.get("percentageChange"))
    if pd.get("deltaIndicator") == "down":
        ch = -abs(ch) if ch is not None else None; pct = -abs(pct) if pct is not None else None
    hl = (d.get("keyStats") or {}).get("dayrange", {}).get("value", "") if isinstance(d.get("keyStats"), dict) else ""
    hi = lo = None
    try: lo, hi = [num(x) for x in hl.split("-")]
    except Exception: pass
    return {"symbol": sym, "name": d.get("companyName") or sym, "price": p, "prev": (p - ch) if ch is not None else None,
            "change": ch, "pct": pct, "currency": "USD", "time": None, "high": hi, "low": lo, "volume": num(pd.get("volume")),
            "exchange": d.get("exchange"), "source": "nasdaq"}

def crypto_quote(sym):
    base = sym.split("-")[0]
    def go():
        st = fetch_json(f"https://api.exchange.coinbase.com/products/{base}-USD/stats")
        p = float(st["last"]); o = float(st["open"]); ch = p - o
        return {"symbol": sym, "name": f"{base} / USD (24h)", "price": p, "prev": o, "change": ch, "pct": ch / o * 100 if o else None,
                "currency": "USD", "time": int(time.time()), "high": float(st["high"]), "low": float(st["low"]),
                "volume": float(st["volume"]), "exchange": "Coinbase", "source": "coinbase"}
    return cached(("cq", sym), 3, go)

def yahoo_quote(sym):
    m = yahoo(sym, "1d", "1m")["meta"]
    p = m.get("regularMarketPrice"); prev = m.get("chartPreviousClose") or m.get("previousClose")
    ch = (p - prev) if (p is not None and prev) else None
    return {"symbol": sym, "name": m.get("shortName") or m.get("longName") or sym, "price": p, "prev": prev,
            "change": ch, "pct": (ch / prev * 100) if ch is not None else None, "currency": m.get("currency"),
            "time": m.get("regularMarketTime"), "high": m.get("regularMarketDayHigh"), "low": m.get("regularMarketDayLow"),
            "volume": m.get("regularMarketVolume"), "exchange": m.get("fullExchangeName") or m.get("exchangeName"), "source": "yahoo"}


CNBC = {"^GSPC": ".SPX", "^DJI": ".DJI", "^IXIC": ".IXIC", "^NDX": ".NDX", "^RUT": ".RUT", "^VIX": ".VIX"}
CNBC_IV = {"1D": (["5M", "1M"], 6), "5D": (["30M", "15M", "1H"], 10), "1M": (["1H", "30M", "1D"], 35), "6M": (["1D"], 186), "1Y": (["1D"], 370), "5Y": (["1W", "1D"], 1830)}

def cnbc_quote(sym):
    cs = CNBC[sym]
    def go():
        u = f"https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={urllib.parse.quote(cs)}&requestMethod=itv&noform=0&partnerId=2&fund=1&exthrs=1&output=json&events=1"
        q = fetch_json(u)["FormattedQuoteResult"]["FormattedQuote"][0]
        p = num(q.get("last")); ch = num(q.get("change")); pct = num(q.get("change_pct")); prev = num(q.get("previous_day_closing"))
        if ch is None and prev: ch = p - prev
        if pct is None and prev and ch is not None: pct = ch / prev * 100
        return {"symbol": sym, "name": q.get("name") or sym, "price": p, "prev": prev if prev else ((p - ch) if ch is not None else None),
                "change": ch, "pct": pct, "currency": "USD", "time": None, "high": num(q.get("high")), "low": num(q.get("low")),
                "volume": None, "exchange": "Index", "source": "cnbc"}
    return cached(("cnq", sym), 4, go)

def cnbc_chart(sym, rk):
    cs = CNBC[sym]; ivs, days = CNBC_IV.get(rk, CNBC_IV["1D"])
    def go():
        end = datetime.datetime.utcnow() - datetime.timedelta(hours=4) + datetime.timedelta(hours=1)
        st = end - datetime.timedelta(days=days); f = "%Y%m%d%H%M%S"
        err = None
        for iv in ivs:
            try:
                u = f"https://ts-api.cnbc.com/harmony/app/bars/{urllib.parse.quote(cs)}/{iv}/{st.strftime(f)}/{end.strftime(f)}/adjusted/EST5EDT.json"
                bars = fetch_json(u, 15)["barData"]["priceBars"] or []
                out = []
                for b in bars:
                    tt = b["tradeTime"]; t = int(datetime.datetime.strptime(tt, f).replace(tzinfo=datetime.timezone.utc).timestamp())
                    o, h, l, c = num(b.get("open")), num(b.get("high")), num(b.get("low")), num(b.get("close"))
                    if None in (o, h, l, c): continue
                    out.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": num(b.get("volume")) or 0})
                if not out: continue
                if rk == "1D":
                    last = out[-1]["time"] // 86400; out = [b for b in out if b["time"] // 86400 == last]
                return out
            except Exception as e: err = e
        raise RuntimeError(f"cnbc: {err}")
    return cached(("cnc", sym, rk), 15 if rk in ("1D", "5D") else 300, go)

def quote(sym):
    srcs = [crypto_quote, yahoo_quote] if is_crypto(sym) else [nasdaq_quote, yahoo_quote]
    if sym in CNBC: srcs = [nasdaq_quote, cnbc_quote, yahoo_quote]
    err = None
    for f in srcs:
        try:
            q = f(sym)
            if q and q.get("price") is not None: return q
        except Exception as e: err = e
    return {"symbol": sym, "error": str(err)[:200]}

def yahoo_chart(sym, rk):
    rng, iv = RANGES.get(rk, RANGES["1D"])
    res = yahoo(sym, rng, iv)
    off = res["meta"].get("gmtoffset", 0) or 0
    ts = res.get("timestamp") or []; q = (res.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q.get(k, [None]*len(ts))[i] for k in ("open","high","low","close","volume"))
        if None in (o, h, l, c): continue
        out.append({"time": t + off, "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    return out

def crypto_chart(sym, rk):
    base = sym.split("-")[0]; iv, lim = CRYPTO.get(rk, CRYPTO["1D"])
    def go():
        k = fetch_json(f"https://api.binance.us/api/v3/klines?symbol={base}USDT&interval={iv}&limit={lim}")
        return [{"time": int(r[0] // 1000), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in k]
    return cached(("cc", sym, rk), 5 if rk in ("1D", "5D") else 60, go)

def nasdaq_intraday(sym, ac):
    def go():
        d = fetch_json(f"https://api.nasdaq.com/api/quote/{nq(sym)}/chart?assetclass={ac}")["data"]
        pts = [(p["x"] / 1000, p["y"], num((p.get("z") or {}).get("shares")) or 0) for p in (d.get("chart") or []) if p.get("y") is not None]
        if not pts: return []
        # Nasdaq x is ET wall-clock encoded as UTC; if it looks like true UTC (first point >=13:00 UTC), shift to ET
        if datetime.datetime.utcfromtimestamp(pts[0][0]).hour >= 13: pts = [(t - 4 * 3600, y, v) for t, y, v in pts]
        bars = {}
        for t, y, v in pts:
            b = int(t // 300 * 300); x = bars.get(b)
            if not x: bars[b] = {"time": b, "open": y, "high": y, "low": y, "close": y, "volume": v}
            else: x["high"] = max(x["high"], y); x["low"] = min(x["low"], y); x["close"] = y; x["volume"] += v
        return [bars[k] for k in sorted(bars)]
    return cached(("nc", sym), 15, go)

def nasdaq_daily(sym, ac, rk):
    def go():
        td = datetime.date.today(); fr = td - datetime.timedelta(days=DAYS.get(rk, 183))
        d = fetch_json(f"https://api.nasdaq.com/api/quote/{nq(sym)}/historical?assetclass={ac}&fromdate={fr}&todate={td}&limit=9999", 15)["data"]
        out = []
        for r in (d.get("tradesTable") or {}).get("rows") or []:
            try:
                m, dd, y = map(int, r["date"].split("/"))
                t = int(datetime.datetime(y, m, dd, tzinfo=datetime.timezone.utc).timestamp())
                out.append({"time": t, "open": num(r["open"]), "high": num(r["high"]), "low": num(r["low"]), "close": num(r["close"]), "volume": num(r["volume"]) or 0})
            except Exception: pass
        out = [b for b in out if None not in (b["open"], b["high"], b["low"], b["close"])]
        out.sort(key=lambda b: b["time"])
        if rk == "5Y":  # weekly aggregation
            wk = {}
            for b in out:
                k = b["time"] - datetime.datetime.utcfromtimestamp(b["time"]).weekday() * 86400; x = wk.get(k)
                if not x: wk[k] = dict(b, time=k)
                else: x["high"] = max(x["high"], b["high"]); x["low"] = min(x["low"], b["low"]); x["close"] = b["close"]; x["volume"] += b["volume"]
            out = [wk[k] for k in sorted(wk)]
        if rk == "5D": out = out[-5:]
        return out
    return cached(("nd", sym, rk), 300, go)

def nasdaq_chart(sym, rk):
    ac, _ = nasdaq_info(sym)
    if rk == "1D":
        b = nasdaq_intraday(sym, ac)
        if len(b) >= 2: return b
    return nasdaq_daily(sym, ac, rk if rk != "1D" else "5D")

def chart(sym, rk):
    srcs = [crypto_chart, yahoo_chart] if is_crypto(sym) else [yahoo_chart, nasdaq_chart]
    if sym in CNBC: srcs = [nasdaq_chart, cnbc_chart, yahoo_chart]
    err = None
    for f in srcs:
        try:
            out = f(sym, rk)
            if out:
                dedup = {}
                for b in out: dedup[b["time"]] = b
                return {"symbol": sym, "range": rk, "candles": [dedup[k] for k in sorted(dedup)], "source": f.__name__}
        except Exception as e: err = e
    raise RuntimeError(f"no chart data ({err})")

def load_wl():
    try: return json.load(open(WL))
    except Exception: return list(DEFAULT)

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=DIR, **k)
    def log_message(self, *a): pass
    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/api/pwa": return self.send_json(json.load(open("/home/user/workspace/pwa/link.json")))
            if u.path == "/api/newsapp": return self.send_json(json.load(open("/home/user/workspace/newsapp/link.json")))
            if u.path == "/api/trending":
                import trending
                return self.send_json(trending.top())
            if u.path == "/api/news": return self.send_json(newsmod.top())
            if u.path == "/api/macro": return self.send_json(cached(("macro",), 600, macro.summary))
            if u.path == "/api/macro/series":
                mid = qs.get("id", [""])[0]
                return self.send_json(cached(("mser", mid), 900, lambda: macro.series(mid)))
            if u.path == "/api/watchlist": return self.send_json(load_wl())
            if u.path == "/api/quotes":
                syms = [s.upper() for s in qs.get("s", [""])[0].split(",") if SYM.match(s)][:60]
                return self.send_json(list(pool.map(quote, syms)))
            if u.path == "/api/chart":
                s = qs.get("s", [""])[0].upper()
                if not SYM.match(s): return self.send_json({"error": "bad symbol"}, 400)
                return self.send_json(chart(s, qs.get("range", ["1D"])[0]))
        except Exception as e:
            return self.send_json({"error": str(e)[:300]}, 502)
        if u.path.endswith(".json") or u.path.endswith(".py"): return self.send_error(404)
        return super().do_GET()
    def do_POST(self):
        if self.path != "/api/watchlist": return self.send_error(404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            syms = []
            for s in data:
                s = str(s).upper()
                if SYM.match(s) and s not in syms: syms.append(s)
            json.dump(syms[:60], open(WL, "w"))
            return self.send_json(syms[:60])
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)

ThreadingHTTPServer(("127.0.0.1", 47740), H).serve_forever()
