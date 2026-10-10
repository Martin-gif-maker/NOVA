# docs.py — "ask about your documents".
#
# Text is pulled out of PDFs, Word / PowerPoint files, rich text and plain text ON THIS MAC, cut into
# passages and kept in a local index. When you ask something, the best-matching passages are found here
# (BM25, no network) and only those few passages go to the AI together with your question.
import os, re, math, time, zipfile, threading, subprocess, collections
import paths
import storage

MAX_FILE_CHARS  = 3_000_000        # ≈ a 1,000-page book; longer files are cut here
MAX_TOTAL_CHARS = 40_000_000
MAX_FOLDER_FILES = 400
PASSAGE = 1100                     # characters per passage
OVERLAP = 150

TEXTUTIL_TYPES = {".doc", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive", ".wordml"}
ZIP_TYPES      = {".docx", ".pptx"}
SHEET_TYPES    = {".xlsx", ".xlsm", ".xls", ".numbers"}                   # spreadsheets
IMAGE_TYPES    = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".bmp", ".gif"}      # read with text recognition
OCR_MAX_PAGES  = 80                # scanned pages read per document (about half a second each)
PLAIN_TYPES    = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".toml",
                  ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".rb", ".php",
                  ".swift", ".kt", ".sh", ".sql", ".css", ".tex", ".srt"}
SUPPORTED = {".pdf"} | TEXTUTIL_TYPES | ZIP_TYPES | SHEET_TYPES | PLAIN_TYPES          # what folder indexing picks up
READABLE  = SUPPORTED | IMAGE_TYPES                                        # …plus pictures, when added one by one


class DocError(Exception):
    """A document could not be read - the message says why, in plain words."""


# ── getting the text out ───────────────────────────────────────────
# ── text recognition (scans, photos of documents) - Apple's Vision framework, entirely on this Mac ──
def ocr_available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("Vision") is not None
    except (ImportError, ValueError):
        return False


def _recognise(cg_image) -> str:
    """The text in a picture, top to bottom."""
    import Vision
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    if hasattr(request, "setAutomaticallyDetectsLanguage_"): request.setAutomaticallyDetectsLanguage_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, _err = handler.performRequests_error_([request], None)
    if not ok: return ""
    rows = []
    for obs in request.results() or []:
        best = obs.topCandidates_(1)
        if not best: continue
        box = obs.boundingBox()                               # 0…1, origin at the bottom left
        rows.append((round(1.0 - (box.origin.y + box.size.height), 2), box.origin.x, str(best[0].string())))
    rows.sort()
    return "\n".join(text for _y, _x, text in rows)


def _page_image(pdf, index: int, scale: float = 2.5):
    """Draw one PDF page into a picture (about 180 dpi - enough for small print)."""
    import Quartz
    page = Quartz.CGPDFDocumentGetPage(pdf, index + 1)
    if page is None: return None
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    w, h = max(1, int(box.size.width * scale)), max(1, int(box.size.height * scale))
    if w * h > 40_000_000: scale *= (40_000_000 / (w * h)) ** 0.5; w, h = int(box.size.width * scale), int(box.size.height * scale)
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(), Quartz.kCGImageAlphaPremultipliedLast)
    if ctx is None: return None
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1); Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    Quartz.CGContextScaleCTM(ctx, scale, scale); Quartz.CGContextTranslateCTM(ctx, -box.origin.x, -box.origin.y)
    Quartz.CGContextDrawPDFPage(ctx, page)
    return Quartz.CGBitmapContextCreateImage(ctx)


def _ocr_pdf(path: str, wanted: list, progress=None) -> dict:
    """Recognise the text of the given page numbers (0-based). -> {page: text}"""
    import Quartz
    from Foundation import NSURL
    pdf = Quartz.CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(path))
    out = {}
    if pdf is None: return out
    for n, i in enumerate(wanted):
        if progress: progress(n, len(wanted))
        image = _page_image(pdf, i)
        if image is not None: out[i] = _recognise(image)
    return out


def _image_text(path: str) -> str:
    if not ocr_available(): raise DocError("Reading text from pictures is not available in this build.")
    import Quartz
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None) if src is not None else None
    if image is None: raise DocError("This picture could not be opened.")
    text = _recognise(image)
    if not text.strip(): raise DocError("No text was found in this picture.")
    return text


