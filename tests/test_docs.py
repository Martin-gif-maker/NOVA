"""Ask about your documents: real PDF / Word / PowerPoint / rich-text files are created here and read back."""
import sys, zipfile
import pytest
import docs, tools, paths, storage

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS PDFKit / textutil")


# ── making real files ──────────────────────────────────────────────
def make_pdf(path, pages):
    """A real PDF with selectable text, one string per page."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPdfWriter, QPainter, QPageSize
    QApplication.instance() or QApplication([])
    w = QPdfWriter(str(path)); w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    p = QPainter(w)
    for i, text in enumerate(pages):
        if i: w.newPage()
        y = 300
        for line in text.split("\n"):
            p.drawText(300, y, line); y += 260
    p.end()
    return str(path)


def make_docx(path, paragraphs):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{t[:len(t)//2]}</w:t></w:r><w:r><w:t>{t[len(t)//2:]}</w:t></w:r></w:p>" for t in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return str(path)


def make_pptx(path, slides):
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        for i, text in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'<?xml version="1.0"?><p:sld xmlns:p="x" xmlns:a="{A}"><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
    return str(path)


@pytest.fixture
def lib(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DOCS_FILE", str(tmp_path / "data" / "documents.json"))
    return docs.library()


# ── extraction ─────────────────────────────────────────────────────
@mac_only
def test_pdf_text_comes_out_page_by_page(tmp_path):
    f = make_pdf(tmp_path / "report.pdf", ["Annual report 2025\nRevenue was 4.2 million euro", "Outlook\nWe expect growth in Bulgaria"])
    parts = docs.extract(f)
    assert [label for label, _ in parts] == ["p.1", "p.2"]
    assert "Revenue was 4.2 million euro" in parts[0][1] and "growth in Bulgaria" in parts[1][1]
    assert docs.extract_text(f).startswith("[p.1]\nAnnual report 2025")


def test_word_and_powerpoint_text(tmp_path):
    d = make_docx(tmp_path / "contract.docx", ["The tenant pays 900 euro per month.", "Notice period: three months."])
    assert docs.extract(d) == [("", "The tenant pays 900 euro per month.\nNotice period: three months.")]     # runs are joined
    p = make_pptx(tmp_path / "deck.pptx", ["Roadmap for Q4", "Hiring plan: two engineers"])
    assert docs.extract(p) == [("slide 1", "Roadmap for Q4"), ("slide 2", "Hiring plan: two engineers")]


@mac_only
def test_rich_text_goes_through_macos(tmp_path):
    f = tmp_path / "letter.rtf"; f.write_text(r"{\rtf1\ansi Dear Ann,\par the invoice is attached.}")
    assert "the invoice is attached" in docs.extract_text(str(f))


def test_unreadable_files_say_why(tmp_path):
    (tmp_path / "prog.bin").write_bytes(b"\x00\x01" * 50)
    (tmp_path / "empty.txt").write_text("   \n ")
    (tmp_path / "fake.docx").write_text("this is not a zip")
    for name, words in (("prog.bin", "not a text document"), ("empty.txt", "no text"), ("fake.docx", "damaged"), ("missing.pdf", "not found")):
        with pytest.raises(docs.DocError, match=words): docs.extract(str(tmp_path / name))


def page_picture(lines, size=(1240, 1754)):
    """A picture of a printed page - what a scanner produces."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QFont, QColor
    from PySide6.QtCore import Qt, QRect
    QApplication.instance() or QApplication([])
    img = QImage(size[0], size[1], QImage.Format.Format_RGB32); img.fill(QColor("white"))
    p = QPainter(img); p.setPen(QColor("black")); p.setFont(QFont("Helvetica", 28))
    for i, line in enumerate(lines):
        p.drawText(QRect(110, 160 + 90 * i, size[0] - 220, 80), Qt.AlignmentFlag.AlignLeft, line)
    p.end()
    return img


def make_scan(path, pages):
    """A PDF whose pages are pictures (no text layer). A page given as a plain string is real text instead."""
    from PySide6.QtGui import QPdfWriter, QPainter, QPageSize
    from PySide6.QtCore import QRect
    w = QPdfWriter(str(path)); w.setPageSize(QPageSize(QPageSize.PageSizeId.A4)); w.setResolution(150)
    p = QPainter(w)
    for i, page in enumerate(pages):
        if i: w.newPage()
        if isinstance(page, str): p.drawText(150, 200, page)
        elif page: p.drawImage(QRect(0, 0, w.width(), w.height()), page_picture(page))
    p.end()
    return str(path)


