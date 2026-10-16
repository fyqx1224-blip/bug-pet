"""
Room Overlay - Interactive desktop pet room.

A full-screen transparent topmost window that lives on top of the wallpaper
(the static room backdrop).  Nothing extra is drawn on the image: interaction
is handled by INVISIBLE HOTSPOTS over the wallpaper's own painted objects.
  - Tap the leaf lamp (invisible hotspot) -> realistic gradient fog fills the
    glass dome (full-screen AI-generated frames).
  - Drag the bug onto the nest / dish / training rings (invisible hotspots) ->
    sleep / eat / train.
  - Optional drawn overlays (glows, rings, HUD, buttons) are gated by the
    SHOW_* flags near the top of the file and are OFF by default.

Click-through for empty areas is implemented via WM_NCHITTEST, so the
desktop remains usable. The bug itself is drawn in this overlay and is
draggable; dropping it inside a zone triggers the corresponding animation.
"""
import asyncio
import ctypes
import json
import math
import os
import random
import shutil
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QRectF
from PyQt5.QtGui import (
    QPainter, QPixmap, QCursor, QColor, QPainterPath, QRadialGradient,
    QLinearGradient, QFont, QGuiApplication, QPen, QImage, QPolygonF,
)
from PyQt5.QtWidgets import QApplication, QWidget, QInputDialog

try:
    import websockets as _websockets
    HAVE_WEBSOCKETS = True
except Exception:  # optional dependency; offline/single-PC mode still works
    _websockets = None
    HAVE_WEBSOCKETS = False

# PyInstaller onefile unpacks assets into the temp dir sys._MEIPASS points at,
# so __file__-relative paths break there.  Resolve the app root once, up front.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _APP_ROOT = Path(sys._MEIPASS)
else:
    _APP_ROOT = Path(__file__).resolve().parent.parent
SPRITES_DIR = _APP_ROOT / "sprites"

# Cross-PC relay endpoint.  Resolution order:
#   1) BUG_RELAY_URL environment variable (the host launcher sets this to its
#      own Tailscale IP, e.g. ws://100.x.y.z:8765)
#   2) relay.txt sitting next to the exe / in the project  (so the host can
#      mail her a fresh address later without rebuilding anything)
#   3) the address baked in when the exe was built
RELAY_URL_DEFAULT = os.environ.get("BUG_RELAY_URL", "ws://localhost:8765")

# When the relay is unreachable (colleague opened the pet first, Tailscale
# blinking), the client retries in the background instead of giving up.
NET_RETRY_SECONDS = 3.0


def _resolve_relay_url():
    env = os.environ.get("BUG_RELAY_URL")
    if env:
        return env
    candidates = []
    if getattr(sys, "frozen", False):
        # onefile relaxes assets into a temp dir, so the *exe's own* folder is
        # where an editable relay.txt actually lives
        candidates.append(Path(sys.executable).resolve().parent / "relay.txt")
    here = Path(__file__).resolve().parent
    candidates += [_APP_ROOT / "relay.txt", here / "relay.txt", here.parent / "relay.txt"]
    for cand in candidates:
        try:
            if cand is not None and cand.exists():
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("ws://") or line.startswith("wss://"):
                        return line
        except Exception:
            pass
    return RELAY_URL_DEFAULT


RELAY_URL = _resolve_relay_url()


# ---------- Persistence (auto-save) ----------
# Stats are dropped when the OS shuts down, so progress used to vanish.  The
# pet now auto-saves (bug position, the three stat bars, and -- most
# importantly -- the offspring's exact stage + elapsed time) to a JSON file and
# restores it on the next launch.
AUTOSAVE_SECONDS = 20.0        # periodic auto-save cadence
# Offline catch-up: while the app is closed, the pet "keeps living", so the
# offspring advances and the stats drift while you were away (capped so a weird
# clock can't explode the values).  Set BUG_PET_OFFLINE_CATCHUP=0 to disable.
OFFLINE_CATCHUP = os.environ.get("BUG_PET_OFFLINE_CATCHUP", "1") not in ("", "0", "false")
OFFLINE_CATCHUP_MAX = 7 * 24 * 3600   # clamp offline elapsed to 7 days


def _live_save_is_protected() -> bool:
    """True when this process is a test harness that forgot to isolate itself.

    Every test must point BUG_SAVE at a temp path (see _testenv.py).  A test
    that does not would otherwise load and then overwrite the player's real
    save -- and test_logic.py drives a full mating, so it would lay a brand new
    egg straight over a developing offspring.  That is exactly how a 成长期
    pet "went back" to 卵期, so the write is now refused outright.
    """
    if os.environ.get("BUG_SAVE"):
        return False                     # explicitly isolated -> fine
    try:
        import __main__
        name = os.path.basename(getattr(__main__, "__file__", "") or "")
    except Exception:
        return False
    return name.startswith("test_")


