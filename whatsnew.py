# whatsnew.py — the short "what's new" note shown once after NOVA was updated (and under Help → What's new).
# Keep each line to one sentence a user can act on; the full list of changes lives in CHANGELOG.md.
import paths
from i18n import tr

NOTES = {
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


def release(version: str = None) -> str:
    """'6.1.3' -> '6.1'"""
    return ".".join(str(version or paths.__version__).split(".")[:2])


def notes(version: str = None) -> list:
    return NOTES.get(release(version), [])


def text(version: str = None) -> str:
    """The note as markdown in the interface language ('' if there is nothing to say about this version)."""
    lines = notes(version)
    if not lines: return ""
    return "**" + tr("✨  What's new in NOVA {}").format(release(version)) + "**\n\n" + "\n".join("• " + tr(l) for l in lines)


def should_show(seen: str, onboarded: bool, version: str = None) -> bool:
    """Once per release, to people who already used NOVA (a fresh install gets the first-run wizard instead)."""
    seen_release = ".".join(str(seen or "").split(".")[:2])              # "" = an older NOVA that did not record it
    return bool(onboarded) and seen_release != release(version) and bool(notes(version))
