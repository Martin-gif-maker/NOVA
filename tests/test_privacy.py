"""Encryption at rest, the outbound ledger and crash reports."""
import json, os, sys, time, zipfile
import pytest
import paths, storage, ledger, crash, tools, tools_web, memory


@pytest.fixture
def store(monkeypatch, tmp_path):
    """All data paths in a temp folder (the key store is the in-memory keyring from conftest)."""
    for name, rel in (("DATA_DIR", ""), ("HISTORY_FILE", "chat_history.json"), ("MEMORY_FILE", "nova_memory.json"),
                      ("REMINDERS_FILE", "nova_reminders.json"), ("NOTES_FILE", "nova_notes.txt"),
                      ("ACTIVITY_FILE", "activity.log"), ("OUTBOUND_FILE", "outbound.log"), ("SESSIONS_DIR", "sessions"),
                      ("CRASH_DIR", "crashes"), ("CONFIG_FILE", "config.json")):
        monkeypatch.setattr(paths, name, str(tmp_path / rel) if rel else str(tmp_path))
    os.makedirs(paths.SESSIONS_DIR)
    for name in ("MEMORY_FILE", "REMINDERS_FILE"):
        monkeypatch.setattr(tools, name, getattr(paths, name))
    import tools_files
    monkeypatch.setattr(tools_files, "NOTES_FILE", paths.NOTES_FILE)
    return tmp_path


# ── encryption ─────────────────────────────────────────────────────
def test_plain_by_default_and_roundtrip(store):
    storage.write_json(paths.HISTORY_FILE, {"messages": [{"role": "user", "content": "hello Ünïcode"}]})
    raw = open(paths.HISTORY_FILE, "rb").read()
    assert b"hello" in raw and not storage.is_encrypted(raw)
    assert storage.read_json(paths.HISTORY_FILE)["messages"][0]["content"] == "hello Ünïcode"
    assert os.name == "nt" or oct(os.stat(paths.HISTORY_FILE).st_mode & 0o777) == "0o600"


def test_encrypted_files_hide_the_text_and_read_back(store):
    assert storage.configure(True) is True
    storage.write_json(paths.HISTORY_FILE, {"messages": [{"role": "user", "content": "my secret plan"}]})
    raw = open(paths.HISTORY_FILE, "rb").read()
    assert storage.is_encrypted(raw) and b"secret" not in raw and b"messages" not in raw
    assert storage.read_json(paths.HISTORY_FILE)["messages"][0]["content"] == "my secret plan"
    first = raw; storage.write_json(paths.HISTORY_FILE, {"messages": [{"role": "user", "content": "my secret plan"}]})
    assert open(paths.HISTORY_FILE, "rb").read() != first                    # fresh nonce every write


def test_tampering_and_wrong_key_are_detected(store):
    storage.configure(True); storage.write_text(paths.NOTES_FILE, "private note")
    blob = bytearray(open(paths.NOTES_FILE, "rb").read()); blob[-1] ^= 1
    open(paths.NOTES_FILE, "wb").write(bytes(blob))
    with pytest.raises(storage.StorageError): storage.read_text(paths.NOTES_FILE)
    storage.write_text(paths.NOTES_FILE, "private note")
    storage.forget_key()                                                     # e.g. the Keychain entry was deleted
    with pytest.raises(storage.StorageError): storage.read_text(paths.NOTES_FILE)
    assert isinstance(storage.StorageError("x"), OSError)                    # ordinary file-error handling covers it


def test_unreadable_encrypted_file_is_kept_not_overwritten(store):
    storage.configure(True); storage.write_text(paths.NOTES_FILE, "irreplaceable")
    storage.forget_key(); storage.configure(False)
    storage.write_text(paths.NOTES_FILE, "new note")
    kept = [f for f in os.listdir(store) if ".locked-" in f]
    assert len(kept) == 1 and storage.read_text(paths.NOTES_FILE) == "new note"


