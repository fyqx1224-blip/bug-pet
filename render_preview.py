"""Render a static preview of the overlay composited over the room wallpaper.

    python render_preview.py <out.png> [guides] [toast_text] [bug_scale]

guides: "1" -> BUG_PET_GUIDES=1 (draw the dashed drop-zone boxes)
toast_text: shown as a net toast in the render ("" = none)
bug_scale: e.g. 0.55 -> shrink the bug before grabbing (QA for 缩小虫子)
Runs headless (QT_QPA_PLATFORM=offscreen) with REAL PyQt5.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
out = sys.argv[1] if len(sys.argv) > 1 else "preview.png"
if len(sys.argv) > 2 and sys.argv[2] == "1":
    os.environ["BUG_PET_GUIDES"] = "1"
# optional third arg: show this text as a net toast in the render
_toast = sys.argv[3] if len(sys.argv) > 3 else ""
# optional fourth arg: bug size scale (QA for the right-click shrink)
_scale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
os.environ["BUG_SAVE"] = os.path.join(
    os.environ.get("TEMP", "."), "bugpet_preview_save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from PyQt5.QtWidgets import QApplication          # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QPixmap  # noqa: E402
from PyQt5.QtCore import Qt                        # noqa: E402
import room_overlay as R                           # noqa: E402
import _qa_fonts                                   # noqa: E402

app = QApplication(sys.argv)
print("fonts available:", len(_qa_fonts.load()))
w = R.RoomOverlay()
w.show()
app.processEvents()

# let the bug settle somewhere on screen
for _ in range(150):
    w._tick()
# pin it to a known spot/pose so scale renders are comparable
w.bug.x = w.sw * 0.5 - R.BUG_W / 2
w.bug.y = w.sh * 0.62 - R.BUG_H / 2
w.bug.state = w.bug.STATE_LANDED
w.bug.land_timer = 10 ** 6
if _scale != 1.0:
    w.bug.size_scale = max(R.BUG_SCALE_MIN, _scale)
if _toast:
    w._net_toast(_toast, seconds=9999.0)
app.processEvents()

pix = w.grab()          # real render of paintEvent, translucency included

wp = QImage(os.path.join(HERE, "wallpaper",
                         "bug_room_wallpaper_1920x1080.png"))
canvas = QImage(w.sw, w.sh, QImage.Format_ARGB32)
canvas.fill(Qt.transparent)
p = QPainter(canvas)
p.drawImage(0, 0, wp.scaled(w.sw, w.sh,
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
p.drawPixmap(0, 0, pix)
p.end()

canvas.save(out)
print(f"saved {out}  screen={w.sw}x{w.sh}  "
      f"HUD_OPACITY={R.HUD_OPACITY}  GUIDES={R.SHOW_ZONE_GUIDES}  "
      f"SHOW_HUD={R.SHOW_HUD}  BUG_SCALE={_scale}")

# zoomed crop of the top-left corner (where the stats panel lives)
crop = canvas.copy(0, 0, min(620, canvas.width()),
                   min(260, canvas.height()))
crop = crop.scaled(crop.width() * 2, crop.height() * 2,
                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
crop_out = out.replace(".png", "_hud_zoom.png")
crop.save(crop_out)
print(f"saved {crop_out}")
app.quit()
