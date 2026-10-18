
import urllib.request, re, time, math, html, threading, datetime, email.utils
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "application/rss+xml, application/xml, text/xml, */*"}
FEEDS = {"CNBC Economy": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "CNBC Top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "WSJ Markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "WSJ Economy": "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed", "NYT Economy": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "NYT Business": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml", "Guardian Economics": "https://www.theguardian.com/business/economics/rss", "FT": "https://www.ft.com/rss/home", "Bloomberg Econ": "https://feeds.bloomberg.com/economics/news.rss", "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss", "CNN Business": "http://rss.cnn.com/rss/money_latest.rss", "Investing.com": "https://www.investing.com/rss/news_14.rss", "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml", "Nasdaq": "https://www.nasdaq.com/feed/rssoutbound?category=Economy", "Fox Business": "https://moxie.foxbusiness.com/google-publisher/economy.xml", "Economist": "https://www.economist.com/finance-and-economics/rss.xml", "Google News Econ": "https://news.google.com/rss/search?q=economy+when:1d&hl=en-US&gl=US&ceid=US:en", "Seeking Alpha": "https://seekingalpha.com/market_currents.xml", "Google News Business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", "Google News Economy 1d": "https://news.google.com/rss/search?q=economy+when:1d&hl=en-US&gl=US&ceid=US:en", "Google News Macro 1d": "https://news.google.com/rss/search?q=inflation+OR+%22federal+reserve%22+OR+tariffs+OR+%22stock+market%22+when:1d&hl=en-US&gl=US&ceid=US:en"}
ECON_FEEDS = set(["CNBC Economy", "WSJ Economy", "NYT Economy", "Guardian Economics", "Bloomberg Econ", "Federal Reserve", "Economist", "Google News Econ", "Google News Economy 1d", "Google News Macro 1d"])
ECON = re.compile(r"\b(econom\w*|inflation\w*|deflation|cpi|ppi|prices?|fed|federal reserve|powell|rates?|yields?|treasur\w*|bonds?|gdp|growth|recession\w*|jobs?|jobless|unemployment|payrolls?|labou?r|wages?|tariffs?|trade|exports?|imports?|deficits?|debt|budget|fiscal|tax\w*|stocks?|markets?|wall street|s&p|dow|nasdaq|dollar|currenc\w*|euro|yen|yuan|oil|opec|crude|gold|commodit\w*|mortgages?|housing|retail sales|consumers?|spending|manufactur\w*|factory|pmi|ecb|bank of england|boj|central banks?|imf|world bank|earnings|profits?|banks?|credit|lending|investors?|shutdown|sanctions?|supply chains?)\b", re.I)
STOP = set("a an the and or of to in on for with at by from as is are was were be been being it its this that these those after before over under into amid about than more most new says say said will would could can may might not no up down out off why how what who when where which while just us u.s you your their they he she his her has have had do does live latest".split())
SYN = {"federal": "fed", "powell": "fed", "wholesale": "ppi", "producer": "ppi", "jobless": "jobs", "payroll": "jobs", "employment": "jobs", "job": "jobs", "equitie": "stock", "share": "stock", "inflationary": "inflation"}
CANON = [("cnbc", "CNBC"), ("marketwatch", "MarketWatch"), ("wsj", "WSJ"), ("wall street journal", "WSJ"), ("nyt", "NYT"), ("new york times", "NYT"),
         ("bbc", "BBC"), ("guardian", "The Guardian"), ("financial times", "FT"), ("ft", "FT"), ("bloomberg", "Bloomberg"), ("reuters", "Reuters"),
         ("fox business", "Fox Business"), ("economist", "The Economist"), ("associated press", "AP"), ("ap news", "AP"), ("yahoo finance", "Yahoo Finance"),
         ("investing.com", "Investing.com"), ("nasdaq", "Nasdaq"), ("seeking alpha", "Seeking Alpha"), ("federal reserve", "Federal Reserve")]
def canon(name):
    n = (name or "").strip(); l = n.lower()
    for k, v in CANON:
        if re.search(r"(?<![\w.])" + re.escape(k) + r"(?![\w])", l): return v
    return re.sub(r"\s+(economy|econ|economics|top|markets|business|news)$", "", n, flags=re.I) or n

def pdate(s):
    s = (s or "").strip()
    if not s: return None
    d = None
    try: d = email.utils.parsedate_to_datetime(s)
    except Exception: pass
    if d is None:
        try: d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None
    if d.tzinfo is None: d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()
def clean(t): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t or ""))).strip()
def tag(el): return el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""

