"""Minimal room-based WebSocket relay for the bug-pet cross-PC play.

Run:
    python net_relay.py            # listens on :8765
    RELAY_PORT=9001 python net_relay.py

Two (or more) clients that join the same `room` get each other's JSON frames
forwarded.  No game logic lives here -- it only routes text frames between the
members of a room.  Pairing is just "enter the same room code".

For two colleagues behind NAT, run this on one machine and connect both via
Tailscale (the relay binds 0.0.0.0, so the colleague uses the host's Tailscale
IP, e.g. ws://100.x.y.z:8765).  No port forwarding needed.

On startup it prints the Tailscale address (and writes it to relay.txt next to
the executable) so the host has something concrete to hand to the colleague.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import websockets

PORT = int(os.environ.get("RELAY_PORT", "8765"))
# Shown only when Tailscale cannot be detected. NEVER put a real Tailscale IP
# here - this repository is public. Override locally with BUG_RELAY_HOST.
FALLBACK_IP = os.environ.get("BUG_RELAY_HOST", "100.64.0.1")
ROOMS = {}  # room -> set(websocket)


def _tailscale_ip():
    """Best-effort detection of this machine's Tailscale IPv4."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "tailscale.exe")
    candidates += [r"C:\Program Files\Tailscale\tailscale.exe",
                   r"C:\Program Files (x86)\Tailscale\tailscale.exe",
                   "tailscale"]
    for exe in candidates:
        try:
            r = subprocess.run([str(exe), "ip", "-4"], capture_output=True,
                               text=True, timeout=8)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line:
                    return line
        except Exception:
            continue
    return FALLBACK_IP


def _write_relay_txt(url):
    """Drop the address next to the exe (or script) so the host can forward it."""
    try:
        base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent)
        (base / "relay.txt").write_text(url + "\n", encoding="utf-8")
    except Exception:
        pass


async def _broadcast(room, msg, skip=None):
    peers = ROOMS.get(room, set())
    data = json.dumps(msg)
    for p in list(peers):
        if p is skip:
            continue
        try:
            await p.send(data)
        except Exception:
            pass


async def _handler(ws):
    room = None
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            if t == "hello":
                room = msg.get("room", "default")
                ROOMS.setdefault(room, set()).add(ws)
                who = msg.get("name", "?")
                _p(f"[relay] {who} 加入房间 {room}（当前 {len(ROOMS[room])} 人）")
                # 告诉加入者本人当前房间人数 …
                await ws.send(json.dumps(
                    {"type": "peer", "count": len(ROOMS[room])}))
                # … 并通知房间里其他人 "有新伙伴进来了"
                await _broadcast(room, {"type": "peer", "count": len(ROOMS[room])},
                                 skip=ws)
            else:
                # state / mate_req / mate_start / egg / bye -> forward to peers
                if room:
                    await _broadcast(room, msg, skip=ws)
    finally:
        if room and ws in ROOMS.get(room, set()):
            ROOMS[room].discard(ws)
            if ROOMS[room]:
                # tell the remaining peers so their remote bug disappears
                await _broadcast(room, {"type": "bye"})
                _p(f"[relay] 有人离开房间 {room}（剩余 {len(ROOMS[room])} 人）")


def _p(*args):
    """Print + flush: onefile console apps buffer stdout, so force it out
    immediately -- otherwise the host sees nothing until the process exits."""
    print(*args, flush=True)


# Tailscale hands out addresses from the CGNAT range 100.64.0.0/10.  Scoping the
# inbound rule to it keeps the relay reachable for the colleague (same tailnet)
# while keeping the port CLOSED to whatever LAN / public Wi-Fi this machine is
# on.  That matters because the relay has NO authentication - anyone who can
# reach the port and guess the room code is in - and the room code travels in
# cleartext over plain ws://, so a shared network is a real exposure.
_TS_RANGE = "100.64.0.0/10"


def _fw_rule_name():
    # ASCII only: the name goes through netsh / bat files.
    # NOTE the "TS": netsh matches rule names by SUBSTRING, so the new name must
    # NOT contain the old one - otherwise deleting the legacy rule would take
    # this one down with it.
    return f"BugPetRelayTS{PORT}"


def _fw_rule_name_legacy():
    # The pre-scoping rule: same port, but open to ANY remote address.
    return f"BugPetRelay{PORT}"


