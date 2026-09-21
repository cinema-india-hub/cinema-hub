"""Turn candidates (or the release calendar) into pending drafts using a free-tier LLM API.
Usage: python src/draft.py trends | python src/draft.py calendar
"""
import csv, datetime as dt, hashlib, json, os, pathlib, re, sys
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "drafts"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # check current free-tier model names
KEY = os.environ.get("GEMINI_API_KEY", "")

RULES = """You write for an English-language film & OTT site aimed at Indian readers.
HARD RULES:
- Use ONLY the facts given in FACTS. Never invent dates, numbers, quotes, casting, plot or box-office figures.
- If a detail is not in FACTS, say it is "not yet confirmed" or leave it out.
- No rumours, no personal-life, relationship, family or health claims about any real person.
- No song lyrics, no long quotes (max 10 words, and only if in FACTS), no copied sentences.
- Neutral, useful tone. Add a short 'What it means for Indian viewers' section (release, streaming or ticket angle) using only FACTS, otherwise say what to watch for.
- 150-250 words for the article body, Markdown, with one H2 subheading at most.
Return ONLY valid JSON: {"title": str, "body_md": str, "short_script": str, "tags": [str]}
short_script = a 35-second voice-over for a vertical video, plain sentences, no emojis."""


def call_llm(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    r = requests.post(url, params={"key": KEY}, timeout=90, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    })
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def save_draft(kind, facts, sources, data):
    did = hashlib.sha1((kind + json.dumps(facts, sort_keys=True)).encode()).hexdigest()[:6]
    path = DRAFTS / f"{did}.json"
    if path.exists():
        return None
    draft = {"id": did, "type": kind, "status": "pending", "notified": False,
             "created": dt.datetime.now(dt.timezone.utc).isoformat(), "sources": sources, **data}
    path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    return did


def from_trends():
    cands = json.loads((ROOT / "data" / "candidates.json").read_text())
    for c in cands:
        facts = {"trend": c["title"], "region": c["geo"], "approx_searches": c["traffic"],
                 "headlines": [f"{n['source']}: {n['title']}" for n in c["news"][:4]]}
        prompt = f"{RULES}\n\nFACTS:\n{json.dumps(facts, ensure_ascii=False)}"
        try:
            data = call_llm(prompt)
        except Exception as e:
            print(f"[draft] LLM failed for {c['title']}: {e}")
            continue
        sources = [{"title": n["title"], "url": n["url"], "source": n["source"]} for n in c["news"][:4]]
        print("[draft] saved", save_draft("trend", facts, sources, data))


def from_calendar():
    today = dt.date.today()
    rows = []
    with open(ROOT / "data" / "calendar.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                d = dt.date.fromisoformat(r["release_date"])
            except ValueError:
                continue
            if 0 <= (d - today).days <= 7 and not r["title"].startswith("Example"):
                rows.append(r)
    if not rows:
        print("[calendar] nothing releasing this week")
        return
    prompt = (f"{RULES}\n\nTask: write a 'Releasing this week' roundup. One short paragraph per film.\n\n"
              f"FACTS:\n{json.dumps(rows, ensure_ascii=False)}")
    data = call_llm(prompt)
    print("[draft] saved", save_draft("release", rows, [], data))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "trends"
    DRAFTS.mkdir(exist_ok=True)
    from_calendar() if mode == "calendar" else from_trends()
