"""Build a slim 'bug_pet_guest' package for the colleague.

- Only the assets the overlay actually loads at runtime are included.
- Bug sprites (1024x1024, shown at 300x200) are downscaled to 512x512.
- Fog frames (1920x1072 RGB, no alpha) are re-encoded as JPEG q85.
- The guest copy's fog loader is patched to accept .jpg as well as .png.
- 启动.bat pre-sets BUG_RELAY_URL so the colleague runs zero config.
"""
import os
import shutil
from pathlib import Path

from PIL import Image

from build_inputs import FOG, SPRITES

SRC = Path(__file__).resolve().parent          # .../bug_pet/
SRC_SRC = SRC / "src"
OUT = SRC.parent / "bug_pet_guest"
# NEVER commit real values here - this repository is public. For a private build
# pass them in:  BUG_RELAY_HOST=100.x.y.z  BUG_ROOM=ROOM-XXXX
HOST_IP = os.environ.get("BUG_RELAY_HOST", "100.64.0.1")
ROOM = os.environ.get("BUG_ROOM", "ROOM-123")

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "src").mkdir(parents=True)
(OUT / "sprites" / "fog_bg").mkdir(parents=True)

# ---- 1) code ----
dup = OUT / "src" / "room_overlay.py"
text = (SRC_SRC / "room_overlay.py").read_text(encoding="utf-8")

# let the guest loader pick up JPEG frames (much smaller than PNG here)
old = '''        for i in range(6):
            path = fog_dir / f"fog_bg_{i}.png"
            if path.exists():'''
new = '''        for i in range(6):
            for _ext in ("jpg", "png"):
                path = fog_dir / f"fog_bg_{i}.{_ext}"
                if path.exists():'''
assert old in text, "fog loader pattern not found"
text = text.replace(old, new, 1)
# indent the two following lines so they live inside the new inner loop
tail_old = '''                pm = QPixmap(str(path))
                if not pm.isNull():
                    self.fog_frames.append(pm)'''
tail_new = '''                    pm = QPixmap(str(path))
                    if not pm.isNull():
                        self.fog_frames.append(pm)
                        break'''
assert tail_old in text, "fog loader tail not found"
text = text.replace(tail_old, tail_new, 1)
dup.write_text(text, encoding="utf-8")

# relay script too (in case she ever wants to host instead)
shutil.copy2(SRC_SRC / "net_relay.py", OUT / "src" / "net_relay.py")
(OUT / "requirements.txt").write_text(
    "PyQt5>=5.15\nPillow>=10.0\nwebsockets>=12.0\n", encoding="utf-8")

# ---- 2) bug sprites -> 512x512 RGBA PNG ----
# The file lists come from build_inputs.py so they can never drift from what
# the build fingerprint (build_exe.py) claims the build consumes.
for rel in SPRITES:
    im = Image.open(SRC / rel).convert("RGBA")
    im = im.resize((512, 512), Image.LANCZOS)
    im.save(OUT / rel, optimize=True)

# ---- 3) fog frames -> JPEG q85 ----
for rel in FOG:
    im = Image.open(SRC / rel).convert("RGB")
    im.save(OUT / (os.path.splitext(rel)[0] + ".jpg"), quality=85, optimize=True)

# ---- 4) launcher ----
(OUT / "启动.bat").write_text(f'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
set BUG_RELAY_URL=ws://{HOST_IP}:8765
set PYTHONIOENCODING=utf-8
python src\\room_overlay.py
endlocal
''', encoding="utf-8")

# ---- 5) instructions for the colleague ----
(OUT / "给同事的说明.txt").write_text(f'''桌面隐翅虫 · 联机包
==============================

这是一个桌面宠物。连上后，你能在我屏幕上的同一时刻，
看到一只和我并排的远程虫子。三步即可：

【第 1 步】装 Tailscale
   https://tailscale.com/download  （Windows 版）
   装完用我给你的账号密码登录，看到列表里出现
   你的电脑 + 我的电脑，就是通了。

【第 2 步】装 Python（只需一次）
   https://www.python.org/downloads/
   ⚠ 安装界面第一屏务必勾选 "Add python.exe to PATH"，
     然后点 Install Now。
   装完打开 PowerShell，执行一次：
       pip install PyQt5 Pillow websockets

【第 3 步】双击本文件夹里的  启动.bat

桌面上就会出现一只隐翅虫。
------------------------------
右键点虫子 → 联机：加入房间 → 房间码填  {ROOM}  → 确定

然后我的屏幕上就会出现你的虫。
把虫拖到左边食盆喂饭、中间训练环训练、右边草窝睡觉，
三项数值都喂满后，就能联机交配、生虫卵、孵小虫。

房间码：{ROOM}
我的联机地址：ws://{HOST_IP}:8765
''', encoding="utf-8")

total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
files = [str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()]
print(f"built: {OUT}")
print(f"files: {len(files)}")
print(f"size : {total/1024/1024:.1f} MB  (was 68 MB)")
for f in sorted(files):
    print("  -", f)
