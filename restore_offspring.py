"""Put the offspring back to a chosen stage in the LIVE save.

The player's 成长期 offspring was overwritten by a test run that wrote to the
real save file (see src/_testenv.py).  This tool restores it.

    python restore_offspring.py                 # -> 成长期, just entered
    python restore_offspring.py GROWTH 0.5      # -> 成长期, half way
    python restore_offspring.py ADULT           # -> 成年期 (done)
    python restore_offspring.py --show          # just print the current state

The pet must be CLOSED, otherwise its 20 s autosave overwrites us.  The script
verifies that by watching the file for a few seconds before touching anything.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

import room_overlay as R  # noqa: E402

ORDER = R.Offspring.ORDER
NAMES = R.Offspring.NAMES
SAVE = R._save_path()


def describe(d):
    o = (d or {}).get("offspring")
    if not o:
        return "没有后代"
    st = o.get("stage")
    name = NAMES.get(st, st)
    dur = R.Offspring.DURATIONS.get(st)
    if dur and dur != float("inf"):
        pct = 100.0 * float(o.get("t", 0.0)) / dur
        return "%s（%s，进度 %.1f%%）" % (name, st, pct)
    return "%s（%s）" % (name, st)


def main():
    args = [a for a in sys.argv[1:] if a != "--show"]
    show_only = "--show" in sys.argv[1:]

    print("存档：", SAVE)
    if not SAVE.exists():
        print("！！找不到存档，先启动一次宠物再关掉。")
        return 1
    with open(SAVE, "r", encoding="utf-8") as f:
        before = json.load(f)
    print("当前：", describe(before))
    if show_only:
        return 0

    stage = (args[0] if args else "GROWTH").upper()
    if stage not in NAMES:
        print("！！阶段只能是：", "、".join(ORDER))
        return 1
    frac = 0.0
    if len(args) > 1:
        try:
            frac = max(0.0, min(1.0, float(args[1])))
        except ValueError:
            print("！！进度要写 0~1 的小数")
            return 1

    # ---- liveness: a running pet rewrites the file every 20 s ----
    m1 = SAVE.stat().st_mtime
    time.sleep(3.0)
    m2 = SAVE.stat().st_mtime
    if m2 != m1:
        print("！！宠物正在运行（存档刚被自动保存改写）。")
        print("   请先关掉虫子（右键退出 / 关掉那个窗口），再重跑本脚本。")
        return 1

    idx = ORDER.index(stage)
    dur = R.Offspring.DURATIONS[stage]
    t = 0.0 if dur == float("inf") else dur * frac

    bak = SAVE.with_suffix(".json.before-restore")
    shutil.copyfile(SAVE, bak)

    d = before
    d["offspring"] = {"stage": stage, "idx": idx, "t": t,
                      "done": stage == R.Offspring.STAGE_ADULT}
    d["ts"] = time.time()
    tmp = SAVE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SAVE)

    with open(SAVE, "r", encoding="utf-8") as f:
        after = json.load(f)
    print("已改：", describe(after))
    print("原存档已备份到：", bak.name)
    print("\n现在重开宠物即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
