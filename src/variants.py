"""Offspring blind-box variant engine.

Three random axes, rolled when the egg is laid and persisted with the save:

    morph    9 curated palettes, all derived from the PARENT's sampled
             colours (the 40% classic is the "looks like mum and dad" floor)
    pattern  4 vector overlays (plain / elytra spots / deep bands / dark head)
    size     5 scale steps (0.85 .. 1.20 of the adult body)

Rarity comes from the morph tier and multiplies RECOVERY RATE only
(上限与衰减速度不变):

    普通 75%  x1.00
    少见 18%  x1.10
    稀有  6%  x1.20
    隐藏  1%  x1.35   (白化 / 黑金)

Two deliberate choices, both learned the hard way on this project:

  * morphs are PRESET palette shifts, not random hues.  A uniform random
    hue produces mostly muddy browns and loses the family resemblance;
    every palette here is the parent palette rotated in HSV space, so the
    internal contrast structure (dark elytra hump, banded abdomen, black
    tail) survives and the beetle still reads as a rove beetle.

  * the roll takes an explicit `random.Random` instance, never the global
    RNG, so a test can pin a seed and assert the distribution, and so the
    draw can never be perturbed by whatever else consumed global entropy.

Pure data + pure python (no Qt): palettes are (r, g, b) tuples and
room_overlay.py wraps them in QColor at draw time.
"""
import colorsys
import random
import time

# ---------------------------------------------------------------------------
# The parent palette, sampled from sprites/walk_right.png (see _draw_beetle).
# ---------------------------------------------------------------------------
BASE = {
    "head_c": (198, 60, 34),
    "pro_c":  (184, 48, 28),
    "abdo_c": (214, 92, 46),
    "band_c": (146, 44, 20),
    "black":  (38, 33, 30),
    "eye_c":  (22, 18, 16),
    "leg_hi": (202, 100, 48),
    "leg_lo": (46, 40, 35),
    "rim":    (118, 30, 16),
}


def _shift(rgb, dh=0.0, ds=1.0, dl=1.0):
    """Rotate hue by `dh` turns, scale saturation and lightness.

    Keeps the colour's own structure: a dark part stays dark relative to a
    light part, which is exactly what a preset needs to survive."""
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + dh) % 1.0
    s = min(1.0, s * ds)
    v = min(1.0, v * dl)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def _palette(dh=0.0, ds=1.0, dl=1.0):
    """The whole parent palette, shifted by one transform."""
    return {k: _shift(c, dh, ds, dl) for k, c in BASE.items()}


# ---------------------------------------------------------------------------
# Morphs (体色).  weight sums to 100.  rarity tier drives the recovery mult.
# ---------------------------------------------------------------------------
MORPHS = [
    dict(id="classic",   name="经典红褐", rarity="common",   weight=40,
         palette=_palette()),
    dict(id="sienna",    name="暗赭",     rarity="common",   weight=20,
         palette=_palette(dh=0.015, ds=0.90, dl=0.82)),
    dict(id="ochre",     name="土黄",     rarity="common",   weight=15,
         palette=_palette(dh=0.050, ds=0.95, dl=1.10)),
    dict(id="steel",     name="蓝钢",     rarity="uncommon", weight=10,
         palette=_palette(dh=-0.517, ds=0.85, dl=0.95)),
    dict(id="forest",    name="墨绿",     rarity="uncommon", weight=8,
         palette=_palette(dh=0.270, ds=0.90, dl=0.90)),
    dict(id="violet",    name="紫罗兰",   rarity="rare",     weight=4,
         palette=_palette(dh=-0.280, ds=0.95, dl=1.00)),
    dict(id="amber",     name="橙金",     rarity="rare",     weight=2,
         palette=_palette(dh=0.025, ds=1.20, dl=1.08)),
    dict(id="albino",    name="白化",     rarity="hidden",   weight=0.6,
         palette=_palette(ds=0.22, dl=1.55), light=True),
    dict(id="blackgold", name="黑金",     rarity="hidden",   weight=0.4,
         palette=_palette(ds=0.75, dl=0.42)),
]
MORPH_BY_ID = {m["id"]: m for m in MORPHS}

