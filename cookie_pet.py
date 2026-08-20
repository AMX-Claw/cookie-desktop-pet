#!/usr/bin/env python3
"""Cookie macOS desktop pet — transparent PyObjC window using Cookie's real art."""

from __future__ import annotations

import fcntl
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import AppKit
import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
    NSGraphicsContext,
    NSImage,
    NSImageInterpolationHigh,
    NSMenu,
    NSMenuItem,
    NSPoint,
    NSRect,
    NSRunLoopCommonModes,
    NSScreen,
    NSSize,
    NSString,
    NSTimer,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
)
from PyObjCTools import AppHelper


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets_compact"
STATE_FILE = Path.home() / ".cookie_desktop_pet_state.json"
LOCK_FILE = Path.home() / ".cookie_desktop_pet.lock"
PID_FILE = Path.home() / ".cookie_desktop_pet.pid"

WIN_W = 92
WIN_H = 100
FPS = 24.0
MOUSE_IDLE_SLEEP_SECONDS = float(os.environ.get("COOKIE_MOUSE_IDLE_SECONDS", "45"))
ACTIVE_BREAK_SECONDS = float(os.environ.get("COOKIE_BREAK_SECONDS", "2700"))
SYSTEM_POLL_SECONDS = float(os.environ.get("COOKIE_SYSTEM_POLL_SECONDS", "30"))
MISCHIEF_MIN_SECONDS = float(os.environ.get("COOKIE_MISCHIEF_MIN_SECONDS", "180"))
MISCHIEF_MAX_SECONDS = float(os.environ.get("COOKIE_MISCHIEF_MAX_SECONDS", "420"))


def rgba(hex_color: str, alpha: float = 1.0):
    h = hex_color.lstrip("#")
    return NSColor.colorWithRed_green_blue_alpha_(
        int(h[0:2], 16) / 255,
        int(h[2:4], 16) / 255,
        int(h[4:6], 16) / 255,
        alpha,
    )


def load_image(name: str) -> NSImage:
    path = ASSETS / name
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        raise RuntimeError(f"Cannot load Cookie asset: {path}")
    return image


