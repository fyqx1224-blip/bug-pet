"""REAL end-to-end network test: two separate processes, a real relay,
real websockets.  Verifies discover + state sync + cross-machine mating.

Client A and client B live in the same file and are driven here as two
concurrently-running asyncio tasks, so the whole thing is genuinely async
and goes through the relay exactly like two real machines would.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.environ.setdefault("BUG_PET_OFFLINE_CATCHUP", "0")

import websockets

RELAY = "ws://127.0.0.1:8765"
ROOM = "ROOM-E2E"
HERE = Path(__file__).resolve().parent


async def _wait_listening(timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            async with websockets.connect(RELAY) as ws:
                await ws.send(json.dumps({"type": "hello", "room": "ping", "name": "p"}))
                return True
        except Exception:
            await asyncio.sleep(0.4)
    return False


async def client(name, results, mesh_x):
    """Mirror the real client: hello, then broadcast state continuously while
    draining whatever the relay forwards back, then a mating handshake."""
    async with websockets.connect(RELAY) as ws:
        await ws.send(json.dumps({"type": "hello", "room": ROOM,
                                  "name": name, "color": "#fff"}))
        got = []

        async def sender():
            # 15 Hz-ish broadcast, like the real overlay does
            for _ in range(8):
                await ws.send(json.dumps({"type": "state", "x": mesh_x,
                                          "y": 222.0, "st": "walking"}))
                await asyncio.sleep(0.25)

        async def receiver(seconds):
            t0 = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - t0 < seconds:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
                    got.append(json.loads(raw))
                except asyncio.TimeoutError:
                    continue

        await asyncio.gather(sender(), receiver(2.2))
        results[name + "_msgs"] = got

        # mating handshake across the relay
        await ws.send(json.dumps({"type": "mate_start", "seed": 4242,
                                  "t0": 0.0, "mid": [400.0, 300.0]}))
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < 2.0:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
                got.append(json.loads(raw))
            except asyncio.TimeoutError:
                continue
        results[name + "_after"] = got


async def run_clients(results):
    await asyncio.gather(client("甲", results, 111.0),
                         client("乙", results, 555.0))


def spawn_relay():
    # HERE == bug_pet/  (this test file lives there)
    exe = HERE / "dist_relay" / "隐翅虫中继.exe"
    if exe.exists():
        return subprocess.Popen([str(exe)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    # fall back to running the source
    env = dict(os.environ)
    return subprocess.Popen(
        [sys.executable, str(HERE / "src" / "net_relay.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HERE), env=env)


async def main():
    relay = spawn_relay()
    try:
        ok = await _wait_listening()
        print("[e2e] relay listening :", ok)
        assert ok, "relay did not come up"

        results = {}
        await asyncio.wait_for(run_clients(results), timeout=30.0)

        a_msgs = [m.get("type") for m in results.get("甲_msgs", [])]
        b_msgs = [m.get("type") for m in results.get("乙_msgs", [])]
        print("[e2e] 甲 received     :", a_msgs)
        print("[e2e] 乙 received     :", b_msgs)

        # each side must see the OTHER client's frame (peer + state + mate_start)
        assert "peer" in a_msgs and "peer" in b_msgs, "peer discovery failed"
        assert "state" in a_msgs and "state" in b_msgs, "state sync failed"
        assert "mate_start" in a_msgs and "mate_start" in b_msgs, "mating handshake failed"

        # the state the peer saw must be the one the other actually sent
        #   甲 sends x=111.0  ->  乙 应该看到 111.0
        #   乙 sends x=555.0  ->  甲 应该看到 555.0
        for who, peer_x in (("甲", 555.0), ("乙", 111.0)):
            seen = [m for m in results[who + "_msgs"] if m.get("type") == "state"]
            assert seen and abs(seen[0].get("x", -1) - peer_x) < 0.001, \
                f"{who} saw wrong x: {seen}"
        print("[e2e] 两端互见对方状态且坐标一致")
        print("\nALL REAL-NETWORK E2E CHECKS PASSED")
    finally:
        relay.terminate()
        try:
            relay.wait(timeout=5)
        except Exception:
            relay.kill()


if __name__ == "__main__":
    asyncio.run(main())
