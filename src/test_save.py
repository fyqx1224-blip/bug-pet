"""Headless test: save / load / offline catch-up."""
import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(__file__))

SAVE_TMP = os.path.join(tempfile.mkdtemp(), "save.json")
os.environ["BUG_SAVE"] = SAVE_TMP
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "1"

import pyqt_stub  # noqa: F401
import room_overlay as R

# ---- 1) no save file -> fresh defaults ----
w = R.RoomOverlay()
assert w.offspring is None
assert w.net is None
print("[1] fresh start: no offline restore, bug at default pos",
      "x=%.0f y=%.0f" % (w.bug.x, w.bug.y))

# ---- 2) simulate play, then save ----
w.offspring = R.Offspring()
w.offspring.stage = R.Offspring.STAGE_LARVA
w.offspring.idx = 2
w.offspring.t = 123.4        # elapsed within the larva stage
w.hud.fullness, w.hud.energy, w.hud.happy = 0.9, 0.8, 0.7
w.bug.x, w.bug.y, w.bug.facing_right = 500, 300, True
w.bug.state = w.bug.STATE_LANDED
w._save_game()

with open(SAVE_TMP, "r", encoding="utf-8") as f:
    data = json.load(f)
print("[2] saved -> offspring:", data["offspring"]['stage'], "t=%.1f" % data["offspring"]['t'],
      "| hud:", data["hud"])
assert data["offspring"]['stage'] == R.Offspring.STAGE_LARVA

# ---- 3) fresh instance restores the same progress ----
w2 = R.RoomOverlay()
assert w2.offspring is not None, "offspring not restored!"
assert w2.offspring.stage == R.Offspring.STAGE_LARVA, w2.offspring.stage
assert w2.offspring.idx == 2, w2.offspring.idx
print("[3] restored -> stage:", w2.offspring.stage_name(), "idx:", w2.offspring.idx,
      "| pos x=%.0f y=%.0f" % (w2.bug.x, w2.bug.y))
assert w2.bug.x == 500 and w2.bug.y == 300

# ---- 4) offline catch-up: age the save and verify stage advance ----
# larva -> growth -> ... needs LARVA_PERIOD + GROWTH_PERIOD seconds.
with open(SAVE_TMP, "r", encoding="utf-8") as f:
    d = json.load(f)
d["ts"] = __import__("time").time() - 1e9        # "offline" ~31 years
with open(SAVE_TMP, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False)
w3 = R.RoomOverlay()
assert w3.offspring is not None
assert w3.offspring.done and w3.offspring.stage == R.Offspring.STAGE_ADULT, \
    "offline catch-up did not reach ADULT"
print("[4] offline catch-up: reached", w3.offspring.stage_name(), "done =", w3.offspring.done)
# stats decayed (off by default after such a long time)
assert w3.hud.fullness == 0.0 and w3.hud.energy == 0.0
print("    offline stats drained:", "full=%.2f energy=%.2f" %
      (w3.hud.fullness, w3.hud.energy))

# ---- 5) sleeping bug restores onto the nest ----
with open(SAVE_TMP, "r", encoding="utf-8") as f:
    d = json.load(f)
import time as _t
d["ts"] = _t.time()
d["bug"]["sleeping"] = True
d["offspring"] = None
d["hud"] = {"fullness": 1.0, "energy": 1.0, "happy": 1.0}
with open(SAVE_TMP, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False)
w4 = R.RoomOverlay()
assert w4.bug.state == w4.bug.STATE_SLEEPING, w4.bug.state
nc = w4.nest.rect.center()
print("[5] sleeping restore: state =", w4.bug.state,
      "| snapped to nest (%.0f,%.0f)" % (nc.x(), nc.y()))
assert abs(w4.bug.x - (nc.x() - R.BUG_W / 2)) < 1

# ---- 6) corrupt save must not crash ----
with open(SAVE_TMP, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json ]")
w5 = R.RoomOverlay()
print("[6] corrupt save handled: bug={}".format(w5.bug.state))

print("\nALL SAVE/RESTORE CHECKS PASSED")