class CookieView(AppKit.NSView):
    controller = None

    def initWithFrame_(self, frame):
        self = objc.super(CookieView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.images = {
            name: load_image(name)
            for name in (
                "idle.png", "down.png", "sleep.png", "stand.png",
                "patch_tail.png", "tail.png", "patch_legs.png",
                "leg_BR.png", "leg_FR.png", "leg_BL.png", "leg_FL.png",
                "body.png", "patch_neck.png", "head.png",
                "lid_L.png", "lid_R.png",
            )
        }
        self.phase = 0.0
        self.blink = False
        self.message = ""
        self.message_until = 0.0
        self.drag_start = None
        self.drag_origin = None
        self.dragged = False
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def menuForEvent_(self, event):
        menu = NSMenu.alloc().initWithTitle_("Cookie")
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "让 Cookie 回家（退出）", "terminate:", "q"
        )
        menu.addItem_(item)
        return menu

    def mouseDown_(self, event):
        self.drag_start = NSEvent.mouseLocation()
        self.drag_origin = self.window().frame().origin
        self.dragged = False
        if event.clickCount() >= 2 and self.controller:
            self.controller.do_trick()

    def mouseDragged_(self, event):
        if self.drag_start is None or self.drag_origin is None:
            return
        now = NSEvent.mouseLocation()
        dx = now.x - self.drag_start.x
        dy = now.y - self.drag_start.y
        if abs(dx) + abs(dy) > 3:
            self.dragged = True
            if self.controller:
                self.controller.dragging = True
        self.window().setFrameOrigin_(
            NSPoint(self.drag_origin.x + dx, self.drag_origin.y + dy)
        )

    def mouseUp_(self, event):
        if self.controller:
            if not self.dragged and event.clickCount() < 2:
                self.controller.pet()
            self.controller.finish_drag()
        self.drag_start = None
        self.drag_origin = None
        self.dragged = False

    @objc.python_method
    def say(self, text: str, duration: float = 3.0):
        self.message = text
        self.message_until = time.time() + duration

    @objc.python_method
    def _draw_image(self, image: NSImage, rect: NSRect, *, angle=0.0, pivot=None):
        ctx = NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()
        if angle and pivot:
            transform = AppKit.NSAffineTransform.transform()
            transform.translateXBy_yBy_(pivot[0], pivot[1])
            transform.rotateByDegrees_(angle)
            transform.translateXBy_yBy_(-pivot[0], -pivot[1])
            transform.concat()
        image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
            rect,
            NSRect(NSPoint(0, 0), image.size()),
            AppKit.NSCompositingOperationSourceOver,
            1.0,
            True,
            None,
        )
        ctx.restoreGraphicsState()

    @objc.python_method
    def _dog_rect(self, bob=0.0, squash=1.0):
        width = 70.5
        height = width * 1070.0 / 950.0
        scaled_h = height * squash
        return NSRect(
            NSPoint((WIN_W - width) / 2.0, WIN_H - 3.0 - scaled_h + bob),
            NSSize(width, scaled_h),
        )

    @objc.python_method
    def _begin_facing(self, rect, facing, turn_scale=1.0):
        ctx = NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()
        center_x = rect.origin.x + rect.size.width / 2.0
        transform = AppKit.NSAffineTransform.transform()
        transform.translateXBy_yBy_(center_x, 0)
        # 原画天然朝左：world facing=-1 时不镜像，facing=+1 时才镜像。
        transform.scaleXBy_yBy_(-facing * turn_scale, 1.0)
        transform.translateXBy_yBy_(-center_x, 0)
        transform.concat()

    @objc.python_method
    def _end_facing(self):
        NSGraphicsContext.currentContext().restoreGraphicsState()

    @objc.python_method
    def _draw_rig(self, rect, facing, gait_phase, turn_scale=1.0, *, walking=True, head_angle=0.0):
        self._begin_facing(rect, facing, turn_scale)
        x, y, w, h = rect.origin.x, rect.origin.y, rect.size.width, rect.size.height

        def pivot(px, py):
            return (x + w * px, y + h * py)

        swing = math.sin(gait_phase * math.tau) if walking else 0.0
        # Each diagonal pair swings only while airborne and returns exactly to
        # the source pose for contact.  The asset pipeline also gives every paw
        # exclusive pixels below its pivot, so rotation cannot tear a shared
        # edge into a second toe.
        pair_a_lift = max(0.0, swing)
        pair_b_lift = max(0.0, -swing)
        tail_swing = (-9.0 * swing) if walking else (3.2 * math.sin(gait_phase * math.tau * .42))
        head_nod = (3.2 * math.sin(gait_phase * math.tau + .4)) if walking else head_angle
        layers = (
            ("patch_tail.png", 0, None),
            ("tail.png", tail_swing, pivot(.802, .614)),
            ("patch_legs.png", 0, None),
            # Original art faces left. Negative rotation reaches a foreleg
            # forward; positive rotation lets the diagonal hind leg push back.
            # Opposite signs make the trot readable at only ~70 px wide.
            ("leg_BR.png", 22.0 * pair_a_lift, pivot(.674, .841)),
            ("leg_FR.png", -28.0 * pair_b_lift, pivot(.474, .866)),
            ("leg_BL.png", 22.0 * pair_b_lift, pivot(.805, .829)),
            ("leg_FL.png", -28.0 * pair_a_lift, pivot(.305, .872)),
            ("body.png", 0, None),
            ("patch_neck.png", 0, None),
            ("head.png", head_nod, pivot(.421, .577)),
        )
        for name, angle, joint in layers:
            self._draw_image(self.images[name], rect, angle=angle, pivot=joint)
        if self.blink:
            self._draw_image(self.images["lid_L.png"], rect)
            self._draw_image(self.images["lid_R.png"], rect)
        self._end_facing()

    @objc.python_method
    def _draw_state(self, name, rect, facing, turn_scale=1.0):
        self._begin_facing(rect, facing, turn_scale)
        self._draw_image(self.images[name], rect)
        self._end_facing()

    @objc.python_method
    def _draw_sleep_zs(self, facing):
        """Three staggered Zs that rise, grow, and fade in a soft loop."""
        clock = time.time() * .38
        # The sleep artwork's head sits just right of centre in its natural
        # left-facing pose. Mirror the emitter with the dog, so the Zs always
        # begin above her head instead of at the window's top-left corner.
        head_x = 52.0 if facing == -1 else 40.0
        drift = 1.0 if facing == -1 else -1.0
        for index in range(3):
            progress = (clock + index / 3.0) % 1.0
            alpha = math.sin(progress * math.pi) ** 1.35 * .82
            size = 6.5 + progress * 4.5
            x = head_x + drift * (
                progress * 9.0 + math.sin(progress * math.tau) * 1.2
            )
            y = 64.0 - progress * 29.0
            NSString.stringWithString_("Z").drawAtPoint_withAttributes_(
                NSPoint(x, y),
                {
                    NSFontAttributeName: NSFont.boldSystemFontOfSize_(size),
                    NSForegroundColorAttributeName: rgba("#7460a8", alpha),
                },
            )

    @objc.python_method
    def _draw_mail_envelope(self, facing):
        x = 48 if facing == -1 else 34
        NSString.stringWithString_("✉︎").drawAtPoint_withAttributes_(
            NSPoint(x, 64),
            {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(12),
                NSForegroundColorAttributeName: rgba("#c84d43", .95),
            },
        )

    @objc.python_method
    def _draw_bubble(self):
        if not self.message or time.time() >= self.message_until:
            return
        font = NSFont.systemFontOfSize_(8.5)
        attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: rgba("#4a3826")}
        text = NSString.stringWithString_(self.message)
        size = text.sizeWithAttributes_(attrs)
        width = min(WIN_W - 4, size.width + 10)
        rect = NSRect(NSPoint((WIN_W - width) / 2, 1), NSSize(width, 18))
        rgba("#fffaf0", .94).set()
        bubble = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 10, 10)
        bubble.fill()
        rgba("#c84d43", .75).set()
        bubble.setLineWidth_(1.2)
        bubble.stroke()
        text.drawAtPoint_withAttributes_(NSPoint(rect.origin.x + 5, 5), attrs)

    def drawRect_(self, dirty_rect):
        NSColor.clearColor().set()
        AppKit.NSRectFill(dirty_rect)
        ctx = NSGraphicsContext.currentContext()
        ctx.setImageInterpolation_(NSImageInterpolationHigh)

        c = self.controller
        if c is None:
            return
        bob = 0.0
        squash = 1.0
        turn_scale = 1.0
        if c.state == "walk":
            bob = -.7 * abs(math.sin(self.phase * math.tau))
        elif c.state == "idle":
            squash = 1.0 + .016 * math.sin(self.phase * math.tau)
        elif c.state == "sleep":
            squash = 1.0 + .024 * math.sin(self.phase * math.tau)
        elif c.state == "down":
            squash = 1.0 + .010 * math.sin(self.phase * math.tau)

        if c.turning:
            p = c.turn_phase
            turn_scale = .80 + .20 * abs(2 * p - 1)
            bob += 1.3 * math.sin(p * math.pi)

        rect = self._dog_rect(bob=bob, squash=squash)
        facing = c.draw_facing
        if c.state == "walk" or c.turning:
            self._draw_rig(rect, facing, self.phase, turn_scale, walking=True)
        elif c.state == "down":
            self._draw_state("down.png", rect, facing)
        elif c.state == "sleep":
            self._draw_state("sleep.png", rect, facing)
            self._draw_sleep_zs(facing)
        elif c.state == "stand":
            self._draw_state("stand.png", rect, facing)
        else:
            self._draw_rig(
                rect,
                facing,
                self.phase,
                walking=False,
                head_angle=c.look_angle,
            )
        if time.time() < c.mail_alert_until:
            self._draw_mail_envelope(facing)
        self._draw_bubble()


