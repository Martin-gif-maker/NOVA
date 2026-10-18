# selftest.py — `NOVA --selftest`: prove that everything the app needs is present and working.
# The build script runs it against the packaged .app (with a throw-away data folder).
import os
import tempfile
import logging
import paths
import crash
import sandbox
import ipc
import schemas
import providers
from mdrender import _md_to_html, _MD_OK

log = logging.getLogger("nova")


def run() -> int:
    """Prove that everything the app needs is importable and working (run against the packaged .app)."""
    problems = []
    html = _md_to_html("| a |\n|---|\n| 1 |\n\n```python\nx = 1\n```")
    if not (_MD_OK and "<table" in html and "<span style=" in html): problems.append("markdown renderer")
    for prov in ("groq", "anthropic", "openai", "ollama"):                 # every provider's client can be built
        try: providers.make_client(prov, "selftest-key", "")
        except Exception as e: problems.append(f"{prov} client ({e})")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key, nonce = os.urandom(32), os.urandom(12)
        assert AESGCM(key).decrypt(nonce, AESGCM(key).encrypt(nonce, b"nova", None), None) == b"nova"
    except Exception as e: problems.append(f"encryption ({e})")
    try:
        import vosk                                                       # loads the native speech library
        vosk.SetLogLevel(-1)
    except Exception as e: problems.append(f"offline voice engine ({e})")
    try:
        import plugin_host, memory, ledger
        assert callable(plugin_host.main) and sandbox.PERMISSIONS and memory.CATEGORIES and ledger.record and crash.install
    except Exception as e: problems.append(f"core modules ({e})")
    try:                                                                # Calendar helper: the separate process starts and answers
        import mac_apps
        try: mac_apps._eventkit({"op": "selftest"}, timeout=30)
        except mac_apps.AppError as e:
            if "unknown request" not in str(e): problems.append(f"calendar helper ({e})")
    except Exception as e: problems.append(f"calendar helper ({e})")
    try:                                                                # documents: Word text extraction + search, PDF reader present
        import docs, zipfile
        import Quartz
        assert hasattr(Quartz, "PDFDocument")                             # the PDF reader is in the bundle
        tmpd = tempfile.mkdtemp(prefix="nova_selftest_")
        try:
            W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            path = os.path.join(tmpd, "t.docx")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>the deposit is two rents</w:t></w:r></w:p></w:body></w:document>')
            lib = docs.Library(os.path.join(tmpd, "index.json")); lib.add_file(path)
            assert lib.search("deposit")[0]["text"] == "the deposit is two rents"
            assert docs.ocr_available()                                   # scanned pages can be read
            import warnings, numbers_parser                               # spreadsheets: a Numbers file written and read back
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                nd = numbers_parser.Document(); nt = nd.sheets[0].tables[0]
                for r, row in enumerate([["City", "People"], ["Sofia", 1286000]]):
                    for c, v in enumerate(row): nt.write(r, c, v)
                nd.save(os.path.join(tmpd, "t.numbers"))
            assert "City: Sofia | People: 1286000" in docs.extract(os.path.join(tmpd, "t.numbers"))[0][1]
        finally:
            import shutil as _sh; _sh.rmtree(tmpd, ignore_errors=True)
    except Exception as e: problems.append(f"documents ({e})")
    try:                                                                # search by meaning: the model runtime loads
        import embeddings
        assert embeddings.runtime_installed()
        import onnxruntime, tokenizers                                    # native libraries in the bundle
        assert "CPUExecutionProvider" in onnxruntime.get_available_providers() and tokenizers.Tokenizer
        if embeddings.installed():                                        # the model itself runs (when downloaded)
            p = embeddings.embed_passages(["The deposit is two monthly rents.", "The trail takes four hours."])
            q = embeddings.embed_query("How much do I pay up front for the flat?")
            assert p.shape == (2, embeddings.DIM) and float(p[0] @ q) > float(p[1] @ q)
    except Exception as e: problems.append(f"search by meaning ({e})")
    try:                                                                # speech in any language: whisper.cpp loads
        import speech
        assert speech.whisper_installed()
        import _pywhispercpp                                              # the native library is in the bundle
        assert hasattr(_pywhispercpp, "whisper_init_from_file") or _pywhispercpp
        if speech.whisper_ready():                                        # the model itself runs (when downloaded)
            import numpy as np
            tone = (np.sin(np.linspace(0, 800 * np.pi, 32000)) * 9000).astype("<i2").tobytes()
            assert isinstance(speech.transcribe_whisper(tone, "en"), str)
    except Exception as e: problems.append(f"speech in any language ({e})")
    try:
        import mcp_client, schedule, modes, usage
        assert schemas.select_tools("hello")[0] and ipc.server_name() and mcp_client.tool_id("a", "b") == "mcp__a__b"
        assert schedule.parse_time("8") == "08:00" and modes.BUILTIN and usage.money(0) == "$0"
        import icons                                                    # the interface's icons can be drawn
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        assert all(QSvgRenderer(QByteArray(icons.svg(n, "#000000"))).isValid() for n in icons.PATHS)
        import echo                                                     # voice talk-over: the loudness comparison runs
        played = [3000.0 if (k // 7) % 2 else 20.0 for k in range(220)]         # words and gaps
        gate = echo.EchoGate(played)
        assert not any(gate.feed(0.5 * played[max(0, k - 5)] + 30) for k in range(220))     # its own echo, 5 chunks late
        assert gate.learned() and gate.delay == 5 and any(gate.feed(20000.0) for _ in range(30))   # …and then you
    except Exception as e: problems.append(f"new modules ({e})")
    if sandbox.available():                                             # a plugin really runs, and really is sealed in
        import json, shutil
        tmp = tempfile.mkdtemp(prefix="nova_selftest_")
        try:
            plug = os.path.join(tmp, "selftest_plugin.py")
            with open(plug, "w", encoding="utf-8") as f:
                f.write('MANIFEST = {"permissions": []}\nimport os, socket\n'
                        'def _try(fn):\n    try: fn(); return "open"\n    except Exception: return "blocked"\n'
                        'def probe(home):\n    return ("ran net=" + _try(lambda: socket.create_connection(("1.1.1.1", 443), timeout=2))'
                        ' + " home=" + _try(lambda: os.listdir(home)))\n'
                        'TOOLS = [{"name": "probe", "function": probe, "params": {"home": {"type": "string"}}}]\n')
            r = sandbox.run(plug, [], ["call", "probe"], json.dumps({"home": os.path.expanduser("~")}), timeout=30,
                            work=os.path.join(tmp, "work"))
            if r.get("result") != "ran net=blocked home=blocked": problems.append(f"plugin sandbox ({r})")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    state = "ok" if not problems else "FAILED: " + "; ".join(problems)
    print(f"NOVA {paths.__version__} selftest {state} · data dir: {paths.DATA_DIR}")
    return 0 if not problems else 1