needs_ocr = pytest.mark.skipif(sys.platform != "darwin" or not docs.ocr_available(), reason="needs Apple's text recognition")


@needs_ocr
def test_scanned_pdf_is_read_with_text_recognition(tmp_path):
    pytest.importorskip("PySide6")
    f = make_scan(tmp_path / "lease-scan.pdf", [["RENTAL AGREEMENT", "The tenant pays 900 euro per month.", "The deposit is two monthly rents."],
                                                ["Pets are allowed with written permission."]])
    seen = []
    parts = docs.extract(f, progress=lambda done, total: seen.append((done, total)))
    assert [label for label, _ in parts] == ["p.1", "p.2"] and seen == [(0, 2), (1, 2)]
    assert "The deposit is two monthly rents." in parts[0][1] and parts[0][1].startswith("RENTAL AGREEMENT")      # in reading order
    assert "Pets are allowed with written permission." in parts[1][1]


@needs_ocr
def test_only_the_pages_without_text_are_recognised(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    f = make_scan(tmp_path / "mixed.pdf", ["A typed first page with real text in it.", ["A scanned second page."]])
    asked = []
    real = docs._ocr_pdf
    monkeypatch.setattr(docs, "_ocr_pdf", lambda path, wanted, progress=None: (asked.append(list(wanted)), real(path, wanted, progress))[1])
    parts = dict(docs.extract(f))
    assert asked == [[1]] and "typed first page" in parts["p.1"] and "scanned second page" in parts["p.2"]
    monkeypatch.setattr(docs, "OCR_MAX_PAGES", 0)                               # the cap is respected
    assert list(dict(docs.extract(f))) == ["p.1"]


@needs_ocr
def test_pictures_of_text_and_empty_scans(tmp_path):
    pytest.importorskip("PySide6")
    pic = tmp_path / "receipt.png"; page_picture(["Receipt 1042", "Amount due: 310 euro"], (900, 400)).save(str(pic))
    assert "Amount due: 310 euro" in docs.extract_text(str(pic))
    assert "Amount due: 310 euro" in tools.read_file(str(pic))                  # "read the receipt on my Desktop" works
    blank = tmp_path / "blank.png"; page_picture([], (300, 200)).save(str(blank))
    with pytest.raises(docs.DocError, match="No text was found"): docs.extract(str(blank))
    with pytest.raises(docs.DocError, match="no readable text"): docs.extract(make_scan(tmp_path / "empty.pdf", [[]]))


@needs_ocr
def test_folder_indexing_does_not_run_recognition_on_every_photo(lib, tmp_path):
    pytest.importorskip("PySide6")
    folder = tmp_path / "pics"; folder.mkdir()
    page_picture(["holiday photo caption"], (600, 300)).save(str(folder / "IMG_0001.png")); (folder / "notes.txt").write_text("trip notes")
    assert lib.add_folder(str(folder))["added"] == ["notes.txt"]                # a folder of photos is not OCR-ed wholesale
    assert lib.add_file(str(folder / "IMG_0001.png"))["name"] == "IMG_0001.png"  # one picture, added on purpose, is
    assert lib.search("holiday caption")[0]["doc"] == "IMG_0001.png"


@mac_only
def test_scan_without_text_recognition_is_explained(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setattr(docs, "ocr_available", lambda: False)
    with pytest.raises(docs.DocError, match="scan"): docs.extract(make_scan(tmp_path / "scan.pdf", [["some words"]]))


def test_passages_overlap_and_keep_their_page():
    text = "Sentence number %d is here. " * 1
    long = "".join(f"Sentence number {i} is here. " for i in range(200))
    ps = docs.passages([("p.7", long)])
    assert len(ps) > 3 and all(p["at"] == "p.7" and len(p["t"]) <= docs.PASSAGE for p in ps)
    assert all(p["t"].endswith(".") for p in ps[:-1])                        # cut at sentence ends, not mid-word
    joined = " ".join(p["t"] for p in ps)
    assert all(f"Sentence number {i} is here." in joined for i in range(200))   # nothing lost
    assert docs.passages([("", "short")]) == [{"t": "short", "at": ""}] and text


# ── the library ────────────────────────────────────────────────────
def test_search_finds_the_right_passage_and_names_its_source(lib, tmp_path):
    lease = make_docx(tmp_path / "lease.docx", ["The tenant pays 900 euro rent per month.", "The deposit is two monthly rents.",
                                                 "Pets are allowed with written permission."] + [f"Clause {i}: general terms apply." for i in range(60)])
    notes = tmp_path / "trip.txt"; notes.write_text("Flight to Berlin on Friday at 07:40.\nHotel near Alexanderplatz.\n" + "Packing list item.\n" * 200)
    assert lib.add_file(lease)["name"] == "lease.docx" and lib.add_file(str(notes))["parts"] >= 2
    top = lib.search("how much is the deposit?", k=3)[0]
    assert top["doc"] == "lease.docx" and "deposit is two monthly rents" in top["text"]
    assert lib.search("when is my flight", k=2)[0]["doc"] == "trip.txt"
    assert lib.search("rents", k=1)[0]["doc"] == "lease.docx"                 # 'rents' finds 'rent' (stemming)
    assert all(h["doc"] == "trip.txt" for h in lib.search("deposit flight", k=5, document="trip"))
    assert lib.search("zebra quantum", k=3) == [] and lib.search("", k=3) == []
    material = docs.answer_material("deposit")
    assert material.startswith("[lease.docx]") and "two monthly rents" in material


def test_library_survives_restart_and_replaces_same_file(lib, tmp_path):
    f = tmp_path / "a.txt"; f.write_text("first version about apples")
    lib.add_file(str(f)); f.write_text("second version about oranges"); lib.add_file(str(f))
    assert lib.names() == ["a.txt"] and lib.search("oranges")[0]["text"].startswith("second") and lib.search("apples") == []
    fresh = docs.Library(lib.path)                                            # as after quitting and starting again
    assert fresh.names() == ["a.txt"] and fresh.search("oranges")
    other = tmp_path / "sub"; other.mkdir(); (other / "a.txt").write_text("a different file with the same name")
    assert lib.add_file(str(other / "a.txt"))["name"] == "sub/a.txt" and len(lib.names()) == 2
    assert lib.remove("A.TXT") is True and lib.remove("nope") is False and lib.names() == ["sub/a.txt"]
    lib.clear(); assert lib.names() == [] and docs.Library(lib.path).names() == []


def test_folder_indexing_skips_junk_and_reports_problems(lib, tmp_path):
    root = tmp_path / "papers"; (root / "deep").mkdir(parents=True); (root / ".git").mkdir(); (root / "node_modules").mkdir()
    (root / "one.md").write_text("alpha document"); (root / "deep" / "two.txt").write_text("beta document")
    (root / ".git" / "config.txt").write_text("hidden"); (root / "node_modules" / "x.txt").write_text("junk")
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff"); (root / "broken.docx").write_text("not a zip"); (root / ".secret.txt").write_text("hidden")
    seen = []
    r = lib.add_folder(str(root), progress=lambda i, n, name: seen.append(name))
    assert sorted(r["added"]) == ["one.md", "two.txt"] and [n for n, _ in r["skipped"]] == ["broken.docx"] and r["more"] == 0
    assert "damaged" in r["skipped"][0][1] and sorted(seen) == ["broken.docx", "one.md", "two.txt"]
    with pytest.raises(docs.DocError): lib.add_folder(str(tmp_path / "nowhere"))


def test_library_limits(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "MAX_FILE_CHARS", 5000); monkeypatch.setattr(docs, "MAX_TOTAL_CHARS", 9000)
    big = tmp_path / "big.txt"; big.write_text("word " * 4000)
    info = lib.add_file(str(big))
    assert info["cut"] is True and info["chars"] == 5000
    second = tmp_path / "second.txt"; second.write_text("text " * 1200)
    with pytest.raises(docs.DocError, match="library is full"): lib.add_file(str(second))


def test_library_is_encrypted_with_everything_else(lib, tmp_path):
    f = tmp_path / "secret.txt"; f.write_text("the launch code is tulip")
    lib.add_file(str(f))
    assert b"tulip" in open(lib.path, "rb").read()
    assert storage.convert_all(True) >= 1
    raw = open(lib.path, "rb").read()
    assert storage.is_encrypted(raw) and b"tulip" not in raw
    assert docs.Library(lib.path).search("launch code")[0]["text"] == "the launch code is tulip"     # still readable through the app
    storage.convert_all(False)


# ── as tools ───────────────────────────────────────────────────────
def test_document_tools(lib, tmp_path):
    assert isinstance(tools.search_documents("anything"), tools.ToolFailure) and "No documents" in tools.list_documents()
    f = make_docx(tmp_path / "policy.docx", ["Employees get 25 days of paid leave per year."] + ["Filler paragraph."] * 5)
    assert "Indexed policy.docx" in tools.add_document(f)
    out = tools.search_documents("how many days of leave")
    assert out.startswith(tools.UNTRUSTED_NOTE) and "[policy.docx]" in out and "25 days of paid leave" in out
    assert "Nothing in the indexed documents matches" in tools.search_documents("volcano")
    assert "policy.docx" in tools.list_documents()
    folder = tmp_path / "dir"; folder.mkdir(); (folder / "n.txt").write_text("note text")
    assert "Indexed 1 document(s)" in tools.add_document(str(folder))
    assert isinstance(tools.add_document(str(tmp_path / "none.pdf")), tools.ToolFailure)
    assert "Removed" in tools.remove_document("policy.docx") and isinstance(tools.remove_document("policy.docx"), tools.ToolFailure)
    assert "search_documents" in tools.UNTRUSTED_SOURCES                      # a document can carry hidden instructions


@mac_only
def test_read_file_reads_documents_too(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["Invoice 1042\nAmount due 310 euro"])
    out = tools.read_file(pdf)
    assert "Amount due 310 euro" in out and "File: " in out
    long = make_docx(tmp_path / "long.docx", ["A long paragraph of text. " * 40] * 30)
    out = tools.read_file(long, max_chars=500)
    assert "shortened" in out and "search_documents" in out
    assert isinstance(tools.read_file(str(tmp_path / "x.docx")), tools.ToolFailure)
    (tmp_path / "bad.docx").write_text("zzz")
    assert "damaged" in tools.read_file(str(tmp_path / "bad.docx"))
    (tmp_path / "plain.txt").write_text("plain text still works")
    assert "plain text still works" in tools.read_file(str(tmp_path / "plain.txt"))


def test_prompt_lists_document_names_only(lib, tmp_path):
    import prompts
    assert "DOCUMENT LIBRARY" not in prompts._build_prompt()
    f = tmp_path / "salary.txt"; f.write_text("my salary is 5000")
    lib.add_file(str(f))
    p = prompts._build_prompt("anything")
    assert "DOCUMENT LIBRARY" in p and "salary.txt" in p and "5000" not in p     # the content stays on the Mac until asked for


# ── in the window ──────────────────────────────────────────────────
def test_dropping_a_long_document_with_a_question_asks_about_it(win, monkeypatch, tmp_path):
    import win_docs
    f = make_docx(tmp_path / "handbook.docx", ["Remote work is allowed three days per week."] + ["Background paragraph about the company. " * 6] * 80)
    sent = []
    monkeypatch.setattr(win, "_start_ai", lambda *a, **k: sent.append(win.messages[-1]["content"]))
    monkeypatch.setattr(win_docs, "confirm_text_upload", lambda *a: pytest.fail("long documents are never pasted in"))
    win.input_field.setText("how many remote days?")
    from PySide6.QtCore import QUrl, QMimeData
    import types
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(f)])
    win.dropEvent(types.SimpleNamespace(mimeData=lambda: md))
    for _ in range(100):
        win._pump(30)
        if sent: break
    assert sent and sent[0].startswith("how many remote days?") and 'document="handbook.docx"' in sent[0]
    assert "handbook.docx" in win.messages[0]["content"] and win.input_field.toPlainText() == ""
    assert "Remote work is allowed three days" in tools.search_documents("remote days", "handbook.docx")