def test_convert_all_encrypts_and_decrypts_everything(store):
    storage.write_json(paths.HISTORY_FILE, {"messages": [{"role": "user", "content": "chat text"}]})
    storage.write_json(os.path.join(paths.SESSIONS_DIR, "20260101_a.json"), {"title": "t", "messages": [{"role": "user", "content": "session text"}]})
    tools.save_memory("likes tea"); tools.save_note("note text"); tools._write_reminders([{"id": "1", "text": "rem text", "due": time.time() + 99}])
    tools._log_activity("write_file", {"path": "/tmp/x"}, "approved", "ok"); ledger.record("api.groq.com", "chat", 100, "model m")
    assert storage.convert_all(True) == 7 and storage.enabled()
    for p in (paths.HISTORY_FILE, paths.MEMORY_FILE, paths.NOTES_FILE, paths.REMINDERS_FILE, os.path.join(paths.SESSIONS_DIR, "20260101_a.json")):
        assert storage.is_encrypted(open(p, "rb").read()), p
    for p in (paths.ACTIVITY_FILE, paths.OUTBOUND_FILE):
        lines = open(p).read().splitlines()
        assert lines and all(l.startswith(storage.LINE_PREFIX) for l in lines) and "write_file" not in open(p).read()
    # everything still works through the normal code paths while encrypted
    assert tools.list_memories()[0].endswith("likes tea") and "note text" in tools.read_notes()
    assert tools._read_reminders()[0]["text"] == "rem text" and ledger.entries()[0]["dest"] == "api.groq.com"
    tools.save_note("second note"); tools._log_activity("read_file", {"path": "/tmp/y"}, "auto", "ok")
    assert "second note" in tools.read_notes() and len(storage.read_lines(paths.ACTIVITY_FILE)) == 2
    assert storage.convert_all(False) == 7 and not storage.enabled()
    assert b"chat text" in open(paths.HISTORY_FILE, "rb").read() and "read_file" in open(paths.ACTIVITY_FILE).read()


def test_export_is_readable_even_when_data_is_encrypted(store):
    storage.configure(True)
    storage.write_json(paths.HISTORY_FILE, {"messages": [{"role": "user", "content": "exported chat"}]})
    tools._log_activity("write_file", {"path": "/tmp/x"}, "approved", "ok")
    open(os.path.join(store, ".nova_key_openai"), "w").write("sk-secret")
    dest = str(store.parent / "out.zip")
    assert paths.export_zip(dest) == 2
    with zipfile.ZipFile(dest) as z:
        assert sorted(z.namelist()) == ["activity.log", "chat_history.json"]            # no key files
        assert b"exported chat" in z.read("chat_history.json") and b"write_file" in z.read("activity.log")


def test_encryption_falls_back_when_the_keychain_is_broken(store, monkeypatch):
    class Broken:
        def get_password(self, *a): raise RuntimeError("locked")
        def set_password(self, *a): raise RuntimeError("locked")
    monkeypatch.setattr(storage, "_keyring", lambda: Broken())
    assert storage.configure(True) is False and not storage.enabled()
    with pytest.raises(storage.StorageError): storage.convert_all(True)


def test_retention_prunes_encrypted_logs(store):
    storage.configure(True)
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 40 * 86400))
    storage.append_line(paths.ACTIVITY_FILE, json.dumps({"t": old, "tool": "old"}))
    tools._log_activity("new_tool", {}, "auto")
    assert paths.apply_retention({"retention_days": 0, "activity_days": 30}) == 1
    assert [json.loads(l)["tool"] for l in storage.read_lines(paths.ACTIVITY_FILE)] == ["new_tool"]


# ── outbound ledger ────────────────────────────────────────────────
def test_ledger_records_destination_and_size_never_content(store):
    import providers
    kw = {"model": "m-1", "messages": [{"role": "user", "content": "TOP SECRET QUESTION"},
                                       {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:..."}}]}],
          "tools": [{"type": "function", "function": {"name": "t"}}]}
    providers.note_chat("api.example.com", kw)
    ledger.record("https://News.Google.com/rss?hl=en", "news headlines")
    ledger.record("http://localhost:11434/v1", "chat", 10)
    raw = open(paths.OUTBOUND_FILE).read()
    assert "TOP SECRET" not in raw
    items = ledger.entries()
    assert [e["dest"] for e in items] == ["api.example.com", "news.google.com", "localhost"]
    assert items[0]["what"] == "image analysis" and items[0]["bytes"] > 50 and "2 messages" in items[0]["detail"] and "1 image" in items[0]["detail"]
    rows = ledger.summary(items)
    assert rows[0][0] == "api.example.com" and rows[0][2] == 1 and ledger.is_local("localhost") and not ledger.is_local("api.groq.com")
    assert ledger.human(10) == "10 B" and ledger.human(2048) == "2.0 KB" and ledger.human(3 * 1024 * 1024) == "3.0 MB"


def test_ledger_period_filter(store):
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3 * 86400))
    storage.append_line(paths.OUTBOUND_FILE, json.dumps({"t": old, "dest": "old.example", "what": "chat", "bytes": 1}))
    ledger.record("new.example", "chat", 5)
    assert [e["dest"] for e in ledger.entries(1)] == ["new.example"]
    assert [e["dest"] for e in ledger.entries(7)] == ["old.example", "new.example"]


