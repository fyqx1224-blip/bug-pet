"""Verify the published package does NOT embed the host's real relay address.

    python check_pkg_clean.py [path-to-桌面隐翅虫-壁纸联机包.zip]

Why this exists
---------------
`build_exe.py` used to bake the machine's real Tailscale address straight into
`room_overlay.py` as `RELAY_URL_DEFAULT`, and `build_full_pkg.py` reused that
same exe for the public release.  The address therefore sat inside a published
binary, recoverable by anyone.

The leak is invisible to a naive check twice over:

  * a plain `gzip`/byte scan of the zip misses it -- the entry script is stored
    as a *CArchive* entry (`room_overlay`), not a PYZ member, and PYZ members
    are individually zlib-compressed marshalled code objects;
  * and scanning only the PYZ skips the entry script entirely, which is exactly
    where the address was.

So this script reads both layers, decompresses, and inspects the compiled
constants.  Exit status is non-zero if a real relay address is found.
"""
import marshal
import os
import re
import struct
import sys
import tempfile
import zipfile
import zlib

from PyInstaller.archive.readers import CArchiveReader

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ZIP = os.path.join(os.path.dirname(HERE), "桌面隐翅虫-壁纸联机包.zip")

# The address every recipient is told to overwrite anyway.  Must stay a
# non-routable placeholder -- 100.64.0.1 is the bottom of the CGNAT range.
PLACEHOLDER = "ws://100.64.0.1:8765"

# Tailscale hands out 100.64.0.0/10 addresses.  Anything else in that range
# inside a published binary is the host's private network address.
CGNAT = re.compile(r"ws://100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+")


def entry_script(arc):
    """Return (name, decompressed blob) for the packaged entry script."""
    for nm in sorted(arc.toc):
        if nm.startswith("_"):
            continue
        if nm.endswith("room_overlay") or nm == "room_overlay":
            return nm, arc.extract(nm)
    return None, None


def ws_constants(blob):
    """Every 'ws://'/'wss://' string constant compiled into the entry script."""
    code = marshal.loads(blob)
    found = []

    def walk(co):
        for c in co.co_consts:
            if isinstance(c, str):
                for m in re.finditer(r"wss?://[^\s'\"]+", c):
                    found.append(m.group(0))
            elif hasattr(c, "co_consts"):
                walk(c)

    walk(code)
    return found


def check_zip(path):
    print("checking:", path)
    if not os.path.exists(path):
        print("  [FAIL] zip not found")
        return False

    z = zipfile.ZipFile(path)
    ok = True

    # ---- 1) relay.txt must be the placeholder ----
    for n in z.namelist():
        if n.endswith("relay.txt"):
            text = z.read(n).decode("utf-8", "replace")
            addrs = re.findall(r"wss?://[^\s]+", text)
            print("  relay.txt:", addrs)
            for a in addrs:
                if CGNAT.search(a) and a != PLACEHOLDER:
                    print("   [FAIL] relay.txt carries a real address:", a)
                    ok = False

    # ---- 2) the exe's compiled constants ----
    exe_name = [n for n in z.namelist() if n.endswith(".exe")]
    if not exe_name:
        print("  [FAIL] no exe inside the zip")
        return False
    tmp = os.path.join(tempfile.gettempdir(), "check_pkg_clean_exe.exe")
    with open(tmp, "wb") as f:
        f.write(z.read(exe_name[0]))

    arc = CArchiveReader(tmp)
    name, blob = entry_script(arc)
    if blob is None:
        print("  [FAIL] entry script not found in the exe")
        return False
    print("  entry script:", name, len(blob), "bytes")

    consts = sorted(set(ws_constants(blob)))
    print("  ws:// constants compiled into the exe:")
    for c in consts:
        print("     ", c)
    for c in consts:
        if CGNAT.search(c) and c != PLACEHOLDER:
            print("   [FAIL] real relay address baked into the exe:", c)
            ok = False

    # ---- 3) belt and braces: sweep every PYZ member too ----
    for nm in sorted(arc.toc):
        if not nm.startswith("PYZ"):
            continue
        pyz = arc.extract(nm)
        if pyz[:4] != b"PYZ\0":
            continue
        toc_off = struct.unpack("!i", pyz[8:12])[0]
        for cname, entry in marshal.loads(pyz[toc_off:]):
            _t, off, ln = entry
            part = pyz[off:off + ln]
            try:
                part = zlib.decompress(part)
            except Exception:
                pass
            for m in CGNAT.finditer(part.decode("latin-1")):
                if m.group(0) != PLACEHOLDER:
                    print("   [FAIL] real address in", nm, "::", cname,
                          m.group(0))
                    ok = False

    print("  ->", "CLEAN" if ok else "LEAK FOUND")
    return ok


if __name__ == "__main__":
    zp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    sys.exit(0 if check_zip(zp) else 1)
