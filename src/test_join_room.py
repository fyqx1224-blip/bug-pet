"""Reproduce the exact "联机 -> 加入房间" user flow headlessly:

real Qt (offscreen) + real relay subprocess + real NetClient, with the
input dialog auto-answered.  Verifies the menu action -> dialog result ->
connect_room -> NetClient -> relay chain, the on-screen status toasts, and
that re-joining is possible after a failed attempt (no more silent no-op).
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # bug_pet/src/
BUGP = HERE.parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BUG_SAVE"] = str(
    Path(tempfile.mkdtemp(prefix="bugjoin_")) / "save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"
sys.path.insert(0, str(HERE))

PORT = 8886
env = dict(os.environ)
env["RELAY_PORT"] = str(PORT)
relay = subprocess.Popen(
    [sys.executable, str(HERE / "net_relay.py")],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
time.sleep(2.0)

# NOTE: no pyqt_stub here -- this test needs REAL Qt (offscreen platform).

from PyQt5.QtWidgets import QApplication  # noqa: E402
import room_overlay as R                 # noqa: E402

app = QApplication(sys.argv)
w = R.RoomOverlay()
w.show()
QApplication.processEvents()

# auto-answer the room dialog, as if the user typed ROOM-777 and pressed OK
R.QInputDialog.getText = staticmethod(
    lambda *a, **k: ("ROOM-777", True))


def drive(seconds):
    n = int(seconds / R.DT)
    for _ in range(n):
        w._tick()
        time.sleep(0.004)


print("[join] HAVE_WEBSOCKETS =", R.HAVE_WEBSOCKETS)
assert R.HAVE_WEBSOCKETS, "websockets missing in this build!"

# ---- 1) failed attempt first (relay address with nothing listening) ----
print("[1] first attempt to a dead port ...")
w.connect_room("ROOM-777", "机器A", url=f"ws://127.0.0.1:1")
assert w.net is not None
first_client = w.net
drive(3.0)                       # > 2s so the failure toast can fire
assert not w.net.connected
print("    toast after failure :", w._net_toast_text)
assert "连不上" in w._net_toast_text, "no retry toast on failed connect"

# ---- 2) re-join with the good address (must NOT be silently ignored) ----
print("[2] re-join with the good relay ...")
w._on_join_room()                # simulates the menu click again
assert w.net is not None and w.net is not first_client, \
    "stale client was not replaced - re-join is a silent no-op!"
assert w.remote_bug is not None
print("    toast on join       :", w._net_toast_text)
assert "正在连接" in w._net_toast_text

drive(3.0)
assert w.net.connected, "NetClient never connected to the relay"
print("    toast after connect :", w._net_toast_text)
assert "已连接" in w._net_toast_text
print("    relay URL used      :", w.net._url)

# ---- 3) peer arrives -> toast + remote bug; peer leaves -> cleared ----
w._net_inbox.append({"type": "state", "x": 640.0, "y": 400.0,
                     "facing": True, "st": "walking",
                     "full": 1.0, "nrg": 1.0, "mood": 1.0})
drive(0.2)
print("    toast on peer arrive:", w._net_toast_text)
assert "对方进入房间" in w._net_toast_text
assert w.remote_bug is not None and abs(w.remote_bug.x - 640.0) < 1

w._net_inbox.append({"type": "bye"})
drive(0.2)
assert w.remote_bug is None, "bye did not clear the remote bug"
print("    toast on peer leave :", w._net_toast_text)
assert "对方已离开" in w._net_toast_text

# ---- 4) connected menu state (drives the "已连接" label) ----
assert w.net.connected

w.net.stop()
relay.terminate()
print("\nJOIN-ROOM FLOW + FEEDBACK CHECKS PASSED")
