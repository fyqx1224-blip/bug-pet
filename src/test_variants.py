"""Blind-box variant engine + reveal-show tests.

    python test_variants.py

Engine areas (pure python, no Qt):
  1. table integrity: weights sum to 100, every id known, defaults consistent
  2. seeded determinism + the roll matches the target distribution
     (morph 40/20/15/10/8/4/2/0.6/0.4, rarity 75/18/6/1)
  3. palettes: classic IS the parent BASE, all 9 distinct and in gamut,
     white morph light / black-gold dark
  4. sanitize_genes: old saves (no genes / garbage) fall back PER FIELD and
     never crash; a valid record round-trips through JSON unchanged
  5. dex accumulation: count, best_pattern (by rank), best_size (by scale),
     first_at, and the 9-cell collection wall

Qt areas (offscreen; skipped when PyQt5 is unavailable):
  6. the reveal state machine: four beats, life-clock pause, click-to-skip,
     fires exactly once per clutch, given genes are never re-rolled
  7. draw smoke test: every morph renders, the reveal egg renders in all
     four phases, the hidden-tier flash lights the canvas, and the size
     axis actually changes the drawn body
"""
import json
import os
import random
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _testenv  # noqa: E402,F401  (never touch the player's live save)

import variants as V  # noqa: E402

ok = True


def check(label, cond):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    ok = ok and bool(cond)


# ===========================================================================
# 1) table integrity
# ===========================================================================
print("== 1) weighted tables ==")
check("9 morphs, weights sum to 100",
      len(V.MORPHS) == 9 and abs(sum(m["weight"] for m in V.MORPHS) - 100) < 1e-9)
check("4 patterns, weights sum to 100",
      len(V.PATTERNS) == 4 and abs(sum(p["weight"] for p in V.PATTERNS) - 100) < 1e-9)
check("5 sizes, weights sum to 100",
      len(V.SIZES) == 5 and abs(sum(s["weight"] for s in V.SIZES) - 100) < 1e-9)
check("every morph rarity is a known tier",
      all(m["rarity"] in V.RARITIES for m in V.MORPHS))
check("morph ids unique", len({m["id"] for m in V.MORPHS}) == 9)
check("pattern ids + ranks unique",
      len({p["id"] for p in V.PATTERNS}) == 4
      and len({p["rank"] for p in V.PATTERNS}) == 4)
check("size ids unique, scales strictly increasing",
      len({s["id"] for s in V.SIZES}) == 5
      and [s["scale"] for s in V.SIZES] == sorted(s["scale"] for s in V.SIZES))
check("DEFAULT_GENES matches the common defaults",
      V.DEFAULT_GENES == {"morph": "classic", "pattern": "plain",
                          "size": "normal", "rarity": "common"})
check("rarity recover_mult monotone 1.0/1.1/1.2/1.35",
      [V.RARITIES[k]["recover_mult"] for k in
       ("common", "uncommon", "rare", "hidden")] == [1.0, 1.1, 1.2, 1.35])
check("rarity colours are hex strings",
      all(isinstance(t["color"], str) and t["color"].startswith("#")
          for t in V.RARITIES.values()))

# ===========================================================================
# 2) the roll: determinism + distribution
# ===========================================================================
print("== 2) roll distribution (200k rolls, seed 1234) ==")
N = 200000
rng = random.Random(1234)
rolls = [V.roll_variant(rng) for _ in range(N)]


def pct(rows, key, val):
    return 100.0 * sum(1 for r in rows if r[key] == val) / N


TOL = 1.0
for m in V.MORPHS:
    got = pct(rolls, "morph", m["id"])
    check(f"morph {m['id']:<10} {got:5.2f}%  (target {m['weight']}%)",
          abs(got - m["weight"]) <= TOL)
for p in V.PATTERNS:
    got = pct(rolls, "pattern", p["id"])
    check(f"pattern {p['id']:<10} {got:5.2f}%  (target {p['weight']}%)",
          abs(got - p["weight"]) <= TOL)
for s in V.SIZES:
    got = pct(rolls, "size", s["id"])
    check(f"size {s['id']:<10} {got:5.2f}%  (target {s['weight']}%)",
          abs(got - s["weight"]) <= TOL)
