# win_docs.py — files and folders handed to NOVA: short ones go into the question, long ones into the document library.
# (One of the mixins that make up main.AssistantWindow; `self` is always the window.)
import os
import threading
import logging
from PySide6.QtWidgets import QFileDialog
import docs
from i18n import tr
from prompts import _build_prompt
from dialogs import confirm_text_upload, DocumentsDialog

log = logging.getLogger("nova")

DOC_FILTER = ("Documents (*.pdf *.docx *.pptx *.xlsx *.xls *.numbers *.doc *.rtf *.odt *.txt *.md *.csv *.html);;"
              "Code and text (*.py *.js *.ts *.json *.log *.css *.sql *.sh);;All (*.*)")
_DOCUMENT_TYPES = {".pdf", ".docx", ".pptx", ".doc", ".rtf", ".rtfd", ".odt", ".xlsx", ".xlsm", ".xls", ".numbers"}


class DocsMixin:
    INLINE_LIMIT = 12000            # characters; anything longer is indexed instead of pasted into the question

    def _analyze_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Select file"), os.path.expanduser("~"), DOC_FILTER)
        if not path: return
        question = self.input_field.toPlainText().strip()
        self.input_field.clear()
        self._submit_file(path, question)

    def _submit_file(self, path: str, question: str = ""):
        """Read the file in the background, then either send it with the question or add it to the library."""
        if not self.client: return
        name = os.path.basename(path)
        self.chat_area.add_message(tr("📄  Reading {}…").format(name), "system", self._theme)

        def _bg():
            try:
                parts = docs.extract(path)
                text = "\n\n".join(f"[{label}]\n{t}" if label else t for label, t in parts)
                if len(text) <= self.INLINE_LIMIT:
                    self._doc_ready.emit({"kind": "inline", "name": name, "path": path, "text": text, "question": question})
                else:
                    info = docs.library().add_file(path, parts)
                    self._doc_ready.emit(dict(info, kind="indexed", question=question))
            except docs.DocError as e:
                self._doc_ready.emit({"kind": "error", "name": name, "error": str(e)})
            except Exception as e:
                log.warning("could not read %s: %s", name, e)
                self._doc_ready.emit({"kind": "error", "name": name, "error": str(e)})
        threading.Thread(target=_bg, daemon=True).start()

    def _index_folder(self, folder: str):
        name = os.path.basename(folder.rstrip("/")) or folder
        self.chat_area.add_message(tr("📚  Reading the documents in {}…").format(name), "system", self._theme)

        def _bg():
            try:
                self._doc_ready.emit(dict(docs.library().add_folder(folder), kind="folder", name=name))
            except docs.DocError as e:
                self._doc_ready.emit({"kind": "error", "name": name, "error": str(e)})
        threading.Thread(target=_bg, daemon=True).start()

    def _on_doc_ready(self, r: dict):
        kind = r["kind"]
        if kind == "error":
            self.chat_area.add_message(f"❌ {r['name']}: {r['error']}", "system", self._theme); return
        if kind == "refreshed":
            self.chat_area.add_message(tr("📚  Documents brought up to date: {} changed, {} new.").format(len(r["updated"]), len(r["added"])),
                                       "system", self._theme)
            self._refresh_prompt(); return
        if kind == "folder":
            msg = tr("📚  Added {} documents from {}. Ask anything about them.").format(len(r["added"]), r["name"])
            if r["skipped"]: msg += " " + tr("{} could not be read.").format(len(r["skipped"]))
            if r["more"]: msg += " " + tr("{} more were left out (too many files).").format(r["more"])
            if not r["added"]: msg = tr("No readable documents were found in {}.").format(r["name"])
            self.chat_area.add_message(msg, "system", self._theme)
            self._refresh_prompt(); return
        if kind == "indexed":
            self.chat_area.add_message(
                tr("📚  {} is now in your documents ({} passages). Only the parts that match a question are sent to the AI.")
                .format(r["name"], r["parts"]) + (" " + tr("It is very long, so only the first part was read.") if r.get("cut") else ""),
                "system", self._theme)
            self._refresh_prompt()
            if r.get("question"):
                self._ask_about_document(r["name"], r["question"])
            return
        # short enough to send whole
        if self._busy:
            self.chat_area.add_message(tr("Still working on your previous request - wait for it or press ✕."), "system", self._theme); return
        name, text = r["name"], r["text"]
        if self.config.get("confirm_uploads", True) and not confirm_text_upload(self, self._theme, name, text):
            return
        is_doc = os.path.splitext(name)[1].lower() in _DOCUMENT_TYPES
        question = r.get("question") or ("Summarize this document." if is_doc else "Analyze this file and explain what it does.")
        self.chat_area.add_message(f"📄 {name}  —  {question}", "user", self._theme)
        self.messages.append({"role": "user", "content": f"{question}\n\nFile: {name}\n```\n{text}\n```"})
        self._request_untrusted = "file"              # the file's text could contain instructions: risky tools will ask
        self._start_ai()

    def _ask_about_document(self, name: str, question: str):
        if self._busy:
            self.input_field.setText(question); return
        self._last_user_msg = question
        self.chat_area.add_message(question, "user", self._theme)
        self.messages.append({"role": "user", "content":
                              f"{question}\n\n(This is about the document “{name}” in the document library - "
                              f"use search_documents with document=\"{name}\".)"})
        self._refresh_prompt(question)
        self._start_ai()

    def _refresh_prompt(self, query: str = ""):
        self.messages[0] = {"role": "system", "content": _build_prompt(query)}

    def _refresh_documents(self):
        """In the background: re-read documents that changed on disk and pick up new files in added folders."""
        def _bg():
            try:
                r = docs.library().refresh(scan_folders=True)
            except Exception as e:
                log.info("document refresh failed: %s", e); return
            if r["updated"] or r["added"]:
                self._doc_ready.emit(dict(r, kind="refreshed"))
        if docs.library().names():
            threading.Thread(target=_bg, daemon=True).start()

    def _show_documents(self):
        try: docs.library().refresh(scan_folders=True)
        except Exception as e: log.info("document refresh failed: %s", e)
        dlg = DocumentsDialog(self._theme, docs.library(), self)
        dlg.exec()
        self._refresh_prompt()