def test_dropping_a_folder_indexes_it(win, tmp_path):
    import types
    from PySide6.QtCore import QUrl, QMimeData
    folder = tmp_path / "papers"; folder.mkdir(); (folder / "a.md").write_text("alpha"); (folder / "b.txt").write_text("beta")
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(str(folder))])
    win.dropEvent(types.SimpleNamespace(mimeData=lambda: md))
    for _ in range(100):
        win._pump(30)
        if len(docs.library().names()) == 2: break
    win._pump(100)
    assert docs.library().names() == ["a.md", "b.txt"] and "a.md" in win.messages[0]["content"]


def test_documents_window_adds_and_removes(app, lib, tmp_path, monkeypatch):
    import dialogs, themes
    from PySide6.QtWidgets import QMessageBox
    d = dialogs.DocumentsDialog(themes.THEMES["nova"], lib)
    assert d.listw.count() == 1 and d.listw.item(0).text() == "No documents yet"
    good = tmp_path / "plan.txt"; good.write_text("the plan is simple")
    bad = tmp_path / "bad.docx"; bad.write_text("zzz")
    d.add_paths([str(good), str(bad)])
    assert d.listw.count() == 1 and d.listw.item(0).text().startswith("plan.txt") and "Added 1 documents." in d.status.text() and "bad.docx" in d.status.text()
    d.listw.setCurrentRow(0); d._remove(); assert lib.names() == []
    d.add_paths([str(good)])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)); d._clear(); assert lib.names() == ["plan.txt"]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)); d._clear(); assert lib.names() == []


