"""Verify the exe inside the release package was built from the CURRENT source.

    python check_exe_version.py [path-to-桌面隐翅虫-壁纸联机包.zip]

Why this exists
---------------
A published zip whose exe predates the last commit is an easy, invisible
mistake: the zip looks fresh, the size is plausible, and the app runs -- it
just quietly ships old behaviour.  (This project's v1.0 asset was exactly
that: the adult redraw never reached the colleague, because the exe inside
the zip had been built before the redraw.)

How it works
------------
Every build stamps `dist/build_info.json`, which build_full_pkg.py ships
inside the package, with:

  * the SHA-256 of every repo file the build consumes -- `src/room_overlay.py`
    plus the sprites; the list lives in build_inputs.py so the build and
    this check can never disagree about what "the current source" means;
  * the SHA-256 of the build scripts themselves;
  * the SHA-256 and size of the finished exe.

This script then:

  1. recomputes the repo / script hashes and compares them against the
     recorded ones  -> "did the source move after the build?" (stale exe);
  2. hashes the exe bytes inside the zip  -> "is this really the exe that
     build produced?" (swapped or hand-edited package).

Exit status is non-zero on any mismatch.

The first version of this script compared the string constants of the repo
source against the packaged exe.  That can never pass: build_guest_pkg.py
deliberately patches the copy that gets packaged (fog loader accepts .jpg,
relay default substituted), so the two differ by construction and the check
reported a permanent false "stale".  Comparing against the build's own
recorded fingerprint is the only comparison that can be true.
"""
import hashlib
import json
import os
import sys
import zipfile

from build_inputs import repo_fingerprint, script_fingerprint

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ZIP = os.path.join(os.path.dirname(HERE), "桌面隐翅虫-壁纸联机包.zip")


def find_in_zip(z, suffix):
    """The single zip entry whose name ends with `suffix`, or None."""
    hits = [n for n in z.namelist() if n.endswith(suffix)]
    return hits[0] if hits else None


def compare_hashes(label, now, then):
    """Diff two {relpath: sha256} dicts; return True when identical."""
    if not then:
        print(f"  [FAIL] the fingerprint records no {label} hashes")
        return False
    ok = True
    for rel in sorted(set(now) | set(then)):
        a, b = then.get(rel), now.get(rel)
        if a == b:
            continue
        if b is None:
            what = "was removed"
        elif a is None:
            what = "was added"
        else:
            what = "changed"
        print(f"   [FAIL] {label}: {rel} {what} since the build")
        ok = False
    return ok


def main():
    zp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    print("checking:", zp)
    ok = True

    with zipfile.ZipFile(zp) as z:
        # ---- 1) the fingerprint must travel with the package ----
        bi = find_in_zip(z, "build_info.json")
        if bi is None:
            print("  [FAIL] build_info.json is not inside the zip.")
            print("         The package predates the fingerprint -- rebuild it "
                  "with build_full_pkg.py before publishing.")
            return 1
        info = json.loads(z.read(bi).decode("utf-8"))
        print(f"  built at        : {info.get('built_at')}"
              f"  (python {info.get('python')})")
        baked = info.get("relay_url")
        print(f"  relay url baked : {baked}"
              + ("   <-- the REAL address; check_pkg_clean.py must pass too"
                 if info.get("bake_real_ip") else "   (placeholder)"))

        # ---- 2) did the source move after the build? ----
        try:
            now_repo = repo_fingerprint()
        except OSError as e:
            print(f"  [FAIL] cannot hash the repo inputs: {e}")
            return 1
        ok &= compare_hashes("repo input", now_repo, info.get("repo") or {})
        print(f"  repo inputs     : {len(now_repo)} file(s) verified")

        try:
            now_scr = script_fingerprint()
        except OSError as e:
            print(f"  [FAIL] cannot hash the build scripts: {e}")
            return 1
        ok &= compare_hashes("build script", now_scr, info.get("scripts") or {})
        print(f"  build scripts   : {len(now_scr)} file(s) verified")

        # ---- 3) is this the exe that build produced? ----
        exe_name = find_in_zip(z, ".exe")
        if exe_name is None:
            print("  [FAIL] no exe inside the zip")
            ok = False
        else:
            blob = z.read(exe_name)
            found = hashlib.sha256(blob).hexdigest()
            recorded = info.get("exe_sha256")
            rec_size = info.get("exe_size")
            rec_size = f"{rec_size:,}" if isinstance(rec_size, int) else "?"
            print(f"  exe             : {exe_name}  {len(blob):,} bytes")
            if not recorded:
                print("  [FAIL] the fingerprint records no exe hash")
                ok = False
            elif found == recorded:
                print("  exe             : byte-identical to the build output")
            else:
                print("  [FAIL] the exe in the zip is NOT the one that build "
                      "produced:")
                print(f"         recorded {recorded[:16]}..  ({rec_size} bytes)")
                print(f"         found    {found[:16]}..  ({len(blob):,} bytes)")
                ok = False

    if ok:
        print("  -> UP TO DATE: the packaged exe matches the current source")
        return 0
    print("  -> STALE / MISMATCHED")
    print("     fix: run build_full_pkg.bat again so the exe matches the "
          "current source,")
    print("          then re-run this check before publishing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
