"""Search by meaning, with a stand-in for the model: vectors are kept with each document, made again for another
model, used next to the words, and the model download is checked before anything is kept."""
import hashlib, io
import numpy as np
import pytest
import docs, embeddings

# The stand-in model: each concept is one direction; a text points along the concepts it mentions.
CONCEPTS = [("deposit", "security payment", "депозит", "put down up front"), ("flight", "plane", "самолет"),
            ("pancake", "crepe", "flour"), ("weather", "rain")]


def _vec(text: str):
    v = np.zeros(embeddings.DIM, np.float32); low = text.lower()
    for k, words in enumerate(CONCEPTS):
        if any(w in low for w in words): v[k] = 1.0
    v[-1] = 0.05                                                     # nothing is exactly orthogonal
    return v / np.linalg.norm(v)


@pytest.fixture
def model(monkeypatch):
    calls = {"passages": 0}
    def passages(texts):
        calls["passages"] += len(texts); return np.vstack([_vec(t) for t in texts])
    monkeypatch.setattr(embeddings, "ready", lambda: True)
    monkeypatch.setattr(embeddings, "embed_passages", passages)
    monkeypatch.setattr(embeddings, "embed_query", _vec)
    return calls


@pytest.fixture
def lib(tmp_path):
    return docs.Library(str(tmp_path / "docs.json"))


def _add(lib, tmp_path, name, text):
    f = tmp_path / name; f.write_text(text); return lib.add_file(str(f))


def test_vectors_are_kept_with_the_document_and_survive_a_restart(model, lib, tmp_path):
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    assert model["passages"] == 1 and lib.missing_vectors() == 0
    fresh = docs.Library(lib.path)
    assert fresh.missing_vectors() == 0 and fresh.search("How much do I put down up front?")[0]["doc"] == "lease.txt"
    assert model["passages"] == 1                                     # nothing was worked out again


def test_a_reworded_question_is_found_and_labelled_for_the_ai(model, lib, tmp_path, monkeypatch):
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    _add(lib, tmp_path, "trip.txt", "The flight to Berlin leaves at 07:40.")
    hit = lib.search("How much do I put down up front?")[0]
    assert hit["doc"] == "lease.txt" and hit["how"] == "meaning"
    monkeypatch.setattr(docs, "library", lambda: lib)
    assert "found by meaning" in docs.answer_material("How much do I put down up front?").split("\n")[0]
    both = lib.search("security payment")[0]
    assert both["doc"] == "lease.txt" and both["how"] == "both"
    assert "found by meaning" not in docs.answer_material("security payment")


def test_bulgarian_questions_reach_english_passages(model, lib, tmp_path):
    _add(lib, tmp_path, "trip.txt", "The flight to Berlin leaves at 07:40.")
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    assert lib.search("Кога излита самолетът?")[0]["doc"] == "trip.txt"


def test_unrelated_questions_and_failures_fall_back_to_words(model, lib, tmp_path, monkeypatch):
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    assert lib.search("What is the weather like?") == []              # nothing about it, nothing passed off
    def broken(_q): raise RuntimeError("model file damaged")
    monkeypatch.setattr(embeddings, "embed_query", broken)
    assert [h["how"] for h in lib.search("monthly rents")] == ["words"]


def test_documents_without_vectors_get_them_later(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(embeddings, "ready", lambda: False)
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    _add(lib, tmp_path, "recipe.txt", "Pancakes need flour, eggs and milk.")
    monkeypatch.setattr(embeddings, "ready", lambda: True)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: np.vstack([_vec(t) for t in texts]))
    monkeypatch.setattr(embeddings, "embed_query", _vec)
    assert lib.missing_vectors() == 2
    seen = []
    assert lib.embed_missing(lambda done, total, name: seen.append((done, total))) == 2
    assert lib.missing_vectors() == 0 and seen == [(0, 2), (1, 2)]
    assert lib.search("What ingredients for crepes?")[0]["doc"] == "recipe.txt"
    monkeypatch.setattr(embeddings, "MODEL_ID", "another-model")      # a new model: the old vectors do not count
    lib.reload()
    assert lib.missing_vectors() == 2 and lib.search("What ingredients for crepes?") == []


def test_alphabet_detection():
    assert docs._cyrillic("Кога излита самолетът?") and not docs._cyrillic("When does the plane leave?")
    assert docs._cyrillic("Договор 2026 (PDF) за наем") and not docs._cyrillic("Lease 2026 — София")


