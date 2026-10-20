# i18n.py — interface translations. English text is the key; unknown strings fall back to English.
#   tr("Settings")  ->  "Настройки" when the interface language is Bulgarian.
# Lookup order: the exact string, then the text without leading symbols/emoji and trailing punctuation
# (so "⚙  Settings" and "Settings:" both find the "Settings" entry and keep their decoration).
#
# The texts are written with the Mac's words. On Windows the same texts are shown with Windows' words
# (PC, Recycle Bin, Explorer, Credential Manager, notification area …): see local() at the end.
import re, sys

_LANG = "en"
SUPPORTED = ("en", "bg")

BG = {
    # buttons / menus
    "Copy response": "Копирай отговора", "Read aloud": "Прочети на глас", "Copy code block": "Копирай кода",
    "Actions": "Действия", "Voice input - click to start/stop, or hold to talk": "Гласов вход — кликни за старт/стоп или задръж, за да говориш",
    "Keyboard shortcuts": "Клавишни комбинации", "Hide": "Скрий", "Minimize": "Минимизирай", "Pin / Unpin": "Закачи / Откачи",
    "More options": "Още опции", "Fullscreen": "На цял екран", "Settings": "Настройки", "Switch AI model": "Смени AI модела",
    "Export": "Експорт", "New chat": "Нов чат", "Show / Hide": "Покажи / Скрий", "Quit": "Изход", "Sessions": "Сесии",
    "Plugins": "Добавки", "Export chat": "Експортирай чата", "Change API key": "Смени API ключа",
    "Quick commands": "Бързи команди", "Stop TTS": "Спри озвучаването", "Games": "Игри", "Analyze screen": "Анализирай екрана",
    "Analyze file": "Анализирай файл", "Paste clipboard": "Постави от клипборда", "View notes": "Бележки", "Daily news": "Новини",
    "No saved sessions": "Няма запазени сесии", "Load": "Зареди", "Delete": "Изтрий", "Regenerate": "Генерирай отново",
    "Refresh": "Обнови", "Reset": "Нулирай", "Clear all": "Изчисти всичко", "View memories": "Покажи спомените",
    "Send message": "Изпрати съобщението", "Response length": "Дължина на отговора", "Message NOVA": "Съобщение до NOVA",
    "Scroll to latest message": "Към последното съобщение",
    "Ask NOVA anything...  (Shift+Enter = new line)": "Питай NOVA каквото и да е...  (Shift+Enter = нов ред)",
    # settings
    "NOVA Settings": "Настройки на NOVA", "Model": "Модел", "Theme": "Тема", "Font size": "Размер на шрифта",
    "Voice (TTS)": "Озвучаване (TTS)", "TTS voice": "Глас", "Wake word": "Активираща дума", "Wake sensitivity": "Чувствителност",
    "Voice": "Гласов вход", "Memories": "Спомени", "Accent color": "Акцентен цвят", "Autostart": "Автостарт",
    "Thinking:": "Мислене:", "Follow-ups": "Следващи въпроси", "Auto-read": "Авточетене", "Voice language": "Език на гласа",
    "Data & privacy": "Данни и поверителност", "Interface language": "Език на интерфейса",
    "Auto-send after voice input": "Изпращай автоматично след гласов вход",
    "Enabled (sends speech to Groq)": "Включена (изпраща реч към Groq)", "Enabled": "Включено",
    "Read every reply aloud": "Чети всеки отговор на глас",
    "Suggest follow-up questions (one extra request per reply)": "Предлагай следващи въпроси (една допълнителна заявка на отговор)",
    "Export my data": "Експорт на данните ми", "Open data folder": "Отвори папката с данни", "Open logs": "Отвори логовете",
    "Delete all my data": "Изтрий всички мои данни", "Run setup again": "Пусни настройката отново",
    "Check for updates": "Провери за обновления", "View activity log": "Покажи журнала с действия",
    "Reset approvals": "Нулирай одобренията", "Copy diagnostics": "Копирай диагностика",
    "Click to pick color": "Кликни за избор на цвят", "Save": "Запази", "Cancel": "Отказ",
    "Applies after restart": "Влиза в сила след рестарт",
    # Windows
    "sandboxed plugins do not work on Windows yet": "изолираните добавки още не работят под Windows",
    "The shortcut {} is already used by another program, so it cannot show or hide NOVA. Use NOVA's icon in the notification area instead.":
        "Клавишната комбинация {} вече се използва от друга програма, затова не може да показва или скрива NOVA. Използвай иконата на NOVA в областта за уведомяване.",
    # new in v6
    "Keep chat history on this Mac": "Пази историята на чата на този Mac", "History:": "История:",
    " days (0 = forever)": " дни (0 = завинаги)", "Delete saved chats after:": "Изтривай чатовете след:",
    "Preview screenshots, images and files before sending them to the AI": "Показвай преглед на екранни снимки, изображения и файлове преди изпращане към AI",
    "Uploads:": "Качвания:", "Ask before NOVA saves or forgets a memory": "Питай, преди NOVA да запомни или забрави нещо", "Memory:": "Памет:",
    "Stop recording automatically when I stop talking": "Спирай записа автоматично, когато млъкна", "Recording:": "Запис:",
    "Search chats…": "Търси в чатовете…", "Search chats": "Търси в чатовете", "messages": "съобщения", "Rename": "Преименувай", "Close": "Затвори",
    "Chat title:": "Заглавие на чата:", "Delete this chat permanently?": "Да изтрия ли този чат завинаги?",
    "NOVA Memories": "Спомени на NOVA", "What NOVA remembers about you (sent with every request):": "Какво NOVA помни за теб (изпраща се с всяка заявка):",
    "Add": "Добави", "Done": "Готово", "Something NOVA should remember:": "Нещо, което NOVA да запомни:",
    "Send to the AI?": "Да изпратя ли към AI?", "This image will be sent to Groq for analysis:": "Това изображение ще бъде изпратено към Groq за анализ:",
    "This text will be sent to Groq:": "Този текст ще бъде изпратен към Groq:", "characters": "знака", "Send to AI": "Изпрати към AI",
    "File": "Файл", "Edit": "Редактиране", "View": "Изглед", "Window": "Прозорец", "Help": "Помощ",
    "{} tool call": "{} действие с инструмент", "{} tool calls": "{} действия с инструменти", "{} failed": "{} неуспешни",
    "Show what NOVA did": "Покажи какво направи NOVA",
    # messages
    "Cancelled": "Отказано", "Settings saved": "Настройките са запазени",
    "New chat. Sessions saved in the + menu": "Нов чат. Сесиите са запазени в менюто +",
    "Session deleted": "Сесията е изтрита", "All memories cleared": "Всички спомени са изтрити",
    "NOVA is busy - try again in a moment": "NOVA е заета — опитай след малко",
    "Still working on your previous request - wait for it or press ✕": "Още работя по предишната заявка — изчакай или натисни ✕",
    "Still transcribing the last recording…": "Още разпознавам последния запис…",
    "NOVA is still answering - your command is in the input box": "NOVA още отговаря — командата ти е в полето за въвеждане",
    "NOVA is listening...": "NOVA слуша...", "Recording... tap mic to stop": "Записвам... натисни микрофона за стоп",
    "Clipboard is empty": "Клипбордът е празен", "Loading news...": "Зареждам новини...",
    "Cannot divide by zero": "Не може да се дели на нула", "No API key": "Няма API ключ",
    "Thinking": "Мисля", "NOVA wants to:": "NOVA иска да:", "NOVA — approve action?": "NOVA — одобряваш ли действието?",
    "Allow once": "Разреши веднъж", "Always allow this kind": "Винаги разрешавай такива", "Deny": "Откажи",
    "All 'always allow' approvals were reset - NOVA will ask again": "Одобренията „винаги“ са нулирани — NOVA ще пита отново",
    "Loaded: {}": "Заредена сесия: {}", "Loaded {} messages from last session.": "Заредени {} съобщения от последната сесия.",
    "Heard: «{}»": "Чух: «{}»", "Recognized: {}": "Разпознах: {}", "Theme: {}": "Тема: {}", "Model: {}": "Модел: {}",
    "Reminder: {}": "Напомняне: {}", "Saved: {}": "Запазено: {}",
    # quick commands (label, prompt)
    "Weather": "Времето", "Battery": "Батерия", "CPU/RAM": "CPU/RAM", "Network": "Мрежа", "Clipboard": "Клипборд",
    "Processes": "Процеси", "Trash": "Кошче", "Memory": "Спомени", "News": "Новини", "Lock": "Заключи",
    "get the current weather": "покажи времето",
    "what is my battery level": "колко е батерията ми", "show CPU and RAM stats": "покажи натоварването на CPU и RAM",
    "show my network and WiFi info": "покажи информация за мрежата и WiFi", "what is in my clipboard right now": "какво има в клипборда ми",
    "list top 10 running processes by memory": "покажи топ 10 процеса по памет", "increase volume by 10": "увеличи звука с 10",
    "decrease volume by 10": "намали звука с 10", "read everything you know about me": "прочети всичко, което знаеш за мен",
    "give me the latest tech news": "дай ми последните технологични новини", "lock the computer": "заключи компютъра",
    # onboarding
    "Welcome to NOVA": "Добре дошъл в NOVA", "I understand and agree": "Разбирам и съм съгласен", "Continue": "Продължи",
    "Back": "Назад", "Skip for now": "Пропусни засега", "Start using NOVA": "Започни да ползваш NOVA",
    "Connect your AI": "Свържи AI", "Test key": "Провери ключа", "Permissions": "Разрешения", "Allow…": "Разреши…",
    "You're all set": "Всичко е готово", "Checking…": "Проверявам…", "Paste your key first": "Първо постави ключа",
    "Key works ✓": "Ключът работи ✓",
    "Your personal AI assistant for your desktop. Before we start, here is exactly how your data is handled:":
        "Твоят личен AI асистент за компютъра. Преди да започнем, ето как точно се обработват данните ти:",
    "PRIVACY": ("<b>Какво остава на твоя Mac:</b> чатовете, спомените, бележките и настройките ти (в потребителската ти папка, "
                "четими само от теб). Можеш да ги експортираш или изтриеш в Настройки.<br><br>"
                "<b>Какво се изпраща към други услуги:</b><br>"
                "• Съобщенията ти и текстът на файлове или екранни снимки, които поискаш да анализира → "
                "<b>AI доставчикът, който избереш на следващата страница</b> (с твоя собствен API ключ). Избери <b>Ollama</b> "
                "и AI-то ще работи на този Mac.<br>"
                "• По избор: записана реч за гласов вход → разпознаването на реч на този доставчик. С офлайн гласовия модел "
                "(Настройки → Глас) речта се разпознава на този Mac и активиращата дума никога не качва звук.<br>"
                "• По избор: текст на отговорите за четене на глас → онлайн гласовете на Microsoft (edge-tts). Избери системния глас "
                "в Настройки → Глас и нищо не се изпраща.<br>"
                "• Времето → Open-Meteo (градът, за който питаш), новините → Google News, търсенето → няколко търсачки една след друга "
                "(DuckDuckGo, Yahoo, Wikipedia …) или Brave; IP адресът ти е видим за тях.<br>"
                "• Когато питаш за календара, пощата, уеб страница, избран текст или документите си, частта, която отговаря на "
                "въпроса, се изпраща към AI доставчика като всяко друго съобщение. Документите се индексират на този Mac; "
                "напускат го само откъсите, които съвпадат с въпроса.<br>"
                "• Настройки → Поверителност → <b>Какво е изпратила NOVA днес</b> показва всяка заявка: накъде е отишла и колко е голяма. "
                "Там можеш и да шифроваш всичко, което NOVA пази на този Mac.<br><br>"
                "NOVA може да изпълнява команди на компютъра ти, когато поискаш. Винаги пита преди рисковани действия "
                "(команди в терминала, изтриване на файлове, въвеждане, изключване)."),
}
# ── second batch: settings tabs, providers, privacy tools, plugins, memory, status messages ──
BG.update({
    # memory editor / "what NOVA sent"
    "Category": "Категория", "Choose automatically": "Избери автоматично", "Keep for": "Пази за",
    "All categories": "Всички категории", "What NOVA sent": "Какво е изпратила NOVA", "Period": "Период",
    "Details": "Подробности", "Destination": "Получател", "What": "Какво", "Requests": "Заявки", "Data sent": "Изпратени данни",
    "Nothing was sent.": "Нищо не е изпратено.", "this Mac": "този Mac", "Until {}": "До {}",
    "{} requests left this Mac, about {} in total.": "{} заявки са напуснали този Mac, общо около {}.",
    "Every time NOVA sends something off this Mac it notes where it went, what kind of thing it was and how big — never the content itself. Requests to a server on this Mac are marked local.":
        "Всеки път, когато NOVA изпрати нещо извън този Mac, тя записва къде е отишло, какъв вид данни са били и колко големи — никога самото съдържание. Заявките към сървър на този Mac са отбелязани като локални.",
    "What NOVA remembers about you. Only the ones that fit your question are sent with it.":
        "Какво помни NOVA за теб. С всеки въпрос се изпращат само спомените, които са свързани с него.",
    "This image will be sent to {} for analysis:": "Това изображение ще бъде изпратено към {} за анализ:",
    "This text will be sent to {}:": "Този текст ще бъде изпратен към {}:",
    "About me": "За мен", "Preference": "Предпочитание", "Work": "Работа", "People": "Хора", "Task": "Задача", "Other": "Друго",
    "Forever": "Завинаги", "1 day": "1 ден", "1 week": "1 седмица", "1 month": "1 месец", "1 year": "1 година",
    "Today": "Днес", "Last 7 days": "Последните 7 дни", "Last 30 days": "Последните 30 дни",
    "chat": "чат", "image analysis": "анализ на изображение", "model list": "списък с модели",
    "speech-to-text": "разпознаване на реч", "read aloud": "четене на глас", "web search": "търсене в интернет",
    "read web page": "четене на уеб страница", "weather": "време", "news headlines": "новинарски заглавия",
    "update check": "проверка за обновления", "update download": "изтегляне на обновление",
    "voice model download": "изтегляне на гласовия модел", "crash report": "доклад за срив",
    "plugin with internet access": "добавка с достъп до интернет",
    # main window
    "Bigger text": "По-голям текст", "Smaller text": "По-малък текст", "Bubble mode": "Режим балонче",
    "Enter new API key:": "Въведи нов API ключ:", "Brave API key": "API ключ за Brave",
    "Enter your Brave Search API key:": "Въведи своя API ключ за Brave Search:",
    "Messages in current context": "Съобщения в текущия контекст",
    "Response length: Normal — click to cycle Short / Normal / Detailed":
        "Дължина на отговора: нормална — кликни за смяна: кратка / нормална / подробна",
    "Keychain unavailable — key saved to a private file.": "Keychain не е достъпен — ключът е запазен в личен файл.",
    "No API key yet, so NOVA cannot answer. Choose ≡ → Change API key.":
        "Все още няма API ключ, затова NOVA не може да отговаря. Избери ≡ → Смени API ключа.",
    "Hi, I'm NOVA. Ask me anything, or press + to see what I can do.":
        "Здравей, аз съм NOVA. Питай ме каквото и да е или натисни +, за да видиш какво мога.",
    "to a private file (keychain unavailable)": "в личен файл (Keychain не е достъпен)",
    "for this session only (could not be stored!)": "само за тази сесия (не можа да бъде запазен!)",
    "Could not change the launch-at-login setting.": "Настройката за стартиране при вход не можа да бъде променена.",
    "Could not store the API key; you'll be asked again next launch.":
        "API ключът не можа да бъде запазен; ще бъдеш попитан отново при следващото стартиране.",
    "{} API key": "API ключ за {}", "Brave Search key saved ✓": "Ключът за Brave Search е запазен ✓",
    "Could not store the Brave Search key.": "Ключът за Brave Search не можа да бъде запазен.",
    "✓ Now using {}": "✓ Вече се използва {}", "⚡  Model: {} ({})": "⚡  Модел: {} ({})", "✓ Model: {} ({})": "✓ Модел: {} ({})",
    "🔑  {} does not use an API key.": "🔑  {} не използва API ключ.", "to {} ✓": "в {} ✓",
    "🔑  {} API key saved {}": "🔑  API ключът за {} е запазен {}",
    "🔑  {} API key updated — saved {}": "🔑  API ключът за {} е обновен — запазен {}",
    "{} needs an API key.": "{} изисква API ключ.", "Could not switch — staying with {}.": "Смяната не успя — оставам с {}.",
    "Staying with {} — no key was entered.": "Оставам с {} — не беше въведен ключ.",
    "The global hotkey ({}) and typing need Accessibility permission. Allow it in System Settings → Privacy & Security → Accessibility (for the app that launches NOVA), then restart NOVA.":
        "Глобалната клавишна комбинация ({}) и въвеждането на текст изискват разрешение за Accessibility. Разреши го в System Settings → Privacy & Security → Accessibility (за приложението, което стартира NOVA) и рестартирай NOVA.",
    # first-run wizard
    "AI provider": "AI доставчик", "Server address": "Адрес на сървъра", "API key": "API ключ", "Test": "Провери",
    "Read replies aloud automatically": "Чети отговорите на глас автоматично",
    "Key already saved ✓  (paste a new one to replace it)": "Ключът вече е запазен ✓  (постави нов, за да го замениш)",
    "API key (optional)": "API ключ (по избор)", "  (a key is already saved)": "  (вече има запазен ключ)",
    # settings
    "Home city": "Твоят град", "Voice engine": "Глас за четене", "Speech recognition": "Разпознаване на реч",
    "Settings sections": "Раздели на настройките", "Auto (follow system)": "Автоматично (според системата)",
    "Pick accent color": "Избери акцентен цвят", "e.g. Sofia — used for the weather": "напр. София — използва се за времето",
    "Test connection": "Провери връзката", "Several search engines (no key)": "Няколко търсачки (без ключ)",
    # the read-aloud voices (language — the voice's own name)
    "English — Aria (US)": "Английски — Aria (САЩ)", "English — Sonia (UK)": "Английски — Sonia (Великобритания)",
    "Bulgarian — Kalina": "Български — Калина", "German — Katja": "Немски — Katja", "French — Denise": "Френски — Denise",
    "Spanish — Elvira": "Испански — Elvira", "Russian — Svetlana": "Руски — Svetlana",
    # the AI providers, as the menus list them
    "Groq (free tier, fast)": "Groq (безплатен план, бърз)",
    "Ollama (runs on this Mac, private, offline)": "Ollama (работи на този Mac, лично, без интернет)",
    "Custom (any OpenAI-compatible server)": "Друг (всеки сървър, съвместим с OpenAI)",
    "Brave Search (needs a key)": "Brave Search (изисква ключ)", "Web search": "Търсене в интернет",
    "Without a key NOVA asks several search engines in turn (DuckDuckGo, Yahoo, Wikipedia and others) through an "
    "unofficial library; What NOVA sent lists each one. Brave Search is an official API and needs your own key.":
        "Без ключ NOVA пита няколко търсачки една след друга (DuckDuckGo, Yahoo, Wikipedia и други) чрез неофициална "
        "библиотека; „Какво е изпратила NOVA“ показва всяка от тях. Brave Search е официален API и изисква твой собствен ключ.",
    "Voice (TTS):": "Озвучаване (TTS):",
    "Online voices (Microsoft)": "Онлайн гласове (Microsoft)", "System voice (offline)": "Системен глас (офлайн)",
    "Online voices sound better but send the text to Microsoft's speech service (unofficial). The system voice works offline and nothing leaves this Mac.":
        "Онлайн гласовете звучат по-добре, но изпращат текста към гласовата услуга на Microsoft (неофициално). Системният глас работи офлайн и нищо не напуска този Mac.",
    "Automatic": "Автоматично", "AI provider (best quality)": "AI доставчик (най-добро качество)",
    "Offline voice model": "Офлайн гласов модел", "Listen for “Hey NOVA”": "Слушай за „Hey NOVA“",
    "Loudness threshold — lower = more sensitive (default 700). Not used by the on-device detector.":
        "Праг на силата на звука — по-ниско = по-чувствително (по подразбиране 700). Не се използва от разпознаването на устройството.",
    "Encrypt chats and memories on disk (key kept in the Keychain)": "Шифровай чатовете и спомените на диска (ключът се пази в Keychain)",
    "Encryption": "Шифроване", "Actions NOVA may do without asking": "Действия, които NOVA може да прави без да пита",
    "Remove selected": "Премахни избраното", "Allowed without asking": "Разрешено без питане", "Transparency": "Прозрачност",
    "Save a crash report when NOVA fails (stays on this Mac unless you send it)":
        "Запазвай доклад при срив на NOVA (остава на този Mac, освен ако не го изпратиш)",
    "Crash reports": "Доклади за сривове", "Your data": "Твоите данни", "Support": "Поддръжка", "Setup": "Настройка",
    "Danger zone": "Опасна зона", "General": "Общи", "AI": "AI", "Privacy": "Поверителност", "Data": "Данни",
    "Best model": "Най-добър модел", "Fast model": "Бърз модел", "Third model": "Трети модел",
    "Pick from the list, or type any model id your provider offers":
        "Избери от списъка или въведи произволен идентификатор на модел, който доставчикът ти предлага",
    "NOVA starts with the best model and switches to the fast one when it is rate-limited.":
        "NOVA започва с най-добрия модел и преминава към бързия, когато достигне лимита на заявките.",
    "On-device: the wake word is detected on this Mac and no audio is uploaded while listening.":
        "На устройството: активиращата дума се разпознава на този Mac и докато слуша, не се качва никакъв звук.",
    "Without the offline voice model, short clips of speech are sent to the AI provider to detect the wake word.":
        "Без офлайн гласовия модел кратки откъси реч се изпращат към AI доставчика, за да се разпознае активиращата дума.",
    "Not available": "Не е налично",
    "The on-device speech engine is not part of this build.": "Разпознаването на реч на устройството не е включено в тази версия.",
    "Remove": "Премахни",
    "What NOVA sent today": "Какво е изпратила NOVA днес",
    "Everything NOVA stores lives in one folder in your Library. Export makes a zip of it (without the API key); Delete removes it and the saved keys.":
        "Всичко, което NOVA пази, е в една папка в твоята Library. Експортът прави zip архив от нея (без API ключа); изтриването я премахва заедно със запазените ключове.",
    "not needed": "не е нужно", "Download ({} MB)": "Изтегли ({} MB)", "Downloading… {}%": "Изтегляне… {}%", "not set": "не е зададен",
    "Fast (recommended)": "Бързо (препоръчително)", "Balanced": "Балансирано", "Deep (slowest)": "Задълбочено (най-бавно)",
    "Auto-detect": "Автоматично разпознаване", "English": "Английски", "Bulgarian": "Български", "German": "Немски",
    "French": "Френски", "Spanish": "Испански", "Russian": "Руски",
    # approvals, plugins, activity
    "Nothing yet.": "Все още няма нищо.", "NOVA — plugin wants to load": "NOVA — добавка иска да се зареди",
    "Allow this plugin": "Разреши тази добавка", "Don't load": "Не зареждай", "Activity log": "Журнал на действията",
    "Every action NOVA took for you, whether you approved it, and how it ended.":
        "Всяко действие, което NOVA е извършила за теб, дали си го одобрил и как е завършило.",
    "It can never read NOVA's chats, memories or keys, your Library or hidden files, or start other apps.":
        "Тя никога не може да чете чатовете, спомените или ключовете на NOVA, твоята Library или скритите файлове, нито да стартира други приложения.",
    "Only allow it if you wrote it or fully trust its source.": "Разреши я само ако ти си я написал или напълно се доверяваш на източника ѝ.",
    "🔌  Plugin {} was not loaded: {}.": "🔌  Добавката {} не беше заредена: {}.",
    "🔌  Plugin {} could not be loaded - see the log.": "🔌  Добавката {} не можа да бъде заредена — виж лога.",
    "It asks for no permissions: no internet, no access to your files.": "Не иска никакви разрешения: без интернет, без достъп до файловете ти.",
    "The plugin “{}” has no MANIFEST, so it is NOT sandboxed: it can run any code on your Mac with your permissions.":
        "Добавката „{}“ няма MANIFEST, затова НЕ е изолирана: може да изпълнява всякакъв код на твоя Mac с твоите права.",
    "🔌  Plugin loaded: {}": "🔌  Добавката е заредена: {}", "sandboxed": "изолирана",
    "The plugin “{}” runs in a sandbox, separate from NOVA.": "Добавката „{}“ работи в изолирана среда (sandbox), отделно от NOVA.",
    "It asks for permission to:": "Иска разрешение да:", "Use the internet": "използва интернет",
    "Read files in Documents, Desktop, Downloads, Pictures, Music and Movies":
        "чете файлове в Documents, Desktop, Downloads, Pictures, Music и Movies",
    "Create and change files in Documents, Desktop and Downloads": "създава и променя файлове в Documents, Desktop и Downloads",
    "Always allow in {}": "Винаги разрешавай в {}", "Always allow typing in {}": "Винаги разрешавай въвеждане в {}",
    "Always allow sleep": "Винаги разрешавай приспиване", "Launch at login": "Стартирай при вход", "Volume up": "Усили звука", "Volume down": "Намали звука",
    "File changes in {}": "Промени по файлове в {}", "Typing into {}": "Въвеждане в {}",
    "Putting the Mac to sleep": "Приспиване на Mac-а", "Typing into any app": "Въвеждане във всяко приложение",
    "Creating new files / appending, anywhere": "Създаване на нови файлове / добавяне, навсякъде",
    "Run shell command": "Изпълни команда в терминала", "Run Python code": "Изпълни Python код", "Create file": "Създай файл",
    "Overwrite file": "Презапиши файл", "Append to file": "Добави към файл", "Kill process": "Прекрати процес",
    "System action": "Системно действие", "Permanently empty the Trash": "Изпразни Кошчето завинаги",
    "delete file(s)": "изтрий файл(ове)", "move file(s)": "премести файл(ове)", "rename file(s)": "преименувай файл(ове)",
    "Remember": "Запомни", "Forget memories containing": "Забрави спомените, съдържащи",
    "NOVA read web or file content earlier in this request, and such content can hide instructions. Approve only if this is what YOU asked for.":
        "По-рано в тази заявка NOVA прочете уеб или файлово съдържание, а такова съдържание може да крие инструкции. Одобри само ако ТИ си поискал това.",
    # chat
    "Select file": "Избери файл", "Short": "Кратка", "Normal": "Нормална", "Detailed": "Подробна",
    "Edit message": "Редактиране на съобщение",
    "Edit this message? It and everything after it will be removed from this chat.":
        "Да редактирам ли това съобщение? То и всичко след него ще бъде премахнато от чата.",
    "Screen Recording permission is missing - allow it in System Settings → Privacy & Security → Screen Recording, then restart NOVA.":
        "Липсва разрешение за Screen Recording — разреши го в System Settings → Privacy & Security → Screen Recording и рестартирай NOVA.",
    "Still working on your previous request - wait for it or press the stop button.": "Все още работя по предишната ти заявка - изчакай или натисни бутона за спиране.",
    "Messages in context · tokens this session: {} in / {} out": "Съобщения в контекста · токени за тази сесия: {} входящи / {} изходящи",
    "The model returned an empty reply (it may have run out of tokens). Try again or switch to 'Detailed'.":
        "Моделът върна празен отговор (може да са свършили токените). Опитай отново или превключи на „Подробна“.",
    "✅  «{}»: opening {}": "✅  «{}»: отварям {}",
    "⚠️  Shortcut «{}» must be a list of app names in config.json.": "⚠️  Пряката команда «{}» трябва да е списък с имена на приложения в config.json.",
    "⚡ {} is busy — retrying with {}...": "⚡ {} е зает — опитвам отново с {}...",
    "❌ {} is too large (max 300 MB).": "❌ {} е твърде голям (макс. 300 MB).",
    "Rate limit — wait a moment and try again.": "Лимит на заявките — изчакай малко и опитай отново.",
    "API key error — use 'Change API key' in the menu.": "Грешка с API ключа — използвай „Смени API ключа“ в менюто.",
    "Network error — check your connection.": "Мрежова грешка — провери връзката си.",
    "The AI service is having trouble — try again in a moment.": "AI услугата има затруднения — опитай отново след малко.",
    "The AI made a mistake calling one of NOVA's tools — ask again, perhaps in other words.":
        "AI сгреши при извикването на един от инструментите на NOVA — попитай отново, може би с други думи.",
    "That model is not available on this account — pick another in Settings.": "Този модел не е наличен за този акаунт — избери друг в Настройки.",
    # data
    "Export NOVA data": "Експорт на данните на NOVA", "Delete all NOVA data": "Изтриване на всички данни на NOVA",
    "This permanently deletes your chats, memories, notes, reminders, settings and the saved API key from this Mac, then quits NOVA.\n\nThis cannot be undone. Export first if unsure.":
        "Това изтрива завинаги чатовете, спомените, бележките, напомнянията, настройките и запазения API ключ от този Mac, след което затваря NOVA.\n\nДействието е необратимо. Ако не си сигурен, първо направи експорт.",
    "All NOVA data was deleted. NOVA will now quit.": "Всички данни на NOVA бяха изтрити. NOVA ще се затвори.",
    "Send crash report?": "Да изпратя ли доклада за срива?", "Send": "Изпрати", "Don't send": "Не изпращай",
    "NOVA update": "Обновление на NOVA",
    "Diagnostics copied (no keys, no chat content) - paste it into your bug report.":
        "Диагностиката е копирана (без ключове, без съдържание на чатове) — постави я в доклада за грешка.",
    "Clear memories": "Изчистване на спомените",
    "Delete all saved memories? This cannot be undone.": "Да изтрия ли всички запазени спомени? Действието е необратимо.",
    "NOVA — Notes": "NOVA — Бележки",
    "Encryption could not be turned on (the Keychain is unavailable) — new data is being stored unencrypted.":
        "Шифроването не можа да бъде включено (Keychain не е достъпен) — новите данни се пазят нешифровани.",
    "Download it now?": "Да го изтегля ли сега?",
    "Start a new chat? Current conversation will be saved to Sessions.": "Да започна ли нов чат? Текущият разговор ще бъде запазен в Сесии.",
    "⚠️  NOVA hit an unexpected error last time. A report (no chat content) was saved: {}":
        "⚠️  Последния път NOVA срещна неочаквана грешка. Запазен е доклад (без съдържание на чатове): {}",
    "Send this report to {}? This is everything that would be sent:": "Да изпратя ли този доклад към {}? Това е всичко, което ще бъде изпратено:",
    "⬇️  Downloading NOVA {}…": "⬇️  Изтеглям NOVA {}…",
    "💾  Exported {} files to {} (the API key is not included).": "💾  Експортирани са {} файла в {} (API ключът не е включен).",
    "No notes yet.": "Все още няма бележки.", "❌  Export failed: {}": "❌  Експортът не успя: {}",
    "🔒  Encryption is on — {} files are now encrypted. The key is in your Keychain.":
        "🔒  Шифроването е включено — {} файла вече са шифровани. Ключът е в твоя Keychain.",
    "🔓  Encryption is off — {} files were decrypted.": "🔓  Шифроването е изключено — {} файла бяха дешифрирани.",
    "⚠️  Could not change the encryption setting: {}": "⚠️  Настройката за шифроване не можа да бъде променена: {}",
    "NOVA {} is available (you have {}).": "Налична е NOVA {} (имаш {}).",
    "✓ Downloaded and verified: {} — drag NOVA to Applications to finish.": "✓ Изтеглено и проверено: {} — провлачи NOVA в Applications, за да завършиш.",
    "Load error: {}": "Грешка при зареждане: {}", "✓ NOVA {} is up to date.": "✓ NOVA {} е актуална.",
    "❌  Update check failed: {}": "❌  Проверката за обновления не успя: {}", "❌  Update failed: {}": "❌  Обновяването не успя: {}",
    "Error clearing memories: {}": "Грешка при изчистване на спомените: {}",
    # extras / help
    "Good morning! ☀️": "Добро утро! ☀️", "NOVA — Active Plugins & Tools": "NOVA — Активни добавки и инструменти",
    "NOVA — Keyboard Shortcuts": "NOVA — Клавишни комбинации", "Ready — what shall we start with?": "Готова съм — с какво да започнем?",
    "Top news:": "Водещи новини:", "Increase / decrease font size": "Увеличи / намали размера на шрифта",
    "Quick calculator  (e.g. = 15% of 200, = 2^10)": "Бърз калкулатор  (напр. = 15% of 200, = 2^10)",
    "Voice input — click again to stop": "Гласов вход — кликни отново за спиране",
    "Cycle response length: Short / Normal / Detailed": "Смяна на дължината на отговора: кратка / нормална / подробна",
    "Open action menu (news, clipboard, file, screen…)": "Отвори менюто с действия (новини, клипборд, файл, екран…)",
    "Regenerate last AI response": "Генерирай отново последния отговор", "Toggle shortcut panel": "Покажи / скрий панела с бързи команди",
    "Edit a sent message (removes it and the replies after it)": "Редактирай изпратено съобщение (премахва него и отговорите след него)",
    "Quit NOVA": "Изход от NOVA", "Move window": "Премести прозореца", "Resize window": "Преоразмери прозореца",
    # background workers
    "Compressing history…": "Компресирам историята…", "No audio was captured.": "Не беше записан звук.",
    "Wake word needs the offline voice model (Settings → Voice → Download) because this AI provider has no speech-to-text.":
        "Активиращата дума изисква офлайн гласовия модел (Настройки → Глас → Изтегли), защото този AI доставчик няма разпознаване на реч.",
    "Nothing was recognised.": "Нищо не беше разпознато.",
    "⚡  {} is rate-limited — using {}": "⚡  {} е с достигнат лимит — използвам {}",
    "⚡  {} is rate-limited — switching to {}": "⚡  {} е с достигнат лимит — превключвам на {}",
    "The reply was cut off before a tool call was complete. Try again, or set the response length to Detailed.":
        "Отговорът беше прекъснат, преди извикването на инструмент да завърши. Опитай отново или избери дължина на отговора „Подробна“.",
    "Microphone error: {}\nAllow microphone access in System Settings → Privacy & Security → Microphone.":
        "Грешка с микрофона: {}\nРазреши достъпа до микрофона в System Settings → Privacy & Security → Microphone.",
    "Wake word could not start ({}).": "Активиращата дума не можа да стартира ({}).",
    "Wake word disabled - cannot use the microphone ({}). Allow microphone access in System Settings → Privacy & Security → Microphone.":
        "Активиращата дума е изключена — микрофонът не може да се използва ({}). Разреши достъпа до микрофона в System Settings → Privacy & Security → Microphone.",
    "⏳  Rate limit — retrying in {}s": "⏳  Лимит на заявките — нов опит след {} сек",
})

