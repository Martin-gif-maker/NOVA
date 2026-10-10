# mdrender.py — markdown → Qt rich text, the safe calculator and reasoning-tag stripping.
import re, ast, operator, logging

log = logging.getLogger("nova")

def _strip_think(text: str) -> str:
    """Remove <think>…</think> reasoning blocks (Qwen) - also an unfinished one while streaming."""
    text = re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL)   # normal case: reasoning first
    text = re.sub(r" ?<think>.*?</think>", "", text, flags=re.DOTALL)
    return re.sub(r"<think>.*$", "", text, flags=re.DOTALL)


try:
    from markdown_it import MarkdownIt
    from pygments import highlight as _pyg_highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.util import ClassNotFound
    _MD_OK = True
except ImportError:                      # fall back to the small built-in renderer
    _MD_OK = False


def _is_light(theme: dict) -> bool:
    t = theme or {}
    if "dark" in t: return not t["dark"]
    h = str(t.get("frame_bg", "#000000")).lstrip("#")
    try: r, g, b = (int(h[k:k + 2], 16) for k in (0, 2, 4))
    except ValueError: return False
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150


def _md_palette(theme: dict) -> dict:
    """Colours for code, tables, links and rules - taken from the theme, so replies match the window."""
    t = theme or {}
    light = _is_light(t)
    soft = t.get("user_bg", "#ECE9E3" if light else "#35353A")           # the quiet surface code sits on
    text = t.get("ai_fg", "#1D1D1F" if light else "#E8E8EA")
    line = t.get("ai_br", "#DDD9D1" if light else "#3E3E43")
    return dict(light=light, pre_bg=soft, pre_fg=text, pre_br=line, code_bg=soft, code_fg=text,
                link=t.get("accent_fg", t.get("accent", "#1F4FD8")), rule=line,
                style="xcode" if light else "github-dark")


def _md_to_html_rich(text: str, theme: dict) -> str:
    c = _md_palette(theme)
    try: fmt = HtmlFormatter(noclasses=True, nowrap=True, style=c["style"])
    except ClassNotFound: fmt = HtmlFormatter(noclasses=True, nowrap=True, style="default" if c["light"] else "monokai")
    mono = "font-family:Menlo,Consolas,monospace;font-size:12px"

    def _highlight(code, lang, _attrs):
        lexer = None
        try:
            lexer = get_lexer_by_name(lang) if lang else (guess_lexer(code) if len(code) > 40 else None)
        except ClassNotFound:
            lexer = None
        body = _pyg_highlight(code, lexer, fmt).rstrip("\n") if lexer else (
            code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").rstrip("\n"))
        return (f'<pre style="background:{c["pre_bg"]};color:{c["pre_fg"]};padding:8px 12px;{mono};'
                f'white-space:pre-wrap;margin:6px 0">{body}</pre>')

    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "highlight": _highlight}).enable(["table", "linkify"])
    html = md.render(_strip_think(text))
    html = re.sub(r"<table>", f'<table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;border-color:{c["pre_br"]};margin:6px 0">', html)
    html = re.sub(r"<code>", f'<code style="background:{c["code_bg"]};color:{c["code_fg"]};{mono}">', html)
    html = re.sub(r'<a href="([^"]*)"', lambda m: f'<a style="color:{c["link"]}" href="{m.group(1)}"'
                  if re.match(r"(https?:|mailto:)", m.group(1)) else '<a', html)
    html = html.replace("<hr />", f'<hr style="border:none;border-top:1px solid {c["rule"]}">')
    return html.strip()


def _md_to_html_basic(text: str, theme: dict = None) -> str:
    t = theme or {}
    c = _md_palette(t)
    pre_bg, pre_fg, pre_br, code_bg, code_fg = c["pre_bg"], c["pre_fg"], c["pre_br"], c["code_bg"], c["code_fg"]
    hr_col = c["rule"]
    text = _strip_think(text)
    text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    # Code is stashed first so the markdown rules below can never touch it.
    stash = []
    def _keep(html):
        stash.append(html); return f"\x00{len(stash)-1}\x00"
    text = re.sub(r'```[\w+-]*[ \t]*\n?(.*?)```',
        lambda m: _keep(f'<pre style="background:{pre_bg};color:{pre_fg};padding:8px 12px;'
                        f'border-radius:6px;font-family:Menlo,Consolas,monospace;font-size:9px;'
                        f'white-space:pre-wrap;border:1px solid {pre_br};margin:6px 0">'
                        + m.group(1).strip("\n") + '</pre>'), text, flags=re.DOTALL)
    text = re.sub(r'`([^`\n]+)`',
        lambda m: _keep(f'<code style="background:{code_bg};color:{code_fg};padding:1px 5px;'
                        f'border-radius:3px;font-family:Menlo,Consolas,monospace;font-size:9px">'
                        + m.group(1) + '</code>'), text)

    text = re.sub(r'^[ \t]*[-*•] (.+)$', r'&nbsp;&nbsp;• \1', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<b>\1</b>', text)
    text = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', text)
    text = re.sub(r'^### (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$',  r'<b><big>\1</big></b>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$',   r'<b><big><big>\1</big></big></b>', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', f'<hr style="border:none;border-top:1px solid {hr_col}">', text, flags=re.MULTILINE)
    text = text.replace('\n', '<br>')
    return re.sub(r'\x00(\d+)\x00', lambda m: stash[int(m.group(1))], text)




def _md_to_html(text: str, theme: dict = None) -> str:
    """Markdown → the HTML subset Qt labels understand (tables, links, lists, highlighted code)."""
    if _MD_OK:
        try:
            return _md_to_html_rich(text, theme)
        except Exception:
            log.exception("markdown render failed; using the basic renderer")
    return _md_to_html_basic(text, theme)


# ──────────────────────────────────────────────────────────────────
#  Safe calculator  ( "= 2+2", "= 15% of 200", "= 2^10" )
# ──────────────────────────────────────────────────────────────────
_CALC_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
             ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}

def _calc_eval(node):
    if isinstance(node, ast.Expression): return _calc_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        a, b = _calc_eval(node.left), _calc_eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(b) > 200 or abs(a) > 1e9):
            raise ValueError("Exponent too large")
        r = _CALC_OPS[type(node.op)](a, b)
        if isinstance(r, (int, float)) and abs(r) > 1e300: raise ValueError("Result too large")
        return r
    raise ValueError("Unsupported expression")

def safe_calculate(expr: str):
    """Evaluate arithmetic safely. Raises ValueError / ZeroDivisionError on bad input."""
    e = expr.strip().replace(",", ".").replace("^", "**").replace("×", "*").replace("÷", "/")
    e = re.sub(r'(?<=[\d\)])\s*[xX]\s*(?=[\d\(])', '*', e)
    e = re.sub(r'(\d+(?:\.\d+)?)\s*%\s*of\s*(\S+)', r'(\1/100)*\2', e, flags=re.IGNORECASE)
    e = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', e)
    if len(e) > 200 or not re.fullmatch(r'[\d\.\+\-\*/\(\)\s]+', e):
        raise ValueError("Not an arithmetic expression")
    return _calc_eval(ast.parse(e.strip(), mode="eval"))
