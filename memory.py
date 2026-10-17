# memory.py — what NOVA remembers about you.
#
# Each memory has a category, the day it was saved, an optional expiry date and search keywords:
#     {"text": "is allergic to peanuts", "category": "preference", "created": "2026-10-07", "expires": "",
#      "tags": "food allergy nuts eating restaurant diet health храна алергия ядки"}
# Only the memories that matter for the current question go into the prompt (`relevant`), so the list can
# grow without every request carrying all of it. Expired memories disappear on their own.
#
# Matching by meaning: when a memory is saved, the AI is asked once (in the background) for words a later
# question might use when that memory matters - "restaurant" for a peanut allergy. They are stored as `tags`
# and matched like the text itself, so finding the right memories later costs no extra request.
import re, datetime, difflib
import storage

VERSION      = 2
MAX_ITEMS    = 200
PROMPT_LIMIT = 12
CATEGORIES   = ("about_me", "preference", "work", "people", "task", "other")
LABELS       = {"about_me": "About me", "preference": "Preference", "work": "Work", "people": "People",
                "task": "Task", "other": "Other"}

_DATE_PREFIX = re.compile(r"^\[(\d{2})\.(\d{2})\.(\d{4})\]\s*")
_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = set("""a an and are as at be but by can did do does for from had has have how i if in into is it its
me my of on or our so than that the their them then there these they this to too us was we were what when where which
who why will with would you your about just very also not no yes please tell know want need like
и в на с за от по да не се е са как че аз ти той тя ние вие те това този тази тези ми ме си ли а но или какво кой коя
къде кога защо моя моят мой""".split())

_GUESS = (
    ("task",       ("todo", "to-do", "deadline", "need to", "needs to", "has to", "have to", "must ", "appointment", "due ",
                    "by tomorrow", "by monday", "by friday", "remember to", "exam on", "meeting on", "трябва", "срок")),
    ("people",     ("wife", "husband", "girlfriend", "boyfriend", "mother", "father", "mom", "dad", "brother", "sister",
                    "friend", "son ", "daughter", "partner", "colleague", "boss", "dog", "cat ", "pet ", "съпруг", "жена ми",
                    "майка", "баща", "брат", "сестра", "приятел")),
    ("work",       ("work", "job", "project", "company", "client", "office", "career", "developer", "engineer", "student",
                    "studies", "university", "school", "business", "работ", "проект", "фирма", "учи")),
    ("preference", ("like", "love", "prefer", "favorite", "favourite", "hate", "dislike", "enjoy", "allergic", "always wants",
                    "never wants", "харес", "обич", "предпочит", "любим", "мраз")),
    ("about_me",   ("name is", "is called", "i am", "lives in", "live in", "born", "birthday", "years old", "from ", "age ",
                    "speaks", "казва се", "живее", "роден", "години")),
)


def today() -> str:
    return datetime.date.today().isoformat()


def guess_category(text: str) -> str:
    low = " " + (text or "").lower() + " "
    for cat, words in _GUESS:
        if any(w in low for w in words): return cat
    return "other"


def _clean_category(cat: str, text: str) -> str:
    cat = (cat or "").strip().lower().replace(" ", "_").replace("-", "_")
    cat = {"me": "about_me", "personal": "about_me", "preferences": "preference", "tasks": "task", "person": "people"}.get(cat, cat)
    return cat if cat in CATEGORIES else guess_category(text)


def make(text: str, category: str = "", expires_days: float = 0, created: str | None = None, tags: str = "") -> dict:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    expires = ""
    try:
        if expires_days and float(expires_days) > 0:
            expires = (datetime.date.today() + datetime.timedelta(days=max(1, round(float(expires_days))))).isoformat()
    except (TypeError, ValueError):
        pass
    return {"text": text, "category": _clean_category(category, text),
            "created": today() if created is None else created, "expires": expires,
            "tags": re.sub(r"\s+", " ", str(tags or "")).strip()[:400]}


def from_display(s: str) -> dict:
    """'[07.10.2026] likes tea' (the old storage format) -> a memory."""
    s = str(s or "").strip(); created = ""
    m = _DATE_PREFIX.match(s)
    if m:
        try: created = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError: created = ""
        s = s[m.end():]
    return make(s, created=created)


def to_display(item: dict) -> str:
    try:
        d = datetime.date.fromisoformat(item.get("created") or "")
        return f"[{d.strftime('%d.%m.%Y')}] {item['text']}"
    except ValueError:
        return item["text"]


def coerce(x) -> dict:
    """Accept a memory dict or an old-style string."""
    if isinstance(x, dict):
        it = make(x.get("text", ""), x.get("category", ""), created=str(x.get("created") or ""), tags=x.get("tags", ""))
        it["expires"] = str(x.get("expires") or "")
        return it
    return from_display(x)


def is_expired(item: dict, on: str | None = None) -> bool:
    exp = item.get("expires") or ""
    return bool(exp) and exp < (on or today())


