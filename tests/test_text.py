import json
import pytest
import chatutil
import mdrender
import prompts
import workers


@pytest.mark.parametrize("expr,expected", [
    ("2+2", 4), ("15% of 200", 30), ("2^10", 1024), ("3x4", 12), ("(1+2)*3", 9), ("10/4", 2.5),
])
def test_calculator(expr, expected):
    assert mdrender.safe_calculate(expr) == expected


@pytest.mark.parametrize("expr", ["9**9**9**9", "hello", "__import__('os')", "2+", "1e400*1e400"])
def test_calculator_rejects_bad_input(expr):
    with pytest.raises((ValueError, SyntaxError)):
        mdrender.safe_calculate(expr)


def test_calculator_zero_division():
    with pytest.raises(ZeroDivisionError):
        mdrender.safe_calculate("1/0")


def test_markdown_leaves_code_alone():
    import re
    for render in (mdrender._md_to_html, mdrender._md_to_html_basic):
        html = render("```py\nx = a * b * c\n- item\n```\n*it* and 2 * 3 * 4")
        plain = re.sub(r"<[^>]+>", "", html)
        assert "x = a * b * c" in plain and "- item" in plain and "2 * 3 * 4" in plain
        assert "<i>it</i>" in html or "<em>it</em>" in html


def test_markdown_escapes_html():
    assert "<script>" not in mdrender._md_to_html("<script>alert(1)</script>")
    assert "<script>" not in mdrender._md_to_html_basic("<script>alert(1)</script>")


def test_strip_think():
    assert mdrender._strip_think("a<think>hidden</think> b") == "a b"
    assert mdrender._strip_think("a<think>unfinished") == "a"


def test_safe_tail_never_starts_with_tool_result():
    msgs = [{"role": "assistant", "content": ""}, {"role": "tool", "content": "r"}, {"role": "assistant", "content": "z"}]
    assert chatutil._safe_tail(msgs, 2)[0]["role"] == "assistant"


def test_plain_messages_drops_noise():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi" + chatutil._LENGTH_HINTS[0]},
            {"role": "assistant", "content": ""}, {"role": "tool", "content": "x"},
            {"role": "assistant", "content": "yo"}]
    out = chatutil._plain_messages(msgs)
    assert [m["content"] for m in out] == ["hi", "yo"]


def test_compact_history_keeps_two_turns_of_plumbing():
    def turn(n, big=False):
        return [{"role": "user", "content": f"q{n}"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": str(n)}]},
                {"role": "tool", "tool_call_id": str(n), "content": json.dumps({"ok": True, "result": ("X" * 2000) if big else f"out{n}"})},
                {"role": "assistant", "content": f"a{n}"}]
    msgs = [{"role": "system", "content": "s"}] + turn(1) + turn(2, big=True) + [{"role": "user", "content": "q3"}]
    out = workers._compact_history(msgs)
    assert not any(m.get("tool_call_id") == "1" for m in out)                       # oldest turn: plumbing dropped
    kept = json.loads([m for m in out if m.get("tool_call_id") == "2"][0]["content"])                # previous turn kept, shortened,
    assert kept["ok"] is True and kept["result"].endswith("[shortened]") and len(kept["result"]) < 900   # and still valid JSON
    assert any(m.get("content") == "q1" for m in out) and any(m.get("content") == "a1" for m in out)   # its text survives
    assert out[-1]["content"] == "q3"


def test_retry_after_parsing():
    assert workers.AIWorker._retry_after("Please try again in 7.5s.") == 7.5
    assert workers.AIWorker._retry_after("try again in 1m3.5s") == 63.5
    assert workers.AIWorker._retry_after("nothing") is None


def test_system_prompt_is_slim():
    assert len(prompts._BASE_PROMPT_EN) < 1100           # sent with every request


def test_rich_markdown_tables_links_lists_and_highlighting():
    html = mdrender._md_to_html("1. a\n2. b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n[ok](https://e.com) [bad](javascript:alert(1))\n\n```python\nprint(1)\n```")
    assert "<ol>" in html and "<table" in html and 'href="https://e.com"' in html
    assert "javascript:" not in html.split("href=")[-1] or 'href="javascript' not in html
    assert "<span style=" in html                      # syntax highlighting


def test_rich_markdown_never_passes_raw_html():
    html = mdrender._md_to_html("<script>alert(1)</script> <img src=x onerror=alert(1)>")
    assert "<script>" not in html and "<img" not in html


def test_every_theme_text_is_readable():
    import themes
    for name, t in themes.THEMES.items():
        for fg, bgs in (("user_fg", ["user_bg"]), ("ai_fg", ["ai_bg", "frame_bg"]),
                        ("sys_fg", ["ai_bg", "frame_bg", "bar_bg"]), ("accent_fg", ["ai_bg", "frame_bg", "bar_bg"])):
            for bg in bgs:
                assert themes.contrast(t[fg], t[bg]) >= 4.5, (name, fg, bg, themes.contrast(t[fg], t[bg]))


def test_custom_accent_gets_readable_text_colour():
    import themes
    t = themes.THEMES["nova"]
    c = themes.readable_on("#222222", themes.surfaces(t))
    assert all(themes.contrast(c, b) >= 4.5 for b in themes.surfaces(t))
