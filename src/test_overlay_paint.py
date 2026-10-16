"""Whole-overlay paint smoke test.

    python test_overlay_paint.py

Catches the class of bug where a layout change silently draws outside its
own box, or where the paint path throws only for a particular offspring
stage.  Renders the real overlay offscreen with an ADULT offspring and a
toast, then checks the help panel still contains all of its text.
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["BUG_SAVE"] = os.path.join(tempfile.mkdtemp(prefix="paint_"), "save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _testenv  # noqa: E402,F401  (never touch the player's live save)

from PyQt5.QtWidgets import QApplication           # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QColor   # noqa: E402
from PyQt5.QtCore import Qt                        # noqa: E402

import room_overlay as R                           # noqa: E402
import _qa_fonts                                   # noqa: E402

app = QApplication(sys.argv)
_qa_fonts.load()

ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          ("  " + extra) if extra else ""))


print("== overlay paint ==")

W, H = 1920, 1080
BG = QColor(120, 130, 120)

for stage in R.Offspring.ORDER:
    w = R.RoomOverlay()
    w.offspring = R.Offspring()
    w.offspring.stage = stage
    w.offspring.idx = R.Offspring.ORDER.index(stage)
    w.offspring.done = stage == R.Offspring.STAGE_ADULT
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    try:
        w.render(p)
        w.info._draw_help(p)          # the resized help panel
        w._draw_toast(p)              # the reused status line
        drew = True
        err = ""
    except Exception as exc:          # noqa: BLE001
        drew = False
        err = repr(exc)
    p.end()
    painted = sum(1 for y in range(0, H, 8) for x in range(0, W, 8)
                  if img.pixelColor(x, y) != BG)
    check("whole overlay paints with 后代=%s" % R.Offspring.NAMES[stage],
          drew and painted > 3000, err or "%d sample px" % painted)

# the help panel must actually contain its own text
w = R.RoomOverlay()
lines = w.info._help_lines()
panel = w.info._help_panel_rect()
last_baseline = panel.y() + w.info.HELP_PAD_TOP + (len(lines) - 1) * w.info.HELP_LINE_H
check("help panel is sized from its content",
      last_baseline + 10 <= panel.bottom(),
      "last baseline %.0f <= bottom %.0f" % (last_baseline, panel.bottom()))

print()
print("ALL OVERLAY-PAINT CHECKS PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
