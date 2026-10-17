# NOVA — what changed

## Unreleased

- The chat no longer leaves an empty gap under the last message. The gap grew by 20–40 px with every message
  on screen.
- Short messages stay on one line in their bubble instead of wrapping early.
- What NOVA says by itself when it stops after too many steps, or when the AI declines, is now in plain words,
  in Bulgarian too, and without a warning emoji.
- The README now shows NOVA (light and dark), what it does, how it works and why it is built that way.
  NOVA is MIT-licensed.

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