# ── staying true to the files, and searching by more than one wording ─
def _touch_later(path, text):
    """Rewrite a file so that it clearly counts as changed (time stamp two seconds on)."""
    import os
    path.write_text(text); st = os.stat(path); os.utime(path, (st.st_atime, st.st_mtime + 2))


def test_changed_files_are_read_again_and_missing_ones_are_noted(lib, tmp_path):
    f = tmp_path / "prices.txt"; f.write_text("the subscription costs 10 euro")
    g = tmp_path / "old.txt"; g.write_text("an old note about gardening")
    lib.add_file(str(f)); lib.add_file(str(g))
    assert lib.refresh() == {"updated": [], "added": [], "missing": []}        # nothing changed: nothing happens
    _touch_later(f, "the subscription costs 14 euro since October"); g.unlink()
    r = lib.refresh()
    assert r["updated"] == ["prices.txt"] and r["missing"] == ["old.txt"]
    assert "14 euro" in lib.search("subscription")[0]["text"]
    assert lib.search("gardening")[0]["doc"] == "old.txt"                      # what was read stays usable…
    assert {d["name"]: d["missing"] for d in lib.info()} == {"old.txt": True, "prices.txt": False}   # …and is marked
    assert lib.refresh() == {"updated": [], "added": [], "missing": []}        # reported once, not every time
    g.write_text("an old note about gardening"); lib.refresh()
    assert lib.info()[0]["missing"] is False                                   # the file came back


