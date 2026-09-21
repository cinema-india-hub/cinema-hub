import datetime as dt, json, os, pathlib, re, sys
import requests, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
DRAFTS, POSTS = ROOT / "drafts", ROOT / "docs" / "_posts"
STATE = ROOT / "data" / "state.json"
TOKEN, CHAT = os.environ.get("TELEGRAM_BOT_TOKEN", ""), str(os.environ.get("TELEGRAM_CHAT_ID", ""))
API = f"https://api.telegram.org/bot{TOKEN}"

DISCLOSURE = ("*Disclosure: some links on this page are affiliate links. We may earn a commission "
              "at no extra cost to you. Release dates and figures can change; check official sources.*")


def send(text):
    requests.post(f"{API}/sendMessage", json={"chat_id": CHAT, "text": text[:4000]}, timeout=30).raise_for_status()


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def notify():
    for p in sorted(DRAFTS.glob("*.json")):
        d = load(p)
        if d["status"] != "pending" or d.get("notified"):
            continue
        send(f"[{d['id']}] {d['title']}\n\n{d['body_md']}\n\nSHORT SCRIPT:\n{d['short_script']}\n\n"
             f"Reply: ok {d['id']}  or  no {d['id']}\n(Edit the draft in the repo if you want to add your own line.)")
        d["notified"] = True
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def publish(d):
    aff = CFG["affiliate"]
    if d["type"] == "release":
        block = f"[{aff['tickets_label']}]({aff['tickets_url']})"
    else:
        block = f"[{aff['gear_label']}]({aff['gear_url']})"
    src = "\n".join(f"- {s['source']}: [{s['title']}]({s['url']})" for s in d.get("sources", []) if s.get("url"))
    today = dt.date.today().isoformat()
    title = d["title"].replace('"', "'")
    tags = d.get("tags", []) or []
    tag_yaml = json.dumps(tags, ensure_ascii=False)
    md = (f'---\nlayout: post\ntitle: "{title}"\ndate: {today}\ntags: {tag_yaml}\ntype: {d.get("type", "trend")}\nsource_count: {len(d.get("sources", []))}\n---\n\n'
          f"{d['body_md']}\n\n{block}\n\n" + (f"**Sources**\n{src}\n\n" if src else "") + f"{DISCLOSURE}\n")
    POSTS.mkdir(parents=True, exist_ok=True)
    (POSTS / f"{today}-{slugify(d['title'])}.md").write_text(md, encoding="utf-8")


def poll():
    state = json.loads(STATE.read_text())
    r = requests.get(f"{API}/getUpdates", params={"offset": state.get("tg_offset", 0) + 1, "timeout": 0}, timeout=30)
    r.raise_for_status()
    for u in r.json().get("result", []):
        state["tg_offset"] = max(state.get("tg_offset", 0), u["update_id"])
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != CHAT:   # ignore everyone except you
            continue
        m = re.match(r"^(ok|no)\s+([0-9a-f]{6})\b", (msg.get("text") or "").strip().lower())
        if not m:
            continue
        p = DRAFTS / f"{m.group(2)}.json"
        if not p.exists():
            continue
        d = load(p)
        if d["status"] != "pending":
            continue
        if m.group(1) == "ok":
            d["status"] = "published"
            publish(d)
        else:
            d["status"] = "rejected"
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    {"notify": notify, "poll": poll}[sys.argv[1]]()