def _fw_rule_present(name=None):
    # NOTE: compare BYTES and match only the ASCII rule name -- netsh prints
    # GBK Chinese on a Chinese Windows, and decoding it as text crashes the
    # pipe reader (that once produced a false "授权被取消" report).
    rule = name or _fw_rule_name()
    needle = rule.encode("ascii")
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
            capture_output=True, timeout=15)
        return needle.lower() in (r.stdout or b"").lower()
    except Exception:
        return False


def _fw_rule_delete(name):
    """Best-effort removal of a rule we added earlier.  Needs admin; a failure
    is not fatal - the rule simply stays put."""
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _drop_legacy_fw_rule():
    """Delete the older, UNSCOPED rule if it is still around: it let the relay
    port be reached from any address, including whatever LAN we are on."""
    if not _fw_rule_present(_fw_rule_name_legacy()):
        return
    if _fw_rule_delete(_fw_rule_name_legacy()):
        _p("[relay] 已移除旧的『不限来源』防火墙规则（安全加固）")
    else:
        _p("[relay] ⚠ 旧的『不限来源』规则还在，建议以管理员身份执行一次：")
        _p(f"[relay]   netsh advfirewall firewall delete rule name={_fw_rule_name_legacy()}")


def _ensure_firewall_rule():
    """First run on a machine, make sure the colleague's traffic can reach
    port PORT.  Windows Firewall blocks inbound by default, so without this
    the colleague gets connection timeouts no matter what.  Adding a rule
    needs admin -> triggers ONE UAC prompt when the rule is missing."""
    if os.name != "nt":
        return True
    if _fw_rule_present():
        _drop_legacy_fw_rule()
        return True
    args = ["netsh", "advfirewall", "firewall", "add", "rule",
            f"name={_fw_rule_name()}", "dir=in", "action=allow",
            "protocol=TCP", f"localport={PORT}", f"remoteip={_TS_RANGE}"]
    # try directly (works when already elevated)
    try:
        r = subprocess.run(args, capture_output=True, timeout=20)
        if r.returncode == 0 and _fw_rule_present():
            _p(f"[relay] 防火墙已放行端口 {PORT}（仅限 Tailscale 网段 {_TS_RANGE}）")
            _drop_legacy_fw_rule()
            return True
    except Exception:
        pass
    # not elevated: ask once via UAC.  The elevated command lives in a .bat
    # so no quoting games with Start-Process -ArgumentList.
    _p("[relay] ─────────────────────────────────────────────")
    _p(f"[relay] 首次运行：需要一次管理员授权放行防火墙（端口 {PORT}），")
    _p("[relay] 否则同事的电脑连不进来。")
    _p("[relay] 屏幕上会弹出『用户账户控制：是否允许更改』→ 点【是】")
    _p("[relay] ─────────────────────────────────────────────")
    try:
        import tempfile
        bat = Path(tempfile.gettempdir()) / "bugpet_relay_firewall.bat"
        bat.write_text("@echo off\n" + " ".join(f'"{a}"' for a in args) + "\n",
                       encoding="ascii", errors="ignore")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Start-Process -FilePath "{bat}" -Verb RunAs -Wait'],
            capture_output=True, text=True, timeout=120)
    except Exception as e:
        _p(f"[relay] 授权流程启动失败: {e!r}")
    if _fw_rule_present():
        _p("[relay] 防火墙放行成功 ✔ 同事现在可以连了")
        _drop_legacy_fw_rule()
        return True
    _p("[relay] 防火墙没有放行（授权被取消？）。")
    _p("[relay] 请右键以管理员身份运行 dist_relay\\防火墙放行.bat")
    return False


async def _main():
    ip = _tailscale_ip()
    url = f"ws://{ip}:{PORT}"
    mode = "exe" if getattr(sys, "frozen", False) else "source"
    _p("=" * 60)
    _p(f"[relay] 隐翅虫中继已启动（{mode}）  端口 {PORT}")
    _p(f"[relay] 本机 Tailscale IP : {ip}")
    _p(f"[relay] 发给同事的地址    : {url}")
    _p("[relay] 也已写入同目录 relay.txt")
    _p("[relay] 房间码双方填一样的即可（默认 ROOM-123）")
    _p("[relay] 关闭此窗口即停止中继")
    _p("=" * 60)
    _write_relay_txt(url)
    _ensure_firewall_rule()
    async with websockets.serve(_handler, "0.0.0.0", PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n[relay] stopped")