# ---------------------------------------------------------------------------
# Patterns (纹样).  Rarity order (for the dex "best" record): dark_head is
# the rarest pattern, plain the most common.
# ---------------------------------------------------------------------------
PATTERNS = [
    dict(id="plain",     name="无纹",     weight=45, rank=0),
    dict(id="spots",     name="鞘翅斑点", weight=30, rank=1),
    dict(id="bands",     name="深横带",   weight=20, rank=2),
    dict(id="dark_head", name="异色头",   weight=5,  rank=3),
]
PATTERN_BY_ID = {p["id"]: p for p in PATTERNS}

# ---------------------------------------------------------------------------
# Sizes (体型).  Pure cosmetics -- the scale multiplies the drawn body only.
# ---------------------------------------------------------------------------
SIZES = [
    dict(id="small",   name="小",   scale=0.85, weight=15),
    dict(id="smaller", name="偏小", scale=0.95, weight=25),
    dict(id="normal",  name="标准", scale=1.00, weight=35),
    dict(id="larger",  name="偏大", scale=1.08, weight=20),
    dict(id="huge",    name="大只", scale=1.20, weight=5),
]
SIZE_BY_ID = {s["id"]: s for s in SIZES}

# ---------------------------------------------------------------------------
# Rarity tiers.  recover_mult scales eat / sleep / train RECOVERY only --
# never the caps and never the decay rates, so a hidden variant makes the
# pet easier to keep, not stronger.
# ---------------------------------------------------------------------------
RARITIES = {
    "common":   dict(name="普通", recover_mult=1.00, color="#888780"),
    "uncommon": dict(name="少见", recover_mult=1.10, color="#378ADD"),
    "rare":     dict(name="稀有", recover_mult=1.20, color="#7F77DD"),
    "hidden":   dict(name="隐藏", recover_mult=1.35, color="#EF9F27"),
}

DEFAULT_GENES = {"morph": "classic", "pattern": "plain", "size": "normal",
                 "rarity": "common"}


# ---------------------------------------------------------------------------
# The roll
# ---------------------------------------------------------------------------
def _pick(rng, table):
    """Weighted pick.  `weight` values are percentages; the table need not
    sum to exactly 100 (the last entry catches the remainder)."""
    total = sum(e["weight"] for e in table)
    r = rng.uniform(0.0, total)
    upto = 0.0
    for e in table:
        upto += e["weight"]
        if r < upto:
            return e
    return table[-1]


def roll_variant(rng=None):
    """Roll one variant.  Pass a seeded `random.Random` for reproducibility."""
    rng = rng if rng is not None else random.Random()
    morph = _pick(rng, MORPHS)
    pattern = _pick(rng, PATTERNS)
    size = _pick(rng, SIZES)
    return {
        "morph": morph["id"],
        "pattern": pattern["id"],
        "size": size["id"],
        "rarity": morph["rarity"],
    }


# ---------------------------------------------------------------------------
# Lookups used by the game
# ---------------------------------------------------------------------------
def morph_of(genes):
    return MORPH_BY_ID.get((genes or {}).get("morph"), MORPHS[0])


def pattern_of(genes):
    return PATTERN_BY_ID.get((genes or {}).get("pattern"), PATTERNS[0])


def size_of(genes):
    return SIZE_BY_ID.get((genes or {}).get("size"), SIZES[2])


def palette_for(genes):
    """The 9-colour palette dict for _draw_beetle (r, g, b tuples)."""
    return dict(morph_of(genes)["palette"])


def is_light_morph(genes):
    """白化 and friends need a thicker rim or they vanish on a light wallpaper."""
    return bool(morph_of(genes).get("light"))