def _save_path() -> Path:
    override = os.environ.get("BUG_SAVE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "bug_pet"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d / "save.json"
    except Exception:
        return Path(__file__).resolve().parent.parent / "save.json"

# ---------- Bug display ----------
BUG_W = 300
BUG_H = 200
# Right-click "缩小虫子": each click multiplies the bug's drawn size by
# BUG_SCALE_STEP, down to BUG_SCALE_MIN (any smaller and it gets hard to
# grab).  The chosen scale is auto-saved with the rest of the game state.
BUG_SCALE_DEFAULT = 1.0
BUG_SCALE_MIN = 0.30
BUG_SCALE_STEP = 0.8
FLAP_FPS = 14
MOVE_FPS = 60
DT = 1.0 / MOVE_FPS  # seconds per tick

# ---------- Zone definitions (fractions of screen size) ----------
# Reference layout: 1920x1080.  These fractions are tuned to the wallpaper
# `bug_room_wallpaper_1920x1080.png` and are auto-scaled to the actual screen.
ZONES = {
    "dome":      dict(x=0.04, y=0.02, w=0.92, h=0.76),
    "nest":      dict(cx=0.873, cy=0.450, w=0.130, h=0.170),
    "dish":      dict(cx=0.180, cy=0.385, r=0.090),
    "training":  dict(cx=0.475, cy=0.185, w=0.220, h=0.150),
    "stats":     dict(x=0.012, y=0.012, w=0.150, h=0.165),
    "info_btn":  dict(x=0.148, y=0.012, w=0.030, h=0.040),
    "fog_btn":   dict(cx=0.500, cy=0.882, r=0.035),
}

# ---------- Tunables ----------
DOME_FOG_MAX_ALPHA = 200   # 0..255
DOME_FOG_RAMP = 3.5        # seconds to reach max
DOME_SINK_DUR = 0.6        # seconds
NEST_BOB_AMP = 8           # px
NEST_PROXIMITY = 160       # px - drop radius that triggers sleep
DISH_PROXIMITY = 150       # px - drop radius that triggers eat
TRAIN_PROXIMITY = 170      # px - drop radius that triggers training
EAT_DURATION = 2.4         # seconds
SLEEP_INTRO = 1.0          # seconds to walk into the nest
TRAIN_DURATION = 3.0       # seconds
RECOG_RING_DUR = 0.9       # seconds

# ---------- Stats (status bar) tunables ----------
# All three stats are normalised 0..1 where 1 = best (full / rested / happy).
# Decay rates are PER SECOND (multiplied by DT each tick).
FULLNESS_DECAY = 0.005      # /s  -> ~200s from full to starving
ENERGY_DECAY  = 0.004      # /s  while awake (sleep recovers it)
MOOD_DRIFT     = 0.004      # /s  happiness drifts toward its baseline
MOOD_BASELINE  = 0.55       # loneliness pulls mood down to here when ignored
EAT_GAIN       = 0.50       # fullness added per meal
EAT_COOLDOWN   = 3.0        # s - prevents the dish from over-filling per bite
SLEEP_GAIN     = 0.50       # energy added per nap
TRAIN_ENERGY   = 0.25       # energy spent per training
TRAIN_HAPPY    = 0.10       # mood gained per training
TRAIN_FULLNESS = 0.10       # fullness spent per training
BREED_THRESHOLD = 0.95      # all three stats must exceed this to enter heat

# ---------- Life-cycle (offspring) durations ----------
# Real, slow pacing (chosen by user). 1 second of wall-clock == LIFE_SCALE s
# of bug-time. Set BUG_PET_FAST env var to collapse everything for testing.
import os as _os
LIFE_FAST = _os.environ.get("BUG_PET_FAST", "") not in ("", "0", "false")
# bug-seconds per wall-second.  1.0 = real time (egg ~8h, full cycle ~36h).
# Set BUG_PET_FAST to collapse everything (egg ~1s) for development/testing.
LIFE_SCALE = 1.0 if not LIFE_FAST else 28800.0
EGG_PERIOD    = 8 * 3600 / LIFE_SCALE    # egg sits in the nest
HATCH_PERIOD  = 4 * 3600 / LIFE_SCALE    # egg darkens, embryo visible
LARVA_PERIOD  = 12 * 3600 / LIFE_SCALE   # campodeiform larva, 3 instars
GROWTH_PERIOD = 12 * 3600 / LIFE_SCALE   # pupa + sub-adult growth
MATING_ANIM   = 3.0                      # s - the two bugs nuzzle
MATING_TO_EGG = 10.0                     # s - after returning to nest, egg appears
EGG_GLOW_COLORS = {"EGG": QColor(250, 238, 218), "HATCH": QColor(250, 220, 130)}

# ---------- What to draw on top of the wallpaper ----------
# The user wants a CLEAN picture: nothing extra drawn on the image.
# Interaction is handled purely through invisible hotspots over the
# wallpaper's own painted objects (leaf lamp, nest, dish, training rings).
# Flip any of these flags back to True to re-enable the original overlays.
SHOW_DECOR = False        # nest/dish/training glows, rings, food, recognition, zzz, proximity outlines, dome under-shadow
SHOW_FOG_BUTTON = False   # the drawn leaf-lamp button (hotspot still works -> just click the lamp in the image)
SHOW_INFO_BUTTON = False  # the drawn 'i' box (F1 still opens the help panel)
SHOW_HUD = True           # the stats panel (functional pet UI; set False for a fully clean image)
# Dashed outlines + labels for the drop zones.  They sat at the top of the
# screen and got in the way of normal work, so they are INVISIBLE now: the
# dish/nest/training hotspots stay fully functional (invisible click zones,
# calibrated to the wallpaper).  Set BUG_PET_GUIDES=1 to draw them again.
SHOW_ZONE_GUIDES = os.environ.get("BUG_PET_GUIDES", "0") not in ("", "0", "false")

# How see-through the stats panel (and the offspring card under it) is.
# 1.0 = solid, 0 = gone.  The user found the solid panel distracting while
# working, so it now floats semi-transparently over the wallpaper.
HUD_OPACITY = float(os.environ.get("BUG_PET_HUD_OPACITY", "0.55"))


# ===================== math helpers =====================
def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smoothstep(edge0, edge1, x):
    t = clamp((x - edge0) / max(1e-6, edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ===================== Bug =====================
class Bug:
    """The rove beetle.  Drawn inside the overlay, draggable, with
    extended state machine (walk / fly / landed / dragged / sleeping /
    eating / training)."""

    STATE_LANDED = "landed"
    STATE_WALKING = "walking"
    STATE_FLYING = "flying"
    STATE_DRAGGED = "dragged"
    STATE_SLEEPING = "sleeping"
    STATE_EATING = "eating"
    STATE_TRAINING = "training"
    STATE_MATING = "mating"

    def __init__(self, sprites_dir: Path):
        self._load_sprites(sprites_dir)
        self.facing_right = True
        # per-bug drawn size (1.0 = original).  Shrink via the right-click
        # menu; applies to this bug instance only (mate / remote keep 1.0).
        self.size_scale = BUG_SCALE_DEFAULT
        self.x = 0.0
        self.y = 0.0
        self.state = self.STATE_LANDED
        self.flap_frame_idx = 0
        self.anim_phase = 0.0
        # walk
        self.walk_target = None
        self.walk_idle_timer = 0
        # land
        self.land_timer = 120
        # flight
        self.flight_frame = 0
        self.flight_total_frames = 1
        self.flight_start = QPointF(0, 0)
        self.flight_end = QPointF(0, 0)
        self.flight_ctrl = QPointF(0, 0)
        # drag
        self.dragging = False
        self.drag_offset = QPoint()
        # net (cross-PC play)
        self.remote = False
        self.placed = False     # remote: True once a real snapshot arrived
        # sleep / eat / train timers
        self.action_t = 0.0
        self.action_duration = 1.0
        # target position for transitions
        self._target_pos = QPointF(0, 0)

    # ---------- sprite loading ----------
    def _load_sprites(self, sprites_dir: Path):
        def load(name):
            return QPixmap(str(sprites_dir / name))

        self.sprite_walk_left = load("walk_wings_left.png")
        self.sprite_walk_right = load("walk_wings_right.png")
        self.sprite_flap = [
            load("flap_1_open.png"),
            load("flap_2_spread.png"),
            load("flap_3_down.png"),
            load("flap_4_folded.png"),
        ]
        all_sprites = [self.sprite_walk_left, self.sprite_walk_right] + self.sprite_flap
        for s in all_sprites:
            s._scaled = s.scaled(BUG_W, BUG_H, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation)
        self._walk_l = self.sprite_walk_left._scaled
        self._walk_r = self.sprite_walk_right._scaled
        self._flap = [s._scaled for s in self.sprite_flap]

    # ---------- per-frame ----------
    def tick(self, screen_w, screen_h):
        self.anim_phase = (self.anim_phase + DT) % 1.0
        self.flap_frame_idx = int(self.anim_phase * FLAP_FPS * 4) % 4

        if self.remote:
            return

        if self.state == self.STATE_LANDED:
            self.land_timer -= 1
            if self.land_timer <= 0:
                r = random.random()
                if r < 0.25:
                    self._start_random_flight(screen_w, screen_h)
                else:
                    self.state = self.STATE_WALKING
                    self.walk_target = None
                    self.walk_idle_timer = random.randint(20, 70)

        elif self.state == self.STATE_WALKING:
            if self.walk_idle_timer > 0:
                self.walk_idle_timer -= 1
            if self.walk_target is None and self.walk_idle_timer <= 0:
                tx = self.x + random.randint(-220, 220)
                ty = self.y + random.randint(-60, 60)
                tx = clamp(tx, 40, screen_w - BUG_W - 40)
                ty = clamp(ty, 60, screen_h - BUG_H - 80)
                self.walk_target = QPointF(tx, ty)
                self.facing_right = tx > self.x
            if self.walk_target is not None:
                dx = self.walk_target.x() - self.x
                dy = self.walk_target.y() - self.y
                d = math.hypot(dx, dy)
                if d < 5:
                    self.walk_target = None
                    self.walk_idle_timer = random.randint(30, 100)
                    self.state = self.STATE_LANDED
                    self.land_timer = random.randint(80, 200)
                else:
                    speed = 1.6
                    self.x += dx / d * speed
                    self.y += dy / d * speed

        elif self.state == self.STATE_FLYING:
            self.flight_frame += 1
            t = self.flight_frame / max(1, self.flight_total_frames)
            if t >= 1.0:
                self.x = self.flight_end.x()
                self.y = self.flight_end.y()
                self.state = self.STATE_LANDED
                self.land_timer = random.randint(100, 240)
            else:
                u = 1 - t
                self.x = u * u * self.flight_start.x() + 2 * u * t * self.flight_ctrl.x() + t * t * self.flight_end.x()
                self.y = u * u * self.flight_start.y() + 2 * u * t * self.flight_ctrl.y() + t * t * self.flight_end.y()

        elif self.state == self.STATE_DRAGGED:
            # position is set by the overlay from mouse
            pass

        elif self.state == self.STATE_SLEEPING:
            # stay in place; the overlay animates the merge
            pass

        elif self.state == self.STATE_EATING:
            self.action_t += DT
            if self.action_t >= self.action_duration:
                self.state = self.STATE_LANDED
                self.land_timer = 60

        elif self.state == self.STATE_TRAINING:
            self.action_t += DT
            if self.action_t >= self.action_duration:
                self.state = self.STATE_LANDED
                self.land_timer = 60

        elif self.state == self.STATE_MATING:
            # Position is driven by the Mating controller; just keep animating.
            pass

    # ---------- actions triggered by the overlay ----------
    def start_sleep(self, target_pos: QPointF):
        """Begin sleeping.  Walk to the nest first, then settle."""
        self._target_pos = target_pos
        self.facing_right = target_pos.x() > self.x
        self.state = self.STATE_SLEEPING
        self.action_t = 0.0
        # jump-cut to nest center for now (smooth slide handled by overlay)
        self.x = target_pos.x()
        self.y = target_pos.y()

    def start_eat(self, target_pos: QPointF):
        self.facing_right = target_pos.x() > self.x
        self.x = target_pos.x()
        self.y = target_pos.y()
        self.state = self.STATE_EATING
        self.action_t = 0.0
        self.action_duration = EAT_DURATION

    def start_train(self, target_pos: QPointF):
        self.facing_right = target_pos.x() > self.x
        self.x = target_pos.x()
        self.y = target_pos.y()
        self.state = self.STATE_TRAINING
        self.action_t = 0.0
        self.action_duration = TRAIN_DURATION

    def _start_random_flight(self, sw, sh):
        tx = random.randint(60, max(61, int(sw - BUG_W - 60)))
        ty = random.randint(int(sh * 0.25), max(int(sh * 0.25) + 1, int(sh * 0.88) - BUG_H))
        self.flight_start = QPointF(self.x, self.y)
        self.flight_end = QPointF(tx, ty)
        mx = (self.flight_start.x() + tx) / 2 + random.randint(-120, 120)
        my = min(self.flight_start.y(), ty) - random.randint(80, 200)
        self.flight_ctrl = QPointF(mx, my)
        dist = math.hypot(tx - self.flight_start.x(), ty - self.flight_start.y())
        dur_ms = max(800, int(dist * 1.2))
        self.flight_total_frames = max(1, int(dur_ms / (1000.0 / MOVE_FPS)))
        self.flight_frame = 0
        self.facing_right = tx > self.flight_start.x()
        self.state = self.STATE_FLYING

    # ---------- drawing ----------
    def w(self):
        """Width of this bug's footprint, honouring the shrink scale."""
        return BUG_W * self.size_scale

    def h(self):
        """Height of this bug's footprint, honouring the shrink scale."""
        return BUG_H * self.size_scale

    def shrink(self):
        """One '缩小虫子' menu click.  Returns the new scale."""
        self.size_scale = max(
            BUG_SCALE_MIN, round(self.size_scale * BUG_SCALE_STEP, 3))
        return self.size_scale

    def restore_size(self):
        self.size_scale = BUG_SCALE_DEFAULT

    def bounding_rect(self):
        # Slightly inset so the bug hotspot is forgiving
        return QRectF(self.x, self.y, self.w(), self.h())

    def center(self):
        return QPointF(self.x + self.w() / 2, self.y + self.h() / 2)

    def draw(self, p: QPainter, nest_blend=0.0, training_amp=0.0):
        # Choose sprite
        angle = 0.0
        if self.state == self.STATE_FLYING:
            sprite = self._flap[self.flap_frame_idx]
            t = self.flight_frame / max(1, self.flight_total_frames)
            angle = math.sin(t * math.pi) * 6
            if not self.facing_right:
                angle = -angle
        else:
            if self.facing_right:
                sprite = self._walk_r
            else:
                sprite = self._walk_l

        # State-driven pose tweaks
        bob_y = 0.0
        scale = self.size_scale     # user-shrink factor (1.0 = original)
        extra_rot = 0.0
        alpha = 1.0

        if self.state == self.STATE_LANDED:
            bob_y = math.sin(self.anim_phase * math.pi * 2) * 1.5
        elif self.state == self.STATE_WALKING:
            bob_y = abs(math.sin(self.anim_phase * math.pi * 8)) * 1.0
        elif self.state == self.STATE_EATING:
            bob_y = abs(math.sin(self.action_t * math.pi * 8)) * 4.0
        elif self.state == self.STATE_SLEEPING:
            # lie on side + blend with nest
            extra_rot = 90 if self.facing_right else -90
            alpha = 1.0 - nest_blend * 0.85
        elif self.state == self.STATE_TRAINING:
            # flap harder
            sprite = self._flap[self.flap_frame_idx]
            bob_y = abs(math.sin(self.action_t * math.pi * 12)) * (4 + training_amp)
            scale = self.size_scale * (1.0 + 0.03 * math.sin(self.action_t * math.pi * 6))
        elif self.state == self.STATE_MATING:
            # gentle nuzzle bob while the Mating controller positions us
            bob_y = math.sin(self.anim_phase * math.pi * 6) * 2.0

        # ---- contact shadow (soft elliptical blob, behind the sprite) ----
        # The sprites are square (1024x1024 -> 200x200 under KeepAspectRatio),
        # so the shadow must follow the *drawn pixmap*, not the 300x200
        # footprint, and it fades to alpha 0 before the edge (no hard cut).
        # The beetle's visible feet sit at ~0.79 of the sprite height (the
        # rows below that are near-invisible alpha noise), and the shadow
        # stays on the ground while the bug bobs.
        if self.state not in (self.STATE_FLYING, self.STATE_DRAGGED):
            fcx = self.x + self.w() / 2
            fcy = self.y + self.h() / 2                  # ground anchor (no bob)
            sx = fcx + (self.x - fcx) * scale            # sprite origin after scaling
            sy = fcy + (self.y - fcy) * scale
            sw_d = sprite.width() * scale
            sh_d = sprite.height() * scale
            if self.state == self.STATE_SLEEPING:
                # lying on its side in the nest: small round contact patch
                sh_cx, sh_cy = fcx, fcy
                rx, ry = sw_d * 0.19, sh_d * 0.13
            else:
                sh_cx = sx + sw_d * 0.50
                sh_cy = sy + sh_d * 0.80
                rx, ry = sw_d * 0.41, sh_d * 0.070
            p.save()
            p.setOpacity(alpha)
            p.translate(sh_cx, sh_cy)
            p.scale(1.0, ry / rx)                        # squash the circle into an ellipse
            sg = QRadialGradient(QPointF(0, 0), rx)
            sg.setColorAt(0.0, QColor(0, 0, 0, 115))
            sg.setColorAt(0.45, QColor(0, 0, 0, 58))
            sg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(sg)
            p.drawEllipse(QPointF(0, 0), rx, rx)
            p.restore()

        p.save()
        p.setOpacity(alpha)
        # scale around the *scaled* footprint centre so the drawn sprite and
        # the clickable bounding_rect() stay centred on the same point
        cx = self.x + self.w() / 2
        cy = self.y + self.h() / 2 + bob_y
        p.translate(cx, cy)
        if scale != 1.0:
            p.scale(scale, scale)
        if extra_rot:
            p.rotate(extra_rot)
        if angle:
            p.rotate(angle)
        p.translate(-cx, -cy)
        p.drawPixmap(int(self.x), int(self.y + bob_y), sprite)
        p.restore()

    # ---------- mouse ----------
    def hit(self, pt: QPointF) -> bool:
        return self.bounding_rect().contains(pt)

    def start_drag(self, mouse_global: QPoint, my_global: QPoint):
        self.dragging = True
        self.drag_offset = mouse_global - QPoint(int(self.x), int(self.y))
        self.state = self.STATE_DRAGGED
        self.land_timer = 0

    def update_drag(self, mouse_global: QPoint):
        nx = mouse_global.x() - self.drag_offset.x()
        ny = mouse_global.y() - self.drag_offset.y()
        self.x = float(nx)
        self.y = float(ny)

    def end_drag(self):
        self.dragging = False
        self.state = self.STATE_LANDED
        self.land_timer = random.randint(40, 120)

    def apply_snapshot(self, d):
        """For cross-PC play: set pos/facing/state from a peer state dict."""
        self.x = float(d.get("x", self.x))
        self.y = float(d.get("y", self.y))
        self.placed = True
        self.facing_right = bool(d.get("facing", self.facing_right))
        # state is transmitted as string; only adopt if not locally busy
        st = d.get("st")
        if st and not self.dragging:
            self.state = st


# ===================== Dome =====================
class Dome:
    """Glass dome over the central habitat.  Click to fog it up; click again
    to 'press in' (sunken) and let the fog clear.  Fog is rendered using
    AI-generated animated frames for realism."""

    STATE_CLEAR = 0
    STATE_FOGGING = 1
    STATE_FOGGED = 2
    STATE_SINKING = 3       # pressed in + clearing
    STATE_CLEARING = 4

    def __init__(self, rect: QRectF):
        self.rect = rect
        self.state = self.STATE_CLEAR
        self.fog_alpha = 0.0           # 0..1
        self.press_phase = 0.0         # 0..1, animation time
        self.press_dir = 0             # -1 in, +1 out
        # Load AI-generated fog animation frames
        self._load_fog_frames()
        self._frame_idx = 0
        self._frame_t = 0.0
        # Frame rate for fog animation (frames per second)
        self.FOG_ANIM_FPS = 8

    def _load_fog_frames(self):
        """Load the 6 AI-generated fog frames from sprites/fog_bg/.
        These are full-screen 1920x1072 frames with the wallpaper background
        + fog inside the glass dome, so they align perfectly with the wallpaper."""
        fog_dir = SPRITES_DIR / "fog_bg"
        self.fog_frames = []
        for i in range(6):
            path = fog_dir / f"fog_bg_{i}.png"
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    self.fog_frames.append(pm)
        if not self.fog_frames:
            # fallback: at least have a transparent placeholder
            self.fog_frames = [QPixmap(1, 1)]
            self.fog_frames[0].fill(Qt.transparent)

    def rect_hot(self) -> QRectF:
        # Interactive hot area
        return self.rect

    def contains(self, pt: QPointF) -> bool:
        return self.rect.contains(pt)

    def click(self):
        if self.state == self.STATE_CLEAR:
            self.state = self.STATE_FOGGING
        elif self.state == self.STATE_FOGGED:
            self.state = self.STATE_SINKING
            self.press_phase = 0.0
            self.press_dir = -1  # start pressing in
        elif self.state == self.STATE_FOGGING:
            # mid-fog: snap to fogged (lets user commit)
            self.state = self.STATE_FOGGED
            self.fog_alpha = 1.0

    def tick(self):
        # Animate fog frame index
        self._frame_t += DT
        frame_interval = 1.0 / self.FOG_ANIM_FPS
        if self._frame_t >= frame_interval:
            self._frame_t -= frame_interval
            self._frame_idx = (self._frame_idx + 1) % len(self.fog_frames)

        if self.state == self.STATE_FOGGING:
            self.fog_alpha = min(1.0, self.fog_alpha + DT / DOME_FOG_RAMP)
            if self.fog_alpha >= 1.0:
                self.state = self.STATE_FOGGED
        elif self.state == self.STATE_SINKING:
            # spring-bounce press in (~0.5s), then start clearing
            self.press_phase += DT / DOME_SINK_DUR
            if self.press_phase >= 0.5:
                # begin clearing fog
                self.state = self.STATE_CLEARING
        elif self.state == self.STATE_CLEARING:
            self.fog_alpha = max(0.0, self.fog_alpha - DT / DOME_FOG_RAMP)
            # also let the press return smoothly
            if self.press_phase < 1.0:
                self.press_phase = min(1.0, self.press_phase + DT / DOME_SINK_DUR)
            if self.fog_alpha <= 0.01:
                self.fog_alpha = 0.0
                self.press_phase = 1.0
                self.state = self.STATE_CLEAR

    def press_amount(self) -> float:
        """0 = no press, 1 = fully sunk in.  Used to darken edges."""
        if self.state == self.STATE_CLEAR:
            return 0.0
        if self.state == self.STATE_SINKING:
            # ease in to ~0.85, then we'll bounce back
            t = self.press_phase / 0.5
            t = clamp(t, 0.0, 1.0)
            return smoothstep(0.0, 1.0, t) * 0.85
        if self.state == self.STATE_CLEARING:
            # bounce back from 0.85 to 0 as fog clears
            t = clamp(self.press_phase, 0.5, 1.0)
            u = (t - 0.5) / 0.5
            # overshoot a bit for a spring feel
            return 0.85 * (1.0 - smoothstep(0.0, 1.0, u)) * (1.0 + 0.12 * math.sin(u * math.pi * 2))
        if self.state == self.STATE_FOGGED:
            return 0.0
        return 0.0

    def draw_under(self, p: QPainter):
        """Draw a slight inner shadow when the dome is pressed in (sunk)."""
        amt = self.press_amount()
        if amt <= 0.01:
            return
        # inset darkening on the edges
        pad = 18 * amt
        path = QPainterPath()
        outer = QRectF(self.rect)
        path.addEllipse(outer)
        inner = QRectF(self.rect.adjusted(pad, pad, -pad, -pad))
        path.addEllipse(inner)
        path.setFillRule(Qt.OddEvenFill)
        grad = QRadialGradient(QPointF(self.rect.center()), self.rect.width() / 2)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, int(180 * amt)))
        p.fillPath(path, grad)

    def draw_fog(self, p: QPainter, sw: int, sh: int):
        if self.fog_alpha <= 0.01 or not self.fog_frames:
            return
        p.save()
        # Get current frame and scale to full screen
        frame = self.fog_frames[self._frame_idx % len(self.fog_frames)]
        p.setOpacity(self.fog_alpha)
        # Scale to fill the entire screen, keeping aspect ratio
        scaled = frame.scaled(sw, sh, Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
        # Center on screen
        dx = (sw - scaled.width()) / 2
        dy = (sh - scaled.height()) / 2
        p.drawPixmap(int(dx), int(dy), scaled)
        p.restore()


# ===================== Nest =====================
class Nest:
    """The leaf sleeping pod.  Bobs up and down; when the bug is dropped
    inside its proximity, the bug goes to sleep and merges with the pod."""

    def __init__(self, rect: QRectF):
        self.rect = rect
        self.bob_phase = random.uniform(0, math.tau)
        self.glow = 0.0     # rises when bug is inside
        self.zzz = []        # particle list
        self._zzz_t = 0.0

    def rect_hot(self) -> QRectF:
        return self.rect.adjusted(-NEST_PROXIMITY * 0.4, -NEST_PROXIMITY * 0.3,
                                   NEST_PROXIMITY * 0.4, NEST_PROXIMITY * 0.4)

    def contains(self, pt: QPointF) -> bool:
        return self.rect_hot().contains(pt)

    def center(self) -> QPointF:
        return QPointF(self.rect.center())

    def bob_offset(self) -> float:
        return math.sin(self.bob_phase) * NEST_BOB_AMP

    def tick(self, bug_inside: bool):
        self.bob_phase += DT * 1.4
        target = 1.0 if bug_inside else 0.0
        self.glow += (target - self.glow) * min(1.0, DT * 3.5)
        # Zzz particles when bug is inside
        self._zzz_t += DT
        if bug_inside and self._zzz_t > 0.35:
            self._zzz_t = 0.0
            self.zzz.append({
                "x": self.rect.x() + random.uniform(self.rect.width() * 0.55,
                                                    self.rect.width() * 0.90),
                "y": self.rect.y() + self.rect.height() * 0.10,
                "vy": -random.uniform(22, 38),
                "life": 1.0,
                "size": random.uniform(14, 22),
            })
        # update
        for z in self.zzz:
            z["y"] += z["vy"] * DT
            z["life"] -= DT * 0.7
        self.zzz = [z for z in self.zzz if z["life"] > 0]

    def draw_glow(self, p: QPainter):
        if self.glow < 0.02:
            return
        cx = self.rect.center().x()
        cy = self.rect.center().y() + self.bob_offset()
        grad = QRadialGradient(QPointF(cx, cy), self.rect.width() * 1.0)
        col_a = int(140 * self.glow)
        grad.setColorAt(0.0, QColor(120, 230, 160, col_a))
        grad.setColorAt(1.0, QColor(120, 230, 160, 0))
        p.fillRect(QRectF(cx - self.rect.width(), cy - self.rect.height(),
                          self.rect.width() * 2, self.rect.height() * 2), grad)

    def draw_zzz(self, p: QPainter):
        p.save()
        font = QFont("Arial", 18, QFont.Bold)
        for z in self.zzz:
            a = clamp(z["life"], 0.0, 1.0)
            p.setPen(QColor(180, 240, 220, int(255 * a)))
            font.setPointSizeF(z["size"])
            p.setFont(font)
            p.drawText(QPointF(z["x"], z["y"]), "Z")
        p.restore()


# ===================== Dish =====================
class Dish:
    """The food dish.  Idle: light flickers, food wiggles.  When the bug
    is nearby: emits a recognition ring then the bug starts eating."""

    STATE_IDLE = 0
    STATE_RECOGNIZING = 1    # ring expanding
    STATE_BUG_EATING = 2     # bug is at the dish eating

    def __init__(self, center: QPointF, radius: float):
        self.center = center
        self.radius = radius
        self.flicker_phase = random.uniform(0, 10)
        self.food_dots = []
        n = 5
        for i in range(n):
            a = (i / n) * math.tau
            self.food_dots.append({
                "base_a": a,
                "a": a,
                "r": radius * random.uniform(0.25, 0.45),
                "size": random.uniform(5, 8),
                "speed": random.uniform(0.6, 1.4),
            })
        self.state = self.STATE_IDLE
        self.recognize_t = 0.0
        self.eat_t = 0.0
        self.eaten_mask = [False] * len(self.food_dots)
        self._regen_t = 0.0

    def rect_hot(self) -> QRectF:
        r = self.radius + DISH_PROXIMITY
        return QRectF(self.center.x() - r, self.center.y() - r, r * 2, r * 2)

    def contains(self, pt: QPointF) -> bool:
        return self.rect_hot().contains(pt)

    def start_recognize(self):
        if self.state == self.STATE_IDLE:
            self.state = self.STATE_RECOGNIZING
            self.recognize_t = 0.0

    def start_eat(self):
        self.state = self.STATE_BUG_EATING
        self.eat_t = 0.0

    def tick(self):
        self.flicker_phase += DT * 8
        # food dots orbit
        for d in self.food_dots:
            d["a"] += d["speed"] * DT
        # regen food after a while
        if self.state == self.STATE_BUG_EATING:
            self.eat_t += DT
            # every 0.35s, eat one dot
            threshold = self.eat_t / EAT_DURATION
            n = len(self.food_dots)
            eaten = int(threshold * n)
            for i in range(n):
                self.eaten_mask[i] = i < eaten
            if self.eat_t >= EAT_DURATION + 0.4:
                # restore
                self.state = self.STATE_IDLE
                self.eaten_mask = [False] * n

        if self.state == self.STATE_RECOGNIZING:
            self.recognize_t += DT
            if self.recognize_t >= RECOG_RING_DUR:
                self.state = self.STATE_IDLE  # waiting for bug to actually eat

    def flicker_value(self) -> float:
        """0..1, fast small flicker for the idle light."""
        base = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.flicker_phase))
        jitter = 0.15 * math.sin(self.flicker_phase * 7.3)
        return clamp(base + jitter, 0.0, 1.0)

    def draw_glow(self, p: QPainter):
        # Idle ambient light on the dish
        f = self.flicker_value()
        cx, cy = self.center.x(), self.center.y() - self.radius * 0.6
        grad = QRadialGradient(QPointF(cx, cy), self.radius * 1.6)
        col = QColor(100, 200, 255, int(110 * f))
        grad.setColorAt(0.0, col)
        grad.setColorAt(1.0, QColor(100, 200, 255, 0))
        r = self.radius * 1.8
        p.fillRect(QRectF(cx - r, cy - r, r * 2, r * 2), grad)

    def draw_food(self, p: QPainter):
        # Draw food dots inside the dish, in their orbit
        p.save()
        for i, d in enumerate(self.food_dots):
            if self.eaten_mask[i]:
                continue
            ang = d["a"]
            fx = self.center.x() + math.cos(ang) * d["r"]
            fy = self.center.y() + math.sin(ang) * d["r"] * 0.55
            size = d["size"]
            col = QColor(255, 180, 80)
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(fx, fy), size, size * 0.85)
        p.restore()

    def draw_recognition(self, p: QPainter):
        if self.state != self.STATE_RECOGNIZING:
            return
        t = clamp(self.recognize_t / RECOG_RING_DUR, 0.0, 1.0)
        # 3 expanding rings staggered
        for k in range(3):
            tt = (t + k * 0.33) % 1.0
            r = self.radius * (1.0 + tt * 3.5)
            a = int(220 * (1.0 - tt))
            pen = QPen(QColor(140, 230, 255, a), 3)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(self.center.x(), self.center.y()), r, r * 0.55)


