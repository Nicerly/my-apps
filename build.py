#!/usr/bin/env python3
"""Builds encrypted data files for the static apps (run by GitHub Actions every ~30 min)."""
import os, sys, json, time, base64, subprocess, urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
ROOT = os.path.dirname(os.path.abspath(__file__)); SITE = os.path.join(ROOT, "site")
def key(name):
    v = os.environ.get(name, "").strip()
    if not v: raise RuntimeError("missing secret " + name)
    k = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)); assert len(k) == 32; return k
def put(app, rel, obj, k):
    p = os.path.join(SITE, app, "data", rel + ".enc"); os.makedirs(os.path.dirname(p), exist_ok=True)
    n = os.urandom(12); open(p, "wb").write(n + AESGCM(k).encrypt(n, json.dumps(obj, separators=(",", ":")).encode(), None))
def keep_old(app, rel):
    base = os.environ.get("PAGES_URL", "").rstrip("/")
    if not base: return False
    try:
        with urllib.request.urlopen(f"{base}/{app}/data/{rel}.enc?t={int(time.time())}", timeout=30) as r: b = r.read()
        p = os.path.join(SITE, app, "data", rel + ".enc"); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b); return True
    except Exception as e:
        print("  could not keep previous", app, rel, repr(e)[:120]); return False
def build_news():
    sys.path.insert(0, os.path.join(ROOT, "src", "news")); import news
    d = news.build()
    if not d.get("stories"): raise RuntimeError("no stories")
    d["built"] = int(time.time())
    put("news", "news", d, key("NEWS_KEY"))
    return {"stories": len(d["stories"]), "sweden": len(d.get("sweden") or []), "topics": {t: len(v) for t, v in (d.get("by_topic") or {}).items()}}
def build_econ():
    sys.path.insert(0, os.path.join(ROOT, "src", "econ")); import build_econ
    return build_econ.run(put, key("ECON_KEY"), keep_old)
APPS = {"news": (build_news, ["news"]), "econ": (build_econ, ["core"])}
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:  # each app in its own process (both have a module called news.py)
        todo = [a for a in APPS if a != "econ" or os.path.exists(os.path.join(ROOT, "src", "econ", "build_econ.py"))]
        rc = [subprocess.run([sys.executable, os.path.abspath(__file__), a]).returncode for a in todo]
        sys.exit(0 if 0 in rc else 1)
    app = args[0]; fn, rels = APPS[app]; t = time.time()
    try:
        print(app, "OK", json.dumps(fn())[:800], f"{time.time() - t:.0f}s", flush=True)
    except Exception as e:
        print(app, "FAILED", repr(e)[:400], flush=True)
        kept = [keep_old(app, r) for r in rels]
        sys.exit(0 if kept and all(kept) else 1)
