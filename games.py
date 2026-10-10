# games.py — NOVA Games: Wordle (daily) + Number Guesser with streaks
import os, json, random, datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGridLayout,
    QMessageBox, QLineEdit
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
import platform_utils as plat
import paths
from i18n import tr
import logging

log = logging.getLogger("nova")

HOME       = os.path.expanduser("~")
GAMES_FILE = paths.GAMES_FILE

# ── Word list ────────────────────────────────────────────────────
WORDS = sorted(set(w.upper() for w in [
    "apple","beach","black","blade","blank","blast","blaze","blend",
    "bless","blind","block","blood","bloom","blown","board","boast",
    "bonus","boost","brave","bread","break","breed","brick","bride",
    "brief","bring","broad","broke","brook","brown","build","built",
    "bunch","burst","cabin","candy","carry","catch","cause","chain",
    "chair","chalk","charm","chart","chase","cheap","check","cheek",
    "chess","chest","chief","child","china","civic","civil","claim",
    "clash","class","clean","clear","clerk","click","cliff","climb",
    "clock","clone","close","cloud","coach","coast","cobra","color",
    "combo","comic","coral","could","count","court","cover","crack",
    "craft","crane","crash","crazy","cream","creek","creep","crisp",
    "cross","crowd","crown","cruel","crush","curve","cycle","daily",
    "dairy","dance","death","debut","delta","depth","derby","devil",
    "dirty","disco","dodge","doing","donor","doubt","dough","draft",
    "drain","drama","drank","drape","dream","dress","drift","drink",
    "drive","drone","drove","drums","dryer","dutch","dwarf","eagle",
    "early","earth","eight","elite","ember","empty","enemy","enjoy",
    "enter","equal","error","event","every","exact","excel","exist",
    "extra","fable","faint","fairy","faith","false","fancy","fatal",
    "feast","fence","ferry","fever","field","fight","final","first",
    "fixed","fizzy","flame","flash","flask","fleet","flesh","flint",
    "float","flood","floor","floss","flown","fluid","flute","focus",
    "force","forge","forth","forum","found","frame","frank","fraud",
    "fresh","front","frost","froze","fruit","fully","gamma","giant",
    "given","gland","glass","glide","globe","gloom","gloss","glove",
    "gorge","grace","grade","grail","grain","grand","grant","grape",
    "grasp","grass","graze","great","greed","green","greet","grief",
    "grill","grind","groan","gross","group","grove","grown","guard",
    "guava","guide","guile","guise","gusto","habit","happy","harsh",
    "haste","hazel","heart","heavy","hedge","hence","herbs","honey",
    "honor","horse","hotel","house","human","humor","hurry","hyper",
    "ideal","image","inbox","index","indie","inner","input","inter",
    "intro","ivory","japan","jewel","joint","joker","judge","juice",
    "juicy","karma","knack","kneel","knife","knock","known","label",
    "lance","large","laser","latch","later","laugh","layer","learn",
    "lease","ledge","legal","lemon","level","light","linen","liner",
    "liver","local","lodge","logic","loose","lover","lower","lucky",
    "lunar","lunch","lusty","lyric","magic","major","maker","manor",
    "maple","march","match","maxim","mayor","media","mercy","merit",
    "metal","might","mixed","model","money","month","moral","motor",
    "motto","mount","mouse","mouth","movie","music","naive","nerve",
    "never","night","ninja","noble","noise","north","noted","novel",
    "nudge","nurse","nylon","occur","ocean","offer","often","olive",
    "onset","opera","orbit","order","other","outer","owned","oxide",
    "ozone","paint","panel","panic","paper","party","pasta","patch",
    "pause","peace","peach","pearl","pedal","penny","petal","phase",
    "phone","photo","piano","pilot","pitch","pixel","pizza","place",
    "plain","plank","plant","plate","plaza","plead","pluck","plumb",
    "plume","point","polar","pound","power","press","price","pride",
    "prime","print","prism","prize","probe","proof","prose","proud",
    "prove","psalm","pulse","punch","pupil","purse","quest","queue",
    "quick","quiet","quota","quote","radar","radio","raise","rally",
    "range","rapid","ratio","reach","react","ready","rebel","reign",
    "relax","relay","remix","repay","rider","ridge","right","risky",
    "rival","river","robot","rocky","rouge","rough","round","royal",
    "rugby","ruler","rural","sadly","saint","sales","sauce","saved",
    "scale","scare","scene","score","scout","screw","seize","sense",
    "serve","seven","shade","shake","shall","shame","shape","share",
    "shark","sharp","sheen","sheep","shelf","shell","shift","shine",
    "shirt","shock","shore","short","shout","shove","sight","sigma",
    "since","sixth","sixty","skill","skimp","slate","slave","sleep",
    "sleet","slide","slope","sloth","slump","smart","smell","smile",
    "smoke","snake","solar","solid","solve","sonic","sorry","south",
    "space","spark","speak","spear","spell","spend","spice","spicy",
    "spike","spine","spoil","spoon","sport","spray","squad","stack",
    "staff","stage","stain","stair","stake","stand","stark","start",
    "state","stays","steam","steel","steep","steer","stern","stick",
    "sting","stock","stomp","stone","stood","storm","story","stove",
    "straw","strip","stuck","study","style","sugar","suite","sunny",
    "super","surge","swamp","swear","sweep","sweet","swift","swing",
    "sword","swore","table","taste","teach","teeth","tempo","tense",
    "tenth","terms","theft","their","theme","there","these","thick",
    "thing","think","third","thorn","those","three","threw","throw",
    "tiger","timer","tired","title","today","token","torch","total",
    "touch","tough","tower","toxic","trace","track","trade","trail",
    "train","trait","tramp","trash","treat","trend","trial","tribe",
    "trick","tried","troop","trove","truck","truly","trump","trunk",
    "trust","truth","tulip","tuple","ultra","under","union","unite",
    "until","upper","upset","urban","usage","usual","utile","utter",
    "valid","value","valve","vapor","vault","veins","verse","video",
    "vigor","viral","virus","visit","vista","vital","vivid","vocal",
    "voice","voted","vouch","vowel","wagon","waste","watch","water",
    "weave","wedge","weird","whale","wheat","wheel","where","which",
    "while","white","whole","width","witch","woman","women","world",
    "worry","worse","worst","worth","would","wound","wrath","write",
    "wrote","yacht","yield","young","yours","youth","zebra","zones",
] if len(w) == 5))

