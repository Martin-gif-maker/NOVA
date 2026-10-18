# NOVA — what changed

## Unreleased

- Quitting NOVA within its first half minute no longer starts the delayed start-up jobs (update check, document
  refresh) on the way out.
- Tests: none may reach the internet any more (a guard fails the test that tries, and says which code did it). One
  test let a real weather request through, which made the suite fail and then crash when the network was slow.
- The games: no emoji in their buttons, messages and menu (the Stats button has a line icon, the games menu looks
  like NOVA's other menus), the stats line wraps instead of being cut off in the Number Guesser, and the date is
  written the Bulgarian way in Bulgarian.
- The plugins window is translated and uses the same thin scroll bars as the other windows.
- **Safety:** after NOVA has read a page, file or email, hidden instructions in it could have had NOVA read your
  files and then "read" a web address with that data in it, which never asked. Now a web address that did not come
  from you, a search result or a link on a page NOVA read asks first; following real links still does not.
- **Safety:** copying a file onto one that already exists replaced it without asking (moving and renaming always
  asked). Now it asks, with what would be replaced.
- The window always opens fully on screen: shrinking NOVA to a bubble, parking it in a corner and opening it again
  used to put most of the window off the edge of the screen (a 61-pixel corner was all that showed).
- The counter in the title bar says "6 messages · 1.2k tokens" (and in Bulgarian), not "6 msgs · 1.2k tok"; the
  bubble's tooltip is translated.

## 6.5.0 — October 2026

- **Speak Bulgarian (or any of 99 languages) to NOVA without anything leaving your Mac.** Settings → Voice → *Any
  language, on this Mac* downloads OpenAI's Whisper large-v3-turbo (574 MB, once, checksum-verified); whisper.cpp
  runs it on the Mac in about a second per sentence. It is the same model the cloud uses, so NOVA prefers it once it
  is there. Silence never becomes words: Whisper's habit of "hearing" "Thank you." or "Абонирайте се!" in a quiet
  room is filtered out. Tested with the Mac's own Bulgarian and English voices: every sentence right.
- Messages and help that still pointed at old buttons (the "⋯" menu, "press ✕", "⊘ Quick cmds") now name what is
  on screen today; the keyboard-shortcuts list is translated and has no emoji.
- While NOVA works, the line under your message says what it is doing ("Opening Maps…", "Checking the weather…")
  from the first moment. It used to start empty and its "Thinking…" dots wrote over the action every 0.4 s.
- What NOVA did (the rows above a reply) is shown as soon as the reply starts, so the text no longer jumps down
  when the reply ends.
- When the AI service refuses your API key, NOVA says which service it was, links to the page for a new key and
  says where to paste it (it used to say only "API key error").

## 6.4.0 — October 2026

- **A cleaner first start.** In the setup wizard the AI-provider menu was almost invisible and the "I understand
  and agree" box had no visible check box; both are fixed. Pages that are too long now scroll instead of
  cutting off their last lines, and the permission page no longer pushes its "Allow…" buttons out of sight.
- **Check boxes show a tick**, and pop-up menus and number fields show a small chevron, in every window and
  every theme.
- **Bulgarian everywhere:** Qt's own buttons and menus (Save, Cancel, Yes, No, Copy, Paste …), the setup
  wizard's provider help, permissions and last page, and the language menu. Table headings in "Usage and cost"
  and "What NOVA sent" are no longer cut off.
- The scheduled-task window: the text field uses the full width, the time field looks like the other fields,
  and the weekdays appear only for "Chosen days".
- Settings → Data says where updates come from (GitHub, your own address, or `git pull` when run from source).

- **Updates come from GitHub by themselves.** The app checks NOVA's GitHub releases once a day and offers the new
  version (Settings → Data: tell me / install by itself / do not check). The download is checked against the SHA-256
  GitHub publishes, a stalled download resumes where it stopped, and a failed one no longer leaves a half-downloaded
  file in Downloads. If macOS's disk-image helper is briefly busy, the update waits for it instead of failing.
- Tests for dropping folders and long files onto NOVA, and for keeping API keys in a private file when the Keychain
  is locked; `coverage run` now reports (it was cut off by the test suite's own fast exit).

## 6.3.0 — October 2026

- **NOVA starts about a third faster** (0.83 s → 0.56 s from launch to a ready window, measured on this Mac), and
  quits at once. The AI provider's library (0.1–0.35 s) now loads in the background right after the window
  appears, and the typing/screenshot library (0.14 s) loads the first time NOVA types or takes a screenshot. A test
  keeps all of them out of start-up.
- **Search your documents by meaning.** ＋ → Documents → *Search by meaning* downloads a small multilingual model once
  (135 MB). After that a question also finds passages that say the same thing in other words ("how much do I put
  down up front?" → "security deposit") or in another language (a Bulgarian question → an English contract). It runs
  on the Mac and is blended with the word search. On the test library it finds 11 of 12 reworded questions, where
  words alone found 2.
- Word search ignores question words ("how", "when", "does", "кога", "колко" …). "When does the plane leave?" no
  longer finds a passage just because it also says "when".
- The document list shows paths in your home folder as `~/…`.
- The chat no longer leaves an empty gap under the last message. The gap grew by 20–40 px with every message
  on screen.
- Short messages stay on one line in their bubble instead of wrapping early.
- What NOVA says by itself when it stops after too many steps, or when the AI declines, is now in plain words,
  in Bulgarian too, and without a warning emoji.
- An evaluation set of 86 requests in English and Bulgarian (`evals/`), with a harness that measures whether
  NOVA sends the right tools and whether the model then picks and fills them in correctly. It found two
  keyword gaps: "find my resume pdf" and "пусни прекия път …" now get their tools without an extra round.
- The README now shows NOVA (light and dark), what it does, how it works and why it is built that way.
  NOVA is MIT-licensed.
- Under the hood: lint with ruff and a type check of the core modules (mypy) run with every `./check.sh`; the type
  check found a voice-monitor attribute that hid Qt's own `started` signal.

## 6.2.0 — October 2026

**A new look.** NOVA now looks like a quiet, carefully made Mac app:
- The three window buttons (red hides to the menu bar, yellow shrinks to a bubble, green is full screen), the
  name in the middle, and one menu for everything else.
- Your messages are soft bubbles; NOVA's replies are plain text, with **what NOVA did** shown as neat rows
  ("Opened Maps · Paris ✓") that you can click for details.
- One card to write in, with the tools under the text: ＋, microphone, answer length, mode and model, send.
- Line icons instead of emoji, and no emoji in front of notices.
- Four palettes: Paper and Sage (light), Graphite and Espresso (dark), or follow the system. Your own accent
  colour still works.
- In full screen the conversation stays in a readable column in the middle.

## 6.1.1 — October 2026

- Old Excel files (`.xls`) can be read and added to the document library.
- The app is smaller: a 35 MB library that was only used to save sound files is gone, and so are unused Qt parts.
- Problems that used to be ignored silently now leave a line in the log (Help → Open logs).
- A complete guide to what NOVA can do: `WHAT_NOVA_CAN_DO.md`.
- Under the hood: the two largest source files were split by theme, the leftover Windows code was removed,
  more of the code is covered by tests (90 %), and the build's self-test no longer looks at your data folder.

## 6.1.0 — October 2026

**Your Mac's apps**
- Calendar and Reminders: read events and open reminders, add new ones (repeating events included).
- Mail: read the selected message, open filled-in drafts and replies. NOVA never sends mail itself.
- Browser: "summarize this page" (Safari, Chrome, Arc, Brave, Edge).
- Apple Shortcuts: NOVA runs your shortcuts; a shortcut can hand NOVA a request and get the answer back
  (`NOVA --ask "…" --wait`, or `nova://ask?text=…`).

**Documents**
- Ask about PDFs, Word, PowerPoint, Excel and Numbers files or whole folders. Text is indexed on the Mac; only the
  passages that match a question are sent to the AI.
- Scanned PDFs are read with on-device text recognition.
- A changed file is read again by itself; new files in a folder you added are picked up.

**Everyday**
- Act on selected text in any app with ⌃⇧Space (Explain, Summarize, Translate, Rewrite, Fix grammar, your own
  actions); optionally paste the result straight over the selection.
- Scheduled tasks: repeating reminders and requests at a time of day. With "Launch at login", NOVA starts in the
  menu bar so they run without opening the window.
- Hands-free voice conversation, with talking over NOVA to interrupt it — also without headphones: NOVA knows
  what it is playing and does not mistake its own voice in the loudspeakers for yours.
- Analyze a part of the screen.
- Modes (Coder, Translator, Tutor, Writer, your own) and saved prompts (`/tldr`, `/eli5`, `/fix`, your own).

**AI**
- Providers: Groq, Anthropic (Claude), OpenAI, Ollama (on this Mac), or any OpenAI-compatible server.
- MCP tool servers (stdio and HTTP); their tokens are kept in the Keychain.
- Memories are found by meaning, have categories and can expire.
- Usage and cost view. Tool definitions are sent only when a request needs them.

**Privacy and safety**
- Optional encryption of everything NOVA stores; "What NOVA sent today"; in-app activity log.
- Approval prompts show exactly what will change (a diff) before a file is overwritten, deleted or moved.
- "Always allow" is limited to one folder, one app, one shortcut or one server tool.
- Plugins with a manifest run in the macOS sandbox. Opt-in crash reports.

**Interface**
- Settings in tabs; full Bulgarian translation, including the games; every control has a spoken name.
- On-device speech recognition and wake word (English), system voice for read-aloud.

**Fixed**
- Long replies were cut off; quitting with the window open crashed; quitting could take two seconds.

**Under the hood**
- Updates can install in place. The project is a git repository with `./check.sh` and a pinned `requirements.lock`.

## 6.0.0
- First macOS version: PySide6 interface, tools with approval prompts, voice, themes, sessions, export / wipe.