def parse(raw):
    try: root = ET.fromstring(raw)
    except ET.ParseError:
        txt = raw.decode("utf-8", "replace")
        txt = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", txt)
        txt = re.sub(r"^<\?xml[^>]*\?>", "", txt.strip())
        root = ET.fromstring(txt)
    out = []
    for el in root.iter():
        if tag(el) not in ("item", "entry"): continue
        d = {"title": "", "link": "", "date": "", "source": ""}
        for c in el:
            t = tag(c)
            if t == "title": d["title"] = clean("".join(c.itertext()))
            elif t == "link":
                h = c.get("href")
                if h and c.get("rel", "alternate") == "alternate": d["link"] = d["link"] or h
                elif not h and (c.text or "").strip(): d["link"] = c.text.strip()
            elif t in ("pubdate", "published", "updated", "date") and not d["date"]: d["date"] = (c.text or "").strip()
            elif t == "source": d["source"] = clean(c.text)
        if d["title"]: out.append(d)
    return out

def toks(title):
    out = set()
    for w in re.findall(r"[a-z0-9$%.'’&-]+", title.lower()):
        w = w.replace("’", "'").strip(".'-&")
        if w.endswith("'s"): w = w[:-2]
        if not w or w in STOP: continue
        if not any(ch.isdigit() for ch in w):
            if len(w) < 3: continue
            if len(w) > 4 and w.endswith("s") and not w.endswith("ss"): w = w[:-1]
        out.add(SYN.get(w, w))
    return frozenset(out)

def fetch_feed(kv):
    name, url = kv
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12) as r: raw = r.read()
        goog = "news.google.com" in url; res = []
        for d in parse(raw):
            t = pdate(d["date"])
            if t is None: continue
            title, src = d["title"], canon(name)
            if goog and d["source"]:
                src = canon(d["source"])
                if " - " in title and title.rsplit(" - ", 1)[1].strip().lower() == d["source"].lower(): title = title.rsplit(" - ", 1)[0].strip()
            hits = len(ECON.findall(title))
            if name not in ECON_FEEDS and hits == 0: continue
            res.append({"title": title, "link": d["link"], "src": src, "feed": name, "t": t, "google": goog, "hits": hits, "toks": toks(title)})
        return name, res, None
    except Exception as e:
        return name, [], f"{type(e).__name__}: {e}"[:120]

def cluster(pool):
    df = Counter()
    for i in pool: df.update(i["toks"])
    N = len(pool) + 1
    idf = {k: math.log(N / v) + 0.5 for k, v in df.items()}
    W = lambda s: sum(idf[t] for t in s) or 1e-9
    for i in pool: i["w"] = W(i["toks"])
    cl = []
    for it in sorted(pool, key=lambda i: -i["t"]):
        A = it["toks"]
        if not A: continue
        best, bs = None, 0
        for c in cl:
            for m in c:
                sh = A & m["toks"]
                if len(sh) < 2: continue
                s = W(sh) / min(it["w"], m["w"])
                if (len(sh) >= 3 and s >= 0.45) or s >= 0.7:
                    if s > bs: bs, best = s, c
        if best is not None: best.append(it)
        else: cl.append([it])
    return cl

def build(n=10):
    now = time.time()
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(fetch_feed, FEEDS.items()))
    items, status, ok = [], {}, 0
    for name, its, err in res:
        status[name] = err or len(its)
        if err is None: ok += 1; items += its
    seen, uniq = set(), []
    for i in items:
        k = (i["src"], i["title"].lower())
        if k not in seen: seen.add(k); uniq.append(i)
    for window in (24, 36, 48, 96):
        pool = [i for i in uniq if now - window * 3600 <= i["t"] <= now + 1800]
        cl = cluster(pool)
        if len(cl) >= n: break
    out = []
    for c in cl:
        srcs = sorted({m["src"] for m in c})
        latest = min(max(m["t"] for m in c), now)
        rep = max(c, key=lambda m: (not m["google"], min(m["hits"], 3), m["t"]))
        score = len(srcs) + 0.25 * min(max(m["hits"] for m in c), 3) + 0.75 * max(0, 1 - (now - latest) / 86400)
        links, done = [], set()
        for m in sorted(c, key=lambda m: m["google"]):
            if m["src"] not in done and m["link"]: done.add(m["src"]); links.append({"src": m["src"], "link": m["link"]})
        out.append({"title": rep["title"], "link": rep["link"], "sources": srcs, "n": len(srcs), "time": int(latest),
                    "first": int(min(m["t"] for m in c)), "links": links, "score": round(score, 2)})
    out.sort(key=lambda x: -x["score"])
    return {"items": out[:n], "feeds_ok": ok, "feeds_total": len(FEEDS), "sources_total": len({i["src"] for i in pool}),
            "headlines_scanned": len(pool), "window_h": window, "updated": int(now), "feeds": status}

_lock = threading.Lock(); _cache = {"t": 0, "v": None}
def top():
    v = _cache["v"]
    if v and time.time() - _cache["t"] < 300: return v
    with _lock:
        if _cache["v"] and time.time() - _cache["t"] < 300: return _cache["v"]
        try:
            v = build()
            if v["items"] or not _cache["v"]: _cache.update(t=time.time(), v=v)
        except Exception:
            if not _cache["v"]: raise
        return _cache["v"]
threading.Thread(target=lambda: (lambda: top())() if True else None, daemon=True).start()