# ===================== Training =====================
class Training:
    """The training portals.  Click or drop the bug here to make it do
    wing-flap exercise."""

    def __init__(self, rect: QRectF):
        self.rect = rect
        self.phase = 0.0
        self.active = False
        self.active_t = 0.0

    def rect_hot(self) -> QRectF:
        return self.rect.adjusted(-20, -20, 20, 20)

    def contains(self, pt: QPointF) -> bool:
        return self.rect_hot().contains(pt)

    def trigger(self):
        self.active = True
        self.active_t = 0.0

    def center(self) -> QPointF:
        return QPointF(self.rect.center())

    def tick(self):
        self.phase += DT * 1.8
        if self.active:
            self.active_t += DT
            if self.active_t >= TRAIN_DURATION:
                self.active = False

    def draw(self, p: QPainter):
        # Three rotating rings
        cx, cy = self.rect.center().x(), self.rect.center().y()
        rw, rh = self.rect.width() / 2, self.rect.height() / 2
        for k in range(3):
            offset = k * (math.tau / 3)
            ang = self.phase * (1.0 if k % 2 == 0 else -1.0) + offset
            r = (rw * 0.4) + (rw * 0.18) * k
            # ellipse with tilt
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(ang) * 0.4)
            color = QColor(120, 220, 255, 180 if self.active else 120)
            pen = QPen(color, 4)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), int(r), int(rh * (0.55 + 0.1 * math.sin(self.phase * 2 + k))))
            p.restore()

        # when active, draw an extra burst
        if self.active:
            for i in range(6):
                a = self.active_t / TRAIN_DURATION
                t = (a + i * 0.16) % 1.0
                rr = (1.0 - t) * (rw * 1.3)
                alpha = int(180 * (1.0 - t))
                p.setPen(QPen(QColor(180, 240, 255, alpha), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(cx, cy), int(rr), int(rr * 0.55))


# ===================== Stats HUD =====================
class StatsHUD:
    """The pet's three needs.  All normalised 0..1, 1 = best.

    fullness : 0 starving .. 1 full
    energy   : 0 exhausted .. 1 rested
    happy    : 0 sad .. 1 happy
    """
    def __init__(self, rect: QRectF):
        self.rect = rect
        self.fullness = 0.60     # 0 starving .. 1 full
        self.energy = 0.55       # 0 exhausted .. 1 rested
        self.happy = 0.70        # 0 sad .. 1 happy
        self._eat_cd = 0.0       # meal cooldown so the dish can't stack bites
        self.in_heat = False     # True when all three stats are maxed
        self._anim_t = 0.0       # drives the pulsing "可交配" heart
        self.hover = False

    def rect_hot(self) -> QRectF:
        return self.rect

    def contains(self, pt: QPointF) -> bool:
        return self.rect.contains(pt)

    def can_breed(self) -> bool:
        return (self.fullness > BREED_THRESHOLD and
                self.energy > BREED_THRESHOLD and
                self.happy > BREED_THRESHOLD)

    def on_eat(self):
        # One bite per cooldown window; a meal tops the bar up by EAT_GAIN.
        if self._eat_cd > 0.0:
            return
        self.fullness = min(1.0, self.fullness + EAT_GAIN)
        self.happy = min(1.0, self.happy + 0.10)
        self._eat_cd = EAT_COOLDOWN

    def on_sleep(self):
        self.energy = min(1.0, self.energy + SLEEP_GAIN)
        self.happy = min(1.0, self.happy + 0.05)

    def on_train(self):
        self.energy = max(0.0, self.energy - TRAIN_ENERGY)
        self.happy = min(1.0, self.happy + TRAIN_HAPPY)
        self.fullness = max(0.0, self.fullness - TRAIN_FULLNESS)

    def decay(self, sleeping=False):
        # Per-second rates scaled by DT so behaviour is frame-rate independent.
        self.fullness = max(0.0, self.fullness - FULLNESS_DECAY * DT)
        if sleeping:
            # resting slowly recharges energy instead of draining it
            self.energy = min(1.0, self.energy + ENERGY_DECAY * 4 * DT)
        else:
            self.energy = max(0.0, self.energy - ENERGY_DECAY * DT)
        # mood drifts toward its baseline (a lone bug gets a little lonely)
        if self.happy > MOOD_BASELINE:
            self.happy = max(MOOD_BASELINE, self.happy - MOOD_DRIFT * DT)
        else:
            self.happy = min(MOOD_BASELINE, self.happy + MOOD_DRIFT * DT)
        if self._eat_cd > 0.0:
            self._eat_cd = max(0.0, self._eat_cd - DT)
        self._anim_t = (self._anim_t + DT) % 10.0
        self.in_heat = self.can_breed()

    def decay_offline(self, seconds):
        """Apply the whole stat drift over `seconds` at once (used when the
        app was closed and we catch the pet up on load)."""
        seconds = max(0.0, float(seconds))
        self.fullness = max(0.0, self.fullness - FULLNESS_DECAY * seconds)
        self.energy = max(0.0, self.energy - ENERGY_DECAY * seconds)
        if self.happy > MOOD_BASELINE:
            self.happy = max(MOOD_BASELINE, self.happy - MOOD_DRIFT * seconds)
        else:
            self.happy = min(MOOD_BASELINE, self.happy + MOOD_DRIFT * seconds)
        self._eat_cd = max(0.0, self._eat_cd - seconds)
        self.in_heat = self.can_breed()

    def draw(self, p: QPainter):
        p.save()
        # semi-transparent so it never blocks the view while working
        p.setOpacity(HUD_OPACITY)
        # panel
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect), 10, 10)
        p.fillPath(path, QColor(20, 28, 36, 110))
        p.setPen(QPen(QColor(120, 200, 255, 140), 1))
        p.drawPath(path)
        # title + heat badge
        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(180, 220, 255))
        p.drawText(QPointF(self.rect.x() + 10, self.rect.y() + 16), "甲虫状态")
        if self.in_heat:
            bx = self.rect.x() + self.rect.width() - 64
            by = self.rect.y() + 6
            # pulsing heart
            pulse = 0.6 + 0.4 * abs(math.sin(self._anim_t if hasattr(self, "_anim_t") else 0))
            p.setBrush(QColor(212, 83, 126, int(200 * pulse)))
            p.setPen(Qt.NoPen)
            hx, hy = bx + 8, by + 11
            p.drawEllipse(QPointF(hx - 3, hy - 1), 3.2, 3.2)
            p.drawEllipse(QPointF(hx + 3, hy - 1), 3.2, 3.2)
            p.drawPolygon([
                QPointF(hx - 6, hy + 1), QPointF(hx, hy + 7), QPointF(hx + 6, hy + 1),
            ])
            p.setPen(QColor(255, 200, 220))
            p.setFont(QFont("Microsoft YaHei", 8, QFont.Bold))
            p.drawText(QPointF(bx + 14, by + 14), "可交配")
        # bars
        bar_x = self.rect.x() + 38
        bar_w = self.rect.width() - 48
        row_h = 18
        base_y = self.rect.y() + 26
        for i, (label, value, color) in enumerate([
            ("饱", self.fullness, QColor(120, 220, 140)),
            ("能", self.energy,    QColor(255, 200, 80)),
            ("悦", self.happy,     QColor(255, 140, 180)),
        ]):
            y = base_y + i * row_h
            p.setPen(QColor(220, 230, 240))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(QPointF(self.rect.x() + 10, y + 12), label)
            # track
            track = QRectF(bar_x, y + 3, bar_w, 12)
            p.setBrush(QColor(50, 60, 70))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(track, 5, 5)
            # fill
            fill = QRectF(bar_x, y + 3, bar_w * clamp(value, 0.0, 1.0), 12)
            p.setBrush(color)
            p.drawRoundedRect(fill, 5, 5)
        p.restore()


