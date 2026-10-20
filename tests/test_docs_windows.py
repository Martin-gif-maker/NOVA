"""The document readers Windows uses instead of Apple's frameworks (docs_windows.py). They are plain Python, so they
are tested on every system - and on a Mac their result is compared with what macOS itself reads from the same file."""
import subprocess, sys, zipfile
import pytest
import docs, docs_windows
from test_docs import make_pdf

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="compares with macOS's own converters")


@pytest.fixture
def as_windows(monkeypatch):
    """docs.py reads the way it does on Windows."""
    monkeypatch.setattr(docs, "ON_WINDOWS", True)
    monkeypatch.setattr(docs_windows, "ocr_available", lambda: False)        # no text recognition in the tests


def test_pdf_text_page_by_page(tmp_path, as_windows):
    pytest.importorskip("pypdf")
    f = make_pdf(tmp_path / "report.pdf", ["Annual report 2025\nRevenue was 4.2 million euro", "Outlook\nWe expect growth in Bulgaria"])
    parts = docs.extract(f)
    assert [label for label, _ in parts] == ["p.1", "p.2"]
    assert "Revenue was 4.2 million euro" in parts[0][1] and "growth in Bulgaria" in parts[1][1]
    assert docs.extract_text(f).startswith("[p.1]\nAnnual report 2025")


def test_cyrillic_pdf(tmp_path, as_windows):
    pytest.importorskip("pypdf")
    f = make_pdf(tmp_path / "bg.pdf", ["Договор за наем\nНаемът е 900 евро на месец"])
    assert "Наемът е 900 евро на месец" in docs.extract_text(f)


def test_a_broken_or_locked_pdf_says_so(tmp_path, as_windows):
    pytest.importorskip("pypdf")
    bad = tmp_path / "bad.pdf"; bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(docs.DocError, match="could not be opened"): docs.extract(str(bad))
    from pypdf import PdfReader, PdfWriter
    plain = make_pdf(tmp_path / "plain.pdf", ["secret plans"])
    writer = PdfWriter(); writer.append(PdfReader(plain)); writer.encrypt("hunter2")
    locked = tmp_path / "locked.pdf"
    with open(locked, "wb") as fh: writer.write(fh)
    with pytest.raises(docs.DocError, match="password"): docs.extract(str(locked))


def test_a_scanned_pdf_without_text_recognition_says_so(tmp_path, as_windows, monkeypatch):
    monkeypatch.setattr(docs_windows, "pdf_pages", lambda path, limit: ["", "  "])
    f = tmp_path / "scan.pdf"; f.write_bytes(b"%PDF")
    with pytest.raises(docs.DocError, match="scan"): docs.extract(str(f))


# ── rich text ──────────────────────────────────────────────────────
def test_rich_text_as_word_writes_it():
    hello = "".join(f"\\u{ord(c)}?" for c in "Здравей")                     # Word writes other alphabets as \uN?
    rtf = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Helvetica;}}{\colortbl;\red0\green0\blue0;}"
           r"{\*\generator Riched20;}\f0\fs24 Dear Ann,\par the invoice is \b attached\b0 .\par "
           r"Caf\'e9 " + hello + r" \{braces\} tab\tab here\par}")
    text = docs_windows.rtf_text(rtf.encode("latin-1"))
    assert text.splitlines()[:2] == ["Dear Ann,", "the invoice is attached."]
    assert "Café Здравей {braces} tab\there" in text and "Helvetica" not in text and "Riched20" not in text


def test_rich_text_as_wordpad_writes_cyrillic():
    """WordPad stores Bulgarian as single bytes in the font's own code page (charset 204 = Cyrillic)."""
    cyr = "".join(f"\\'{b:02x}" for b in "Здравей, свят".encode("cp1251"))
    rtf = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fnil\fcharset0 Calibri;}{\f1\fnil\fcharset204 Calibri;}}"
           r"\pard\f0\fs22 Hello \f1 " + cyr + r"\f0  again\par}")
    assert docs_windows.rtf_text(rtf.encode("latin-1")).strip() == "Hello Здравей, свят again"
    whole = r"{\rtf1\ansi\ansicpg1251 " + cyr + r"\par}"                      # …or the whole file is Cyrillic
    assert docs_windows.rtf_text(whole.encode("latin-1")).strip() == "Здравей, свят"


