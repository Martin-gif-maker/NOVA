# modes.py — "modes": ready-made ways for NOVA to behave (Coder, Translator, Tutor, Writer) plus your own,
# and saved prompts you can reuse by typing /name.
import re

DEFAULT = "default"
BUILTIN = {
    "default":    {"label": "Assistant", "prompt": ""},
    "coder":      {"label": "Coder", "prompt":
                   "MODE: CODER. The user is programming. Lead with working, complete code, then a short explanation. "
                   "Name the edge cases and how to test it. No filler, no restating the question."},
    "translator": {"label": "Translator", "prompt":
                   "MODE: TRANSLATOR. Treat each message as text to translate unless it is clearly a question to you. "
                   "Translate Bulgarian to English and any other language to Bulgarian, unless the user names the languages. "
                   "Reply with the translation only; add one short note only when a phrase is ambiguous."},
    "tutor":      {"label": "Tutor", "prompt":
                   "MODE: TUTOR. Teach rather than just answer: explain step by step in simple words with one small example, "
                   "and end with one short question that checks understanding. For exercises give a hint before the full solution."},
    "writer":     {"label": "Writer", "prompt":
                   "MODE: WRITER. Help with writing: clarity, tone, structure. When asked to write or rewrite, give the finished "
                   "text first, then at most three brief notes on what you changed and why."},
}
DEFAULT_PROMPTS = {
    "tldr": "Summarize the following in three short bullet points:",
    "eli5": "Explain this in very simple words, as if to a child:",
    "fix":  "Find and fix the problems in this code. Show the corrected code, then explain each fix in one line:",
}
_NAME = re.compile(r"[^\w\-]+", re.UNICODE)


def clean_name(name: str) -> str:
    """A name usable after '/' : lower-case, no spaces."""
    return _NAME.sub("-", str(name or "").strip().lower()).strip("-")[:30]


def all_modes(custom: dict = None) -> dict:
    """key -> {'label', 'prompt', 'custom'} : the built-in modes followed by the user's own."""
    out = {k: dict(v, custom=False) for k, v in BUILTIN.items()}
    for name, prompt in (custom or {}).items():
        key = clean_name(name)
        if key and key not in BUILTIN and str(prompt).strip():
            out[key] = {"label": str(name).strip()[:30], "prompt": "MODE: " + str(name).strip().upper() + ". " + str(prompt).strip(), "custom": True}
    return out


def mode_prompt(key: str, custom: dict = None) -> str:
    return all_modes(custom).get(key or DEFAULT, BUILTIN[DEFAULT])["prompt"]


def mode_label(key: str, custom: dict = None) -> str:
    return all_modes(custom).get(key or DEFAULT, BUILTIN[DEFAULT])["label"]


def expand_slash(text: str, prompts: dict):
    """What a message that starts with '/' means:
         ('expanded', text)  '/tldr the article…'  -> the saved prompt followed by the rest
         ('list', names)     '/' or '/unknown'     -> show which saved prompts exist
         ('plain', text)     anything else, including paths such as /Users/me/file.txt"""
    m = re.match(r"/([\w\-]*)(?:\s+(.*))?$", text.strip(), re.DOTALL | re.UNICODE)
    if not m: return "plain", text
    key, rest = clean_name(m.group(1)), (m.group(2) or "").strip()
    table = {clean_name(k): v for k, v in (prompts or {}).items()}
    if key in table:
        return "expanded", str(table[key]).strip() + ("\n\n" + rest if rest else "")
    if not rest:
        return "list", sorted(table)
    return "plain", text