def test_network_tools_write_to_the_ledger(store, monkeypatch):
    import requests
    class R:
        text = "<html><body>hi</body></html>"; status_code = 200
        def raise_for_status(self): pass
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(tools_web, "_is_public_url", lambda u: (True, ""))
    tools.read_webpage("https://example.org/private/path?q=secret")
    e = ledger.entries()[-1]
    assert e["dest"] == "example.org" and e["what"] == "read web page" and "secret" not in json.dumps(e)


# ── crash reports ──────────────────────────────────────────────────
def _boom():
    try: raise ValueError("bad thing in " + os.path.expanduser("~/Documents/private.txt"))
    except ValueError: return sys.exc_info()


def test_crash_report_is_opt_in_and_scrubbed(store, monkeypatch):
    monkeypatch.setattr(crash, "_enabled", lambda: False)
    assert crash.write_report(*_boom()) is None and crash.reports() == []
    monkeypatch.setattr(crash, "_enabled", lambda: True)
    path = crash.write_report(*_boom())
    text = open(path).read()
    home = os.path.expanduser("~")
    assert "ValueError" in text and "~/Documents/private.txt" in text and home not in text and os.path.basename(home) not in text
    assert f"version: {paths.__version__}" in text and (os.name == "nt" or oct(os.stat(path).st_mode & 0o777) == "0o600")
    assert crash.unseen() == [path] and crash.unseen() == []                # told once


def test_crash_reports_only_go_to_https_and_are_logged(store, monkeypatch):
    monkeypatch.setattr(crash, "_enabled", lambda: True)
    path = crash.write_report(*_boom())
    assert crash.send(path, "http://insecure.example/c")[0] is False
    import requests
    sent = {}
    class R: status_code = 200
    monkeypatch.setattr(requests, "post", lambda url, data=None, **k: (sent.update(url=url, data=data), R())[1])
    ok, msg = crash.send(path, "https://reports.example/c")
    assert ok and sent["url"] == "https://reports.example/c" and b"ValueError" in sent["data"]
    assert ledger.entries()[-1]["what"] == "crash report" and ledger.entries()[-1]["dest"] == "reports.example"


def test_crash_hooks_cover_threads(store, monkeypatch):
    import threading
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__); monkeypatch.setattr(threading, "excepthook", threading.__excepthook__)
    monkeypatch.setattr(crash, "_installed", False)
    crash.install(lambda: True)
    t = threading.Thread(target=lambda: 1 / 0, name="worker-7"); t.start(); t.join()
    reports = crash.reports()
    assert len(reports) == 1 and "ZeroDivisionError" in open(reports[0]).read() and "thread worker-7" in open(reports[0]).read()


# ── memory ─────────────────────────────────────────────────────────
def test_memory_categories_expiry_and_migration(store):
    json.dump({"facts": ["[01.01.2026] loves coffee", "works as a developer"]}, open(paths.MEMORY_FILE, "w"))
    items = tools.memory_items()                                              # the old flat list is understood
    assert [(i["text"], i["category"], i["created"]) for i in items] == [("loves coffee", "preference", "2026-01-01"),
                                                                         ("works as a developer", "work", "")]
    assert "until" in tools.save_memory("dentist on Friday", "task", 3)
    assert "Remembered" in tools.save_memory("sister is called Maria")
    saved = json.load(open(paths.MEMORY_FILE))
    assert saved["version"] == 2 and [i["category"] for i in saved["items"]] == ["preference", "work", "task", "people"]
    assert saved["items"][2]["expires"] > memory.today()
    saved["items"][2]["expires"] = "2020-01-01"; json.dump(saved, open(paths.MEMORY_FILE, "w"))
    assert "dentist" not in tools.read_memory() and len(tools.memory_items()) == 3   # expired memories vanish
    assert "[People] sister is called Maria" in tools.read_memory()
    assert tools.save_memory("x", category="nonsense") and tools.memory_items()[-1]["category"] == "other"


