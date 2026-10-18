import json, os, re, math, time, threading, html, urllib.request, urllib.parse, email.utils, datetime as dt
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "news_cache.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
CORE = ["Economy", "Social unrest", "Science", "Technology", "Disasters"]
TOPICS = CORE + ["Business & Markets", "Energy", "Climate & Environment", "Space"]
MAX_AGE_H = 30
TTL = 900
MASK = [(re.compile(p, re.I), r) for p, r in [
 (r"\bWest Bank\b", "Westbank"), (r"\bGaza Strip\b", "Gaza"), (r"\bBlack Sea\b", "Blacksea"), (r"\bWall Street Journal\b", "WSJ"),
 (r"\bBank of America\b", "BofA"), (r"\b(?:drone|air|missile|military|rocket) ?strikes?\b|\bstrikes? on\b|\bstrikes? (?:in|against|near)\b", "attack")]]
W = {
 "Economy": [(3, r"econom(?:y|ic|ics|ies|ists?)|inflation|gdp|recession|jobs report|unemployment|jobless|payrolls|federal reserve|fed (?:chair|rate|officials?|policy)|interest rates?|rate (?:cut|hike)s?|central banks?|ecb|bank of (?:england|japan|canada)|tariffs?|trade (?:war|deal|talks|deficit|surplus)|stock market|stocks|equities|wall street|s&p 500|nasdaq|dow jones|bond (?:market|yields?)|treasury yields?|oil prices?|crude|opec|imf|world bank|earnings|retail sales|consumer (?:prices|spending|confidence|sentiment)|mortgage rates?|housing market|layoffs|bankrupt\w*|ipo|cost of living|national debt|budget deficit"),
             (1, r"markets?|shares|investors?|prices|budget|tax(?:es)?|debt|deficit|profits?|banks|banking|currenc(?:y|ies)|dollar|yuan|yen|exports?|imports?|wages|consumers?|manufactur\w*|supply chains?|revenue|sales|growth|economists?|jobs|companies|firms")],
 "Social unrest": [(3, r"protests?|protesters?|protesting|riots?|rioters?|rioting|demonstrations?|demonstrators|unrest|curfew|crackdown on (?:protest\w*|dissent|opposition)|tear gas|rubber bullets|uprising|coup|martial law|general strike|on strike|strikes? (?:by|over)|walkouts?|marches|marchers|civil disobedience|looting|mass arrests?|clashes with police|anti-government|dissidents?"),
                   (1, r"police|arrests?|arrested|clashes|clashed|strike|unions?|activists?|rally|rallies|state of emergency|opposition|tensions")],
 "Science": [(3, r"scien(?:ce|ces|tist|tists|tific)|researchers|astronom\w*|telescope|nasa|spacecraft|planets?|exoplanets?|asteroids?|comets?|physic(?:s|ists?)|chemists?|chemistry|biolog\w*|species|fossils?|dinosaurs?|genom\w*|dna|genes?|evolution(?:ary)?|archaeolog\w*|neanderthals?|microplastics?|study finds|new study|climate change|global warming|vaccines?|neuroscien\w*|molecules?|bacteria|ecolog\w*|paleontolog\w*|galax(?:y|ies)|black holes?|orbit"),
             (1, r"study|studies|research|discover(?:y|ies|ed)|brain|climate|ocean|emissions|pollution|health|disease|patients|medic\w*|experiment\w*|lab|space|moon|mars|cells|virus(?:es)?")],
 "Technology": [(3, r"(?-i:AI)|artificial intelligence|chips?|chipmakers?|semiconductors?|nvidia|openai|chatgpt|anthropic|(?-i:Apple|Google|Meta|Microsoft|Amazon)|alphabet|tesla|spacex|starlink|software|cyber ?attacks?|cybersecurity|hack(?:ers?|ed|ing)|data breach|ransomware|robots?|robotics|smartphones?|iphone|android|tiktok|crypto(?:currency|currencies)?|bitcoin|tech|technology|technologies|big tech|start-?ups?|algorithms?|deepfakes?|electric vehicles?|evs|5g|quantum computing|data cent(?:er|re)s?|llms?|large language models?|silicon valley|grok|self-driving|autonomous vehicles?"),
                  (1, r"digital|online|internet|apps?|platforms?|devices?|computers?|computing|social media|satellites?|drones?|batter(?:y|ies)|gadgets?|users")],
 "Disasters": [(3, r"earthquakes?|quakes?|tsunamis?|hurricanes?|typhoons?|cyclones?|tornado(?:es|s)?|floods?|flooding|wildfires?|bushfires?|forest fires?|droughts?|landslides?|mudslides?|volcan(?:o|oes|ic)|eruptions?|heat ?waves?|avalanches?|famine|epidemic|pandemic|outbreaks?|ebola|cholera|mpox|plane crash|train crash|derail\w*|death toll|natural disasters?|blizzards?|monsoon|magnitude|severe weather|extreme weather|storm surge|tropical storm"),
                 (1, r"storms?|evacuat\w*|rescuers?|rescue|explosion|collapsed?|disaster|emergency|survivors|damage|destroyed|fire|rain|snow|heat|crash")],
}
W.update({
 "Economy": [(3, r"econom(?:y|ic|ics|ies|ists?)|inflation|gdp|recession|jobs report|unemployment|jobless|payrolls|federal reserve|fed (?:chair|rate|officials?|policy)|interest rates?|rate (?:cut|hike)s?|central banks?|ecb|bank of (?:england|japan|canada)|tariffs?|trade (?:war|deal|talks|deficit|surplus)|bond (?:market|yields?)|treasury yields?|oil prices?|imf|world bank|retail sales|consumer (?:prices|spending|confidence|sentiment)|mortgage rates?|housing market|cost of living|national debt|budget deficit"),
             (1, r"prices|budget|tax(?:es)?|debt|deficit|currenc(?:y|ies)|dollar|yuan|yen|exports?|imports?|wages|consumers?|manufactur\w*|supply chains?|growth|economists?|jobs|markets?")],
 "Business & Markets": [(3, r"earnings|quarterly (?:results|profits?|revenue|sales)|profit warning|revenue|stock market|stocks|equities|wall street|s&p 500|nasdaq|dow jones|ftse|dax|nikkei|hang seng|ipo|mergers?|acquisitions?|acquires?|acquired|takeover|buyout|ceo|chief executive|layoffs?|job cuts|bankrupt\w*|chapter 11|antitrust|private equity|hedge funds?|venture capital|dividends?|buybacks?|market (?:value|cap\w*)|shareholders?|share price"),
                        (1, r"company|companies|firms?|shares|investors?|deals?|sales|profits?|retailers?|airlines?|automakers?|carmakers?|banks|banking|business|corporate|brands?|billion")],
 "Energy": [(3, r"energy|oil|crude|brent|opec|natural gas|lng|gas prices?|petrol|gasoline|diesel|refiner(?:y|ies)|pipelines?|nuclear (?:power|plants?|reactors?|energy)|reactors?|uranium|renewables?|solar|wind (?:power|farms?|turbines?)|offshore wind|hydropower|hydrogen|power (?:grid|plants?|prices|outages?|stations?)|electricity|blackouts?|utilit(?:y|ies)|coal|fossil fuels?|battery storage|grid"),
            (1, r"power|fuel|drilling|barrels?|exxon|chevron|aramco|totalenergies|equinor|batter(?:y|ies)|charging|emissions")],
 "Climate & Environment": [(3, r"climate change|global warming|climate crisis|emissions|greenhouse gas(?:es)?|carbon (?:dioxide|emissions|capture|tax|market|credits?|neutral)|co2|net zero|methane|deforestation|biodiversity|extinct\w*|endangered|wildlife|conservation|pollution|polluted|air quality|microplastics?|plastic waste|sea levels?|glaciers?|ice sheets?|sea ice|coral reefs?|heat ?waves?|el ni[nñ]o|la ni[nñ]a|cop\d+|paris agreement|environment(?:al)?|ecosystems?|rainforests?|droughts?|warming"),
                           (1, r"climate|weather|temperatures?|forests?|rivers?|oceans?|species|nature|green|sustainab\w*|recycl\w*|waste|floods?|wildfires?")],
 "Space": [(3, r"spacecraft|spaceflight|astronauts?|cosmonauts?|nasa|esa|spacex|starship|falcon 9|blue origin|space (?:agency|mission|probe|telescope|station|force|race|debris|launch)|rocket launch|satellites?|orbit\w*|iss|moon|lunar|artemis|mars|jupiter|saturn|venus|asteroids?|comets?|meteors?|telescopes?|james webb|hubble|astronom\w*|exoplanets?|galax(?:y|ies)|black holes?|solar (?:system|flare|storm|eclipse)|eclipse|cosmic|universe|planets?"),
           (1, r"space|launch(?:es|ed)?|missions?|probe|crew|rockets?|mercury|sun|stars?|cosmos")],
})
WR = {t: [(w, re.compile(r"\b(?:" + p + r")\b", re.I)) for w, p in v] for t, v in W.items()}
CONFLICT = re.compile(r"\b(?:war|wars|warfare|military|troops|soldiers|army|missiles?|drones?|attack(?:s|ed)?|shelling|bomb\w*|ceasefire|truce|gaza|hamas|hezbollah|houthis?|israel\w*|idf|westbank|settlers?|ukrain\w*|russia\w*|kremlin|putin|zelensky\w*|nato|pentagon|iran\w*|militants?|offensive|invasion|frontline|weapons|sanctions?|diplomat\w*|summit|blacksea)\b", re.I)
STOP = set("a an the of to in on for and or but with at by from as is are was were be been it its this that after over into new says say said will would could may might has have had not no up out more than about amid vs his her their they he she we you who what why how when where which first two one year years how live update updates news report reports".split())
def norm(s):
    for rx, r in MASK: s = rx.sub(r, s or "")
    return s

