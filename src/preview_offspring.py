"""Offscreen QA sheet for the offspring stages (esp. the redrawn pupa).

    python preview_offspring.py [out.png]

Renders every stage twice: at real on-screen size and zoomed, over a
backdrop sampled from the room wallpaper's nest area (so contrast is
judged honestly).  Headless, real PyQt5.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPainter, QPixmap, QImage, QColor, QFont
from PyQt5.QtCore import Qt

import room_overlay as R

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "preview_pupa.png")

app = QApplication(sys.argv)

# backdrop: sample the wallpaper right where the nest sits (0.873, 0.450)
wp_path = os.path.join(ROOT, "wallpaper", "bug_room_wallpaper_1920x1080.png")
wp = QImage(wp_path)
backdrop = QColor(232, 230, 224)
if not wp.isNull():
    backdrop = QColor(wp.pixel(int(wp.width() * 0.873), int(wp.height() * 0.450)))

O = R.Offspring
CASES = [
    ("卵期",       O.STAGE_EGG,    0.40),
    ("孵化后期",   O.STAGE_HATCH,  0.70),
    ("幼年期",     O.STAGE_LARVA,  0.50),
    ("成长期 5%",  O.STAGE_GROWTH, 0.05),
    ("成长期 50%", O.STAGE_GROWTH, 0.50),
    ("成长期 95%", O.STAGE_GROWTH, 0.95),
    ("成年期",     O.STAGE_ADULT,  1.00),
]

W, ROW, ZOOM = 1000, 104, 3.5
H = ROW * len(CASES) + 76
pm = QPixmap(W, H)
pm.fill(backdrop)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)

p.setFont(QFont("Microsoft YaHei", 11))
p.setPen(QColor(90, 84, 70))
p.drawText(24, 34, "隐翅虫后代各阶段（左：屏幕实际大小   右：3.5× 放大）")
p.setPen(QColor(150, 144, 128))
p.drawText(24, 56, "背景色取自壁纸睡窝区域")

for i, (label, stage, prog) in enumerate(CASES):
    cy = 76 + i * ROW + ROW * 0.5
    p.setPen(QColor(120, 112, 96))
    p.setFont(QFont("Microsoft YaHei", 10))
    p.drawText(24, int(cy) + 5, label)

    off = O()
    off.idx = O.ORDER.index(stage)
    off.stage = stage
    off.anim_t = 1.6                     # mid-breath pose
    if stage == O.STAGE_ADULT:
        off.done = True
    else:
        off.t = prog * O.DURATIONS[stage]

    off.draw_in_nest(p, 215, cy)         # real size
    p.save()                             # zoomed
    p.translate(650, cy)
    p.scale(ZOOM, ZOOM)
    off.draw_in_nest(p, 0, 0)
    p.restore()

    if i:
        p.setPen(QColor(0, 0, 0, 18))
        p.drawLine(16, int(cy - ROW * 0.5), W - 16, int(cy - ROW * 0.5))

p.end()
pm.save(out)
print("saved:", out, f"{pm.width()}x{pm.height()}", "backdrop:", backdrop.name())
