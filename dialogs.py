# dialogs.py — chat browser (search / rename / delete), memory editor and "send this to the AI?" previews.
import os, json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QInputDialog, QMessageBox, QTextEdit, QComboBox, QFormLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage
from i18n import tr
import storage
import memory
import ledger
import platform_utils as plat


def _style(t: dict) -> str:
    """The shared look of NOVA's dialogs: the window's surface, white fields with a hairline, one accent button."""
    return (f"QDialog{{background:{t['frame_bg']};}} QLabel{{color:{t['ai_fg']};}}"
            f"QLineEdit,QTextEdit,QListWidget,QComboBox,QTableWidget{{background:{t['ai_bg']};color:{t['ai_fg']};"
            f"border:1px solid {t['ai_br']};border-radius:6px;padding:5px 7px;"
            f"selection-background-color:{t['send_bg']};selection-color:#ffffff;}}"
            f"QLineEdit:focus,QTextEdit:focus{{border-color:{t['accent']};}}"
            f"QHeaderView::section{{background:{t['frame_bg']};color:{t['sys_fg']};border:none;padding:4px 6px;}}"
            f"QListWidget::item{{padding:6px;border-radius:5px;}}"
            f"QListWidget::item:selected{{background:{t['send_bg']};color:#ffffff;}}"
            f"QPushButton{{background:{t['send_bg']};color:#ffffff;border:none;border-radius:6px;padding:5px 14px;}}"
            f"QPushButton:hover{{background:{t['send_hv']};}}"
            f"QPushButton:disabled{{background:{t['ai_br']};color:{t['sys_fg']};}}")


def _btn(text, fn, secondary=False, t=None):
    b = QPushButton(text); b.clicked.connect(fn)
    if secondary and t:
        b.setStyleSheet(f"QPushButton{{background:{t['ai_bg']};color:{t['ai_fg']};border:1px solid {t['ai_br']};"
                        f"border-radius:6px;padding:5px 14px;}}QPushButton:hover{{border-color:{t['sys_fg']};}}"
                        f"QPushButton:disabled{{color:{t['sys_fg']};}}")
    return b


# ── Saved chats ────────────────────────────────────────────────────
def read_sessions(sessions_dir: str, limit: int = 200) -> list:
    """[{path, title, created, count, text}] newest first. `text` is lower-cased content for searching."""
    out = []
    if not os.path.isdir(sessions_dir): return out
    for f in sorted((x for x in os.listdir(sessions_dir) if x.endswith(".json")), reverse=True)[:limit]:
        path = os.path.join(sessions_dir, f)
        try:
            d = storage.read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict): continue
        msgs = d.get("messages", [])
        out.append({"path": path, "title": d.get("title") or f[:-5], "created": (d.get("created") or "")[:16].replace("T", " "),
                    "count": len(msgs), "text": " ".join(str(m.get("content", "")) for m in msgs).lower()})
    return out


