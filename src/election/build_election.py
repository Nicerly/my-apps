
"""Election data builder: Polymarket (race + control odds), Kalshi (control odds), VoteHub (poll averages)."""
import json, re, time, urllib.request, urllib.parse
UA = {"User-Agent": "MyAppsElection/1.0 (personal iPhone app)"}
DIAG = {}
def jget(url, params=None, tries=3):
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    raise err
STATES = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY"}
def price(m):
    try: p = json.loads(m.get("outcomePrices") or "null")
    except Exception: p = None
    if not p: return None
    try: return float(p[0])
    except Exception: return None
def party(name):
    n = name.strip(); m = re.search(r"\((D|R|I|L|G)\)", n)
    if m: return m.group(1)
    low = n.lower()
    if low.startswith("democrat"): return "D"
    if low.startswith("republican"): return "R"
    if low.startswith("independent"): return "I"
    return ""
def poly_events():
    out = {}
    for closed in ("false", "true"):
        off = 0
        while off < (4000 if closed == "false" else 2000):
            js = jget("https://gamma-api.polymarket.com/events", {"limit": 100, "offset": off, "closed": closed, "tag_slug": "midterms"})
            if not js: break
            for e in js:
                if (e.get("createdAt") or "") >= "2025-01-01": out[e["id"]] = e
            off += 100
    DIAG["poly_events"] = len(out)
    return list(out.values())
RACE_SG = re.compile(r"^(.+?) (Senate|Governor) Election Winner\s*$")
RACE_H = re.compile(r"^([A-Z]{2})-(\d\d|AL) House Election Winner")
NAME_PARTY = {"Mary Peltola": "D", "Dan Osborn": "I"}
def party_ctx(nm, mk, desc):
    p = party(nm)
    if p: return p
    if nm in NAME_PARTY: return NAME_PARTY[nm]
    for txt in (mk.get("question") or "", mk.get("description") or "", desc):
        m = re.search(re.escape(nm) + r"\s*\((D|R|I|L|G)\b", txt)
        if m: return m.group(1)
        m = re.search(re.escape(nm) + r",?\s+(?:the\s+)?(?:incumbent\s+)?(Democrat|Republican|Independent)", txt)
        if m: return m.group(1)[0]
    return ""
def race_from(e):
    t = (e.get("title") or "").strip()
    m = RACE_SG.match(t); h = RACE_H.match(t)
    if m and m.group(1) in STATES: office, st, dist = m.group(2).lower(), STATES[m.group(1)], None
    elif h: office, st, dist = "house", h.group(1), h.group(2)
    else: return None
    desc = e.get("description") or ""
    cands = []
    for mk in e.get("markets") or []:
        p = price(mk); nm = (mk.get("groupItemTitle") or mk.get("question") or "").strip()
        if p is None or not nm or re.match(r"^((Person|Party|Option|Candidate|Player) [A-Z]|[A-Z]|Other|Another .*|Someone else)$", nm): continue
        cands.append({"n": re.sub(r"\s*\((D|R|I|L|G)\)\s*$", "", nm), "p": round(p, 4), "pty": party_ctx(nm, mk, desc),
                      "won": bool(mk.get("closed") and p >= 0.99)})
    cands = [c for c in sorted(cands, key=lambda c: -c["p"]) if c["p"] >= 0.005][:4]
    if not cands: return None
    top = cands[0]
    return {"office": office, "st": st, "d": dist, "slug": e.get("slug"), "vol": round(float(e.get("volume") or 0)),
            "cands": cands, "lead": top["pty"], "called": top["won"] or (bool(e.get("closed")) and top["p"] >= 0.99)}
def pick_two(e):
    r = {}
    for mk in e.get("markets") or []:
        p = price(mk); nm = (mk.get("groupItemTitle") or "")
        if p is None: continue
        if nm.startswith("Democrat"): r["D"] = round(p, 4)
        elif nm.startswith("Republican"): r["R"] = round(p, 4)
    return r
def buckets(e):
    out = []
    for mk in e.get("markets") or []:
        p = price(mk)
        if p is None or re.match(r"^((Person|Party|Option|Candidate|Player) [A-Z]|[A-Z]|Other|Another .*|Someone else)$", mk.get("groupItemTitle") or ""): continue
        try: th = float(mk.get("groupItemThreshold") or 0)
        except Exception: th = 0
        out.append((th, {"b": mk.get("groupItemTitle"), "p": round(p, 4)}))
    return [b for _, b in sorted(out, key=lambda x: x[0])]
def polymarket():
    evs = poly_events(); races = {}; control = {}; seats = {}; balance = []
    for e in evs:
        t = (e.get("title") or "").strip(); s = e.get("slug") or ""
        if s.startswith("which-party-will-win-the-house-in-2026"): control["house"] = pick_two(e)
        elif s.startswith("which-party-will-win-the-senate-in-2026"): control["senate"] = pick_two(e)
        elif s.startswith("balance-of-power-2026-midterms"):
            balance = [{"b": mk.get("groupItemTitle"), "p": price(mk)} for mk in e.get("markets") or [] if price(mk) is not None]
        elif re.match(r"^Republican (Senate|House) seats after the 2026", t):
            seats[("senate" if "Senate" in t else "house")] = buckets(e)
        else:
            r = race_from(e)
            if r:
                k = (r["office"], r["st"], r["d"])
                if k not in races or r["vol"] > races[k]["vol"]: races[k] = r
    out = {"senate": [], "governor": [], "house": []}
    for r in races.values(): out[r["office"]].append(r)
    for k in out: out[k].sort(key=lambda r: (r["st"], r["d"] or ""))
    DIAG["poly_races"] = {k: len(v) for k, v in out.items()}
    return {"control": control, "balance": balance, "seats": seats, "races": out}
