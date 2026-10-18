# icons.py — NOVA's own line icons: thin strokes on a 16-point grid, drawn in whatever colour the theme asks for.
#
# Every icon is a few SVG paths (below). They are rendered once per colour and size and cached, so they stay
# sharp on Retina screens and follow light / dark themes - unlike emoji, which look different on every system.
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QGuiApplication

# name -> the inside of a 16×16 <svg> (stroked, never filled, unless the element says otherwise)
PATHS = {
    "menu":      '<path d="M3 4.500h10M3 8h10M3 11.500h10"/>',
    "plus":      '<path d="M8 3v10M3 8h10"/>',
    "mic":       '<rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.500 8a4.500 4.500 0 0 0 9 0M8 12.500V14"/>',
    "stop":      '<rect x="4.500" y="4.500" width="7" height="7" rx="1.200" fill="currentColor" stroke="none"/>',
    "send":      '<path d="M8 13V3M4 7l4-4 4 4"/>',
    "down":      '<path d="M8 3v10M4 9l4 4 4-4"/>',
    "copy":      '<rect x="5.500" y="5.500" width="7.500" height="7.500" rx="1.500"/><path d="M3 10.500V4a1 1 0 0 1 1-1h6.500"/>',
    "speaker":   '<path d="M3 6.200v3.600h2.300L8.500 12.500v-9L5.300 6.200H3zM11 6a3 3 0 0 1 0 4"/>',
    "refresh":   '<path d="M13 8a5 5 0 1 1-1.600-3.700M13 3v2.800h-2.800"/>',
    "code":      '<path d="M6 4.500 2.500 8 6 11.500M10 4.500 13.500 8 10 11.500"/>',
    "check":     '<path d="M3.500 8.500l3 3 6-7"/>',
    "cross":     '<path d="M4 4l8 8M12 4l-8 8"/>',
    "chevron":   '<path d="M6 4l4 4-4 4"/>',
    "caret":     '<path d="M4.500 6.500 8 10l3.500-3.500"/>',
    "caret-up":  '<path d="M4.500 9.500 8 6l3.500 3.500"/>',
    "pin":       '<path d="M8 14s4.500-4 4.500-7.500a4.500 4.500 0 0 0-9 0C3.500 10 8 14 8 14z"/><circle cx="8" cy="6.500" r="1.500"/>',
    "bell":      '<path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.500H3L4 11zM6.500 14h3"/>',
    "clock":     '<circle cx="8" cy="8" r="5.500"/><path d="M8 5v3l2 1.500"/>',
    "calendar":  '<rect x="2.500" y="3.500" width="11" height="10" rx="1.500"/><path d="M2.500 6.500h11M5.500 2v3M10.500 2v3"/>',
    "mail":      '<rect x="2.500" y="3.500" width="11" height="9" rx="1.500"/><path d="M3 4.500l5 4 5-4"/>',
    "globe":     '<circle cx="8" cy="8" r="5.500"/><path d="M2.500 8h11M8 2.500c2 2 2 9 0 11M8 2.500c-2 2-2 9 0 11"/>',
    "search":    '<circle cx="7" cy="7" r="4"/><path d="M10 10l3.500 3.500"/>',
    "file":      '<path d="M4 2.500h5l3 3v8H4v-11zM9 2.500v3h3"/>',
    "folder":    '<path d="M2.500 4.500h4l1.500 1.500h5.500v7h-11v-8.500z"/>',
    "book":      '<path d="M3 3h4a1.500 1.500 0 0 1 1.500 1.500V13A1.500 1.500 0 0 0 7 11.500H3V3zM13 3H9.500A1.500 1.500 0 0 0 8 4.500"/><path d="M13 3v8.500H9.500A1.500 1.500 0 0 0 8 13"/>',
    "terminal":  '<rect x="2.500" y="3" width="11" height="10" rx="1.500"/><path d="M5 6.500 7 8.500 5 10.500M8.500 10.500h2.500"/>',
    "trash":     '<path d="M3 4.500h10M6.500 4.500V3h3v1.500M4.500 4.500l.500 8.500h6l.500-8.500"/>',
    "edit":      '<path d="M3 13l.600-2.800L10.800 3l2.200 2.200L5.800 12.400 3 13z"/>',
    "note":      '<path d="M3.500 2.500h9v8l-3 3h-6v-11zM12.500 10.500h-3v3M5.500 5.500h5M5.500 8h3"/>',
    "bookmark":  '<path d="M4.500 2.500h7v11L8 11l-3.500 2.500v-11z"/>',
    "app":       '<rect x="2.500" y="2.500" width="4.500" height="4.500" rx="1"/><rect x="9" y="2.500" width="4.500" height="4.500" rx="1"/><rect x="2.500" y="9" width="4.500" height="4.500" rx="1"/><rect x="9" y="9" width="4.500" height="4.500" rx="1"/>',
    "volume":    '<path d="M3 6.200v3.600h2.300L8.500 12.500v-9L5.300 6.200H3zM10.800 5.500a3.500 3.500 0 0 1 0 5M12.500 4a5.800 5.800 0 0 1 0 8"/>',
    "power":     '<path d="M8 2.500v5M4.800 4.500a5 5 0 1 0 6.400 0"/>',
    "battery":   '<rect x="2" y="5" width="10.500" height="6" rx="1.500"/><path d="M14 7v2"/><rect x="3.500" y="6.500" width="5" height="3" rx=".500" fill="currentColor" stroke="none"/>',
    "chip":      '<rect x="4.500" y="4.500" width="7" height="7" rx="1"/><path d="M6.500 2.500v2M9.500 2.500v2M6.500 11.500v2M9.500 11.500v2M2.500 6.500h2M2.500 9.500h2M11.500 6.500h2M11.500 9.500h2"/>',
    "wifi":      '<path d="M2.500 6.500a8 8 0 0 1 11 0M4.500 8.800a5 5 0 0 1 7 0M6.500 11a2.200 2.200 0 0 1 3 0"/>',
    "cloud":     '<path d="M5 12.500a3 3 0 0 1-.400-6 4 4 0 0 1 7.700 1A2.600 2.600 0 0 1 11.500 12.500H5z"/>',
    "clipboard": '<rect x="3.500" y="3.500" width="9" height="10" rx="1.500"/><rect x="6" y="2" width="4" height="3" rx="1"/>',
    "image":     '<rect x="2.500" y="3" width="11" height="10" rx="1.500"/><circle cx="6" cy="6.500" r="1.200"/><path d="M3 11.500l3.500-3 2.500 2 2-1.500 2 2"/>',
    "keyboard":  '<rect x="1.500" y="4" width="13" height="8" rx="1.500"/><path d="M4 6.500h.010M6.700 6.500h.010M9.400 6.500h.010M12 6.500h.010M5 9.500h6"/>',
    "music":     '<path d="M6 12V4l6.500-1.500v8"/><circle cx="4.500" cy="12" r="1.500"/><circle cx="11" cy="10.500" r="1.500"/>',
    "plug":      '<path d="M6 2v3M10 2v3M4.500 5h7v2.500a3.500 3.500 0 0 1-7 0V5zM8 11v3"/>',
    "layers":    '<path d="M8 2.500 13.500 5.500 8 8.500 2.500 5.500 8 2.500zM2.500 8.500 8 11.500l5.500-3M2.500 11 8 14l5.500-3"/>',
    "sliders":   '<path d="M3 5h4M10 5h3M3 11h2M8 11h5"/><circle cx="8.500" cy="5" r="1.500"/><circle cx="6.500" cy="11" r="1.500"/>',
    "lines":     '<path d="M3 4.500h10M3 8h7M3 11.500h4"/>',
    "headphones": '<path d="M3 10V8a5 5 0 0 1 10 0v2"/><rect x="2.500" y="9.500" width="2.500" height="4" rx="1"/><rect x="11" y="9.500" width="2.500" height="4" rx="1"/>',
    "game":      '<rect x="2" y="5" width="12" height="7" rx="3"/><path d="M5 7.500v2M4 8.500h2M10.500 8h.010M12 9.500h.010"/>',
    "news":      '<rect x="2.500" y="3" width="11" height="10" rx="1.500"/><path d="M5 6h6M5 8.500h6M5 11h3"/>',
    "crop":      '<path d="M4.500 2v9.500H14M2 4.500h9.500V14"/>',
    "export":    '<path d="M8 10V2.500M5 5.500l3-3 3 3M3 10v3h10v-3"/>',
    "history":   '<path d="M3 8a5 5 0 1 0 1.600-3.700M3 3v2.800h2.800M8 5.500V8l1.800 1.200"/>',
    "key":       '<circle cx="5.500" cy="10.500" r="2.500"/><path d="M7.300 8.700 13 3M11 5l1.500 1.500M9.500 6.500 11 8"/>',
    "palette":   '<path d="M8 2.500a5.500 5.500 0 1 0 0 11c1 0 1.500-.700 1-1.500s0-1.500 1-1.500h1.500A2 2 0 0 0 13.500 8.500 5.500 5.500 0 0 0 8 2.500z"/><path d="M5.500 8h.010M6.500 5.500h.010M9.500 5.500h.010"/>',
    "bolt":      '<path d="M9 2 4 9h3.500L7 14l5-7H8.500L9 2z"/>',
    "question":  '<circle cx="8" cy="8" r="5.500"/><path d="M6.300 6.500a1.800 1.800 0 1 1 2.500 1.600c-.500.300-.800.700-.800 1.200M8 11.300h.010"/>',
    "info":      '<circle cx="8" cy="8" r="5.500"/><path d="M8 7.300v3.500M8 5.200h.010"/>',
    "warning":   '<path d="M8 2.500 14 13H2L8 2.500zM8 6.500v3M8 11.300h.010"/>',
    "window":    '<rect x="2.500" y="3" width="11" height="10" rx="1.500"/><path d="M2.500 6h11"/>',
    "stats":     '<path d="M3 13V8M6.300 13V4M9.700 13V9.500M13 13V6"/>',
    "wallpaper": '<rect x="2.500" y="3" width="11" height="8" rx="1.500"/><path d="M6 13.500h4M8 11v2.500"/>',
    "eye":       '<path d="M1.800 8S4 3.800 8 3.800 14.200 8 14.200 8 12 12.200 8 12.200 1.800 8 1.800 8z"/><circle cx="8" cy="8" r="1.800"/>',
}

