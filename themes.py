# themes.py — colour themes, with contrast guaranteed for readable text.
import copy

# The look: a quiet Mac app. Warm neutral surfaces, hairline borders, one ink-like accent per theme.
# (The keys "nova", "matrix", "ember", "soft" are kept from earlier versions so saved settings keep working;
# what you see is the label.)
#   frame_bg  the window            bar_bg / bar_br   the title bar and its hairline
#   ai_bg / ai_br   cards and fields (input box, action rows, menus) and their hairline
#   ai_fg     text                  sys_fg   secondary text (labels, times, icons)
#   user_bg / user_fg   your own messages      accent / send_bg / send_hv   the one colour that stands out
#   ok / bad  the tick and the cross on things NOVA did
THEMES = {
    "soft": {
        "label":"Paper","accent":"#1F4FD8","dark":False,
        "frame_bg":"#FBFAF8","frame_br":"#D6D2CA",
        "bar_bg":"#F4F2EE","bar_br":"#E2DFD9",
        "user_bg":"#ECE9E3","user_fg":"#1D1D1F",
        "ai_bg":"#FFFFFF","ai_fg":"#1D1D1F","ai_br":"#DDD9D1",
        "sys_fg":"#86837B","send_bg":"#1F4FD8","send_hv":"#1A43B8","icon_fg":"#1F4FD8",
        "avatar_bg":"#ECE9E3","avatar_fg":"#3C3B38","ok":"#2E7D4F","bad":"#C0392B",
    },
    "nova": {
        "label":"Graphite","accent":"#6C97FF","dark":True,
        "frame_bg":"#1E1E20","frame_br":"#3A3A3D",
        "bar_bg":"#252528","bar_br":"#343437",
        "user_bg":"#35353A","user_fg":"#F2F2F4",
        "ai_bg":"#2A2A2E","ai_fg":"#E8E8EA","ai_br":"#3E3E43",
        "sys_fg":"#9A9AA0","send_bg":"#3D6BF0","send_hv":"#5580FF","icon_fg":"#6C97FF",
        "avatar_bg":"#35353A","avatar_fg":"#D0D0D4","ok":"#5BBF85","bad":"#E0685C",
    },
    "matrix": {
        "label":"Sage","accent":"#2F6F4F","dark":False,
        "frame_bg":"#F7F8F4","frame_br":"#CFD5C8",
        "bar_bg":"#EEF1EA","bar_br":"#DCE1D5",
        "user_bg":"#E3E9DC","user_fg":"#1C211C",
        "ai_bg":"#FFFFFF","ai_fg":"#1C211C","ai_br":"#D5DACE",
        "sys_fg":"#7C8478","send_bg":"#2F6F4F","send_hv":"#275E43","icon_fg":"#2F6F4F",
        "avatar_bg":"#E3E9DC","avatar_fg":"#2E3A2E","ok":"#2F6F4F","bad":"#B8442F",
    },
    "ember": {
        "label":"Espresso","accent":"#E08A4A","dark":True,
        "frame_bg":"#201C19","frame_br":"#40382F",
        "bar_bg":"#27221E","bar_br":"#3A322B",
        "user_bg":"#3A3029","user_fg":"#F5EEE8",
        "ai_bg":"#2C2622","ai_fg":"#EDE6DF","ai_br":"#453B32",
        "sys_fg":"#A3978B","send_bg":"#C96F2E","send_hv":"#DD8344","icon_fg":"#E08A4A",
        "avatar_bg":"#3A3029","avatar_fg":"#E5D8CC","ok":"#8CC68C","bad":"#E8796A",
    },
}
THEME_ORDER = ["soft","nova","matrix","ember"]
THEMES_BASE = copy.deepcopy(THEMES)      # pristine copy - custom accents never mutate THEMES


# ── Contrast (WCAG): every text colour must reach 4.5:1 on the surfaces it is drawn on ───────────
def _lum(h: str) -> float:
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(c: str, to: str, amt: float) -> str:
    c, to = c.lstrip("#"), to.lstrip("#")
    ch = [round(int(c[i:i + 2], 16) + (int(to[i:i + 2], 16) - int(c[i:i + 2], 16)) * amt) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(ch)


def readable_on(color: str, backgrounds, target: float = 4.6) -> str:
    """Nudge `color` towards white (dark UI) or black (light UI) until it reads on every background."""
    dark_ui = sum(_lum(b) for b in backgrounds) / len(backgrounds) < 0.4
    end = "#ffffff" if dark_ui else "#000000"
    for step in range(0, 21):
        cand = _mix(color, end, step / 20)
        if all(contrast(cand, b) >= target for b in backgrounds):
            return cand
    return end


def surfaces(t: dict):
    return [t["frame_bg"], t["ai_bg"], t["bar_bg"]]


def ensure_contrast(t: dict) -> dict:
    """Return `t` with a readable secondary text colour (`sys_fg`) and accent text colour (`accent_fg`)."""
    t["sys_fg"] = readable_on(t["sys_fg"], surfaces(t))
    t["accent_fg"] = readable_on(t["accent"], surfaces(t))
    return t


for _t in THEMES.values():
    ensure_contrast(_t)
THEMES_BASE = copy.deepcopy(THEMES)
