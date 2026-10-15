"""
Bug Pet - Desktop rove beetle pet
A frameless, transparent, top-most bug that wanders on the screen.
- Click + drag to move
- Right-click for menu (Exit)
- Esc to exit
- The bug auto-walks, occasionally takes off and lands at random positions.
"""

import math
import random
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF
from PyQt5.QtGui import (QPainter, QPixmap, QCursor, QTransform, QColor,
                         QGuiApplication, QPainterPath)
from PyQt5.QtWidgets import QApplication, QWidget, QMenu, QAction

SPRITES_DIR = Path(__file__).resolve().parent.parent / "sprites"

# Display size of the pet ("略大" - slightly larger than typical desktop pet)
PET_W = 360
PET_H = 240

# How fast the bug "flaps" while flying - frames per second
FLAP_FPS = 14
# How often the bug ticks movement updates (60 fps)
MOVE_FPS = 60


def lerp(a, b, t):
    return a + (b - a) * t


def quad_bezier(p0, p1, p2, t):
    """Quadratic bezier interpolation."""
    u = 1 - t
    x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
    y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
    return x, y


class BugPet(QWidget):
    """The desktop rove beetle pet."""

    STATE_WALKING = "walking"
    STATE_FLYING = "flying"
    STATE_LANDED = "landed"

    def __init__(self):
        super().__init__()
        self._load_sprites()
        self._setup_window()
        self._init_state()

    # ---------- setup ----------
    def _load_sprites(self):
        """Load all sprite frames and scale them to PET size."""
        def load(name):
            path = SPRITES_DIR / name
            return QPixmap(str(path))

        self.sprite_walk_left = load("walk_wings_left.png")
        self.sprite_walk_right = load("walk_wings_right.png")
        self.sprite_flap = [
            load("flap_1_open.png"),
            load("flap_2_spread.png"),
            load("flap_3_down.png"),
            load("flap_4_folded.png"),
        ]

        # Keep raw (no-wing) walking frames as a fallback - not used by default
        self.sprite_walk_left_plain = load("walk_left.png")
        self.sprite_walk_right_plain = load("walk_right.png")

        # Scale all to PET_W x PET_H while preserving aspect ratio
        all_sprites = ([self.sprite_walk_left, self.sprite_walk_right]
                       + self.sprite_flap
                       + [self.sprite_walk_left_plain, self.sprite_walk_right_plain])
        for sprite in all_sprites:
            scaled = sprite.scaled(PET_W, PET_H, Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
            # Convert to a pixmap that has alpha (already has since PNG with bg=transparent)
            sprite._scaled = scaled

        self._cache_scaled()

    def _cache_scaled(self):
        """Cache scaled versions for paint speed."""
        self._walk_left_scaled = self.sprite_walk_left._scaled
        self._walk_right_scaled = self.sprite_walk_right._scaled
        self._walk_left_plain_scaled = self.sprite_walk_left_plain._scaled
        self._walk_right_plain_scaled = self.sprite_walk_right_plain._scaled
        self._flap_scaled = [s._scaled for s in self.sprite_flap]

    def _setup_window(self):
        """Make window transparent, frameless, top-most."""
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(PET_W, PET_H)
        # Don't steal focus / activate on click for transparency
        self.setWindowOpacity(0.999)  # forces compositing
        # Allow click-through for transparent areas (optional - off for drag support)
        # self.setAttribute(Qt.WA_NoMousePropagation, False)

    def _init_state(self):
        """Place the pet at a random spot on the primary screen."""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()

        # Clamp helper: lower <= upper always, and keep pet fully on-screen.
        def rand_y(lo_frac, hi_frac):
            lo = max(0, int(sh * lo_frac))
            hi = max(lo + 1, int(sh * hi_frac) - PET_H)
            hi = min(hi, sh - PET_H)
            return random.randint(lo, hi)

        # Start somewhere mid-screen, slightly above the bottom (where icons are)
        x = random.randint(int(sw * 0.1), max(int(sw * 0.1) + 1, int(sw * 0.85) - PET_W))
        x = min(x, sw - PET_W)
        y = rand_y(0.55, 0.85)
        self.move(x, y)

        # State machine
        self.state = self.STATE_LANDED
        self.facing_right = random.choice([True, False])
        self.flap_frame_idx = 0
        self.anim_phase = 0.0  # 0..1 cycling for sprite timing

        # Walking state
        self.walk_target = None
        self.walk_idle_timer = 0  # frames until next walk decision

        # Landing state (paused on a spot)
        self.land_timer = random.randint(40, 140)  # ~0.7s..2.3s
        self.land_glow_alpha = 0.0  # for drop shadow fade-in

        # Flight state
        self.flight_t = 0.0
        self.flight_start = QPointF(self.pos())
        self.flight_end = QPointF(self.pos())
        self.flight_ctrl = QPointF(self.pos())
        self.flight_duration_frames = 0
        self.flight_speed_px_per_frame = 0

        # Drag state
        self.dragging = False
        self.drag_offset = QPoint()

        # Animation timers
        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._tick)
        self._move_timer.start(int(1000 / MOVE_FPS))

        # Right-click menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # ---------- main tick ----------
    def _tick(self):
        """Update state machine and position once per frame."""
        # Walk idle timer counts down always
        if self.walk_idle_timer > 0:
            self.walk_idle_timer -= 1

        # Animation phase advance (used by paintEvent for sprite cycle)
        self.anim_phase = (self.anim_phase + 1.0 / MOVE_FPS) % 1.0

        # Wing flap frame index advances faster than other frames
        self.flap_frame_idx = int(self.anim_phase * FLAP_FPS * 4) % 4

        if self.dragging:
            self.update()
            return

        if self.state == self.STATE_LANDED:
            self._tick_landed()
        elif self.state == self.STATE_WALKING:
            self._tick_walking()
        elif self.state == self.STATE_FLYING:
            self._tick_flying()

        self.update()

    # ---------- landed ----------
    def _tick_landed(self):
        # Gentle bobbing animation (already handled in paint)
        self.land_timer -= 1
        if self.land_timer <= 0:
            # Decide: walk a bit or take off?
            r = random.random()
            if r < 0.35:
                self._start_flight()
            else:
                self.state = self.STATE_WALKING
                self.walk_target = None
                self.walk_idle_timer = random.randint(20, 60)

    # ---------- walking ----------
    def _tick_walking(self):
        # If mouse gets very close, take off
        mpos = QCursor.pos()
        bpos = self.pos()
        dist_to_mouse = math.hypot(mpos.x() - bpos.x(), mpos.y() - bpos.y())
        if dist_to_mouse < 110:
            self._start_flight()
            return

        # If we don't have a target, pick one
        if self.walk_target is None:
            if self.walk_idle_timer > 0:
                # Sit still briefly
                return
            screen = QGuiApplication.primaryScreen().availableGeometry()
            sw, sh = screen.width(), screen.height()
            # Bias target toward lower half (icons tend to be there)
            tx = bpos.x() + random.randint(-180, 180)
            ty = bpos.y() + random.randint(-60, 60)
            tx = max(20, min(sw - PET_W - 20, tx))
            ty = max(20, min(sh - PET_H - 60, ty))
            self.walk_target = QPoint(tx, ty)
            self.facing_right = tx > bpos.x()

        # Move toward target
        dx = self.walk_target.x() - self.pos().x()
        dy = self.walk_target.y() - self.pos().y()
        dist = math.hypot(dx, dy)
        if dist < 6:
            self.walk_target = None
            self.walk_idle_timer = random.randint(20, 90)
            self.state = self.STATE_LANDED
            self.land_timer = random.randint(60, 200)
            return

        speed = 1.4  # px per frame
        nx = self.pos().x() + dx / dist * speed
        ny = self.pos().y() + dy / dist * speed
        self.move(int(nx), int(ny))

    # ---------- flying ----------
    def _start_flight(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        tx = random.randint(40, screen.width() - PET_W - 40)
        # Bias landings toward the lower 60% (icons area)
        ty = random.randint(int(screen.height() * 0.30),
                          int(screen.height() * 0.92) - PET_H)

        self.flight_start = QPointF(self.pos())
        self.flight_end = QPointF(tx, ty)
        # Control point: arc upward
        mx = (self.flight_start.x() + tx) / 2 + random.randint(-120, 120)
        my = min(self.flight_start.y(), ty) - random.randint(80, 220)
        self.flight_ctrl = QPointF(mx, my)

        # Flight duration scales with distance
        dist = math.hypot(tx - self.flight_start.x(), ty - self.flight_start.y())
        # ~1.5 seconds for short flights, ~3 seconds for long flights
        duration_ms = max(800, int(dist * 1.2))
        self.flight_total_frames = max(1, int(duration_ms / (1000 / MOVE_FPS)))
        self.flight_frame = 0
        self.facing_right = tx > self.flight_start.x()
        self.state = self.STATE_FLYING

    def _tick_flying(self):
        self.flight_frame += 1
        self.flight_t = self.flight_frame / self.flight_total_frames

        if self.flight_t >= 1.0:
            # Arrived
            self.move(int(self.flight_end.x()), int(self.flight_end.y()))
            self.state = self.STATE_LANDED
            self.land_timer = random.randint(80, 240)  # ~1.3s..4s pause
            return

        x, y = quad_bezier(
            (self.flight_start.x(), self.flight_start.y()),
            (self.flight_ctrl.x(), self.flight_ctrl.y()),
            (self.flight_end.x(), self.flight_end.y()),
            self.flight_t,
        )
        self.move(int(x), int(y))

    # ---------- paint ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Subtle drop shadow when landed (gives a "settled" feel)
        if self.state == self.STATE_LANDED:
            self._paint_shadow(painter)
        elif self.state == self.STATE_WALKING:
            self._paint_shadow(painter, alpha=120)

        # Pick sprite based on state
        if self.state == self.STATE_FLYING:
            sprite = self._flap_scaled[self.flap_frame_idx]
            # Add slight rotation for natural flight tilt
            angle = math.sin(self.flight_t * math.pi) * 6  # up to 6 deg
            if not self.facing_right:
                angle = -angle
        else:
            angle = 0
            if self.facing_right:
                sprite = self._walk_right_scaled
            else:
                sprite = self._walk_left_scaled

        # Subtle bobbing when landed
        bob_y = 0
        if self.state == self.STATE_LANDED:
            bob_y = math.sin(self.anim_phase * math.pi * 2) * 1.5
        elif self.state == self.STATE_WALKING:
            bob_y = abs(math.sin(self.anim_phase * math.pi * 8)) * 1.0

        # Apply rotation around center, with bobbing offset
        painter.save()
        cx = self.width() / 2
        cy = self.height() / 2 + bob_y
        painter.translate(cx, cy)
        if angle:
            painter.rotate(angle)
        painter.translate(-cx, -cy)
        painter.drawPixmap(0, int(bob_y), sprite)
        painter.restore()

    def _paint_shadow(self, painter, alpha=70):
        """Paint a soft elliptical shadow at the bug's feet."""
        w, h = self.width(), self.height()
        cx = w / 2
        cy = h - 18  # near the bottom of the window
        rx, ry = PET_W * 0.30, 10

        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), rx, ry)

        # Draw a radial-fade ellipse
        from PyQt5.QtGui import QRadialGradient
        grad = QRadialGradient(cx, cy, rx)
        grad.setColorAt(0.0, QColor(0, 0, 0, alpha))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, grad)

    # ---------- mouse ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self.grabMouse()
            self.state = self.STATE_LANDED
            self.land_timer = 0
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if self.dragging:
            new_pos = event.globalPos() - self.drag_offset
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            self.releaseMouse()
            # Continue with landed behavior
            self.state = self.STATE_LANDED
            self.land_timer = random.randint(40, 120)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_flight()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            QApplication.quit()

    # ---------- context menu ----------
    def _show_menu(self, pos=None):
        menu = QMenu(self)
        # Make menu borderless-ish and clean
        menu.setStyleSheet("""
            QMenu {
                background: rgba(40, 40, 40, 230);
                color: white;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 22px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #e74c3c;
            }
        """)

        fly_action = QAction("让它飞一下", self)
        fly_action.triggered.connect(self._start_flight)
        menu.addAction(fly_action)

        quit_action = QAction("退  出", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        if pos is None:
            pos = QCursor.pos()
        menu.exec_(pos)


def main():
    # High-DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running until explicitly quit

    pet = BugPet()
    pet.show()

    # Hide from screen sharing tools that look at taskbar
    # pet.setWindowFlags(pet.windowFlags() | Qt.Tool)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()