def kalshi():
    res = {}; tried = {}
    for ser, ch in (("CONTROLH", "house"), ("CONTROLS", "senate")):
        evs = []
        for url in (f"https://api.elections.kalshi.com/trade-api/v2/events?series_ticker={ser}&with_nested_markets=true&limit=50",
                    f"https://api.elections.kalshi.com/trade-api/v2/events/{ser}-2026?with_nested_markets=true",
                    f"https://api.elections.kalshi.com/trade-api/v2/events/{ser}-26?with_nested_markets=true"):
            try:
                j = jget(url, tries=1); evs += j.get("events") or ([j["event"]] if j.get("event") else [])
            except Exception as ex: tried[url[-60:]] = repr(ex)[:80]
        for e in evs:
            if not re.search(r"2026|-26$", e.get("event_ticker", "")): continue
            mks = e.get("markets") or []
            for m in mks:
                pty = ((m.get("custom_strike") or {}).get("Party") or m.get("yes_sub_title") or "")
                try:
                    b, a = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
                    p = (a + b) / 2 if b and a else float(m.get("last_price_dollars") or 0)
                except Exception: continue
                if pty.startswith("Dem"): res.setdefault(ch, {})["D"] = round(p, 4)
                elif pty.startswith("Rep"): res.setdefault(ch, {})["R"] = round(p, 4)
    DIAG["kalshi"] = {"found": res, "errors": tried}
    return res
def _ans(a):
    c = next((a[k] for k in ("choice", "answer", "party", "name", "candidate") if isinstance(a, dict) and a.get(k)), "")
    v = next((a[k] for k in ("pct", "percent", "value", "share") if isinstance(a, dict) and a.get(k) is not None), None)
    try: v = float(v)
    except Exception: v = None
    return str(c), v
def poll_avg(js, a_key, b_key, subject=None, days=None):
    rows = []
    for p in js:
        if subject and subject.lower() not in json.dumps(p.get("subject") or p.get("seat_name") or "").lower(): continue
        A = B = None
        for a in p.get("answers") or []:
            c, v = _ans(a)
            if v is None: continue
            if a_key(c): A = v
            elif b_key(c): B = v
        if A is None or B is None or not p.get("end_date"): continue
        rows.append({"who": p.get("pollster") or "?", "end": p["end_date"][:10], "a": A, "b": B, "pop": p.get("population") or "", "n": p.get("sample_size")})
    if not rows: return None
    rows.sort(key=lambda r: r["end"], reverse=True)
    latest = rows[0]["end"]
    for days in (21, 30, 45, 60, 90):
        t0 = time.mktime(time.strptime(latest, "%Y-%m-%d")) - days * 86400
        cut = time.strftime("%Y-%m-%d", time.localtime(t0)); per = {}
        for r in rows:
            if r["end"] >= cut and r["who"] not in per: per[r["who"]] = r
        if len(per) >= 6: break
    use = list(per.values())
    return {"a": round(sum(r["a"] for r in use) / len(use), 1), "b": round(sum(r["b"] for r in use) / len(use), 1),
            "pollsters": len(use), "since": cut, "latest": latest, "days": days, "recent": rows[:12]}
def polls():
    out = {}
    try:
        js = jget("https://api.votehub.com/polls", {"poll_type": "generic-ballot"})
        g = poll_avg(js, lambda c: c.lower().startswith("dem") or c == "D", lambda c: c.lower().startswith("rep") or c == "R")
        if g: out["generic"] = g
        DIAG["vh_generic"] = len(js)
    except Exception as ex: DIAG["vh_generic_err"] = repr(ex)[:150]
    try:
        js = jget("https://api.votehub.com/polls", {"poll_type": "approval"})
        g = poll_avg(js, lambda c: c.lower().startswith("approve"), lambda c: c.lower().startswith("disapprove"), subject="trump")
        if g: out["approval"] = g
        DIAG["vh_approval"] = len(js)
    except Exception as ex: DIAG["vh_approval_err"] = repr(ex)[:150]
    return out
def build():
    d = {"built": int(time.time()), "poly": polymarket(), "polls": polls()}
    try: d["kalshi"] = kalshi()
    except Exception as ex: d["kalshi"] = {}; DIAG["kalshi_err"] = repr(ex)[:150]
    if not any(d["poly"]["races"].values()): raise RuntimeError("no Polymarket races")
    d["sources"] = ["Polymarket", "Kalshi", "VoteHub"]
    return d
def run(put, key, keep_old):
    d = build(); put("election", "election", d, key)
    return {"races": {k: len(v) for k, v in d["poly"]["races"].items()}, "control": d["poly"]["control"], "kalshi": d.get("kalshi"),
            "polls": {k: (v["a"], v["b"], v["pollsters"]) for k, v in d["polls"].items()}, "diag": DIAG}
