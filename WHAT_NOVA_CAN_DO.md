# Everything NOVA can do

*Version 6.6.0 · macOS. For each thing: what you type or click, what happens, and how NOVA does it.*

## First: how NOVA works

1. You type (or say) something in plain words — English or Bulgarian.
2. Your message goes to the AI you chose (Groq, Claude, OpenAI, or a model running on your Mac), together with a
   list of **tools** — small actions NOVA can do on your Mac, like "open an app" or "read a file".
3. The AI either just answers, or picks a tool and fills in the details. For "open paris on the map" it picks
   the tool `open_maps` with the place "Paris".
4. NOVA runs that tool on your Mac. **If the action is risky (deleting, typing, running commands, shutting
   down …) NOVA shows you a question first and only continues if you allow it.**
5. The tool's result goes back to the AI, which tells you what happened in one short sentence. It can chain
   several tools for one request ("find the newest PDF in Downloads and summarize it").

So the AI decides *what* to do; NOVA's own code does it, and you approve anything that could cause harm.

---

## 1. Opening things

| You type | What happens | How it works |
|---|---|---|
| "open paris on the map", "show me the way to Plovdiv" | Google Maps opens in your browser at that place | Tool `open_maps`: builds a `google.com/maps/search/…` address and hands it to your default browser |
| "open youtube.com", "go to github" | The page opens in your browser | Tool `open_url`: adds `https://` if missing and opens it |
| "google best laptops 2026" | A Google results page opens | Tool `search_web`: opens `google.com/search?q=…` in the browser |
| "open Spotify", "start Chrome", "open calculator" | The app starts | Tool `open_application`: knows everyday names (also Windows ones: "notepad" → TextEdit, "task manager" → Activity Monitor, "control panel" → System Settings), keeps an index of every app in your Applications folders, then asks macOS to open it (`open -a`) |
| "show my Downloads folder", "show that file in Finder" | Finder opens with the file selected | Tool `open_in_explorer`: runs `open -R <file>` |
| type just **`work`** | Chrome, VS Code and Spotify open together | Your own one-word shortcuts (the `shortcuts` list in the settings file: a word → apps to open). No AI involved |

## 2. The internet

| You type | What happens | How it works |
|---|---|---|
| "what's the latest news about Tesla?", "how much does an iPhone 17 cost?" | NOVA searches and answers with what it found | Tool `search_web_and_read`: asks several search engines in turn - DuckDuckGo, Yahoo, Wikipedia and others, each listed in *What NOVA sent* - (or Brave Search, if you entered a key in Settings → AI) and gives the AI the titles, links and snippets of the top results |
| "summarize this article: https://…" | NOVA reads the page and summarizes it | Tool `read_webpage`: downloads the page, strips menus/scripts, passes the first ~4,000 characters to the AI. Addresses inside your home network are refused |
| "what's the weather?", "weather in Varna" | Current weather and today's forecast | Tool `get_weather`: Open-Meteo (a free official weather service). With no city it uses your **home city** from Settings → General — it never guesses your location |
| ＋ → **Daily news** | The top headlines appear in the chat | Reads Google News' public feed directly — no AI request needed |

Everything that comes from the web is treated as **outside content** (see Safety): NOVA will not follow instructions hidden in a web page.

## 3. Files and folders