def _pdf_pages(path: str, progress=None) -> list:
    try:
        from Quartz import PDFDocument
        from Foundation import NSURL
    except ImportError:
        raise DocError("PDF reading is not available in this build.")
    doc = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(path))
    if doc is None: raise DocError("This PDF could not be opened (damaged or password-protected).")
    if doc.isLocked(): raise DocError("This PDF is password-protected.")
    pages = []; total = 0
    for i in range(int(doc.pageCount())):
        page = doc.pageAtIndex_(i)
        text = str(page.string() or "") if page is not None else ""
        pages.append(text); total += len(text)
        if total > MAX_FILE_CHARS: break
    blank = [i for i, t in enumerate(pages) if len(t.strip()) < 12]             # scanned pages have no text layer
    if blank and ocr_available():
        for i, text in _ocr_pdf(path, blank[:OCR_MAX_PAGES], progress).items():
            if text.strip(): pages[i] = text
    if not any(p.strip() for p in pages):
        raise DocError("This PDF has no readable text - it is a scan and no text could be recognised in it.")
    return pages


def _xml_text(data: bytes, para_tag: str, text_tag: str) -> str:
    import xml.etree.ElementTree as ET
    out = []
    for para in ET.fromstring(data).iter(para_tag):
        line = "".join(t.text or "" for t in para.iter(text_tag))
        if line.strip(): out.append(line)
    return "\n".join(out)


def _docx_text(path: str) -> str:
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        return _xml_text(z.read("word/document.xml"), W + "p", W + "t")


def _pptx_slides(path: str) -> list:
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        return [_xml_text(z.read(n), A + "p", A + "t") for n in names]


# ── spreadsheets ───────────────────────────────────────────────────
_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | {45, 46, 47} | set(range(50, 59))      # Excel's built-in date / time formats


def _cell_text(value) -> str:
    """One cell as text: whole numbers without '.0', dates as 2026-03-01, nothing for empty cells."""
    import datetime
    if value is None: return ""
    if isinstance(value, bool): return "yes" if value else "no"
    if isinstance(value, float):
        if value != value: return ""                              # NaN
        return str(int(value)) if value == int(value) and abs(value) < 1e15 else f"{value:.10g}"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d") if (value.hour, value.minute, value.second) == (0, 0, 0) else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (datetime.date, datetime.time, datetime.timedelta)): return str(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def table_text(rows: list) -> str:
    """Rows of a table as lines of text. With a header row every line names its columns
    ("Month: March | Revenue: 1800"), so a single line still makes sense when it is found by a search."""
    rows = [[_cell_text(c) for c in row] for row in rows]
    rows = [r for r in rows if any(r)]
    if not rows: return ""
    width = max((max((i for i, c in enumerate(r) if c), default=-1) + 1) for r in rows)
    rows = [(r + [""] * width)[:width] for r in rows]
    head = rows[0]
    named = next((i for i, h in enumerate(head) if not h), width)          # the header's own columns; cells further right stay unnamed
    has_header = (named >= 2 and len(rows) >= 2 and not any(head[named:])
                  and not any(re.fullmatch(r"-?[\d.,]+", h) for h in head[:named]))
    if not has_header:
        return "\n".join(" | ".join(c for c in r if c) for r in rows)
    lines = [" | ".join(head[:named])]
    for r in rows[1:]:
        lines.append(" | ".join((f"{h}: {c}" if h else c) for h, c in zip(head, r) if c))
    return "\n".join(lines)


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha(): n = n * 26 + (ord(ch.upper()) - 64)
        else: break
    return n - 1


