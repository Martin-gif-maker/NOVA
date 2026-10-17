# Third-party software

NOVA is built on the open-source packages below. Licence names come from each package's own metadata;
the full texts ship with the packages (inside the app bundle under `Contents/Resources`/site-packages).

| Package | Version | Licence |
|---|---|---|
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| groq | 1.7.0 | Apache-2.0 |
| anthropic | 1.13.0 | MIT |
| openai | 3.27.0 | Apache-2.0 |
| vosk | 0.3.44 | Apache-2.0 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| pyautogui | 0.9.54 | BSD |
| Pillow | 12.3.0 | MIT-CMU |
| requests | 2.34.2 | Apache-2.0 |
| sounddevice | 0.5.6 | MIT |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| psutil | 7.2.2 | BSD-3-Clause |
| keyring | 25.7.0 | MIT |
| ddgs | 9.16.0 | MIT |
| pyperclip | 1.11.0 | BSD |
| edge-tts | 7.2.8 | GNU Lesser General Public License v3 (LGPLv3) |
| markdown-it-py | 4.2.0 | MIT License |
| linkify-it-py | 2.2.0 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyobjc-core | 12.2.2 | MIT |
| pyobjc-framework-Cocoa | 12.2.2 | MIT |
| pyobjc-framework-Quartz | 12.2.2 | MIT |
| pyobjc-framework-EventKit | 12.2.2 | MIT |
| pyobjc-framework-Vision | 12.2.2 | MIT |
| numbers-parser | 4.19.0 | MIT |
| xlrd | 2.0.2 | BSD |
| onnxruntime | 1.31.0 | MIT |
| tokenizers | 0.23.3 | Apache-2.0 |
| flatbuffers | 25.12.19 | Apache-2.0 |
| protobuf, cramjam, python-snappy (used by numbers-parser) | 7.36.2, 2.13.0, 0.7.3 | BSD-3-Clause, MIT, BSD |
| compact-json, sigfig, six, wcwidth (used by numbers-parser) | 1.8.2, 1.4.0, 1.17.0, 0.9.2 | MIT |
| python-dateutil, importlib_resources (used by numbers-parser) | 2.9.0.post0, 7.1.0 | Apache-2.0 OR BSD-3-Clause, Apache-2.0 |
| enum-tools (used by numbers-parser) | 0.13.0 | LGPL-3.0-or-later |
| pyinstaller | 6.22.3 | GNU General Public License v2 (GPLv2) |
| mcp (tests only, not bundled) | 2.3.0 | MIT |

PyInstaller is a build tool; its licence includes an exception that lets you distribute apps built with it under any licence.

## LGPL notice (PySide6 / Qt, edge-tts)
PySide6 and Qt are used under the GNU LGPL v3. NOVA links to them dynamically (the shared libraries inside
`NOVA.app`), so you may replace those libraries with your own build of Qt/PySide6 as the LGPL requires.
Source code for PySide6 and Qt is available from https://code.qt.io and https://pypi.org/project/PySide6/.
`edge-tts` is LGPL-3.0 and is used unmodified.

## Offline voice model (downloaded on request, not bundled)
`vosk-model-small-en-us-0.15` from https://alphacephei.com/vosk/models — Apache-2.0. NOVA downloads it only when you
press *Download* in Settings → Voice, and verifies its SHA-256 before unpacking.

## Search-by-meaning model (downloaded on request, not bundled)
`multilingual-e5-small` by Liang Wang et al. (https://huggingface.co/intfloat/multilingual-e5-small), in the 8-bit ONNX
form published at https://huggingface.co/Xenova/multilingual-e5-small — MIT. NOVA downloads it only when you press
*Download* in ＋ → Documents, from a pinned revision, and verifies each file's SHA-256 before using it. It runs with
`onnxruntime` (MIT) and `tokenizers` (Apache-2.0).

## Services NOVA contacts (not bundled)
* The AI provider you choose: Groq, Anthropic, OpenAI, or a server you run yourself (Ollama / custom).
* Open-Meteo (weather; free for non-commercial use), Google News RSS (headlines).
* Web search: DuckDuckGo via `ddgs` (unofficial) or the Brave Search API with your own key (official).
* Read-aloud: Microsoft Edge online voices via `edge-tts` (unofficial) unless the system voice is selected.
* MCP tool servers you connect yourself: whatever those servers contact is up to them.

Each has its own terms; review them before distributing NOVA. "What NOVA sent today" (Settings → Privacy) shows
which of them were actually contacted.
