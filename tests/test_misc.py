import json, os, time, hashlib
import pytest
import paths, updater, diagnostics, models, dialogs


def test_old_settings_are_upgraded_and_keys_removed():
    cfg = paths.upgrade_config({"groq_api_key": "secret", "lang": "bg", "theme": "soft"})
    assert "groq_api_key" not in cfg and "lang" not in cfg
    assert cfg["schema"] == paths.SCHEMA_VERSION and cfg["retention_days"] == 90 and cfg["theme"] == "soft"
    assert paths.upgrade_config(dict(cfg)) == cfg                       # idempotent


def test_retention_removes_only_old_data(monkeypatch, tmp_path):
    sess = tmp_path / "s"; sess.mkdir()
    old, new = sess / "old.json", sess / "new.json"; old.write_text("{}"); new.write_text("{}")
    os.utime(old, (time.time() - 200 * 86400,) * 2)
    act = tmp_path / "act.log"
    act.write_text('{"t": "2020-01-01 10:00:00", "tool": "x"}\n' + json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": "y"}) + "\n")
    monkeypatch.setattr(paths, "SESSIONS_DIR", str(sess)); monkeypatch.setattr(paths, "ACTIVITY_FILE", str(act))
    assert paths.apply_retention({"retention_days": 90, "activity_days": 30}) == 2
    assert not old.exists() and new.exists() and '"tool": "y"' in act.read_text() and '"tool": "x"' not in act.read_text()
    assert paths.apply_retention({"retention_days": 0, "activity_days": 0}) == 0       # 0 = keep forever


def test_update_versions_and_checksum(tmp_path, monkeypatch):
    assert updater.is_newer("6.1.0", "6.0.0") and not updater.is_newer("6.0.0", "6.0.0") and updater.is_newer("10.0.0", "9.9.9")
    with pytest.raises(ValueError): updater.fetch_info("http://insecure.example/feed.json")
    with pytest.raises(ValueError): updater.download("https://x.example/a.dmg", "not-a-hash", str(tmp_path))
    data = b"installer-bytes"
    class R:
        headers = {"content-length": str(len(data))}
        def raise_for_status(self): pass
        def iter_content(self, n): yield data
        def __enter__(self): return self
        def __exit__(self, *a): pass
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    ok = updater.download("https://x.example/NOVA.dmg", hashlib.sha256(data).hexdigest(), str(tmp_path))
    assert open(ok, "rb").read() == data
    with pytest.raises(ValueError, match="checksum"):
        updater.download("https://x.example/NOVA2.dmg", "0" * 64, str(tmp_path))
    assert not (tmp_path / "NOVA2.dmg.part").exists()                   # tampered download is deleted


def test_diagnostics_hide_secrets(monkeypatch, tmp_path):
    log = tmp_path / "nova.log"; log.write_text("ok line\nAuthorization: Bearer abcdefghijklmnop1234\nkey gsk_ABCDEFGH12345678\n")
    monkeypatch.setattr(paths, "LOG_FILE", str(log))
    out = diagnostics.build_diagnostics({"theme": "soft", "groq_api_key": "gsk_SHOULDNOTAPPEAR1234"})
    assert "gsk_" not in out and "Bearer abcdef" not in out and "theme" in out and "SHOULDNOTAPPEAR" not in out


def test_models_reconcile_keeps_working_models():
    saved, vsaved = dict(models.MODELS), list(models.VISION_MODELS)
    try:
        assert models.reconcile(set(m[0] for m in models.MODELS.values()) | set(vsaved)) == [] and models.MODELS == saved
        assert models.reconcile(set()) == []                                # unknown availability: change nothing
        models.apply_overrides({"smart": "my/custom-model"})
        assert models.MODELS["smart"][0] == "my/custom-model"
    finally:
        models.MODELS.clear(); models.MODELS.update(saved); models.VISION_MODELS[:] = vsaved


def test_sessions_are_searchable_by_content(tmp_path):
    for name, title, text in (("a.json", "Cooking", "pasta recipe"), ("b.json", "Taxes", "invoice due")):
        (tmp_path / name).write_text(json.dumps({"title": title, "created": "2026-10-07T10:00:00",
                                                 "messages": [{"role": "user", "content": text}]}))
    rows = dialogs.read_sessions(str(tmp_path))
    assert {r["title"] for r in rows} == {"Cooking", "Taxes"}
    assert [r["title"] for r in rows if "invoice" in r["text"]] == ["Taxes"]


def test_replacement_avoids_duplicate_slots_and_keeps_vision_fallbacks():
    saved, vsaved = dict(models.MODELS), list(models.VISION_MODELS)
    try:
        avail = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"}          # what Groq offered on 2026-10-07
        models.MODELS["mix"] = ("qwen/qwen3-32b", "QWEN")                                   # a retired model
        notes = models.reconcile(avail)
        assert models.MODELS["mix"][0] == "qwen/qwen3.8-27b" and len({v[0] for v in models.MODELS.values()}) == 3 and notes
        assert models.VISION_MODELS == ["qwen/qwen3.8-27b"]                                 # scout/maverick are gone
    finally:
        models.MODELS.clear(); models.MODELS.update(saved); models.VISION_MODELS[:] = vsaved


# ── version and "what's new" ───────────────────────────────────────
def test_version_lives_in_one_place():
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert re.fullmatch(r"\d+\.\d+\.\d+", paths.__version__)
    for name in ("NOVA.spec", "packaging/build_mac.sh", "create_shortcut.py"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert not re.search(r'["\-]\d+\.\d+\.\d+["\.]', text.replace("0.0.1", "")), name      # no hard-coded version left
    assert f"## {paths.__version__}" in open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()   # every release is described
    import create_shortcut
    assert create_shortcut._version() == paths.__version__


def test_whats_new_is_for_updaters_once_per_release():
    import whatsnew
    assert whatsnew.release("6.1.3") == "6.1" and whatsnew.notes("6.1.0") and whatsnew.notes("9.9.0") == []
    assert whatsnew.should_show("", True, "6.1.0") and whatsnew.should_show("6.0.0", True, "6.1.0")
    assert not whatsnew.should_show("6.1.0", True, "6.1.2")              # a small fix release does not repeat the note
    assert not whatsnew.should_show("", False, "6.1.0")                  # brand-new users get the wizard instead
    assert not whatsnew.should_show("6.1.0", True, "9.9.0")              # nothing written for that release
    t = whatsnew.text("6.1.0")
    assert t.startswith("**✨  What's new in NOVA 6.1**") and t.count("• ") == len(whatsnew.notes("6.1.0")) and whatsnew.text("9.9.0") == ""


def test_the_feature_guide_names_every_tool_and_no_tool_that_does_not_exist():
    """WHAT_NOVA_CAN_DO.md is the complete list for people: it must not fall behind the tools."""
    import re, tools
    text = open(os.path.join(paths.CODE_DIR, "WHAT_NOVA_CAN_DO.md"), encoding="utf-8").read()
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text))
    real = set(tools.TOOL_FUNCTIONS) - set(tools.PLUGIN_TOOLS) - set(tools.MCP_TOOLS)
    missing = sorted(real - named - {"more_tools"})                  # more_tools is plumbing between the AI and NOVA
    unknown = sorted(n for n in named - real if n not in ("update_feed",))
    assert not missing, f"tools the guide does not mention: {missing}"
    assert not unknown, f"the guide names tools that do not exist: {unknown}"
    assert paths.__version__ in text