# ── third batch: documents, Mac apps, selection actions, schedules, modes, MCP, usage, updates, games ──
BG.update({
    # document library
    "Documents": "Документи", "Add file": "Добави файл", "Add folder": "Добави папка", "Remove all": "Премахни всички",
    "No documents yet": "Все още няма документи", "passages": "откъса", "Added {} documents.": "Добавени документи: {}.",
    "Could not read:": "Не можаха да бъдат прочетени:",
    "NOVA reads these documents on this Mac. When you ask a question, only the few passages that match it are sent to the AI. You can also drop a file or a folder onto the NOVA window.":
        "NOVA чете тези документи на този Mac. Когато зададеш въпрос, към AI се изпращат само няколкото откъса, които съвпадат с него. Можеш и да пуснеш файл или папка върху прозореца на NOVA.",
    "Remove every document from NOVA? The files themselves are not touched.": "Да премахна ли всички документи от NOVA? Самите файлове не се пипат.",
    "📄  Reading {}…": "📄  Чета {}…", "📚  Reading the documents in {}…": "📚  Чета документите в {}…",
    "📚  Added {} documents from {}. Ask anything about them.": "📚  Добавени са {} документа от {}. Питай каквото искаш за тях.",
    "No readable documents were found in {}.": "В {} не бяха намерени четими документи.",
    "{} could not be read.": "{} не можаха да бъдат прочетени.",
    "{} more were left out (too many files).": "Още {} бяха пропуснати (твърде много файлове).",
    "📚  {} is now in your documents ({} passages). Only the parts that match a question are sent to the AI.":
        "📚  {} вече е в документите ти ({} откъса). Към AI се изпращат само частите, които съвпадат с въпроса.",
    "It is very long, so only the first part was read.": "Документът е много дълъг, затова е прочетена само първата част.",
    # selected text in any app
    "Explain": "Обясни", "Summarize": "Обобщи", "Translate": "Преведи", "Rewrite": "Пренапиши", "Fix grammar": "Поправи граматиката",
    "Ask NOVA about it": "Попитай NOVA за това", "Selected text": "Избран текст",
    "Select some text first, then press {}.": "Първо избери текст, после натисни {}.",
    "Press {} in any app to explain, translate or rewrite the selected text": "Натисни {} във всяко приложение, за да обясниш, преведеш или пренапишеш избрания текст",
    "📋  Copied — press {} in the other app to paste it over your selection.": "📋  Копирано — натисни {} в другото приложение, за да го поставиш върху избраното.",
    "My actions": "Моите действия", "Selected-text actions": "Действия с избран текст", "Selected-text action": "Действие с избран текст",
    "Name (shown in the menu)": "Име (показва се в менюто)", "What NOVA should do with the text": "Какво да направи NOVA с текста",
    "The answer replaces the selected text (rewrites, translations)": "Отговорът заменя избрания текст (пренаписване, превод)",
    "Your own actions for the menu that {} opens on selected text. The selected text is added after your instruction.":
        "Твоите собствени действия за менюто, което {} отваря върху избран текст. Избраният текст се добавя след твоята инструкция.",
    "replaces the selection": "заменя избраното",
    "Paste rewrites and translations straight over the selection (otherwise they are only copied)":
        "Поставяй пренаписаното и преводите направо върху избраното (иначе само се копират)",
    "📋  Pasted over your selection (it is also on the clipboard).": "📋  Поставено върху избраното (има го и в клипборда).",
    # the Crafted look: action rows and the new window
    'Used tool': 'Използван инструмент',
    'Yesterday': 'Вчера',
    '{} action': '{} действие',
    '{} actions': '{} действия',
    'Failed': 'Неуспешно',
    'Enter sends · Shift+Enter starts a new line': 'Enter изпраща · Shift+Enter започва нов ред',
    'Mode and model': 'Режим и модел',
    'Keep on top': 'Дръж най-отгоре',
    'Do not keep on top': 'Не дръж най-отгоре',
    'Stop': 'Спри',
    'Opened app': 'Отворено приложение',
    'Opened page': 'Отворена страница',
    'Opened Maps': 'Отворени Карти',
    'Searched Google': 'Търсене в Google',
    'Searched the web': 'Търсене в интернет',
    'Read page': 'Прочетена страница',
    'Ran command': 'Изпълнена команда',
    'Ran Python': 'Изпълнен Python',
    'Took screenshot': 'Направена снимка на екрана',
    'Typed text': 'Въведен текст',
    'Emptied Trash': 'Изпразнено кошче',
    'Checked system': 'Проверена система',
    'Saved note': 'Запазена бележка',
    'Read notes': 'Прочетени бележки',
    'Reminder': 'Напомняне',
    'Remembered': 'Запомнено',
    'Checked memory': 'Проверена памет',
    'Forgot': 'Забравено',
    'Wrote file': 'Записан файл',
    'Searched files': 'Търсене във файлове',
    'Read file': 'Прочетен файл',
    'Showed in Finder': 'Показано във Finder',
    'Read clipboard': 'Прочетен клипборд',
    'Copied to clipboard': 'Копирано в клипборда',
    'Listed running apps': 'Работещи приложения',
    'Stopped app': 'Спряно приложение',
    'Checked battery': 'Проверена батерия',
    'Checked network': 'Проверена мрежа',
    'Sent notification': 'Изпратено известие',
    'Set wallpaper': 'Сменен тапет',
    'Listed shortcuts': 'Преки пътища',
    'Ran shortcut': 'Изпълнен пряк път',
    'Scheduled': 'Планирано',
    'Checked schedule': 'Проверен график',
    'Cancelled task': 'Отменена задача',
    'Searched documents': 'Търсене в документите',
    'Listed documents': 'Списък с документи',
    'Added document': 'Добавен документ',
    'Removed document': 'Премахнат документ',
    'Checked calendar': 'Проверен календар',
    'Added event': 'Добавено събитие',
    'Checked reminders': 'Проверени напомняния',
    'Added reminder': 'Добавено напомняне',
    'Read email': 'Прочетен имейл',
    'Drafted email': 'Чернова на имейл',
    'Drafted reply': 'Чернова на отговор',
    'Read browser page': 'Прочетена страница в браузъра',
    'Moved to Trash': 'Преместено в кошчето',
    'Moved': 'Преместено',
    'Copied': 'Копирано',
    'Renamed': 'Преименувано',
    'Listed folder': 'Съдържание на папка',
    'Created folder': 'Създадена папка',
    'Files': 'Файлове',
    'Muted': 'Без звук',
    'Unmuted': 'Звукът е включен',
    'Volume set': 'Зададена сила на звука',
    'Checked volume': 'Проверена сила на звука',
    'Volume': 'Сила на звука',
    'Shutting down': 'Изключване',
    'Restarting': 'Рестартиране',
    'Sleep': 'Заспиване',
    'Locked the screen': 'Заключен екран',
    'Cancelled shutdown': 'Отменено изключване',
    'System': 'Система',
    'Play / pause': 'Пусни / пауза',
    'Next track': 'Следваща песен',
    'Previous track': 'Предишна песен',
    'Spotify': 'Spotify',
    'Searching the web': 'Търся в интернет',
    'Reading the page': 'Чета страницата',
    'Checking the weather': 'Проверявам времето',
    'Reading the file': 'Чета файла',
    'Looking through your files': 'Преглеждам файловете ти',
    'Searching your documents': 'Търся в документите ти',
    'Reading the document': 'Чета документа',
    'Running a command': 'Изпълнявам команда',
    'Running code': 'Изпълнявам код',
    'Checking your calendar': 'Проверявам календара ти',
    'Checking your reminders': 'Проверявам напомнянията ти',
    'Reading the email': 'Чета имейла',
    'Running the shortcut': 'Изпълнявам прекия път',
    'Taking a screenshot': 'Правя снимка на екрана',
    'Working': 'Работя',
    'NOVA has a new look: calmer colours, sharper details, and line icons instead of emoji.': 'NOVA има нов облик: по-спокойни цветове, по-ясни детайли и линейни икони вместо емоджи.',
    'Under each reply you now see what NOVA did, as neat rows you can click for details.': 'Под всеки отговор вече виждаш какво е направила NOVA — като спретнати редове, върху които можеш да кликнеш за подробности.',
    'The red, yellow and green window buttons hide NOVA, shrink it to a bubble, or fill the screen.': 'Червеният, жълтият и зеленият бутон на прозореца скриват NOVA, свиват я до балонче или я разгръщат на цял екран.',
    'Pick a look in Settings → General: Paper or Sage (light), Graphite or Espresso (dark), or follow the system.': 'Избери облик в Настройки → Общи: Paper или Sage (светли), Graphite или Espresso (тъмни) или следвай системата.',
    'Paper': 'Paper',
    'Graphite': 'Graphite',
    'Sage': 'Sage',
    'Espresso': 'Espresso',
    "Show / hide NOVA from anywhere": "Покажи / скрий NOVA отвсякъде",
    # MCP tool servers, Shortcuts, requests from other apps
    "🔌  Tool servers (MCP)": "🔌  Сървъри с инструменти (MCP)", "Tool servers (MCP)": "Сървъри с инструменти (MCP)",
    "More tools": "Още инструменти", "Add a tool server": "Добави сървър с инструменти",
    "🔌  {} is connected: {} tools.": "🔌  {} е свързан: {} инструмента.",
    "⚠️  The tool server “{}” could not be connected: {}": "⚠️  Сървърът с инструменти „{}“ не можа да бъде свързан: {}",
    "A tool server is a program that runs on your Mac with your permissions, or a web service that receives what NOVA sends it. Only add servers you trust.":
        "Сървърът с инструменти е програма, която работи на твоя Mac с твоите права, или уеб услуга, която получава това, което NOVA ѝ изпраща. Добавяй само сървъри, на които имаш доверие.",
    "Command or web address": "Команда или уеб адрес", "Settings (KEY=value, one per line)": "Настройки (КЛЮЧ=стойност, по една на ред)",
    "for a web address: Authorization=Bearer …": "за уеб адрес: Authorization=Bearer …",
    "Give the server a name and a command or web address.": "Дай име на сървъра и команда или уеб адрес.",
    "MCP servers give NOVA extra tools - for GitHub, Notion, databases, your files and much more. NOVA asks before it uses a server's tool for the first time, and treats what a server returns as untrusted.":
        "MCP сървърите дават на NOVA допълнителни инструменти — за GitHub, Notion, бази данни, твоите файлове и още много. NOVA пита, преди да използва инструмент на сървър за първи път, и приема върнатото от сървъра като ненадеждно.",
    "Paste JSON": "Постави JSON", "Paste the server definition (the “mcpServers” JSON many apps use):": "Постави дефиницията на сървъра (JSON-ът „mcpServers“, който ползват много приложения):",
    "connected, {} tools": "свързан, {} инструмента", "could not be connected": "не можа да бъде свързан", "connecting": "свързване",
    "connects when you save": "ще се свърже, когато запазиш", "No tool servers yet": "Все още няма сървъри с инструменти", "Added: {}": "Добавени: {}",
    "Always allow {}": "Винаги разрешавай {}", "Connected server tool: {}": "Инструмент от свързан сървър: {}",
    "Always allow the shortcut “{}”": "Винаги разрешавай командата „{}“", "Running the shortcut “{}”": "Изпълнение на командата „{}“",
    "Other apps": "Други приложения",
    "Send requests from Shortcuts and nova:// links right away, without me pressing Enter": "Изпращай заявките от Shortcuts и nova:// връзки веднага, без да натискам Enter",
    "↪  Received from another app — check the text below and press Enter to send it.": "↪  Получено от друго приложение — провери текста по-долу и натисни Enter, за да го изпратиш.",
    "Find memories by meaning (asks the AI once for keywords when a memory is saved)": "Намирай спомените по смисъл (пита AI веднъж за ключови думи при запазване на спомен)",
    "Reading scanned page {} of {}…": "Чета сканирана страница {} от {}…",
    "At login, start in the menu bar without opening the window (scheduled tasks and the hotkey still work)":
        "При вход стартирай в лентата с менюта, без да отваряш прозореца (планираните задачи и клавишната комбинация работят)",
    "Tip: turn on “Launch at login” in Settings → General and NOVA waits in the menu bar, so these run without you opening it.":
        "Съвет: включи „Стартирай при вход“ в Настройки → Общи и NOVA ще чака в лентата с менюта, така че задачите да се изпълняват, без да я отваряш.",
    "📚  Documents brought up to date: {} changed, {} new.": "📚  Документите са обновени: {} променени, {} нови.",
    "the file is no longer there": "файлът вече го няма",
    # what's new
    "What's new in NOVA {}": "Какво ново в NOVA {}", "What's new": "Какво ново",
    "Nothing new to report for this version.": "За тази версия няма нищо ново за отбелязване.",
    "Ask about your calendar, reminders and mail — NOVA can add events and draft replies (you press Send).":
        "Питай за календара, напомнянията и пощата си — NOVA може да добавя събития и да подготвя отговори (ти натискаш „Изпрати“).",
    "Drop a PDF, Word or Excel file, or a whole folder, onto NOVA and ask about it. Scanned pages are read too.":
        "Пусни PDF, Word или Excel файл, или цяла папка, върху NOVA и питай за тях. Чете и сканирани страници.",
    "Select text in any app and press ⌃⇧Space to explain, translate or rewrite it.":
        "Избери текст във всяко приложение и натисни ⌃⇧Space, за да го обясниш, преведеш или пренапишеш.",
    "Say “every morning at 8 give me the news” and NOVA schedules it (＋ → Scheduled tasks).":
        "Кажи „всяка сутрин в 8 ми дай новините“ и NOVA ще го планира (＋ → Планирани задачи).",
    "＋ → Voice conversation lets you talk hands-free; ＋ → Mode switches between Coder, Translator, Tutor and Writer.":
        "＋ → Гласов разговор ти позволява да говориш без ръце; ＋ → Режим превключва между Програмист, Преводач, Учител и Писател.",
    "Type /tldr, /eli5 or /fix before a text to reuse a prompt — or save your own.":
        "Напиши /tldr, /eli5 или /fix преди текст, за да използваш готова подкана — или запази свои.",
    "Connect tool servers (MCP) and run your Apple Shortcuts from NOVA.":
        "Свържи сървъри с инструменти (MCP) и пускай своите Apple Shortcuts от NOVA.",
    "Choose your AI in Settings → AI: Groq, Claude, OpenAI, or Ollama running on this Mac.":
        "Избери своя AI в Настройки → AI: Groq, Claude, OpenAI или Ollama, работещ на този Mac.",
    "Settings → Privacy: encrypt what NOVA stores, and see everything it sent.":
        "Настройки → Поверителност: шифровай това, което NOVA пази, и виж всичко, което е изпратила.",
    # games
    "NOVA — Wordle": "NOVA — Wordle", "NOVA — Number Guesser": "NOVA — Познай числото", "Number Guesser": "Познай числото",
    "Stats": "Статистика", "Wordle Stats": "Статистика за Wordle", "Number Guesser Stats": "Статистика за „Познай числото“",
    "{}  |  Played: {}  |  Win: {}%  |  Streak: {}  |  Best: {}": "{}  |  Изиграни: {}  |  Победи: {}%  |  Серия: {}  |  Рекорд: {}",
    "✓ Already solved today!  Streak: {}": "✓ Днешната дума вече е позната!  Серия: {}",
    "❌ The word was: {}  —  next word in {}": "❌ Думата беше: {}  —  следваща дума след {}",
    "Not enough letters": "Недостатъчно букви", "Not in the word list": "Няма такава дума в списъка",
    "Streak: {}  —  next word in {}": "Серия: {}  —  следваща дума след {}",
    "Genius!": "Гениално!", "Magnificent!": "Великолепно!", "Impressive!": "Впечатляващо!",
    "Splendid!": "Чудесно!", "Great!": "Браво!", "Phew!": "На косъм!",
    "Played: {}\nWin %: {}%\nCurrent streak: {}\nBest streak: {}": "Изиграни: {}\nПобеди: {}%\nТекуща серия: {}\nНай-добра серия: {}",
    "Guess distribution:": "Разпределение на опитите:", "Next word in: {}": "Следваща дума след: {}",
    "Tries left: {}": "Оставащи опити: {}", "Solved in {} tries": "Познато с {} опита", "Better luck tomorrow!": "Повече късмет утре!",
    "✓ Already played today!  Streak: {}": "✓ Днес вече игра!  Серия: {}",
    "❌ It was {}  —  next in {}": "❌ Числото беше {}  —  следващо след {}",
    "Guess a number between 1 and 100": "Познай число между 1 и 100", "Your guess...": "Твоето предположение...",
    "Enter a number!": "Въведи число!", "Between 1 and 100!": "Между 1 и 100!",
    "Correct!  Streak: {}": "Позна!  Серия: {}", "Next number in {}": "Следващо число след {}",
    "Out of tries!": "Опитите свършиха!", "Too low — go higher": "Твърде малко — по-голямо", "Too high — go lower": "Твърде голямо — по-малко",
    "Wordle  (daily word)": "Wordle  (дума на деня)", "Number Guesser  (daily)": "Познай числото  (всеки ден)",
    "next in {}": "следващо след {}", "Streaks: Wordle {} ({})  ·  Number Guesser {} ({})": "Серии: Wordle {} ({})  ·  Познай числото {} ({})",
    # updates
    "Install it now? NOVA will restart.": "Да го инсталирам ли сега? NOVA ще се рестартира.",
    "✓ NOVA {} was installed. It is used the next time you start NOVA.": "✓ NOVA {} беше инсталирана. Ще се използва при следващото стартиране на NOVA.",
    "✓ NOVA {} is installed — restarting…": "✓ NOVA {} е инсталирана — рестартирам…",
    "Updates": "Обновления", "Tell me when there is a new version": "Кажи ми, когато има нова версия",
    "Install new versions by themselves": "Инсталирай новите версии автоматично", "Do not check": "Не проверявай",
    "NOVA checks your own update address once a day.": "NOVA проверява твоя адрес за обновления веднъж на ден.",
    "NOVA checks its releases on GitHub once a day and verifies every download before installing it.":
        "NOVA проверява версиите си в GitHub веднъж на ден и проверява всяко изтегляне, преди да го инсталира.",
    "This NOVA runs from source: update it with git pull. Check for updates still shows if there is a new release.":
        "Тази NOVA работи от изходния код: обновявай я с git pull. „Провери за обновления“ пак показва дали има нова версия.",
    # usage and cost
    "Usage and cost": "Използване и разходи", "Usage": "Използване", "Provider": "Доставчик", "Tokens in": "Входящи токени",
    "Tokens out": "Изходящи токени", "Est. cost": "Прибл. разход", "Last 12 months": "Последните 12 месеца",
    "Set price for the selected model": "Задай цена за избрания модел", "Price": "Цена", "No requests in this period.": "Няма заявки за този период.",
    "{} requests · {} tokens in · {} tokens out · about {}": "{} заявки · {} входящи токена · {} изходящи токена · около {}",
    "No price is set for: {} (not included in the total).": "Няма зададена цена за: {} (не е включено в общата сума).",
    "Price for {} in USD per million tokens, as input / output (for example 4 / 20):": "Цена за {} в USD за милион токена, като вход / изход (например 4 / 20):",
    "Enter two numbers, for example 4 / 20.": "Въведи две числа, например 4 / 20.",
    "Tokens are counted from what each AI provider reports. The cost is only an estimate from the prices per million tokens set here - your provider's bill is what counts. Models running on this Mac are free.":
        "Токените се броят според това, което отчита всеки AI доставчик. Разходът е само приблизителна оценка по цените за милион токена, зададени тук — меродавна е сметката от доставчика. Моделите, които работят на този Mac, са безплатни.",
    # modes and saved prompts
    "🎭  Mode": "🎭  Режим", "🎭  Mode: {}": "🎭  Режим: {}", "💬  Saved prompts": "💬  Запазени подкани",
    "Assistant": "Асистент", "Coder": "Програмист", "Translator": "Преводач", "Tutor": "Учител", "Writer": "Писател",
    "Edit modes and prompts": "Редактирай режимите и подканите", "Modes and saved prompts": "Режими и запазени подкани",
    "Saved prompts": "Запазени подкани", "My modes": "Моите режими", "Saved prompt": "Запазена подкана", "Mode": "Режим",
    "Name (used as /name)": "Име (ползва се като /име)", "Prompt": "Подкана", "Name": "Име", "How NOVA should behave": "Как да се държи NOVA",
    "none yet": "все още няма", "💬  Saved prompts: {}": "💬  Запазени подкани: {}",
    "Type /name followed by your text. Add your own under ＋ → Saved prompts.": "Напиши /име и след това своя текст. Добави свои от ＋ → Запазени подкани.",
    "Reusable prompts. Type /name in the message box, followed by your text.": "Подкани за многократна употреба. Напиши /име в полето за съобщение, последвано от своя текст.",
    "Your own modes, next to Coder, Translator, Tutor and Writer. A mode tells NOVA how to behave until you switch back.":
        "Твои собствени режими, наред с Програмист, Преводач, Учител и Писател. Режимът казва на NOVA как да се държи, докато не го смениш.",
    # hands-free voice conversation
    "🎧  Voice conversation": "🎧  Гласов разговор", "🎧  End voice conversation": "🎧  Край на гласовия разговор",
    "🎧  Voice conversation ended.": "🎧  Гласовият разговор приключи.",
    "🎧  Voice conversation ended (it was quiet).": "🎧  Гласовият разговор приключи (беше тихо).",
    "🎧  Voice conversation is on — just talk. Say “stop listening” or tap the mic to end. You can talk over NOVA to interrupt it.":
        "🎧  Гласовият разговор е включен — просто говори. Кажи „stop listening“ или „стоп“, или докосни микрофона, за да приключиш. Можеш да говориш върху NOVA, за да я прекъснеш.",
    "Voice input is not available: this AI provider has no speech-to-text and the offline voice model is not installed (Settings → Voice).":
        "Гласовият вход не е наличен: този AI доставчик няма разпознаване на реч, а офлайн гласовият модел не е инсталиран (Настройки → Глас).",
    "✂️  Analyze part of the screen": "✂️  Анализирай част от екрана", "Part of the screen": "Част от екрана",
    "Conversation": "Разговор", "In a voice conversation, let me interrupt NOVA by talking": "В гласов разговор мога да прекъсна NOVA, като заговоря",
    # scheduled tasks
    "⏰  Scheduled tasks": "⏰  Планирани задачи", "Scheduled tasks": "Планирани задачи", "New scheduled task": "Нова планирана задача",
    "⏰  Scheduled ({}):": "⏰  Планирано ({}):", "Kind": "Вид", "Time": "Час", "Repeat": "Повторение",
    "Ask NOVA (it answers at that time)": "Попитай NOVA (отговаря в този час)", "Reminder (just show the text)": "Напомняне (само показва текста)",
    "e.g. Give me today's news and the weather": "напр. Дай ми днешните новини и времето",
    "Every day": "Всеки ден", "Weekdays (Mon–Fri)": "Делнични дни (пон–пет)", "Weekends": "Уикенди", "Once": "Веднъж", "Chosen days": "Избрани дни",
    "Mon": "Пон", "Tue": "Вт", "Wed": "Ср", "Thu": "Чет", "Fri": "Пет", "Sat": "Съб", "Sun": "Нед",
    "every day at {}": "всеки ден в {}", "every weekday at {}": "всеки делничен ден в {}", "at weekends at {}": "през уикендите в {}",
    "once on {} at {}": "веднъж на {} в {}", "every {} at {}": "всеки {} в {}",
    "next: {}": "следващо: {}", "turned off": "изключено", "Turn off / on": "Изключи / включи", "Nothing is scheduled": "Няма нищо планирано",
    "NOVA runs these while it is open. If it was closed at the set time, a task still runs when you open NOVA within a few hours. You can also just ask: “every morning at 8 give me the news”.":
        "NOVA ги изпълнява, докато е отворена. Ако е била затворена в зададения час, задачата пак се изпълнява, когато отвориш NOVA до няколко часа след това. Можеш и просто да кажеш: „всяка сутрин в 8 ми дай новините“.",
    "Explain, translate or rewrite the text selected in any app": "Обясни, преведи или пренапиши текста, избран във всяко приложение",
    # answers the AI worker writes itself
    "The AI declined this request. Try rephrasing it, or switch the model in the menu.":
        "AI отказа тази заявка. Опитай да я кажеш по друг начин или смени модела от менюто.",
    "(Safety category: {})": "(Категория за безопасност: {})",
    "I stopped after {} steps without finishing. Try splitting the request into smaller ones.":
        "Спрях след {} стъпки, без да завърша. Опитай да разделиш заявката на по-малки.",
    "The AI declined to analyse this image.": "AI отказа да анализира това изображение.",
    "No image-capable model is available with this AI provider.": "Тази AI услуга няма модел, който разбира изображения.",
    "Image analysis is rate-limited - try again in {}s.": "Анализът на изображения е ограничен за момента — опитай пак след {} с.",
    "Image analysis is rate-limited - try again shortly.": "Анализът на изображения е ограничен за момента — опитай пак след малко.",
    "{} did not accept the API key - it may have expired or been revoked. Get a new one at {}, then choose ≡ → Change API key.":
        "{} не прие API ключа - може да е изтекъл или отменен. Вземи нов от {} и после избери ≡ → Смени API ключа.",
    "Looking at the image": "Разглеждам изображението",
    "NOVA — click to expand": "NOVA — кликни, за да се отвори",
    "Built-in tools ({}):": "Вградени инструменти ({}):", "Plugin tools ({}):": "Инструменти от добавки ({}):",
    "no permissions": "без разрешения", "NOT sandboxed (no MANIFEST)": "НЕ е в пясъчник (няма MANIFEST)",
    "Plugin files: {}": "Файлове с добавки: {}", "No plugins loaded.": "Няма заредени добавки.",
    "Drop .py files into: {}": "Сложи .py файлове в: {}",
    "NOVA {} is on GitHub (you have {}). This NOVA runs from its source code: update it with git pull in its folder.":
        "NOVA {} е в GitHub (ти имаш {}). Тази NOVA работи от изходния си код: обнови я с git pull в папката ѝ.",
    "1 message": "1 съобщение", "{} messages": "{} съобщения", "{} tokens": "{} токена",
    # speech on this Mac (Settings → Voice)
    "On this Mac (offline)": "На този Mac (офлайн)",
    "Automatic uses the speech model on this Mac when you have downloaded it (any language, nothing leaves the Mac), otherwise the AI provider's, otherwise the small English model. On this Mac never sends your voice anywhere.":
        "Автоматично използва гласовия модел на този Mac, ако си го изтеглил (всеки език, нищо не напуска Mac-а), иначе този на AI доставчика, иначе малкия английски модел. „На този Mac“ никога не изпраща гласа ти.",
    "Any language, on this Mac:": "Всеки език, на този Mac:",
    "Wake word, on this Mac:": "Активираща дума, на този Mac:",
    "Installed ✓ — Bulgarian, English and 97 more languages are recognised on this Mac. Nothing you say leaves it.":
        "Инсталиран ✓ — български, английски и още 97 езика се разпознават на този Mac. Нищо от казаното не го напуска.",
    "Recognises Bulgarian, English and 97 more languages on this Mac, as well as the cloud does (it is the same model), with no audio leaving it.":
        "Разпознава български, английски и още 97 езика на този Mac толкова добре, колкото облакът (моделът е същият), без звукът да го напуска.",
    "Installed ✓ — the wake word (and English speech) work offline.": "Инсталиран ✓ — активиращата дума (и английската реч) работят офлайн.",
    "Lets the “Hey NOVA” wake word (and English speech) work on this Mac, with no audio leaving it.":
        "Позволява активиращата дума „Hey NOVA“ (и английската реч) да работят на този Mac, без звукът да го напуска.",
    "New line": "Нов ред", "Length": "Дължина", "Double-click": "Двойно щракване",
    "Drag the title bar": "Влачене на заглавната лента", "Drag a corner": "Влачене на ъгъл",
    "The menu: new chat, sessions, theme, model, settings": "Менюто: нов чат, сесии, тема, модел, настройки",
    # what's new in 6.6
    "“Quit Safari” now quits an app the way ⌘Q does, so it can ask you to save first.":
        "„Затвори Safari“ вече затваря програмата като ⌘Q, така че тя може първо да те попита дали да запази.",
    "With Search by meaning installed, NOVA also picks the memories that fit your question, even when you said it in other words.":
        "С инсталираното Търсене по смисъл NOVA избира и спомените, които пасват на въпроса ти, дори ако си ги казал с други думи.",
    "“Forget …” finds the memory even when you word it differently, and file requests like “Desktop/notes.txt” mean your own Desktop.":
        "„Забрави …“ намира спомена, дори да го кажеш с други думи, а заявки за файлове като „Desktop/notes.txt“ означават твоя собствен Desktop.",
    "Small offline models (Ollama, LM Studio) work better: when one writes a command out instead of running it, NOVA runs it, with the usual checks.":
        "Малките офлайн модели (Ollama, LM Studio) работят по-добре: когато някой напише командата като текст, вместо да я изпълни, NOVA я изпълнява, със същите проверки.",
    # what's new in 6.5
    "Speak Bulgarian, English or 97 more languages with nothing leaving your Mac: Settings → Voice → Any language, on this Mac (a one-time 574 MB download).":
        "Говори на български, английски или още 97 езика, без нищо да напуска Mac-а ти: Настройки → Гласов вход → Всеки език, на този Mac (еднократно изтегляне от 574 MB).",
    "While NOVA works, the line under your message says what it is doing, and replies no longer jump when they finish.":
        "Докато NOVA работи, редът под съобщението ти казва какво прави, а отговорите вече не подскачат, когато свършат.",
    "If your AI service refuses the API key, NOVA tells you where to get a new one.":
        "Ако AI услугата откаже API ключа, NOVA ти казва откъде да вземеш нов.",
    # what's new in 6.4
    "NOVA keeps itself up to date: once a day it looks for a new version and, when you agree, installs it (Settings → Data).":
        "NOVA се обновява сама: веднъж на ден проверява за нова версия и, ако се съгласиш, я инсталира (Настройки → Данни).",
    "The setup wizard and every settings window are fully in Bulgarian, and check boxes now show a tick.":
        "Първоначалната настройка и всички прозорци с настройки са изцяло на български, а отметките вече показват ✓.",
    "The scheduled-task window is easier to use: the weekdays appear only when you choose days.":
        "Прозорецът за планирани задачи е по-удобен: дните от седмицата се показват само когато избираш дни.",
    # what's new in 6.3
    "Search your documents by meaning: ＋ → Documents → Search by meaning (a one-time 135 MB download). A question then also finds passages that say the same thing in other words or in another language.":
        "Търси в документите си по смисъл: ＋ → Документи → Търсене по смисъл (еднократно изтегляне от 135 MB). Тогава въпросът намира и откъси, които казват същото с други думи или на друг език.",
    "NOVA starts about a third faster, and quits at once.": "NOVA се стартира с около една трета по-бързо и се затваря веднага.",
    "Short messages stay on one line, and long chats no longer leave an empty gap under the last message.":
        "Кратките съобщения остават на един ред, а дългите разговори вече не оставят празно място под последното съобщение.",
    "Auto (system)": "Автоматично (като системата)",
    "On this Mac with the offline voice model, otherwise through the AI provider.":
        "На този Mac с офлайн гласовия модел, иначе чрез AI доставчика.",
    "With Microsoft's online voices; Settings → Voice can use the Mac's own voice instead.":
        "С онлайн гласовете на Microsoft; в Настройки → Гласов вход можеш да избереш гласа на Mac.",
    # first-run wizard
    "{} runs AI models on this Mac - nothing you type leaves your computer, and it works offline. Install it from {}, download a model (for example {}), then press Test.":
        "{} изпълнява AI модели на този Mac - нищо от написаното не напуска компютъра ти и работи без интернет. Инсталирай го от {}, изтегли модел (например {}) и натисни Провери.",
    "Any server that speaks the OpenAI chat API (LM Studio, a company gateway…). Enter its address; the key is optional.":
        "Всеки сървър, който поддържа чат API на OpenAI (LM Studio, фирмен шлюз…). Въведи адреса му; ключът не е задължителен.",
    "NOVA will use {} to think. Create an API key at {} and paste it below. It is stored in your {}, never in a plain file.":
        "NOVA ще мисли с {}. Създай API ключ на {} и го постави отдолу. Пази се в {}, никога в обикновен файл.",
    "Everything here is optional - NOVA works without it, and macOS only asks when a feature needs it. Grant what you want to use:":
        "Всичко тук е по избор - NOVA работи и без него, а macOS пита само когато дадена функция има нужда. Разреши каквото ще ползваш:",
    "Accessibility": "Достъпност", "Screen Recording": "Запис на екрана", "Microphone": "Микрофон",
    "global hotkey, typing into other apps, lock screen": "глобална клавишна комбинация, писане в други приложения, заключване на екрана",
    "“look at my screen” and screenshots": "„погледни екрана ми“ и екранни снимки",
    "voice input and the wake word": "гласов вход и активиращата дума",
    "Show or hide NOVA anywhere with {}": "Покажи или скрий NOVA отвсякъде с {}",
    "Type a question, or press the microphone button to speak": "Напиши въпрос или натисни бутона с микрофона, за да говориш",
    "Start a message with {} for a quick calculation (e.g. {})": "Започни съобщение с {} за бързо пресмятане (напр. {})",
    "New chat: {} · Settings: the menu at the top right": "Нов чат: {} · Настройки: менюто горе вдясно",
    "NOVA asks before it runs commands, deletes files or types for you.": "NOVA пита, преди да изпълни команди, да изтрие файлове или да пише вместо теб.",
    "You can re-run this setup, export your data or delete everything from Settings at any time.":
        "Можеш да пуснеш тази настройка отново, да експортираш данните си или да изтриеш всичко от Настройки по всяко време.",
    # search by meaning (Documents)
    "Search by meaning": "Търсене по смисъл",
    "Search by meaning is not part of this build.": "Търсенето по смисъл не е включено в тази версия.",
    "Search by meaning is on: a question also finds passages that say the same thing in other words or in another language.":
        "Търсенето по смисъл е включено: въпросът намира и откъси, които казват същото с други думи или на друг език.",
    "Search by meaning finds passages that say the same thing in other words or in another language. It works on this Mac after a one-time download.":
        "Търсенето по смисъл намира откъси, които казват същото с други думи или на друг език. Работи на този Mac след еднократно изтегляне.",
    "Remove search by meaning? NOVA then finds passages by their words only. You can download it again at any time.":
        "Да се премахне ли търсенето по смисъл? Тогава NOVA ще намира откъси само по думите им. Можеш да го изтеглиш отново по всяко време.",
    "Preparing your documents for search by meaning… {}%": "Подготвям документите ти за търсене по смисъл… {}%",
    "Search by meaning could not be set up: {}": "Търсенето по смисъл не можа да се настрои: {}",
    "The download was cancelled.": "Изтеглянето беше прекъснато.",
    "The downloaded model is corrupt or was tampered with (checksum mismatch).":
        "Изтегленият модел е повреден или подменен (контролната сума не съвпада).",
})