# Proper nouns / obscure entries stay valid as guesses but are never picked as the answer.
_NOT_ANSWERS = {"CHINA", "JAPAN", "DUTCH", "TUPLE", "UTILE", "INBOX", "INDIE", "LUSTY", "PSALM", "SIGMA", "GAMMA", "DELTA"}
ANSWERS = [w for w in WORDS if w not in _NOT_ANSWERS]

_DICT_WORDS = None
def is_valid_guess(word: str) -> bool:
    """Any real 5-letter word: our list plus the system dictionary (if there is one)."""
    global _DICT_WORDS
    if word in WORDS: return True
    if _DICT_WORDS is None:
        _DICT_WORDS = set()
        for path in ("/usr/share/dict/words", "/usr/share/dict/web2"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if len(line) == 5 and line.isalpha() and line.islower():
                            _DICT_WORDS.add(line.upper())
                break
            except OSError:
                continue
    return word in _DICT_WORDS if _DICT_WORDS else word.isalpha()

# ── Daily word (same word for everyone on the same date) ─────────
def get_daily_word() -> str:
    today = datetime.date.today()
    seed  = today.year * 10000 + today.month * 100 + today.day
    return random.Random(seed).choice(ANSWERS)

def time_until_midnight() -> str:
    now  = datetime.datetime.now()
    nxt  = (now + datetime.timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    secs = int((nxt - now).total_seconds())
    h, r = divmod(secs, 3600); m = r // 60
    return f"{h}h {m}m"

# ── Stats helpers ─────────────────────────────────────────────────
def load_stats() -> dict:
    try:
        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_stats(stats: dict):
    try:
        tmp = GAMES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        os.replace(tmp, GAMES_FILE)
    except Exception as e: log.info("game statistics were not saved: %s", e)

def save_progress(game: str, data: dict):
    """Remember an unfinished daily game so closing the dialog doesn't give a free retry."""
    all_stats = load_stats()
    all_stats.setdefault(game, {})["progress"] = {"date": datetime.date.today().isoformat(), **data}
    save_stats(all_stats)

def load_progress(game: str):
    p = load_stats().get(game, {}).get("progress")
    return p if p and p.get("date") == datetime.date.today().isoformat() else None

def get_wordle_stats() -> dict:
    s = load_stats().get("wordle", {})
    return {
        "played":      s.get("played",  0),
        "won":         s.get("won",     0),
        "streak":      s.get("streak",  0),
        "best":        s.get("best",    0),
        "guesses":     s.get("guesses", {}),
        "last_played": s.get("last_played", ""),
        "last_result": s.get("last_result", ""),
        "last_board":  s.get("last_board",  []),
    }

def record_wordle_result(won: bool, guess_count: int, board_states: list):
    all_stats = load_stats()
    s = all_stats.get("wordle", {})
    today     = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(1)).isoformat()

    s["played"]      = s.get("played", 0) + 1
    s["last_played"] = today
    s["last_result"] = "won" if won else "lost"
    s["last_board"]  = board_states          # list of row dicts for replay
    s.pop("progress", None)

    if won:
        s["won"] = s.get("won", 0) + 1
        last = s.get("last_played_win", "")
        if last in (yesterday, today):
            s["streak"] = s.get("streak", 0) + 1
        else:
            s["streak"] = 1
        s["best"]            = max(s.get("best", 0), s["streak"])
        s["last_played_win"] = today
        g = s.get("guesses", {})
        g[str(guess_count)]  = g.get(str(guess_count), 0) + 1
        s["guesses"] = g
    else:
        s["streak"] = 0

    all_stats["wordle"] = s
    save_stats(all_stats)

# ── Tile ─────────────────────────────────────────────────────────
class Tile(QLabel):
    EMPTY   = "empty"
    FILLED  = "filled"
    CORRECT = "correct"
    PRESENT = "present"
    ABSENT  = "absent"

    def __init__(self, theme: dict):
        super().__init__()
        self.setFixedSize(52, 52)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(plat.ui_font(18, QFont.Weight.Bold))
        self._theme = theme
        self.set_state(self.EMPTY, "")

    def set_state(self, state: str, letter: str = ""):
        self.setText(letter)
        t = self._theme
        if state == self.CORRECT:
            bg, fg, br = "#538d4e", "#ffffff", "#538d4e"
        elif state == self.PRESENT:
            bg, fg, br = "#b59f3b", "#ffffff", "#b59f3b"
        elif state == self.ABSENT:
            bg, fg, br = "#3a3a3c", "#aaaaaa", "#3a3a3c"
        elif state == self.FILLED:
            bg, fg, br = t["ai_bg"], t["ai_fg"], t["sys_fg"]
        else:  # empty
            bg, fg, br = t["ai_bg"], t["ai_fg"], t["ai_br"]
        self.setStyleSheet(
            f"QLabel{{background:{bg};color:{fg};"
            f"border:2px solid {br};border-radius:4px;}}")

# ── Key button ────────────────────────────────────────────────────
class KeyBtn(QPushButton):
    def __init__(self, ch: str, theme: dict, wide=False):
        super().__init__(ch)
        self.ch     = ch
        self._theme = theme
        self._state = "unused"
        self.setFixedSize(68 if wide else 36, 42)
        self.setFont(plat.ui_font(10, QFont.Weight.Bold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)   # ← prevents Enter from clicking buttons
        self.setDefault(False)
        self._refresh()

    def _refresh(self):
        t  = self._theme
        bg, fg, br = {
            "correct": ("#538d4e","#ffffff","#538d4e"),
            "present": ("#b59f3b","#ffffff","#b59f3b"),
            "absent":  ("#3a3a3c","#888888","#3a3a3c"),
        }.get(self._state, (t["ai_bg"], t["ai_fg"], t["ai_br"]))
        self.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};"
            f"border:1px solid {br};border-radius:4px;}}"
            f"QPushButton:hover{{background:{bg};}}")

    def upgrade(self, state: str):
        rank = {"correct":3,"present":2,"absent":1,"unused":0}
        if rank.get(state,0) > rank.get(self._state,0):
            self._state = state; self._refresh()

