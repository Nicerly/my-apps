"""Midterms 2026 data from journalism sources only: The New York Times (live results, race calls,
seat counts, race ratings), Inside Elections (race ratings) and polls sponsored by news organisations
(collected by VoteHub). No betting or prediction markets. Output is public, unencrypted JSON."""
import json, re, time, datetime, urllib.request, urllib.parse
DATE = "2026-11-03"
NYT = "https://static01.nyt.com/elections-assets/pages/data/%s/results-%s.json"
IE = "https://insideelections.com/wp-content/themes/inside-elections/cache/ratings_latest_%s_year=2026_district=all_clean.json"
VH = "https://api.votehub.com/polls"
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      "Accept": "application/json,*/*"}
OFFICES = {"senate": "S", "house": "H", "governor": "G"}
STATES = dict(x.split(":") for x in ("AL:Alabama,AK:Alaska,AZ:Arizona,AR:Arkansas,CA:California,CO:Colorado,CT:Connecticut,DE:Delaware,"
    "FL:Florida,GA:Georgia,HI:Hawaii,ID:Idaho,IL:Illinois,IN:Indiana,IA:Iowa,KS:Kansas,KY:Kentucky,LA:Louisiana,ME:Maine,MD:Maryland,"
    "MA:Massachusetts,MI:Michigan,MN:Minnesota,MS:Mississippi,MO:Missouri,MT:Montana,NE:Nebraska,NV:Nevada,NH:New Hampshire,"
    "NJ:New Jersey,NM:New Mexico,NY:New York,NC:North Carolina,ND:North Dakota,OH:Ohio,OK:Oklahoma,OR:Oregon,PA:Pennsylvania,"
    "RI:Rhode Island,SC:South Carolina,SD:South Dakota,TN:Tennessee,TX:Texas,UT:Utah,VT:Vermont,VA:Virginia,WA:Washington,"
    "WV:West Virginia,WI:Wisconsin,WY:Wyoming,DC:District of Columbia").split(","))
AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}
ROM = {"I": 1, "II": 2, "III": 3}
PARTY = {"DEM": "D", "GOP": "R", "REP": "R", "IND": "I", "LIB": "L", "GRN": "G"}
CALL = {"too_early": "Too early to call", "too_close": "Too close to call", "uncalled": "Not called yet",
        "called": "Called", "runoff": "Heading to a runoff", "won": "Called"}
MEDIA = re.compile(r"New York Times|\bNYT\b|\bCNN\b|Fox News|\bABC\b|Washington Post|\bCBS\b|\bNBC\b|Wall Street Journal|\bWSJ\b|"
                   r"Reuters|Economist|Associated Press|AP-NORC|\bNPR\b|\bPBS\b|USA Today|Bloomberg|Los Angeles Times|Financial Times|\bCNBC\b|\bMSNBC\b", re.I)
SOURCES = [
    {"name": "The New York Times", "what": "Live results, race calls, seat counts and race ratings",
     "url": "https://www.nytimes.com/interactive/2026/11/03/us/elections/results-senate.html"},
    {"name": "Inside Elections (Nathan L. Gonzales)", "what": "Nonpartisan race ratings", "url": "https://insideelections.com/ratings/senate"},
    {"name": "Polls sponsored by news organisations (e.g. NYT/Siena, CNN, Fox News, CBS, Reuters/Ipsos, The Economist/YouGov)",
     "what": "Generic congressional ballot and Trump approval; only polls run for news outlets are kept (list collected by VoteHub)",
     "url": "https://votehub.com/polls/"},
]