# ── file ───────────────────────────────────────────────────────────
def load(path: str) -> list:
    """All live memories, oldest first. Understands the old {"facts": [...]} files."""
    try:
        data = storage.read_json(path)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict): return []
    raw = data.get("items") if "items" in data else data.get("facts", [])
    items = [coerce(x) for x in (raw or [])]
    return [it for it in items if it["text"] and not is_expired(it)]


def save(path: str, items: list) -> None:
    items = [coerce(x) for x in items]
    items = [it for it in items if it["text"] and not is_expired(it)][-MAX_ITEMS:]
    storage.write_json(path, {"version": VERSION, "items": items})


# ── editing ────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


def add(items: list, text: str, category: str = "", expires_days: float = 0) -> list:
    """Append a memory, replacing one that says (almost) the same thing - never merely similar words."""
    new = make(text, category, expires_days)
    kept = [x for x in items if difflib.SequenceMatcher(None, _norm(x["text"]), _norm(new["text"])).ratio() < 0.85]
    return (kept + [new])[-MAX_ITEMS:]


def remove(items: list, keyword: str) -> list:
    k = keyword.lower()
    return [x for x in items if k not in x["text"].lower()]


# ── choosing what goes into the prompt ─────────────────────────────
def _tokens(text: str) -> set:
    return {w for w in (t.lower() for t in _WORD.findall(text or "")) if len(w) >= 3 and w not in _STOP}


def _overlap(a: set, b: set) -> int:
    """Shared words; long words also match on a 5-letter stem (coffee/coffees, работа/работя)."""
    hits = len(a & b)
    stems_b = {w[:5] for w in b - a if len(w) >= 5}
    return hits + sum(1 for w in a - b if len(w) >= 5 and w[:5] in stems_b)


def relevant(items: list, query: str = "", limit: int = PROMPT_LIMIT) -> list:
    """The memories worth sending with this request, in the order they were saved.
    Everything fits -> everything. Otherwise: memories that share words with the question first, then who the
    user is and what they prefer, then the most recent."""
    if len(items) <= limit: return list(items)
    q = _tokens(query); n = len(items); scored = []
    for i, it in enumerate(items):
        score = (3.0 * _overlap(q, _tokens(it["text"])) + 2.0 * _overlap(q, _tokens(it.get("tags", "")))) if q else 0.0
        score += {"about_me": 1.5, "preference": 1.0, "task": 0.8}.get(it.get("category"), 0.0)
        score += i / n                                             # newer = slightly better (and breaks ties)
        scored.append((score, i))
    keep = sorted(i for _s, i in sorted(scored, reverse=True)[:limit])
    return [items[i] for i in keep]


def line(item: dict) -> str:
    extra = f" (until {item['expires']})" if item.get("expires") else ""
    return f"• [{LABELS.get(item.get('category') or '', 'Other')}] {item['text']}{extra}"


def prompt_text(items: list, query: str = "", limit: int = PROMPT_LIMIT) -> str:
    chosen = relevant(items, query, limit)
    if not chosen: return ""
    more = len(items) - len(chosen)
    tail = f"\n(+{more} more memories not shown - call read_memory to see them all.)" if more > 0 else ""
    return "\n".join(line(it) for it in chosen) + tail


# ── keywords from the AI (matching by meaning) ─────────────────────
def tagging_prompt(texts: list) -> str:
    facts = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    return ("Below are facts an assistant remembers about its user. For EACH fact give 8 to 12 single words that a "
            "future question could contain when this fact is relevant: the topic, synonyms, and everyday situations "
            "where it matters (for \"is allergic to peanuts\": food allergy nuts eating restaurant menu snack diet health). "
            "Give the words in English AND in Bulgarian. Do not repeat words that are already in the fact.\n"
            "Answer with JSON only, in the form {\"1\": \"word word word\", \"2\": \"...\"}.\n\n" + facts)


def parse_tags(reply: str, texts: list) -> dict:
    """The AI's answer -> {fact text: 'keywords'}. Tolerant of extra prose and code fences."""
    import json
    reply = reply or ""
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    data = None
    if m:
        try: data = json.loads(m.group(0))
        except ValueError: data = None
    if not isinstance(data, dict):                             # fall back to lines like "1: word word"
        data = {mm.group(1): mm.group(2) for mm in re.finditer(r"^\s*(\d+)\s*[.:)\-]\s*(.+)$", reply, re.MULTILINE)}
    out = {}
    for key, value in data.items():
        try: i = int(str(key).strip()) - 1
        except ValueError: continue
        if isinstance(value, (list, tuple)): value = " ".join(str(v) for v in value)
        words = [w for w in _WORD.findall(str(value).lower()) if len(w) >= 3]
        if 0 <= i < len(texts) and words:
            out[texts[i]] = " ".join(dict.fromkeys(words))[:400]
    return out


def untagged(items: list, limit: int = 30) -> list:
    return [it["text"] for it in items if not it.get("tags")][:limit]
