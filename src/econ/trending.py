import json, os, re, time, urllib.request, datetime
try:
    from zoneinfo import ZoneInfo; ET = ZoneInfo("America/New_York")
except Exception:
    ET = None
DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "trending_cache.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", "Accept": "application/json"}
OK = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
N = 7

def _get(url, t=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        return json.load(r)

def yahoo():
    for h in ("query1", "query2"):
        try:
            d = _get(f"https://{h}.finance.yahoo.com/v1/finance/trending/US?count=30")
            return [q["symbol"] for q in d["finance"]["result"][0]["quotes"]]
        except Exception as e:
            err = e
    raise err

def stocktwits():
    d = _get("https://api.stocktwits.com/api/2/trending/symbols.json")
    return [s["symbol"] for s in d["symbols"] if s.get("region", "US") == "US" and s.get("instrument_class") in ("Stock", "ETF", "ExchangeTradedFund", None)]

def apewisdom():
    d = _get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1")
    return [x["ticker"] for x in d["results"]]

SOURCES = [("Yahoo Finance most-viewed", yahoo), ("Stocktwits trending", stocktwits), ("Reddit mentions (ApeWisdom)", apewisdom)]

def today():
    return (datetime.datetime.now(ET) if ET else datetime.datetime.utcnow() - datetime.timedelta(hours=4)).strftime("%Y-%m-%d")

def build():
    syms, used, errs = [], [], {}
    for name, fn in SOURCES:
        try:
            got = [s for s in fn() if OK.match(s or "")]
        except Exception as e:
            errs[name] = repr(e)[:150]; continue
        added = False
        for s in got:
            if s not in syms and len(syms) < N:
                syms.append(s); added = True
        if added: used.append(name)
        if len(syms) >= N: break
    return {"date": today(), "symbols": syms, "source": ", ".join(used), "errors": errs, "fetched": int(time.time())}

def load():
    try: return json.load(open(CACHE))
    except Exception: return None

def top(force=False):
    c = load()
    if not force and c and c.get("date") == today() and len(c.get("symbols", [])) >= N:
        return c
    # avoid hammering sources if a refresh failed recently
    if not force and c and c.get("date") == today() and time.time() - c.get("fetched", 0) < 900:
        return c
    n = build()
    if len(n["symbols"]) >= (len(c.get("symbols", [])) if c and c.get("date") == today() else 1):
        json.dump(n, open(CACHE, "w")); return n
    if c:
        c = dict(c); c["stale"] = True; return c
    return n