_cache = {}


def svg(name: str, color: str, stroke: float = 1.5) -> bytes:
    body = PATHS.get(name) or PATHS["info"]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="{color}" color="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def file(name: str, color: str, size: int = 16, stroke: float = 1.5) -> str:
    """The icon as a PNG file (style sheets take a file, not a picture): `<name>.png` plus a sharp `@2x` twin that Qt
    picks on Retina screens. Made once, in a private temporary folder. Returns the path of the 1x file."""
    import os, tempfile
    from PySide6.QtGui import QImage
    from PySide6.QtSvg import QSvgRenderer
    folder = os.path.join(tempfile.gettempdir(), f"nova-icons-{os.getuid()}")
    base = os.path.join(folder, f"{name}-{color.lstrip('#')}-{size}-{stroke:g}")
    if not (os.path.exists(base + ".png") and os.path.exists(base + "@2x.png")):
        os.makedirs(folder, mode=0o700, exist_ok=True)
        for scale, suffix in ((1, ""), (2, "@2x")):
            img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32); img.fill(Qt.GlobalColor.transparent)
            painter = QPainter(img); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            QSvgRenderer(QByteArray(svg(name, color, stroke))).render(painter, QRectF(0, 0, size * scale, size * scale))
            painter.end(); img.save(base + suffix + ".png", "PNG")
    return base + ".png"


def pixmap(name: str, color: str, size: int = 16, stroke: float = 1.5) -> QPixmap:
    """The icon as a picture `size` points wide, sharp on Retina screens."""
    from PySide6.QtSvg import QSvgRenderer
    screen = QGuiApplication.primaryScreen()
    ratio = max(2.0, float(screen.devicePixelRatio()) if screen else 2.0)
    key = (name, color, size, stroke, ratio)
    pm = _cache.get(key)
    if pm is None:
        pm = QPixmap(int(size * ratio), int(size * ratio)); pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg(name, color, stroke))).render(painter, QRectF(0, 0, size * ratio, size * ratio))
        painter.end()
        pm.setDevicePixelRatio(ratio)
        _cache[key] = pm
    return pm


def icon(name: str, color: str, size: int = 16, stroke: float = 1.5) -> QIcon:
    return QIcon(pixmap(name, color, size, stroke))
