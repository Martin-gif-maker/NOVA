# docs_windows.py — reading documents without Apple's frameworks (docs.py uses these on Windows).
#
#   PDF text            the pypdf package
#   .rtf  .odt  .html   read here, in plain Python (no converter program is needed)
#   scans and pictures  Windows' own text recognition (Windows.Media.Ocr), entirely on this PC, reached through
#                       a hidden PowerShell - so no extra package has to be installed
# The first three need nothing from Windows and are tested on every system.
import os, re, sys, base64, zipfile, subprocess
import logging

log = logging.getLogger("nova")

CONVERTIBLE = {".rtf", ".odt", ".html", ".htm"}             # what to_text() reads
NOT_HERE = {".doc": "Old Word files (.doc) cannot be read on Windows. Open the file in Word, save it as .docx and try again.",
            ".rtfd": "This is a macOS document bundle; it cannot be read on Windows.",
            ".webarchive": "This is a Safari web archive; it cannot be read on Windows.",
            ".wordml": "This old Word XML format cannot be read on Windows. Save the file as .docx and try again."}


def _error(message: str):
    from docs import DocError
    return DocError(message)


# ── PDF ────────────────────────────────────────────────────────────
def pdf_pages(path: str, max_chars: int) -> list:
    """The text layer of every page (an empty string for a scanned page)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise _error("PDF reading is not available in this build.")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):          # many PDFs are "protected" with an empty password
            raise _error("This PDF is password-protected.")
        count = len(reader.pages)
    except Exception as e:
        if type(e).__name__ == "DocError": raise
        raise _error("This PDF could not be opened (damaged or password-protected).")
    pages = []; total = 0
    for i in range(count):
        try: text = reader.pages[i].extract_text() or ""
        except Exception as e:
            log.info("PDF page %s could not be read: %s", i + 1, e); text = ""
        pages.append(text); total += len(text)
        if total > max_chars: break
    return pages


# ── RTF ────────────────────────────────────────────────────────────
_RTF_TOKEN = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)", re.I | re.S)
# groups that hold settings, not text
_RTF_SKIP = frozenset("""aftncn aftnsep aftnsepc annotation atnauthor atndate atnicn atnid atnparent atnref atntime atrfend
atrfstart author background bkmkend bkmkstart blipuid buptim category colorschememapping colortbl comment company creatim
datafield datastore defchp defpap do doccomm docvar dptxbxtext ebcend ebcstart factoidname falt fchars ffdeftext ffentrymcr
ffexitmcr ffformat ffhelptext ffl ffname ffstattext field file filetbl fldinst fldrslt fldtype fname fontemb fontfile
fonttbl footer footerf footerl footerr footnote formfield ftncn ftnsep ftnsepc g generator gridtbl header headerf headerl
headerr hl hlfr hlinkbase hlloc hlsrc hsv htmltag info keycode keywords latentstyles lchars levelnumbers leveltext lfolevel
linkval list listlevel listname listoverride listoverridetable listpicture liststylename listtable listtext lsdlockedexcept
macc maccPr mailmerge maln malnScr manager margPr mbar mbarPr mbaseJc mbegChr mborderBox mborderBoxPr mbox mboxPr mchr
mcount mctrlPr md mdeg mdegHide mden mdiff mdPr me mendChr meqArr meqArrPr mf mfName mfPr mfunc mfuncPr mgroupChr
mgroupChrPr mgrow mhideBot mhideLeft mhideRight mhideTop mhtmltag mlim mlimloc mlimlow mlimlowPr mlimupp mlimuppPr mm
mmaddfieldname mmath mmathPict mmathPr mmaxdist mmc mmcJc mmconnectstr mmconnectstrdata mmcPr mmcs mmdatasource
mmheadersource mmmailsubject mmodso mmodsofilter mmodsofldmpdata mmodsomappedname mmodsoname mmodsorecipdata mmodsosort
mmodsosrc mmodsotable mmodsoudl mmodsoudldata mmodsouniquetag mmPr mmquery mmr mnary mnaryPr mnoBreak mnum mobjDist moMath
moMathPara moMathParaPr mopEmu mphant mphantPr mplcHide mpos mr mrad mradPr mrPr msepChr mshow mshp msPre msPrePr msSub
msSubPr msSubSup msSubSupPr msSup msSupPr mstrikeBLTR mstrikeH mstrikeTLBR mstrikeV msub msubHide msup msupHide mtransp
mtype mvertJc mvfmf mvfml mvtof mvtol mzeroAsc mzeroDesc mzeroWid nesttableprops nextfile nonesttables objalias objclass
objdata object objname objsect objtime oldcprops oldpprops oldsprops oldtprops oleclsid operator panose password passwordhash
pgp pgptbl picprop pict pn pnseclvl pntext pntxta pntxtb printim private propname protend protstart protusertbl pxe result
revtbl revtim rsidtbl rxe shp shpgrp shpinst shppict shprslt shptxt sn sp staticval stylesheet subject sv svb tc template
themedata title txe ud upr userprops wgrffmtfilter windowcaption writereservation writereservhash xe xform xmlattrname
xmlattrvalue xmlclose xmlname xmlnstbl xmlopen""".split())
_RTF_CHARS = {"par": "\n", "sect": "\n\n", "page": "\n\n", "line": "\n", "tab": "\t", "cell": "\t", "row": "\n",
              "emdash": "\u2014", "endash": "\u2013", "emspace": "\u2003", "enspace": "\u2002", "qmspace": "\u2005",
              "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201C", "rdblquote": "\u201D"}
# a font's character set -> the code page its \'xx bytes are written in (204 = Cyrillic)
_RTF_CHARSETS = {0: None, 1: None, 77: "mac_roman", 128: "cp932", 129: "cp949", 134: "cp936", 136: "cp950", 161: "cp1253",
                 162: "cp1254", 163: "cp1258", 177: "cp1255", 178: "cp1256", 186: "cp1257", 204: "cp1251", 222: "cp874",
                 238: "cp1250"}


def rtf_text(data: bytes) -> str:
    """The plain text of an RTF document."""
    src = data.decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", src)
    default = f"cp{m.group(1)}" if m else "cp1252"
    fonts = {}
    for f in re.finditer(r"\\f(\d+)\b[^{};]*?\\fcharset(\d+)", src[:200_000]):
        fonts[int(f.group(1))] = _RTF_CHARSETS.get(int(f.group(2))) or default
    stack = []; ignorable = False; ucskip = 1; curskip = 0; codec = default
    out = []; pending = bytearray()

    def flush():
        if pending:
            try: out.append(pending.decode(codec, "replace"))
            except LookupError: out.append(pending.decode("cp1252", "replace"))
            pending.clear()

    for match in _RTF_TOKEN.finditer(src):
        word, arg, hexa, char, brace, plain = match.groups()
        if brace:
            curskip = 0; flush()
            if brace == "{": stack.append((ucskip, ignorable, codec))
            elif stack: ucskip, ignorable, codec = stack.pop()
        elif char:
            curskip = 0
            if char == "*": ignorable = True
            elif not ignorable:
                if char in "\r\n": flush(); out.append("\n")              # a backslash at the end of a line = \par
                elif char == "~": flush(); out.append("\u00A0")
                elif char in "{}\\": flush(); out.append(char)
        elif word:
            curskip = 0
            if word in _RTF_SKIP: ignorable = True
            elif ignorable: pass
            elif word in _RTF_CHARS: flush(); out.append(_RTF_CHARS[word])
            elif word == "uc": ucskip = int(arg or 1)
            elif word == "f" and arg is not None: flush(); codec = fonts.get(int(arg), default)
            elif word == "u" and arg is not None:
                code = int(arg)
                if code < 0: code += 0x10000
                flush(); out.append(chr(code)); curskip = ucskip
        elif hexa:
            if curskip > 0: curskip -= 1
            elif not ignorable: pending.append(int(hexa, 16))
        elif plain:
            if curskip > 0: curskip -= 1
            elif not ignorable: flush(); out.append(plain)
    flush()
    return "".join(out)


# ── OpenDocument text (.odt) ───────────────────────────────────────
def odt_text(path: str) -> str:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    lines = []

    def flat(el) -> str:
        parts = [el.text or ""]
        for child in el:
            if child.tag == text_ns + "tab": parts.append("\t")
            elif child.tag == text_ns + "line-break": parts.append("\n")
            elif child.tag == text_ns + "s": parts.append(" " * int(child.get(text_ns + "c", "1") or 1))
            elif child.tag not in (text_ns + "p", text_ns + "h"): parts.append(flat(child))     # a nested paragraph is its own line
            parts.append(child.tail or "")
        return "".join(parts)

    for el in root.iter():
        if el.tag in (text_ns + "p", text_ns + "h"):
            lines.append(flat(el))
    return "\n".join(lines)


# ── HTML ───────────────────────────────────────────────────────────
def html_text(data: bytes) -> str:
    from html.parser import HTMLParser
    head = data[:4096].decode("latin-1")
    m = re.search(r"charset\s*=\s*[\"']?\s*([\w-]+)", head, re.I)
    src = None
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp1252"]:
        try: src = data.decode(enc); break
        except (UnicodeDecodeError, LookupError): continue
    if src is None: src = data.decode("utf-8", "replace")

    class Reader(HTMLParser):
        BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "header",
                 "footer", "blockquote", "pre", "ul", "ol", "dt", "dd", "hr", "title"}
        HIDDEN = {"script", "style", "noscript", "template", "svg"}

        def __init__(self):
            super().__init__(convert_charrefs=True); self.out = []; self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in self.HIDDEN: self.hidden += 1
            elif tag in self.BLOCK: self.out.append("\n")
            elif tag in ("td", "th"): self.out.append("\t")

        def handle_endtag(self, tag):
            if tag in self.HIDDEN: self.hidden = max(0, self.hidden - 1)
            elif tag in self.BLOCK: self.out.append("\n")

        def handle_data(self, text):
            if not self.hidden: self.out.append(text)

    reader = Reader()
    reader.feed(src); reader.close()
    text = "".join(reader.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n\s*", "\n\n", text).strip()


def to_text(path: str) -> str:
    """What `textutil` does on the Mac: the text of an .rtf / .odt / .html file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in NOT_HERE: raise _error(NOT_HERE[ext])
    if ext == ".odt": return odt_text(path)
    with open(path, "rb") as f: data = f.read(60_000_000)
    return rtf_text(data) if ext == ".rtf" else html_text(data)