def test_search_tool_sees_a_change_without_any_manual_step(lib, tmp_path):
    f = tmp_path / "plan.txt"; f.write_text("we launch in March")
    tools.add_document(str(f))
    _touch_later(f, "we launch in June")
    assert "launch in June" in tools.search_documents("when do we launch")


def test_new_files_in_an_added_folder_are_picked_up(lib, tmp_path):
    folder = tmp_path / "papers"; folder.mkdir(); (folder / "a.txt").write_text("alpha paper")
    lib.add_folder(str(folder))
    (folder / "b.txt").write_text("beta paper about whales"); (folder / "photo.jpg").write_bytes(b"\xff\xd8")
    assert lib.refresh() == {"updated": [], "added": [], "missing": []}        # a plain refresh only looks at known files
    assert lib.refresh(scan_folders=True)["added"] == ["b.txt"] and lib.search("whales")[0]["doc"] == "b.txt"
    assert docs.Library(lib.path).refresh(scan_folders=True)["added"] == []    # the folder list survives a restart; nothing new now
    lib.clear(); (folder / "c.txt").write_text("gamma")
    assert lib.refresh(scan_folders=True)["added"] == []                       # "remove all" also forgets the folders


def test_several_wordings_find_what_one_wording_misses(lib, tmp_path):
    a = tmp_path / "lease.txt"; a.write_text("The security payment equals two monthly rents and is returned at the end.\n" + "General clause.\n" * 150)
    b = tmp_path / "dogovor.txt"; b.write_text("Депозитът се връща в срок от един месец след напускане.\n" + "Обща клауза.\n" * 150)
    c = tmp_path / "other.txt"; c.write_text("The deposit box at the bank is open on weekdays.\n" + "Filler line.\n" * 150)
    for f in (a, b, c): lib.add_file(str(f))
    one = [h["doc"] for h in lib.search("deposit", k=5)]
    assert one == ["other.txt"]                                               # the literal word only finds the wrong document
    many = docs.search_many(lib, ["deposit", "security payment", "депозит"], k=5)
    assert {h["doc"] for h in many} == {"lease.txt", "dogovor.txt", "other.txt"}
    assert docs.search_many(lib, ["deposit"], 5) == lib.search("deposit", 5)   # one wording behaves as before
    assert docs.search_many(lib, ["", "  "], 5) == []
    out = tools.search_documents("deposit", also="security payment; депозит")
    assert "[lease.txt]" in out and "[dogovor.txt]" in out


