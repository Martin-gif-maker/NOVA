# whatsnew.py — the short "what's new" note shown once after NOVA was updated (and under Help → What's new).
# Keep each line to one sentence a user can act on; the full list of changes lives in CHANGELOG.md.
import paths
from i18n import tr

NOTES = {
    "6.6": [
        "“Quit Safari” now quits an app the way ⌘Q does, so it can ask you to save first.",
        "With Search by meaning installed, NOVA also picks the memories that fit your question, even when you said it in other words.",
        "“Forget …” finds the memory even when you word it differently, and file requests like “Desktop/notes.txt” mean your own Desktop.",
        "Small offline models (Ollama, LM Studio) work better: when one writes a command out instead of running it, NOVA runs it, with the usual checks.",
    ],
    "6.5": [
        "Speak Bulgarian, English or 97 more languages with nothing leaving your Mac: Settings → Voice → Any language, on this Mac (a one-time 574 MB download).",
        "While NOVA works, the line under your message says what it is doing, and replies no longer jump when they finish.",
        "If your AI service refuses the API key, NOVA tells you where to get a new one.",
    ],
    "6.4": [
        "NOVA keeps itself up to date: once a day it looks for a new version and, when you agree, installs it (Settings → Data).",
        "The setup wizard and every settings window are fully in Bulgarian, and check boxes now show a tick.",
        "The scheduled-task window is easier to use: the weekdays appear only when you choose days.",
    ],
    "6.3": [
        "Search your documents by meaning: ＋ → Documents → Search by meaning (a one-time 135 MB download). A question then also finds passages that say the same thing in other words or in another language.",
        "NOVA starts about a third faster, and quits at once.",
        "Short messages stay on one line, and long chats no longer leave an empty gap under the last message.",
    ],
    "6.2": [
        "NOVA has a new look: calmer colours, sharper details, and line icons instead of emoji.",
        "Under each reply you now see what NOVA did, as neat rows you can click for details.",
        "The red, yellow and green window buttons hide NOVA, shrink it to a bubble, or fill the screen.",
        "Pick a look in Settings → General: Paper or Sage (light), Graphite or Espresso (dark), or follow the system.",
    ],
    "6.1": [
        "Ask about your calendar, reminders and mail — NOVA can add events and draft replies (you press Send).",
        "Drop a PDF, Word or Excel file, or a whole folder, onto NOVA and ask about it. Scanned pages are read too.",
        "Select text in any app and press ⌃⇧Space to explain, translate or rewrite it.",
        "Say “every morning at 8 give me the news” and NOVA schedules it (＋ → Scheduled tasks).",
        "＋ → Voice conversation lets you talk hands-free; ＋ → Mode switches between Coder, Translator, Tutor and Writer.",
        "Type /tldr, /eli5 or /fix before a text to reuse a prompt — or save your own.",
        "Connect tool servers (MCP) and run your Apple Shortcuts from NOVA.",
        "Choose your AI in Settings → AI: Groq, Claude, OpenAI, or Ollama running on this Mac.",
        "Settings → Privacy: encrypt what NOVA stores, and see everything it sent.",
    ],
}


def release(version: str | None = None) -> str:
    """'6.1.3' -> '6.1'"""
    return ".".join(str(version or paths.__version__).split(".")[:2])


def notes(version: str | None = None) -> list:
    return NOTES.get(release(version), [])


def _key(rel: str) -> tuple:
    return tuple(int(p) for p in rel.split(".") if p.isdigit())


def text(version: str | None = None, since: str = "") -> str:
    """The note as markdown in the interface language ('' if there is nothing to say). With `since` (the version
    used before), every release after it is included, newest first - someone coming from 6.2 hears about 6.3 and
    6.4 too, not only about this one."""
    current = release(version)
    if since:
        older = _key(release(since))
        rels = sorted((r for r in NOTES if older < _key(r) <= _key(current)), key=_key, reverse=True)
    else:
        rels = [current] if notes(version) else []
    shown = {r: [t for t in map(tr, NOTES[r]) if t] for r in rels}        # a line that is not for this system is ""
    parts = ["**" + tr("What's new in NOVA {}").format(r) + "**\n\n" + "\n".join("• " + t for t in shown[r])
             for r in rels if shown[r]]
    return "\n\n".join(parts)


def should_show(seen: str, onboarded: bool, version: str | None = None) -> bool:
    """Once per release, to people who already used NOVA (a fresh install gets the first-run wizard instead)."""
    seen_release = ".".join(str(seen or "").split(".")[:2])              # "" = an older NOVA that did not record it
    return bool(onboarded) and seen_release != release(version) and bool(notes(version))