| You type | What happens | How it works |
|---|---|---|
| "what's in my Documents folder?" | A list of files and folders | Tool `manage_files` (action *list*) |
| "move report.pdf to Desktop", "rename…" | Done — **after you approve** | Tool `manage_files`. The approval shows exactly which files are affected |
| "copy report.pdf to Desktop", "make a folder called Invoices" | Done (nothing is lost by these, so no question) | Tool `manage_files` |
| "delete old.txt" | The file goes to the **Trash** (not gone forever) — after you approve | Tool `manage_files` (action *delete*): moves it to `~/.Trash`. System folders and your whole home/Documents/Desktop folders are protected and cannot be deleted |
| "find my CV", "find files that mention 'invoice 2031'" | A list of matching files | Tool `search_files`: walks your home folder (or one you name), by file name — or inside files if you ask. Stops after 20 seconds |
| "read notes.txt", "what does this PDF say: ~/Downloads/x.pdf" | NOVA reads it and answers | Tool `read_file`: plain text directly; PDF, Word, PowerPoint, Excel (`.xlsx` **and old `.xls`**), Numbers, and **photos / scans of text** (read on the Mac with Apple's text recognition) |
| "write a shopping list to ~/Desktop/list.txt" | The file is written — after you approve | Tool `write_file`. If the file exists, the approval shows a **before/after diff** of what would change |
| "empty the trash" | Trash is emptied — after you approve | Tool `empty_recycle_bin`: asks Finder to empty the Trash |
| Drag a file onto NOVA, or ＋ → **Analyze file** | Small file: sent with your question. Big file / folder: added to your document library | Text is extracted on the Mac; you see a preview before anything is sent (Settings → Privacy → *Preview … before sending*) |

## 4. Your documents ("ask about my files")

| You do | What happens | How it works |
|---|---|---|
| ＋ → **Documents** → add files or a whole folder (or drop a folder on NOVA), or type "add ~/Documents/contract.pdf to my documents" | They are indexed | Tool `add_document`: text is pulled out **on your Mac**, cut into passages of about a page, and stored in NOVA's data folder |
| "what does my rental contract say about the deposit?" | An answer with the document name and page | Tool `search_documents`: finds the best-matching passages by their words (the AI adds other wordings and translations of your question, so "deposit" also finds "депозит" or "advance payment"). **Only those few passages are sent to the AI**, never the whole document |
| ＋ → **Documents** → *Search by meaning* → **Download (135 MB)**, once | Questions also find passages that say the same thing in other words or another language: "how much do I put down up front for the flat?" finds "a security deposit equal to two monthly rents", a Bulgarian question finds an English contract | A small multilingual model runs **on your Mac** (no text leaves it for this). Each passage gets a "meaning fingerprint" when it is indexed; a question's fingerprint is compared with all of them, and the result is blended with the word search. On NOVA's test library it finds 11 of 12 reworded questions (words alone: 2) and 6 of 6 Bulgarian questions about English text |
| Change a document on disk | NOVA re-reads it by itself | It compares the file's date and size before each search; new files in an added folder are picked up too |
| "which documents do you have?", "forget the old contract" | List / remove from the index (the file itself is not touched) | Tools `list_documents`, `remove_document` |

Scanned PDFs are read with on-device text recognition (up to 80 pages per file).

## 5. Memory, notes and reminders

| You type | What happens | How it works |
|---|---|---|
| "remember that my sister's birthday is 3 May", or just mention something personal | NOVA saves it and uses it later | Tool `save_memory`: stored in a file on your Mac with a category (About me, Preference, Work, People, Task, Other); can expire ("remember for a week that…"). Only the memories that fit your current question are added to a request |
| "what do you know about me?", "forget what I said about my job" | Lists / deletes memories | Tools `read_memory`, `delete_memory`. You can also view and edit them: Settings → Privacy → *View memories* |
| "note: call the plumber" · ＋ → **View notes** | Saved with date and time / shows all notes | Tools `save_note`, `read_notes`: one text file in NOVA's data folder |
| "remind me in 20 minutes to check the oven" | A notification and a message after 20 minutes | Tool `set_reminder`: a timer; saved to disk, so it survives a restart of NOVA |
| "every weekday at 8 give me the news and weather", "remind me every Friday at 17:00 to send the report" | It happens at that time, repeatedly | Tools `schedule_task` / `list_scheduled_tasks` / `cancel_scheduled_task`: NOVA checks the clock every minute. A *request* is sent to the AI at that time; a *reminder* is just shown. If the Mac was asleep, it catches up within 6 hours. Manage them under ＋ → **Scheduled tasks** |

## 6. Controlling the Mac

| You type | What happens | How it works |
|---|---|---|
| "volume up", "set volume to 30", "mute" | The volume changes | Tool `control_volume`: AppleScript (`set volume output volume …`) |
| "lock the screen" · "go to sleep" | Locks at once · sleeps after you approve | Tool `control_system` |
| "shut down", "restart" | Starts a **10-second countdown** — asks first; say "cancel" to stop it | Tool `control_system`: tells macOS to shut down when the countdown ends |
| "next song", "pause the music" | Spotify skips / pauses | Tool `control_spotify`: talks to the Spotify app (never starts it by itself). The current track is also shown in NOVA's title bar |
| "what's my battery?", "how much RAM is used?", "what's my IP / Wi-Fi?" | The numbers | Tools `get_battery`, `get_system_stats`, `get_network_info` |
| "what's using the most memory?", "quit Safari", "force quit Safari" | A list of running apps / the app quits as with ⌘Q and may ask to save; "force quit" (or a process number) ends it at once (asks first) | Tools `list_processes`, `kill_process` (AppKit's `terminate`, or a kill when forced). System processes, Finder and NOVA itself are protected |
| "what's in my clipboard?", "copy this to the clipboard: …" | Reads / sets the clipboard | Tools `get_clipboard`, `set_clipboard` |
| "take a screenshot" | A picture is saved to the Desktop | Tool `take_screenshot` (needs the Screen Recording permission) |
| "type 'Hello, how are you?' in the app I'm using" | NOVA types it for you — asks first, and shows which app will receive it | Tool `type_text_keyboard`: switches to the other app and pastes the text (so Bulgarian letters work), then puts your clipboard back. Needs the Accessibility permission |
| "set this picture as my wallpaper" | The desktop picture changes | Tool `set_wallpaper` |
| "send me a notification that the download is done" | A notification appears | Tool `send_notification` |

## 7. Calendar, Reminders, Mail, browser

These use the Mac's own apps. The first time, macOS asks you to allow NOVA to use each one.

| You type | What happens | How it works |
|---|---|---|
| "what's on my calendar today / this week?" | Your events | Tool `get_calendar_events`: Apple's EventKit, in a small helper process |
| "add a meeting with Ivan tomorrow at 15:00 for an hour" | The event is created in Calendar | Tool `add_calendar_event` (repeating and all-day events too) |
| "what's on my reminders list?", "add 'buy milk' to my reminders" | Reads / adds in the **Reminders app** (syncs to your iPhone) | Tools `list_apple_reminders`, `add_apple_reminder` |
| "summarize the email I have selected" | A summary | Tool `read_selected_email`: reads the message selected in Mail |
| "write an email to Maria about Friday's meeting", "reply that I agree" | A filled-in **draft** opens in Mail | Tools `draft_email`, `draft_email_reply`. **NOVA never sends mail — you press Send** |
| "summarize this page" (with a page open in Safari, Chrome, Arc, Brave or Edge) | A summary of the page you are looking at | Tool `read_browser_tab`: asks the browser for the page's address and text |

## 8. Apple Shortcuts, in both directions

| You do | What happens | How it works |
|---|---|---|
| "run my Morning Routine shortcut" | The shortcut runs — after you approve (you can allow one shortcut for good) | Tools `list_shortcuts`, `run_shortcut`: macOS's `shortcuts run` command |
| In a shortcut: *Run Shell Script* `NOVA --ask "Summarize: $1" --wait` | The shortcut receives NOVA's answer as text | A second, tiny copy of NOVA passes the text to the running one over a private local connection, waits, and prints the answer. If NOVA is not running it is started in the menu bar |
| *Open URL* `nova://ask?text=…` | The text appears in NOVA's message box | NOVA registers the `nova://` link type |

Text arriving from another app waits for you to press Enter (unless you turn on auto-send in Settings → Privacy), and risky tools always ask, because NOVA cannot know who wrote that text.

## 9. Text selected in any app (⌃⇧Space)

Select text anywhere → press **⌃⇧Space** → a small menu appears next to the mouse:

- **Explain**, **Summarize** — the answer appears in NOVA.
- **Translate** (Bulgarian ↔ English), **Rewrite**, **Fix grammar** — the result is copied, so ⌘V pastes it over your selection. With Settings → General → *Paste rewrites … straight over the selection*, NOVA switches back and pastes it for you.
- **Your own actions** — menu → *My actions…*: give a name and an instruction ("Make this formal:").
- **Ask NOVA about it…** — puts the text in the message box so you can type your own question.

How: NOVA asks macOS (Accessibility) for the selected text; for apps that do not answer, it presses ⌘C for you and restores your clipboard afterwards.

## 10. Voice

| You do | What happens | How it works |
|---|---|---|
| Click the microphone (or hold it to talk) | Your speech becomes text in the message box | Recorded on the Mac, then recognised **on the Mac itself** once you have downloaded the speech model (Settings → Voice → *Any language, on this Mac*, 574 MB: Bulgarian, English and 97 more languages, about a second per sentence), otherwise by your AI provider |
| Say **"Hey NOVA"** (Settings → Voice → Wake word) | NOVA wakes up and listens | With the offline model the word is detected on the Mac and nothing is uploaded while it listens |
| 🔊 on any reply, or *Read every reply aloud* | NOVA speaks | Microsoft's online voices (English, Bulgarian, German …) or the Mac's built-in voice (offline) |
| ＋ → **Voice conversation** | Hands-free: you talk, NOVA answers aloud, listens again | Ends when you say "stop listening" / "стоп", tap the mic, or stay quiet. **You can talk over NOVA to interrupt it** — it compares the microphone with the sound it is playing, so it does not interrupt itself |

## 11. Seeing things: screen and pictures

| You do | What happens | How it works |
|---|---|---|
| ＋ → **Analyze screen** (type a question first if you like) | NOVA looks at your screen and answers | Takes a screenshot, shows you a preview, then sends it to a model that understands images |
| ＋ → **Analyze part of the screen** | Drag a rectangle; only that part is analysed | macOS's own crosshair tool |
| Drop or pick a picture | NOVA describes it or answers about it | Same image-understanding models |

## 12. Without the AI: instant things

| You do | What happens |
|---|---|
| Type **`= 15% of 200`**, `= 2^10`, `= (4+5)*3` | The answer at once — a built-in calculator, no request sent |
| ＋ → **Quick commands** | A row of one-click buttons: Weather, Battery, CPU/RAM, Network, Clipboard, Processes, Trash, Volume +/−, Memory, News, Lock |
| ＋ → **Paste clipboard** | Pastes your clipboard (or picks from the last 8 things you pasted this way) into the message box |
| ＋ → **Games** | Wordle (a new word every day) and Guess the number, with your streaks and statistics |
| ＋ → **Sessions** | Every past chat, saved automatically with a title; open one to continue it |
| ＋ → **Export chat** | Saves the conversation as a text file on your Desktop |

## 13. Shaping how NOVA answers

- **Modes** (＋ → Mode): Assistant, **Coder**, **Translator**, **Tutor**, **Writer** — or your own. A mode adds instructions to every request until you switch back.
- **Saved prompts**: type `/tldr`, `/eli5` or `/fix` before a text — or save your own `/name`.
- **Answer length** (the lines button in the input box): Short · Normal · Detailed.
- **Model and mode** (the small label in the input box): switch between the best and the fast model of your provider, or pick a mode. If the best one is busy, NOVA retries with the fast one by itself.
- **↻** regenerates the last answer. **Double-click one of your messages** to edit and resend it.
- **Follow-up suggestions** (Settings → AI): clickable next questions under each reply.
- Long conversations are summarized in the background so they keep fitting in the model's memory.

## 14. More tools from outside

- **Tool servers (MCP)** — ＋ → Tool servers: connect ready-made servers (GitHub, Notion, databases …) by command or web address, or paste the JSON other apps use. Their tools appear to the AI like NOVA's own. NOVA asks the first time each one is used, treats what they return as outside content, and keeps their tokens in the Keychain.
- **Plugins** — drop a small Python file into NOVA's `plugins` folder to add your own tool (example: `examples/plugins/word_count.py`). NOVA asks for your consent per file, and plugins run **sealed in a sandbox** with only the permissions they declare (internet / read files / write files). ≡ → Plugins lists every tool.
- **Run code** — "calculate the first 20 primes in Python", "run `ls -la ~/Desktop`": tools `execute_python_code` (10-second limit, separate process) and `run_shell_command`. **Both always ask first.**

## 15. Safety and privacy

- **Approval before risk.** These always show a question first: shell commands, Python code, deleting / moving / renaming files, writing files, stopping apps, shutdown / restart / sleep, emptying the Trash, typing for you, running a shortcut, tool-server tools, and plugin tools that have permissions. You can *Always allow* one narrow thing (one folder, one app, one shortcut) — never everything. Review the list in Settings → Privacy.
- **Outside content is never trusted.** Once a request has read a web page, a file, an email, the clipboard, your calendar or a document, **every** action with an effect (opening pages and apps, calendar events, reminders, mail drafts …) needs your approval, and "always allow" is switched off for that request — so hidden text in a page cannot make NOVA do things.
- **Your keys** are stored in the macOS Keychain, not in a file.
- **Encryption** (Settings → Privacy): chats, memories, notes and logs can be encrypted on disk; the key lives in the Keychain.
- **What NOVA sent today** (Settings → Privacy): every internet request — where to and how much, never the content. **Activity log**: every tool that ran, and whether you allowed it.
- **Preview before upload**: screenshots, pictures and files are shown to you before they go to the AI.
- **Your data is yours**: Settings → Data → Export my data / Delete all my data. Chats can be deleted automatically after N days.
- **Crash reports** are off unless you turn them on, and stay on your Mac unless you send them.

## 16. The AI behind it

Settings → AI: **Groq** (free and fast), **Anthropic (Claude)**, **OpenAI**, **Ollama** (a model running on your own Mac — private and offline), or any OpenAI-compatible server. You can pick the models, how hard the model should think, and test the connection. **Help → Usage and cost** shows how many tokens each provider used and an estimated price.

## 17. The window

- **⌘⇧Space** shows or hides NOVA from anywhere. It also lives in the menu bar (tray icon).
- Three sizes: **bubble** (a small circle), normal, and **full screen** — the yellow and green window buttons; the red one hides NOVA to the menu bar.
- **Pin** keeps it on top of other windows. Drag the title bar to move, a corner to resize.
- Looks: **Paper** and **Sage** (light), **Graphite** and **Espresso** (dark), or *Auto* to follow the system — plus your own accent colour and font size (⌘+ / ⌘−).
- Under each of NOVA's replies you see **what it did** as neat rows ("Opened Maps · Paris ✓"); click a row for the exact details.
- English or Bulgarian interface (Settings → General).
- **Launch at login** (Settings → General): NOVA starts hidden in the menu bar, so the hotkey and scheduled tasks work without opening the window.
- **Morning briefing**: when NOVA starts between 7 and 11 in the morning it greets you with the weather (if a home city is set) and the top headlines.
- If NOVA is hidden when an answer arrives, you get a notification.
- Help menu: What's new · Keyboard shortcuts · Open logs · Usage and cost · Copy diagnostics · Check for updates (needs an update address in the settings file; NOVA can then install the new version in place).

---

### What needs a permission from macOS (asked the first time)

| Feature | Permission |
|---|---|
| Microphone, wake word, voice conversation | Microphone |
| Screenshot, Analyze screen | Screen Recording |
| Typing for you, ⌃⇧Space on some apps, paste-over-selection, the global hotkey | Accessibility |
| Calendar / Reminders / Mail / browser page / Spotify / Finder actions | Each app's own "allow NOVA to control …" question |

### What NOVA does not do

- It never sends an email, pays, or posts anything by itself.
- It does not watch your screen, microphone or clipboard in the background (except the wake word, if you turned it on).
- It does not upload your documents: only the passages that match a question leave the Mac.

---

## NOVA on Windows

NOVA also runs on Windows 10 and 11, from the same code and with the same look. **This part is new: it is checked by
automatic tests on Windows machines, but nobody has used it on a real PC yet** — expect first-use surprises in
anything you see, hear or press. Where nothing is said below, a feature works the same as on the Mac.

| Part of this guide | On Windows |
|---|---|
| 1. Opening things | Same. Apps are found by their Start menu name (Store apps such as Calculator included). Files are shown in Explorer. |
| 2. The internet | Same. |
| 3. Files and folders | Same. Delete moves to the **Recycle Bin** — and refuses on a USB stick or network drive, which have none, instead of deleting for good. Commands run in `cmd`. |
| 4. Your documents | Search by meaning (the on-device model): same. PDF, Word, PowerPoint, Excel, Numbers, plain text: same. Rich text (`.rtf`), OpenDocument (`.odt`) and web pages (`.html`) are read by NOVA itself. **Not readable:** old Word `.doc` (save as `.docx`), `.rtfd`, `.webarchive`. Scans and photos use Windows' own text recognition, for the languages installed in Windows. |
| 5. Memory, notes and reminders | Same. Notifications come from NOVA's icon in the notification area. |
| 6. Controlling the computer | Volume, mute, lock, sleep, hibernate, shut down / restart (10 seconds to cancel), empty the Recycle Bin, wallpaper, clipboard, typing, running programs, battery, network, screenshot. Spotify: play / pause / next / previous through the media keys. "Quit Notepad" closes the program the way its close button does, so it can ask to save; "force quit" (or a process number) ends it at once. Program names work without ".exe". |
| 7. Calendar, Reminders, Mail, browser | **Not available.** These use Apple's apps. NOVA does not offer these tools to the AI on Windows, so it will say it cannot rather than try. |
| 8. Apple Shortcuts, in both directions | Apple Shortcuts do not exist on Windows. Other programs can still hand NOVA a request: `NOVA-cli --ask "…" --wait` prints the answer, and `nova://ask?text=…` links open the installed app. |
| 9. Text selected in any app | The shortcut is **Ctrl+Alt+Shift+Space**. NOVA always copies the selection for you (Ctrl+C) and then puts your clipboard back. |
| 10. Voice | Microphone, wake word, read aloud (online voices, or Windows' own voice offline) and voice conversation. Speech in any language on this PC (Whisper, Settings → Voice): same. With the online voices, "talk over NOVA to interrupt" uses a plain loudness threshold unless ffmpeg is installed. |
| 11. Seeing things | Whole screen: same. Part of the screen: NOVA dims the screen the mouse is on and you drag a rectangle (Esc cancels). |
| 12–13, 15–16 | Same. Keys are kept in **Windows Credential Manager**. |
| 14. More tools from outside | Tool servers (MCP): same. Plugins: a plugin without a `MANIFEST` can be allowed after the same warning. **A plugin with a `MANIFEST` is not loaded**, because Windows has no sandbox NOVA can put it in — NOVA never runs such a plugin unsealed. |
| 17. The window | Same look and the same three round buttons. Show / hide from anywhere: **Ctrl+Alt+Space**. NOVA sits in the notification area (bottom right). "Start with Windows" replaces "Launch at login". There is no menu bar; Ctrl+N, Ctrl+Q and the other keys still work. |
| Permissions | Windows asks for none. Voice needs Settings → Privacy & security → Microphone → "Let desktop apps access your microphone". |
| Where things are kept | Data: `%APPDATA%\NOVA` · logs: `%LOCALAPPDATA%\NOVA\Logs` |
| Updates | NOVA looks at its GitHub releases (or your own feed) for a Windows setup program (`NOVA-<version>-setup.exe`); it is downloaded, checked against the SHA-256 GitHub publishes and opened, and it replaces NOVA. A release with only the Mac disk image is no update for Windows. Run from its source code, NOVA says to update with `git pull`. |

If another program already uses Ctrl+Alt+Space, NOVA says so when it starts; the icon in the notification area still works.
