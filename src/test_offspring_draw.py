"""Headless checks for the offspring stage drawing (esp. the redrawn pupa).

    python test_offspring_draw.py

Renders every stage onto an offscreen QImage and asserts that
  * all five stages paint something
  * the pupa (成长期) is elongated, not a blob
  * the pupa grows with stage progress
  * the pupa tans (darkens) as eclosion approaches
Real PyQt5, QT_QPA_PLATFORM=offscreen.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PyQt5.QtWidgets import QApplication          # noqa: E402
from PyQt5.QtGui import QImage, QPainter          # noqa: E402
from PyQt5.QtCore import Qt                       # noqa: E402

import room_overlay as R                          # noqa: E402

app = QApplication(sys.argv)
O = R.Offspring
CW, CH = 220, 160


def render(stage, prog):
    img = QImage(CW, CH, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    off = O()
    off.idx = O.ORDER.index(stage)
    off.stage = stage
    off.anim_t = 1.6                     # fixed mid-breath pose
    if stage == O.STAGE_ADULT:
        off.done = True
    else:
        off.t = prog * O.DURATIONS[stage]
    off.draw_in_nest(p, CW / 2, CH / 2)
    p.end()
    return img


def stats(img, step=2):
    """(painted pixel count, mean luminance, bbox) of the painted pixels.

    Samples every `step` pixels; uses pixelColor() because QColor(pixel())
    mis-reads the QRgb int on this PyQt5 build.
    """
    n = tot = 0
    x0, y0, x1, y1 = CW, CH, -1, -1
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            c = img.pixelColor(x, y)
            if c.alpha() > 24:
                n += 1
                tot += (c.red() + c.green() + c.blue()) / 3.0
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    lum = tot / n if n else 0.0
    return n, lum, (x1 - x0 + 1, y1 - y0 + 1)


ok = True


def check(label, cond):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    ok = ok and bool(cond)


print("== offspring stage drawing ==")

# 1) every stage paints
for st in O.ORDER:
    try:
        n, lum, bbox = stats(render(st, 0.5))
        drew = n > 50
    except Exception as exc:                       # noqa: BLE001
        print("   exception:", exc)
        drew = False
    check(f"{O.NAMES[st]} paints ({st})", drew)

# 2) pupa is elongated, not a blob
n, lum, (bw, bh) = stats(render(O.STAGE_GROWTH, 0.5))
check(f"成长期 elongated bbox {bw}x{bh}", bw / max(bh, 1) > 2.0)

# 3) pupa grows with progress
n_early = stats(render(O.STAGE_GROWTH, 0.05))[0]
n_late = stats(render(O.STAGE_GROWTH, 0.95))[0]
check(f"成长期 grows {n_early} -> {n_late} px", n_late > n_early * 1.15)

# 4) pupa tans toward the adult colour
l_early = stats(render(O.STAGE_GROWTH, 0.05))[1]
l_late = stats(render(O.STAGE_GROWTH, 0.95))[1]
check(f"成长期 tans {l_early:.0f} -> {l_late:.0f} lum", l_late < l_early)

# 5) pupa is drawn cream (not accidentally dark or invisible)
check(f"成长期 cream body (lum {lum:.0f})", lum > 150)

print()
print("ALL OFFSPRING-DRAW CHECKS PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