# ── the download ──
class _Response:
    def __init__(self, data): self.data = data; self.headers = {"content-length": str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_content(self, n):
        buf = io.BytesIO(self.data)
        while chunk := buf.read(n): yield chunk


@pytest.fixture
def small_model(monkeypatch, tmp_path):
    """Pretend the model is two small files, served by a fake web server (no network)."""
    files = {"model_quantized.onnx": b"o" * 70000, "tokenizer.json": b"{}" * 10}
    monkeypatch.setattr(embeddings, "FILES", {n: (n, hashlib.sha256(b).hexdigest(), len(b)) for n, b in files.items()})
    monkeypatch.setenv("NOVA_MEANING_MODEL", str(tmp_path / "model"))
    served = dict(files)
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **k: _Response(served[url.rsplit("/", 1)[1]]))
    return served


def test_the_model_is_downloaded_checked_and_put_in_place(small_model, tmp_path):
    steps = []
    folder = embeddings.download(steps.append)
    assert folder == str(tmp_path / "model") and embeddings.installed()
    assert steps[-1] == 1.0 and steps == sorted(steps)
    embeddings.remove()
    assert not embeddings.installed() and not (tmp_path / "model").exists()


def test_a_tampered_download_is_thrown_away(small_model, tmp_path):
    small_model["tokenizer.json"] = b"[]" * 10                         # same size, different content
    with pytest.raises(embeddings.EmbeddingError, match="checksum"):
        embeddings.download()
    left = sorted(p.name for p in (tmp_path / "model").iterdir())
    assert left == ["model_quantized.onnx"] and not embeddings.installed()    # nothing half-written is kept


def test_a_download_can_be_cancelled(small_model, tmp_path):
    with pytest.raises(embeddings.EmbeddingError, match="cancelled"):
        embeddings.download(cancelled=lambda: True)
    assert list((tmp_path / "model").iterdir()) == []


# ── the Documents window ──
def _wait(app, cond, secs=5):
    import time
    end = time.time() + secs
    while not cond() and time.time() < end:
        app.processEvents(); time.sleep(0.01)
    assert cond()


def test_the_documents_window_downloads_and_prepares(app, lib, tmp_path, monkeypatch):
    import themes, dialogs
    monkeypatch.setattr(embeddings, "runtime_installed", lambda: True)
    state = {"installed": False}
    monkeypatch.setattr(embeddings, "installed", lambda: state["installed"])
    monkeypatch.setattr(embeddings, "ready", lambda: state["installed"])
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: np.vstack([_vec(t) for t in texts]))
    _add(lib, tmp_path, "lease.txt", "The security payment equals two monthly rents.")
    def fake_download(progress=None, cancelled=None):
        for f in (0.5, 1.0): progress(f)
        state["installed"] = True
    monkeypatch.setattr(embeddings, "download", fake_download)
    d = dialogs.DocumentsDialog(themes.THEMES["soft"], lib)
    assert d.meaning_btn.text() == "Download (135 MB)" and lib.missing_vectors() == 1
    d.meaning_btn.click()
    _wait(app, lambda: d._meaning_job is None)
    assert d.meaning_btn.text() == "Remove" and "is on" in d.meaning_status.text()
    assert lib.missing_vectors() == 0                                  # the document was prepared right after


def test_a_failed_download_says_why_and_offers_it_again(app, lib, monkeypatch):
    import themes, dialogs
    monkeypatch.setattr(embeddings, "runtime_installed", lambda: True)
    monkeypatch.setattr(embeddings, "installed", lambda: False)
    def broken(progress=None, cancelled=None): raise embeddings.EmbeddingError("No internet connection.")
    monkeypatch.setattr(embeddings, "download", broken)
    d = dialogs.DocumentsDialog(themes.THEMES["soft"], lib)
    d.meaning_btn.click()
    _wait(app, lambda: d._meaning_job is None)
    assert "No internet connection." in d.meaning_status.text() and d.meaning_btn.text().startswith("Download")


def test_the_documents_window_shows_home_paths_short(app, lib, tmp_path, monkeypatch):
    import os, themes, dialogs
    monkeypatch.setattr(embeddings, "runtime_installed", lambda: False)
    home = tmp_path / "home"; (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
    f = home / "Documents" / "lease.txt"; f.write_text("The deposit is two monthly rents.")
    lib.add_file(str(f))
    d = dialogs.DocumentsDialog(themes.THEMES["soft"], lib)
    assert d.listw.item(0).text().endswith("~/Documents/lease.txt")


def test_memories_are_chosen_by_meaning_too(model):
    import memory
    CONCEPTS.append(("restaurant", "order", "peanut", "allergic"))           # food: one meaning, no shared word
    try:
        items = [memory.make(f"likes film number {i}", "preference") for i in range(20)]
        items.insert(3, memory.make("is allergic to peanuts", "health"))
        picked = memory.relevant(items, "what should I order at the restaurant?")
        assert len(picked) == memory.PROMPT_LIMIT and any("peanuts" in it["text"] for it in picked)
    finally:
        CONCEPTS.pop()
