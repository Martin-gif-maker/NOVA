"""Search by meaning with the real on-device model (embeddings.py) on tests/meaning_corpus.py.

Runs when the model is on this Mac:  NOVA_MEANING_MODEL=<folder with model_quantized.onnx and tokenizer.json>
(the folder NOVA downloads it to is ~/Library/Application Support/NOVA/models/multilingual-e5-small).
"""
import os
import pytest
import docs, embeddings
import meaning_corpus as C

pytestmark = pytest.mark.skipif(not (os.environ.get("NOVA_MEANING_MODEL") and embeddings.ready()),
                                reason="needs the meaning model: NOVA_MEANING_MODEL=<folder>")


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    d = tmp_path_factory.mktemp("meaning")
    lib = docs.Library(str(d / "docs.json"))
    for name, text in C.PASSAGES:
        (d / name).write_text(text); lib.add_file(str(d / name))
    return lib


def _top(lib, question):
    hits = lib.search(question)
    return hits[0]["doc"] if hits else None


def test_every_passage_got_its_vector(lib):
    assert lib.missing_vectors() == 0


def test_reworded_questions_are_found(lib):
    found = sum(_top(lib, q) == want for q, want in C.REWORDED)
    assert found >= 10, f"{found} of {len(C.REWORDED)}"                 # words alone: 2, Apple's model: 6


def test_bulgarian_questions_find_english_passages(lib):
    found = sum(_top(lib, q) == want for q, want in C.BULGARIAN)
    assert found >= 5, f"{found} of {len(C.BULGARIAN)}"


def test_questions_in_the_documents_own_words_still_come_first(lib):
    assert all(_top(lib, q) == want for q, want in C.EXACT)


def test_unrelated_questions_find_nothing(lib):
    for q in ("What is the capital of Australia?", "Who won the football world cup in 1998?",
              "What is the boiling point of mercury?",
              "Коя е столицата на Австралия?", "Кой спечели световното по футбол през 1998?", "Как се плете шал?"):
        assert lib.search(q) == [], q
    # "How do I knit a scarf?" comes closest of all to "apply two coats of primer to bare wood" (both are crafts)
    # and is passed on, labelled as found by meaning - the AI then says the documents do not cover it.


def test_a_passage_found_only_by_meaning_is_labelled_for_the_ai(lib, monkeypatch):
    monkeypatch.setattr(docs, "library", lambda: lib)
    text = docs.answer_material("How much vacation do staff get?")
    assert text.startswith("[handbook.txt]") and "found by meaning" in text.split("\n")[0]
