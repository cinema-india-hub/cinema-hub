"""Fetch Google Trends 'Trending Now' RSS, keep NEW film/OTT topics, write data/candidates.json."""
import json, re, time, pathlib
import xml.etree.ElementTree as ET
import requests, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
STATE = ROOT / "data" / "state.json"
OUT = ROOT / "data" / "candidates.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; CinemaHubBot/1.0)"}
KEEP_SECONDS = 14 * 24 * 3600


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_traffic(s):
    s = (s or "").strip().upper().replace("+", "").replace(",", "")
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def parse_trends(xml_bytes, geo):
    """Namespace-agnostic parse so small feed-format changes don't break us."""
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter("item"):
        d = {"geo": geo, "title": "", "traffic": 0, "pubDate": "", "news": []}
        for el in item:
            n = local(el.tag)
            if n == "title":
                d["title"] = (el.text or "").strip()
            elif n == "approx_traffic":
                d["traffic"] = parse_traffic(el.text)
            elif n == "pubDate":
                d["pubDate"] = (el.text or "").strip()
            elif n == "news_item":
                ni = {local(c.tag): (c.text or "").strip() for c in el}
                d["news"].append({
                    "title": ni.get("news_item_title", ""),
                    "url": ni.get("news_item_url", ""),
                    "source": ni.get("news_item_source", ""),
                })
        if d["title"]:
            out.append(d)
    return out


def fetch_trends(geo):
    r = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", headers=UA, timeout=30)
    r.raise_for_status()
    return parse_trends(r.content, geo)


def signal_headlines():
    heads = []
    for url in CFG.get("signal_feeds", []):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            heads += [(t.text or "").lower() for t in root.iter("title") if t.text]
        except Exception as e:
            print(f"[signal] skip {url}: {e}")
    return heads


def term_regex(terms):
    return re.compile(r"\b(" + "|".join(re.escape(t.lower()) for t in terms) + r")\b")


def main():
    state = json.loads(STATE.read_text())
    now = time.time()
    seen = {k: v for k, v in state.get("seen", {}).items() if now - v < KEEP_SECONDS}
    ent, block = term_regex(CFG["entertainment_terms"]), term_regex(CFG["block_terms"])
    signals = signal_headlines()
    cands = []
    for geo in CFG["geos"]:
        try:
            items = fetch_trends(geo)
        except Exception as e:
            print(f"[trends] {geo} failed: {e}")
            continue
        for it in items:
            key = f"{geo}|{it['title'].lower()}"
            if key in seen:
                continue
            seen[key] = now
            blob = " ".join([it["title"]] + [n["title"] for n in it["news"]]).lower()
            if block.search(blob) or not ent.search(blob):
                continue
            if it["traffic"] < CFG["min_traffic"]:
                continue
            corroborated = bool(it["news"]) or any(it["title"].lower() in h for h in signals)
            if not corroborated:
                continue
            if any(c["title"].lower() == it["title"].lower() for c in cands):
                continue  # same topic already picked from another region
            cands.append(it)
    cands.sort(key=lambda c: c["traffic"], reverse=True)
    cands = cands[: CFG["max_candidates"]]
    OUT.write_text(json.dumps(cands, indent=2, ensure_ascii=False), encoding="utf-8")
    state["seen"] = seen
    STATE.write_text(json.dumps(state, indent=2))
    print(f"[trends] {len(cands)} new candidate(s)")


if __name__ == "__main__":
    main()