for tier in ("common", "uncommon", "rare", "hidden"):
    target = sum(m["weight"] for m in V.MORPHS if m["rarity"] == tier)
    got = pct(rolls, "rarity", tier)
    check(f"rarity {tier:<10} {got:5.2f}%  (target {target}%)",
          abs(got - target) <= TOL)

a = [V.roll_variant(random.Random(7)) for _ in range(50)]
b = [V.roll_variant(random.Random(7)) for _ in range(50)]
c = [V.roll_variant(random.Random(8)) for _ in range(50)]
check("same seed -> identical rolls", a == b)
check("different seed -> different rolls", a != c)
check("roll_variant() with no rng still returns a valid record",
      all(r["morph"] in V.MORPH_BY_ID and r["pattern"] in V.PATTERN_BY_ID
          and r["size"] in V.SIZE_BY_ID
          and r["rarity"] == V.MORPH_BY_ID[r["morph"]]["rarity"]
          for r in (V.roll_variant() for _ in range(200))))

# ===========================================================================
# 3) palettes
# ===========================================================================
print("== 3) palettes ==")


def lum(pal):
    return sum(sum(c) for c in pal.values()) / (3.0 * len(pal))


def in_gamut(pal):
    return all(isinstance(v, int) and 0 <= v <= 255
               for c in pal.values() for v in c)


check("classic palette is the untouched parent BASE",
      V.palette_for({"morph": "classic"}) == V.BASE)
check("every palette covers the 9 parent keys",
      all(set(m["palette"]) == set(V.BASE) for m in V.MORPHS))
check("every palette is integer rgb in 0..255",
      all(in_gamut(m["palette"]) for m in V.MORPHS))
pals = {m["id"]: tuple(sorted(m["palette"].items())) for m in V.MORPHS}
check("all 9 palettes pairwise distinct", len(set(pals.values())) == 9)
check("white morph is much lighter than the parent",
      lum(V.palette_for({"morph": "albino"})) > lum(V.BASE) + 20)
check("black-gold is much darker than the parent",
      lum(V.palette_for({"morph": "blackgold"})) < lum(V.BASE) - 15)
check("unknown morph falls back to the parent look",
      V.palette_for({"morph": "nope"}) == V.BASE)
check("is_light_morph true only for the white morph",
      V.is_light_morph({"morph": "albino"})
      and not V.is_light_morph({"morph": "classic"}))

# ===========================================================================
# 4) sanitize_genes (old-save migration)
# ===========================================================================
print("== 4) old-save migration ==")
d, o = V.sanitize_genes(None)
check("None -> parent look, repaired", d == V.DEFAULT_GENES and not o)
for junk in ("x", 42, [], 3.5, True):
    d, o = V.sanitize_genes(junk)
    check(f"junk {junk!r} -> parent look", d == V.DEFAULT_GENES and not o)
d, o = V.sanitize_genes({})
check("empty dict -> parent look, repaired", d == V.DEFAULT_GENES and not o)
d, o = V.sanitize_genes({"morph": "unicorn", "pattern": "bands", "size": "huge"})
check("unknown morph repaired per field, valid fields kept",
      d == {"morph": "classic", "pattern": "bands", "size": "huge",
            "rarity": "common"} and not o)
d, o = V.sanitize_genes({"morph": "albino"})
check("rare morph kept, rarity recomputed to hidden",
      d["morph"] == "albino" and d["rarity"] == "hidden"
      and d["pattern"] == "plain" and d["size"] == "normal" and not o)
d, o = V.sanitize_genes({"morph": "violet", "pattern": "spots", "size": "small"})
check("valid record untouched",
      d == {"morph": "violet", "pattern": "spots", "size": "small",
            "rarity": "rare"} and o)
check("tampered rarity is recomputed from the morph",
      V.sanitize_genes({"morph": "classic", "rarity": "hidden"})[0]["rarity"]
      == "common")
# the save format is plain JSON: roll -> dump -> load -> sanitize -> identical
g = {"morph": "blackgold", "pattern": "dark_head", "size": "huge",
     "rarity": "hidden"}
g2, o = V.sanitize_genes(json.loads(json.dumps(g)))
check("genes round-trip through JSON unchanged", g2 == g and o)

