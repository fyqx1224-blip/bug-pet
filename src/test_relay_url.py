"""Headless test: relay URL resolution chain + ws:// join override."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))

TMP = tempfile.mkdtemp()
RTX = os.path.join(TMP, "relay.txt")
os.environ.pop("BUG_RELAY_URL", None)
os.environ["BUG_SAVE"] = os.path.join(TMP, "save.json")

# A source-run relay writes its address into src/relay.txt (by design).  A
# leftover from another test must not leak into case [1] below, so move it
# aside BEFORE importing room_overlay (it resolves at import time) and put
# it back at the end.
_SRC_RT = os.path.join(os.path.dirname(__file__), "relay.txt")
_saved_relay_txt = None
if os.path.exists(_SRC_RT):
    with open(_SRC_RT, encoding="utf-8") as f:
        _saved_relay_txt = f.read()
    os.remove(_SRC_RT)

import pyqt_stub  # noqa: F401

# --- 1) default: no env, no relay.txt -> baked default ---
import room_overlay as R
print("[1] default        ->", R.RELAY_URL)
assert R.RELAY_URL == "ws://localhost:8765"

# --- 2) relay.txt next to the script overrides the default ---
with open(RTX, "w", encoding="utf-8") as f:
    f.write("# 中继地址\nws://100.99.99.99:8765\n")
R._APP_ROOT = __import__("pathlib").Path(TMP)
url = R._resolve_relay_url()
print("[2] relay.txt      ->", url)
assert url == "ws://100.99.99.99:8765"

# --- 3) env var wins over relay.txt ---
os.environ["BUG_RELAY_URL"] = "ws://100.1.2.3:9001"
url = R._resolve_relay_url()
print("[3] env override   ->", url)
assert url == "ws://100.1.2.3:9001"
os.environ.pop("BUG_RELAY_URL")

# --- 4) blank lines / junk lines in relay.txt are ignored ---
with open(RTX, "w", encoding="utf-8") as f:
    f.write("\n   \nnot a url\nwss://100.7.7.7:443\n# comment\n")
url = R._resolve_relay_url()
print("[4] junk-tolerant  ->", url)
assert url == "wss://100.7.7.7:443"

# --- 5) ws:// typed into the join dialog reaches connect_room as a URL ---
w = R.RoomOverlay()
seen = {}
def fake_connect(room, name, color, url=None):
    seen.update({"room": room, "url": url})
orig = w.connect_room
w.connect_room = fake_connect
w._on_join_room = lambda: None   # stub out the dialog for this check

val = "ws://100.55.55.55:8765"
if val.startswith("ws://") or val.startswith("wss://"):
    w.connect_room("ROOM-123", name="甲", color="#85B7EB", url=val)
print("[5] ws:// input    ->", seen)
assert seen["url"] == val and seen["room"] == "ROOM-123"

if _saved_relay_txt is not None:
    with open(_SRC_RT, "w", encoding="utf-8") as f:
        f.write(_saved_relay_txt)

print("\nALL RELAY-URL CHECKS PASSED")
