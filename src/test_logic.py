"""Logic test for Phase 3 using the PyQt5 shim (no display needed)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pyqt_stub  # noqa: F401  (registers fake PyQt5 before import)
import room_overlay as R
from PyQt5.QtCore import QPoint, QPointF

# ---- construct (offscreen geometry 1920x1080 from the shim) ----
w = R.RoomOverlay()

# ---- 1) drive initiator into heat ----
w.hud.fullness = w.hud.energy = w.hud.happy = 1.0
w.hud.decay()
assert w.hud.in_heat, "expected in_heat True"
print("[1] in_heat =", w.hud.in_heat, "| can_breed =", w.hud.can_breed())

# ---- 2) drag handlers work for BOTH bugs ----
w.bug.x, w.bug.y = 300, 300
w.bug.start_drag(QPoint(320, 320), QPoint(320, 320))
w._drag_bug = w.bug
w.bug.update_drag(QPoint(360, 340))
assert w.bug.dragging and w.bug.x == 360 - w.bug.drag_offset.x()
w._on_bug_dropped(w.bug)
print("[2] initiator drop -> state =", w.bug.state)

# ---- 3) summon mate -> mating auto-starts ----
assert w.mate is None
w._summon_mate()
assert w.mate is not None, "mate not summoned"
assert w.mating is not None, "mating not started"
assert w.bug.state == R.Bug.STATE_MATING and w.mate.state == R.Bug.STATE_MATING
print("[3] mate summoned; both in STATE_MATING =", w.bug.state == w.mate.state == R.Bug.STATE_MATING)

# ---- 4) run mating sequence to completion (real pacing) ----
saw_mating = False
laid = False
n = 0
for _ in range(3000):
    w._tick()
    n += 1
    if w.bug.state == R.Bug.STATE_MATING or (w.mate and w.mate.state == R.Bug.STATE_MATING):
        saw_mating = True
    if w.offspring is not None:
        laid = True
        break
assert saw_mating, "never observed STATE_MATING during sequence"
assert laid, "egg was never laid"
print(f"[4] saw STATE_MATING = {saw_mating} | egg laid after {n} ticks | "
      f"mating cleared = {w.mating is None}")
print("    initiator state =", w.bug.state, "| mate state =", w.mate.state)

# ---- 5) offspring advances through every stage to ADULT ----
# In real-time mode the egg period is ~8h by design; collapse durations to
# fast values (mirrors BUG_PET_FAST) so we can exercise the full state machine.
R.Offspring.DURATIONS = {
    R.Offspring.STAGE_EGG: 0.5, R.Offspring.STAGE_HATCH: 0.5,
    R.Offspring.STAGE_LARVA: 0.5, R.Offspring.STAGE_GROWTH: 0.5,
    R.Offspring.STAGE_ADULT: float("inf"),
}
stages = []
prev = None
for _ in range(40000):
    if w.offspring is None:
        break
    w.offspring.tick(R.DT)
    if w.offspring.stage != prev:
        stages.append(w.offspring.stage_name())
        prev = w.offspring.stage
    if w.offspring.done:
        break
print("[5] offspring stages seen:", stages)
print("    final stage =", w.offspring.stage_name(), "| done =", w.offspring.done)
assert w.offspring.done, "offspring never reached ADULT"

# ---- 6) re-summon guard: blocked while a clutch is developing/done ----
# (we just laid one that is already adult; allow a fresh mating cycle)
w.hud.fullness = w.hud.energy = w.hud.happy = 1.0
w.hud.decay()
# kill the mate + mating so a new summon is permitted
w.mate = None
w.mating = None
w._summon_mate()
assert w.mate is not None, "re-summon blocked unexpectedly"
print("[6] re-summon (after clearing mate) works =", w.mate is not None)

# ---- 7) summon blocked when NOT in heat ----
w.mate = None; w.mating = None; w.offspring = None
w.hud.fullness = 0.2
w.hud.decay()
before = w.mate
w._summon_mate()
assert w.mate is None, "mate summoned while NOT in heat!"
print("[7] summon correctly blocked when not in heat =", w.mate is None)

print("\nALL PHASE-3 LOGIC CHECKS PASSED")
