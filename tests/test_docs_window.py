"""The window's side of documents (win_docs.py) and where API keys are kept when the Keychain fails (keystore.py)."""
import os, stat, time
import pytest
import docs, keystore, paths
from conftest import MemoryKeyring
from gui_support import FakeCompletions


def _wait_for(win, cond, secs=8):
    end = time.time() + secs
    while not cond() and time.time() < end: win._pump(50)
    assert cond()


def _system_lines(win) -> list:
    from widgets import MessageBubble
    lay = win.chat_area._layout
    return [w._label.text() for w in (lay.itemAt(i).widget() for i in range(lay.count()))
            if isinstance(w, MessageBubble) and w._role == "system"]


@pytest.fixture
def library(monkeypatch, tmp_path):
    import embeddings
    monkeypatch.setattr(embeddings, "ready", lambda: False)
    monkeypatch.setattr(paths, "DOCS_FILE", str(tmp_path / "library.json"))
    return docs.library()


def test_a_dropped_folder_is_indexed_and_reported(win, library, tmp_path):
    folder = tmp_path / "Contracts"; folder.mkdir()
    (folder / "lease.txt").write_text("The deposit is two monthly rents. " * 40)
    (folder / "notes.md").write_text("Call the landlord about the heating.")
    (folder / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    win._index_folder(str(folder))
    _wait_for(win, lambda: any("Added" in t for t in _system_lines(win)))
    line = [t for t in _system_lines(win) if "Added" in t][-1]
    assert "Added 2 documents from Contracts" in line and "1 could not be read" in line
    assert set(library.names()) == {"lease.txt", "notes.md"}
    assert "lease.txt" in win.messages[0]["content"]                     # the AI is told which documents exist


def test_an_empty_folder_says_so(win, library, tmp_path):
    (tmp_path / "Empty").mkdir()
    win._index_folder(str(tmp_path / "Empty"))
    _wait_for(win, lambda: any("No readable documents" in t for t in _system_lines(win)))


def test_a_long_file_with_a_question_is_indexed_then_asked_about(win, library, tmp_path):
    f = tmp_path / "handbook.txt"; f.write_text("Employees receive 25 days of paid leave. " * 600)     # > INLINE_LIMIT
    FakeCompletions.script = [["Twenty-five days."]]
    win._submit_file(str(f), "how much leave do I get?")
    _wait_for(win, lambda: any(m.get("role") == "assistant" and "Twenty-five" in str(m.get("content")) for m in win.messages))
    asked = [m["content"] for m in win.messages if m.get("role") == "user"][-1]
    assert asked.startswith("how much leave do I get?") and 'document="handbook.txt"' in asked
    assert library.names() == ["handbook.txt"]


def test_documents_changed_on_disk_are_reported_after_a_refresh(win, library, tmp_path):
    f = tmp_path / "plan.txt"; f.write_text("first plan " * 50)
    library.add_file(str(f))
    time.sleep(0.01); f.write_text("second plan, now longer " * 60); os.utime(f, (time.time() + 5, time.time() + 5))
    import win_docs
    win_docs.DocsMixin._refresh_documents(win)                           # (the `win` fixture turns the start-up one off)
    _wait_for(win, lambda: any("brought up to date" in t for t in _system_lines(win)))
    assert "1 changed" in [t for t in _system_lines(win) if "brought up to date" in t][-1]


def test_an_unreadable_file_is_reported_not_sent(win, library, tmp_path):
    f = tmp_path / "photo.raw"; f.write_bytes(os.urandom(4000))
    win._submit_file(str(f))
    _wait_for(win, lambda: any("photo.raw" in t for t in _system_lines(win) if not t.startswith("Reading")))
    assert not any("photo.raw" in str(m.get("content")) for m in win.messages if m.get("role") == "user")


# ── API keys when the Keychain is not available ──
class _BrokenKeyring(MemoryKeyring):
    def set_password(self, *a): raise RuntimeError("Keychain locked")
    def get_password(self, *a): raise RuntimeError("Keychain locked")
    def delete_password(self, *a): raise RuntimeError("Keychain locked")


@pytest.fixture
def no_keychain(monkeypatch, tmp_path):
    monkeypatch.setattr(keystore, "_keyring", _BrokenKeyring())
    monkeypatch.setattr(keystore, "_KEY_FILE", str(tmp_path / ".nova_key"))
    return tmp_path


def test_a_key_falls_back_to_a_private_file(no_keychain):
    assert keystore._save_api_key("gsk_test", "groq") == "file"
    f = no_keychain / ".nova_key"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600                      # only you can read it
    assert keystore._get_api_key("groq") == "gsk_test"
    assert keystore._save_api_key("sk-ant-test", "anthropic") == "file" and (no_keychain / ".nova_key_anthropic").exists()
    keystore.delete_api_key("groq")
    assert not f.exists() and keystore._get_api_key("groq") == ""


def test_other_secrets_are_never_written_to_a_file(no_keychain):
    assert keystore.set_secret("mcp_token", "secret") is False and keystore.get_secret("mcp_token") == ""
    assert list(no_keychain.iterdir()) == []
