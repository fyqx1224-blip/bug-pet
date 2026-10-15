"""Headless test for the right-click '缩小虫子' feature.

Covers: per-bug scale state, shrink/restore stepping + floor, footprint math
(bounding_rect / center / hit), teleport centring, Mating nest pos, mate /
remote staying at 1.0, and the autosave round-trip (incl. legacy saves).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # bug_pet/src/
sys.path.insert(0, str(HERE))

TMP = Path(tempfile.mkdtemp(prefix="bugshrink_"))
os.environ["BUG_SAVE"] = str(TMP / "save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"

import pyqt_stub  # noqa: F401,E402  (registers fake PyQt5 before import)
import room_overlay as R  # noqa: E402
from PyQt5.QtCore import QPointF, QRectF  # noqa: E402

w = R.RoomOverlay()
bug = w.bug

# ---- 1) defaults: footprint identical to the original constants ----
assert bug.size_scale == R.BUG_SCALE_DEFAULT
assert bug.w() == R.BUG_W and bug.h() == R.BUG_H
bug.x, bug.y = 100.0, 200.0
br = bug.bounding_rect()
assert (br.x(), br.y(), br.width(), br.height()) == \
    (100, 200, R.BUG_W, R.BUG_H), br.__dict__
assert bug.center() == QPointF(100 + R.BUG_W / 2, 200 + R.BUG_H / 2) \
    or (bug.center().x() == 100 + R.BUG_W / 2
        and bug.center().y() == 200 + R.BUG_H / 2)
print("[1] default footprint == BUG_W/H; center ok")

# ---- 2) shrink steps down and floors at BUG_SCALE_MIN ----
steps = []
for _ in range(10):
    steps.append(bug.shrink())
assert steps[-1] == R.BUG_SCALE_MIN, steps
# non-increasing, and pinned at the floor once reached
assert all(b <= a for a, b in zip(steps, steps[1:])), steps
first_floor = steps.index(R.BUG_SCALE_MIN)
assert all(s == R.BUG_SCALE_MIN for s in steps[first_floor:]), steps
assert first_floor >= 4, steps          # really shrinks several times first
print("[2] shrink chain:", [f"{s:.3f}" for s in steps], "-> floored")
assert bug.w() == R.BUG_W * R.BUG_SCALE_MIN
bug.x, bug.y = 640.0, 400.0
c = bug.center()
assert abs(c.x() - (640 + bug.w() / 2)) < 1e-6
assert abs(c.y() - (400 + bug.h() / 2)) < 1e-6
print("    scaled footprint + center ok:",
      f"({c.x():.0f},{c.y():.0f}) size {bug.w():.0f}x{bug.h():.0f}")

# ---- 3) hit test follows the shrunk footprint ----
assert bug.hit(QPointF(640 + bug.w() / 2, 400 + bug.h() / 2))
assert not bug.hit(QPointF(640 + R.BUG_W - 5, 400 + R.BUG_H - 5))
print("[3] hit(): inner point hits, old outer corner misses")

# ---- 4) restore back to the original size ----
bug.restore_size()
assert bug.size_scale == R.BUG_SCALE_DEFAULT
print("[4] restore_size() -> back to 1.0")

# ---- 5) the overlay handlers the menu wires up ----
w._shrink_bug()
assert abs(bug.size_scale - 0.8) < 1e-9, bug.size_scale
w._shrink_bug()
assert abs(bug.size_scale - 0.64) < 1e-9, bug.size_scale
w._restore_bug_size()
assert bug.size_scale == R.BUG_SCALE_DEFAULT
print("[5] _shrink_big -> 0.8 -> 0.64; _restore_bug_size -> 1.0")

# ---- 6) teleport centres the *scaled* footprint on the target ----
bug.shrink()
w._teleport_bug_to(900, 500)
c = bug.center()
assert abs(c.x() - 900) < 1e-6 and abs(c.y() - 500) < 1e-6, (c.x(), c.y())
bug.restore_size()
print("[6] _teleport_bug_to centres a shrunk bug on the target point")

# ---- 7) Mating nest pos uses the scaled footprint ----
mate = R.Bug(R.SPRITES_DIR)
nest = R.QRectF(300, 700, 260, 200)
m = R.Mating(bug, mate, nest)
p = m._nest_pos()
nc = nest.center()
assert abs(p.x() - (nc.x() - bug.w() / 2)) < 1e-6
assert abs(p.y() - (nc.y() - bug.h() / 2)) < 1e-6
print("[7] Mating._nest_pos centred for the shrunk bug")

# ---- 8) mate / remote bugs keep the default size ----
assert mate.size_scale == R.BUG_SCALE_DEFAULT
w.remote_bug = R.Bug(R.SPRITES_DIR)
assert w.remote_bug.size_scale == R.BUG_SCALE_DEFAULT
w.remote_bug = None
print("[8] mate + remote bugs stay at 1.0")

# ---- 9) autosave round-trip (constructor auto-loads) ----
bug.shrink()                       # 0.8
w._save_game()
data = json.loads(Path(os.environ["BUG_SAVE"]).read_text(encoding="utf-8"))
assert abs(data["bug"]["scale"] - 0.8) < 1e-9, data["bug"]
w2 = R.RoomOverlay()               # constructor calls _load_save()
assert abs(w2.bug.size_scale - 0.8) < 1e-9, w2.bug.size_scale
print("[9] scale saved + auto-restored on relaunch:", data["bug"]["scale"])

# ---- 10) a legacy save without 'scale' still loads (defaults to 1.0) ----
data["bug"].pop("scale")
Path(os.environ["BUG_SAVE"]).write_text(
    json.dumps(data), encoding="utf-8")
w3 = R.RoomOverlay()
assert w3.bug.size_scale == R.BUG_SCALE_DEFAULT
print("[10] legacy save (no scale field) -> defaults to 1.0")

print("\nALL SHRINK-FEATURE CHECKS PASSED")
