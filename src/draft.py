import csv, datetime as dt, hashlib, json, os, pathlib, re, sys
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "drafts"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite") 
KEY = os.environ.get("GEMINI_API_KEY", "")

RULES = """You write for an English-language film, TV and OTT site aimed at Indian readers.
SCOPE: only movies, TV series and streaming/OTT. If the topic is sports, music, politics, business or anything else, return {"skip": true, "reason": "off-topic"}.
HARD RULES:
- Use ONLY the facts given in FACTS. Never invent dates, numbers, quotes, casting, plot or box-office figures.
- BE SPECIFIC OR SKIP. The article must contain at least three concrete facts from FACTS (a title, a date, a platform, a confirmed role, a figure with its source). If FACTS do not support that, return {"skip": true, "reason": "too thin"}. Do not pad.
- Never use filler such as: "fans are following", "stay tuned", "coverage details", "across major platforms", "experts say", "it remains to be seen", "not yet confirmed" repeated more than once.
- No rumours, no personal-life, relationship, family or health claims about any real person.
- No song lyrics, no long quotes (max 10 words, and only if in FACTS), no copied sentences.
- Plain, direct style like a good newsroom brief: lead with the news in the first sentence, short sentences, no hype, no rhetorical questions.
- Include one short 'For Indian viewers' line ONLY if FACTS give a real India angle (release date, platform, ticket window). Otherwise omit it entirely.
- 120-200 words for the article body, Markdown, no headings.
Return ONLY valid JSON: {"title": str, "body_md": str, "short_script": str, "tags": [str]} or {"skip": true, "reason": str}
title = a plain factual headline under 80 characters. short_script = a 30-second voice-over, plain sentences, no emojis, no calls to action."""


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
        if data.get("skip") or not data.get("body_md"):
            print(f"[draft] skipped '{c['title']}': {data.get('reason', 'no content')}")
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
    if data.get("skip") or not data.get("body_md"):
        print(f"[draft] skipped calendar roundup: {data.get('reason', 'no content')}")
        return
    print("[draft] saved", save_draft("release", rows, [], data))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "trends"
    DRAFTS.mkdir(exist_ok=True)
    from_calendar() if mode == "calendar" else from_trends()