def _xlsx_sheets(path: str) -> list:
    """[(sheet name, rows)] of an Excel workbook, read straight from its XML (no extra library)."""
    import datetime
    import xml.etree.ElementTree as ET
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si"):
                shared.append("".join(t.text or "" for t in si.iter(M + "t")))
        date_styles = set()
        if "xl/styles.xml" in names:
            styles = ET.fromstring(z.read("xl/styles.xml"))
            custom = {int(f.get("numFmtId", 0)): f.get("formatCode", "") for f in styles.iter(M + "numFmt")}
            xfs = styles.find(M + "cellXfs")
            for i, xf in enumerate(xfs if xfs is not None else []):
                fid = int(xf.get("numFmtId", 0))
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fid, "")).lower()
                if fid in _DATE_FORMATS or (code and re.search(r"[dy]|mm|h|ss", code) and "0" not in code and "#" not in code):
                    date_styles.add(i)
        book = ET.fromstring(z.read("xl/workbook.xml"))
        pr = book.find(M + "workbookPr")
        epoch = datetime.datetime(1904, 1, 1) if pr is not None and pr.get("date1904") in ("1", "true") else datetime.datetime(1899, 12, 30)
        targets = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                t = rel.get("Target", "")
                targets[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        out = []
        for n, sheet in enumerate(book.iter(M + "sheet"), 1):
            member = targets.get(sheet.get(R + "id"), f"xl/worksheets/sheet{n}.xml")
            if member not in names: continue
            rows = []
            for row in ET.fromstring(z.read(member)).iter(M + "row"):
                cells = {}
                for c in row.iter(M + "c"):
                    kind, v = c.get("t"), c.find(M + "v")
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(M + "t"))
                    elif v is None or v.text is None:
                        continue
                    elif kind == "s":
                        try: value = shared[int(v.text)]
                        except (ValueError, IndexError): continue
                    elif kind == "b": value = v.text == "1"
                    elif kind in ("str", "e"): value = v.text
                    else:
                        try: value = float(v.text)
                        except ValueError: value = v.text
                        if isinstance(value, float) and int(c.get("s", 0) or 0) in date_styles:
                            try:
                                secs = round(value * 86400)                    # whole seconds: 14:30 must not become 14:29
                                value = (epoch + datetime.timedelta(seconds=secs)) if value >= 1 else \
                                    (datetime.datetime.min + datetime.timedelta(seconds=secs)).time()
                            except (OverflowError, ValueError): pass
                    cells[_col_index(c.get("r", "")) if c.get("r") else len(cells)] = value
                if cells:
                    rows.append([cells.get(i) for i in range(max(cells) + 1)])
            out.append((sheet.get("name") or f"Sheet {n}", rows))
        return out


def _xls_sheets(path: str) -> list:
    """[(sheet name, rows)] of an old Excel workbook (.xls, the format before 2007)."""
    import datetime
    try:
        import xlrd
    except ImportError:
        raise DocError("Old Excel files (.xls) cannot be read by this build. Open it and save it as .xlsx, then add that file.")
    try:
        book = xlrd.open_workbook(path)
    except Exception as e:
        raise DocError(f"This old Excel file could not be read ({type(e).__name__}). Open it and save it as .xlsx, then add that file.")
    out = []
    for sheet in book.sheets():
        rows = []
        for r in range(sheet.nrows):
            row = []
            for c in range(sheet.ncols):
                kind, value = sheet.cell_type(r, c), sheet.cell_value(r, c)
                if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR): value = None
                elif kind == xlrd.XL_CELL_BOOLEAN: value = bool(value)
                elif kind == xlrd.XL_CELL_DATE:
                    try:
                        secs = round(value * 86400)
                        value = xlrd.xldate_as_datetime(value, book.datemode) if value >= 1 else \
                            (datetime.datetime.min + datetime.timedelta(seconds=secs)).time()
                    except (ValueError, OverflowError, ArithmeticError): pass          # not a real date: keep the number
                row.append(value)
            rows.append(row)
        out.append((sheet.name, rows))
    return out