# ===========================================================================
# 5) dex accumulation
# ===========================================================================
print("== 5) dex ==")
first_at = time.time()
dex = V.dex_update({}, {"morph": "violet", "pattern": "plain",
                        "size": "normal", "rarity": "rare"})
e = dex["violet"]
check("first opening: count 1, first_at set",
      e["count"] == 1 and e["first_at"] >= first_at - 5)
check("first opening: best = rolled pattern/size",
      e["best_pattern"] == "plain" and e["best_size"] == "normal")

dex = V.dex_update(dex, {"morph": "violet", "pattern": "dark_head",
                         "size": "huge", "rarity": "rare"})
e = dex["violet"]
check("second opening: count 2, first_at kept",
      e["count"] == 2 and abs(e["first_at"] - first_at) < 5)
check("best_pattern upgrades by rank", e["best_pattern"] == "dark_head")
check("best_size upgrades by scale", e["best_size"] == "huge")

dex = V.dex_update(dex, {"morph": "violet", "pattern": "plain",
                         "size": "small", "rarity": "rare"})
e = dex["violet"]
check("plainer/smaller later opening never downgrades the best",
      e["best_pattern"] == "dark_head" and e["best_size"] == "huge")
check("dex_update works on a non-dict dex", V.dex_update(None, g)["blackgold"]["count"] == 1)

rows = V.dex_lines(dex)
check("9 rows on the collection wall", len(rows) == 9)
check("unopened morph shows ???", any("???（未开出）" in r for r in rows))
check("opened morph shows count + best",
      any("紫罗兰" in r and "已开出 3 次" in r and "异色头" in r and "大只" in r
          for r in rows))
rows2 = V.dex_lines({"ghost_morph": {"count": 5}})
check("unknown dex id ignored by the wall",
      len(rows2) == 9 and all("ghost" not in r for r in rows2))
check("dex_lines survives a non-dict dex",
      len(V.dex_lines("garbage")) == 9)

# ===========================================================================
# 6) reveal state machine + 7) draw smoke test (need Qt)
# ===========================================================================
have_qt = True
try:
    from PyQt5.QtWidgets import QApplication          # noqa: E402
    from PyQt5.QtGui import QImage, QPainter, QFont   # noqa: E402
    from PyQt5.QtCore import Qt                       # noqa: E402
    import room_overlay as R                          # noqa: E402
except Exception as exc:                              # noqa: BLE001
    have_qt = False
    print("== 6/7) skipped: PyQt5 unavailable (%s) ==" % exc)

