"""REAL-Qt (offscreen) test for the right-click bug menu.

The headless shim tests can't build QMenu/QAction, so this runs with real
PyQt5 offscreen and swaps in a fake QtWidgets module JUST for the duration of
_show_bug_menu() -- the menu is captured instead of shown (no event loop
block).  Verifies: the menu builds without errors, the shrink items exist,
firing them really shrinks the bug, the floor case disables the item, and the
restore entry only appears once the bug is shrunk.
"""
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BUG_SAVE"] = str(
    Path(tempfile.mkdtemp(prefix="bugmenu_")) / "save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"

from PyQt5.QtWidgets import QApplication  # noqa: E402
import room_overlay as R                 # noqa: E402


class FakeAction:
    def __init__(self, text, parent=None):
        self._text = text
        self.enabled = True
        self._slot = None
        self.triggered = types.SimpleNamespace(connect=self._connect)

    def _connect(self, f):
        self._slot = f

    def text(self):
        return self._text

    def setText(self, t):
        self._text = t

    def setEnabled(self, v):
        self.enabled = v

    def fire(self):
        assert self._slot is not None, "action has no slot"
        self._slot()


class FakeMenu:
    def __init__(self, *a, **k):
        pass

    def setStyleSheet(self, *a, **k):
        pass

    def addAction(self, a):
        CAPTURED.append(a)

    def addSeparator(self):
        CAPTURED.append("---")

    def exec_(self, *a, **k):
        pass


CAPTURED = []


def open_menu(w, bug):
    """Build the menu with the fake QtWidgets; return the captured items."""
    import PyQt5.QtWidgets as qtw
    CAPTURED.clear()
    fake = types.ModuleType("PyQt5.QtWidgets")
    fake.QMenu = FakeMenu
    fake.QAction = FakeAction
    sys.modules["PyQt5.QtWidgets"] = fake
    try:
        w._show_bug_menu(global_pos=None, bug=bug)
    finally:
        sys.modules["PyQt5.QtWidgets"] = qtw
    return list(CAPTURED)


def labels(items):
    return [a.text() if isinstance(a, FakeAction) else a for a in items]


app = QApplication(sys.argv)
w = R.RoomOverlay()
w.show()
app.processEvents()

# ---- 1) menu builds on the default-size bug; shrink item present ----
items = open_menu(w, w.bug)
texts = labels(items)
print("[1] menu items:", texts)
shrink_items = [a for a in items
                if isinstance(a, FakeAction) and "缩小虫子" in a.text()]
assert len(shrink_items) == 1, "shrink item missing"
assert "100%" in shrink_items[0].text(), texts
assert not any("恢复原本大小" in t for t in texts), \
    "restore entry must not show at default size"

# ---- 2) firing the captured action really shrinks ----
before = w.bug.size_scale
shrink_items[0].fire()
assert w.bug.size_scale < before, "firing 缩小虫子 did not shrink"
print("[2] fired 缩小虫子 ->", f"{before:.2f} -> {w.bug.size_scale:.2f}")

# ---- 3) after shrinking, the restore entry appears and works ----
items = open_menu(w, w.bug)
texts = labels(items)
print("[3] menu items:", texts)
restore = [a for a in items
           if isinstance(a, FakeAction) and "恢复原本大小" in a.text()]
assert len(restore) == 1, "restore entry missing after shrink"
restore[0].fire()
assert w.bug.size_scale == R.BUG_SCALE_DEFAULT, "restore did not reset"
print("    fired 恢复原本大小 ->", w.bug.size_scale)

# ---- 4) at the floor the shrink item is disabled with a notice ----
for _ in range(10):
    w.bug.shrink()
items = open_menu(w, w.bug)
floor_item = [a for a in items
              if isinstance(a, FakeAction)
              and ("最小" in a.text() or "缩小" in a.text())][0]
assert floor_item.text() == "虫子已经最小啦", floor_item.text()
assert floor_item.enabled is False, "floor item should be disabled"
print("[4] floor state ->", repr(floor_item.text()), "disabled =",
      floor_item.enabled is False)

# ---- 5) the menu also builds for the remote peer bug ----
w.remote_bug = R.Bug(R.SPRITES_DIR)
items = open_menu(w, w.remote_bug)
texts = labels(items)
assert any("缩小虫子" in t for t in texts), texts
print("[5] remote-bug menu ok:", texts[:2], "...")
w.remote_bug = None

print("\nALL MENU-WIRING CHECKS PASSED")