def _numbers_sheets(path: str) -> list:
    """[(sheet / table name, rows)] of an Apple Numbers document."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from numbers_parser import Document
            doc = Document(path)
    except ImportError:
        raise DocError("Numbers files cannot be read by this build. In Numbers choose File → Export To → Excel or CSV and add that file.")
    except Exception as e:
        raise DocError(f"This Numbers file could not be read ({type(e).__name__}). Export it to Excel or CSV and add that file.")
    out = []
    for sheet in doc.sheets:
        for table in sheet.tables:
            name = sheet.name if len(sheet.tables) == 1 else f"{sheet.name} / {table.name}"
            out.append((name, table.rows(values_only=True)))
    return out


def _sheet_parts(sheets: list) -> list:
    return [(f"sheet {name}", table_text(rows)) for name, rows in sheets]


def _textutil(path: str) -> str:
    try:
        r = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", path], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DocError(f"Could not convert this file: {e}")
    if r.returncode != 0: raise DocError("macOS could not convert this file to text.")
    return r.stdout.decode("utf-8", errors="replace")


def _plain(path: str) -> str:
    with open(path, "rb") as f: raw = f.read(MAX_FILE_CHARS * 4)
    if b"\x00" in raw[:4096]: raise DocError("This is not a text document (it looks like a program, picture or archive).")
    return raw.decode("utf-8", errors="replace")


def extract(path: str, progress=None) -> list:
    """The text of a document as a list of sections: [(label, text)]. label is 'p.3' / 'slide 2' / ''.
    `progress(done, total)` is called while scanned pages are being read (that can take a while)."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path): raise DocError(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            parts = [(f"p.{i + 1}", t) for i, t in enumerate(_pdf_pages(path, progress))]
        elif ext in IMAGE_TYPES:
            parts = [("", _image_text(path))]
        elif ext in (".xlsx", ".xlsm"):
            parts = _sheet_parts(_xlsx_sheets(path))
        elif ext == ".numbers":
            parts = _sheet_parts(_numbers_sheets(path))
        elif ext == ".xls":
            parts = _sheet_parts(_xls_sheets(path))
        elif ext == ".docx":
            parts = [("", _docx_text(path))]
        elif ext == ".pptx":
            parts = [(f"slide {i + 1}", t) for i, t in enumerate(_pptx_slides(path))]
        elif ext in TEXTUTIL_TYPES:
            parts = [("", _textutil(path))]
        else:
            parts = [("", _plain(path))]
    except DocError:
        raise
    except (zipfile.BadZipFile, KeyError):
        raise DocError("This file is damaged or is not really a Word / PowerPoint / Excel document.")
    except OSError as e:
        raise DocError(f"Could not read the file: {e}")
    except Exception as e:
        raise DocError(f"Could not read this document ({type(e).__name__}).")
    parts = [(label, _tidy(text)) for label, text in parts]
    parts = [(label, text) for label, text in parts if text]
    if not parts: raise DocError("There is no text in this document.")
    return parts