if have_qt:
    app = QApplication(sys.argv)
    O = R.Offspring

    # ---- 6) state machine ------------------------------------------------
    print("== 6) reveal state machine ==")
    genes = {"morph": "violet", "pattern": "spots", "size": "larger",
             "rarity": "rare"}
    off = O(genes=genes)
    check("given genes are kept (no re-roll)", off.genes == genes)
    check("fresh egg is secret",
          not off.revealed and off.reveal is None
          and off.reveal_phase() is None)

    ev = off.tick(O.DURATIONS[O.STAGE_EGG])
    check("egg period elapses -> hatch, no event yet",
          ev is None and off.stage == O.STAGE_HATCH)
    ev = off.tick(O.DURATIONS[O.STAGE_HATCH])
    check("hatch completes -> reveal_start",
          ev == "reveal_start" and off.reveal is not None and off.revealed
          and off.stage == O.STAGE_LARVA)

    t_at_start = off.t
    for _ in range(2):
        off.tick(1.0)
    check("life clock is PAUSED during the show",
          off.t == t_at_start and off.reveal is not None
          and off.stage == O.STAGE_LARVA and off.reveal["t"] == 2.0)

    off.reveal["t"] = 0.0
    check("beat 1: shake", off.reveal_phase() == "shake")
    off.reveal["t"] = O.REVEAL_SHAKE
    check("beat 2: crack", off.reveal_phase() == "crack")
    off.reveal["t"] = O.REVEAL_CRACK
    check("beat 3: flash", off.reveal_phase() == "flash")
    off.reveal["t"] = O.REVEAL_FLASH
    check("beat 4: banner", off.reveal_phase() == "banner")
    check("reveal banner text carries the variant",
          "稀有" in off.reveal["banner"] and "紫罗兰" in off.reveal["banner"])

    ev = off.skip_reveal()
    check("click-to-skip ends the show now",
          ev == "reveal_end" and off.reveal is None)
    check("skip with no show returns None", off.skip_reveal() is None)

    off2 = O(genes=genes)
    off2.tick(O.DURATIONS[O.STAGE_EGG])
    off2.tick(O.DURATIONS[O.STAGE_HATCH])
    seen = [off2.tick(dt) for dt in (0.5, 0.2, 0.5, 1.0, 0.9)]
    check("natural run: one reveal_start, then reveal_end at ~3 s",
          seen == [None, None, None, None, "reveal_end"])
    check("life clock resumes after the show", off2.t == 0.0)

    evs = []
    n_ticks = int(O.DURATIONS[O.STAGE_LARVA] / 0.25) + 2
    for _ in range(n_ticks):
        e = off2.tick(0.25)
        if e:
            evs.append(e)
    check("reveal fires exactly once per clutch",
          "reveal_start" not in evs and off2.stage == O.STAGE_GROWTH)

    # ---- 7) draw smoke test ----------------------------------------------
    print("== 7) draw smoke test (offscreen) ==")
    CW, CH = 220, 160

    def canvas():
        img = QImage(CW, CH, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        return img, p

    def painted(img, step=2):
        n = 0
        for y in range(0, img.height(), step):
            for x in range(0, img.width(), step):
                if img.pixelColor(x, y).alpha() > 24:
                    n += 1
        return n

    def diff_pixels(a, b):
        n = 0
        for y in range(a.height()):
            for x in range(a.width()):
                if a.pixel(x, y) != b.pixel(x, y):
                    n += 1
        return n

    def render_adult(genes):
        img, p = canvas()
        o = O(genes=genes)
        o.idx = len(O.ORDER) - 1
        o.stage = O.STAGE_ADULT
        o.done = True
        o.draw_in_nest(p, CW / 2, CH / 2)
        p.end()
        return img

    def render_reveal(genes, t):
        img, p = canvas()
        o = O(genes=genes)
        o.stage = O.STAGE_LARVA
        o.idx = O.ORDER.index(O.STAGE_LARVA)
        o._start_reveal()
        o.reveal["t"] = t
        o.draw_in_nest(p, CW / 2, CH / 2)
        o.draw_reveal_flash(p, CW, CH)
        p.end()
        return img

    def genes_for(mid, pattern="spots", size="normal"):
        return {"morph": mid, "pattern": pattern, "size": size,
                "rarity": V.MORPH_BY_ID[mid]["rarity"]}

    for m in V.MORPHS:
        try:
            img = render_adult(genes_for(m["id"]))
            n = painted(img)
        except Exception as exc:                       # noqa: BLE001
            print("   exception:", exc)
            n = 0
        check(f"adult renders: {m['name']} ({n} px)", n > 50)

    g_classic = genes_for("classic")
    g_albino = genes_for("albino")
    g_violet = genes_for("violet")
    check("classic vs 白化 render differently",
          diff_pixels(render_adult(g_classic), render_adult(g_albino)) > 500)
    check("classic vs 紫罗兰 render differently",
          diff_pixels(render_adult(g_classic), render_adult(g_violet)) > 500)

    n_small = painted(render_adult(genes_for("classic", size="small")))
    n_huge = painted(render_adult(genes_for("classic", size="huge")))
    check(f"size axis scales the drawn body ({n_small} -> {n_huge} px)",
          n_huge > n_small * 1.3)

    for label, t in (("shake", 0.3), ("crack", 0.9),
                     ("flash", 1.7), ("banner", 2.5)):
        try:
            img = render_reveal(g_albino, t)
            n = painted(img)
        except Exception as exc:                       # noqa: BLE001
            print("   exception:", exc)
            n = 0
        check(f"reveal egg renders in the {label} phase ({n} px)", n > 20)

    img_flash = render_reveal(g_albino, 1.7)
    check("hidden-tier flash lights the whole canvas",
          painted(img_flash) > 500)
    img_noflash = render_reveal(g_violet, 1.7)
    check("non-hidden tier does not flash the canvas",
          painted(img_noflash) < painted(img_flash))

print()
print("ALL VARIANT TESTS PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