def test_a_passage_matching_several_wordings_ranks_first(lib, tmp_path):
    f = tmp_path / "hr.txt"
    f.write_text("Annual leave: employees receive 25 vacation days.\n\n" + "Unrelated paragraph about parking.\n" * 60 +
                 "\n\nSick leave needs a note.\n\n" + "More unrelated text about the canteen.\n" * 60 + "\n\nHolidays follow the public calendar.")
    lib.add_file(str(f))
    top = docs.search_many(lib, ["vacation days", "annual leave", "holidays"], k=3)[0]
    assert "25 vacation days" in top["text"]


# ── spreadsheets ───────────────────────────────────────────────────
def make_xlsx(path):
    """A real Excel workbook written by openpyxl (dates, numbers, text, a gap, a second sheet)."""
    openpyxl = pytest.importorskip("openpyxl")
    import datetime
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Budget"
    ws.append(["Month", "Revenue", "Costs", "Paid on", "Note"])
    ws.append(["January", 1200, 800.5, datetime.date(2026, 1, 31), "first month"])
    ws.append(["February", 1500, 950, datetime.datetime(2026, 2, 28, 14, 30), None])
    ws.append([])
    ws.append(["March", 1800, None, datetime.date(2026, 3, 31), "best so far"])
    ws["G7"] = "far away cell"
    other = wb.create_sheet("People"); other.append(["Ann", 34, True]); other.append(["Борис", 41, False])
    wb.save(str(path))
    return str(path)


def test_excel_rows_become_self_describing_lines(tmp_path):
    parts = dict(docs.extract(make_xlsx(tmp_path / "budget.xlsx")))
    assert list(parts) == ["sheet Budget", "sheet People"]
    lines = parts["sheet Budget"].splitlines()
    assert lines[0] == "Month | Revenue | Costs | Paid on | Note"
    assert lines[1] == "Month: January | Revenue: 1200 | Costs: 800.5 | Paid on: 2026-01-31 | Note: first month"
    assert lines[2] == "Month: February | Revenue: 1500 | Costs: 950 | Paid on: 2026-02-28 14:30"      # empty cells are left out
    assert lines[3] == "Month: March | Revenue: 1800 | Paid on: 2026-03-31 | Note: best so far"         # the blank row is gone
    assert "far away cell" in lines[-1]
    assert parts["sheet People"] == "Ann | 34 | yes\nБорис | 41 | no"          # no header row here: plain rows


def test_a_question_about_a_spreadsheet_finds_the_row(lib, tmp_path):
    lib.add_file(make_xlsx(tmp_path / "budget.xlsx"))
    hit = lib.search("revenue in March")[0]
    assert hit["doc"] == "budget.xlsx" and hit["at"] == "sheet Budget" and "Month: March | Revenue: 1800" in hit["text"]
    assert "Revenue: 1800" in tools.read_file(make_xlsx(tmp_path / "again.xlsx"))


def test_numbers_files_are_read(tmp_path):
    numbers_parser = pytest.importorskip("numbers_parser")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = numbers_parser.Document(); table = doc.sheets[0].tables[0]
        for r, row in enumerate([["City", "Population"], ["Sofia", 1286000], ["Plovdiv", 346000]]):
            for c, v in enumerate(row): table.write(r, c, v)
        f = tmp_path / "cities.numbers"; doc.save(str(f))
    parts = docs.extract(str(f))
    assert parts[0][0].startswith("sheet ") and parts[0][1] == "City | Population\nCity: Sofia | Population: 1286000\nCity: Plovdiv | Population: 346000"


