#!/usr/bin/env python3
"""Congress stock trades: House Clerk PTR PDFs + Senate eFD PTRs + Yahoo daily prices -> site/congress/data.json"""
import io, os, re, sys, json, time, zipfile, bisect, datetime as dt, concurrent.futures as cf, html as H
import xml.etree.ElementTree as ET
import httpx
from pypdf import PdfReader

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
TODAY = dt.date.today()
YEARS = [int(y) for y in os.environ.get("CONGRESS_YEARS", "").split(",") if y] or list(range(TODAY.year - 2, TODAY.year + 1))
PREV = os.environ.get("CONGRESS_PREV", "https://nicerly.github.io/my-apps/congress/data.json")
PRICE_BUDGET = float(os.environ.get("PRICE_BUDGET", "900"))
HB = "https://disclosures-clerk.house.gov/public_disc"
SB = "https://efdsearch.senate.gov"
LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); LOG.append(s); print(s, flush=True)
import unicodedata
def norm(s): return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
def clean_last(s):
    s = (s or "").split(",")[0]
    s = re.sub(r"\b(Jr|Sr|II|III|IV|MD|FACS)\.?(?=\s|$)", "", s, flags=re.I)
    return s.strip()
def iso(mdy):
    try:
        m, d, y = mdy.strip().split("/"); return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception: return None
BR = {1001: 15000, 15001: 50000, 50001: 100000, 100001: 250000, 250001: 500000, 500001: 1000000,
      1000001: 5000000, 5000001: 25000000, 25000001: 50000000}
def amt(s):
    s = (s or "").replace(",", ""); nums = [int(x) for x in re.findall(r"\$(\d+)", s)]
    if not nums: return None, None
    if "over" in s.lower(): return nums[0], None
    return nums[0], (nums[1] if len(nums) > 1 else BR.get(nums[0]))
PARTY = {"Democrat": "D", "Republican": "R", "Independent": "I"}

def legislators(c):
    out = []
    for fn, cur in (("legislators-current.json", True), ("legislators-historical.json", False)):
        for base in ("https://unitedstates.github.io/congress-legislators/", "https://theunitedstates.io/congress-legislators/"):
            try:
                r = c.get(base + fn)
                if r.status_code != 200: continue
                for L in r.json():
                    if cur or (L.get("terms") and L["terms"][-1].get("end", "") >= "2019-01-01"):
                        L["_cur"] = cur; out.append(L)
                break
            except Exception as e: log("legislators", fn, type(e).__name__)
    return out

# ---------------- House ----------------
def house_index(c):
    out = []
    for y in YEARS:
        try: r = c.get(f"{HB}/financial-pdfs/{y}FD.zip")
        except Exception as e: log("house index", y, type(e).__name__); continue
        if r.status_code != 200: log("house index", y, r.status_code); continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xn = [n for n in z.namelist() if n.lower().endswith(".xml")][0]
        for m in ET.fromstring(z.read(xn)).iter("Member"):
            g = {ch.tag: (ch.text or "").strip() for ch in m}
            if g.get("FilingType") == "P" and g.get("DocID"): out.append(g)
    return out
TX = re.compile(r"\[([A-Z]{2})\]\s*(P|S\s*\(partial\)|S|E)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})\s+"
                r"((?:Spouse/DC\s+)?Over\s+\$[\d,]+|\$[\d,]+(?:\s*-\s*\$[\d,]+)?)")
LABEL = re.compile(r"\b(F S|S O|D|C|L):\s?")
HDR = re.compile(r"ID Owner Asset Transaction Type Date Notification Date Amount Cap\. Gains > \$200\?")
def pdf_text(b):
    rd = PdfReader(io.BytesIO(b))
    return "\n".join((pg.extract_text() or "") for pg in rd.pages).replace("\x00", "")
