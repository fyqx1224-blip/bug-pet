"""Register real Windows fonts for the offscreen QA previews.

    import _qa_fonts
    _qa_fonts.load()          # after QApplication exists, before drawing text

QT_QPA_PLATFORM=offscreen reports ZERO font families on this machine
(`QFontDatabase().families()` == []), so every label in render_preview.py /
preview_offspring.py / preview_adult.py was silently drawn as nothing and the
sheets looked like they had no captions at all.  Adding the font files
explicitly gives the painter something to rasterize.
"""
import os

from PyQt5.QtGui import QFontDatabase

_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",      # Microsoft YaHei -- the UI face
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)

_loaded = False


def load():
    """Idempotent.  Returns the family list actually available afterwards."""
    global _loaded
    if not _loaded:
        for path in _CANDIDATES:
            if os.path.exists(path):
                QFontDatabase.addApplicationFont(path)
        _loaded = True
    return QFontDatabase().families()