# ===================== Offspring (life cycle) =====================
class Offspring:
    """The clutch laid after a mating.  Rove beetles are holometabolous, so
    the offspring runs the full metamorphosis: egg -> hatching -> larva ->
    growth (pupa + sub-adult) -> adult.  Drawn with vectors (no new sprites)."""
    STAGE_EGG = "EGG"
    STAGE_HATCH = "HATCH"
    STAGE_LARVA = "LARVA"
    STAGE_GROWTH = "GROWTH"
    STAGE_ADULT = "ADULT"
    ORDER = [STAGE_EGG, STAGE_HATCH, STAGE_LARVA, STAGE_GROWTH, STAGE_ADULT]
    NAMES = {STAGE_EGG: "卵期", STAGE_HATCH: "孵化后期", STAGE_LARVA: "幼年期",
             STAGE_GROWTH: "成长期", STAGE_ADULT: "成年期"}
    DURATIONS = {STAGE_EGG: EGG_PERIOD, STAGE_HATCH: HATCH_PERIOD,
                 STAGE_LARVA: LARVA_PERIOD, STAGE_GROWTH: GROWTH_PERIOD,
                 STAGE_ADULT: float("inf")}
    SIZE = {STAGE_EGG: 0.55, STAGE_HATCH: 0.65, STAGE_LARVA: 0.85,
            STAGE_GROWTH: 1.05, STAGE_ADULT: 1.25}

    def __init__(self):
        self.stage = self.STAGE_EGG
        self.idx = 0
        self.t = 0.0           # wall-seconds spent in the current stage
        self.anim_t = 0.0
        self.done = False      # has reached the adult stage

    def tick(self, dt):
        self.anim_t = (self.anim_t + dt) % 10.0
        if self.stage == self.STAGE_ADULT:
            return
        self.t += dt
        dur = self.DURATIONS[self.stage]
        if self.t >= dur:
            self.t -= dur
            self.idx = min(self.idx + 1, len(self.ORDER) - 1)
            self.stage = self.ORDER[self.idx]
            if self.stage == self.STAGE_ADULT:
                self.done = True

    def progress(self):
        """0..1 within the current stage (adult reports 1.0)."""
        if self.stage == self.STAGE_ADULT:
            return 1.0
        return clamp(self.t / self.DURATIONS[self.stage], 0.0, 1.0)

    def stage_name(self):
        return self.NAMES[self.stage]

    def draw_in_nest(self, p: QPainter, cx, cy):
        s = self.SIZE[self.stage]
        if self.stage in (self.STAGE_EGG, self.STAGE_HATCH):
            self._draw_egg(p, cx, cy, self.stage == self.STAGE_HATCH, s)
        elif self.stage == self.STAGE_LARVA:
            self._draw_larva(p, cx, cy, s)
        elif self.stage == self.STAGE_GROWTH:
            self._draw_pupa(p, cx, cy, self.progress(), s)
        else:
            self._draw_beetle(p, cx, cy, s)

    def _draw_egg(self, p, cx, cy, hatching, s):
        p.save()
        pulse = 1.0 + 0.05 * math.sin(self.anim_t * 3)
        w = 22 * s * pulse
        h = 13 * s
        col = QColor(250, 238, 218) if not hatching else QColor(250, 220, 130)
        pen = QPen(QColor(180, 160, 110), 1)
        p.setPen(pen)
        p.setBrush(col)
        p.drawEllipse(QPointF(cx, cy), w, h)
        # papilla at the front (left) tip
        p.drawEllipse(QPointF(cx - w, cy), 2.5, 2.5)
        if hatching:
            p.setPen(QPen(QColor(150, 110, 60), 1.4))
            p.drawArc(QRectF(cx - w * 0.6, cy - h * 0.6, w * 1.2, h * 1.2),
                      200 * 16, 150 * 16)
        p.restore()

    def _draw_larva(self, p, cx, cy, s):
        """Campodeiform rove-beetle larva: distinct head capsule with
        stemmata and antennae, three leg-bearing thoracic segments, a
        tapering abdomen and two tail urogomphi."""
        p.save()
        wig = math.sin(self.anim_t * 6) * 2          # slow squirm
        L = 52 * s
        H = 17 * s
        x0 = cx - L * 0.5
        y0 = cy + wig

        def xy(fx, fy):
            return (x0 + L * fx, y0 + H * fy)

        def pt(fx, fy):
            return QPointF(x0 + L * fx, y0 + H * fy)

        body_col = QColor(202, 164, 110)
        edge = QColor(142, 104, 60)
        seg = QColor(166, 126, 76)

        # ---- body: spindle tapering into the tail ----
        body = QPainterPath()
        body.moveTo(*xy(0.11, -0.32))
        body.cubicTo(*xy(0.34, -0.52), *xy(0.60, -0.50), *xy(0.84, -0.30))
        body.cubicTo(*xy(0.94, -0.20), *xy(0.99, -0.07), *xy(1.00, 0.0))
        body.cubicTo(*xy(0.99, 0.07), *xy(0.94, 0.20), *xy(0.84, 0.30))
        body.cubicTo(*xy(0.60, 0.50), *xy(0.34, 0.52), *xy(0.11, 0.32))
        body.closeSubpath()
        grad = QLinearGradient(0, y0 - H * 0.5, 0, y0 + H * 0.5)
        grad.setColorAt(0.0, body_col.lighter(106))
        grad.setColorAt(0.55, body_col)
        grad.setColorAt(1.0, body_col.darker(112))
        p.setPen(QPen(edge, 1.2))
        p.setBrush(grad)
        p.drawPath(body)

        # ---- thoracic + abdominal segments (kept inside the body outline) ----
        p.setPen(QPen(seg, 0.8))
        p.setBrush(Qt.NoBrush)
        for i, hh in enumerate((0.34, 0.38, 0.41, 0.43, 0.45, 0.45, 0.42, 0.36, 0.28)):
            fx = 0.18 + i * 0.083
            a = QPainterPath()
            a.moveTo(*xy(fx, -hh))
            a.quadTo(*xy(fx + 0.025, 0.0), *xy(fx, hh))
            p.drawPath(a)

        # ---- three pairs of thoracic legs ----
        p.setPen(QPen(edge, 1.0))
        for lx in (0.19, 0.31, 0.43):
            p.drawLine(pt(lx, 0.40), pt(lx + 0.02, 0.74))
            p.drawLine(pt(lx + 0.02, 0.74), pt(lx + 0.075, 0.98))

        # ---- head capsule ----
        p.setPen(QPen(edge.darker(108), 1.1))
        p.setBrush(QColor(158, 116, 68))
        p.drawEllipse(pt(0.065, 0.0), L * 0.072, H * 0.34)
        # antennae
        p.setPen(QPen(edge, 0.9))
        p.drawLine(pt(0.010, -0.10), pt(-0.100, -0.28))
        p.drawLine(pt(0.010, 0.10), pt(-0.090, 0.28))
        # stemmata (eye spots)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(58, 42, 28))
        p.drawEllipse(pt(0.050, -0.14), 1.3 * s, 1.3 * s)
        p.drawEllipse(pt(0.050, 0.14), 1.3 * s, 1.3 * s)

        # ---- tail urogomphi ----
        p.setPen(QPen(edge, 0.9))
        p.drawLine(pt(0.95, -0.07), pt(1.06, -0.20))
        p.drawLine(pt(0.95, 0.07), pt(1.06, 0.20))
        p.restore()

    def _draw_pupa(self, p, cx, cy, prog, s):
        """Rove-beetle pupa: cream capsule with a distinct head, folded
        antennae, abdominal segments and wing pads.  It grows with `prog`
        and tans toward the adult colour as eclosion approaches."""
        p.save()
        breath = 1.0 + 0.02 * math.sin(self.anim_t * 2.0)   # slow, pupae barely move
        ext = 1.0 + prog * 0.55
        L = 44 * s * ext
        H = 20 * s * breath
        x0 = cx - L * 0.5          # head end (left)
        y0 = cy

        def xy(fx, fy):            # -> (x, y) for path drawing
            return (x0 + L * fx, y0 + H * fy)

        def pt(fx, fy):            # -> QPointF for drawLine / drawEllipse
            return QPointF(x0 + L * fx, y0 + H * fy)

        # colours tan toward the adult as the imago develops inside
        base = QColor(int(240 - 55 * prog), int(232 - 55 * prog), int(205 - 58 * prog))
        edge = QColor(int(178 - 30 * prog), int(166 - 32 * prog), int(132 - 26 * prog))
        seg = QColor(int(198 - 30 * prog), int(184 - 32 * prog), int(148 - 26 * prog))

        # ---- body: capsule, abdomen fullest around two thirds ----
        # the front is pinched into a short "neck" so the head reads as attached
        body = QPainterPath()
        body.moveTo(*xy(0.16, -0.30))
        body.cubicTo(*xy(0.38, -0.60), *xy(0.62, -0.58), *xy(0.90, -0.30))
        body.cubicTo(*xy(1.00, -0.08), *xy(1.00, 0.08), *xy(0.90, 0.30))
        body.cubicTo(*xy(0.60, 0.55), *xy(0.30, 0.54), *xy(0.16, 0.30))
        body.closeSubpath()
        grad = QLinearGradient(0, y0 - H * 0.6, 0, y0 + H * 0.6)
        grad.setColorAt(0.0, base.lighter(107))
        grad.setColorAt(0.55, base)
        grad.setColorAt(1.0, base.darker(113))
        p.setPen(QPen(edge, 1.3))
        p.setBrush(grad)
        p.drawPath(body)

        # ---- abdominal segments (arcs bowing toward the tail) ----
        p.setPen(QPen(seg, 0.9))
        p.setBrush(Qt.NoBrush)
        for i in range(6):
            fx = 0.34 + i * 0.108
            hh = H * (0.48 - 0.036 * i)
            a = QPainterPath()
            a.moveTo(*xy(fx, -hh / H))
            a.quadTo(*xy(fx + 0.03, 0.0), *xy(fx, hh / H))
            p.drawPath(a)

        # ---- developing wing pads: a soft ridge line along the lower flank ----
        # (a filled shape here reads as a pasted-on plate, so keep it to one
        #  faint longitudinal ridge that stays inside the body silhouette)
        p.setPen(QPen(seg, 0.7))
        p.setBrush(Qt.NoBrush)
        ridge = QPainterPath()
        ridge.moveTo(*xy(0.32, 0.26))
        ridge.cubicTo(*xy(0.50, 0.40), *xy(0.72, 0.38), *xy(0.90, 0.20))
        p.drawPath(ridge)

        # ---- folded legs: short bent stubs tucked under the belly ----
        p.setPen(QPen(edge, 0.9))
        for lx in (0.40, 0.53, 0.66):
            p.drawLine(pt(lx, 0.40), pt(lx + 0.030, 0.52))
            p.drawLine(pt(lx + 0.030, 0.52), pt(lx + 0.060, 0.62))

        # ---- head capsule, overlapping the neck ----
        p.setPen(QPen(edge, 1.1))
        p.setBrush(base.lighter(104))
        p.drawEllipse(pt(0.100, 0.0), L * 0.075, H * 0.35)
        # eye speck
        p.setPen(Qt.NoPen)
        p.setBrush(edge.darker(118))
        p.drawEllipse(pt(0.075, -0.12), 1.3 * s, 1.3 * s)
        # antennae folded back along the body
        p.setPen(QPen(edge, 1.0))
        p.setBrush(Qt.NoBrush)
        for dy in (-1, 1):
            a = QPainterPath()
            a.moveTo(*xy(0.13, dy * 0.16))
            a.quadTo(*xy(0.30, dy * 0.46), *xy(0.50, dy * 0.30))
            p.drawPath(a)

        # ---- soft sheen along the upper back ----
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        hl = QPainterPath()
        hl.moveTo(*xy(0.18, -0.34))
        hl.cubicTo(*xy(0.42, -0.50), *xy(0.66, -0.48), *xy(0.84, -0.24))
        hl.cubicTo(*xy(0.62, -0.36), *xy(0.38, -0.38), *xy(0.18, -0.34))
        p.drawPath(hl)
        p.restore()

    def _draw_beetle(self, p, cx, cy, s):
        """Adult rove beetle -- the form the whole life cycle grows into.

        The proportions below are measured off `sprites/walk_right.png`, whose
        body is 673 px long.  As fractions of that length the layout is

            head    0.000 - 0.146   round, half-height 0.40 H
            neck    0.146 - 0.168   pinched, 0.26 H
            pronotum 0.160 - 0.300  red shield, 0.43 H
            elytra  0.294 - 0.510   SHORT black covers, 0.62 H (the tallest
                                    part of the body -- it forms a hump)
            abdomen 0.300 - 0.866   banded orange, 0.51 H
            tail    0.866 - 1.000   black cone, tapering to 0.19 H

        Colours are sampled from the same sprite, so the offspring visibly
        grows up into its parent rather than into a generic blob.

        It also has to keep moving: this was the only stage that ignored
        `anim_t`, and `tick()` returns early once ADULT is reached, so a grown
        beetle used to sit there as a frozen silhouette."""
        p.save()
        # ---- idle motion ---------------------------------------------------
        burst = self.anim_t % 6.0
        flutter = math.sin(burst / 1.2 * math.pi) ** 2 if burst < 1.2 else 0.0
        breath = 1.0 + 0.03 * math.sin(self.anim_t * 0.9)
        sway = math.sin(self.anim_t * 1.7) * 0.055 + math.sin(self.anim_t * 3.9) * 0.022

        L = 64.0 * s                     # nose-to-tail length
        H = 12.2 * s * breath            # vertical unit (NOT the half-height)
        x0 = cx - L * 0.40               # antennae stick out to the left
        y0 = cy - 1.5 * s * flutter      # the body lifts during a flutter

        # The pet's sprite stands head-high and tail-low.  A perfectly level
        # beetle reads as stiff, so the whole body is rotated ~5 deg about its
        # own centre -- head end up, tail end down.
        _a = math.radians(5.0)
        _ca, _sa = math.cos(_a), math.sin(_a)

        def xy(fx, fy):
            dx, dy = L * (fx - 0.5), H * fy
            return (x0 + L * 0.5 + dx * _ca - dy * _sa,
                    y0 + dx * _sa + dy * _ca)

        def pt(fx, fy):
            return QPointF(*xy(fx, fy))

        # palette sampled from sprites/walk_right.png
        head_c = QColor(198, 60, 34)
        pro_c = QColor(184, 48, 28)
        abdo_c = QColor(214, 92, 46)
        band_c = QColor(146, 44, 20)
        black = QColor(38, 33, 30)
        eye_c = QColor(22, 18, 16)
        leg_hi = QColor(202, 100, 48)
        leg_lo = QColor(46, 40, 35)
        rim = QColor(118, 30, 16)

        # ---- far-side legs first, so the body overlaps them ----------------
        p.setPen(QPen(leg_lo.lighter(150), 1.4 * s, Qt.SolidLine, Qt.RoundCap))
        for fx, k in ((0.320, 0.92), (0.460, 1.00), (0.600, 0.94)):
            p.drawLine(pt(fx, 0.30), pt(fx - 0.048, 0.84 * k))
            p.drawLine(pt(fx - 0.048, 0.84 * k), pt(fx + 0.020, 1.46 * k))

        # ---- abdomen: long, plated, tapering to the black tail -------------
        abdo = QPainterPath()
        abdo.moveTo(*xy(0.300, -0.36))
        abdo.cubicTo(*xy(0.380, -0.52), *xy(0.520, -0.53), *xy(0.640, -0.52))
        abdo.cubicTo(*xy(0.760, -0.51), *xy(0.852, -0.47), *xy(0.920, -0.34))
        abdo.cubicTo(*xy(0.972, -0.23), *xy(1.000, -0.11), *xy(1.005, 0.0))
        abdo.cubicTo(*xy(1.000, 0.11), *xy(0.972, 0.23), *xy(0.920, 0.34))
        abdo.cubicTo(*xy(0.852, 0.47), *xy(0.760, 0.51), *xy(0.640, 0.52))
        abdo.cubicTo(*xy(0.520, 0.53), *xy(0.380, 0.52), *xy(0.300, 0.36))
        abdo.closeSubpath()
        ag = QLinearGradient(0, y0 - H * 0.53, 0, y0 + H * 0.53)
        ag.setColorAt(0.0, abdo_c.lighter(118))
        ag.setColorAt(0.55, abdo_c)
        ag.setColorAt(1.0, abdo_c.darker(136))
        p.setPen(QPen(band_c.darker(130), 1.0))
        p.setBrush(ag)
        p.drawPath(abdo)

        p.save()
        p.setClipPath(abdo)          # plates + tail stay inside the outline
        # Tergites.  Without these the abdomen is one smooth cone and the
        # beetle stops looking like the sprite it grew out of.  Kept faint so
        # the gradient above still carries the shading.
        bounds = [0.330 + i * 0.055 for i in range(12)]

        def _bow(fx, span=0.032, reach=0.80):
            q = QPainterPath()
            q.moveTo(*xy(fx, -reach))
            q.quadTo(*xy(fx + span, 0.0), *xy(fx, reach))
            return q

        p.setPen(Qt.NoPen)
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            plate = QPainterPath()
            plate.moveTo(*xy(a, -0.80))
            plate.quadTo(*xy(a + 0.032, 0.0), *xy(a, 0.80))
            plate.lineTo(*xy(b, 0.80))
            plate.quadTo(*xy(b + 0.032, 0.0), *xy(b, -0.80))
            plate.closeSubpath()
            p.setBrush(QColor(255, 255, 255, 26) if i % 2 == 0
                       else QColor(70, 24, 12, 30))
            p.drawPath(plate)
        p.setPen(QPen(band_c.darker(126), 0.8))
        p.setBrush(Qt.NoBrush)
        for fx in bounds:
            p.drawPath(_bow(fx))
        tip = QPainterPath()             # the black tail cone
        tip.moveTo(*xy(0.866, -0.80))
        tip.lineTo(*xy(1.12, -0.80))
        tip.lineTo(*xy(1.12, 0.80))
        tip.lineTo(*xy(0.866, 0.80))
        tip.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(black)
        p.drawPath(tip)
        sheen = QLinearGradient(0, y0 - H * 0.53, 0, y0 + H * 0.14)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 92))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        p.drawPath(abdo)
        p.restore()

        # ---- elytra: the SHORT black wing covers (rove-beetle signature) ---
        # In the sprite these are the TALLEST part of the body -- they form a
        # hump above the abdomen -- but they only reach halfway down it.
        ely = QPainterPath()
        ely.moveTo(*xy(0.292, -0.38))
        ely.cubicTo(*xy(0.300, -0.62), *xy(0.395, -0.66), *xy(0.470, -0.56))
        ely.cubicTo(*xy(0.505, -0.50), *xy(0.516, -0.30), *xy(0.516, -0.10))
        ely.cubicTo(*xy(0.452, 0.52), *xy(0.342, 0.50), *xy(0.328, 0.28))
        ely.closeSubpath()
        p.save()
        p.translate(0, -1.2 * s * flutter)      # covers crack open on a flutter
        eg = QLinearGradient(0, y0 - H * 0.66, 0, y0 + H * 0.50)
        eg.setColorAt(0.0, black.lighter(235))
        eg.setColorAt(0.42, black.lighter(130))
        eg.setColorAt(1.0, black.darker(112))
        p.setPen(QPen(QColor(16, 13, 11), 1.1))
        p.setBrush(eg)
        p.drawPath(ely)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawEllipse(pt(0.362, -0.36), L * 0.052, H * 0.12)
        p.restore()

        # ---- pronotum: the red-orange thorax shield ------------------------
        pro = QPainterPath()
        pro.moveTo(*xy(0.152, -0.26))
        pro.cubicTo(*xy(0.162, -0.44), *xy(0.235, -0.48), *xy(0.272, -0.38))
        pro.cubicTo(*xy(0.296, -0.30), *xy(0.302, -0.14), *xy(0.302, 0.0))
        pro.cubicTo(*xy(0.302, 0.14), *xy(0.296, 0.30), *xy(0.272, 0.38))
        pro.cubicTo(*xy(0.235, 0.48), *xy(0.162, 0.44), *xy(0.152, 0.26))
        pro.closeSubpath()
        pg = QLinearGradient(0, y0 - H * 0.44, 0, y0 + H * 0.44)
        pg.setColorAt(0.0, pro_c.lighter(126))
        pg.setColorAt(0.55, pro_c)
        pg.setColorAt(1.0, pro_c.darker(134))
        p.setPen(QPen(rim, 1.2))
        p.setBrush(pg)
        p.drawPath(pro)

        # ---- head, on a pinched neck --------------------------------------
        neck = QPainterPath()
        neck.moveTo(*xy(0.118, -0.24))
        neck.lineTo(*xy(0.178, -0.27))
        neck.lineTo(*xy(0.178, 0.27))
        neck.lineTo(*xy(0.118, 0.24))
        neck.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(rim.darker(114))
        p.drawPath(neck)

        hd = QPainterPath()
        hd.moveTo(*xy(0.018, -0.20))
        hd.cubicTo(*xy(0.026, -0.38), *xy(0.070, -0.44), *xy(0.112, -0.39))
        hd.cubicTo(*xy(0.142, -0.35), *xy(0.152, -0.22), *xy(0.152, 0.0))
        hd.cubicTo(*xy(0.152, 0.22), *xy(0.142, 0.35), *xy(0.112, 0.39))
        hd.cubicTo(*xy(0.070, 0.44), *xy(0.026, 0.38), *xy(0.018, 0.20))
        hd.closeSubpath()
        hg = QLinearGradient(0, y0 - H * 0.44, 0, y0 + H * 0.44)
        hg.setColorAt(0.0, head_c.lighter(124))
        hg.setColorAt(0.6, head_c)
        hg.setColorAt(1.0, head_c.darker(134))
        p.setPen(QPen(rim, 1.1))
        p.setBrush(hg)
        p.drawPath(hd)

        p.setPen(Qt.NoPen)               # eye + specular dot
        p.setBrush(eye_c)
        p.drawEllipse(pt(0.098, -0.14), L * 0.017, H * 0.115)
        p.setBrush(QColor(255, 255, 255, 160))
        p.drawEllipse(pt(0.092, -0.18), 0.8 * s, 0.8 * s)
        p.setPen(QPen(rim.darker(115), 1.1))   # mandibles
        p.drawLine(pt(0.024, -0.04), pt(-0.012, -0.11))
        p.drawLine(pt(0.024, 0.04), pt(-0.012, 0.11))

        # ---- antennae: long, beaded, sweeping forward and up ---------------
        # Control point sits near the head, so each antenna leaves the head
        # almost straight and then curves away -- a symmetric Bezier here
        # renders as two rigid rods.
        for dy, k in ((-1, 1.0), (1, 0.62)):
            a0 = (0.030, dy * 0.15)
            a1 = (-0.055, dy * (0.40 + sway * 1.4))
            a2 = (-0.255, dy * (1.00 + sway * 2.6) * k)
            seg = []
            for i in range(11):          # sampled quadratic Bezier -> beads
                t = i / 10.0
                u = 1.0 - t
                seg.append((u * u * a0[0] + 2 * u * t * a1[0] + t * t * a2[0],
                            u * u * a0[1] + 2 * u * t * a1[1] + t * t * a2[1]))
            shaft = QPainterPath()
            shaft.moveTo(*xy(*seg[0]))
            for q in seg[1:]:
                shaft.lineTo(*xy(*q))
            p.setPen(QPen(leg_lo, 1.1 * s, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPath(shaft)
            p.setPen(Qt.NoPen)
            p.setBrush(leg_lo)
            for i, q in enumerate(seg[1:], start=1):
                # moniliform: the beads shrink toward the tip
                r = (1.20 - 0.048 * i) * s
                p.drawEllipse(pt(*q), r, r)

        # ---- near-side legs: orange femur, dark tibia, short tarsus --------
        # The sprite's feet reach ~0.23 L below the abdomen, i.e. fy ~ 1.6.
        for fx, tx, ty in ((0.258, 0.202, 1.54),
                           (0.402, 0.352, 1.74),
                           (0.548, 0.620, 1.56)):
            knee = (fx - 0.052, 0.86)
            p.setPen(QPen(leg_hi, 3.0 * s, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pt(fx, 0.30), pt(*knee))
            p.setPen(QPen(leg_lo, 1.8 * s, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pt(*knee), pt(tx, ty))
            p.setPen(QPen(leg_lo, 1.0 * s, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pt(tx, ty), pt(tx + 0.042, ty + 0.14))
        p.restore()

    def draw_panel(self, p: QPainter, rect: QRectF):
        """Small status card: stage name + progress bar."""
        p.save()
        # same semi-transparent feel as the stats panel
        p.setOpacity(HUD_OPACITY)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 10, 10)
        p.fillPath(path, QColor(20, 28, 36, 110))
        p.setPen(QPen(QColor(120, 200, 255, 140), 1))
        p.drawPath(path)
        p.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        p.setPen(QColor(180, 220, 255))
        p.drawText(QPointF(rect.x() + 10, rect.y() + 16), "后代")
        p.setFont(QFont("Microsoft YaHei", 9))
        p.setPen(QColor(220, 230, 240))
        p.drawText(QPointF(rect.x() + 46, rect.y() + 16), self.stage_name())
        if self.stage == self.STAGE_ADULT:
            # A 100%-full bar reads as "still loading, never finishes", which
            # is exactly what made a grown pet look stuck.  Say it in words.
            p.setPen(QColor(150, 220, 170))
            p.drawText(QPointF(rect.x() + 10, rect.y() + 34),
                       "已成年 · 满值后右键可再召唤伴侣，养下一窝")
            p.restore()
            return
        bar_x = rect.x() + 10
        bar_w = rect.width() - 20
        by = rect.y() + 26
        p.setBrush(QColor(50, 60, 70))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bar_x, by, bar_w, 10), 5, 5)
        p.setBrush(QColor(153, 60, 29))
        p.drawRoundedRect(QRectF(bar_x, by, bar_w * self.progress(), 10), 5, 5)
        p.restore()


# ===================== Mating (breeding sequence) =====================
class Mating:
    """Drives a single breeding event between the initiator bug and its
    summoned partner:

        approach  -> walk the two bugs to a meeting point, facing each other
        nuzzle    -> ~MATING_ANIM seconds of heart particles (the "mating")
        return    -> both fly back to the nest (each 'returns to its nest')
        wait      -> MATING_TO_EGG seconds later, lay an egg in the initiator's nest
        done

    The controller owns the movement of both bugs while they are in
    STATE_MATING; the Bug.tick() AI is suspended for them during that time.
    """

    PHASE_APPROACH = "approach"
    PHASE_NUZZLE = "nuzzle"
    PHASE_RETURN = "return"
    PHASE_WAIT = "wait"
    PHASE_DONE = "done"

    def __init__(self, bug: "Bug", mate: "Bug", nest_rect: QRectF,
                 seed: int = None, t0: float = None, mirror: bool = False):
        """`mirror=True` for the ACCEPTOR side of a cross-PC mating: the two
        peers must agree on a single shared world, so the acceptor's own bug
        takes the RIGHT meeting spot and drives its (remote) mate to the
        LEFT -- exactly where the initiator's controller put it.  Without
        this the two controllers fight over the remote bug's position and
        the approach phase never completes."""
        self.bug = bug
        self.mate = mate
        self.mirror = mirror
        self.nest_rect = nest_rect
        self.phase = self.PHASE_APPROACH
        self.t = 0.0
        self.hearts = []
        # Deterministic RNG for cross-PC sync (both peers get the same seed)
        self.seed = seed if seed is not None else random.randrange(1 << 31)
        self.t0 = t0 if t0 is not None else 0.0
        self.rng = random.Random(self.seed)
        # Meeting point: midpoint between the two bugs right now.
        bc = bug.center()
        mc = mate.center()
        self.mid = QPointF((bc.x() + mc.x()) / 2, (bc.y() + mc.y()) / 2)
        bug.state = Bug.STATE_MATING
        mate.state = Bug.STATE_MATING

    def _nest_pos(self, dx_offset=0.0):
        c = self.nest_rect.center()
        # use the bug's own (possibly shrunk) footprint so it rests centred
        return QPointF(c.x() - self.bug.w() / 2 + dx_offset,
                       c.y() - self.bug.h() / 2)

    def _move_toward(self, bug, target, dt, speed=2.6):
        dx = target.x() - bug.x
        dy = target.y() - bug.y
        d = math.hypot(dx, dy)
        step = speed * dt * MOVE_FPS          # px per frame (dt*MOVE_FPS ~ 1)
        if d <= max(step, 0.5):
            bug.x = target.x()
            bug.y = target.y()
            return True
        bug.x += dx / d * step
        bug.y += dy / d * step
        return False

    def tick(self, dt, screen_w, screen_h):
        """Advance the sequence. Returns 'lay_egg' exactly once (phase -> DONE)."""
        if self.phase == self.PHASE_APPROACH:
            if self.mirror:
                # acceptor: own bug goes RIGHT, remote mate goes LEFT
                tgt_b = QPointF(self.mid.x() + 70, self.mid.y())
                tgt_m = QPointF(self.mid.x() - 70, self.mid.y())
                self.bug.facing_right = False
                self.mate.facing_right = True
            else:
                tgt_b = QPointF(self.mid.x() - 70, self.mid.y())
                tgt_m = QPointF(self.mid.x() + 70, self.mid.y())
                self.bug.facing_right = True
                self.mate.facing_right = False
            b_done = self._move_toward(self.bug, tgt_b, dt)
            m_done = self._move_toward(self.mate, tgt_m, dt)
            if b_done and m_done:
                self.phase = self.PHASE_NUZZLE
                self.t = 0.0
        elif self.phase == self.PHASE_NUZZLE:
            self.t += dt
            if self.rng.random() < 0.5:
                self._spawn_heart()
            if self.t >= MATING_ANIM:
                self.phase = self.PHASE_RETURN
                self.t = 0.0
        elif self.phase == self.PHASE_RETURN:
            if self.mirror:
                # acceptor mirrors the initiator's layout: its own bug rests
                # LEFT of the mate, so both screens agree on one world
                tb = self._nest_pos(-60.0)
                tm = self._nest_pos(0.0)
            else:
                tb = self._nest_pos(0.0)
                tm = self._nest_pos(-60.0)     # mate settles slightly left of the initiator
            b_done = self._move_toward(self.bug, tb, dt, speed=3.6)
            m_done = self._move_toward(self.mate, tm, dt, speed=3.6)
            if b_done and m_done:
                self.bug.x, self.bug.y = tb.x(), tb.y()
                self.mate.x, self.mate.y = tm.x(), tm.y()
                self.bug.state = Bug.STATE_SLEEPING
                self.mate.state = Bug.STATE_SLEEPING
                self.phase = self.PHASE_WAIT
                self.t = 0.0
        elif self.phase == self.PHASE_WAIT:
            self.t += dt
            if self.t >= MATING_TO_EGG:
                self.phase = self.PHASE_DONE
                return "lay_egg"
        self._update_hearts(dt)
        return None

    def _spawn_heart(self):
        x = (self.bug.center().x() + self.mate.center().x()) / 2 + self.rng.uniform(-12, 12)
        y = min(self.bug.center().y(), self.mate.center().y()) - self.rng.uniform(12, 46)
        self.hearts.append({"x": x, "y": y, "vy": -34,
                            "life": 1.0, "size": self.rng.uniform(10, 18)})

    def _update_hearts(self, dt):
        for h in self.hearts:
            h["y"] += h["vy"] * dt
            h["life"] -= dt * 0.8
        self.hearts = [h for h in self.hearts if h["life"] > 0]

    def draw_hearts(self, p: QPainter):
        if not self.hearts:
            return
        p.save()
        p.setPen(Qt.NoPen)
        for h in self.hearts:
            a = clamp(h["life"], 0.0, 1.0)
            p.setBrush(QColor(255, 120, 170, int(220 * a)))
            hx, hy, s = h["x"], h["y"], h["size"]
            p.drawEllipse(QPointF(hx - s * 0.22, hy - s * 0.10), s * 0.22, s * 0.22)
            p.drawEllipse(QPointF(hx + s * 0.22, hy - s * 0.10), s * 0.22, s * 0.22)
            p.drawPolygon([
                QPointF(hx - s * 0.45, hy + s * 0.04),
                QPointF(hx, hy + s * 0.42),
                QPointF(hx + s * 0.45, hy + s * 0.04),
            ])
        p.restore()


# ===================== Net client (cross-PC play) =====================
class NetClient:
    """Async WebSocket client running in a background thread so it doesn't
    block the PyQt5 main loop.  Incoming messages are delivered via a callback
    that is called from the asyncio thread; the overlay should push them into
    a thread-safe queue or QMetaObject.invokeMethod if Qt widgets are touched.

    Usage:
        nc = NetClient(room="ROOM-123", name="甲", color="#85B7EB",
                       on_msg=lambda d: overlay._on_net_msg(d))
        nc.start("ws://localhost:8765")
        nc.send({"type":"state", "x":200, ...})
    """

    def __init__(self, room: str, name: str, color: str, on_msg):
        self.room = room
        self.name = name
        self.color = color
        self.on_msg = on_msg
        self.ws = None
        self.loop = None
        self.thread = None
        self.connected = False
        self._url = None
        self._stop = threading.Event()
        self._aq = None            # asyncio.Queue, created per connection

    def start(self, url: str):
        self._url = url
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Politely disconnect (peer gets a 'bye') and end the thread."""
        self._stop.set()
        self.send({"type": "bye"})      # wakes the blocked sender

    def _run(self):
        # Retry forever: the colleague often opens the pet BEFORE the host's
        # relay is listening (or Tailscale blinks for a moment).  A single
        # failed attempt must not permanently kill the net layer.
        while not self._stop.is_set():
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.loop = loop
                loop.run_until_complete(self._client())
            except Exception as e:
                print(f"[net] connect failed ({e!r}); "
                      f"retry in {NET_RETRY_SECONDS:.0f}s")
            finally:
                self.connected = False
                self._aq = None
                if loop is not None:
                    try:
                        loop.close()
                    except Exception:
                        pass
                self.loop = None
            if self._stop.is_set():
                break
            time.sleep(NET_RETRY_SECONDS)

    async def _client(self):
        # Exceptions propagate to _run, which logs and retries.
        # proxy=None: our relay is a LAN/Tailscale address -- never let a
        # system/sandbox HTTP proxy intercept it.
        async with _websockets.connect(self._url, proxy=None) as ws:
            self.ws = ws
            self._aq = asyncio.Queue()
            self.connected = True
            await ws.send(json.dumps({
                "type": "hello", "room": self.room,
                "name": self.name, "color": self.color,
            }))
            recv_task = asyncio.ensure_future(self._recv(ws))
            send_task = asyncio.ensure_future(self._sender())
            done, pending = await asyncio.wait(
                {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                if not t.cancelled():
                    t.exception()   # retrieve, or asyncio warns at GC time

    async def _sender(self):
        while True:
            msg = await self._aq.get()
            try:
                await self.ws.send(json.dumps(msg))
                if msg.get("type") == "bye":
                    # graceful shutdown: tell the peer, then hang up so the
                    # recv task finishes and the thread can exit cleanly
                    await self.ws.close()
                    break
            except Exception:
                break

    async def _recv(self, ws):
        async for raw in ws:
            try:
                self.on_msg(json.loads(raw))
            except Exception:
                pass

    def send(self, msg: dict):
        """Thread-safe (called from the Qt main thread): hop onto the
        client's event loop instead of using an executor thread, which would
        block interpreter shutdown."""
        loop, q = self.loop, self._aq
        if loop is None or q is None:
            return
        try:
            loop.call_soon_threadsafe(q.put_nowait, msg)
        except RuntimeError:
            pass    # loop already closed (shutting down)


# ===================== Info button =====================
class InfoButton:
    """A small 'i' button that toggles a help overlay."""

    def __init__(self, rect: QRectF):
        self.rect = rect
        self.show_help = False

    def rect_hot(self) -> QRectF:
        return self.rect

    def contains(self, pt: QPointF) -> bool:
        return self.rect.contains(pt)

    def draw(self, p: QPainter):
        # The help panel (F1) stays available even with no drawn button glyph.
        if self.show_help:
            p.save()
            self._draw_help(p)
            p.restore()
        if not SHOW_INFO_BUTTON:
            return
        p.save()
        p.setOpacity(0.9)
        p.setBrush(QColor(20, 28, 36, 200))
        p.setPen(QPen(QColor(120, 200, 255, 140), 1))
        p.drawRoundedRect(QRectF(self.rect), 10, 10)
        p.setPen(QColor(180, 220, 255))
        f = QFont("Arial", 14, QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(self.rect), Qt.AlignCenter, "i")
        p.restore()

    HELP_LINE_H = 26        # baseline-to-baseline
    HELP_PAD_TOP = 32
    HELP_PAD_BOTTOM = 16

    def _help_lines(self):
        """The help text.  Separate from the painter so the panel can be sized
        from it -- and so a test can assert the last line still fits."""
        return [
            "隐翅虫 · 互动房间",
            "",
            "• 按底部叶片按钮 → 盒子里起雾（带渐变）",
            "• 再按一下 → 罩子内陷弹回 + 雾气散去",
            "• 拖动虫子到右侧叶子窝 → 虫子自动入窝睡觉（融合）",
            "• 拖动虫子到左侧食盆 → 食盆亮识别光 → 进食动画",
            "• 拖动虫子到中央蓝色训练环 → 振翅训练",
            "• 双击虫子 → 让它飞一下",
            "• 拖动虫子 → 自由移动到任意位置",
            "• 三项满值后右键虫子 → 召唤伴侣，两虫自动交配并回窝",
            "• 右键虫子 → 联机：加入房间，即可与同事跨电脑互动、远程交配",
            "• 加房可输入房间码，或直接粘 ws://…地址（IP 变了时用）",
            "• 交配约 10 秒后，发起方窝里出现虫卵（卵→孵化→幼虫→成长→成虫）",
            "• 养到成年后它留在窝里活动；再满值召唤一次即可换下一窝",
            "• 右键虫子 → 菜单；F1 → 帮助；Esc → 退出",
            "",
            "桌面空白处仍可点击（区域穿透）",
        ]

    def _help_panel_rect(self):
        """Size the panel from the content.  It used to be a fixed 360 px tall,
        which already pushed the last two lines outside the box; deriving it
        means adding a line can never make that worse."""
        n = len(self._help_lines())
        h = self.HELP_PAD_TOP + (n - 1) * self.HELP_LINE_H + self.HELP_PAD_BOTTOM
        return QRectF(40, 80, 470, h)

    def _draw_help(self, p: QPainter):
        p.setOpacity(0.94)
        lines = self._help_lines()
        panel = self._help_panel_rect()
        path = QPainterPath()
        path.addRoundedRect(panel, 14, 14)
        p.fillPath(path, QColor(18, 24, 32, 235))
        p.setPen(QPen(QColor(120, 200, 255, 180), 1))
        p.drawPath(path)
        p.setPen(QColor(220, 235, 255))
        p.setFont(QFont("Microsoft YaHei", 11))
        for i, line in enumerate(lines):
            f = QFont("Microsoft YaHei", 13 if i == 0 else 11,
                      QFont.Bold if i == 0 else QFont.Normal)
            p.setFont(f)
            if i == 0:
                p.setPen(QColor(140, 220, 255))
            else:
                p.setPen(QColor(220, 235, 255))
            p.drawText(QPointF(panel.x() + 20,
                               panel.y() + self.HELP_PAD_TOP + i * self.HELP_LINE_H), line)


# ===================== Fog button =====================
class FogButton:
    """The leaf button on the room base.  Press it to trigger the dome fog.
    Visual: a circular ring with a leaf icon, glowing cyan.  Pulses idle,
    spins actively while fog is building / clearing."""

    def __init__(self, center: QPointF, radius: float):
        self.center = center
        self.radius = radius
        self.t = 0.0
        self.spin = 0.0           # rotation for active ring
        self.press_flash = 0.0    # 0..1 momentary flash on click

    def rect_hot(self) -> QRectF:
        r = self.radius * 1.15
        return QRectF(self.center.x() - r, self.center.y() - r, r * 2, r * 2)

    def contains(self, pt: QPointF) -> bool:
        # circular hit test (slightly forgiving)
        d = math.hypot(pt.x() - self.center.x(), pt.y() - self.center.y())
        return d <= self.radius * 1.05

    def press(self):
        self.press_flash = 1.0

    def tick(self, dome_active: bool):
        self.t += DT
        self.spin += DT * 2.4
        if dome_active:
            self.press_flash = max(self.press_flash, 0.6)
        self.press_flash = max(0.0, self.press_flash - DT * 1.8)

    def draw(self, p: QPainter, dome_active: bool):
        if not SHOW_FOG_BUTTON:
            # Invisible hotspot only: the leaf lamp is already painted in the
            # wallpaper, so the user just clicks it. No extra UI is drawn.
            return
        cx, cy = self.center.x(), self.center.y()
        r = self.radius
        p.save()

        # Only show visual feedback when active or pressed
        # Normal state: nearly invisible - just a faint ring matching the
        # wallpaper's leaf lamp style
        base_alpha = 0.12
        if dome_active:
            base_alpha = 0.35
        if self.press_flash > 0.05:
            base_alpha = max(base_alpha, self.press_flash * 0.8)

        # Outer soft halo (subtle)
        halo = QRadialGradient(QPointF(cx, cy), r * 1.8)
        halo.setColorAt(0.0, QColor(120, 230, 200, int(60 * base_alpha)))
        halo.setColorAt(1.0, QColor(120, 230, 200, 0))
        p.fillRect(QRectF(cx - r * 1.8, cy - r * 1.8, r * 3.6, r * 3.6), halo)

        # Thin ring matching the wallpaper's cyan accent color
        ring_alpha = int(100 * base_alpha)
        p.setPen(QPen(QColor(120, 230, 200, ring_alpha), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), int(r), int(r))

        # Active spinning arc
        if dome_active or self.press_flash > 0.05:
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(self.spin * 60))
            arc_pen = QPen(QColor(160, 255, 220, int(180 * base_alpha)), 2)
            p.setPen(arc_pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(int(-r * 0.7), int(-r * 0.7), int(r * 1.4), int(r * 1.4),
                      int(0 * 16), int(270 * 16))
            p.restore()

        # Leaf icon - smaller and more subtle
        self._draw_leaf(p, cx, cy, r * 0.45, base_alpha)

        p.restore()

    def _draw_leaf(self, p: QPainter, cx, cy, size, base_alpha):
        p.save()
        p.translate(cx, cy)
        wob = 4 * math.sin(self.t * 1.6) + 8 * self.press_flash * math.sin(self.t * 9)
        p.rotate(wob)
        path = QPainterPath()
        path.moveTo(0, -size)
        path.cubicTo(size * 0.95, -size * 0.3,
                     size * 0.55, size * 0.95,
                     0, size)
        path.cubicTo(-size * 0.55, size * 0.95,
                     -size * 0.95, -size * 0.3,
                     0, -size)
        fill = QLinearGradient(QPointF(-size, -size), QPointF(size, size))
        fill.setColorAt(0.0, QColor(160, 245, 215, int(180 * base_alpha)))
        fill.setColorAt(1.0, QColor(80, 200, 170, int(180 * base_alpha)))
        p.setBrush(fill)
        p.setPen(QPen(QColor(220, 255, 240, int(140 * base_alpha)), 1))
        p.drawPath(path)
        p.setPen(QPen(QColor(240, 255, 250, int(100 * base_alpha)), 0.8))
        p.drawLine(0, int(-size * 0.85), 0, int(size * 0.85))
        p.restore()


# ===================== Room Overlay (main) =====================
class RoomOverlay(QWidget):
    WM_NCHITTEST = 0x0084
    HTCLIENT = 1
    HTTRANSPARENT = -1

    def __init__(self):
        super().__init__()
        self.bug = Bug(SPRITES_DIR)
        self._setup_window()
        self._compute_zones()
        self.dome = Dome(self.zone_rect("dome"))
        self.nest = Nest(self.zone_rect("nest"))
        self.dish = Dish(QPointF(self._frac("dish", "cx") * self.sw,
                                  self._frac("dish", "cy") * self.sh),
                          self._frac("dish", "r") * self.sw)
        self.training = Training(self.zone_rect("training"))
        self.hud = StatsHUD(self.zone_rect("stats"))
        self.info = InfoButton(self.zone_rect("info_btn"))
        # breeding / offspring state
        self.mate = None          # second bug, summoned via "召唤伴侣"
        self.offspring = None     # the clutch laid after a successful mating
        self.mating = None        # active Mating controller (Phase 3)
        # cross-PC play (Phase 4)
        self.net = None           # NetClient when connected
        self.remote_bug = None    # peer bug rendered from network snapshots
        self._net_inbox = []      # thread-safe msg buffer (processed in _tick)
        self._net_send_counter = 0
        # transient on-screen net status toast (so joining is never silent)
        self._toast_text = ""
        self._toast_until = 0.0
        self._net_ok_noted = False    # already toasted "connected"
        self._net_fail_noted = False  # already toasted "retrying"
        self._peer_seen = False       # peer's first snapshot received
        self._net_wait = 0.0          # game-seconds since the current client started
        self.fog_btn = FogButton(
            QPointF(self._frac("fog_btn", "cx") * self.sw,
                    self._frac("fog_btn", "cy") * self.sh),
            self._frac("fog_btn", "r") * self.sw,
        )
        # bug start position
        self.bug.x = self.sw * 0.45
        self.bug.y = self.sh * 0.55
        # timer
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(int(1000 / MOVE_FPS))
        # mouse
        self.setMouseTracking(True)
        self._drag_bug = None          # which bug (if any) is being dragged
        # suppress clicks
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # proximity state
        self._bug_in_nest_range = False
        self._bug_in_dish_range = False
        self._bug_in_train_range = False
        # auto-save accumulator
        self._save_accum = 0.0
        # restore the previous session (bug pos, stats, offspring progress)
        loaded_ok = True
        try:
            self._load_save()
        except Exception as e:
            loaded_ok = False
            print("[save] load failed:", e)
        if loaded_ok:
            self._save_game()   # stamp a fresh save so ts tracks this launch
        else:
            # Never overwrite a save we could not read.  Doing so used to cost
            # the only copy of the offspring's progress on one bad parse.
            print("[save] previous save.json left untouched "
                  "(a fallback copy lives at save.json.bak)")

    # ---------- setup ----------
    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        screen = QGuiApplication.primaryScreen()
        # Use the FULL primary-screen geometry (not availableGeometry) so the
        # overlay's coordinate system matches the wallpaper, which is stretched
        # across the entire screen.  This keeps every hotspot (lamp, nest, dish,
        # training, HUD) exactly on top of the corresponding feature painted in
        # the wallpaper.  Empty areas still return HTTRANSPARENT, so the taskbar
        # and the rest of the desktop remain clickable.
        g = screen.geometry()
        self.sw, self.sh = g.width(), g.height()
        self.setFixedSize(self.sw, self.sh)
        self.move(g.x(), g.y())
        self.setWindowOpacity(0.999)

    def _compute_zones(self):
        self._zone_rects = {}
        for name, z in ZONES.items():
            if "cx" in z:
                cx = z["cx"] * self.sw
                cy = z["cy"] * self.sh
                if "r" in z:
                    self._zone_rects[name] = QRectF(cx - z["r"] * self.sw,
                                                    cy - z["r"] * self.sw,
                                                    z["r"] * 2 * self.sw,
                                                    z["r"] * 2 * self.sw)
                else:
                    self._zone_rects[name] = QRectF(cx - z["w"] * self.sw / 2,
                                                    cy - z["h"] * self.sh / 2,
                                                    z["w"] * self.sw,
                                                    z["h"] * self.sh)
            else:
                self._zone_rects[name] = QRectF(z["x"] * self.sw,
                                                z["y"] * self.sh,
                                                z["w"] * self.sw,
                                                z["h"] * self.sh)

    def zone_rect(self, name) -> QRectF:
        return self._zone_rects[name]

    def _frac(self, name, key):
        return ZONES[name][key]

    # ---------- click-through ----------
    def _in_any_hotspot(self, pt: QPointF) -> bool:
        # The bug sprite is 300x200 px, much larger than the small interaction
        # hotspots.  We check the specific zones FIRST so the leaf lamp, nest,
        # dish, training rings, HUD and info button stay clickable even when
        # the bug is standing on top of one of them.  The bug is only picked
        # up when no specific zone matches.
        if self.fog_btn.contains(pt):
            return True
        if self.nest.contains(pt):
            return True
        if self.dish.contains(pt):
            return True
        if self.training.contains(pt):
            return True
        if self.hud.contains(pt):
            return True
        if self.info.contains(pt):
            return True
        if self.bug.hit(pt):
            return True
        if self.mate is not None and self.mate.hit(pt):
            return True
        return False

    def nativeEvent(self, eventType, message):
        try:
            et = eventType if isinstance(eventType, str) else eventType.decode("ascii", "ignore")
            if "MSG" in et.upper() or "WM" in et.upper():
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_NCHITTEST:
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    pt = QPoint(x, y)
                    local = self.mapFromGlobal(pt)
                    localf = QPointF(local)
                    if self.bug.dragging or (self.mate is not None and self.mate.dragging):
                        msg.result = self.HTCLIENT
                        return True, self.HTCLIENT
                    if self._in_any_hotspot(localf):
                        msg.result = self.HTCLIENT
                        return True, self.HTCLIENT
                    msg.result = self.HTTRANSPARENT
                    return True, self.HTTRANSPARENT
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    # ---------- per-frame ----------
    def _tick(self):
        # Decay stats (recover energy while the bug is asleep)
        sleeping = self.bug.state == self.bug.STATE_SLEEPING
        self.hud.decay(sleeping=sleeping)
        # Component ticks
        bug_inside_nest = self.nest.contains(self.bug.center()) and \
                          self.bug.state in (self.bug.STATE_SLEEPING, self.bug.STATE_LANDED, self.bug.STATE_WALKING)
        self.nest.tick(bug_inside=bug_inside_nest)
        self.dish.tick()
        self.training.tick()
        self.dome.tick()
        dome_active = self.dome.state in (self.dome.STATE_FOGGING,
                                          self.dome.STATE_FOGGED,
                                          self.dome.STATE_SINKING,
                                          self.dome.STATE_CLEARING)
        self.fog_btn.tick(dome_active=dome_active)
        # Offspring life-cycle advance
        if self.offspring is not None:
            self.offspring.tick(DT)
        # Mating sequence (Phase 3): drive both bugs, then lay the egg.
        if self.mating is not None:
            res = self.mating.tick(DT, self.sw, self.sh)
            if res == "lay_egg":
                self._lay_egg()
                self._save_game()      # clutch must survive an immediate shutdown
            if self.mating is not None and self.mating.phase == Mating.PHASE_DONE:
                self.mating = None
                self._save_game()
        # Bug tick (suspended while dragged or mating)
        if self.bug.state not in (self.bug.STATE_DRAGGED, self.bug.STATE_MATING):
            self.bug.tick(self.sw, self.sh)
        if self.mate is not None and self.mate.state not in (
                self.mate.STATE_DRAGGED, self.mate.STATE_MATING):
            self.mate.tick(self.sw, self.sh)
        # remote bug animates but its AI is gated by remote=True
        if self.remote_bug is not None:
            self.remote_bug.tick(self.sw, self.sh)
        # Cross-PC net sync (Phase 4)
        if self.net is not None and self.net.connected:
            self._net_send_counter = (self._net_send_counter + 1) % 4
            if self._net_send_counter == 0:
                self._send_net_state()
            if not self._net_ok_noted:
                # first successful connection -> tell the user
                self._net_ok_noted = True
                self._net_fail_noted = False
                self._toast(
                    f"联机：已连接（房间 {self.net.room}），等对方进来 …", 6.0)
        elif self.net is not None and not self._net_fail_noted:
            # still not connected ~2 game-seconds after joining -> warn (once)
            self._net_wait += DT
            if self._net_wait > 2.0:
                self._net_fail_noted = True
                self._toast(
                    "联机：连不上中继，后台自动重试中 …", 6.0)
        if self._net_inbox:
            inbox = self._net_inbox[:]
            self._net_inbox.clear()
            for msg in inbox:
                self._process_net_msg(msg)
        # Proximity / recognition
        d_to_dish = math.hypot(self.bug.center().x() - self.dish.center.x(),
                               self.bug.center().y() - self.dish.center.y())
        d_to_train = math.hypot(self.bug.center().x() - self.training.center().x(),
                                self.bug.center().y() - self.training.center().y())
        d_to_nest = math.hypot(self.bug.center().x() - self.nest.center().x(),
                               self.bug.center().y() - self.nest.center().y())
        # The dish emits a recognition ring when the bug is nearby and idle
        if d_to_dish < DISH_PROXIMITY and self.bug.state in (self.bug.STATE_LANDED, self.bug.STATE_WALKING):
            if self.dish.state == self.dish.STATE_IDLE and random.random() < 0.03:
                self.dish.start_recognize()
        # Periodic auto-save so a hard shutdown never wipes progress
        self._save_accum += DT
        if self._save_accum >= AUTOSAVE_SECONDS:
            self._save_accum = 0.0
            self._save_game()
        self.update()

    # ---------- mouse ----------
    def _bug_at(self, pt: QPointF):
        """Return the bug under the point (mate takes priority if overlapping)."""
        if self.mate is not None and self.mate.hit(pt):
            return self.mate
        if self.bug.hit(pt):
            return self.bug
        return None

    def mousePressEvent(self, event):
        pt = QPointF(event.pos())
        if event.button() == Qt.LeftButton:
            # Specific zones win over the (huge) bug sprite, so the lamp and
            # info button always respond even when the bug overlaps them.
            if self.fog_btn.contains(pt):
                self.dome.click()
                self.fog_btn.press()
                return
            if self.info.contains(pt):
                self.info.show_help = not self.info.show_help
                return
            b = self._bug_at(pt)
            if b is not None:
                b.start_drag(event.globalPos(), event.globalPos())
                self._drag_bug = b
                self.grabMouse()
                return
            # nest / dish / training / hud: no direct click action

    def mouseMoveEvent(self, event):
        if self._drag_bug is not None and self._drag_bug.dragging:
            self._drag_bug.update_drag(event.globalPos())
            # proximity indicators (visual feedback)
            self._update_proximity()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_bug is not None:
            b = self._drag_bug
            if b.dragging:
                b.end_drag()
            self.releaseMouse()
            self._drag_bug = None
            self._on_bug_dropped(b)

    def mouseDoubleClickEvent(self, event):
        pt = QPointF(event.pos())
        b = self._bug_at(pt)
        if b is not None:
            b._start_random_flight(self.sw, self.sh)

    def _update_proximity(self):
        bc = self.bug.center()
        self._bug_in_nest_range = self.nest.contains(bc)
        self._bug_in_dish_range = self.dish.contains(bc)
        self._bug_in_train_range = self.training.contains(bc)

    def _on_bug_dropped(self, bug):
        bc = bug.center()
        # Nest first (sleep wins over eat/train)
        if self.nest.contains(bc):
            nest_pt = QPointF(self.nest.rect.center().x() - BUG_W / 2,
                              self.nest.rect.center().y() - BUG_H / 2)
            bug.start_sleep(nest_pt)
            if bug is self.bug:
                self.hud.on_sleep()
            return
        if self.dish.contains(bc):
            dish_pt = QPointF(self.dish.center.x() - BUG_W / 2,
                              self.dish.center.y() - BUG_H / 2 + 20)
            bug.start_eat(dish_pt)
            self.dish.start_eat()
            if bug is self.bug:
                self.hud.on_eat()
            return
        if self.training.contains(bc):
            train_pt = QPointF(self.training.rect.center().x() - BUG_W / 2,
                               self.training.rect.center().y() - BUG_H / 2)
            bug.start_train(train_pt)
            self.training.trigger()
            if bug is self.bug:
                self.hud.on_train()
            return

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._save_game()
            QApplication.quit()
        elif event.key() == Qt.Key_F1:
            self.info.show_help = not self.info.show_help

    def _on_context_menu(self, global_pos):
        """Right-click handler: only the bug itself pops the menu (matches the
        original behaviour); empty / zone clicks fall through to the desktop."""
        localf = QPointF(self.mapFromGlobal(global_pos))
        bug = self._bug_at(localf)
        if bug is None:
            return
        self._show_bug_menu(global_pos, bug)

    def _show_bug_menu(self, global_pos=None, bug=None):
        from PyQt5.QtWidgets import QMenu, QAction
        if bug is None:
            bug = self.bug
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(30, 38, 48, 235);
                color: white;
                border: 1px solid #5a8;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item { padding: 6px 22px; border-radius: 4px; }
            QMenu::item:selected { background: #4a8; }
        """)
        # "召唤伴侣" only from the initiator, and only when it is in heat and
        # no mating / clutch is already in progress.
        if bug is self.bug:
            no_clutch = (self.offspring is None) or self.offspring.done
            can_summon = (self.hud.in_heat and self.mate is None
                          and self.mating is None and no_clutch)
            a0 = QAction("召唤伴侣", self)
            a0.triggered.connect(lambda: self._summon_mate())
            if not can_summon:
                a0.setEnabled(False)
                if not self.hud.in_heat:
                    a0.setText("召唤伴侣（需三项满值）")
                elif self.mate is not None:
                    a0.setText("伴侣已在场")
                elif self.mating is not None:
                    a0.setText("交配中…")
                else:
                    a0.setText("已有后代在发育")
            menu.addAction(a0)
            menu.addSeparator()
            # Cross-PC play (Phase 4)
            a_net = QAction("联机：加入房间", self)
            a_net.triggered.connect(self._on_join_room)
            if self.net is not None and self.net.connected:
                a_net.setText("联机：已连接")
                a_net.setEnabled(False)
            elif self.net is not None:
                a_net.setText("联机：连接中…（可重试）")
            menu.addAction(a_net)
            if self.net is not None and self.net.connected:
                can_net_mate = (self.hud.in_heat and self.remote_bug is not None
                                and self.mating is None
                                and (self.offspring is None or self.offspring.done))
                a_nmate = QAction("联机：邀请交配", self)
                a_nmate.triggered.connect(self._on_net_mate_request)
                if not can_net_mate:
                    a_nmate.setEnabled(False)
                    a_nmate.setText("联机：邀请交配（需联机+满值+对端在场）")
                menu.addAction(a_nmate)
            menu.addSeparator()
        a1 = QAction("让它飞一下", self)
        a1.triggered.connect(lambda: bug._start_random_flight(self.sw, self.sh))
        menu.addAction(a1)
        a2 = QAction("去吃饭", self)
        a2.triggered.connect(lambda: self._teleport_bug_to(
            self.dish.center.x(), self.dish.center.y() + 20, bug))
        menu.addAction(a2)
        a3 = QAction("去睡觉", self)
        a3.triggered.connect(lambda: self._teleport_bug_to(
            self.nest.rect.center().x(), self.nest.rect.center().y(), bug))
        menu.addAction(a3)
        a4 = QAction("去训练", self)
        a4.triggered.connect(lambda: self._teleport_bug_to(
            self.training.rect.center().x(), self.training.rect.center().y(), bug))
        menu.addAction(a4)
        # bug size: shrink step by step (with a restore entry once shrunk)
        pct = f"{bug.size_scale * 100:.0f}%"
        if bug.size_scale > BUG_SCALE_MIN + 1e-6:
            a_size = QAction(f"缩小虫子（当前 {pct}）", self)
            a_size.triggered.connect(lambda: self._shrink_bug(bug))
        else:
            a_size = QAction("虫子已经最小啦", self)
            a_size.setEnabled(False)
        menu.addAction(a_size)
        if bug.size_scale < BUG_SCALE_DEFAULT - 1e-6:
            a_restore = QAction("恢复原本大小", self)
            a_restore.triggered.connect(lambda: self._restore_bug_size(bug))
            menu.addAction(a_restore)
        menu.addSeparator()
        a5 = QAction("退  出", self)
        a5.triggered.connect(self._on_exit)
        menu.addAction(a5)
        if global_pos is None:
            global_pos = QCursor.pos()
        menu.exec_(global_pos)

    def _summon_mate(self):
        """Create the partner bug in the same process, then begin mating.
        Only valid when the initiator is in heat (all three stats maxed)."""
        if self.mate is not None or self.mating is not None:
            return
        if not self.hud.in_heat:
            return
        self.mate = Bug(SPRITES_DIR)
        self.mate.x = clamp(self.bug.x - 260, 40, self.sw - BUG_W - 40)
        self.mate.y = clamp(self.bug.y, 60, self.sh - BUG_H - 80)
        self.mate.facing_right = True
        # The partner arrives beside the initiator -> "put together" -> mating.
        self.mating = Mating(self.bug, self.mate, self.nest.rect)

    def _teleport_bug_to(self, x, y, bug=None):
        if bug is None:
            bug = self.bug
        # centre the bug's *actual* footprint (respects a shrunk bug)
        bug.x = x - bug.w() / 2
        bug.y = y - bug.h() / 2
        # immediately trigger the drop check
        self._on_bug_dropped(bug)

    def _shrink_bug(self, bug=None):
        """Right-click '缩小虫子': step the bug's drawn size down one notch."""
        if bug is None:
            bug = self.bug
        bug.shrink()
        self._save_game()   # persist the size right away

    def _restore_bug_size(self, bug=None):
        if bug is None:
            bug = self.bug
        bug.restore_size()
        self._save_game()

    def _on_exit(self):
        self._save_game()
        QApplication.quit()

    def _on_join_room(self):
        room, ok = QInputDialog.getText(self, "加入房间",
                                        "输入房间码（或完整 ws:// 地址）：",
                                        text="ROOM-123")
        if ok and room.strip():
            val = room.strip()
            # 用本机计算机名做标识：中继控制台能分清是谁进来了
            try:
                name = socket.gethostname() or "甲"
            except Exception:
                name = "甲"
            if val.startswith("ws://") or val.startswith("wss://"):
                # advanced: she typed a full relay address -> use it directly
                self.connect_room("ROOM-123", name=name, color="#85B7EB", url=val)
            else:
                self.connect_room(val, name=name, color="#85B7EB")

    def _on_net_mate_request(self):
        if self.net is None or not self.net.connected or self.remote_bug is None:
            return
        self.net.send({"type": "mate_req"})

    # ---------- persistence (auto-save) ----------
    def _gather_save(self) -> dict:
        bug = self.bug
        off = None
        if self.offspring is not None:
            off = {"stage": self.offspring.stage,
                   "idx": self.offspring.idx,
                   "t": self.offspring.t,
                   "done": self.offspring.done}
        return {
            "ver": 1,
            "ts": time.time(),
            "bug": {
                "x": bug.x,
                "y": bug.y,
                "facing": bug.facing_right,
                "sleeping": bug.state == bug.STATE_SLEEPING,
                "scale": bug.size_scale,
            },
            "hud": {
                "fullness": self.hud.fullness,
                "energy": self.hud.energy,
                "happy": self.hud.happy,
            },
            "offspring": off,
        }

    def _save_game(self):
        if _live_save_is_protected():
            print("[save] REFUSED to write the live save from a test process "
                  "(%s).  Set BUG_SAVE to a temp path." % _save_path())
            return
        try:
            data = self._gather_save()
            p = _save_path()
            tmp = p.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Keep exactly ONE generation back.  A single unreadable/torn save
            # used to be unrecoverable because the next launch stamped a fresh
            # file straight over it; now there is always a fallback.
            if p.exists():
                try:
                    shutil.copyfile(p, p.with_suffix(".json.bak"))
                except Exception:
                    pass
            os.replace(tmp, p)   # atomic-ish: avoid a torn file
        except Exception as e:
            print("[save] write failed:", e)

    def _load_save(self):
        p = _save_path()
        d = None
        primary_err = None
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as e:
                primary_err = e
                print("[save] %s unreadable (%s); falling back to the backup"
                      % (p.name, e))
        if d is None:
            bak = p.with_suffix(".json.bak")
            if not bak.exists():
                if primary_err is not None:
                    # Nothing to fall back to.  Raise so the caller knows the
                    # session was NOT restored and must not stamp over the file.
                    raise primary_err
                return
            with open(bak, "r", encoding="utf-8") as f:
                d = json.load(f)
            print("[save] restored progress from", bak.name)
        if not isinstance(d, dict) or d.get("ver") != 1:
            return
        # ---- bug ----
        b = d.get("bug") or {}
        x = float(b.get("x", self.bug.x))
        y = float(b.get("y", self.bug.y))
        # restore the right-click shrink size (absent in old saves -> 1.0)
        self.bug.size_scale = clamp(
            float(b.get("scale", BUG_SCALE_DEFAULT)), BUG_SCALE_MIN, 2.0)
        # clamp into the current screen (handles resolution changes)
        self.bug.x = clamp(x, 0, max(0, self.sw - self.bug.w()))
        self.bug.y = clamp(y, 0, max(0, self.sh - self.bug.h()))
        self.bug.facing_right = bool(b.get("facing", self.bug.facing_right))
        if b.get("sleeping"):
            # asleep -> put it back on the nest so the pose matches the scene
            nc = self.nest.rect.center()
            self.bug.x = nc.x() - self.bug.w() / 2
            self.bug.y = nc.y() - self.bug.h() / 2
            self.bug.start_sleep(QPointF(self.bug.x, self.bug.y))
        else:
            self.bug.state = self.bug.STATE_LANDED
            self.bug.land_timer = 60
            self.bug.action_t = 0.0
        # ---- stats ----
        h = d.get("hud") or {}
        self.hud.fullness = clamp(float(h.get("fullness", self.hud.fullness)), 0.0, 1.0)
        self.hud.energy = clamp(float(h.get("energy", self.hud.energy)), 0.0, 1.0)
        self.hud.happy = clamp(float(h.get("happy", self.hud.happy)), 0.0, 1.0)
        # ---- offline catch-up ----
        offline = 0.0
        if OFFLINE_CATCHUP:
            try:
                offline = clamp(time.time() - float(d.get("ts", time.time())),
                                0.0, OFFLINE_CATCHUP_MAX)
            except Exception:
                offline = 0.0
        # ---- offspring ----
        o = d.get("offspring")
        if o:
            self.offspring = Offspring()
            # `idx` is the durable half of this record: it is a plain integer,
            # so it survives any change to the STAGE_* string vocabulary.
            # Use the string when it is recognised, otherwise fall back to
            # `idx` -- an unrecognised stage used to silently rewind the pet to
            # 卵期 while keeping its elapsed time, which is exactly what a
            # "成长期 变回 卵期" report looks like.
            st = o.get("stage")
            if st in Offspring.NAMES:
                self.offspring.stage = st
                self.offspring.idx = Offspring.ORDER.index(st)
            else:
                try:
                    idx = int(o.get("idx", 0))
                except (TypeError, ValueError):
                    idx = 0
                idx = max(0, min(idx, len(Offspring.ORDER) - 1))
                self.offspring.idx = idx
                self.offspring.stage = Offspring.ORDER[idx]
                if st is not None:
                    print("[save] unknown offspring stage %r -> keeping idx=%d (%s)"
                          % (st, idx, self.offspring.stage))
            self.offspring.t = max(0.0, float(o.get("t", 0.0)))
            self.offspring.done = bool(o.get("done", False))
            if self.offspring.done:
                self.offspring.stage = Offspring.STAGE_ADULT
                self.offspring.idx = len(Offspring.ORDER) - 1
        # advance both by the offline time (big dt -> the normal tick handles
        # multi-stage transitions because it loops the surplus over).
        if offline > 0 or self.offspring is not None:
            if offline > 0:
                self.hud.decay_offline(offline)
                for _ in range(int(offline / DT) + 1):
                    if self.offspring is not None:
                        self.offspring.tick(DT)
        self.hud.decay(sleeping=b.get("sleeping", False))  # refresh in_heat

    def closeEvent(self, event):
        self._save_game()
        if self.net is not None:
            # polite 'bye' so the peer's screen drops our bug immediately
            try:
                self.net.stop()
                if self.net.thread is not None:
                    self.net.thread.join(timeout=1.0)
            except Exception:
                pass
        super().closeEvent(event)

    # ---------- breeding / offspring ----------
    def _lay_egg(self):
        """Spawn the clutch in the initiator's nest (called after mating)."""
        if self.offspring is None:
            self.offspring = Offspring()
        elif self.offspring.done:
            # The previous clutch is already adult and merely sitting in the
            # nest.  A second mating has to actually produce a new egg: this
            # used to fall through silently, so the whole courtship played out
            # and then nothing appeared -- indistinguishable from a bug.
            self.offspring = Offspring()
            self._toast("成年虫飞走了，窝里换上新的一窝卵", 6.0)

    # ---------- cross-PC play (Phase 4) ----------
    def connect_room(self, room: str, name: str, color: str = "#85B7EB",
                     url: str = None):
        """Join a relay room and start broadcasting state / receiving peer.
        `url` defaults to the resolved RELAY_URL; pass one to override."""
        if not HAVE_WEBSOCKETS:
            print("[net] websockets not installed; offline mode only")
            self._toast("联机不可用：此构建缺少 websockets 组件", 6.0)
            return
        if self.net is not None:
            if self.net.connected:
                return              # already online - nothing to do
            # a previous attempt never got through (relay down / bad address):
            # replace the stale client instead of silently ignoring the click
            self.net.stop()
            self.net = None
            self.remote_bug = None
        self._net_ok_noted = False
        self._net_fail_noted = False
        self._peer_seen = False
        self._net_wait = 0.0
        self.net = NetClient(room=room, name=name, color=color,
                             on_msg=lambda d: self._net_inbox.append(d))
        self.net.start(url or RELAY_URL)
        # create the remote bug sprite (it will animate but not run local AI)
        if self.remote_bug is None:
            self.remote_bug = Bug(SPRITES_DIR)
            self.remote_bug.remote = True
        self._toast(f"联机：正在连接中继（房间 {room}）…", 5.0)

    def _toast(self, text: str, seconds: float = 5.0):
        """Show a transient status line on the overlay.  Anything that happens
        without a visible change on screen must say so here -- a silent
        no-op is indistinguishable from a bug."""
        self._toast_text = text
        self._toast_until = time.time() + seconds
        self.update()

    def _send_net_state(self):
        if self.net is None or not self.net.connected:
            return
        self.net.send({
            "type": "state",
            "x": self.bug.x,
            "y": self.bug.y,
            "facing": self.bug.facing_right,
            "st": self.bug.state,
            "full": self.hud.fullness,
            "nrg": self.hud.energy,
            "mood": self.hud.happy,
        })

    def _process_net_msg(self, msg):
        t = msg.get("type")
        if t == "state":
            if self.remote_bug is None:
                self.remote_bug = Bug(SPRITES_DIR)
                self.remote_bug.remote = True
            if not self._peer_seen:
                self._peer_seen = True
                self._toast("对方进入房间了！拖到一起养吧", 5.0)
            self.remote_bug.apply_snapshot(msg)
        elif t == "mate_req":
            # Peer wants to mate. Auto-accept: generate a shared seed & midpoint
            # and broadcast it back (relay skips sender, so initiator receives it).
            if self.remote_bug is None:
                return
            seed = random.randrange(1 << 31)
            bc = self.bug.center()
            rc = self.remote_bug.center()
            mid = QPointF((bc.x() + rc.x()) / 2, (bc.y() + rc.y()) / 2)
            self.net.send({"type": "mate_start", "seed": seed,
                           "t0": 0.0, "mid": [mid.x(), mid.y()]})
            # Start our own mating deterministically.  We are the ACCEPTOR:
            # mirror the layout so both screens share one bug world.
            self.mating = Mating(self.bug, self.remote_bug,
                                 self.nest.rect, seed=seed, t0=0.0,
                                 mirror=True)
        elif t == "mate_start":
            if self.remote_bug is None:
                return
            seed = msg.get("seed", 0)
            mx, my = msg.get("mid", [0, 0])
            self.mating = Mating(self.bug, self.remote_bug,
                                 self.nest.rect, seed=seed, t0=0.0)
            # Override the midpoint to the agreed shared value so both sides match
            self.mating.mid = QPointF(mx, my)
        elif t == "bye":
            self.remote_bug = None
            self._peer_seen = False
            self._toast("对方已离开房间", 4.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # Layer order (decorative layers are gated by SHOW_* flags; off by
        # default so the wallpaper stays clean -- only the bug + fog show):
        # 1) Dome under-shadow (if pressed in)
        if SHOW_DECOR:
            self.dome.draw_under(p)
        # 2) Component ambient glows
        if SHOW_DECOR:
            self.nest.draw_glow(p)
            self.dish.draw_glow(p)
        # 3) Training rings
        if SHOW_DECOR:
            self.training.draw(p)
        # 4) Dish food
        if SHOW_DECOR:
            self.dish.draw_food(p)
        # 5) Dish recognition ring
        if SHOW_DECOR:
            self.dish.draw_recognition(p)
        # 6) The bug (the desktop pet)
        nest_blend = 1.0 if self.bug.state == self.bug.STATE_SLEEPING else 0.0
        training_amp = 1.0 if self.bug.state == self.bug.STATE_TRAINING else 0.0
        self.bug.draw(p, nest_blend=nest_blend, training_amp=training_amp)
        # 6a) The summoned partner (drawn on top of the initiator)
        if self.mate is not None:
            m_nest_blend = 1.0 if self.mate.state == self.mate.STATE_SLEEPING else 0.0
            m_train_amp = 1.0 if self.mate.state == self.mate.STATE_TRAINING else 0.0
            self.mate.draw(p, nest_blend=m_nest_blend, training_amp=m_train_amp)
        # 6a½) Remote peer bug (cross-PC play).  `placed` gates the draw:
        # the sprite is pre-created on join but must NOT appear at (0,0)
        # until the peer's first real snapshot arrives.
        if self.remote_bug is not None and self.remote_bug.placed:
            r_nest_blend = 1.0 if self.remote_bug.state == self.remote_bug.STATE_SLEEPING else 0.0
            r_train_amp = 1.0 if self.remote_bug.state == self.remote_bug.STATE_TRAINING else 0.0
            self.remote_bug.draw(p, nest_blend=r_nest_blend, training_amp=r_train_amp)
        # 6b) Mating heart particles (above the bugs, below the fog)
        if self.mating is not None:
            self.mating.draw_hearts(p)
        # 6c) Offspring (sits in the nest, drawn above the bugs)
        if self.offspring is not None:
            nc = self.nest.rect.center()
            self.offspring.draw_in_nest(p, nc.x(), nc.y() + 6)
        # 7) Dome fog (full-screen wallpaper-based AI frames)
        self.dome.draw_fog(p, self.sw, self.sh)
        # 8) Zzz above nest
        if SHOW_DECOR:
            self.nest.draw_zzz(p)
        # 9) HUD
        if SHOW_HUD:
            self.hud.draw(p)
        # 9b) Offspring status card (below the stats panel)
        if SHOW_HUD and self.offspring is not None:
            r = self.hud.rect
            egg_rect = QRectF(r.x(), r.y() + r.height() + 10,
                              r.width(), 44)
            self.offspring.draw_panel(p, egg_rect)
        # 9c) Transient net status toast (join / retry / peer arrive / leave)
        if self._toast_text and time.time() < self._toast_until:
            self._draw_toast(p)
        # 10) Info button + help (help panel via F1; 'i' glyph off by default)
        self.info.draw(p)
        # 10b) Drop-zone guides (for machines without the room wallpaper)
        if SHOW_ZONE_GUIDES:
            self._draw_zone_guides(p)
        # 11) Fog button glyph (off by default; the lamp hotspot still works)
        if SHOW_FOG_BUTTON:
            dome_active = self.dome.state in (self.dome.STATE_FOGGING,
                                              self.dome.STATE_FOGGED,
                                              self.dome.STATE_SINKING,
                                              self.dome.STATE_CLEARING)
            self.fog_btn.draw(p, dome_active=dome_active)

        # Proximity highlight outlines (subtle, decor only)
        if SHOW_DECOR:
            self._draw_proximity_outline(p)

    # ---------- drop-zone guides (no-wallpaper machines) ----------
    def _draw_toast(self, p: QPainter):
        """Small centred status line (semi-transparent, top of screen,
        auto-expires)."""
        text = self._toast_text
        # rough width: CJK ~15px, latin ~8px at 12pt bold
        px = sum(15 if ord(ch) > 0x2E80 else 8 for ch in text)
        bw = min(max(px + 44, 200), self.sw - 40)
        box = QRectF(0, 0, bw, 38)
        box.moveCenter(QPointF(self.sw / 2.0, self.sh * 0.065))
        p.save()
        p.setOpacity(0.88)
        path = QPainterPath()
        path.addRoundedRect(box, 9, 9)
        p.fillPath(path, QColor(20, 28, 36, 215))
        p.setPen(QPen(QColor(120, 200, 255, 150), 1))
        p.drawPath(path)
        p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        p.setPen(QColor(230, 240, 250))
        p.drawText(box, Qt.AlignCenter, text)
        p.restore()

    def _draw_zone_guides(self, p: QPainter):
        """Dashed outlines + labels so a colleague without the room wallpaper
        can still see where to drag the bug (dish / nest / training rings)."""
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        guide = [
            (self.dish.rect_hot(),     QColor(100, 200, 255, 150), "食盆（吃饭）"),
            (self.nest.rect_hot(),     QColor(120, 230, 160, 150), "睡窝（睡觉）"),
            (self.training.rect_hot(), QColor(120, 210, 255, 150), "训练区（训练）"),
        ]
        for zone, color, label in guide:
            pen = QPen(color, 2, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 18))
            p.drawRoundedRect(zone, 10, 10)
            # label sits at the top-left of the zone, just inside
            lx = zone.x() + 8
            ly = zone.y() + 18
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QPointF(lx, ly), label)
            p.setPen(pen)
        p.restore()

    def _draw_proximity_outline(self, p: QPainter):
        if not self.bug.dragging:
            return
        p.save()
        p.setBrush(Qt.NoBrush)
        for zone, color in [
            (self.nest.rect_hot(),     QColor(120, 230, 160, 120)),
            (self.dish.rect_hot(),     QColor(100, 200, 255, 120)),
            (self.training.rect_hot(), QColor(120, 220, 255, 120)),
        ]:
            pen = QPen(color, 2, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(zone)
        p.restore()


# ===================== Wallpaper CLI (exe doubles as installer) =====================
# The colleague runs no Python, so the exe itself installs / restores the room
# wallpaper.  Called before the GUI starts:
#    桌面隐翅虫.exe --with-wallpaper "房间壁纸.jpg" "备份-原壁纸.txt"
#    桌面隐翅虫.exe --restore-wallpaper "备份-原壁纸.txt"

def _reg_read_wallpaper() -> str:
    r"""Current wallpaper path from HKCU\Control Panel\Desktop."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Control Panel\Desktop", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(k, "WallPaper")
        winreg.CloseKey(k)
        return val or ""
    except Exception:
        return ""


def _reg_apply_wallpaper(path) -> bool:
    """Set Fill style + apply `path` as the desktop wallpaper."""
    if os.name != "nt":
        print("[wallpaper] Windows only")
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "10")  # Fill
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, "0")
        winreg.SetValueEx(k, "WallPaper", 0, winreg.REG_SZ, str(path))
        winreg.CloseKey(k)
    except Exception as e:
        print("[wallpaper] style set failed:", e)
    SPI_SETDESKWALLPAPER, SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 20, 0x01, 0x02
    ret = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, str(path),
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    return bool(ret)


def _backup_wallpaper(bak_path):
    """Remember HER original wallpaper -- but only the first time, so re-running
    the launcher never overwrites the real backup with our own room image."""
    if Path(bak_path).exists():
        return
    cur = _reg_read_wallpaper()
    try:
        with open(bak_path, "w", encoding="utf-8") as f:
            f.write(cur + "\n")
        print("[wallpaper] backed up her original ->", cur or "(none)")
    except Exception as e:
        print("[wallpaper] backup failed:", e)


def _restore_wallpaper(bak_path) -> bool:
    if not Path(bak_path).exists():
        print("[wallpaper] no backup file:", bak_path)
        return False
    try:
        cur = Path(bak_path).read_text(encoding="utf-8").strip()
    except Exception:
        cur = ""
    if not cur:
        print("[wallpaper] backup is empty; nothing to restore")
        return False
    if not os.path.isfile(cur):
        print("[wallpaper] original wallpaper no longer on disk:", cur)
        return False
    ok = _reg_apply_wallpaper(cur)
    print("[wallpaper] restored ->", cur, "|", ok)
    return ok


def main():
    argv = list(sys.argv[1:])
    # ---- pre-GUI wallpaper commands ----
    if argv:
        if argv[0] == "--with-wallpaper" and len(argv) >= 2:
            wp, bak = argv[1], (argv[2] if len(argv) > 2
                                else str(Path(wp).resolve().with_name("备份-原壁纸.txt")))
            if os.path.isfile(wp):
                _backup_wallpaper(bak)
                print("[wallpaper] apply ->", wp, "|",
                      _reg_apply_wallpaper(wp))
            else:
                print("[wallpaper] file not found:", wp)
            # fall through: still launch the pet
        elif argv[0] == "--restore-wallpaper" and len(argv) >= 2:
            _restore_wallpaper(argv[1])
            return
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = RoomOverlay()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