def test_rich_text_file_is_read_through_docs(tmp_path, as_windows):
    f = tmp_path / "letter.rtf"; f.write_text(r"{\rtf1\ansi Dear Ann,\par the invoice is attached.}")
    assert docs.extract(str(f)) == [("", "Dear Ann,\nthe invoice is attached.")]


# ── web pages and OpenDocument ─────────────────────────────────────
def test_html_keeps_the_words_and_drops_the_machinery(tmp_path, as_windows):
    page = ("<html><head><meta charset='utf-8'><title>Offer</title><style>p{color:red}</style>"
            "<script>var secret = 'do not show';</script></head><body><h1>Оферта</h1>"
            "<p>Price: 1&nbsp;200 &euro; &amp; free delivery</p><ul><li>one</li><li>two</li></ul>"
            "<table><tr><td>a</td><td>b</td></tr></table></body></html>")
    f = tmp_path / "offer.html"; f.write_bytes(page.encode("utf-8"))
    text = docs.extract_text(str(f))
    assert "Оферта" in text and "Price: 1 200 € & free delivery" in text and "one" in text and "two" in text
    assert "secret" not in text and "color:red" not in text
    old = tmp_path / "old.htm"; old.write_bytes("<p>Здравей</p>".encode("cp1251").replace(b"<p>", b"<meta charset=windows-1251><p>"))
    assert docs.extract_text(str(old)) == "Здравей"


def make_odt(path, paragraphs):
    ns = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:text>'
                                  f'<text:h>Minutes</text:h>{body}</office:text></office:body></office:document-content>')
    return str(path)


def test_opendocument_text(tmp_path, as_windows):
    f = make_odt(tmp_path / "minutes.odt", ["First <text:span>point</text:span>: budget", "Tab<text:tab/>here<text:s text:c=\"2\"/>and<text:line-break/>next"])
    assert docs.extract(f) == [("", "Minutes\nFirst point: budget\nTab here and\nnext")]


def test_formats_windows_cannot_read_say_what_to_do(tmp_path, as_windows):
    f = tmp_path / "old.doc"; f.write_bytes(b"\xd0\xcf\x11\xe0 not really")
    with pytest.raises(docs.DocError, match="save it as .docx"): docs.extract(str(f))


def test_recognised_pages_are_read_back_from_the_helper(monkeypatch, tmp_path):
    """The PowerShell helper answers one line per page; a missing language is reported in plain words."""
    import base64, types, platform_utils as plat
    if not hasattr(plat, "_system_exe"): monkeypatch.setattr(plat, "_system_exe", lambda name: name, raising=False)
    seen = {}

    def fake_run(cmd, **k):
        seen["pages"] = k["env"]["NOVA_PAGES"]
        lines = [f"@@PAGE {n} " + base64.b64encode(f"страница {n}".encode()).decode() for n in k["env"]["NOVA_PAGES"].split(",")]
        return types.SimpleNamespace(returncode=0, stdout=("noise\n" + "\n".join(lines)).encode(), stderr=b"")
    monkeypatch.setattr(docs_windows.subprocess, "run", fake_run)
    assert docs_windows.ocr_pdf(str(tmp_path / "scan.pdf"), [0, 3]) == {0: "страница 0", 3: "страница 3"} and seen["pages"] == "0,3"
    monkeypatch.setattr(docs_windows.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(returncode=3, stdout=b"", stderr=b""))
    with pytest.raises(docs.DocError, match="text-recognition language"): docs_windows.ocr_pdf("x.pdf", [0])


# ── the same files, read by macOS and by the Windows readers ───────
@mac_only
def test_same_words_as_macos_reads(tmp_path):
    pytest.importorskip("pypdf")
    words = lambda t: t.split()
    f = make_pdf(tmp_path / "report.pdf", ["Annual report 2025\nRevenue was 4.2 million euro", "Договор за наем\nНаемът е 900 евро"])
    assert [words(p) for p in docs_windows.pdf_pages(f, 10**6)] == [words(p) for p in docs._pdf_text_layer(f)]
    src = tmp_path / "note.txt"; src.write_text("Dear Ann,\nthe invoice — №42 — is attached.\nПоздрави, Мартин\n", encoding="utf-8")
    for fmt in ("rtf", "html", "odt"):
        out = tmp_path / f"note.{fmt}"
        subprocess.run(["/usr/bin/textutil", "-convert", fmt, "-inputencoding", "UTF-8", "-output", str(out), str(src)], check=True)
        assert words(docs_windows.to_text(str(out))) == words(docs._textutil(str(out))), fmt