def test_memory_relevance_picks_what_fits_the_question():
    items = [memory.make(f"random fact number {i} about topic{i}", "other") for i in range(30)]
    items.insert(3, memory.make("The user's name is Martin", "about_me"))
    items.insert(7, memory.make("Prefers window seats on flights", "preference"))
    items.insert(11, memory.make("Is allergic to peanuts", "preference"))
    chosen = [i["text"] for i in memory.relevant(items, "book me a flight to Berlin, which seat?", limit=6)]
    assert len(chosen) == 6 and "Prefers window seats on flights" in chosen and "The user's name is Martin" in chosen
    assert chosen == [i["text"] for i in items if i["text"] in chosen]                # original order kept
    text = memory.prompt_text(items, "any food I should avoid? peanuts", limit=6)
    assert "allergic to peanuts" in text and "more memories not shown" in text
    assert len(memory.relevant(items[:5], "anything")) == 5                           # few memories: all of them
    assert memory.relevant([], "x") == [] and memory.prompt_text([], "x") == ""
    bg = [memory.make(f"факт {i}", "other") for i in range(20)] + [memory.make("Работи като програмист в София", "work")]
    assert "програмист" in memory.prompt_text(bg, "какво работя?", limit=4)             # works for Bulgarian too


# ── memories found by meaning (keywords) ───────────────────────────
def test_keywords_make_a_memory_match_a_question_with_no_shared_words():
    items = [memory.make(f"filler fact number {i} about topic{i}", "other") for i in range(30)]
    allergy = memory.make("Is allergic to peanuts", "other", tags="food allergy nuts eating restaurant menu snack diet health храна алергия ядки ресторант")
    plain = memory.make("Is allergic to peanuts", "other")
    question = "what should I order at the restaurant tonight?"
    assert "Is allergic to peanuts" not in [i["text"] for i in memory.relevant([plain] + items, question, limit=5)]   # words alone miss it
    assert "Is allergic to peanuts" in [i["text"] for i in memory.relevant([allergy] + items, question, limit=5)]     # keywords find it
    assert "Is allergic to peanuts" in [i["text"] for i in memory.relevant([allergy] + items, "какво да ям в ресторанта", limit=5)]
    assert "food allergy" not in memory.line(allergy)                              # keywords are for matching only, never shown


def test_keyword_answers_are_parsed_tolerantly():
    facts = ["likes hiking", "works as a nurse", "has a dog called Rex"]
    good = 'Sure!\n```json\n{"1": "mountain outdoors walk trail", "2": ["hospital", "shift", "patients"], "9": "ignored", "x": "bad"}\n```'
    assert memory.parse_tags(good, facts) == {"likes hiking": "mountain outdoors walk trail", "works as a nurse": "hospital shift patients"}
    lines = "1. mountain, outdoors, walk\n2: hospital shift\n3) pet animal vet walk walk"
    assert memory.parse_tags(lines, facts)["has a dog called Rex"] == "pet animal vet walk"          # duplicates removed
    assert memory.parse_tags("I cannot help with that", facts) == {} and memory.parse_tags("", facts) == {}
    prompt = memory.tagging_prompt(facts)
    assert "1. likes hiking" in prompt and "3. has a dog called Rex" in prompt and "JSON" in prompt
    assert memory.untagged([memory.make("a"), memory.make("b", tags="x y")]) == ["a"]


def test_keywords_survive_saving_and_are_only_set_once(store):
    seen = []
    tools.TAG_HOOK = lambda: seen.append(1)
    try:
        tools.save_memory("Is allergic to peanuts")
    finally:
        tools.TAG_HOOK = None
    assert seen == [1]                                                             # saving asks for keywords
    assert tools.set_memory_tags({"Is allergic to peanuts": "food nuts restaurant", "unknown fact": "x"}) == 1
    assert tools.memory_items()[0]["tags"] == "food nuts restaurant"
    assert tools.set_memory_tags({"Is allergic to peanuts": "other words"}) == 0   # existing keywords are kept
    assert json.load(open(paths.MEMORY_FILE))["items"][0]["tags"] == "food nuts restaurant"
    assert tools.list_memories()[0].endswith("Is allergic to peanuts")             # display text is unchanged
