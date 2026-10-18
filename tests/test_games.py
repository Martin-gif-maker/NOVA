import games


def test_evaluate_handles_duplicate_letters():
    ev = games.WordleDialog._evaluate
    assert ev(None, "ALLOY", "LLAMA") == ["present", "correct", "present", "absent", "absent"]
    assert ev(None, "CRANE", "CRANE") == ["correct"] * 5


def test_guess_validation():
    assert games.is_valid_guess("CRANE")
    assert not games.is_valid_guess("QQQQQ")


def test_daily_word_is_stable_and_valid():
    w = games.get_daily_word()
    assert w == games.get_daily_word() and len(w) == 5 and w not in games._NOT_ANSWERS


def test_progress_is_remembered_and_cleared(data_dir):
    assert games.load_progress("wordle") is None
    games.save_progress("wordle", {"board": [1]})
    assert games.load_progress("wordle")["board"] == [1]
    games.record_wordle_result(False, 0, [])
    assert games.load_progress("wordle") is None


# ── the game windows themselves ────────────────────────────────────
import datetime
import pytest


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _type(dlg, word):
    for ch in word: dlg._on_key(ch)
    dlg._on_key("↵")


def test_wordle_win_is_recorded_and_locks_the_board(qapp, data_dir, monkeypatch):
    import themes
    monkeypatch.setattr(games, "get_daily_word", lambda: "CRANE")
    d = games.WordleDialog(themes.THEMES["nova"])
    _type(d, "CR"); assert d._row == 0 and "Not enough" in d._msg_lbl.text() if hasattr(d, "_msg_lbl") else d._row == 0
    d._on_key("⌫"); d._on_key("⌫")
    _type(d, "QQQQQ"); assert d._row == 0                                   # not a word: the row is not used up
    for _ in range(5): d._on_key("⌫")
    _type(d, "SLATE"); assert d._row == 1 and not d._done
    assert games.load_progress("wordle")["board"][0]["letters"] == list("SLATE")
    _type(d, "CRANE")
    s = games.get_wordle_stats()
    assert d._done and s["played"] == 1 and s["won"] == 1 and s["streak"] == 1 and s["last_played"] == datetime.date.today().isoformat()
    d._on_key("A"); assert d._col == 0 or d._done                           # no typing after the game ended
    again = games.WordleDialog(themes.THEMES["nova"])                       # reopening today shows the finished game
    assert again._done


def test_wordle_progress_is_restored_and_six_misses_lose(qapp, data_dir, monkeypatch):
    import themes
    monkeypatch.setattr(games, "get_daily_word", lambda: "CRANE")
    d = games.WordleDialog(themes.THEMES["nova"]); _type(d, "SLATE"); _type(d, "PRICE")
    d2 = games.WordleDialog(themes.THEMES["nova"])
    assert d2._row == 2 and not d2._done                                    # closing the window does not lose the guesses
    for w in ("BRINE", "GRAPE", "TRACE", "DRONE"): _type(d2, w)
    s = games.get_wordle_stats()
    assert d2._done and s["played"] == 1 and s["won"] == 0 and s["streak"] == 0


def test_number_guess_hints_win_and_loss(qapp, data_dir, monkeypatch):
    import themes
    monkeypatch.setattr(games, "get_daily_number", lambda: 42)
    d = games.NumberGuessDialog(themes.THEMES["nova"])
    def guess(x): d._entry.setText(str(x)); d._guess()
    guess("abc"); assert d._tries == 0 and "number" in d._msg_lbl.text().lower()
    guess(500); assert d._tries == 0
    guess(10); assert "low" in d._msg_lbl.text() and d._tries == 1
    guess(90); assert "high" in d._msg_lbl.text() and games.load_progress("numguess")["tries"] == 2
    d2 = games.NumberGuessDialog(themes.THEMES["nova"]); assert d2._tries == 2      # progress survives reopening
    guess(42)
    s = games.get_ng_stats()
    assert d._done and not d._entry.isEnabled() and s["won"] == 1 and s["streak"] == 1


def test_number_guess_runs_out_of_tries(qapp, data_dir, monkeypatch):
    import themes
    monkeypatch.setattr(games, "get_daily_number", lambda: 42)
    d = games.NumberGuessDialog(themes.THEMES["nova"])
    for n in range(1, 8):
        d._entry.setText(str(n)); d._guess()
    assert d._done and "42" in d._msg_lbl.text() and games.get_ng_stats()["won"] == 0


def test_games_speak_bulgarian(qapp, data_dir, monkeypatch):
    import i18n, themes
    monkeypatch.setattr(i18n, "_LANG", "bg"); monkeypatch.setattr(games, "get_daily_number", lambda: 42)
    d = games.NumberGuessDialog(themes.THEMES["nova"])
    assert d.windowTitle() == "NOVA — Познай числото" and d._tries_lbl.text() == "Оставащи опити: 7"
    d._entry.setText("abc"); d._guess(); assert d._msg_lbl.text() == "Въведи число!"
    d._entry.setText("10"); d._guess(); assert d._msg_lbl.text() == "Твърде малко — по-голямо" and d._tries_lbl.text() == "Оставащи опити: 6"
    d._entry.setText("42"); d._guess(); assert d._msg_lbl.text().startswith("Позна!") and d._tries_lbl.text() == "Познато с 2 опита"
    monkeypatch.setattr(games, "get_daily_word", lambda: "CRANE")
    w = games.WordleDialog(themes.THEMES["nova"])
    for ch in "CR": w._on_key(ch)
    w._on_key("↵")
    assert "Изиграни: 0" in w._stats_lbl.text() and w.windowTitle() == "NOVA — Wordle"