TABLES = {"bg": BG}


def system_language() -> str:
    try:
        from PySide6.QtCore import QLocale
        return "bg" if QLocale.system().name().lower().startswith("bg") else "en"
    except Exception:
        return "en"


def set_language(code: str) -> str:
    """'auto' follows the system; returns the language actually used."""
    global _LANG
    code = system_language() if code in (None, "", "auto") else code
    _LANG = code if code in SUPPORTED else "en"
    return _LANG


def language() -> str:
    return _LANG


_qt_translator = None


def install_qt_translations(app=None) -> bool:
    """Qt's own words in the interface language: standard buttons (Save, Cancel, Yes, No), the right-click menu of
    text fields (Copy, Paste, Select All) and file dialogs. They come with Qt as qtbase_<lang>.qm. True if loaded."""
    global _qt_translator
    from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator
    app = app or QCoreApplication.instance()
    if app is None: return False
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator); _qt_translator = None
    if _LANG == "en": return False
    tr_ = QTranslator(app)
    if not tr_.load(f"qtbase_{_LANG}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)): return False
    app.installTranslator(tr_); _qt_translator = tr_
    return True


_EDGE = re.compile(r"^([^\w{]*)(.*?)([^\w}]*)$", re.DOTALL)


def _edges(text: str) -> tuple:
    """(leading symbols, the words, trailing symbols) - the pattern always matches."""
    m = _EDGE.match(text)
    return m.groups() if m else ("", text, "")


def translated(text: str, lang: str = "bg") -> bool:
    """True if `text` has an entry in the given language (same lookup rules as tr)."""
    table = TABLES.get(lang) or {}
    if text in table: return True
    pre, core, post = _edges(text)
    return (core + post) in table or core in table


def _lookup(text: str) -> str:
    table = TABLES.get(_LANG)
    if not table or not text:
        return text
    if text in table:
        return table[text]
    pre, core, post = _edges(text)
    if core + post in table:                       # key keeps its own trailing punctuation ("listening...")
        return pre + table[core + post]
    if core in table:
        return pre + table[core] + post
    return text


def tr(text: str, windows: bool | None = None) -> str:
    """The text in the interface language and in this system's words. `windows` forces the system for the tests."""
    if (ON_WINDOWS if windows is None else windows) and text in _WINDOWS_TEXTS:
        en, bg = _WINDOWS_TEXTS[text]
        return bg if _LANG == "bg" else en
    return local(_lookup(text), windows)


# ── this system's words ────────────────────────────────────────────
ON_WINDOWS = sys.platform == "win32"

# Whole texts that describe something Windows does differently (English text -> English, Bulgarian).
# An empty pair means "does not apply on Windows": the line is left out there (see whatsnew.py).
_WINDOWS_TEXTS = dict((
    ("Connect tool servers (MCP) and run your Apple Shortcuts from NOVA.",
     ("Connect tool servers (MCP) to give NOVA more tools.",
         "Свържи сървъри с инструменти (MCP), за да дадеш на NOVA още инструменти.")),
    ("Ask about your calendar, reminders and mail — NOVA can add events and draft replies (you press Send).",
     ("", "")),
    ("“Quit Safari” now quits an app the way ⌘Q does, so it can ask you to save first.",
     ("“Quit Notepad” now closes a program the way its close button does, so it can ask you to save first.",
         "„Затвори Notepad“ вече затваря програмата като бутона ѝ за затваряне, така че тя може първо да те попита дали да запази.")),
    ("Send requests from Shortcuts and nova:// links right away, without me pressing Enter",
     ("Send requests from other programs and nova:// links right away, without me pressing Enter",
         "Изпращай заявките от други програми и nova:// връзки веднага, без да натискам Enter")),
))

# Words and phrases, longest first. They are replaced in English and Bulgarian texts alike (the Bulgarian ones
# keep some names in English).
_WINDOWS_WORDS = (
    ("System Settings → Privacy & Security → Microphone", "Settings → Privacy & security → Microphone"),
    ("drag NOVA to Applications to finish", "the setup program has been opened: follow it to finish"),
    ("провлачи NOVA в Applications, за да завършиш", "инсталаторът е отворен: следвай го, за да завършиш"),
    ("(for the app that launches NOVA)", ""),
    ("⌃⇧Space", "Ctrl+Alt+Shift+Space"), ("⌘⇧Space", "Ctrl+Alt+Space"), ("⌘", "Ctrl+"),
    ("“Launch at login”", "“Start with Windows”"), ("Launch at login", "Start with Windows"),
    ("launch-at-login", "start-with-Windows"), ("At login, start", "When you sign in, start"),
    ("in the menu bar", "in the notification area"), ("menu bar", "notification area"),
    ("the Keychain", "Windows Credential Manager"), ("your Keychain", "Windows Credential Manager"),
    ("Keychain", "Windows Credential Manager"), ("keychain", "Windows Credential Manager"),
    ("the Trash", "the Recycle Bin"), ("Trash", "Recycle Bin"), ("Finder", "Explorer"),
    ("this Mac", "this PC"), ("your Mac", "your PC"), ("the Mac", "the PC"), ("another Mac", "another PC"),
    ("macOS", "Windows"),
    # Bulgarian
    ("в твоя Windows Credential Manager", "в Windows Credential Manager"),
    ("„Стартирай при вход“", "„Стартирай с Windows“"), ("Стартирай при вход", "Стартирай с Windows"),
    ("стартиране при вход", "стартиране с Windows"), ("При вход стартирай", "При влизане в Windows стартирай"),
    ("в лентата с менюта", "в областта за уведомяване"), ("лентата с менюта", "областта за уведомяване"),
    ("във Explorer", "в Explorer"),
    ("този Mac", "този компютър"), ("твоя Mac", "твоя компютър"), ("Mac-а", "компютъра"), ("друг Mac", "друг компютър"),
    ("гласа на Mac", "гласа на Windows"),
)


def local(text: str, windows: bool | None = None) -> str:
    """`text` in this operating system's words (unchanged on the Mac). `windows` forces the answer for the tests."""
    if not text or not (ON_WINDOWS if windows is None else windows):
        return text
    for old, new in _WINDOWS_WORDS:
        if old in text: text = text.replace(old, new)
    return text.replace("  ,", ",").replace(" ,", ",")
