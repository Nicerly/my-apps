"""Economic App data build: runs the app's own server code in-process and saves every API answer the page needs (encrypted)."""
import os, sys, ast, re, json, time, threading, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__))
RANGES = ["1D", "5D", "1M", "6M", "1Y", "5Y"]
def safe(s): return re.sub(r"[^A-Za-z0-9]", lambda m: "_%02X" % ord(m.group()), s)
def load_server():
    path = os.path.join(HERE, "server.py"); src = open(path, encoding="utf-8").read(); tree = ast.parse(src); keep = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)): keep.append(n); continue
        seg = ast.get_source_segment(src, n) or ""
        if re.search(r"serve_forever|HTTPServer\(|__name__|\.start\(\)|os\.chdir", seg): continue
        keep.append(n)
    tree.body = keep
    if HERE not in sys.path: sys.path.insert(0, HERE)
    ns = {"__file__": path, "__name__": "econ_server"}
    exec(compile(tree, path, "exec"), ns); return ns
def prev_core(k):
    base = os.environ.get("PAGES_URL", "").rstrip("/")
    if not base: return {}
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with urllib.request.urlopen(f"{base}/econ/data/core.enc?t={int(time.time())}", timeout=30) as r: b = r.read()
        return json.loads(AESGCM(k).decrypt(b[:12], b[12:], None))
    except Exception: return {}
def syms_in(o, out):
    if isinstance(o, dict):
        for kk, v in o.items():
            if kk in ("symbol", "sym") and isinstance(v, str): out.append(v)
            elif kk == "symbols" and isinstance(v, list): out += [x for x in v if isinstance(x, str)]
            else: syms_in(v, out)
    elif isinstance(o, list):
        for v in o: syms_in(v, out)
    return out
def run(put, k, keep_old):
    t0 = time.time(); ns = load_server()
    H = ns.get("H") or next(v for v in ns.values() if isinstance(v, type) and issubclass(v, BaseHTTPRequestHandler) and hasattr(v, "do_GET"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]; errs = {}
    def tryget(name, p, t=120):
        try:
            with urllib.request.urlopen(base + p, timeout=t) as r: return json.load(r)
        except Exception as e: errs[name] = repr(e)[:160]; return None
    old = prev_core(k)
    wl = tryget("watchlist", "/api/watchlist") or old.get("watchlist") or []
    with ThreadPoolExecutor(3) as ex:
        fm, fn, ft = ex.submit(tryget, "macro", "/api/macro"), ex.submit(tryget, "news", "/api/news"), ex.submit(tryget, "trending", "/api/trending")
        macro, news, trending = fm.result() or old.get("macro"), fn.result() or old.get("news"), ft.result() or old.get("trending")
    ids = []
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("id"), str): ids.append(o["id"])
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(macro); ids = list(dict.fromkeys(ids))
    series = dict(old.get("series") or {})
    with ThreadPoolExecutor(4) as ex:
        for i, v in zip(ids, ex.map(lambda i: tryget("series:" + i, "/api/macro/series?id=" + urllib.parse.quote(i)), ids)):
            if v: series[i] = v
    try: extra = json.load(open(os.path.join(HERE, "extra_symbols.json")))
    except Exception: extra = []
    SYM = ns.get("SYM") or re.compile(r"^[A-Za-z0-9.\-^=]{1,15}$")
    cand = list(wl) + list(ns.get("DEFAULT", [])) + list(extra) + (syms_in(trending, []) if trending else [])
    avail = list(dict.fromkeys(s for s in cand if isinstance(s, str) and SYM.match(s)))[:80]
    quotes = {}
    chunks = [avail[i:i + 10] for i in range(0, len(avail), 10)]
    with ThreadPoolExecutor(3) as ex:
        for res in ex.map(lambda c: tryget("quotes:" + c[0], "/api/quotes?s=" + urllib.parse.quote(",".join(c), safe=",")), chunks):
            for q in (res if isinstance(res, list) else []):
                if isinstance(q, dict) and q.get("symbol") and q.get("price") is not None: quotes[q["symbol"]] = q
    oq = old.get("quotes") or {}; stale = []
    for s in avail:
        if s not in quotes and s in oq: quotes[s] = oq[s]; stale.append(s)
    charts_ok, charts_failed = 0, []
    def one(s):
        d = {}
        for rk in RANGES:
            r = tryget(f"chart:{s}:{rk}", f"/api/chart?s={urllib.parse.quote(s)}&range={rk}")
            if isinstance(r, dict) and r.get("candles"): d[rk] = r
        return s, d
    with ThreadPoolExecutor(6) as ex:
        for s, d in ex.map(one, avail):
            if d: put("econ", "c/" + safe(s), d, k); charts_ok += 1
            else: charts_failed.append(s + ("(kept old)" if keep_old("econ", "c/" + safe(s)) else ""))
    srv.shutdown()
    if not quotes and not macro:
        if keep_old("econ", "core"): return {"core": "kept previous", "errs": dict(list(errs.items())[:8])}
        raise RuntimeError("no data: " + json.dumps(dict(list(errs.items())[:6]))[:400])
    core = {"watchlist": [s for s in wl if s in avail] or list(wl), "avail": avail, "quotes": quotes, "macro": macro, "series": series,
            "news": news, "trending": trending, "built": int(time.time())}
    put("econ", "core", core, k)
    return {"avail": len(avail), "quotes": len(quotes), "stale_quotes": stale[:10], "macro": bool(macro), "series": len(series), "news": bool(news),
            "trending": bool(trending), "charts_ok": charts_ok, "charts_failed": charts_failed[:20], "n_errs": len(errs),
            "errs": dict(list(errs.items())[:10]), "secs": int(time.time() - t0)}