class CookieController:
    def __init__(self):
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(1)

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSRect(NSPoint(0, 0), NSSize(WIN_W, WIN_H)),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setOpaque_(False)
        self.window.setHasShadow_(False)
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setIgnoresMouseEvents_(False)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        self.view = CookieView.alloc().initWithFrame_(
            NSRect(NSPoint(0, 0), NSSize(WIN_W, WIN_H))
        )
        self.view.controller = self
        self.window.setContentView_(self.view)

        self.state = "idle"
        self.state_until = time.time() + random.uniform(3.5, 7.0)
        self.force_state = os.environ.get("COOKIE_FORCE_STATE")
        if self.force_state in ("idle", "walk", "down", "sleep", "stand"):
            self.state = self.force_state
            self.state_until = float("inf")
        self.facing = random.choice((-1, 1))
        self.draw_facing = self.facing
        self.turning = False
        self.turn_started = 0.0
        self.turn_phase = 0.0
        self.next_facing = self.facing
        # At this tiny display size, a fast window translation reads as sliding
        # even when the paws animate correctly.  Keep the travel distance per
        # gait cycle short enough that the planted pair visibly grips the desk.
        self.speed = 0.45
        self.tick_count = 0
        self.dragging = False
        self.last_tick = time.time()
        self.look_angle = 0.0
        self.look_target = 0.0
        self.next_look_at = time.time() + random.uniform(2.5, 5.5)
        mouse = NSEvent.mouseLocation()
        self.last_mouse_point = (mouse.x, mouse.y)
        self.last_mouse_moved_at = time.time()
        self.sleep_due_to_mouse_idle = False
        self.active_started_at = time.time()
        self.mail_unread_seen = None
        self.mail_alert_until = 0.0
        self.latest_mail_unread = None
        self.memory_pressure_level = "normal"
        self.memory_high_samples = 0
        self.memory_sleep_requested = False
        self.monitor_stop = threading.Event()
        self.mischief_target_x = None
        self.mischief_until = 0.0
        self.next_mischief_at = time.time() + random.uniform(
            MISCHIEF_MIN_SECONDS, MISCHIEF_MAX_SECONDS
        )

        self._restore_position()
        # NSWindow origins are effectively snapped to backing pixels. At the
        # slow gait, each 24 fps tick travels < 1 px; reading the snapped frame
        # back on every tick would discard that fraction forever and make the
        # dog walk in place. Keep a separate sub-pixel accumulator.
        self.walk_x = float(self.window.frame().origin.x)
        self.window.makeKeyAndOrderFront_(None)
        self.view.say("妈妈，我来桌面上散步啦 🐕", 4.5)

        self.monitor_thread = threading.Thread(
            target=self._system_monitor_loop,
            name="CookieSystemMonitor",
            daemon=True,
        )
        self.monitor_thread.start()

        self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / FPS,
            self,
            objc.selector(self.update_, signature=b"v@:@"),
            None,
            True,
        )
        NSRunLoopCommonModes_value = NSRunLoopCommonModes
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes_value)

    @objc.python_method
    def _system_monitor_loop(self):
        """Low-frequency, metadata-only system sensing off the UI thread."""
        while not self.monitor_stop.is_set():
            try:
                result = subprocess.run(
                    ["/usr/bin/memory_pressure", "-Q"],
                    capture_output=True,
                    text=True,
                    timeout=6,
                    check=False,
                )
                match = re.search(r"free percentage:\s*(\d+)%", result.stdout)
                if match:
                    free = int(match.group(1))
                    if free < 5:
                        self.memory_pressure_level = "critical"
                    elif free < 10:
                        self.memory_pressure_level = "high"
                    elif free < 20:
                        self.memory_pressure_level = "elevated"
                    else:
                        self.memory_pressure_level = "normal"
                    if self.memory_pressure_level in ("high", "critical"):
                        self.memory_high_samples += 1
                        if self.memory_high_samples >= 3:
                            self.memory_sleep_requested = True
                            self.memory_high_samples = 0
                    else:
                        self.memory_high_samples = 0
            except (OSError, subprocess.SubprocessError):
                pass

            # Asking Mail for one integer can wake a closed app, so only poll
            # while Mail is already running. No subject, sender, or body leaves it.
            try:
                running = subprocess.run(
                    ["/usr/bin/pgrep", "-x", "Mail"],
                    capture_output=True,
                    timeout=3,
                    check=False,
                ).returncode == 0
                if running:
                    result = subprocess.run(
                        [
                            "/usr/bin/osascript",
                            "-e",
                            'tell application "Mail" to get unread count of inbox',
                        ],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        check=False,
                    )
                    value = result.stdout.strip()
                    if result.returncode == 0 and value.isdigit():
                        self.latest_mail_unread = int(value)
            except (OSError, subprocess.SubprocessError):
                pass

            self.monitor_stop.wait(SYSTEM_POLL_SECONDS)

    @objc.python_method
    def _consume_system_events(self, now):
        unread = self.latest_mail_unread
        if unread is not None:
            self.latest_mail_unread = None
            previous = self.mail_unread_seen
            self.mail_unread_seen = unread
            if previous is not None and unread > previous:
                delta = unread - previous
                self.mail_alert_until = now + 5.5
                if not self.force_state:
                    self.turning = False
                    self.state = "stand"
                    self.state_until = now + 4.5
                self.view.say(f"有 {delta} 封新邮件 ✉︎", 4.8)
            if previous != unread:
                self._save_position()

        if self.memory_sleep_requested:
            self.memory_sleep_requested = False
            if not self.force_state and self.state != "sleep":
                self.turning = False
                self.state = "sleep"
                self.sleep_due_to_mouse_idle = False
                self.state_until = now + 45
                self.view.say("电脑也累啦，一起歇会儿", 5.0)

    @objc.python_method
    def _maybe_remind_break(self, now):
        if (
            not self.force_state
            and not self.dragging
            and now - self.last_mouse_moved_at < 60
            and now - self.active_started_at >= ACTIVE_BREAK_SECONDS
        ):
            self.turning = False
            self.state = "stand"
            self.state_until = now + 4.5
            self.active_started_at = now
            self.view.say("妈妈，起来伸个懒腰吧", 5.0)

    @objc.python_method
    def _maybe_start_mischief(self, now):
        if self.mischief_target_x is not None:
            if now >= self.mischief_until:
                self.mischief_target_x = None
                self.next_mischief_at = now + random.uniform(
                    MISCHIEF_MIN_SECONDS, MISCHIEF_MAX_SECONDS
                )
            return
        if self.force_state or now < self.next_mischief_at or self.dragging:
            return
        mouse = NSEvent.mouseLocation()
        visible = self._visible_frame()
        # She only chases a cursor already near the desktop floor. No vertical
        # window jump, and the cursor itself is never moved or clicked.
        if mouse.y > visible.origin.y + 190:
            self.next_mischief_at = now + 60
            return
        target = mouse.x - WIN_W / 2
        target = min(
            max(target, visible.origin.x),
            visible.origin.x + visible.size.width - WIN_W,
        )
        self.mischief_target_x = target
        self.mischief_until = now + 24
        self.turning = False
        self.state = "walk"
        self.state_until = self.mischief_until
        self.view.say("嘿嘿，鼠标给我咬一口", 3.5)

    @objc.python_method
    def _visible_frame_for_origin(self, x, y):
        center = NSPoint(x + WIN_W / 2, y + WIN_H / 2)
        screens = list(NSScreen.screens())
        for screen in screens:
            if AppKit.NSPointInRect(center, screen.frame()):
                return screen.visibleFrame()

        # A monitor may have been unplugged since the position was saved. Pick
        # the screen whose full frame is nearest to the old window center.
        def distance_sq(screen):
            frame = screen.frame()
            left, bottom = frame.origin.x, frame.origin.y
            right = left + frame.size.width
            top = bottom + frame.size.height
            nearest_x = min(max(center.x, left), right)
            nearest_y = min(max(center.y, bottom), top)
            return (center.x - nearest_x) ** 2 + (center.y - nearest_y) ** 2

        screen = min(screens, key=distance_sq) if screens else NSScreen.mainScreen()
        return screen.visibleFrame()

    @objc.python_method
    def _visible_frame(self):
        frame = self.window.frame()
        return self._visible_frame_for_origin(frame.origin.x, frame.origin.y)

    @objc.python_method
    def _restore_position(self):
        main_visible = NSScreen.mainScreen().visibleFrame()
        x = main_visible.origin.x + (main_visible.size.width - WIN_W) / 2
        y = main_visible.origin.y + 8
        try:
            data = json.loads(STATE_FILE.read_text())
            x = float(data.get("x", x))
            y = float(data.get("y", y))
            self.facing = int(data.get("facing", self.facing))
            self.draw_facing = self.facing
            saved_unread = data.get("mail_unread")
            if isinstance(saved_unread, int) and saved_unread >= 0:
                self.mail_unread_seen = saved_unread
        except (OSError, ValueError, TypeError):
            pass
        visible = self._visible_frame_for_origin(x, y)
        x = min(max(x, visible.origin.x), visible.origin.x + visible.size.width - WIN_W)
        y = min(max(y, visible.origin.y), visible.origin.y + visible.size.height - WIN_H)
        self.window.setFrameOrigin_(NSPoint(x, y))

    @objc.python_method
    def _save_position(self):
        frame = self.window.frame()
        data = {"x": frame.origin.x, "y": frame.origin.y, "facing": self.facing}
        if self.mail_unread_seen is not None:
            data["mail_unread"] = self.mail_unread_seen
        try:
            STATE_FILE.write_text(json.dumps(data))
        except OSError:
            pass

    @objc.python_method
    def _start_turn(self, new_facing):
        if self.turning or new_facing == self.facing:
            return
        self.turning = True
        self.next_facing = new_facing
        self.draw_facing = self.facing
        self.turn_started = time.time()
        self.turn_phase = 0.0

    @objc.python_method
    def _advance_turn(self, now):
        self.turn_phase = min(1.0, (now - self.turn_started) / .72)
        if self.turn_phase >= .5:
            self.draw_facing = self.next_facing
        if self.turn_phase >= 1.0:
            self.facing = self.next_facing
            self.draw_facing = self.facing
            self.turning = False
            self.turn_phase = 0.0

    @objc.python_method
    def _change_state(self):
        now = time.time()
        if self.state == "down":
            self.state = "sleep"
            self.sleep_due_to_mouse_idle = False
            self.state_until = now + random.uniform(12, 24)
        elif self.state == "sleep":
            self.state = "idle"
            self.state_until = now + random.uniform(3, 6)
        elif self.state == "stand":
            self.state = "idle"
            self.state_until = now + random.uniform(3, 6)
        else:
            choice = random.choices(("walk", "idle", "down"), weights=(55, 30, 15), k=1)[0]
            self.state = choice
            if choice == "walk":
                self.state_until = now + random.uniform(7, 15)
            elif choice == "down":
                self.state_until = now + random.uniform(7, 12)
            else:
                self.state_until = now + random.uniform(3, 7)

    @objc.python_method
    def pet(self):
        self.sleep_due_to_mouse_idle = False
        self.last_mouse_moved_at = time.time()
        self.state = "idle"
        self.state_until = time.time() + random.uniform(4, 7)
        self.view.say(random.choice((
            "嗯……就这里，再摸一下",
            "尾巴已经摇起来了",
            "妈妈的手，我认得",
            "十六岁也还是小宝宝",
        )), 3.2)

    @objc.python_method
    def do_trick(self):
        self.sleep_due_to_mouse_idle = False
        self.last_mouse_moved_at = time.time()
        self.state = "stand"
        self.state_until = time.time() + 2.8
        self.view.say("给妈妈作个揖 🐾", 2.6)

    @objc.python_method
    def finish_drag(self):
        self.dragging = False
        visible = self._visible_frame()
        frame = self.window.frame()
        x = min(max(frame.origin.x, visible.origin.x), visible.origin.x + visible.size.width - WIN_W)
        y = min(max(frame.origin.y, visible.origin.y), visible.origin.y + visible.size.height - WIN_H)
        self.window.setFrameOrigin_(NSPoint(x, y))
        self.walk_x = float(x)
        self._save_position()

    @objc.python_method
    def _track_mouse_activity(self, now):
        mouse = NSEvent.mouseLocation()
        current = (mouse.x, mouse.y)
        dx = current[0] - self.last_mouse_point[0]
        dy = current[1] - self.last_mouse_point[1]
        moved = dx * dx + dy * dy >= 4.0
        if moved:
            idle_gap = now - self.last_mouse_moved_at
            if idle_gap >= 300:
                self.active_started_at = now
            self.last_mouse_point = current
            self.last_mouse_moved_at = now
            if self.sleep_due_to_mouse_idle:
                self.sleep_due_to_mouse_idle = False
                self.state = "idle"
                self.state_until = now + random.uniform(4, 7)
                self.view.say("你回来啦", 2.2)
        elif (
            now - self.last_mouse_moved_at >= MOUSE_IDLE_SLEEP_SECONDS
            and not self.sleep_due_to_mouse_idle
            and self.state not in ("sleep", "stand")
        ):
            self.turning = False
            self.state = "sleep"
            self.sleep_due_to_mouse_idle = True
            self.state_until = float("inf")

    @objc.python_method
    def _update_idle_look(self, now, dt):
        if self.state == "idle":
            if now >= self.next_look_at:
                self.look_target = random.choice((-7.0, 0.0, 7.0))
                self.next_look_at = now + random.uniform(2.2, 5.5)
        else:
            self.look_target = 0.0
        amount = min(1.0, dt * 4.8)
        self.look_angle += (self.look_target - self.look_angle) * amount

    @objc.python_method
    def _tick(self):
        now = time.time()
        dt = min(.08, max(0.0, now - self.last_tick))
        self.last_tick = now
        self.tick_count += 1
        phase_speed = 1.05 if self.state == "walk" else (.22 if self.state == "sleep" else .30)
        self.view.phase = (self.view.phase + dt * phase_speed) % 1.0
        self.view.blink = (self.tick_count % 145) in (0, 1, 2, 3)
        self._track_mouse_activity(now)
        self._consume_system_events(now)
        self._maybe_remind_break(now)
        self._maybe_start_mischief(now)
        self._update_idle_look(now, dt)

        if self.turning:
            self._advance_turn(now)
        elif not self.force_state and now >= self.state_until:
            self._change_state()

        if self.state == "walk" and not self.turning:
            frame = self.window.frame()
            visible = self._visible_frame()
            min_x = visible.origin.x
            max_x = visible.origin.x + visible.size.width - WIN_W
            if self.mischief_target_x is not None:
                remaining = self.mischief_target_x - self.walk_x
                if abs(remaining) <= 5:
                    self.walk_x = self.mischief_target_x
                    self.window.setFrameOrigin_(NSPoint(self.walk_x, frame.origin.y))
                    self.mischief_target_x = None
                    self.next_mischief_at = now + random.uniform(
                        MISCHIEF_MIN_SECONDS, MISCHIEF_MAX_SECONDS
                    )
                    self.state = "stand"
                    self.state_until = now + 2.8
                    self.view.say("（啃啃）抓到你啦", 3.2)
                    self.view.setNeedsDisplay_(True)
                    return
                desired_facing = 1 if remaining > 0 else -1
                if desired_facing != self.facing:
                    self._start_turn(desired_facing)
                    self.view.setNeedsDisplay_(True)
                    return
            self.walk_x += self.facing * self.speed * dt * FPS
            x = self.walk_x
            if x <= min_x:
                x = min_x
                self.walk_x = x
                self._start_turn(1)
            elif x >= max_x:
                x = max_x
                self.walk_x = x
                self._start_turn(-1)
            self.window.setFrameOrigin_(NSPoint(x, frame.origin.y))

        self.view.setNeedsDisplay_(True)

    def update_(self, timer):
        self._tick()

    @objc.python_method
    def run(self):
        AppHelper.runEventLoop()


def acquire_lock():
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Cookie is already walking on the desktop.")
        raise SystemExit(0)
    return lock_fd


if __name__ == "__main__":
    _lock = acquire_lock()
    PID_FILE.write_text(str(os.getpid()))
    try:
        controller = CookieController()
        controller.run()
    finally:
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
