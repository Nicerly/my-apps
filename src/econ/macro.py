
import urllib.request, json, csv, io, datetime, time, threading, os
from concurrent.futures import ThreadPoolExecutor
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "*/*"}
HERE = os.path.dirname(os.path.abspath(__file__))
_c = {}; _l = threading.Lock()
def cached(k, ttl, f):
    now = time.time()
    with _l: v = _c.get(k)
    if v and now - v[0] < ttl: return v[1]
    try: r = f()
    except Exception:
        if v: return v[1]
        raise
    with _l: _c[k] = (now, r)
    return r
def get(u, t=25, data=None, hdr=None):
    h = dict(UA); h.update(hdr or {})
    with urllib.request.urlopen(urllib.request.Request(u, data=data, headers=h), timeout=t) as r:
        return r.read().decode("utf-8", "replace")
def fnum(x):
    try: return float(str(x).replace("%", "").replace(",", "").strip())
    except Exception: return None

def treasury():
    def go():
        yr = datetime.date.today().year; out = {}
        for y in (yr - 2, yr - 1, yr):
            u = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv"
            try: txt = get(u, 30)
            except Exception:
                if y == yr: raise
                continue
            for d in csv.DictReader(io.StringIO(txt)):
                try: dt = datetime.datetime.strptime(d["Date"], "%m/%d/%Y").date().isoformat()
                except Exception: continue
                for col in ("3 Mo", "2 Yr", "10 Yr", "30 Yr"):
                    v = fnum(d.get(col))
                    if v is not None: out.setdefault(col, {})[dt] = v
        res = {k: sorted(v.items()) for k, v in out.items()}
        a, b = out.get("10 Yr", {}), out.get("2 Yr", {})
        res["spread"] = sorted((d, round(a[d] - b[d], 2)) for d in a if d in b)
        return res
    return cached("tsy", 3600, go)

def nyfed(kind):
    path = {"effr": "unsecured/effr", "sofr": "secured/sofr"}[kind]
    def go():
        j = json.loads(get(f"https://markets.newyorkfed.org/api/rates/{path}/last/750.json"))
        return sorted((r["effectiveDate"], float(r["percentRate"])) for r in j["refRates"] if r.get("percentRate") is not None)
    return cached(("ny", kind), 3600, go)

BLS_IDS = ["LNS14000000", "CUUR0000SA0", "CES0000000001"]
BLS_FILE = os.path.join(HERE, "bls_cache.json")
def bls():
    # v1 API is limited to ~25 requests/day per IP: one batched POST, cached 12h in memory and on disk
    def go():
        try:
            disk = json.load(open(BLS_FILE))
            if time.time() - disk["t"] < 12 * 3600: return disk["data"]
        except Exception: disk = None
        try:
            yr = datetime.date.today().year
            body = json.dumps({"seriesid": BLS_IDS, "startyear": str(yr - 5), "endyear": str(yr)}).encode()
            j = json.loads(get("https://api.bls.gov/publicAPI/v1/timeseries/data/", 30, body, {"Content-Type": "application/json"}))
            data = {}
            for s in j["Results"]["series"]:
                pts = []
                for d in s["data"]:
                    if not d["period"].startswith("M") or d["period"] == "M13": continue
                    v = fnum(d["value"])
                    if v is not None: pts.append((f'{d["year"]}-{d["period"][1:]}-01', v))
                data[s["seriesID"]] = sorted(pts)
            if not all(data.get(k) for k in BLS_IDS): raise RuntimeError("bls incomplete: " + str(j.get("message"))[:200])
            json.dump({"t": time.time(), "data": data}, open(BLS_FILE, "w"))
            return data
        except Exception:
            if disk: return disk["data"]
            raise
    return cached("bls", 12 * 3600, go)

CNBC_SYMS = {"DXY": ".DXY", "VIX": ".VIX", "OIL": "@CL.1", "GOLD": "@GC.1"}
def cnbc_quotes():
    def go():
        u = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=" + "|".join(CNBC_SYMS.values()) + "&requestMethod=itv&noform=0&partnerId=2&fund=1&exthrs=1&output=json&events=1"
        qs = json.loads(get(u, 15))["FormattedQuoteResult"]["FormattedQuote"]
        return {q["symbol"]: q for q in qs}
    return cached("cnq", 30, go)