def test_spreadsheet_problems_are_explained(tmp_path, monkeypatch):
    (tmp_path / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0 not really an excel file")
    with pytest.raises(docs.DocError, match="old Excel file could not be read"): docs.extract(str(tmp_path / "old.xls"))
    (tmp_path / "fake.xlsx").write_text("not a zip")
    with pytest.raises(docs.DocError, match="damaged"): docs.extract(str(tmp_path / "fake.xlsx"))
    (tmp_path / "x.numbers").write_text("junk")
    with pytest.raises(docs.DocError, match="Export it to Excel or CSV"): docs.extract(str(tmp_path / "x.numbers"))
    import builtins
    real_import = builtins.__import__
    def no_numbers(name, *a, **k):
        if name == "numbers_parser": raise ImportError("not bundled")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_numbers)
    with pytest.raises(docs.DocError, match="cannot be read by this build"): docs.extract(str(tmp_path / "x.numbers"))


def test_table_text_edge_cases():
    assert docs.table_text([]) == "" and docs.table_text([[None, None], []]) == ""
    assert docs.table_text([["only one column"], ["second row"]]) == "only one column\nsecond row"
    assert docs.table_text([[2024, 2025], [10, 20]]) == "2024 | 2025\n10 | 20"            # numbers on top are data, not a header
    assert docs.table_text([["A", "B"], [1.0, 2.50], [float("nan"), "x"]]) == "A | B\nA: 1 | B: 2.5\nB: x"
    assert docs._col_index("A1") == 0 and docs._col_index("Z9") == 25 and docs._col_index("AB12") == 27


def test_excel_times_and_the_1904_calendar(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    import datetime
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Task", "Starts"]); ws.append(["Stand-up", datetime.time(9, 15)]); ws.append(["Review", datetime.datetime(2026, 10, 9, 14, 30)])
    wb.epoch = openpyxl.utils.datetime.CALENDAR_MAC_1904
    wb.save(str(tmp_path / "times.xlsx"))
    assert dict(docs.extract(str(tmp_path / "times.xlsx")))["sheet Sheet"] == \
        "Task | Starts\nTask: Stand-up | Starts: 09:15:00\nTask: Review | Starts: 2026-10-09 14:30"


# ── search quality on a small mixed library (tests/meaning_corpus.py) ─
def test_questions_in_the_documents_own_words_find_the_right_one_and_others_find_nothing(lib, tmp_path):
    import meaning_corpus as C
    for name, text in C.PASSAGES:
        (tmp_path / name).write_text(text); lib.add_file(str(tmp_path / name))
    for question, wanted in C.EXACT:
        assert lib.search(question)[0]["doc"] == wanted, question
    for question in C.ABSENT:                                        # nothing loosely related is passed off as an answer
        assert lib.search(question) == [], question
    # A reworded question shares no words with the passage: it is found when the AI adds other wordings (the `also`
    # field of search_documents), which is how NOVA searches "by meaning".
    assert docs.search_many(lib, ["How much money do I put down up front for the flat?"])[:1] != [h for h in lib.search("security deposit")][:1]
    hits = docs.search_many(lib, ["How much money do I put down up front for the flat?", "security deposit", "advance payment rent"])
    assert hits[0]["doc"] == "lease.txt"


def test_old_excel_files_are_read_too(lib, tmp_path):
    xlwt = pytest.importorskip("xlwt"); pytest.importorskip("xlrd")
    import datetime
    book = xlwt.Workbook(); sheet = book.add_sheet("Stock")
    date = xlwt.XFStyle(); date.num_format_str = "YYYY-MM-DD"
    for r, row in enumerate([["Item", "Pieces", "Price", "Counted", "Ordered"], ["Болтове M8", 1200, 0.15, datetime.date(2026, 9, 30), True],
                             ["Washers", 80, 0.02, datetime.date(2026, 10, 1), False]]):
        for c, value in enumerate(row):
            if isinstance(value, datetime.date): sheet.write(r, c, value, date)
            else: sheet.write(r, c, value)
    book.add_sheet("Empty")
    f = tmp_path / "stock.xls"; book.save(str(f))
    parts = dict(docs.extract(str(f)))
    assert parts["sheet Stock"].splitlines() == ["Item | Pieces | Price | Counted | Ordered",
                                                 "Item: Болтове M8 | Pieces: 1200 | Price: 0.15 | Counted: 2026-09-30 | Ordered: yes",
                                                 "Item: Washers | Pieces: 80 | Price: 0.02 | Counted: 2026-10-01 | Ordered: no"]
    lib.add_file(str(f))
    assert "Pieces: 80" in lib.search("how many washers")[0]["text"] and "Price: 0.15" in tools.read_file(str(f))