# ── text recognition (scans, photos of documents) ──────────────────
_NO_LANGUAGE = 3
_OCR_PS = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
$asTask = ($methods | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAction = ($methods | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($operation, $type) { $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation)); $null = $task.Wait(-1); $task.Result }
function AwaitAction($action) { $task = $asAction.Invoke($null, @($action)); $null = $task.Wait(-1) }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { exit 3 }
function ReadText($stream) {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $text = ($result.Lines | ForEach-Object { $_.Text }) -join "`n"
    [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes([string]$text))
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:NOVA_IN)) ([Windows.Storage.StorageFile])
if ($env:NOVA_PAGES) {
    $pdf = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
    foreach ($number in $env:NOVA_PAGES.Split(',')) {
        $page = $pdf.GetPage([uint32]$number)
        $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
        $width = [Math]::Min($page.Size.Width * 2.5, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension - 1)
        $options.DestinationWidth = [uint32]$width
        AwaitAction ($page.RenderToStreamAsync($stream, $options))
        Write-Output ('@@PAGE ' + $number + ' ' + (ReadText $stream))
        $stream.Dispose(); $page.Dispose()
    }
} else {
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    Write-Output ('@@PAGE 0 ' + (ReadText $stream))
}
'''


def ocr_available() -> bool:
    """Windows 10 and later carry text recognition (for the languages installed in Settings)."""
    return sys.platform == "win32" and sys.getwindowsversion().major >= 10


def _run_ocr(path: str, pages: str = "", timeout: float = 600) -> dict:
    """-> {page number: text}. Raises DocError when Windows cannot recognise text at all."""
    import platform_utils as plat
    env = dict(os.environ, NOVA_IN=os.path.abspath(path), NOVA_PAGES=pages)
    try:
        r = subprocess.run([plat._system_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", _OCR_PS],
                           capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, **plat.QUIET_PROCESS)
    except (OSError, subprocess.SubprocessError) as e:
        raise _error(f"Windows' text recognition could not be started: {e}")
    if r.returncode == _NO_LANGUAGE:
        raise _error("Windows has no text-recognition language installed. Add one in Settings → Time & language → "
                     "Language & region (the language's optional feature \"Optical character recognition\").")
    out = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 2 or parts[0] != "@@PAGE": continue
        try: out[int(parts[1])] = base64.b64decode(parts[2] if len(parts) > 2 else "").decode("utf-8", "replace")
        except ValueError: continue
    if r.returncode != 0 and not out:
        log.info("text recognition failed: %s", r.stderr.decode("utf-8", "replace")[-400:])
    return out


def ocr_pdf(path: str, wanted: list, progress=None) -> dict:
    """Recognise the text of the given page numbers (0-based). -> {page: text}"""
    out = {}
    for start in range(0, len(wanted), 5):                   # a few pages per run, so progress can be shown
        if progress: progress(start, len(wanted))
        chunk = wanted[start:start + 5]
        try: out.update(_run_ocr(path, ",".join(str(i) for i in chunk)))
        except Exception as e:
            if type(e).__name__ == "DocError" and not out: raise
            log.info("text recognition stopped: %s", e); break
    return out


def image_text(path: str) -> str:
    if not ocr_available(): raise _error("Reading text from pictures is not available in this build.")
    text = _run_ocr(path, timeout=120).get(0, "")
    if not text.strip(): raise _error("No text was found in this picture.")
    return text
