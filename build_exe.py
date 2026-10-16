"""Package the bug pet as a single .exe so the colleague needs NO Python.

Run on a machine that already has Python + PyQt5 (i.e. your own PC):
    双击 build_exe.bat

Output:
    dist/桌面隐翅虫.exe     <- the app
    dist/relay.txt          <- relay address (editable if the Tailscale IP changes)
    dist/给同事的说明.txt     <- what to send her
    桌面隐翅虫.exe.zip       <- send THIS to her
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GUEST = ROOT.parent / "bug_pet_guest"
# NEVER put a real Tailscale IP here - this repository is public.
FALLBACK_IP = os.environ.get("BUG_RELAY_HOST", "100.64.0.1")

# Baking the host's REAL Tailscale address into the exe makes the colleague's
# copy connect with zero setup -- but the address then lives inside a binary,
# and the release zip is public, so anyone can pull it straight back out of
# room_overlay's compiled constants.  Baking it is therefore OPT-IN, and only
# for the private hand-off package:
#
#     $env:BUG_BAKE_RELAY_IP = "1"
#     .\build_exe.bat
#
# The published 壁纸联机包 never bakes it (build_full_pkg.py forces it off) and
# ships a placeholder relay.txt instead, which _resolve_relay_url() already
# prefers over the baked default -- so nothing is lost by not baking.
BAKE_REAL_IP = os.environ.get("BUG_BAKE_RELAY_IP") == "1"


def tailscale_ip() -> str:
    """Find this machine's Tailscale IP (falls back to the last known one)."""
    for exe in (r"C:\Program Files\Tailscale\tailscale.exe",
                r"C:\Program Files (x86)\Tailscale\tailscale.exe",
                "tailscale"):
        try:
            r = subprocess.run([exe, "ip", "-4"], capture_output=True,
                               text=True, timeout=10)
            first = (r.stdout or "").strip().splitlines()
            if first and first[0].strip():
                return first[0].strip()
            # onefile: tailscale may list several IPs on its own output
            for line in first:
                if line.strip():
                    return line.strip()
        except Exception:
            continue
    return FALLBACK_IP


ip = tailscale_ip() if BAKE_REAL_IP else FALLBACK_IP
URL = f"ws://{ip}:8765"
print(f"[build] relay ip     : {ip}"
      + ("" if BAKE_REAL_IP else "  (placeholder, real IP NOT baked)"))
print(f"[build] relay url    : {URL}")

# ---- 1) refresh the slim package (code + downscaled assets + jpg fog) ----
print("[build] building slim guest package ...")
subprocess.run([sys.executable, str(ROOT / "build_guest_pkg.py")], check=True)

# ---- 2) bake the address into the copy that will be packaged ----
overlay = GUEST / "src" / "room_overlay.py"
text = overlay.read_text(encoding="utf-8")
old = 'RELAY_URL_DEFAULT = os.environ.get("BUG_RELAY_URL", "ws://localhost:8765")'
new = f'RELAY_URL_DEFAULT = os.environ.get("BUG_RELAY_URL", "{URL}")'
assert old in text, "RELAY_URL_DEFAULT line not found - has the source drifted?"
overlay.write_text(text.replace(old, new, 1), encoding="utf-8")

# ---- 3) make sure PyInstaller is available ----
try:
    import PyInstaller  # noqa: F401
    print("[build] PyInstaller", PyInstaller.__version__)
except ImportError:
    print("[build] installing PyInstaller ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                   check=True)

# ---- 4) run PyInstaller ----
dist = ROOT / "dist"
build = ROOT / "build"
for d in (dist, build):
    if d.exists():
        shutil.rmtree(d)

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile", "--windowed",
    "--noconfirm", "--clean",
    "--name", "桌面隐翅虫",
    # Windows uses ';' as the source;dest separator
    "--add-data", f"{GUEST / 'sprites'};sprites",
    "--collect-submodules", "websockets",
    "--hidden-import", "websockets",
    "--distpath", str(dist),
    "--workpath", str(build),
    "--specpath", str(ROOT),
    str(overlay),
]
print("[build] running PyInstaller ...")
subprocess.run(cmd, check=True)

exe = dist / "桌面隐翅虫.exe"
if not exe.exists():
    print("[build] !! exe not produced - see the PyInstaller log above")
    sys.exit(1)

# ---- 5) put the editable relay address + instructions beside the exe ----
(dist / "relay.txt").write_text(URL + "\n", encoding="utf-8")
(dist / "给同事的说明.txt").write_text(f'''桌面隐翅虫 · 联机版
==============================
不用装 Python，双击就能玩。

【打开】双击  桌面隐翅虫.exe
  （第一次跑，杀毒软件可能问一下，选"仍要运行"即可）

【界面上有三个虚框】食盆 / 睡窝 / 训练区
  把虫拖进框里就会吃饭 / 睡觉 / 训练；也可以直接右键虫子
  用菜单里的"去吃饭 / 去睡觉 / 去训练"。

【联机】右键点虫子 → 联机：加入房间 → 房间码填
        ROOM-123    → 确定

然后电脑另一头（我）的屏幕上就会出现你的虫。
三个虚框喂满后，就能联机交配、生虫卵、孵小虫。

------------------------------
如果连不上：多半是我这边的 Tailscale IP 变了。
把 zip 里的  relay.txt  用记事本打开，改成我新发给你的
 ws://xxx.xxx.xxx.xxx:8765  保存，再重开 exe。

或者在"加入房间"框里直接粘贴完整地址 ws://开头的那串。

当前联机地址：{URL}
房间码：ROOM-123
''', encoding="utf-8")

# ---- 6) zip it ----
zip_path = ROOT.parent / "桌面隐翅虫.exe.zip"
if zip_path.exists():
    zip_path.unlink()
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(exe, exe.name)
    z.write(dist / "relay.txt", "relay.txt")
    z.write(dist / "给同事的说明.txt", "给同事的说明.txt")

print()
print("=" * 56)
print("[build] DONE")
print(f"[build] exe  : {exe}  ({exe.stat().st_size/1024/1024:.1f} MB)")
print(f"[build] zip  : {zip_path}  ({zip_path.stat().st_size/1024/1024:.1f} MB)")
print("[build] send the zip to her; she only unzips + double-clicks.")
print("=" * 56)