def cfg(): return json.load(open(os.path.join(HERE, "sources.json")))
def fetch(url, t=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r: return r.read()
def clean(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(s or "")))).strip()
def ptime(s):
    s = (s or "").strip()
    if not s: return None
    try: return email.utils.parsedate_to_datetime(s).timestamp()
    except Exception: pass
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None
def parse(raw):
    out = []
    for el in ET.fromstring(raw).iter():
        if el.tag.split("}")[-1] not in ("item", "entry"): continue
        d = {}
        for c in el:
            ct = c.tag.split("}")[-1]
            if ct == "title": d["title"] = clean(c.text)
            elif ct == "link":
                href = c.get("href") or (c.text or "").strip()
                if href and ("link" not in d or c.get("rel") in (None, "alternate")): d["link"] = href
            elif ct in ("description", "summary", "encoded") and not d.get("desc"): d["desc"] = clean(c.text)[:400]
            elif ct in ("pubDate", "published", "updated", "date") and not d.get("t"): d["t"] = ptime(c.text)
            elif ct == "source": d["src"] = clean(c.text)
            elif ct == "alertlevel": d["alert"] = (c.text or "").strip()
        if d.get("title"): out.append(d)
    return out
def toks(t):
    w = re.findall(r"[a-z0-9]+", t.lower().replace("\u2019s", "").replace("'s", ""))
    return {x[:-1] if len(x) > 4 and x.endswith("s") else x for x in w if x not in STOP and len(x) > 2}
