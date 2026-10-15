"""Minimal PyQt5 shim so the real room_overlay logic can be unit-tested
headlessly (no display, no real Qt).  Only the pieces room_overlay touches
at import / construct / _tick time are implemented; nothing renders."""
import sys, types
import math
from pathlib import Path


class Qt:
    FramelessWindowHint = 1
    WindowStaysOnTopHint = 2
    Tool = 4
    NoDropShadowWindowHint = 8
    WA_TranslucentBackground = 100
    WA_NoSystemBackground = 101
    AlignCenter = 0x84
    NoPen = 0
    OddEvenFill = 0
    DashLine = 2
    LeftButton = 1
    RightButton = 2
    CustomContextMenu = 9
    AA_EnableHighDpiScaling = 100
    AA_UseHighDpiPixmaps = 101
    KeepAspectRatio = 2
    SmoothTransformation = 1
    Antialiasing = 0
    SmoothPixmapTransform = 0
    Bold = 75
    Normal = 50


class QPoint:
    def __init__(self, x=0, y=0):
        self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y
    def __sub__(self, o): return QPoint(self._x - o._x, self._y - o._y)


class QPointF:
    def __init__(self, x=0.0, y=0.0):
        # real PyQt accepts QPoint/QPointF as a single arg
        if isinstance(x, (QPoint, QPointF)):
            x, y = x._x, x._y
        self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y
    def __repr__(self): return f"QPointF({self._x},{self._y})"


class QRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self._x, self._y, self._w, self._h = x, y, w, h
    def x(self): return self._x
    def y(self): return self._y
    def width(self): return self._w
    def height(self): return self._h
    def center(self): return QPointF(self._x + self._w / 2, self._y + self._h / 2)
    def contains(self, pt):
        return (self._x <= pt.x() <= self._x + self._w and
                self._y <= pt.y() <= self._y + self._h)
    def adjusted(self, l, t, r, b):
        return QRect(self._x + l, self._y + t, self._w - l + r, self._h - t + b)


class QRectF(QRect):
    pass


class QColor:
    def __init__(self, *a, **k): pass


class QPixmap:
    def __init__(self, path=None):
        self.path = path
    def isNull(self): return False
    def scaled(self, *a, **k): return self


class QPen:
    def __init__(self, *a, **k): pass


class QFont:
    def __init__(self, *a, **k): pass
    def setPointSizeF(self, s): pass
    def setBold(self, b): pass


class QPolygonF:
    def __init__(self, pts=None): self.pts = pts or []


class QPainterPath:
    def addRoundedRect(self, *a, **k): pass
    def addEllipse(self, *a, **k): pass
    def setFillRule(self, *a, **k): pass


class QRadialGradient:
    def __init__(self, *a, **k): pass
    def setColorAt(self, *a, **k): pass


class QLinearGradient(QRadialGradient):
    pass


class QPainter:
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def save(self, *a): pass
    def restore(self, *a): pass
    def setOpacity(self, *a): pass
    def translate(self, *a): pass
    def rotate(self, *a): pass
    def scale(self, *a): pass
    def setBrush(self, *a): pass
    def setPen(self, *a): pass
    def setFont(self, *a): pass
    def setRenderHint(self, *a): pass
    def fillRect(self, *a): pass
    def fillPath(self, *a): pass
    def drawPath(self, *a): pass
    def drawPixmap(self, *a): pass
    def drawEllipse(self, *a): pass
    def drawPolygon(self, *a): pass
    def drawRoundedRect(self, *a): pass
    def drawText(self, *a, **k): pass
    def drawArc(self, *a): pass
    def drawLine(self, *a): pass


class QCursor:
    @staticmethod
    def pos(): return QPoint(0, 0)


class _Screen:
    def geometry(self): return QRect(0, 0, 1920, 1080)


class QGuiApplication:
    @staticmethod
    def primaryScreen(): return _Screen()
    @staticmethod
    def setAttribute(*a, **k): pass


class QTimer:
    def __init__(self, *a, **k):
        self.timeout = types.SimpleNamespace(connect=lambda f: None)
    def start(self, *a, **k): pass


class QWidget:
    def __init__(self, *a, **k): pass
    def setWindowFlags(self, *a): pass
    def setAttribute(self, *a): pass
    def setFixedSize(self, *a): pass
    def move(self, *a): pass
    def setWindowOpacity(self, *a): pass
    def setMouseTracking(self, *a): pass
    def setContextMenuPolicy(self, *a): pass
    def grabMouse(self, *a): pass
    def releaseMouse(self, *a): pass
    def show(self, *a): pass
    def update(self, *a): pass
    def mapFromGlobal(self, pt): return pt
    # Qt signals used in room_overlay (made connect-able, no-op emit)
    customContextMenuRequested = types.SimpleNamespace(connect=lambda f: None)


class QInputDialog:
    @staticmethod
    def getText(parent, title, label, text=""):
        return (text, True)

class QApplication(QGuiApplication):
    def __init__(self, argv=None):
        self.argv = argv
    @staticmethod
    def setQuitOnLastWindowClosed(*a): pass
    @staticmethod
    def quit(): pass
    def exec_(self): pass


def _make_module(name, attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    m.__all__ = list(attrs.keys())
    return m


qtcore = _make_module("PyQt5.QtCore", {
    "Qt": Qt, "QTimer": QTimer, "QPoint": QPoint, "QPointF": QPointF,
    "QRect": QRect, "QRectF": QRectF,
})
qtgui = _make_module("PyQt5.QtGui", {
    "QPainter": QPainter, "QPixmap": QPixmap, "QCursor": QCursor,
    "QColor": QColor, "QPainterPath": QPainterPath,
    "QRadialGradient": QRadialGradient, "QLinearGradient": QLinearGradient,
    "QFont": QFont, "QGuiApplication": QGuiApplication, "QPen": QPen,
    "QImage": object, "QPolygonF": QPolygonF,
})
qtwid = _make_module("PyQt5.QtWidgets", {
    "QApplication": QApplication, "QWidget": QWidget, "QInputDialog": QInputDialog,
})

pkg = types.ModuleType("PyQt5")
pkg.__path__ = []
sys.modules["PyQt5"] = pkg
sys.modules["PyQt5.QtCore"] = qtcore
sys.modules["PyQt5.QtGui"] = qtgui
sys.modules["PyQt5.QtWidgets"] = qtwid