def parse_house(text):
    t = re.sub(r"\s+", " ", text)
    i = t.find("$200?"); t = t[i + 5:] if i >= 0 else t
    j = t.find("* For the complete list"); t = t[:j] if j >= 0 else t
    t = HDR.sub(" ", t)
    rows, prev = [], 0
    for m in TX.finditer(t):
        seg = t[prev:m.start()].strip(); prev = m.end()
        parts = LABEL.split(seg); name = parts[-1].strip()
        if len(parts) > 1:
            if parts[-2] == "F S": name = re.sub(r"^\w+\s*", "", name)
            else:
                mo = re.search(r"(?:^|\s)(SP|JT|DC)\s+(.+)$", name)
                if mo: name = mo.group(0).strip()
        owner = ""
        mo = re.match(r"(SP|JT|DC)\s+(.*)$", name)
        if mo: owner, name = mo.group(1), mo.group(2)
        tk = None
        mt = re.findall(r"\(([A-Z][A-Z0-9.\-/]{0,7})\)", name)
        if mt: tk = mt[-1]
        nm = re.sub(r"\s*\([A-Z][A-Z0-9.\-/]{0,7}\)\s*$", "", name).strip()[:90]
        ty = m.group(2).replace(" ", "")
        ty = {"P": "P", "S": "S", "S(partial)": "SP", "E": "E"}.get(ty, ty)
        lo, hi = amt(m.group(5))
        rows.append({"td": iso(m.group(3)), "ty": ty, "tk": tk, "as": nm, "at": m.group(1), "ow": owner, "lo": lo, "hi": hi})
    return rows

# ---------------- Senate ----------------
SOWN = {"Self": "", "Spouse": "SP", "Joint": "JT", "Child": "DC", "Dependent Child": "DC"}
STYP = {"Purchase": "P", "Sale (Full)": "S", "Sale (Partial)": "SP", "Exchange": "E", "Sale": "S"}
SAT = {"Stock": "ST", "Stock Option": "OP", "Corporate Bond": "CS", "Municipal Security": "GS", "Government Security": "GS",
       "Mutual Fund": "MF", "Exchange Traded Fund": "EF", "Cryptocurrency": "CT"}
def csrf(c):
    for ck in c.cookies.jar:
        if ck.name == "csrftoken": return ck.value
def senate_client():
    last = None
    for k in range(5):
        c = httpx.Client(headers=UA, timeout=60, follow_redirects=True)
        try:
            r = c.get(SB + "/search/home/")
            m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
            if m:
                c.post(SB + "/search/home/", data={"csrfmiddlewaretoken": m.group(1), "prohibition_agreement": "1"},
                       headers={"Referer": SB + "/search/home/"})
                if csrf(c): return c
            last = "status %s" % r.status_code
        except Exception as e: last = type(e).__name__
        c.close(); time.sleep(5 + 10 * k)
    raise RuntimeError("senate login failed: " + str(last))
def senate_list(c):
    out, start = [], 0
    while True:
        tok = csrf(c)
        r = c.post(SB + "/search/report/data/", data={"start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
                   "submitted_start_date": f"01/01/{min(YEARS)} 00:00:00", "submitted_end_date": "", "candidate_state": "",
                   "senator_state": "", "office_id": "", "first_name": "", "last_name": "", "csrfmiddlewaretoken": tok},
                   headers={"Referer": SB + "/search/", "X-CSRFToken": tok or ""})
        j = r.json(); d = j.get("data") or []
        out += d; start += len(d)
        if not d or start >= int(j.get("recordsTotal", 0)): break
    return out
def parse_senate(html):
    tb = re.search(r"<tbody>(.*?)</tbody>", html, re.S); rows = []
    if not tb: return rows
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.S):
        tds = [re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 8: continue
        _, d, owner, tick, asset, atype, typ, amount = tds[:8]
        lo, hi = amt(amount)
        tk = tick if re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,7}", tick or "") else None
        rows.append({"td": iso(d), "ty": STYP.get(typ, typ[:2].upper()), "tk": tk, "as": asset[:90], "at": SAT.get(atype, "OT"),
                     "ow": SOWN.get(owner, ""), "lo": lo, "hi": hi})
    return rows