def ents(t):
    return {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", t or "") if w.lower() not in STOP}
def tscore(it):
    ti, de = norm(it["title"]), norm(it["desc"]); sc = {}
    for t, pats in WR.items():
        n = 0.0
        for w, rx in pats:
            n += w * len({m.group(0).lower() for m in rx.finditer(ti)}) + 0.5 * w * len({m.group(0).lower() for m in rx.finditer(de)})
        if it["hint"] == t: n += 3
        if n: sc[t] = n
    return sc
GSUF = re.compile(r"\s+[-\u2013|]\s+[^-\u2013|]{2,40}$")

JUNK = re.compile(r"print edition|roundup: market talk|\bmarket talk\b|^(?:watch|video|listen|podcast|quiz)\s*[:|]|^(?:the )?(?:morning|evening|daily) (?:briefing|newsletter)\b|\bnewsletter\b|^what'?s news\b|^(?:today'?s )?(?:crossword|wordle|horoscope)", re.I)
def _build_main():
    C = cfg(); now = time.time(); items, status, sig, used = [], {}, [], []
    def one(s):
        try: return s, parse(fetch(s["url"])), None
        except Exception as e: return s, [], repr(e)[:120]
    with ThreadPoolExecutor(14) as ex: res = list(ex.map(one, C["sources"] + C.get("signals", [])))
    for s, its, err in res:
        if s.get("signal"):
            sig += [toks(GSUF.sub("", i["title"])) for i in its]; status[s["name"]] = err or len(its); continue
        its.sort(key=lambda i: -(i.get("t") or 0)); kept = 0
        for i in its:
            t = i.get("t") or now - 12 * 3600
            if now - t > s.get("max_age_h", MAX_AGE_H) * 3600 or t > now + 3600: continue
            title, desc = i["title"], i.get("desc", "")
            if JUNK.search(title): continue
            if s.get("gfilter"):
                if not re.search(s["gfilter"], i.get("src", "") + " " + title, re.I): continue
                title, desc = GSUF.sub("", title), ""
            sev = 0
            if s.get("kind") == "gdacs":
                lv = i.get("alert", "").lower()
                if lv not in ("orange", "red"): continue
                sev = 4 if lv == "red" else 2
            if s.get("kind") == "usgs":
                m = re.match(r"M\s*([\d.]+)", title)
                if not m or float(m.group(1)) < 6.0: continue
                sev = 1 + (float(m.group(1)) - 6) * 2; title = "Magnitude " + title[1:].strip()
            if desc and desc[:60].lower() == title[:60].lower(): desc = ""
            items.append({"pub": s["pub"], "title": title, "url": i.get("link", ""), "t": t, "desc": desc, "hint": s.get("hint"),
                          "prio": s.get("prio", 5), "sev": sev, "tk": toks(title), "en": ents(title + " " + desc[:200])})
            kept += 1
            if kept >= s.get("max", 40): break
        status[s["name"]] = err or kept
        if kept and s["pub"] not in used: used.append(s["pub"])
    items.sort(key=lambda x: (x["prio"], -x["t"]))
    df = {}
    for tk in [i["tk"] for i in items] + sig:
        for w in tk: df[w] = df.get(w, 0) + 1
    N = len(items) + len(sig)
    idf = lambda w: math.log((N + 1) / (df.get(w, 0) + 0.5))
    def wsim(a, b):
        inter = a & b
        if len(inter) < 2: return 0.0
        wi = sum(idf(w) for w in inter); wa = sum(idf(w) for w in a); wb = sum(idf(w) for w in b)
        return max(wi / (wa + wb - wi), 0.75 * wi / min(wa, wb))
    def same(x, y):
        s = wsim(x["tk"], y["tk"])
        if x["pub"] == y["pub"]: return s >= 0.34
        return s >= 0.26 or (s >= 0.12 and len(x["en"] & y["en"]) >= 2)
    clusters = []
    for it in items:
        for c in clusters:
            if any(same(it, m) for m in c[:8]): c.append(it); break
        else: clusters.append([it])
    out = []; dropped = 0
    for its in clusters:
        pubs = []
        for i in its:
            if i["pub"] not in pubs: pubs.append(i["pub"])
        agg = {}
        for i in its:
            for t, n in tscore(i).items(): agg[t] = agg.get(t, 0) + n
        avg = {t: n / len(its) for t, n in agg.items()}
        conflict = sum(1 for i in its if CONFLICT.search(norm(i["title"]))) * 2 >= len(its)
        need = {t: (3 if not conflict else (4.5 if t in ("Social unrest", "Disasters") else 6)) for t in TOPICS}
        tops = sorted([t for t, v in avg.items() if v >= need[t]], key=lambda t: -avg[t])
        if not tops: dropped += 1; continue
        nsig = sum(1 for g in sig if any(wsim(g, i["tk"]) >= 0.25 for i in its[:6]))
        newest = max(i["t"] for i in its)
        rec = max(0.0, 1 - (now - newest) / 86400)
        score = 4 * (len(pubs) - 1) + 0.5 * (len(its) - len(pubs)) + 2.5 * min(nsig, 4) + 2 * rec + max(i["sev"] for i in its) + min(avg[tops[0]], 9) / 3 - (2.5 if len(pubs) == 1 and all(i["prio"] >= 5 for i in its) and not max(i["sev"] for i in its) else 0)
        firsts = {}
        for i in its: firsts.setdefault(i["pub"], i)
        out.append({"title": its[0]["title"], "url": its[0]["url"], "topic": tops[0], "topics": tops,
                    "summary": next((i["desc"][:260] for i in its if i["desc"]), ""), "time": int(newest), "first": int(min(i["t"] for i in its)),
                    "n_sources": len(pubs), "n_articles": len(its), "trend_signal": nsig, "score": round(score, 2), "conflict": conflict,
                    "tscores": {t: round(v, 1) for t, v in avg.items()},
                    "sources": [{"name": p, "url": firsts[p]["url"], "title": firsts[p]["title"]} for p in pubs]})
    out.sort(key=lambda c: -c["score"])
    by = {t: [c for c in out if t in c["topics"]][:20] for t in TOPICS}
    caps = {s["pub"]: s["cap"] for s in C["sources"] if s.get("cap")}
    pick, seen, cnt, pc = [], set(), {t: 0 for t in TOPICS}, {}
    def lead(c): return c["sources"][0]["name"] if c["n_sources"] == 1 else None
    def fits(c):
        p = lead(c); return p is None or pc.get(p, 0) < caps.get(p, 4)
    def add(c):
        pick.append(c); seen.add(id(c)); cnt[c["topic"]] += 1
        p = lead(c)
        if p: pc[p] = pc.get(p, 0) + 1
    for t in TOPICS:
        k = 0
        for c in by[t]:
            if k >= (2 if t in CORE else 1): break
            if id(c) not in seen and cnt[c["topic"]] < 3 and fits(c): add(c); k += 1
    for cap in (3, 4, 99):
        for c in out:
            if len(pick) >= 20: break
            if id(c) not in seen and cnt[c["topic"]] < cap and fits(c): add(c)
    pick.sort(key=lambda c: -c["score"])
    return {"updated": int(now), "stories": pick, "by_topic": by, "topics": TOPICS, "sources_used": used, "status": status,
            "n_items": len(items), "n_clusters": len(clusters), "n_dropped": dropped, "n_multi": sum(1 for c in out if c["n_sources"] > 1), "n_sig": len(sig), "n_sig_hit": sum(1 for c in out if c["trend_signal"]),
            "excluded": C.get("excluded", [])}

_lock = threading.Lock(); _cache = {"data": None, "ts": 0}
def refresh():
    if not _lock.acquire(blocking=False): return
    try:
        d = build()
        if d["stories"]:
            _cache.update(data=d, ts=time.time()); json.dump(d, open(CACHE, "w"))
    finally: _lock.release()
def get(force=False):
    if _cache["data"] is None:
        try: d = json.load(open(CACHE)); _cache.update(data=d, ts=d.get("updated", 0))
        except Exception: pass
    age = time.time() - _cache["ts"]
    if _cache["data"] is None or (force and age > 120): refresh()
    elif age > TTL: threading.Thread(target=refresh, daemon=True).start()
    return _cache["data"] or {"stories": [], "by_topic": {}, "error": "no data yet"}


# ---------------- Sweden tab (Swedish, untranslated; separate top 20) ----------------
SV_STOP = set("""och i att det som en på är av för med till den har de inte om ett han men var jag sig från vi så kan man när år säger efter nu ska vill under mot alla hon då sin sina sitt nya ny nytt blir blev får fick kommer också eller vid ut upp in där här hur vad varför vem över mellan två tre enligt flera många mer än bara skulle kunde just gör gjorde direkt igen inför utan sedan dag dagen idag hade även detta denna dessa live""".split())
ENT_SV = re.compile(r"\b[A-ZÅÄÖ][a-zåäöéA-ZÅÄÖ]{2,}\b")
def toks_sv(t): return {w for w in re.findall(r"[^\W_]+", (t or "").lower()) if w not in SV_STOP and len(w) > 2}
def ents_sv(t): return {w.lower() for w in ENT_SV.findall(t or "") if w.lower() not in SV_STOP}
POL_SV = re.compile(r"\b(?:trump\w*|biden|vance|putin\w*|zelenskyj\w*|vita hus\w*|presschef\w*|kongress\w*|senat\w*|republikan\w*|demokrater\w*|regering\w*|riksdag\w*|statsminist\w*|minister\w*|kristersson|magdalena andersson|åkesson|partiledar\w*|parti(?:et|er|erna)?|socialdemokrat\w*|moderat\w*|sverigedemokrat\w*|liberalerna|centerpartiet|vänsterpartiet|miljöpartiet|kristdemokrat\w*|oppositionen|politik\w*|politiker\w*|talesperson\w*|extra ?val\w*|nyval|valet|valrörelse\w*|riksdagsval\w*|val(?:dag|resultat|kampanj|löfte)\w*|opinionsmätning\w*|väljar\w*|(?-i:S|M|SD|KD|V|MP|L|C)-(?:topp|ledare|politiker))\b", re.I)
def build_se(C=None):
    C = C or cfg(); now = time.time(); items, status, sig, used = [], {}, [], []
    srcs, sigs = C.get("sweden", []), C.get("sweden_signals", [])
    if not srcs: return {"stories": [], "used": [], "status": {}}
    def one(s):
        try: return s, parse(fetch(s["url"])), None
        except Exception as e: return s, [], repr(e)[:120]
    with ThreadPoolExecutor(10) as ex: res = list(ex.map(one, srcs + sigs))
    for s, its, err in res:
        if s.get("signal"):
            sig += [toks_sv(GSUF.sub("", i["title"])) for i in its]; status[s["name"]] = err or len(its); continue
        its.sort(key=lambda i: -(i.get("t") or 0)); kept = 0
        for i in its:
            t = i.get("t") or now - 12 * 3600
            if now - t > s.get("max_age_h", MAX_AGE_H) * 3600 or t > now + 3600: continue
            title, desc = i["title"], i.get("desc", "")
            if desc and desc[:60].lower() == title[:60].lower(): desc = ""
            items.append({"pub": s["pub"], "title": title, "url": i.get("link", ""), "t": t, "desc": desc, "prio": s.get("prio", 3),
                          "tk": toks_sv(title), "en": ents_sv(title + " " + desc[:200])})
            kept += 1
            if kept >= s.get("max", 40): break
        status[s["name"]] = err or kept
        if kept and s["pub"] not in used: used.append(s["pub"])
    items.sort(key=lambda x: (x["prio"], -x["t"]))
    df = {}
    for tk in [i["tk"] for i in items] + sig:
        for w in tk: df[w] = df.get(w, 0) + 1
    N = len(items) + len(sig)
    idf = lambda w: math.log((N + 1) / (df.get(w, 0) + 0.5))
    def wsim(a, b):
        inter = a & b
        if len(inter) < 2: return 0.0
        wi = sum(idf(w) for w in inter); wa = sum(idf(w) for w in a); wb = sum(idf(w) for w in b)
        try: return max(wi / (wa + wb - wi), 0.75 * wi / min(wa, wb))
        except ZeroDivisionError: return 0.0
    def same(x, y):
        s = wsim(x["tk"], y["tk"])
        if x["pub"] == y["pub"]: return s >= 0.34
        return s >= 0.26 or (s >= 0.12 and len(x["en"] & y["en"]) >= 2)
    clusters = []
    for it in items:
        for c in clusters:
            if any(same(it, m) for m in c[:8]): c.append(it); break
        else: clusters.append([it])
    out = []; polx = []
    for its in clusters:
        pubs = []
        for i in its:
            if i["pub"] not in pubs: pubs.append(i["pub"])
        if POL_SV.search(its[0]["title"]) or sum(1 for i in its if POL_SV.search(i["title"])) * 2 >= len(its):
            polx.append(its[0]["title"]); continue
        nsig = sum(1 for g in sig if any(wsim(g, i["tk"]) >= 0.25 for i in its[:6]))
        newest = max(i["t"] for i in its); rec = max(0.0, 1 - (now - newest) / 86400)
        score = 4 * (len(pubs) - 1) + 0.5 * (len(its) - len(pubs)) + 2.5 * min(nsig, 4) + 2 * rec - (1.5 if len(pubs) == 1 and not nsig else 0)
        firsts = {}
        for i in its: firsts.setdefault(i["pub"], i)
        out.append({"title": its[0]["title"], "url": its[0]["url"], "topic": "Sverige", "topics": ["Sverige"],
                    "summary": next((i["desc"][:260] for i in its if i["desc"]), ""), "time": int(newest), "first": int(min(i["t"] for i in its)),
                    "n_sources": len(pubs), "n_articles": len(its), "trend_signal": nsig, "score": round(score, 2),
                    "sources": [{"name": p, "url": firsts[p]["url"], "title": firsts[p]["title"]} for p in pubs]})
    out.sort(key=lambda c: -c["score"])
    pick, pc = [], {}
    for c in out:
        if len(pick) >= 20: break
        p = c["sources"][0]["name"] if c["n_sources"] == 1 else None
        if p and pc.get(p, 0) >= 5: continue
        if p: pc[p] = pc.get(p, 0) + 1
        pick.append(c)
    return {"stories": pick, "used": used, "status": status, "n_items": len(items), "n_clusters": len(clusters), "n_politics": len(polx), "politics_dropped": polx[:20]}

def build():
    box = {}
    def se():
        try: box["se"] = build_se()
        except Exception as e: box["se"] = {"stories": [], "used": [], "status": {"error": repr(e)[:150]}}
    th = threading.Thread(target=se, daemon=True); th.start()
    d = _build_main(); th.join(90)
    s = box.get("se") or {"stories": [], "used": [], "status": {"error": "timeout"}}
    d.update(sweden=s["stories"], sweden_sources=s["used"], sweden_status=s["status"], sweden_politics_dropped=s.get("politics_dropped", []), sweden_excluded=cfg().get("sweden_excluded", []))
    return d