# ── Wordle dialog ─────────────────────────────────────────────────
class WordleDialog(QDialog):
    ROWS = 6; COLS = 5

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.t = theme
        self.setWindowTitle(tr("NOVA — Wordle"))
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(
            f"QDialog{{background:{theme['frame_bg']};}}"
            f"QLabel{{color:{theme['ai_fg']};}}")

        self._word    = get_daily_word()
        self._row     = 0
        self._col     = 0
        self._current = [""] * 5
        self._done    = False
        self._keys    = {}
        self._board_states = []   # for saving

        self._build_ui()

        # Check if already played today
        s = get_wordle_stats()
        if s["last_played"] == datetime.date.today().isoformat():
            self._restore_played(s)
        else:
            self._update_stats_bar()
            prog = load_progress("wordle")
            if prog:
                self._restore_progress(prog.get("board", []))

    def _restore_progress(self, board: list):
        for row_data in board:
            r = row_data["row"]
            for c, (letter, state) in enumerate(zip(row_data["letters"], row_data["states"])):
                self._tiles[r][c].set_state(state, letter)
                if letter in self._keys:
                    self._keys[letter].upgrade(state)
        self._board_states = list(board)
        self._row = len(board)

    # ── Build ─────────────────────────────────────────────────────
    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setSpacing(8); vl.setContentsMargins(16,14,16,14)

        # Title
        title = QLabel("W O R D L E")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(plat.ui_font(16, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{self.t.get('accent_fg', self.t['accent'])};letter-spacing:4px;")
        vl.addWidget(title)

        # Date + stats bar
        self._stats_lbl = QLabel("")
        self._stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stats_lbl.setFont(plat.ui_font(9))
        self._stats_lbl.setStyleSheet(f"color:{self.t['sys_fg']};")
        vl.addWidget(self._stats_lbl)

        # Message
        self._msg = QLabel(" ")
        self._msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg.setFont(plat.ui_font(10, QFont.Weight.Bold))
        self._msg.setMinimumHeight(22)
        vl.addWidget(self._msg)

        # Tile grid
        grid_frame  = QFrame()
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setSpacing(5); grid_layout.setContentsMargins(0,0,0,0)
        self._tiles = []
        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                tile = Tile(self.t)
                grid_layout.addWidget(tile, r, c)
                row.append(tile)
            self._tiles.append(row)
        vl.addWidget(grid_frame, alignment=Qt.AlignmentFlag.AlignHCenter)

        # On-screen keyboard
        kb = QFrame(); kb_vl = QVBoxLayout(kb)
        kb_vl.setSpacing(5); kb_vl.setContentsMargins(0,6,0,0)
        for row_chars in ["QWERTYUIOP", "ASDFGHJKL", "↵ZXCVBNM⌫"]:
            hl = QHBoxLayout(); hl.setSpacing(4); hl.addStretch()
            for ch in row_chars:
                wide = ch in ("↵","⌫")
                btn  = KeyBtn(ch, self.t, wide=wide)
                btn.clicked.connect(lambda _, c=ch: self._on_key(c))
                hl.addWidget(btn)
                if ch not in ("↵","⌫"):
                    self._keys[ch] = btn
            hl.addStretch()
            kb_vl.addLayout(hl)
        vl.addWidget(kb)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self._stats_btn = self._mkbtn("📊  " + tr("Stats"),    self._show_stats)
        btn_row.addWidget(self._stats_btn)
        vl.addLayout(btn_row)

    def _mkbtn(self, text, fn):
        b = QPushButton(text)
        b.setFixedHeight(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFont(plat.ui_font(10))
        b.setAutoDefault(False); b.setDefault(False)
        b.setStyleSheet(
            f"QPushButton{{background:{self.t['send_bg']};color:#fff;"
            f"border:none;border-radius:8px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{self.t['send_hv']};}}")
        b.clicked.connect(fn); return b

    def _update_stats_bar(self):
        s   = get_wordle_stats()
        wp  = int(s["won"]/s["played"]*100) if s["played"] else 0
        today = datetime.date.today().strftime("%d %b %Y")
        self._stats_lbl.setText(tr("{}  |  Played: {}  |  Win: {}%  |  🔥 Streak: {}  |  Best: {}")
                                .format(today, s['played'], wp, s['streak'], s['best']))

    # ── Restore already-played board ──────────────────────────────
    def _restore_played(self, s: dict):
        for row_data in s.get("last_board", []):
            r = row_data["row"]
            for c, (letter, state) in enumerate(zip(row_data["letters"], row_data["states"])):
                self._tiles[r][c].set_state(state, letter)
                if letter in self._keys:
                    self._keys[letter].upgrade(state)
        self._done = True
        if s["last_result"] == "won":
            streak = s["streak"]
            self._show_msg(tr("✓ Already solved today!  🔥 Streak: {}").format(streak), "#538d4e")
        else:
            self._show_msg(tr("❌ The word was: {}  —  next word in {}").format(self._word, time_until_midnight()), "#cc4444")
        self._update_stats_bar()

    # ── Input ─────────────────────────────────────────────────────
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Backspace:
            self._on_key("⌫")
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_key("↵")
        elif Qt.Key.Key_A <= k <= Qt.Key.Key_Z:
            self._on_key(chr(k))
        # do NOT call super() — prevents any button from eating Enter

    def _on_key(self, ch: str):
        if self._done: return
        if ch == "⌫":
            if self._col > 0:
                self._col -= 1
                self._current[self._col] = ""
                self._tiles[self._row][self._col].set_state(Tile.EMPTY, "")
        elif ch == "↵":
            self._submit()
        elif len(ch) == 1 and ch.isalpha() and self._col < 5:
            letter = ch.upper()
            self._current[self._col] = letter
            self._tiles[self._row][self._col].set_state(Tile.FILLED, letter)
            self._col += 1

    # ── Submit guess ──────────────────────────────────────────────
    def _submit(self):
        if self._col < 5:
            self._flash(tr("Not enough letters ✋")); return
        guess = "".join(self._current)
        if not is_valid_guess(guess):
            self._flash(tr("Not in word list 🤔")); return

        result = self._evaluate(guess, self._word)
        row_data = {"row": self._row, "letters": list(guess), "states": result}
        self._board_states.append(row_data)

        for c, (letter, state) in enumerate(zip(guess, result)):
            self._tiles[self._row][c].set_state(state, letter)
            if letter in self._keys:
                self._keys[letter].upgrade(state)

        if guess == self._word:
            self._done = True
            record_wordle_result(True, self._row + 1, self._board_states)
            self._update_stats_bar()
            praise = ["Genius! 🧠","Magnificent! 🎉","Impressive! 👏",
                      "Splendid! 😊","Great! 👍","Phew! 😅"]
            self._show_msg(tr(praise[min(self._row, 5)]), "#538d4e")
            streak = get_wordle_stats()["streak"]
            QTimer.singleShot(1800, lambda: self._show_msg(
                tr("🔥 Streak: {}  —  next word in {}").format(streak, time_until_midnight()), "#538d4e"))
        elif self._row == 5:
            self._done = True
            record_wordle_result(False, 0, self._board_states)
            self._update_stats_bar()
            self._show_msg(tr("❌ The word was: {}  —  next word in {}").format(self._word, time_until_midnight()), "#cc4444")
        else:
            save_progress("wordle", {"board": self._board_states})
            self._row += 1
            self._col = 0
            self._current = [""] * 5

    def _evaluate(self, guess: str, word: str):
        result    = [Tile.ABSENT] * 5
        remaining = list(word)
        for i,(g,w) in enumerate(zip(guess,word)):
            if g == w:
                result[i] = Tile.CORRECT
                remaining[remaining.index(g)] = None
        for i, g in enumerate(guess):
            if result[i] == Tile.CORRECT: continue
            if g in remaining:
                result[i] = Tile.PRESENT
                remaining[remaining.index(g)] = None
        return result

    def _flash(self, text: str):
        self._show_msg(text, "#cc4444")
        QTimer.singleShot(1600, lambda: self._show_msg(" ", ""))

    def _show_msg(self, text: str, color: str):
        self._msg.setText(text)
        self._msg.setStyleSheet(f"color:{color};" if color else "")

    def _show_stats(self):
        s    = get_wordle_stats()
        wp   = int(s["won"]/s["played"]*100) if s["played"] else 0
        dist = s.get("guesses", {})
        mx   = max((dist.get(str(i),0) for i in range(1,7)), default=1) or 1
        bars = ""
        for i in range(1,7):
            n    = dist.get(str(i), 0)
            bar  = "█" * max(1, int(n/mx*12)) if n else ""
            bars += f"  {i}: {bar} {n}\n"
        QMessageBox.information(self, tr("Wordle Stats"),
            tr("Played: {}\nWin %: {}%\nCurrent streak: {} 🔥\nBest streak: {}").format(s['played'], wp, s['streak'], s['best'])
            + "\n\n" + tr("Guess distribution:") + f"\n{bars}\n" + tr("Next word in: {}").format(time_until_midnight()))


# ── Number Guesser ────────────────────────────────────────────────
def get_daily_number() -> int:
    today = datetime.date.today()
    seed  = today.year * 10000 + today.month * 100 + today.day + 1  # +1 so it differs from Wordle seed
    return random.Random(seed).randint(1, 100)

def get_ng_stats() -> dict:
    s = load_stats().get("numguess", {})
    return {
        "played":      s.get("played",      0),
        "won":         s.get("won",         0),
        "streak":      s.get("streak",      0),
        "best":        s.get("best",        0),
        "last_played": s.get("last_played", ""),
        "last_result": s.get("last_result", ""),
        "last_tries":  s.get("last_tries",  0),
    }

def record_ng_result(won: bool, tries: int):
    all_stats = load_stats()
    s         = all_stats.get("numguess", {})
    today     = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(1)).isoformat()

    s["played"]      = s.get("played", 0) + 1
    s["last_played"] = today
    s["last_result"] = "won" if won else "lost"
    s["last_tries"]  = tries
    s.pop("progress", None)

    if won:
        s["won"] = s.get("won", 0) + 1
        last = s.get("last_played_win", "")
        s["streak"] = s.get("streak", 0) + 1 if last in (yesterday, today) else 1
        s["best"]            = max(s.get("best", 0), s["streak"])
        s["last_played_win"] = today
    else:
        s["streak"] = 0

    all_stats["numguess"] = s
    save_stats(all_stats)


class NumberGuessDialog(QDialog):
    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.t = theme
        self.setWindowTitle(tr("NOVA — Number Guesser"))
        self.setModal(True); self.setFixedWidth(320)
        self.setStyleSheet(f"QDialog{{background:{theme['frame_bg']};}}"
                           f"QLabel{{color:{theme['ai_fg']};}}")
        self._target = get_daily_number()
        self._tries  = 0
        self._max    = 7
        self._done   = False
        self._build_ui()
        self._update_stats_bar()

        # Already played today?
        s = get_ng_stats()
        if s["last_played"] == datetime.date.today().isoformat():
            self._restore_played(s)
        else:
            prog = load_progress("numguess")
            if prog:
                self._tries = int(prog.get("tries", 0))
                self._tries_lbl.setText(tr("Tries left: {}").format(self._max - self._tries))
                if prog.get("hint"): self._show_msg(prog["hint"], self.t["accent"])

    def _restore_played(self, s: dict):
        self._done = True
        self._entry.setEnabled(False)
        if s["last_result"] == "won":
            streak = s["streak"]
            self._tries_lbl.setText(tr("Solved in {} tries").format(s['last_tries']))
            self._show_msg(tr("✓ Already played today!  🔥 Streak: {}").format(streak), "#538d4e")
        else:
            self._tries_lbl.setText(tr("Better luck tomorrow!"))
            self._show_msg(tr("❌ It was {}  —  next in {}").format(self._target, time_until_midnight()), "#cc4444")
        self._update_stats_bar()

    def _build_ui(self):
        vl = QVBoxLayout(self); vl.setSpacing(10); vl.setContentsMargins(20,20,20,20)

        title = QLabel(tr("Number Guesser"))
        title.setFont(plat.ui_font(14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color:{self.t.get('accent_fg', self.t['accent'])};")
        vl.addWidget(title)

        today = datetime.date.today().strftime("%d %b %Y")
        self._stats_lbl = QLabel(f"{today}")
        self._stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stats_lbl.setFont(plat.ui_font(9))
        self._stats_lbl.setStyleSheet(f"color:{self.t['sys_fg']};")
        vl.addWidget(self._stats_lbl)

        vl.addWidget(self._lbl(tr("Guess a number between 1 and 100")))

        self._tries_lbl = QLabel(tr("Tries left: {}").format(self._max))
        self._tries_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tries_lbl.setFont(plat.ui_font(10))
        vl.addWidget(self._tries_lbl)

        self._entry = QLineEdit()
        self._entry.setPlaceholderText(tr("Your guess..."))
        self._entry.setFont(plat.ui_font(12))
        self._entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._entry.setStyleSheet(
            f"QLineEdit{{background:{self.t['ai_bg']};color:{self.t['ai_fg']};"
            f"border:1px solid {self.t['ai_br']};border-radius:8px;padding:6px;}}")
        self._entry.returnPressed.connect(self._guess)
        vl.addWidget(self._entry)

        self._msg_lbl = QLabel(" ")
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setFont(plat.ui_font(11, QFont.Weight.Bold))
        vl.addWidget(self._msg_lbl)

        vl.addWidget(self._mkbtn("📊  " + tr("Stats"), self._show_stats))

    def _update_stats_bar(self):
        s  = get_ng_stats()
        wp = int(s["won"]/s["played"]*100) if s["played"] else 0
        today = datetime.date.today().strftime("%d %b %Y")
        self._stats_lbl.setText(tr("{}  |  Played: {}  |  Win: {}%  |  🔥 Streak: {}  |  Best: {}")
                                .format(today, s['played'], wp, s['streak'], s['best']))

    def _lbl(self, text):
        l = QLabel(text); l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setFont(plat.ui_font(10)); return l

    def _mkbtn(self, text, fn):
        b = QPushButton(text); b.setFixedHeight(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFont(plat.ui_font(10))
        b.setAutoDefault(False); b.setDefault(False)
        b.setStyleSheet(
            f"QPushButton{{background:{self.t['send_bg']};color:#fff;"
            f"border:none;border-radius:8px;padding:0 12px;}}"
            f"QPushButton:hover{{background:{self.t['send_hv']};}}")
        b.clicked.connect(fn); return b

    def _show_msg(self, text, color=""):
        self._msg_lbl.setText(text)
        self._msg_lbl.setStyleSheet(f"color:{color};" if color else "")

    def _guess(self):
        if self._done: return
        try:
            n = int(self._entry.text().strip())
        except ValueError:
            self._show_msg(tr("Enter a number!"), "#cc4444"); return
        if not 1 <= n <= 100:
            self._show_msg(tr("Between 1 and 100!"), "#cc4444"); return

        self._tries += 1
        left = self._max - self._tries

        if n == self._target:
            self._done = True
            record_ng_result(True, self._tries)
            self._update_stats_bar()
            self._tries_lbl.setText(tr("Solved in {} tries").format(self._tries))

            self._show_msg(tr("🎉 Correct!  🔥 Streak: {}").format(get_ng_stats()['streak']), "#538d4e")
            QTimer.singleShot(1800, lambda: self._show_msg(
                tr("Next number in {}").format(time_until_midnight()), "#538d4e"))
            self._entry.setEnabled(False)
        elif left == 0:
            self._done = True
            record_ng_result(False, self._tries)
            self._update_stats_bar()
            self._tries_lbl.setText(tr("Out of tries!"))
            self._show_msg(tr("❌ It was {}  —  next in {}").format(self._target, time_until_midnight()), "#cc4444")
            self._entry.setEnabled(False)
        else:
            hint = "Too low ⬆️" if n < self._target else "Too high ⬇️"
            self._show_msg(tr(hint), self.t["accent"])
            self._tries_lbl.setText(tr("Tries left: {}").format(left))
            save_progress("numguess", {"tries": self._tries, "hint": hint})
        self._entry.clear(); self._entry.setFocus()

    def _show_stats(self):
        s  = get_ng_stats()
        wp = int(s["won"]/s["played"]*100) if s["played"] else 0
        QMessageBox.information(self, tr("Number Guesser Stats"),
            tr("Played: {}\nWin %: {}%\nCurrent streak: {} 🔥\nBest streak: {}").format(s['played'], wp, s['streak'], s['best'])
            + "\n\n" + tr("Next number in {}").format(time_until_midnight()))


# ── Launcher ─────────────────────────────────────────────────────
def open_games_menu(parent, theme):
    from PySide6.QtWidgets import QMenu
    import datetime as _dt
    t  = theme
    s  = load_stats()
    wl = s.get("wordle",   {})
    ng = s.get("numguess", {})

    menu = QMenu(parent)
    menu.setStyleSheet(
        f"QMenu{{background:{t['bar_bg']};border:1px solid {t['ai_br']};"
        f"border-radius:12px;color:{t['ai_fg']};font-size:11px;padding:6px;}}"
        f"QMenu::item{{padding:9px 18px;border-radius:6px;}}"
        f"QMenu::item:selected{{background:{t['frame_bg']};}}"
        f"QMenu::item:disabled{{color:{t['sys_fg']};}}")

    menu.addAction(tr("🟩  Wordle  (daily word)")).triggered.connect(
        lambda: WordleDialog(theme, parent).exec())
    menu.addAction(tr("🔢  Number Guesser  (daily)")).triggered.connect(
        lambda: NumberGuessDialog(theme, parent).exec())
    menu.addSeparator()

    today     = _dt.date.today().isoformat()
    wl_status = "✓" if wl.get("last_played","") == today else tr("next in {}").format(time_until_midnight())
    ng_status = "✓" if ng.get("last_played","") == today else tr("next in {}").format(time_until_midnight())
    menu.addAction(
        tr("🟩 Wordle: {}🔥 ({})   |   🔢 Number: {}🔥 ({})").format(wl.get('streak',0), wl_status, ng.get('streak',0), ng_status)
    ).setEnabled(False)

    from PySide6.QtCore import QPoint
    pos = parent._plus_btn.mapToGlobal(
        parent._plus_btn.rect().topLeft() - QPoint(0, menu.sizeHint().height()))
    menu.exec(pos)