# ---------------- Prices ----------------
def yahoo_hist(c, tk, p1):
    sym = tk.replace(".", "-").replace("/", "-")
    for host in ("query1", "query2"):
        for k in range(3):
            try:
                r = c.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                          params={"period1": p1, "period2": int(time.time()), "interval": "1d"})
            except Exception: time.sleep(2); continue
            if r.status_code == 429: time.sleep(2 + 4 * k); continue
            if r.status_code == 404: return False
            if r.status_code != 200: break
            try:
                res = r.json()["chart"]["result"][0]
            except Exception: return False
            ts = res.get("timestamp") or []; cl = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
            meta = res.get("meta", {})
            pts = [(dt.datetime.fromtimestamp(a, dt.timezone.utc).date().isoformat(), b) for a, b in zip(ts, cl) if b]
            return {"n": meta.get("longName") or meta.get("shortName"), "c": meta.get("regularMarketPrice") or (pts[-1][1] if pts else None), "pts": pts}
    return None
NQH = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
def nasdaq_hist(c, tk, p1):
    fd = dt.datetime.fromtimestamp(p1, dt.timezone.utc).date().isoformat()
    for ac in ("stocks", "etf"):
        for k in range(2):
            try:
                r = c.get(f"https://api.nasdaq.com/api/quote/{tk}/historical", headers=NQH, timeout=30,
                          params={"assetclass": ac, "fromdate": fd, "todate": TODAY.isoformat(), "limit": "9999"})
            except Exception: time.sleep(2); continue
            if r.status_code == 429: time.sleep(3 + 5 * k); continue
            if r.status_code != 200: break
            try: rows = (((r.json() or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
            except Exception: rows = []
            pts = []
            for row in rows:
                try:
                    mo, da, yr = row["date"].split("/")
                    pts.append((f"{yr}-{int(mo):02d}-{int(da):02d}", float(str(row["close"]).replace("$", "").replace(",", ""))))
                except Exception: pass
            if pts:
                pts.sort(); return {"n": None, "c": pts[-1][1], "pts": pts}
            break
    return None
PRICE_SRC = [x for x in os.environ.get("PRICE_SRC", "yahoo,nasdaq").split(",") if x]
YH_FAIL = [0]
def price_hist(c, tk, p1):
    for src in PRICE_SRC:
        if src == "yahoo":
            if YH_FAIL[0] >= 8: continue
            h = yahoo_hist(c, tk, p1)
            if h is None: YH_FAIL[0] += 1
            elif h: YH_FAIL[0] = 0
        else: h = nasdaq_hist(c, tk, p1)
        if h: return h
    return None
def px_at(pts, d):
    if not pts or not d: return None
    ds = [p[0] for p in pts]; i = bisect.bisect_right(ds, d) - 1
    if i < 0: i = 0 if (dt.date.fromisoformat(ds[0]) - dt.date.fromisoformat(d)).days < 7 else -1
    return round(pts[i][1], 4) if i >= 0 else None

def load_prev(out):
    if PREV:
        try:
            if PREV.startswith("http"):
                r = httpx.get(PREV + f"?t={int(time.time())}", timeout=60, headers=UA)
                if r.status_code == 200: return r.json()
            elif os.path.exists(PREV): return json.load(open(PREV))
        except Exception as e: log("prev", type(e).__name__)
    return {}

def build(out):
    t0 = time.time(); c = httpx.Client(headers=UA, timeout=60, follow_redirects=True, limits=httpx.Limits(max_connections=16))
    prev = load_prev(out); docs = dict(prev.get("docs", {})); members = dict(prev.get("members", {}))
    trades = [x for x in prev.get("trades", []) if x.get("k") in docs]
    leg = legislators(c); by_sd, by_last = {}, {}
    for L in leg:
        tm = L["terms"][-1]; pt = PARTY.get(tm.get("party"), (tm.get("party") or "?")[:1])
        info = {"n": L["name"].get("official_full") or f'{L["name"]["first"]} {L["name"]["last"]}', "pt": pt, "bg": L["id"].get("bioguide"),
                "type": tm["type"], "state": tm["state"], "first": L["name"].get("first"), "nick": L["name"].get("nickname"), "cur": L.get("_cur", True)}
        if tm["type"] == "rep" and info["cur"]: by_sd.setdefault((tm["state"], int(tm.get("district") or 0)), info)
        by_last.setdefault(norm(L["name"]["last"]), []).append(info)
    log("legislators", len(leg))
    # House
    idx = house_index(c); log("house PTR filings", len(idx))
    def hmember(g):
        sd = g.get("StateDst", ""); st, dn = sd[:2], int(sd[2:] or 0) if sd[2:].isdigit() else 0
        info = by_sd.get((st, dn))
        ln = clean_last(g["Last"])
        if not info or norm(ln) not in norm(info["n"]):
            cands = sorted([x for x in by_last.get(norm(ln), []) if x["state"] == st], key=lambda x: (x["type"] != "rep", not x["cur"]))
            info = cands[0] if cands else None
        mid = f"H-{norm(ln)}-{sd}"
        members[mid] = {"n": info["n"] if info else f"{g['First']} {ln}".strip(), "ch": "H", "sd": sd,
                        "pt": info["pt"] if info else "", "bg": info["bg"] if info else None}
        return mid
    todo = []; kmid = {}
    for g in idx:
        k = "H" + g["DocID"]; mid = hmember(g); kmid[k] = mid
        url = f"{HB}/ptr-pdfs/{g['Year']}/{g['DocID']}.pdf"
        if k in docs: continue
        if not g["DocID"].startswith("2"):
            docs[k] = {"m": mid, "f": iso(g["FilingDate"]), "n": 0, "p": 1, "u": url}; continue
        todo.append((k, mid, iso(g["FilingDate"]), url))
    log("house new electronic PDFs", len(todo))
    zero = []
    def fh(a):
        k, mid, fd, url = a
        r = c.get(url)
        if r.status_code != 200: return a, None, None
        txt = pdf_text(r.content)
        return a, txt, parse_house(txt) if txt.strip() else []
    with cf.ThreadPoolExecutor(12) as ex:
        for fut in cf.as_completed([ex.submit(fh, a) for a in todo]):
            try: (k, mid, fd, url), txt, rows = fut.result()
            except Exception as e: log("house pdf err", type(e).__name__); continue
            if rows is None: continue
            if txt.strip() and not rows: zero.append(k)
            docs[k] = {"m": mid, "f": fd, "n": len(rows), "p": 0 if txt.strip() else 1, "u": url}
            for x in rows: x.update(k=k, m=mid, fd=fd); trades.append(x)
    log("house done", round(time.time() - t0), "s; zero-parse", len(zero))
    # Senate
    try:
        sc = senate_client(); sl = senate_list(sc); log("senate PTR reports", len(sl))
        stodo = []
        for row in sl:
            first, last, office, link, filed = row[:5]
            hm = re.search(r'href="([^"]+)"', link); 
            if not hm: continue
            href = hm.group(1); k = "S" + href.rstrip("/").split("/")[-1]
            lc = clean_last(last)
            cands = by_last.get(norm(lc), []); sen = [x for x in cands if x["type"] == "sen"] or cands
            if len(sen) > 1: sen = [x for x in sen if norm(first)[:3] in norm((x["first"] or "") + (x["nick"] or ""))] or sen
            sen = sorted(sen, key=lambda x: not x["cur"])
            info = sen[0] if sen else None
            mid = f"S-{norm(lc)}-{(info or {}).get('state', '')}"
            nm = info["n"] if info else f"{first} {lc}".strip()
            members[mid] = {"n": nm, "ch": "S", "sd": (info or {}).get("state", ""), "pt": (info or {}).get("pt", ""), "bg": (info or {}).get("bg")}
            kmid[k] = mid
            if k in docs: continue
            url = SB + href
            if "/paper/" in href: docs[k] = {"m": mid, "f": iso(filed), "n": 0, "p": 1, "u": url}; continue
            stodo.append((k, mid, iso(filed), url))
        def fs(a):
            r = sc.get(a[3]); return a, (parse_senate(r.text) if r.status_code == 200 and "<tbody>" in r.text else None)
        with cf.ThreadPoolExecutor(6) as ex:
            for fut in cf.as_completed([ex.submit(fs, a) for a in stodo]):
                try: (k, mid, fd, url), rows = fut.result()
                except Exception as e: log("senate err", type(e).__name__); continue
                if rows is None: continue
                docs[k] = {"m": mid, "f": fd, "n": len(rows), "p": 0, "u": url}
                for x in rows: x.update(k=k, m=mid, fd=fd); trades.append(x)
        log("senate done", len(stodo), "new")
    except Exception as e:
        log("senate failed", type(e).__name__, str(e)[:120])
    for k, mid in kmid.items():
        if k in docs: docs[k]["m"] = mid
    for x in trades:
        if x.get("k") in kmid: x["m"] = kmid[x["k"]]
    # Prices
    ptk = {}
    for x in trades:
        if x.get("tk") and x.get("at") in ("ST", "EF"): ptk[x["tk"]] = ptk.get(x["tk"], 0) + (1000 if x["m"].startswith("H-pelosi") else 1)
    order = sorted(ptk, key=lambda t: -ptk[t]); tick = {}; hist = {}
    p1 = int(dt.datetime(min(YEARS) - 1, 12, 1, tzinfo=dt.timezone.utc).timestamp()); tp = time.time()
    def fp(tk):
        if time.time() - tp > PRICE_BUDGET: return tk, None
        return tk, price_hist(c, tk, p1)
    with cf.ThreadPoolExecutor(int(os.environ.get('PRICE_THREADS', '6'))) as ex:
        for fut in cf.as_completed([ex.submit(fp, t) for t in order]):
            tk, h = fut.result()
            if h: hist[tk] = h["pts"]; tick[tk] = {"n": h["n"], "c": h["c"]}
    miss = [t for t in order if t not in hist]
    log("price retry", len(miss))
    RB = float(os.environ.get("RETRY_BUDGET", "600"))
    for t in miss:
        if time.time() - tp > PRICE_BUDGET + RB: break
        time.sleep(0.4)
        try: h = price_hist(c, t, p1)
        except Exception: h = None
        if h: hist[t] = h["pts"]; tick[t] = {"n": h["n"], "c": h["c"]}
    prevtick = prev.get("tick", {}); prevpx = {(x["k"], x.get("tk"), x.get("td")): x.get("px") for x in prev.get("trades", [])}
    for t in order:
        if t not in tick and t in prevtick: tick[t] = prevtick[t]
    log("prices", len(hist), "fresh of", len(order), "in", round(time.time() - tp), "s")
    for x in trades:
        tk = x.get("tk")
        if tk in hist: x["px"] = px_at(hist[tk], x.get("td"))
        elif (x["k"], tk, x.get("td")) in prevpx: x["px"] = prevpx[(x["k"], tk, x.get("td"))]
        cur = (tick.get(tk) or {}).get("c")
        x["r"] = round(cur / x["px"] - 1, 4) if cur and x.get("px") else None
    trades.sort(key=lambda x: (x.get("fd") or "", x.get("td") or ""), reverse=True)
    used = {x["m"] for x in trades} | {d["m"] for d in docs.values()}
    members = {k: v for k, v in members.items() if k in used}
    data = {"v": 1, "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "years": YEARS,
            "members": members, "trades": trades, "docs": docs, "tick": tick,
            "stats": {"trades": len(trades), "docs": len(docs), "members": len(members), "zero": zero[:40], "secs": round(time.time() - t0)},
            "log": LOG[-60:]}
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"; json.dump(data, open(tmp, "w"), separators=(",", ":"), ensure_ascii=False); os.replace(tmp, out)
    log("wrote", out, os.path.getsize(out), "bytes")
    return data["stats"]

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "site/congress/data.json")