def extract_text(path: str, max_chars: int = None) -> str:
    text = "\n\n".join(f"[{label}]\n{t}" if label else t for label, t in extract(path))
    return text if max_chars is None else text[:max_chars]


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def passages(parts: list) -> list:
    """Cut sections into overlapping passages: [{'t': text, 'at': label}]. Breaks fall between paragraphs or sentences."""
    out = []
    for label, text in parts:
        i = 0; n = len(text)
        while i < n:
            end = min(n, i + PASSAGE)
            if end < n:
                cut = max(text.rfind("\n\n", i + PASSAGE // 2, end), text.rfind(". ", i + PASSAGE // 2, end),
                          text.rfind("\n", i + PASSAGE // 2, end))
                if cut > i: end = cut + 1
            piece = text[i:end].strip()
            if piece: out.append({"t": piece, "at": label})
            if end >= n: break
            i = max(end - OVERLAP, i + 1)
    return out


# ── the library ────────────────────────────────────────────────────
_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = set("a an and are as at be but by for from has have in is it its of on or that the their this to was were will with "
            "и в на с за от по да не се е са че това".split())


def tokens(text: str) -> list:
    """Lower-cased words; long words are cut to a 6-letter stem so 'invoices' finds 'invoice', 'договори' finds 'договор'."""
    return [w[:6] if len(w) > 6 else w for w in (t.lower() for t in _WORD.findall(text or "")) if len(w) >= 2 and w not in _STOP]


class Library:
    """The indexed documents. Thread-safe; stored in one (optionally encrypted) file in NOVA's data folder."""
    def __init__(self, path: str = None):
        self.path = path or paths.DOCS_FILE
        self._lock = threading.RLock()
        self._docs = None                # name -> {"path", "added", "chars", "mtime", "size", "passages": [...]}
        self._folders = []               # folders that were added as a whole: new files in them are picked up
        self._stats = None               # cached search statistics

    # persistence
    def _load(self) -> dict:
        with self._lock:
            if self._docs is None:
                try:
                    data = storage.read_json(self.path)
                    self._docs = data.get("docs", {}) if isinstance(data, dict) else {}
                    self._folders = [f for f in (data.get("folders") or []) if isinstance(f, str)] if isinstance(data, dict) else []
                except (OSError, ValueError):
                    self._docs = {}; self._folders = []
            return self._docs

    def _save(self) -> None:
        with self._lock:
            self._stats = None
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            storage.write_json(self.path, {"version": 1, "docs": self._docs or {}, "folders": self._folders}, indent=None)

    def reload(self) -> None:
        with self._lock: self._docs = None; self._stats = None

    # content
    def names(self) -> list:
        return sorted(self._load())

    def info(self) -> list:
        return [{"name": n, "path": d.get("path", ""), "parts": len(d.get("passages", [])), "chars": d.get("chars", 0),
                 "added": d.get("added", ""), "missing": bool(d.get("missing"))} for n, d in sorted(self._load().items())]

    def total_chars(self) -> int:
        return sum(d.get("chars", 0) for d in self._load().values())

    def add_file(self, path: str, parts: list = None, progress=None) -> dict:
        """Index one file (replacing an older copy with the same name). Returns its info. Raises DocError.
        `parts` = text already taken out with extract(), to avoid reading the file twice."""
        path = os.path.abspath(os.path.expanduser(path))
        if parts is None: parts = extract(path, progress)
        chars = sum(len(t) for _l, t in parts)
        cut = chars > MAX_FILE_CHARS
        if cut:
            kept, room = [], MAX_FILE_CHARS
            for label, text in parts:
                if room <= 0: break
                kept.append((label, text[:room])); room -= len(text)
            parts = kept; chars = MAX_FILE_CHARS
        with self._lock:
            docs = self._load()
            name = os.path.basename(path)
            if name in docs and docs[name].get("path") != path:            # two different files with the same name
                name = f"{os.path.basename(os.path.dirname(path))}/{name}"
            if self.total_chars() - docs.get(name, {}).get("chars", 0) + chars > MAX_TOTAL_CHARS:
                raise DocError("Your document library is full. Remove some documents first (＋ → Documents).")
            try: st = os.stat(path); stamp = {"mtime": st.st_mtime, "size": st.st_size}
            except OSError: stamp = {}
            docs[name] = dict({"path": path, "added": time.strftime("%Y-%m-%d %H:%M"), "chars": chars, "passages": passages(parts)}, **stamp)
            self._save()
            return {"name": name, "parts": len(docs[name]["passages"]), "chars": chars, "cut": cut}

    def add_folder(self, folder: str, progress=None) -> dict:
        """Index every supported file below a folder. Returns {'added': [...], 'skipped': [(name, why)], 'more': n}."""
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder): raise DocError(f"Folder not found: {folder}")
        files = self._folder_files(folder)
        more = max(0, len(files) - MAX_FOLDER_FILES); files = files[:MAX_FOLDER_FILES]
        added, skipped = [], []
        for i, f in enumerate(files):
            if progress: progress(i, len(files), os.path.basename(f))
            try:
                added.append(self.add_file(f)["name"])
            except DocError as e:
                skipped.append((os.path.basename(f), str(e)))
                if "library is full" in str(e): break
        with self._lock:
            self._load()
            if folder not in self._folders:
                self._folders.append(folder); self._save()
        return {"added": added, "skipped": skipped, "more": more}

    def _folder_files(self, folder: str) -> list:
        out = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv", "venv"))
            out += [os.path.join(root, n) for n in sorted(names) if not n.startswith(".") and os.path.splitext(n)[1].lower() in SUPPORTED]
        return out

    def refresh(self, scan_folders: bool = False) -> dict:
        """Keep the index true to the files: re-read documents that changed on disk, note the ones that are gone,
        and (with scan_folders) pick up new files in folders that were added as a whole.
        Returns {'updated': [names], 'added': [names], 'missing': [names]}."""
        report = {"updated": [], "added": [], "missing": []}
        with self._lock:
            docs = self._load()
            dirty = False
            for name, d in list(docs.items()):
                path = d.get("path", "")
                try:
                    st = os.stat(path)
                except OSError:
                    if not d.get("missing"): d["missing"] = True; dirty = True; report["missing"].append(name)
                    continue
                if d.get("missing"): d.pop("missing", None); dirty = True
                if "mtime" not in d:                                   # indexed by an older NOVA: start watching from now
                    d["mtime"], d["size"] = st.st_mtime, st.st_size; dirty = True; continue
                if abs(st.st_mtime - d["mtime"]) > 1 or st.st_size != d.get("size"):
                    try:
                        new_name = self.add_file(path)["name"]; report["updated"].append(new_name)
                        if new_name != name: docs.pop(name, None); dirty = True
                    except DocError:                                   # unreadable right now (half-saved?): keep the old text
                        d["mtime"], d["size"] = st.st_mtime, st.st_size; dirty = True
            if scan_folders:
                known = {d.get("path") for d in docs.values()}
                for folder in list(self._folders):
                    if not os.path.isdir(folder): continue
                    for f in self._folder_files(folder):
                        if f in known or len(docs) >= MAX_FOLDER_FILES * 2: continue
                        try: report["added"].append(self.add_file(f)["name"]); known.add(f)
                        except DocError: known.add(f)
            if dirty: self._save()
        return report

    def remove(self, name: str) -> bool:
        with self._lock:
            docs = self._load()
            hit = name if name in docs else next((n for n in docs if n.lower() == name.lower()), None)
            if hit is None: return False
            del docs[hit]; self._save()
            return True

    def clear(self) -> None:
        with self._lock:
            self._docs = {}; self._folders = []; self._save()

    # search
    def _statistics(self):
        with self._lock:
            if self._stats is None:
                rows = []; df = collections.Counter(); total = 0
                for name, d in self._load().items():
                    for i, p in enumerate(d.get("passages", [])):
                        tf = collections.Counter(tokens(p["t"])); n = sum(tf.values())
                        rows.append((name, i, tf, n)); total += n
                        df.update(tf.keys())
                self._stats = (rows, df, (total / len(rows)) if rows else 1.0)
            return self._stats

    def search(self, query: str, k: int = 6, document: str = "") -> list:
        """The k passages that best match the question: [{'doc', 'at', 'text', 'score'}], best first (BM25)."""
        rows, df, avg = self._statistics()
        q = set(tokens(query))
        if not rows or not q: return []
        want = document.strip().lower()
        N = len(rows); scored = []
        for name, i, tf, n in rows:
            if want and want not in name.lower(): continue
            s = 0.0
            for term in q:
                f = tf.get(term)
                if f:
                    idf = math.log(1 + (N - df[term] + 0.5) / (df[term] + 0.5))
                    s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * n / avg))
            if s > 0: scored.append((s, name, i))
        scored.sort(reverse=True)
        docs = self._load(); out = []; taken = collections.Counter()
        for s, name, i in scored:
            if taken[name] >= max(3, k - 1) and not want: continue            # do not let one document crowd out the rest
            p = docs[name]["passages"][i]
            out.append({"doc": name, "at": p.get("at", ""), "text": p["t"], "score": round(s, 2)}); taken[name] += 1
            if len(out) >= k: break
        return out