def size_scale(genes):
    return float(size_of(genes)["scale"])


def recover_mult(genes):
    """Rarity recovery multiplier (1.0 .. 1.35)."""
    return float(RARITIES.get((genes or {}).get("rarity"),
                              RARITIES["common"])["recover_mult"])


def rarity_color(genes):
    """Hex colour of the rarity tier (for the reveal flash / banner)."""
    return RARITIES.get((genes or {}).get("rarity"),
                        RARITIES["common"])["color"]


def banner(genes):
    """The reveal banner, e.g. '稀有 · 紫罗兰 · 鞘翅斑点'."""
    return "%s · %s · %s" % (
        RARITIES.get((genes or {}).get("rarity"), RARITIES["common"])["name"],
        morph_of(genes)["name"],
        pattern_of(genes)["name"],
    )


def mix(a, b, t):
    """Blend two (r, g, b) tuples.  Used to tint larva / pupa toward the
    adult morph colour without hardcoding a second palette."""
    t = max(0.0, min(1.0, t))
    return (round(a[0] + (b[0] - a[0]) * t),
            round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


def sanitize_genes(g):
    """Validate a genes dict from a save.

    Returns (genes, ok).  Repair is PER FIELD: a corrupted pattern does not
    throw away a rare morph, only the offending field falls back to the
    parent default (the same defensive pattern the offspring `idx` fallback
    uses).  `rarity` is always recomputed from the (possibly repaired) morph,
    so it can never disagree with the morph tier.  `ok` is False when
    anything was repaired or the input was not a dict at all.
    """
    out = dict(DEFAULT_GENES)
    if not isinstance(g, dict):
        return out, False
    ok = True
    for key, table in (("morph", MORPHS), ("pattern", PATTERNS), ("size", SIZES)):
        val = g.get(key)
        if val in {e["id"] for e in table}:
            out[key] = val
        else:
            ok = False
            print("[save] unknown offspring %s %r -> default %r"
                  % (key, val, out[key]))
    out["rarity"] = morph_of(out)["rarity"]
    return out, ok


# ---------------------------------------------------------------------------
# Dex (图鉴) helpers -- one entry per morph, kept in the save.
# ---------------------------------------------------------------------------
def dex_update(dex, genes):
    """Record one opened variant into the dex dict (mutates and returns it).

    count      how many times this morph has been opened
    best_*     the rarest pattern / largest size seen for this morph
    first_at   wall-clock ts of the first opening
    """
    if not isinstance(dex, dict):
        dex = {}
    mid = morph_of(genes)["id"]
    e = dex.get(mid)
    if e is None:
        dex[mid] = {"count": 1,
                    "best_pattern": pattern_of(genes)["id"],
                    "best_size": size_of(genes)["id"],
                    "first_at": time.time()}
        return dex
    e["count"] = int(e.get("count", 0)) + 1
    pat = pattern_of(genes)
    if pat["rank"] > PATTERN_BY_ID.get(e.get("best_pattern"),
                                       PATTERNS[0])["rank"]:
        e["best_pattern"] = pat["id"]
    if size_of(genes)["scale"] > size_of({"size": e.get("best_size")})["scale"]:
        e["best_size"] = size_of(genes)["id"]
    return dex


def dex_lines(dex):
    """The 9-cell collection wall as text rows (for the 图鉴 dialog)."""
    rows = []
    for m in MORPHS:
        e = dex.get(m["id"]) if isinstance(dex, dict) else None
        if e:
            pat = PATTERN_BY_ID.get(e.get("best_pattern"), PATTERNS[0])
            siz = SIZE_BY_ID.get(e.get("best_size"), SIZES[2])
            rows.append("%s（已开出 %d 次 · 最好：%s / %s）"
                        % (m["name"], int(e.get("count", 0)),
                           pat["name"], siz["name"]))
        else:
            rows.append("???（未开出）")
    return rows
