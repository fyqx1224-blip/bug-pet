"""What the exe is built FROM -- defined in exactly one place.

Both sides of the release gate import this module:

  * `build_exe.py`    stamps the fingerprint (dist/build_info.json) that
                      records the SHA-256 of every file listed here;
  * `check_exe_version.py` recomputes the same hashes and compares them
                      against the recorded ones.

Keeping the list here means the build and the check can never disagree
about what "the current source" means.  When the app starts loading a new
sprite, add it here and both sides follow automatically.

Nothing in this module touches the network, PyInstaller or Qt -- only
hashing -- so the gate runs anywhere Python does.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The single app module PyInstaller compiles into the exe.
CODE = "src/room_overlay.py"

# Bug sprites, downscaled to 512x512 RGBA by build_guest_pkg.py.
# (walk_left.png / walk_right.png are measurement references only -- the
# overlay loads walk_wings_* -- so they are NOT build inputs.)
SPRITES = (
    "sprites/walk_wings_left.png",
    "sprites/walk_wings_right.png",
    "sprites/flap_1_open.png",
    "sprites/flap_2_spread.png",
    "sprites/flap_3_down.png",
    "sprites/flap_4_folded.png",
)

# Fog frames, re-encoded as JPEG q85 by build_guest_pkg.py.
FOG = tuple(f"sprites/fog_bg/fog_bg_{i}.png" for i in range(6))

# The build scripts themselves.  If one of these changes, the exe should be
# rebuilt -- the packaging behaviour it produces is part of "the source".
SCRIPTS = (
    "build_exe.py",
    "build_guest_pkg.py",
    "build_full_pkg.py",
)


def input_files():
    """Every repo file the build consumes, as paths relative to ROOT."""
    return (CODE,) + SPRITES + FOG


def sha256(path):
    """SHA-256 of one file.  Accepts a str or a Path."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repo_fingerprint():
    """{relpath: sha256} for every repo file the build consumes."""
    return {rel: sha256(ROOT / rel) for rel in input_files()}


def script_fingerprint():
    """{relpath: sha256} for the build scripts themselves."""
    return {rel: sha256(ROOT / rel) for rel in SCRIPTS}
