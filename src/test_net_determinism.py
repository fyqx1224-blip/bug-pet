"""Headless test: deterministic Mating seed + remote snapshot apply."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pyqt_stub  # noqa: F401
import room_overlay as R
from PyQt5.QtCore import QPointF

# Build two bugs + two Matings with the SAME seed
b1 = R.Bug(R.SPRITES_DIR)
b1.x, b1.y = 200, 200
m1 = R.Bug(R.SPRITES_DIR)
m1.x, m1.y = 400, 200

b2 = R.Bug(R.SPRITES_DIR)
b2.x, b2.y = 200, 200
m2 = R.Bug(R.SPRITES_DIR)
m2.x, m2.y = 400, 200

nest = R.QRectF(600, 300, 200, 150)
SEED = 42

mat1 = R.Mating(b1, m1, nest, seed=SEED, t0=0.0)
mat2 = R.Mating(b2, m2, nest, seed=SEED, t0=0.0)

# Run both for 120 ticks (~2s)
for _ in range(120):
    mat1.tick(R.DT, 1920, 1080)
    mat2.tick(R.DT, 1920, 1080)

# Hearts must match exactly
h1 = [(h["x"], h["y"], h["size"]) for h in mat1.hearts]
h2 = [(h["x"], h["y"], h["size"]) for h in mat2.hearts]
assert h1 == h2, f"hearts diverged! len1={len(h1)} len2={len(h2)}"
print("[OK] Same seed → identical hearts:", len(h1), "particles")

# Different seed must differ
mat3 = R.Mating(b1, m1, nest, seed=SEED + 1, t0=0.0)
for _ in range(120):
    mat3.tick(R.DT, 1920, 1080)
h3 = [(h["x"], h["y"], h["size"]) for h in mat3.hearts]
assert h3 != h1, "different seed should produce different hearts"
print("[OK] Different seed → divergent hearts")

# Remote bug snapshot apply
rb = R.Bug(R.SPRITES_DIR)
rb.remote = True
rb.apply_snapshot({"x": 123.5, "y": 456.7, "facing": True, "st": "walking"})
assert rb.x == 123.5 and rb.y == 456.7
assert rb.facing_right is True and rb.state == "walking"
print("[OK] Remote snapshot apply")

# Remote tick does not move bug (AI gated)
orig_x = rb.x
for _ in range(60):
    rb.tick(1920, 1080)
assert rb.x == orig_x
print("[OK] Remote bug tick gates AI movement")

print("\nALL NET/DETERMINISM CHECKS PASSED")