def search_many(lib: "Library", queries: list, k: int = 6, document: str = "") -> list:
    """Search with several wordings of the same question and merge the results, so a passage is found whether it
    says "deposit", "security payment" or "депозит". Passages that match several wordings come first."""
    queries = [q for q in dict.fromkeys(str(q).strip() for q in queries) if q][:6]
    if len(queries) <= 1:
        return lib.search(queries[0] if queries else "", k, document)
    merged = {}
    for q in queries:
        for rank, hit in enumerate(lib.search(q, max(k, 6), document)):
            key = (hit["doc"], hit["text"])
            entry = merged.setdefault(key, dict(hit, score=0.0))
            entry["score"] += 1.0 / (30 + rank)                          # reciprocal rank fusion
    return [dict(h, score=round(h["score"], 4)) for h in sorted(merged.values(), key=lambda h: -h["score"])[:k]]


_library = None
_library_lock = threading.Lock()


def library() -> Library:
    """The one shared library (created on first use)."""
    global _library
    with _library_lock:
        if _library is None or _library.path != paths.DOCS_FILE:
            _library = Library()
        return _library


def answer_material(query, k: int = 6, document: str = "") -> str:
    """What the AI gets for a question: the matching passages with where they come from.
    `query` may be one string or a list of alternative wordings."""
    lib = library()
    if not lib.names(): return ""
    hits = search_many(lib, query if isinstance(query, (list, tuple)) else [query], k, document)
    if not hits: return ""
    return "\n\n".join(f"[{h['doc']}{', ' + h['at'] if h['at'] else ''}]\n{h['text']}" for h in hits)