def cnbc_hist(cs):
    def go():
        f = "%Y%m%d%H%M%S"; end = datetime.datetime.utcnow(); st = end - datetime.timedelta(days=760)
        u = f"https://ts-api.cnbc.com/harmony/app/bars/{urllib.parse.quote(cs)}/1D/{st.strftime(f)}/{end.strftime(f)}/adjusted/EST5EDT.json"
        bars = json.loads(get(u, 20))["barData"]["priceBars"] or []
        pts = {}
        for b in bars:
            c = fnum(b.get("close"))
            if c is not None: pts[datetime.datetime.strptime(b["tradeTime"], f).date().isoformat()] = c
        return sorted(pts.items())
    return cached(("cnh", cs), 1800, go)
import urllib.parse

def yoy(pts):
    m = dict(pts); out = []
    for d, v in pts:
        y, mo = int(d[:4]), d[5:7]; p = m.get(f"{y-1}-{mo}-01")
        if p: out.append((d, round((v / p - 1) * 100, 2)))
    return out
def diff(pts): return [(pts[i][0], round(pts[i][1] - pts[i-1][1], 1)) for i in range(1, len(pts))]

# id: (name, group, unit, decimals, loader, source)
IND = {
 "EFFR":   ("Fed funds rate (EFFR)", "Rates", "%", 2, lambda: nyfed("effr"), "NY Fed"),
 "SOFR":   ("SOFR", "Rates", "%", 2, lambda: nyfed("sofr"), "NY Fed"),
 "DGS3MO": ("3-month Treasury", "Rates", "%", 2, lambda: treasury()["3 Mo"], "US Treasury"),
 "DGS2":   ("2-year Treasury", "Rates", "%", 2, lambda: treasury()["2 Yr"], "US Treasury"),
 "DGS10":  ("10-year Treasury", "Rates", "%", 2, lambda: treasury()["10 Yr"], "US Treasury"),
 "DGS30":  ("30-year Treasury", "Rates", "%", 2, lambda: treasury()["30 Yr"], "US Treasury"),
 "T10Y2Y": ("10y-2y spread", "Rates", "pts", 2, lambda: treasury()["spread"], "US Treasury"),
 "UNRATE": ("Unemployment rate", "Economy", "%", 1, lambda: bls()["LNS14000000"], "BLS"),
 "CPIYOY": ("CPI inflation (YoY)", "Economy", "%", 1, lambda: yoy(bls()["CUUR0000SA0"]), "BLS"),
 "PAYEMS": ("Payrolls change (k)", "Economy", "k", 0, lambda: diff(bls()["CES0000000001"]), "BLS"),
 "DXY":    ("US dollar index", "Markets", "", 2, lambda: cnbc_hist(".DXY"), "CNBC"),
 "VIX":    ("VIX volatility", "Markets", "", 2, lambda: cnbc_hist(".VIX"), "CNBC"),
 "OIL":    ("WTI crude oil", "Markets", "$", 2, lambda: cnbc_hist("@CL.1"), "CNBC"),
 "GOLD":   ("Gold", "Markets", "$", 1, lambda: cnbc_hist("@GC.1"), "CNBC"),
}

def _item(k, with_points=False):
    name, grp, unit, dec, fn, src = IND[k]
    pts = list(fn())
    if k in CNBC_SYMS:  # live value on top of daily history
        try:
            q = cnbc_quotes().get(CNBC_SYMS[k]); lv = fnum(q.get("last")) if q else None
            if lv is not None:
                today = datetime.date.today().isoformat()
                pts = [p for p in pts if p[0] != today] + [(today, lv)]
        except Exception: pass
    if not pts: raise RuntimeError("no data")
    d, v = pts[-1]; pv = pts[-2][1] if len(pts) > 1 else None
    it = {"id": k, "name": name, "group": grp, "unit": unit, "dec": dec, "source": src, "date": d, "value": v,
          "prev": pv, "change": round(v - pv, 4) if pv is not None else None}
    if with_points: it["points"] = [{"time": a, "value": b} for a, b in pts]
    return it

def summary():
    def one(k):
        try: return _item(k)
        except Exception as e:
            n = IND[k]; return {"id": k, "name": n[0], "group": n[1], "source": n[5], "error": str(e)[:120]}
    with ThreadPoolExecutor(8) as ex: return list(ex.map(one, IND))
def series(k):
    if k not in IND: raise KeyError(k)
    return _item(k, True)
