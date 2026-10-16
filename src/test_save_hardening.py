"""Verify the save/load hardening.  Uses TEMP files only."""
import json, os, shutil, sys, tempfile, time

TMPDIR = tempfile.mkdtemp(prefix="bugdiag_")
SAVE = os.path.join(TMPDIR, "save.json")
os.environ["BUG_SAVE"] = SAVE
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"

sys.path.insert(0, os.path.dirname(__file__))
import pyqt_stub  # noqa: F401
import room_overlay as R

BAK = SAVE + ".bak"
ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and cond
    print(("  [PASS] " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))


def write(stage, idx, t, done=False, ts=None):
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump({"ver": 1, "ts": ts or time.time(),
                   "bug": {"x": 500, "y": 300, "facing": True,
                           "sleeping": False, "scale": 1.0},
                   "hud": {"fullness": 1.0, "energy": 1.0, "happy": 1.0},
                   "offspring": {"stage": stage, "idx": idx, "t": t, "done": done}}, f)


print("=== 1) normal GROWTH save round-trips ===")
write("GROWTH", 3, 1234.5)
w = R.RoomOverlay()
check("stage kept", w.offspring.stage == "GROWTH", w.offspring.stage)
check("t kept", abs(w.offspring.t - 1234.5) < 1e-6, "%.1f" % w.offspring.t)

print("=== 2) unknown stage string falls back to idx (was: silent rewind to EGG) ===")
write("PUPA", 3, 1234.5)          # idx 3 == GROWTH
w = R.RoomOverlay()
check("did NOT rewind", w.offspring.stage == "GROWTH", w.offspring.stage)
check("idx honoured", w.offspring.idx == 3, str(w.offspring.idx))

print("=== 3) unknown stage AND no usable idx -> clamp, still not a crash ===")
write("BOGUS", 99, 10.0)
w = R.RoomOverlay()
check("clamped to ADULT", w.offspring.stage == "ADULT", w.offspring.stage)

print("=== 4) a backup is kept on every save ===")
write("GROWTH", 3, 100.0)
w = R.RoomOverlay()               # writes save.json + save.json.bak
check(".bak created", os.path.exists(BAK))
with open(BAK, "r", encoding="utf-8") as f:
    check(".bak parses", json.load(f)["offspring"]["stage"] == "GROWTH")

print("=== 5) corrupt save.json -> restore from .bak ===")
write("LARVA", 2, 500.0)
w = R.RoomOverlay()
with open(SAVE, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json ]")
w2 = R.RoomOverlay()
check("offspring restored from backup", w2.offspring is not None
      and w2.offspring.stage == "LARVA", getattr(w2.offspring, "stage", None))

print("=== 6) corrupt save.json with NO backup -> file must be preserved ===")
os.remove(BAK)
with open(SAVE, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json ]")
w3 = R.RoomOverlay()
with open(SAVE, "r", encoding="utf-8") as f:
    body = f.read()
check("corrupt file NOT overwritten", body.startswith("{ this is not valid json"),
      repr(body[:24]))

print("=== 7) a test process must never write the live save ===")
saved_env = os.environ.pop("BUG_SAVE")
try:
    check("guard fires for a test_ process", R._live_save_is_protected() is True)
finally:
    os.environ["BUG_SAVE"] = saved_env
check("guard is off once BUG_SAVE is set", R._live_save_is_protected() is False)

shutil.rmtree(TMPDIR, ignore_errors=True)
print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
sys.exit(0 if ok else 1)
