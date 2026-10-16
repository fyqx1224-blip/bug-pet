"""Offscreen QA sheet for the ADULT offspring: the idle motion + new panel.

    python preview_adult.py [out.png]

The adult used to be a dead silhouette (it was the only stage that ignored
anim_t).  This renders one full 6 s idle cycle so the breathing / antenna
twitch / wing flutter can be judged, plus the new status card.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _testenv  # noqa: F401  (never touch the player's live save)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPainter, QPixmap, QColor, QFont, QPen, QImage
from PyQt5.QtCore import Qt, QRectF, QPointF

import room_overlay as R
import _qa_fonts

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "preview_adult.png")

app = QApplication(sys.argv)
print("fonts available:", len(_qa_fonts.load()))

O = R.Offspring
# one 6 s cycle; the flutter burst runs from 0.0 to 1.2 s
PHASES = [0.0, 0.3, 0.6, 0.9, 1.2, 2.0, 3.0, 4.5]
ZOOM = 2.8
CELL, GAP = 292, 10
ROWS = 1
CARD_H = 208
W = 48 + len(PHASES) * (CELL + GAP)
H = 104 + CARD_H + 620

pm = QPixmap(W, H)
pm.fill(QColor(239, 237, 231))
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)

p.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
p.setPen(QColor(58, 54, 48))
p.drawText(24, 40, "成年期后代 · 一个 6 秒待机循环（%.1f× 放大）" % ZOOM)
p.setFont(QFont("Microsoft YaHei", 10))
p.setPen(QColor(130, 124, 112))
p.drawText(24, 64, "0.0–1.2 s 抖翅：身体抬起、鞘翅张开；其余时间缓慢呼吸 + 触角摆动")
p.drawText(24, 84, "以前成年期是唯一不读动画时钟的阶段 —— 画出来是一动不动的剪影")

for i, t in enumerate(PHASES):
    x0 = 24 + i * (CELL + GAP)
    card = QRectF(x0, 104, CELL, CARD_H)
    p.setPen(QPen(QColor(214, 210, 200), 1))
    p.setBrush(QColor(252, 251, 248))
    p.drawRoundedRect(card, 10, 10)

    off = O()
    off.idx = O.ORDER.index(O.STAGE_ADULT)
    off.stage = O.STAGE_ADULT
    off.done = True
    off.anim_t = t
    p.save()
    # the legs hang well below the body, so sit the beetle high in the cell
    p.translate(card.center().x() - 8, card.center().y() - 26)
    p.scale(ZOOM, ZOOM)
    off.draw_in_nest(p, 0, 0)
    p.restore()

    p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
    p.setPen(QColor(96, 90, 80))
    p.drawText(QRectF(x0, card.bottom() + 6, CELL, 20), Qt.AlignCenter, "%.1f s" % t)

# ---- the new status card ----
y = 104 + CARD_H + 40
p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
p.setPen(QColor(58, 54, 48))
p.drawText(24, y, "状态卡（真实大小）")
p.setFont(QFont("Microsoft YaHei", 10))
p.setPen(QColor(130, 124, 112))
p.drawText(24, y + 20, "成年后不再画满格进度条 —— 满格看起来像“还在加载”，现在直接写文字")

panels = [("成年期（新）", O.STAGE_ADULT), ("成长期（对比）", O.STAGE_GROWTH)]
for i, (label, stage) in enumerate(panels):
    ry = y + 44 + i * 66
    off = O()
    off.idx = O.ORDER.index(stage)
    off.stage = stage
    if stage == O.STAGE_ADULT:
        off.done = True
    else:
        off.t = 0.5 * O.DURATIONS[stage]
    p.setFont(QFont("Microsoft YaHei", 10))
    p.setPen(QColor(96, 90, 80))
    p.drawText(24, ry + 22, label)
    # the HUD is drawn over a bright wallpaper -> mimic that here
    p.fillRect(QRectF(150, ry, 640, 44), QColor(226, 222, 212))
    off.draw_panel(p, QRectF(150, ry, 640, 44))

# ---- family resemblance: the pet's own sprite next to the drawn adult ----
sy = y + 44 + len(panels) * 66 + 26
p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
p.setPen(QColor(58, 54, 48))
p.drawText(24, sy, "像不像它爸妈")
p.setFont(QFont("Microsoft YaHei", 10))
p.setPen(QColor(130, 124, 112))
p.drawText(24, sy + 20, "左：主虫精灵图（水平镜像成同一朝向）  右：手绘的成年后代")

CARD_W, CARD_H2 = 440, 240
box_y = sy + 34


def _card_frame(x):
    """Outline only -- a filled rounded rect would paint over the sprite."""
    p.setPen(QPen(QColor(214, 210, 200), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(x, box_y, CARD_W, CARD_H2), 10, 10)


_rx = 60 + CARD_W + 40
_card_frame(60)
_card_frame(_rx)

# -- left: the pet's own sprite, cropped to its drawn pixels and mirrored so
#    it faces the same way as the vector offspring (walk_right faces right).
try:
    from PIL import Image

    _im = Image.open(os.path.join(ROOT, "sprites", "walk_right.png")).convert("RGBA")
    # Threshold the alpha band first -- the sprite carries a wide,
    # almost-invisible (alpha 1-2) margin, so a plain getbbox() returns nearly
    # the whole canvas and the beetle ends up a speck in the middle.
    _bb = _im.split()[3].point(lambda v: 255 if v > 24 else 0).getbbox()
    _bug = _im.crop(_bb).transpose(Image.FLIP_LEFT_RIGHT)
    _bh = 176
    _bug = _bug.resize((max(1, int(_bug.width * _bh / _bug.height)), _bh),
                       Image.LANCZOS)
    _card = Image.new("RGBA", (CARD_W, CARD_H2), (252, 251, 248, 255))
    _card.alpha_composite(_bug, ((CARD_W - _bug.width) // 2,
                                 (CARD_H2 - _bh) // 2))
    # Hand the pixels over in memory.  Do NOT round-trip via a temp file +
    # QImage(path): that intermittently yielded a NULL image, and a null image
    # makes drawImage a silent no-op (the card came out blank with no error).
    _buf = _card.tobytes()
    _qi = QImage(_buf, CARD_W, CARD_H2, QImage.Format_RGBA8888).copy()
    if _qi.isNull():
        raise RuntimeError("sprite card -> QImage produced a null image")
    p.drawImage(QPointF(60, box_y), _qi)
except Exception as exc:                    # noqa: BLE001
    p.setPen(QColor(180, 60, 50))
    p.drawText(60, box_y + 20, "sprite load failed: %r" % (exc,))

# -- right: the vector adult, at a body length that matches the sprite card
#    (L = 64 px * SIZE 1.25 * 3.6 = 288 px)
p.save()
p.translate(_rx + CARD_W * 0.46, box_y + CARD_H2 * 0.52)
p.scale(3.6, 3.6)
off = O()
off.idx = O.ORDER.index(O.STAGE_ADULT)
off.stage = O.STAGE_ADULT
off.done = True
off.anim_t = 3.0
off.draw_in_nest(p, 0, 0)
p.restore()

p.end()
pm.save(out)
print("saved:", out, f"{pm.width()}x{pm.height()}")

