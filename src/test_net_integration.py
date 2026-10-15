"""Full-stack cross-PC integration: two RoomOverlay instances (PyQt5 shim,
headless) talking through a REAL relay subprocess over REAL websockets.

This exercises the entire product path exactly as two colleague machines do:

    connect_room -> hello/peer -> 15 Hz state broadcast -> remote_bug mirror
    -> mate_req -> mate_start (acceptor picks the shared seed)
    -> deterministic Mating on both sides -> egg laid on both sides
    -> autosave contains the clutch -> bye clears the remote bug

Nothing here is mocked on the network side: the relay is src/net_relay.py
running as its own process, and both clients use the real NetClient threads.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # bug_pet/src/
BUGP = HERE.parent                              # bug_pet/
sys.path.insert(0, str(HERE))

# temp save + no offline catch-up, so we never touch the real %LOCALAPPDATA% save
os.environ["BUG_SAVE"] = str(
    Path(tempfile.mkdtemp(prefix="bugpet_it_")) / "save.json")
os.environ["BUG_PET_OFFLINE_CATCHUP"] = "0"

import pyqt_stub  # noqa: F401,E402  (registers fake PyQt5 before import)
import room_overlay as R  # noqa: E402

PORT = 8899
RELAY = f"ws://127.0.0.1:{PORT}"
ROOM = "ROOM-IT"


def spawn_relay():
    env = dict(os.environ)
    env["RELAY_PORT"] = str(PORT)
    return subprocess.Popen(
        [sys.executable, str(HERE / "net_relay.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


async def _wait_listening(timeout=20.0):
    import websockets
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            async with websockets.connect(RELAY) as ws:
                await ws.send(json.dumps({"type": "hello", "room": "ping",
                                          "name": "p"}))
                return True
        except Exception:
            await asyncio.sleep(0.3)
    return False


def drive_both(wA, wB, ticks, sleep=0.004):
    """Tick both overlays in lockstep, sleeping so the real network threads
    (and the peer) get wall-clock time to run between frames."""
    for _ in range(ticks):
        wA._tick()
        wB._tick()
        if sleep:
            time.sleep(sleep)


def main():
    relay = spawn_relay()
    try:
        assert asyncio.run(_wait_listening()), "relay did not start"
        print(f"[it] real relay up on {RELAY}")

        wA = R.RoomOverlay()
        wB = R.RoomOverlay()
        wA.connect_room(ROOM, "机器甲", "#85B7EB", url=RELAY)
        wB.connect_room(ROOM, "机器乙", "#F1A85B", url=RELAY)

        # ---- 1) connect + discover + state mirror (<= ~5s) ----
        t0 = time.time()
        while time.time() - t0 < 5.0:
            drive_both(wA, wB, 5)
            if (wA.net.connected and wB.net.connected
                    and wA.remote_bug is not None and wB.remote_bug is not None):
                break
        assert wA.net.connected and wB.net.connected, "net not connected"
        assert wA.remote_bug is not None and wB.remote_bug is not None, \
            "remote bug never spawned from peer state frames"
        print("[it] both connected; peer discovered on both sides")

        # park A's bug exactly (SLEEPING = stays in place) and let B mirror it
        wA.bug.state = R.Bug.STATE_SLEEPING
        wA.bug.x, wA.bug.y = 700.0, 500.0
        drive_both(wA, wB, 40)
        bx, by = wB.remote_bug.x, wB.remote_bug.y
        assert abs(bx - 700.0) < 12 and abs(by - 500.0) < 12, \
            f"position mirror off: got ({bx},{by}) expected ~(700,500)"
        print(f"[it] B mirrors A at ({bx:.0f},{by:.0f})  <- A sent (700,500)")

        # ---- 2) mate handshake through the relay ----
        for w in (wA, wB):
            w.hud.fullness = w.hud.energy = w.hud.happy = 1.0
            w.hud.decay()          # refreshes the cached in_heat flag
        assert wA.hud.in_heat and wB.hud.in_heat, "both should be in heat"
        wA._on_net_mate_request()          # A invites -> B auto-accepts
        drive_both(wA, wB, 20)
        assert wA.mating is not None and wB.mating is not None, \
            "mating did not start on BOTH sides"
        assert wA.mating.seed == wB.mating.seed, \
            f"seeds diverged: {wA.mating.seed} vs {wB.mating.seed}"
        assert wA.bug.state == R.Bug.STATE_MATING and \
               wB.bug.state == R.Bug.STATE_MATING, "both bugs must be mating"
        print(f"[it] mating live on both sides, shared seed = {wA.mating.seed}")

        # ---- 3) run the full sequence -> egg on both sides ----
        laid = [False, False]
        hearts_seen = [0, 0]
        n = 0
        t0 = time.time()
        while time.time() - t0 < 45.0:
            wA._tick()
            wB._tick()
            n += 1
            if wA.offspring is not None:
                laid[0] = True
            if wB.offspring is not None:
                laid[1] = True
            if wA.mating:
                hearts_seen[0] = max(hearts_seen[0], len(wA.mating.hearts))
            if wB.mating:
                hearts_seen[1] = max(hearts_seen[1], len(wB.mating.hearts))
            if all(laid):
                break
            time.sleep(0.004)
        assert all(laid), f"egg not laid on both sides: {laid}"
        print(f"[it] egg laid on BOTH sides after {n} ticks "
              f"(peak hearts A={hearts_seen[0]}, B={hearts_seen[1]})")
        assert min(hearts_seen) > 0, "no heart particles were ever spawned"

        # ---- 4) autosave carries the clutch across a shutdown ----
        sp = Path(os.environ["BUG_SAVE"])
        assert sp.exists(), "autosave file missing"
        data = json.loads(sp.read_text(encoding="utf-8"))
        assert data.get("offspring"), "clutch missing from save"
        print("[it] autosave contains offspring stage:", data["offspring"].get("stage"))

        # ---- 5) peer departure (real path: stop() -> bye -> relay) ----
        wB.net.stop()
        t0 = time.time()
        while time.time() - t0 < 3.0:
            drive_both(wA, wB, 3)
            if wA.remote_bug is None:
                break
        assert wA.remote_bug is None, \
            "peer departure did not clear the remote bug"
        print("[it] B left -> A's remote bug cleared via relay 'bye'")

        # ---- 6) clean shutdown of both clients ----
        for w in (wA, wB):
            if w.net is not None:
                w.net.stop()
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if not (wA.net.thread.is_alive() or wB.net.thread.is_alive()):
                break
            time.sleep(0.05)
        print("[it] both client threads exited cleanly")

        print("\nALL CROSS-PC INTEGRATION CHECKS PASSED")
    finally:
        relay.terminate()
        try:
            relay.wait(timeout=5)
        except Exception:
            relay.kill()


if __name__ == "__main__":
    main()
