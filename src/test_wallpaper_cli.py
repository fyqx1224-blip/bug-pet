"""Headless test for the wallpaper CLI (backup / restore only -- never applies).

_reg_apply_wallpaper is monkeypatched so the real desktop is untouched.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
os.environ.pop("BUG_RELAY_URL", None)
os.environ["BUG_SAVE"] = os.path.join(tempfile.mkdtemp(), "save.json")

import pyqt_stub  # noqa: F401
import room_overlay as R

TMP = tempfile.mkdtemp()

# ---- 0) stub out the actual desktop mutation ----
applied = []
R._reg_apply_wallpaper = lambda p: applied.append(p) or True

# ---- 1) registry read works (read-only, real registry on Windows) ----
cur = R._reg_read_wallpaper()
print("[1] current wallpaper in registry ->", repr(cur)[:80])

# ---- 2) backup is written once, and a 2nd run must NOT overwrite it ----
bak = os.path.join(TMP, "备份-原壁纸.txt")
R._backup_wallpaper(bak)
first = open(bak, encoding="utf-8").read().strip()
print("[2] backup #1                    ->", repr(first)[:80])

# poison the backup with a fake value, then "run again" -- it must survive
with open(bak, "w", encoding="utf-8") as f:
    f.write("C:\\FAKE\\她原来的壁纸.jpg\n")
R._backup_wallpaper(bak)
second = open(bak, encoding="utf-8").read().strip()
assert second == "C:\\FAKE\\她原来的壁纸.jpg", "backup was overwritten!"
print("[3] backup kept after re-run     ->", second)

# ---- 4) restore with a missing file -> False, no crash ----
ok = R._restore_wallpaper(os.path.join(TMP, "不存在的备份.txt"))
print("[4] restore, no backup file      ->", ok)
assert ok is False

# ---- 5) restore with an empty backup -> False ----
with open(bak, "w", encoding="utf-8") as f:
    f.write("\n")
ok = R._restore_wallpaper(bak)
print("[5] restore, empty backup        ->", ok)
assert ok is False

# ---- 6) restore with a backup pointing at a deleted file -> False ----
with open(bak, "w", encoding="utf-8") as f:
    f.write("C:\\不存在的路径\\x.jpg\n")
ok = R._restore_wallpaper(bak)
print("[6] restore, file gone from disk ->", ok)
assert ok is False

# ---- 7) restore with a real existing file -> applies it ----
real = os.path.join(TMP, "她原来的壁纸.jpg")
open(real, "w").write("x")
with open(bak, "w", encoding="utf-8") as f:
    f.write(real + "\n")
ok = R._restore_wallpaper(bak)
print("[7] restore, real file           ->", ok, "| applied:", applied)
assert ok is True and applied[-1] == real

# ---- 8) argument dispatch maps to the right helper ----
seen = {}
R._backup_wallpaper = lambda p: seen.__setitem__("backup", p)
orig_apply = R._reg_apply_wallpaper
R._reg_apply_wallpaper = lambda p: (seen.__setitem__("apply", p), True)[1]
wp = os.path.join(TMP, "房间壁纸.jpg")
open(wp, "w").write("x")
argv = ["--with-wallpaper", wp, os.path.join(TMP, "b2.txt")]
# replay the same dispatch main() performs
if argv[0] == "--with-wallpaper" and len(argv) >= 2:
    _wp, _bak = argv[1], argv[2]
    if os.path.isfile(_wp):
        R._backup_wallpaper(_bak)
        R._reg_apply_wallpaper(_wp)
print("[8] --with-wallpaper dispatch    ->", seen)
assert seen["backup"].endswith("b2.txt") and seen["apply"] == wp

# missing wallpaper file -> no backup, no apply, still falls through
seen.clear()
argv = ["--with-wallpaper", os.path.join(TMP, "没有这张.jpg"), os.path.join(TMP, "b3.txt")]
if argv[0] == "--with-wallpaper" and len(argv) >= 2:
    _wp, _bak = argv[1], argv[2]
    if os.path.isfile(_wp):
        R._backup_wallpaper(_bak)
        R._reg_apply_wallpaper(_wp)
print("[9] missing wallpaper file       ->", seen, "(falls through to launch)")
assert seen == {}

print("\nALL WALLPAPER-CLI CHECKS PASSED")
