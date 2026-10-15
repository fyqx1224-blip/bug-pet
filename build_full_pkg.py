"""Build the 壁纸联机包: exe + room wallpaper + one-click apply + readme.

Run on your own machine (needs Python + PyQt5):
    双击 build_full_pkg.bat

Produces:
    桌面隐翅虫-壁纸联机包.zip     <- send THIS to her

Package contents:
    桌面隐翅虫.exe
    relay.txt                        relay address (editable if the IP changes)
    房间壁纸.jpg                      the room wallpaper (re-encoded, ~3 MB)
    备份-原壁纸.txt                   HER original wallpaper, saved on first run
    双击我-开始玩.bat                 backup + apply wallpaper + launch the pet
    恢复我原来的壁纸.bat              puts her wallpaper back
    README.txt
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PKG = ROOT.parent / "壁纸联机包"
WP_PNG = ROOT / "wallpaper" / "bug_room_wallpaper_1920x1080.png"


def main():
    # ---- 1) build the exe (also refreshes the slim package) ----
    print("[pkg] building exe ...")
    subprocess.run([sys.executable, str(ROOT / "build_exe.py")], check=True)

    exe = DIST / "桌面隐翅虫.exe"
    if not exe.exists():
        print("[pkg] !! build_exe.py did not produce the exe")
        sys.exit(1)

    # ---- 2) stage the package ----
    # NOTE: plain unlink instead of shutil.rmtree -- some environments
    # intercept rmtree and force a recycle-bin move, which can fail.
    if PKG.exists():
        for root, dirs, files in os.walk(PKG, topdown=False):
            for name in files:
                os.unlink(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
    PKG.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, PKG / "桌面隐翅虫.exe")

    # NOTE: do NOT copy dist/relay.txt here. net_relay.py writes the machine's
    # REAL Tailscale address into it, and this package is published publicly, so
    # shipping it would leak the host's private network address. Ship a
    # placeholder instead; the host hands the real ws://... address over
    # out-of-band (WeChat etc.) and the recipient pastes it in.
    (PKG / "relay.txt").write_text(
        "# 中继地址。改成房主发给你的那个（形如 ws://100.x.y.z:8765），保存后重开。\n"
        "ws://100.64.0.1:8765\n", encoding="utf-8")

    # wallpaper: PNG (2.8 MB) -> JPG q92 (smaller, and Windows accepts .jpg)
    print("[pkg] re-encoding wallpaper ...")
    im = Image.open(WP_PNG).convert("RGB")
    im.save(PKG / "房间壁纸.jpg", quality=92, optimize=True)
    print(f"[pkg] wallpaper: {WP_PNG.name} "
          f"{WP_PNG.stat().st_size/1024/1024:.1f} MB -> jpg "
          f"{(PKG / '房间壁纸.jpg').stat().st_size/1024/1024:.1f} MB")

    # ---- 3) launchers ----
    (PKG / "双击我-开始玩.bat").write_text('''@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
echo 正在布置饲养房间 ...
"%~dp0桌面隐翅虫.exe" --with-wallpaper "%~dp0房间壁纸.jpg" "%~dp0备份-原壁纸.txt"
endlocal
''', encoding="utf-8")

    (PKG / "恢复我原来的壁纸.bat").write_text('''@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
"%~dp0桌面隐翅虫.exe" --restore-wallpaper "%~dp0备份-原壁纸.txt"
echo.
echo 已尝试恢复你原来的壁纸。按任意键关闭。
pause >nul
''', encoding="utf-8")

    # ---- 4) readme ----
    # first non-comment line of relay.txt (it may start with a # hint line)
    url = next((ln.strip() for ln in
                (PKG / "relay.txt").read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")), "")
    (PKG / "README.txt").write_text(f'''桌面隐翅虫 · 壁纸联机包
==================================================
给完全不懂电脑的人准备的版本：不用装 Python、不用装任何东西。
解开 zip 后，整个文件夹随便放哪（建议放桌面），然后只干一件事——
双击  双击我-开始玩.bat


一、点完之后会发生什么
--------------------------------------------------
1. 你现在的壁纸会被自动备份到  备份-原壁纸.txt
2. 桌面换成「隐翅虫饲养房间」壁纸
3. 隐翅虫出现在桌面上，开始散步

那个房间壁纸不是摆设：食盆、睡窝、训练区都画在上面，
虫子是靠这些位置来判定"吃饭/睡觉/训练"的。


二、怎么玩
--------------------------------------------------
· 左键按住虫子可以随便拖着玩，松手它自己走
· 双击它，它会飞一圈
· 右键点虫子有菜单：去吃饭 / 去睡觉 / 去训练 / 让它飞一下
· 把虫子拖到壁纸上的 食盆 / 睡窝 / 训练环 也能触发同样的事
· 左上角三条是 饱 / 能 / 悦，会随时间下降，喂饭睡觉训练能补
· 按 F1 看帮助，Esc 退出
· 桌上那盏叶子灯：点一下玻璃房里会起雾，再点一下雾散掉


三、和我联机（关键）
--------------------------------------------------
前提：我们已经装好 Tailscale 并登录了同一个账号
（你在 Tailscale 列表里能看到我的设备名就行）。

右键点虫子 → 联机：加入房间 → 房间码填房主发给你的那个 → 确定

我的屏幕上就会出现你的虫，你屏幕上也会看到我的。
两只虫都喂满（三条满格）之后，就能一起交配、生虫卵、
虫卵会经过 卵期 → 孵化后期 → 幼年期 → 成长期 → 成年期 慢慢长大。
关掉程序再打开，进度会自动接着走，不会从头开始。

房间码：见房主发你的消息
联机地址：{url}      ← 这是占位地址，请换成房主发给你的那个


四、连不上怎么办
--------------------------------------------------
多半是房主的 Tailscale IP 变了。用记事本打开本文件夹里的
relay.txt，把里面那行换成房主新发给你的地址（形如
ws://100.x.y.z:8765），保存后重开。

或者在"加入房间"的输入框里，直接粘贴房主发给你的完整地址。


五、不想要这个壁纸了
--------------------------------------------------
双击  恢复我原来的壁纸.bat
你原来的壁纸就回来了（第一次启动时自动备份过）。
如果那张原图已经被你删了/移动了，会恢复失败——那种情况
就在桌面上右键 → 个性化 → 背景 里自己选一张。

虫子本体：右键 → 退出。壁纸不会被动。


六、杀毒软件报警？
--------------------------------------------------
点"允许运行 / 仍要运行"即可。程序没做任何奇怪的事，
只是需要读写自己文件夹里的 备份-原壁纸.txt 和存档。


附：快捷键
--------------------------------------------------
F1   帮助开关
Esc  退出
''', encoding="utf-8")

    # ---- 5) zip ----
    zip_path = ROOT.parent / "桌面隐翅虫-壁纸联机包.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PKG.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(PKG.parent))

    size = zip_path.stat().st_size / 1024 / 1024
    print()
    print("=" * 58)
    print("[pkg] DONE")
    print(f"[pkg] folder : {PKG}")
    print(f"[pkg] zip    : {zip_path}  ({size:.1f} MB)")
    print("[pkg] she only needs to unzip + 双击 双击我-开始玩.bat")
    print("=" * 58)


if __name__ == "__main__":
    main()