def getj(url, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e; time.sleep(2 + 3 * i)
    raise last

def rating(s):
    if not s: return None
    t = str(s).lower()
    if "not up" in t: return None
    if "toss" in t: return {"t": "Toss-up", "s": 0}
    side = "D" if "dem" in t else "R" if ("rep" in t or "gop" in t) else None
    if not side: return {"t": str(s), "s": None}
    lvl = next((w for w in ("solid", "safe", "likely", "lean", "tilt") if w in t), "")
    mag = {"solid": 3, "safe": 3, "likely": 2, "lean": 1, "tilt": 0.5}.get(lvl, 1)
    return {"t": ({"safe": "Solid"}.get(lvl, lvl.capitalize()) + " " + side).strip(), "s": mag if side == "D" else -mag}

def votes_of(c):
    v = c.get("votes")
    if isinstance(v, dict): v = v.get("total", v.get("votes"))
    try: return int(v or 0)
    except Exception: return 0

def cand(cid, m, v, w):
    nm = ((m.get("first_name") or "").strip() + " " + (m.get("last_name") or "").strip()).strip() or str(cid)
    if m.get("suffix"): nm += " " + str(m["suffix"])
    pt = m.get("party") or {}
    p = PARTY.get(str(pt.get("nyt_id") or "").upper()) or ("I" if "indep" in str(pt.get("name") or "").lower() else "O")
    return {"n": nm, "p": p, "pn": pt.get("name"), "v": v, "w": 1 if w else 0, "inc": 1 if m.get("incumbent") else 0,
            "o": m.get("order") or m.get("ballot_order") or 99}

def parse_race(r, off, close):
    tru = r.get("top_reporting_unit") or {}
    st = str(tru.get("state_postal") or str(r.get("nyt_id") or "")[:2]).upper()
    if st not in STATES: return None
    meta = r.get("candidate_metadata") or {}
    won = set((r.get("outcome") or {}).get("won") or [])
    cands, seen = [], set()
    for c in tru.get("candidates") or []:
        cid = c.get("nyt_id"); seen.add(cid)
        cands.append(cand(cid, meta.get(cid) or {}, votes_of(c), c.get("winner") or cid in won))
    for cid, m in meta.items():
        if cid not in seen: cands.append(cand(cid, m or {}, 0, cid in won))
    tot = sum(c["v"] for c in cands)
    for c in cands: c["pct"] = round(100.0 * c["v"] / tot, 1) if tot else None
    cands.sort(key=lambda c: (-c["v"], c["o"] if isinstance(c["o"], int) else 99))
    for c in cands: c.pop("o", None)
    seat = str(r.get("seat_number") or "").strip()
    if off == "senate":
        cls = int(seat) if seat.isdigit() else 2
        label = STATES[st] + (" (special)" if cls != 2 else ""); key = f"{st}-{cls}"; srt = (STATES[st], cls)
    elif off == "house":
        n = int(seat) if seat.isdigit() else 0
        al = st in AT_LARGE or n == 0 or "large" in str(r.get("seat") or "").lower()
        label = f"{st} at-large" if al else f"{st}-{n:02d}"; key = f"{st}-{n}"; cls = n; srt = (STATES[st], n)
    else:
        label = STATES[st]; key = st; cls = None; srt = (STATES[st], 0)
    w = next((c for c in cands if c["w"]), None)
    raw = r.get("race_call_status")
    status = "Called" if w else (CALL.get(raw) or (str(raw).replace("_", " ").capitalize() if raw else "Awaiting results"))
    try: eevp = float(tru["eevp"]) if tru.get("eevp") is not None else None
    except Exception: eevp = None
    return {"key": key, "st": st, "sn": STATES[st], "label": label, "cls": cls, "_srt": srt,
            "nyt": rating(r.get("rating") or r.get("general_rating")), "status": status, "call": raw,
            "winner": w["p"] if w else None, "eevp": eevp, "unc": 1 if r.get("uncontested") else 0,
            "close": close.get(st), "cands": cands, "upd": r.get("updated_at")}

def ie_index(recs, off):
    m = {}
    for x in recs or []:
        rt = rating(x.get("rating"))
        if not rt: continue
        st = str(x.get("state") or x.get("district") or "")[:2].upper()
        if off == "senate": k = (st, ROM.get(str(x.get("office") or "").upper()))
        elif off == "house":
            dg = re.findall(r"\d+", str(x.get("district") or "")) or re.findall(r"\d+", str(x.get("office") or ""))
            k = (st, int(dg[0]) if dg else 0)
        else: k = (st, None)
        m.setdefault(k, rt)
    return m

def ie_lookup(m, off, x):
    st = x["st"]
    if off == "senate":
        r = m.get((st, x["cls"]))
        if r is None:
            same = [v for k, v in m.items() if k[0] == st]
            r = same[0] if len(same) == 1 else None
        return r
    if off == "house":
        r = m.get((st, x["cls"]))
        if r is None and st in AT_LARGE: r = m.get((st, 0)) or m.get((st, 1))
        return r
    return m.get((st, None))

def ans(p):
    out = {}
    for a in p.get("answers") or []:
        k = str(a.get("choice") or a.get("answer") or a.get("name") or "").strip().lower()
        v = a.get("pct", a.get("value", a.get("percent")))
        try: out[k] = float(v)
        except Exception: pass
    return out

def pick(a, names):
    for k, v in a.items():
        if k in names or any(len(n) > 2 and k.startswith(n) for n in names): return v
    return None

def media(polls, kx, ky, fx, fy):
    rows = []
    for p in polls or []:
        sp = [str(s) for s in (p.get("sponsors") or []) if s]
        pol = str(p.get("pollster") or "")
        who = "/".join(dict.fromkeys(sp + ([pol] if pol else [])))
        if not MEDIA.search(who): continue
        a = ans(p); x, y = pick(a, fx), pick(a, fy)
        if x is None or y is None: continue
        u = p.get("url") or p.get("source")
        rows.append({"who": who, "end": str(p.get("end_date") or "")[:10], "n": p.get("sample_size"), "pop": p.get("population"),
                     kx: round(x, 1), ky: round(y, 1), "url": u if isinstance(u, str) and u.startswith("http") else None})
    rows.sort(key=lambda r: r["end"], reverse=True)
    out = {"avg": None, "polls": rows[:15]}
    if rows:
        try: cut = (datetime.date.fromisoformat(rows[0]["end"]) - datetime.timedelta(days=45)).isoformat()
        except Exception: cut = ""
        used, seen = [], set()
        for r in rows:
            if r["end"] < cut: break
            if r["who"] in seen: continue
            seen.add(r["who"]); used.append(r)
        if used:
            out["avg"] = {kx: round(sum(r[kx] for r in used) / len(used), 1), ky: round(sum(r[ky] for r in used) / len(used), 1),
                          "n": len(used), "from": used[-1]["end"], "to": used[0]["end"]}
    return out

def vh(**params):
    return getj(VH + "?" + urllib.parse.urlencode(params))

def polls(errs):
    out = {}
    try:
        out["generic"] = media(vh(poll_type="generic-ballot"), "d", "r", ("d", "dem", "democrat", "democrats", "democratic"),
                               ("r", "rep", "gop", "republican", "republicans"))
    except Exception as e: errs.append("Polls (generic ballot): " + type(e).__name__)
    try:
        try: ap = vh(poll_type="approval", subject="Trump")
        except Exception: ap = []
        if not ap: ap = vh(poll_type="approval")
        ap = [p for p in ap if "trump" in str(p.get("subject") or "trump").lower()]
        out["approval"] = media(ap, "ap", "dis", ("approve", "approval"), ("disapprove", "disapproval"))
    except Exception as e: errs.append("Polls (approval): " + type(e).__name__)
    return out

def build():
    out = {"v": 2, "date": DATE, "offices": {}, "errors": [], "sources": SOURCES}
    ie = {}
    for off in OFFICES:
        try: ie[off] = getj(IE % off).get("ratings") or []
        except Exception as e: ie[off] = []; out["errors"].append(f"Inside Elections {off}: {type(e).__name__}")
    close = {}
    for off, code in OFFICES.items():
        try: d = getj(NYT % (DATE, off))
        except Exception as e:
            out["errors"].append(f"NYT {off}: {type(e).__name__}"); continue
        for pc in d.get("pollClosingTimes") or []:
            s = ((pc.get("reporting_unit") or {}).get("state_postal") or "").upper(); t = pc.get("poll_closing_time")
            if s and t and t > close.get(s, ""): close[s] = t
        iem = ie_index(ie.get(off), off)
        races, seen = [], set()
        for r in d.get("races") or []:
            if r.get("office_id") not in (code, None): continue
            x = parse_race(r, off, close)
            if not x or x["key"] in seen: continue
            seen.add(x["key"]); x["ie"] = ie_lookup(iem, off, x); races.append(x)
        races.sort(key=lambda x: x["_srt"])
        for x in races: x.pop("_srt", None)
        won, called = {}, 0
        for x in races:
            if x["winner"]:
                called += 1; k = x["winner"] if x["winner"] in ("D", "R") else "O"; won[k] = won.get(k, 0) + 1
        try: ctrl = dict((d.get("partyControlData") or {}).get("results", [{}])[0].get("offices", {}).get(code) or {})
        except Exception: ctrl = {}
        for k in list(ctrl):
            if k.startswith("model") or k.startswith("nyt_model"): ctrl.pop(k)
        out["offices"][off] = {"races": races, "won": won, "called": called, "control": ctrl,
                               "updated": (d.get("resultsMeta") or {}).get("resultsUpdatedAt")}
    if not out["offices"]: raise RuntimeError("NYT results unavailable: " + "; ".join(out["errors"]))
    out["polls"] = polls(out["errors"])
    out["built"] = int(time.time())
    return out

def summary(d):
    s = {o: len(v["races"]) for o, v in d["offices"].items()}
    s["called"] = {o: v["called"] for o, v in d["offices"].items()}
    s["polls"] = {k: len(v.get("polls") or []) for k, v in (d.get("polls") or {}).items()}
    s["errors"] = d.get("errors")
    return s

if __name__ == "__main__":
    print(json.dumps(summary(build()))[:2000])