class SessionsDialog(QDialog):
    """Browse, search, rename, delete and load saved chats. `selected_path` is set when the user loads one."""
    def __init__(self, theme: dict, sessions_dir: str, parent=None):
        super().__init__(parent)
        self.t = theme; self.dir = sessions_dir; self.selected_path = None
        self.setWindowTitle(tr("Sessions")); self.setMinimumSize(520, 440); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("Search chats…")); self.search.textChanged.connect(self._fill)
        self.search.setAccessibleName(tr("Search chats"))
        self.listw = QListWidget(); self.listw.itemDoubleClicked.connect(lambda _i: self._load())
        self.listw.setAccessibleName(tr("Sessions"))
        self.listw.itemSelectionChanged.connect(self._sel_changed)
        row = QHBoxLayout()
        self.load_btn = _btn(tr("Load"), self._load); self.ren_btn = _btn(tr("Rename"), self._rename, True, theme)
        self.del_btn = _btn(tr("Delete"), self._delete, True, theme)
        row.addWidget(self.load_btn); row.addWidget(self.ren_btn); row.addWidget(self.del_btn); row.addStretch()
        row.addWidget(_btn(tr("Close"), self.reject, True, theme))
        v.addWidget(self.search); v.addWidget(self.listw, 1); v.addLayout(row)
        self._all = read_sessions(sessions_dir); self._fill(); self._sel_changed()

    def _fill(self):
        q = self.search.text().strip().lower(); self.listw.clear()
        for s in self._all:
            if q and q not in s["title"].lower() and q not in s["text"]: continue
            it = QListWidgetItem(f"{s['title']}\n{s['created']}  ·  {s['count']} {tr('messages')}")
            it.setData(Qt.ItemDataRole.UserRole, s["path"]); self.listw.addItem(it)
        if not self.listw.count():
            self.listw.addItem(QListWidgetItem(tr("No saved sessions"))); self.listw.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _current(self):
        it = self.listw.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _sel_changed(self):
        on = self._current() is not None
        for b in (self.load_btn, self.ren_btn, self.del_btn): b.setEnabled(on)

    def _load(self):
        p = self._current()
        if p: self.selected_path = p; self.accept()

    def _rename(self):
        p = self._current()
        if not p: return
        try:
            d = storage.read_json(p)
            name, ok = QInputDialog.getText(self, tr("Rename"), tr("Chat title:"), text=d.get("title", ""))
            if ok and name.strip():
                d["title"] = name.strip()[:80]
                storage.write_json(p, d)
                self._all = read_sessions(self.dir); self._fill()
        except (OSError, ValueError):
            pass

    def _delete(self):
        p = self._current()
        if p and QMessageBox.question(self, tr("Delete"), tr("Delete this chat permanently?"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try: os.remove(p)
            except OSError: pass
            self._all = read_sessions(self.dir); self._fill()


# ── Memories ───────────────────────────────────────────────────────
class MemoryEditDialog(QDialog):
    """One memory: what to remember, its category, and how long to keep it."""
    KEEP = (("Forever", 0), ("1 day", 1), ("1 week", 7), ("1 month", 30), ("1 year", 365))

    def __init__(self, theme: dict, item: dict = None, parent=None):
        super().__init__(parent)
        self._orig = dict(item) if item else None
        self.setWindowTitle(tr("Edit") if item else tr("Add")); self.setMinimumWidth(420); self.setStyleSheet(_style(theme))
        form = QFormLayout(self); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
        self.text = QTextEdit(); self.text.setAcceptRichText(False); self.text.setFixedHeight(84)
        self.text.setPlainText(item["text"] if item else ""); self.text.setAccessibleName(tr("Something NOVA should remember:"))
        self.cat = QComboBox(); self.cat.setAccessibleName(tr("Category"))
        self.cat.addItem(tr("Choose automatically"), "")
        for c in memory.CATEGORIES: self.cat.addItem(tr(memory.LABELS[c]), c)
        if item: self.cat.setCurrentIndex(max(0, self.cat.findData(item.get("category", ""))))
        self.keep = QComboBox(); self.keep.setAccessibleName(tr("Keep for"))
        if item and item.get("expires"):
            self.keep.addItem(tr("Until {}").format(item["expires"]), None)          # leave the date as it is
        for label, days in self.KEEP: self.keep.addItem(tr(label), days)
        form.addRow(tr("Something NOVA should remember:"), self.text)
        form.addRow(tr("Category") + ":", self.cat); form.addRow(tr("Keep for") + ":", self.keep)
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Save"), self.accept))
        form.addRow(row)

    def result_item(self):
        text = self.text.toPlainText().strip()
        if not text: return None
        days = self.keep.currentData()
        same_text = bool(self._orig) and self._orig.get("text") == text
        it = memory.make(text, self.cat.currentData() or "", days or 0,
                         created=self._orig.get("created", "") if self._orig else None,
                         tags=self._orig.get("tags", "") if same_text else "")      # new wording: new keywords are fetched
        if days is None and self._orig: it["expires"] = self._orig.get("expires", "")
        return it


class MemoriesDialog(QDialog):
    """View, filter, add, edit and delete what NOVA remembers about you. Result: `items` (dicts) / `facts` (text)."""
    def __init__(self, theme: dict, facts: list, parent=None):
        super().__init__(parent)
        self.t = theme; self.items = [memory.coerce(f) for f in facts]
        self.setWindowTitle(tr("NOVA Memories")); self.setMinimumSize(520, 400); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        v.addWidget(QLabel(tr("What NOVA remembers about you. Only the ones that fit your question are sent with it.")))
        self.filter = QComboBox(); self.filter.setAccessibleName(tr("Category"))
        self.filter.addItem(tr("All categories"), "")
        for c in memory.CATEGORIES: self.filter.addItem(tr(memory.LABELS[c]), c)
        self.filter.currentIndexChanged.connect(self._fill)
        self.listw = QListWidget(); self.listw.itemDoubleClicked.connect(lambda _i: self._edit())
        self.listw.setAccessibleName(tr("NOVA Memories")); self.listw.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(_btn(tr("Add"), self._add)); row.addWidget(_btn(tr("Edit"), self._edit, True, theme))
        row.addWidget(_btn(tr("Delete"), self._delete, True, theme)); row.addStretch()
        row.addWidget(_btn(tr("Done"), self.accept))
        v.addWidget(self.filter); v.addWidget(self.listw, 1); v.addLayout(row); self._fill()

    @property
    def facts(self) -> list:
        return [memory.to_display(it) for it in self.items]

    def _fill(self, *_a):
        want = self.filter.currentData() or ""; self.listw.clear()
        for i, it in enumerate(self.items):
            if want and it.get("category") != want: continue
            when = f"  ·  {it['created']}" if it.get("created") else ""
            until = "  ·  ⏳ " + tr("Until {}").format(it["expires"]) if it.get("expires") else ""
            row = QListWidgetItem(f"{it['text']}\n{tr(memory.LABELS.get(it.get('category'), 'Other'))}{when}{until}")
            row.setData(Qt.ItemDataRole.UserRole, i); self.listw.addItem(row)

    def _index(self):
        it = self.listw.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _ask(self, item: dict = None):
        """Open the editor. Returns the new memory or None."""
        d = MemoryEditDialog(self.t, item, self)
        return d.result_item() if d.exec() == QDialog.DialogCode.Accepted else None

    def _add(self):
        it = self._ask()
        if it: self.items.append(it); self._fill()

    def _edit(self):
        i = self._index()
        if i is None: return
        it = self._ask(self.items[i])
        if it: self.items[i] = it; self._fill()

    def _delete(self):
        i = self._index()
        if i is not None: del self.items[i]; self._fill()


# ── Document library ───────────────────────────────────────────────
class DocumentsDialog(QDialog):
    """The documents NOVA can answer questions about: add files or folders, remove them, and switch on search by
    meaning (embeddings.py: a one-time model download, then each document is prepared on this Mac)."""
    meaning_progress = Signal(float, str)        # (fraction, "download" / "prepare" / "done" / an error) from the worker

    def __init__(self, theme: dict, library, parent=None):
        super().__init__(parent)
        self.t = theme; self.lib = library
        self.setWindowTitle(tr("Documents")); self.setMinimumSize(560, 420); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        note = QLabel(tr("NOVA reads these documents on this Mac. When you ask a question, only the few passages that "
                         "match it are sent to the AI. You can also drop a file or a folder onto the NOVA window."))
        note.setWordWrap(True); v.addWidget(note)
        mrow = QHBoxLayout(); mrow.setSpacing(10)
        self.meaning_status = QLabel(""); self.meaning_status.setWordWrap(True)
        self.meaning_btn = _btn("", self._toggle_meaning, True, theme)
        self.meaning_btn.setAccessibleName(tr("Search by meaning"))
        mrow.addWidget(self.meaning_status, 1); mrow.addWidget(self.meaning_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(mrow)
        self._meaning_job = None                 # {"cancel": bool} while a download / preparation runs
        self.meaning_progress.connect(self._on_meaning_progress)
        self.listw = QListWidget(); self.listw.setAccessibleName(tr("Documents")); self.listw.setWordWrap(True)
        self.status = QLabel(""); self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(_btn(tr("Add file") + "…", self._add_files)); row.addWidget(_btn(tr("Add folder") + "…", self._add_folder))
        self.rm_btn = _btn(tr("Remove"), self._remove, True, theme); row.addWidget(self.rm_btn)
        row.addWidget(_btn(tr("Remove all"), self._clear, True, theme)); row.addStretch()
        row.addWidget(_btn(tr("Close"), self.accept, True, theme))
        v.addWidget(self.listw, 1); v.addWidget(self.status); v.addLayout(row)
        self._fill()
        self._refresh_meaning()
        import embeddings
        if embeddings.ready() and self.lib.missing_vectors():
            self._start_meaning(download=False)    # documents added before the model was there

    # ── search by meaning ──
    def _refresh_meaning(self):
        import embeddings
        if not embeddings.runtime_installed():
            self.meaning_btn.setEnabled(False); self.meaning_btn.setText(tr("Not available"))
            self.meaning_status.setText(tr("Search by meaning is not part of this build.")); return
        self.meaning_btn.setEnabled(True)
        if embeddings.installed():
            self.meaning_btn.setText(tr("Remove"))
            self.meaning_status.setText(tr("Search by meaning is on: a question also finds passages that say the same thing "
                                           "in other words or in another language."))
        else:
            self.meaning_btn.setText(tr("Download ({} MB)").format(embeddings.MODEL_MB))
            self.meaning_status.setText(tr("Search by meaning finds passages that say the same thing in other words or in "
                                           "another language. It works on this Mac after a one-time download."))

    def _toggle_meaning(self):
        import embeddings
        if self._meaning_job:                                       # running: the button is "Cancel"
            self._meaning_job["cancel"] = True; return
        if embeddings.installed():
            if QMessageBox.question(self, tr("Search by meaning"), tr("Remove search by meaning? NOVA then finds passages by "
                                    "their words only. You can download it again at any time."),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                embeddings.remove(); self._refresh_meaning()
            return
        self._start_meaning(download=True)

    def _start_meaning(self, download: bool):
        import threading, embeddings
        job = self._meaning_job = {"cancel": False}
        self.meaning_btn.setText(tr("Cancel"))
        def emit(frac, state):
            try: self.meaning_progress.emit(frac, state)
            except RuntimeError: pass                                # the window was closed; the work goes on
        def _bg():
            try:
                if download:
                    embeddings.download(lambda f: emit(f, "download"), lambda: job["cancel"])
                self.lib.embed_missing(lambda done, total, _name: emit(done / max(total, 1), "prepare"), lambda: job["cancel"])
                emit(1.0, "done")
            except Exception as e:
                emit(-1.0, str(e))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_meaning_progress(self, frac: float, state: str):
        if state == "download":
            self.meaning_status.setText(tr("Downloading… {}%").format(int(frac * 100)))
        elif state == "prepare":
            self.meaning_status.setText(tr("Preparing your documents for search by meaning… {}%").format(int(frac * 100)))
        else:
            self._meaning_job = None; self._refresh_meaning()
            if frac < 0 and "cancelled" not in state:
                self.meaning_status.setText(tr("Search by meaning could not be set up: {}").format(tr(state)))

    def _fill(self):
        self.listw.clear()
        for d in self.lib.info():
            gone = "  ·  ⚠ " + tr("the file is no longer there") if d.get("missing") else ""
            it = QListWidgetItem(f"{d['name']}\n{d['parts']} {tr('passages')}  ·  {d['added']}{gone}  ·  {d['path']}")
            it.setData(Qt.ItemDataRole.UserRole, d["name"]); self.listw.addItem(it)
        if not self.listw.count():
            self.listw.addItem(QListWidgetItem(tr("No documents yet"))); self.listw.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def add_paths(self, paths_: list):
        """Index files and folders now (shows a busy cursor). Used by the buttons and by the tests."""
        import docs
        from PySide6.QtWidgets import QApplication
        added, problems = 0, []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in paths_:
                try:
                    if os.path.isdir(p):
                        r = self.lib.add_folder(p); added += len(r["added"])
                        problems += [f"{n}: {why}" for n, why in r["skipped"]]
                    else:
                        self.lib.add_file(p, progress=self._reading_page); added += 1
                except docs.DocError as e:
                    problems.append(f"{os.path.basename(p)}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText(tr("Added {} documents.").format(added) + (("  " + tr("Could not read:") + " " + "; ".join(problems[:4])) if problems else ""))
        self._fill()

    def _reading_page(self, done: int, total: int):
        """Scanned pages take a moment each: say where we are and keep the window alive."""
        from PySide6.QtWidgets import QApplication
        self.status.setText(tr("Reading scanned page {} of {}…").format(done + 1, total)); QApplication.processEvents()

    def _add_files(self):
        from PySide6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(self, tr("Add file"), os.path.expanduser("~"),
                                                "Documents (*.pdf *.docx *.pptx *.xlsx *.numbers *.doc *.rtf *.odt *.txt *.md *.csv *.html "
                                                "*.png *.jpg *.jpeg *.tiff *.heic);;All (*.*)")
        if files: self.add_paths(files)

    def _add_folder(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, tr("Add folder"), os.path.expanduser("~"))
        if folder: self.add_paths([folder])

    def _remove(self):
        it = self.listw.currentItem(); name = it.data(Qt.ItemDataRole.UserRole) if it else None
        if name: self.lib.remove(name); self._fill()

    def _clear(self):
        if self.lib.names() and QMessageBox.question(self, tr("Remove all"), tr("Remove every document from NOVA? The files themselves are not touched."),
                                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                     QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.lib.clear(); self._fill()


# ── Scheduled tasks ────────────────────────────────────────────────
def schedule_when(task: dict) -> str:
    """'every day at 08:00' in the interface language."""
    import schedule as sched
    template, args = sched.describe_parts(task)
    if template == "every {} at {}":
        args = (", ".join(tr(d) for d in args[0].split(", ")), args[1])
    return tr(template).format(*args)



class ScheduleEditDialog(QDialog):
    """A new scheduled task: what, reminder or request, time of day, which days."""
    REPEATS = (("Every day", "daily"), ("Weekdays (Mon–Fri)", "weekdays"), ("Weekends", "weekends"),
               ("Once", "once"), ("Chosen days", "custom"))

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        import schedule as sched
        from PySide6.QtWidgets import QTimeEdit, QCheckBox
        from PySide6.QtCore import QTime
        self._sched = sched
        self.setWindowTitle(tr("New scheduled task")); self.setMinimumWidth(440); self.setStyleSheet(_style(theme))
        form = QFormLayout(self); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
        self.kind = QComboBox(); self.kind.setAccessibleName(tr("Kind"))
        self.kind.addItem(tr("Ask NOVA (it answers at that time)"), "ask"); self.kind.addItem(tr("Reminder (just show the text)"), "reminder")
        self.text = QLineEdit(); self.text.setAccessibleName(tr("What"))
        self.text.setPlaceholderText(tr("e.g. Give me today's news and the weather"))
        self.time = QTimeEdit(QTime(8, 0)); self.time.setDisplayFormat("HH:mm"); self.time.setAccessibleName(tr("Time"))
        self.repeat = QComboBox(); self.repeat.setAccessibleName(tr("Repeat"))
        for label, value in self.REPEATS: self.repeat.addItem(tr(label), value)
        days = QHBoxLayout(); self.day_boxes = []
        for i, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            cb = QCheckBox(tr(name)); cb.setChecked(i < 5); self.day_boxes.append(cb); days.addWidget(cb)
        days.addStretch()
        self.problem = QLabel(""); self.problem.setWordWrap(True)
        form.addRow(tr("Kind") + ":", self.kind); form.addRow(tr("What") + ":", self.text)
        form.addRow(tr("Time") + ":", self.time); form.addRow(tr("Repeat") + ":", self.repeat); form.addRow("", days)
        form.addRow(self.problem)
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Save"), self._ok))
        form.addRow(row)
        self.repeat.currentIndexChanged.connect(self._toggle_days); self._toggle_days()
        self.task = None

    def _toggle_days(self, *_a):
        on = self.repeat.currentData() == "custom"
        for cb in self.day_boxes: cb.setEnabled(on)

    def _ok(self):
        repeat = self.repeat.currentData()
        if repeat == "custom":
            repeat = ",".join(self._sched.DAY_NAMES[i] for i, cb in enumerate(self.day_boxes) if cb.isChecked()) or "?"
        try:
            self.task = self._sched.make(self.kind.currentData(), self.text.text(), self.time.time().toString("HH:mm"), repeat)
        except self._sched.ScheduleError as e:
            self.problem.setText("⚠️  " + str(e)); return
        self.accept()


class ScheduleDialog(QDialog):
    """Everything NOVA does by itself at set times: add, turn off, delete."""
    def __init__(self, theme: dict, path: str, lock, parent=None):
        super().__init__(parent)
        import schedule as sched
        self._sched = sched; self.t = theme; self.path = path; self.lock = lock
        self.setWindowTitle(tr("Scheduled tasks")); self.setMinimumSize(560, 400); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        note = QLabel(tr("NOVA runs these while it is open. If it was closed at the set time, a task still runs when you "
                         "open NOVA within a few hours. You can also just ask: “every morning at 8 give me the news”."))
        note.setWordWrap(True); v.addWidget(note)
        import platform_utils as plat
        if plat.IS_MAC and not plat.autostart_enabled():
            tip = QLabel(tr("Tip: turn on “Launch at login” in Settings → General and NOVA waits in the menu bar, "
                            "so these run without you opening it."))
            tip.setWordWrap(True); v.addWidget(tip)
        self.listw = QListWidget(); self.listw.setAccessibleName(tr("Scheduled tasks")); self.listw.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(_btn(tr("Add") + "…", self._add))
        self.toggle_btn = _btn(tr("Turn off / on"), self._toggle, True, theme); row.addWidget(self.toggle_btn)
        row.addWidget(_btn(tr("Delete"), self._delete, True, theme)); row.addStretch()
        row.addWidget(_btn(tr("Close"), self.accept, True, theme))
        v.addWidget(self.listw, 1); v.addLayout(row)
        self._fill()

    def _tasks(self) -> list:
        with self.lock: return self._sched.load(self.path)

    def _fill(self):
        self.listw.clear()
        for t in self._tasks():
            nxt = self._sched.next_run(t)
            when = tr("next: {}").format(nxt.strftime("%a %d %b %H:%M")) if nxt else tr("turned off")
            icon = "🔔" if t["kind"] == "reminder" else "💬"
            it = QListWidgetItem(f"{icon}  {t['text']}\n{schedule_when(t)}  ·  {when}")
            it.setData(Qt.ItemDataRole.UserRole, t["id"]); self.listw.addItem(it)
        if not self.listw.count():
            self.listw.addItem(QListWidgetItem(tr("Nothing is scheduled"))); self.listw.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _current(self):
        it = self.listw.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _ask(self):
        """Open the form. Returns the new task or None (separate so tests can stand in for the form)."""
        d = ScheduleEditDialog(self.t, self)
        return d.task if d.exec() == QDialog.DialogCode.Accepted else None

    def _add(self):
        task = self._ask()
        if task:
            with self.lock:
                tasks = self._sched.load(self.path); tasks.append(task); self._sched.save(self.path, tasks)
            self._fill()

    def _toggle(self):
        tid = self._current()
        if tid is None: return
        with self.lock:
            tasks = self._sched.load(self.path)
            for t in tasks:
                if t["id"] == tid: t["enabled"] = not t.get("enabled", True)
            self._sched.save(self.path, tasks)
        self._fill()

    def _delete(self):
        tid = self._current()
        if tid is None: return
        with self.lock:
            self._sched.save(self.path, [t for t in self._sched.load(self.path) if t["id"] != tid])
        self._fill()


# ── Modes and saved prompts ────────────────────────────────────────
class NamedTextDialog(QDialog):
    """A name and a text - used for one custom mode or one saved prompt."""
    def __init__(self, theme: dict, title: str, name_label: str, text_label: str, name: str = "", text: str = "", parent=None,
                 check_label: str = "", checked: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title); self.setMinimumWidth(460); self.setStyleSheet(_style(theme))
        form = QFormLayout(self); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
        self.name = QLineEdit(name); self.name.setAccessibleName(name_label)
        self.text = QTextEdit(); self.text.setAcceptRichText(False); self.text.setPlainText(text); self.text.setMinimumHeight(120)
        self.text.setAccessibleName(text_label)
        form.addRow(name_label + ":", self.name); form.addRow(text_label + ":", self.text)
        self.check = None
        if check_label:                                    # an optional yes / no that belongs to the entry
            from PySide6.QtWidgets import QCheckBox
            self.check = QCheckBox(check_label); self.check.setChecked(bool(checked)); form.addRow("", self.check)
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Save"), self.accept))
        form.addRow(row)

    def values(self):
        return self.name.text().strip(), self.text.toPlainText().strip()

    def checked(self) -> bool:
        return bool(self.check is not None and self.check.isChecked())


def clean_actions(actions) -> dict:
    """Selected-text actions as stored in the settings, tidied: {name: {"prompt": text, "replace": bool}}.
    (A plain text instead of the inner dict is accepted too.)"""
    out = {}
    for name, a in (actions.items() if isinstance(actions, dict) else []):
        prompt = (a.get("prompt", "") if isinstance(a, dict) else a if isinstance(a, str) else "")
        name = " ".join(str(name).split())[:30]; prompt = str(prompt).strip()[:4000]
        if name and prompt: out[name] = {"prompt": prompt, "replace": bool(isinstance(a, dict) and a.get("replace"))}
    return out


class PromptsDialog(QDialog):
    """Your own modes, saved prompts and selected-text actions. Result: modes_result() / prompts_result() / actions_result()."""
    KINDS = ("prompts", "modes", "actions")

    def __init__(self, theme: dict, custom_modes: dict, saved_prompts: dict, parent=None, selection_actions: dict = None,
                 tab: str = ""):
        super().__init__(parent)
        from PySide6.QtWidgets import QTabWidget, QWidget
        self.t = theme
        actions = clean_actions(selection_actions)
        self._data = {"modes": dict(custom_modes or {}), "prompts": dict(saved_prompts or {}),
                      "actions": {n: a["prompt"] for n, a in actions.items()}}
        self._replace = {n for n, a in actions.items() if a["replace"]}       # actions whose answer replaces the selection
        self.setWindowTitle(tr("Modes and saved prompts")); self.setMinimumSize(560, 430); self.setStyleSheet(
            _style(theme) + f"QTabWidget::pane{{border:1px solid {theme['ai_br']};border-radius:8px;}}"
                            f"QTabBar::tab{{background:transparent;color:{theme['sys_fg']};padding:7px 14px;border:none;}}"
                            f"QTabBar::tab:selected{{color:{theme['ai_fg']};border-bottom:2px solid {theme['accent']};}}")
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        self.tabs = QTabWidget(); self.tabs.setAccessibleName(tr("Modes and saved prompts")); self.lists = {}
        notes = {"prompts": tr("Reusable prompts. Type /name in the message box, followed by your text."),
                 "modes": tr("Your own modes, next to Coder, Translator, Tutor and Writer. A mode tells NOVA how to behave until you switch back."),
                 "actions": tr("Your own actions for the menu that {} opens on selected text. "
                               "The selected text is added after your instruction.").format(plat.SELECTION_HOTKEY_LABEL)}
        for kind, title in (("prompts", tr("Saved prompts")), ("modes", tr("My modes")), ("actions", tr("Selected-text actions"))):
            page = QWidget(); pv = QVBoxLayout(page); pv.setContentsMargins(10, 10, 10, 10)
            note = QLabel(notes[kind]); note.setWordWrap(True); pv.addWidget(note)
            lw = QListWidget(); lw.setAccessibleName(title); lw.setWordWrap(True)
            lw.itemDoubleClicked.connect(lambda _i, k=kind: self._edit(k)); self.lists[kind] = lw
            row = QHBoxLayout()
            row.addWidget(_btn(tr("Add"), lambda _=False, k=kind: self._add(k)))
            row.addWidget(_btn(tr("Edit"), lambda _=False, k=kind: self._edit(k), True, theme))
            row.addWidget(_btn(tr("Delete"), lambda _=False, k=kind: self._delete(k), True, theme)); row.addStretch()
            pv.addWidget(lw, 1); pv.addLayout(row)
            self.tabs.addTab(page, title)
        v.addWidget(self.tabs, 1)
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Save"), self.accept))
        v.addLayout(row)
        for kind in self.KINDS: self._fill(kind)
        if tab in self.KINDS: self.tabs.setCurrentIndex(self.KINDS.index(tab))

    def modes_result(self) -> dict: return dict(self._data["modes"])
    def prompts_result(self) -> dict: return dict(self._data["prompts"])
    def actions_result(self) -> dict:
        return {n: {"prompt": p, "replace": n in self._replace} for n, p in self._data["actions"].items()}

    def _fill(self, kind: str):
        import modes
        lw = self.lists[kind]; lw.clear()
        for name in sorted(self._data[kind]):
            text = " ".join(str(self._data[kind][name]).split())
            shown = ("/" + modes.clean_name(name)) if kind == "prompts" else name
            if kind == "actions" and name in self._replace: shown += "   ⟲ " + tr("replaces the selection")
            it = QListWidgetItem(f"{shown}\n{text[:110]}{'…' if len(text) > 110 else ''}")
            it.setData(Qt.ItemDataRole.UserRole, name); lw.addItem(it)

    def _current(self, kind: str):
        it = self.lists[kind].currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _ask(self, kind: str, name: str = "", text: str = ""):
        """Open the form; returns (name, text) - for an action (name, text, replace) - or None.
        Separate so tests can stand in for the form."""
        if kind == "actions":
            d = NamedTextDialog(self.t, tr("Selected-text action"), tr("Name (shown in the menu)"), tr("What NOVA should do with the text"),
                                name, text, self, tr("The answer replaces the selected text (rewrites, translations)"),
                                name in self._replace)
            return (d.values() + (d.checked(),)) if d.exec() == QDialog.DialogCode.Accepted else None
        labels = (tr("Name (used as /name)"), tr("Prompt")) if kind == "prompts" else (tr("Name"), tr("How NOVA should behave"))
        d = NamedTextDialog(self.t, tr("Saved prompt") if kind == "prompts" else tr("Mode"), labels[0], labels[1], name, text, self)
        return d.values() if d.exec() == QDialog.DialogCode.Accepted else None

    def _store(self, kind: str, old: str, result):
        import modes
        if not result: return
        name, text = result[0], result[1]
        if kind == "prompts": name = modes.clean_name(name)
        if kind == "actions": name = " ".join(name.split())
        if not name or not text: return
        if kind == "modes" and modes.clean_name(name) in modes.BUILTIN: name += " 2"       # built-in names stay built-in
        if old and old != name: self._data[kind].pop(old, None); self._replace.discard(old)
        self._data[kind][name[:30]] = text[:4000]
        if kind == "actions":
            (self._replace.add if len(result) > 2 and result[2] else self._replace.discard)(name[:30])
        self._fill(kind)

    def _add(self, kind: str): self._store(kind, "", self._ask(kind))

    def _edit(self, kind: str):
        name = self._current(kind)
        if name is not None: self._store(kind, name, self._ask(kind, name, str(self._data[kind][name])))

    def _delete(self, kind: str):
        name = self._current(kind)
        if name is not None: self._data[kind].pop(name, None); self._replace.discard(name); self._fill(kind)


# ── MCP tool servers ───────────────────────────────────────────────
def _pairs(text: str) -> dict:
    """'KEY=value' lines -> dict."""
    out = {}
    for line in str(text or "").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip(): out[k.strip()] = v.strip()
    return out


class McpServerDialog(QDialog):
    """One server: a name, the command that starts it (or its web address), and optional settings."""
    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add a tool server")); self.setMinimumWidth(500); self.setStyleSheet(_style(theme))
        form = QFormLayout(self); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
        warn = QLabel(tr("A tool server is a program that runs on your Mac with your permissions, or a web service that "
                         "receives what NOVA sends it. Only add servers you trust."))
        warn.setWordWrap(True); form.addRow(warn)
        self.name = QLineEdit(); self.name.setAccessibleName(tr("Name")); self.name.setPlaceholderText("github")
        self.target = QLineEdit(); self.target.setAccessibleName(tr("Command or web address"))
        self.target.setPlaceholderText("npx -y @modelcontextprotocol/server-filesystem ~/Documents   |   https://example.com/mcp")
        self.extra = QTextEdit(); self.extra.setAcceptRichText(False); self.extra.setFixedHeight(70)
        self.extra.setAccessibleName(tr("Settings (KEY=value, one per line)"))
        self.extra.setPlaceholderText("GITHUB_TOKEN=…        (" + tr("for a web address: Authorization=Bearer …") + ")")
        self.problem = QLabel(""); self.problem.setWordWrap(True)
        form.addRow(tr("Name") + ":", self.name); form.addRow(tr("Command or web address") + ":", self.target)
        form.addRow(tr("Settings (KEY=value, one per line)") + ":", self.extra); form.addRow(self.problem)
        row = QHBoxLayout(); row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Add"), self._ok))
        form.addRow(row)
        self.result_pair = None

    def _ok(self):
        import mcp_client
        name = mcp_client.safe_name(self.name.text())[:24] if self.name.text().strip() else ""
        target = self.target.text().strip()
        if not name or not target:
            self.problem.setText("⚠️  " + tr("Give the server a name and a command or web address.")); return
        extra = _pairs(self.extra.toPlainText())
        spec = {"url": target, "headers": extra} if target.lower().startswith(("http://", "https://")) else {"command": target, "env": extra}
        self.result_pair = (name, mcp_client.normalise(spec)); self.accept()


class McpDialog(QDialog):
    """The connected tool servers: add, paste a definition, turn off, remove. Result: servers()."""
    def __init__(self, theme: dict, servers: dict, status_fn=None, parent=None):
        super().__init__(parent)
        import mcp_client
        self._mc = mcp_client; self.t = theme; self._status = status_fn or (lambda: {})
        self._servers = {n: mcp_client.normalise(s) for n, s in (servers or {}).items() if isinstance(s, dict)}
        self.setWindowTitle(tr("Tool servers (MCP)")); self.setMinimumSize(600, 420); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        note = QLabel(tr("MCP servers give NOVA extra tools - for GitHub, Notion, databases, your files and much more. "
                         "NOVA asks before it uses a server's tool for the first time, and treats what a server returns as untrusted."))
        note.setWordWrap(True); v.addWidget(note)
        self.listw = QListWidget(); self.listw.setAccessibleName(tr("Tool servers (MCP)")); self.listw.setWordWrap(True)
        self.status = QLabel(""); self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(_btn(tr("Add") + "…", self._add)); row.addWidget(_btn(tr("Paste JSON") + "…", self._paste, True, theme))
        row.addWidget(_btn(tr("Turn off / on"), self._toggle, True, theme)); row.addWidget(_btn(tr("Remove"), self._remove, True, theme))
        row.addStretch()
        row.addWidget(_btn(tr("Cancel"), self.reject, True, theme)); row.addWidget(_btn(tr("Save"), self.accept))
        v.addWidget(self.listw, 1); v.addWidget(self.status); v.addLayout(row)
        self._fill()

    def servers(self) -> dict:
        return {n: dict(s) for n, s in self._servers.items()}

    def _fill(self):
        live = self._status() or {}
        self.listw.clear()
        for name in sorted(self._servers):
            s = self._servers[name]
            state, n_tools, error = live.get(name, ("", 0, ""))
            if not s["enabled"]: head = "○  " + name + "  —  " + tr("turned off")
            elif state == "ready": head = "●  " + name + "  —  " + tr("connected, {} tools").format(n_tools)
            elif state == "error": head = "⚠  " + name + "  —  " + (error or tr("could not be connected"))[:140]
            elif state == "starting": head = "…  " + name + "  —  " + tr("connecting")
            else: head = "○  " + name + "  —  " + tr("connects when you save")
            where = s["url"] or " ".join([s["command"], *s["args"]])
            it = QListWidgetItem(f"{head}\n{where[:160]}"); it.setData(Qt.ItemDataRole.UserRole, name); self.listw.addItem(it)
        if not self.listw.count():
            self.listw.addItem(QListWidgetItem(tr("No tool servers yet"))); self.listw.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _current(self):
        it = self.listw.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _ask(self):
        """Open the form; returns (name, spec) or None. Separate so tests can stand in for the form."""
        d = McpServerDialog(self.t, self)
        return d.result_pair if d.exec() == QDialog.DialogCode.Accepted else None

    def _add(self):
        pair = self._ask()
        if pair: self._servers[pair[0]] = pair[1]; self._fill()

    def _ask_json(self):
        text, ok = QInputDialog.getMultiLineText(self, tr("Paste JSON"), tr("Paste the server definition (the “mcpServers” JSON many apps use):"))
        return text if ok else None

    def _paste(self):
        text = self._ask_json()
        if not text or not text.strip(): return
        try:
            found = self._mc.parse_pasted(text)
        except self._mc.MCPError as e:
            self.status.setText("⚠️  " + str(e)); return
        self._servers.update(found)
        self.status.setText(tr("Added: {}").format(", ".join(sorted(found)))); self._fill()

    def _toggle(self):
        name = self._current()
        if name: self._servers[name]["enabled"] = not self._servers[name]["enabled"]; self._fill()

    def _remove(self):
        name = self._current()
        if name: self._servers.pop(name, None); self._fill()


# ── Usage and cost ─────────────────────────────────────────────────
class UsageDialog(QDialog):
    """Requests and tokens per model, and an estimated cost from prices the user can edit. Result: prices()."""
    PERIODS = (("Today", 1), ("Last 7 days", 7), ("Last 30 days", 30), ("Last 12 months", 365))

    def __init__(self, theme: dict, prices: dict = None, parent=None):
        super().__init__(parent)
        import usage
        self._usage = usage; self._prices = {k: list(v) for k, v in (prices or {}).items()}
        self.setWindowTitle(tr("Usage and cost")); self.setMinimumSize(680, 440); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        note = QLabel(tr("Tokens are counted from what each AI provider reports. The cost is only an estimate from the prices per "
                         "million tokens set here - your provider's bill is what counts. Models running on this Mac are free."))
        note.setWordWrap(True); v.addWidget(note)
        self.period = QComboBox(); self.period.setAccessibleName(tr("Period"))
        for label, days in self.PERIODS: self.period.addItem(tr(label), days)
        self.period.currentIndexChanged.connect(self._fill)
        self.table = QTableWidget(0, 6); self.table.setAccessibleName(tr("Usage and cost"))
        self.table.setHorizontalHeaderLabels([tr("Provider"), tr("Model"), tr("Requests"), tr("Tokens in"), tr("Tokens out"), tr("Est. cost")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.total = QLabel(""); self.total.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(_btn(tr("Set price for the selected model") + "…", self._set_price, True, theme)); row.addStretch()
        row.addWidget(_btn(tr("Close"), self.accept))
        v.addWidget(self.period); v.addWidget(self.table, 1); v.addWidget(self.total); v.addLayout(row)
        self._fill()

    def prices(self) -> dict:
        return {k: list(v) for k, v in self._prices.items()}

    def _fill(self, *_a):
        u = self._usage
        s = u.summary(u.entries(self.period.currentData() or 1), self._prices)
        self._rows = s["rows"]
        self.table.setRowCount(len(s["rows"]))
        for r, row in enumerate(s["rows"]):
            cells = (row["provider"], row["model"], u.count(row["requests"]), u.count(row["in"]), u.count(row["out"]), u.money(row["cost"]))
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        if not s["rows"]:
            self.total.setText(tr("No requests in this period.")); return
        text = tr("{} requests · {} tokens in · {} tokens out · about {}").format(u.count(s["requests"]), u.count(s["in"]), u.count(s["out"]), u.money(s["cost"]))
        if s["unpriced"]:
            text += "\n" + tr("No price is set for: {} (not included in the total).").format(", ".join(s["unpriced"]))
        self.total.setText(text)

    def _ask_price(self, model: str, current):
        """Returns (input, output) in USD per million tokens, or None. Separate so tests can stand in for the prompt."""
        shown = f"{current[0]:g} / {current[1]:g}" if current else ""
        text, ok = QInputDialog.getText(self, tr("Price"), tr("Price for {} in USD per million tokens, as input / output (for example 4 / 20):").format(model), text=shown)
        if not ok: return None
        import re
        nums = re.findall(r"\d+(?:[.,]\d+)?", text)
        if len(nums) != 2: return ()
        return float(nums[0].replace(",", ".")), float(nums[1].replace(",", "."))

    def _set_price(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self._rows): return
        row = self._rows[r]
        got = self._ask_price(row["model"], self._usage.price_for(row["model"], row["provider"], self._prices))
        if got is None: return
        if not got:
            self.total.setText("⚠️  " + tr("Enter two numbers, for example 4 / 20.")); return
        self._prices[row["model"]] = [got[0], got[1]]
        self._fill()


# ── Read-only viewers: activity log, "what NOVA sent" ──────────────
def format_activity(lines: list) -> str:
    """Activity-log records (JSON lines) as readable text, newest first."""
    out = []
    for l in reversed(lines[-400:]):
        try: e = json.loads(l)
        except ValueError: continue
        if not isinstance(e, dict): continue
        args = ", ".join(f"{k}={v}" for k, v in (e.get("args") or {}).items())
        out.append(f"{e.get('t', '')}   {'✓' if e.get('ok', True) else '✗'}  {e.get('tool', '?')}   [{e.get('outcome', '')}]"
                   + (f"\n      {args}" if args else "") + (f"\n      → {e.get('result')}" if e.get("result") else ""))
    return "\n\n".join(out)


class TextViewDialog(QDialog):
    def __init__(self, theme: dict, title: str, text: str, note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.setMinimumSize(620, 460); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        if note:
            n = QLabel(note); n.setWordWrap(True); v.addWidget(n)
        self.view = QTextEdit(); self.view.setReadOnly(True); self.view.setPlainText(text); self.view.setAccessibleName(title)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(_btn(tr("Close"), self.accept))
        v.addWidget(self.view, 1); v.addLayout(row)


class SentDialog(QDialog):
    """Where NOVA sent data, what kind and how much. The content itself is never recorded."""
    PERIODS = (("Today", 1), ("Last 7 days", 7), ("Last 30 days", 30))

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("What NOVA sent")); self.setMinimumSize(640, 480); self.setStyleSheet(_style(theme))
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        note = QLabel(tr("Every time NOVA sends something off this Mac it notes where it went, what kind of thing it was "
                         "and how big — never the content itself. Requests to a server on this Mac are marked local."))
        note.setWordWrap(True); v.addWidget(note)
        self.period = QComboBox(); self.period.setAccessibleName(tr("Period"))
        for label, days in self.PERIODS: self.period.addItem(tr(label), days)
        self.period.currentIndexChanged.connect(self._fill)
        self.table = QTableWidget(0, 4); self.table.setAccessibleName(tr("What NOVA sent"))
        self.table.setHorizontalHeaderLabels([tr("Destination"), tr("What"), tr("Requests"), tr("Data sent")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.total = QLabel("")
        self.details = QTextEdit(); self.details.setReadOnly(True); self.details.setAccessibleName(tr("Details"))
        row = QHBoxLayout(); row.addWidget(self.total); row.addStretch(); row.addWidget(_btn(tr("Close"), self.accept))
        v.addWidget(self.period); v.addWidget(self.table, 2); v.addWidget(QLabel(tr("Details") + ":")); v.addWidget(self.details, 2)
        v.addLayout(row); self._fill()

    def _fill(self, *_a):
        items = ledger.entries(self.period.currentData() or 1)
        rows = ledger.summary(items)
        self.table.setRowCount(len(rows))
        for r, (dest, what, n, b) in enumerate(rows):
            shown = dest + ("  (" + tr("this Mac") + ")" if ledger.is_local(dest) else "")
            for c, text in enumerate((shown, tr(what), str(n), ledger.human(b) if b else "—")):
                self.table.setItem(r, c, QTableWidgetItem(text))
        off_mac = [e for e in items if not ledger.is_local(e.get("dest", ""))]
        self.total.setText(tr("{} requests left this Mac, about {} in total.").format(
            len(off_mac), ledger.human(sum(int(e.get("bytes", 0) or 0) for e in off_mac))) if items else tr("Nothing was sent."))
        self.details.setPlainText("\n".join(
            f"{e.get('t', '')}   {e.get('dest', '?')}   {e.get('what', '')}   {ledger.human(int(e.get('bytes', 0) or 0))}"
            + (f"   ({e.get('detail')})" if e.get("detail") else "") for e in reversed(items[-500:])))


# ── "Send this to the AI?" previews ────────────────────────────────
def _pil_to_pixmap(img, max_w=480):
    rgb = img.convert("RGB"); w, h = rgb.size
    qi = QImage(rgb.tobytes("raw", "RGB"), w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qi).scaledToWidth(min(max_w, w), Qt.TransformationMode.SmoothTransformation)


def _ai_name() -> str:
    """Who receives uploads: the active AI provider (a local one is said to be on this Mac)."""
    import providers, models
    pid = models.provider()
    return providers.label(pid) + (" (" + tr("this Mac") + ")" if providers.info(pid).get("local") else "")


def confirm_image_upload(parent, theme: dict, pil_image, what: str) -> bool:
    d = QDialog(parent); d.setWindowTitle(tr("Send to the AI?")); d.setStyleSheet(_style(theme))
    v = QVBoxLayout(d); v.setContentsMargins(16, 14, 16, 14)
    v.addWidget(QLabel(tr("This image will be sent to {} for analysis:").format(_ai_name()) + f"\n{what}"))
    pic = QLabel(); pic.setPixmap(_pil_to_pixmap(pil_image)); pic.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(pic)
    row = QHBoxLayout(); row.addStretch()
    row.addWidget(_btn(tr("Cancel"), d.reject, True, theme)); send = _btn(tr("Send to AI"), d.accept); send.setDefault(True)
    row.addWidget(send); v.addLayout(row)
    d.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return d.exec() == QDialog.DialogCode.Accepted


def confirm_text_upload(parent, theme: dict, name: str, text: str) -> bool:
    d = QDialog(parent); d.setWindowTitle(tr("Send to the AI?")); d.setStyleSheet(_style(theme)); d.setMinimumWidth(460)
    v = QVBoxLayout(d); v.setContentsMargins(16, 14, 16, 14)
    v.addWidget(QLabel(tr("This text will be sent to {}:").format(_ai_name()) + f"\n{name}  ({len(text)} " + tr("characters") + ")"))
    box = QTextEdit(); box.setReadOnly(True); box.setPlainText(text[:1500] + ("…" if len(text) > 1500 else "")); box.setMinimumHeight(160)
    v.addWidget(box)
    row = QHBoxLayout(); row.addStretch()
    row.addWidget(_btn(tr("Cancel"), d.reject, True, theme)); send = _btn(tr("Send to AI"), d.accept); send.setDefault(True)
    row.addWidget(send); v.addLayout(row)
    d.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return d.exec() == QDialog.DialogCode.Accepted
