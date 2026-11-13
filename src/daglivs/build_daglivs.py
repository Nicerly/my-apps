#!/usr/bin/env python3
"""DaglivsMat: fetch Coop's assortment (by category) -> compact catalog JSON for the page.
Usage: COOP_KEY=... python build_daglivs.py OUT.json"""
import os, sys, json, time, datetime, concurrent.futures as cf
import httpx
KEY = os.environ.get("COOP_KEY", "")
STORE = os.environ.get("COOP_STORE", "251300")
EXT = "https://external.api.coop.se/personalization/search"
QS = f"api-version=v1&store={STORE}&groups=CUSTOMER_PRIVATE&device=desktop&direct=false"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
SEEDS = ("mjölk fil yoghurt ost smör grädde ägg bröd knäckebröd flingor müsli havregryn pasta ris nudlar mjöl socker kaffe te juice läsk "
 "vatten öl chips godis choklad kex glass pizza kyckling nötfärs korv bacon skinka fisk lax räkor sill pålägg äpple banan tomat gurka "
 "sallad potatis lök morot svamp kryddor olja ketchup sås buljong konserv bönor soppa taco sylt nötter tofu havredryck barnmat blöjor "
 "schampo tandkräm diskmedel tvättmedel toalettpapper påsar batterier kattmat hundmat snus tidning blommor vitaminer ljus").split()
DEADLINE = time.time() + 1500

def client():
    return httpx.Client(timeout=60, headers={"ocp-apim-subscription-key": KEY, "Content-Type": "application/json",
        "Accept": "application/json", "Origin": "https://www.coop.se", "Referer": "https://www.coop.se/", "User-Agent": UA})
C = client()

def post(path, body, tries=4):
    for i in range(tries):
        try:
            r = C.post(f"{EXT}/{path}?{QS}", json=body)
            if r.status_code in (401, 403):
                sys.exit(f"Coop API refused the key ({r.status_code})")
            if r.status_code == 200 and r.content.strip():
                return r.json()
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1.5 * (i + 1))
    return None

def ro(skip, take): return {"skip": skip, "take": take, "sortBy": [], "facets": []}
def search(q, skip=0, take=200):
    return post("products", {"query": q, "resultsOptions": ro(skip, take), "relatedResultsOptions": {"skip": 0, "take": 0}})
def by_cat(cid, skip=0, take=200):
    return post("entities/by-attribute", {"attribute": {"name": "categoryIds", "value": str(cid)}, "resultsOptions": ro(skip, take)})
def res(d): return (d or {}).get("results") or {}

def cid_of(c): return str(c.get("code") or c.get("id") or "")
def chain(it):
    out, cs = [], it.get("navCategories") or []
    c = cs[0] if cs else None
    while c:
        out.append((cid_of(c), c.get("name") or ""))
        sc = c.get("superCategories") or []
        c = sc[0] if sc else None
    return out[::-1]

def num(d):
    if isinstance(d, bool): return None
    if isinstance(d, (int, float)): return d
    if isinstance(d, dict):
        for k in ("b2cPrice", "price", "amount", "value"):
            if k in d:
                v = num(d[k])
                if v is not None: return v
        for v in d.values():
            x = num(v)
            if x is not None: return x
    return None

def size_of(it):
    s = it.get("packageSizeInformation")
    if isinstance(s, str) and s.strip(): return s.strip()
    ps, pu = it.get("packageSize"), it.get("packageSizeUnit")
    if ps: return f"{ps:g} {pu or ''}".strip() if isinstance(ps, (int, float)) else f"{ps} {pu or ''}".strip()
    return ""

prods, cats = {}, {}
def add(it):
    if it.get("type", "Product") != "Product": return
    pid = str(it.get("id") or it.get("ean") or "")
    if not pid or not it.get("name"): return
    ch = chain(it); par = ""
    for cid, nm in ch:
        if cid and cid not in cats: cats[cid] = [nm, par]
        par = cid or par
    p = num(it.get("salesPriceData"))
    prods[pid] = [pid, it.get("name", "").strip(), (it.get("manufacturerName") or "").strip(), size_of(it),
                  round(p, 2) if p is not None else None, (it.get("comparativePriceText") or "").strip(),
                  it.get("imageUrl") or "", ch[-1][0] if ch else ""]

def fetch_cat(cid):
    got, skip, total, take, fails = [], 0, None, 200, 0
    while time.time() < DEADLINE:
        d = by_cat(cid, skip, take)
        if d is None:
            fails += 1
            if take > 50: take //= 2; continue
            break
        r = res(d); its = r.get("items") or []
        total = r.get("count", total); got += its; skip += len(its)
        if not its or (total is not None and skip >= total) or skip >= 30000: break
    return cid, total, got, fails

def main(out):
    if not KEY: sys.exit("COOP_KEY missing")
    t0 = time.time()
    prev_tops = []
    if os.path.exists(out):
        try:
            pj = json.load(open(out)); prev_tops = [c for c, v in (pj.get("cats") or {}).items() if not v[1]]
        except Exception: pass
    with cf.ThreadPoolExecutor(4) as ex:
        for d in ex.map(lambda q: search(q), SEEDS):
            for it in res(d).get("items") or []: add(it)
    n_seed = len(prods)
    tops = sorted(set([c for c, v in cats.items() if not v[1]] + prev_tops))
    stats = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for cid, total, got, fails in ex.map(fetch_cat, tops):
            for it in got: add(it)
            stats[cid] = [cats.get(cid, ["?"])[0], total, len(got), fails]
    # top categories not fully returned -> fetch their children too
    weak = [c for c, s in stats.items() if s[1] is None or s[2] < 0.95 * (s[1] or 1)]
    kids = [c for c, v in cats.items() if v[1] in weak]
    if kids:
        with cf.ThreadPoolExecutor(4) as ex:
            for cid, total, got, fails in ex.map(fetch_cat, kids):
                for it in got: add(it)
                stats[cid] = [cats.get(cid, ["?"])[0], total, len(got), fails]
    urls = [p[6] for p in prods.values() if p[6]]
    base = os.path.commonprefix(urls[:300]) if urls else ""
    base = base[:base.rfind("/") + 1] if "/" in base else ""
    plist = sorted(prods.values(), key=lambda p: p[1].lower())
    for p in plist:
        if base and p[6].startswith(base): p[6] = p[6][len(base):]
    data = {"v": 1, "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "store": STORE,
            "imgBase": base, "cats": cats, "p": plist}
    tmp = out + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, out)
    print(json.dumps({"products": len(plist), "seed_products": n_seed, "cats": len(cats), "tops": len(tops), "weak": weak,
                      "secs": round(time.time() - t0), "stats": stats}, ensure_ascii=False), file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "catalog.json")
