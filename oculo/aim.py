"""Deterministic, feedback-only aim controller. No OS or Qt dependencies.

One bounded relative step per observation; never queue an interpolated path.
Prediction describes SCREEN motion, not world velocity: camera motion cannot
be identified from bounding boxes alone. Keep it off for streamed games.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .config import Settings


@dataclass(frozen=True)
class Target:
    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int
    confidence: float = 1.0

    def point(self, y: float) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, self.y1 + (self.y2 - self.y1) * y

    def valid(self) -> bool:
        return (all(math.isfinite(v) for v in
                    (self.x1, self.y1, self.x2, self.y2, self.confidence))
                and self.x2 > self.x1 and self.y2 > self.y1)


def bounded(value, low, high, default):
    try:
        number = float(value)
        return max(low, min(high, number)) if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def options(s: Settings) -> dict:
    """Validate external presets at the control boundary, including NaN/inf."""
    limits = {
        "fov": (1, 2000, 180), "match_radius": (1, 500, 80),
        "lost_ms": (0, 500, 120), "point_y": (0, 1, .5),
        "response_ms": (20, 2000, 180), "ema": (.01, 1, .65),
        "prediction_ms": (0, 100, 0), "prediction_limit": (0, 30, 8),
        "deadzone": (0, 30, 2), "max_step": (1, 100, 8),
        "max_speed": (1, 3000, 400), "gain_x": (.05, 10, 1),
        "gain_y": (.05, 10, 1), "stale_ms": (20, 500, 200),
    }
    return {k: bounded(getattr(s, "aim_" + k), *v) for k, v in limits.items()}


def eligible_targets(targets, crosshair, s):
    p = options(s)
    return [t for t in targets if t.valid() and (not s.aim_limit_fov or
            math.dist(t.point(p["point_y"]), crosshair) <= p["fov"])]


def overlap(a: Target, b: Target) -> float:
    area = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(
        0, min(a.y2, b.y2) - max(a.y1, b.y1))
    return area / max(1e-9, (a.x2-a.x1)*(a.y2-a.y1) +
                           (b.x2-b.x1)*(b.y2-b.y1) - area)


class AimEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.target = None
        self.seen = None
        self.time = None
        self.filtered = None
        self.previous_error = None
        self.signature = None

    def step(self, targets: list[Target], crosshair: tuple[float, float],
             now: float, s: Settings) -> tuple[float, float]:
        p = options(s)
        signature = tuple(p.items()) + (s.aim_mode, s.aim_sticky, s.aim_limit_fov)
        if signature != self.signature:
            self.reset()
            self.signature = signature
        if not math.isfinite(now) or not all(math.isfinite(v) for v in crosshair):
            self.reset()
            return 0., 0.
        if self.time is not None and now <= self.time:
            return 0., 0.  # duplicates/out-of-order observations
        gap = None if self.time is None else now - self.time
        if gap is not None and gap > p["stale_ms"] / 1000:
            self.reset()
            self.signature = signature
            gap = None
        dt = min(1/30, gap if gap is not None else 1/120)
        self.time = now
        point = lambda t: t.point(p["point_y"])
        distance = lambda a, b: math.hypot(a[0]-b[0], a[1]-b[1])
        candidates = eligible_targets(targets, crosshair, s)
        selected = None
        continuing = False
        if s.aim_sticky and self.target is not None:
            matches = [t for t in candidates if t.class_id == self.target.class_id
                       and distance(point(t), point(self.target)) <= p["match_radius"]]
            if matches:
                selected = min(matches, key=lambda t: (
                    distance(point(t), point(self.target)) / p["match_radius"] -
                    overlap(t, self.target)))
                continuing = True
            elif self.seen is not None and now-self.seen <= p["lost_ms"]/1000:
                self.filtered = self.previous_error = None
                return 0., 0.  # identity grace only; no blind pursuit
        if selected is None and candidates:
            selected = min(candidates, key=lambda t: (
                distance(point(t), crosshair), -t.confidence, t.class_id, t.x1, t.y1))
        if selected is None:
            self.target = self.filtered = self.previous_error = None
            return 0., 0.
        if not continuing:
            self.filtered = self.previous_error = None
        self.target, self.seen = selected, now
        tx, ty = point(selected)
        error = (tx-crosshair[0], ty-crosshair[1])
        alpha = 1 - (1-p["ema"]) ** (dt*60)
        filtered = []
        for axis, raw in enumerate(error):
            old = None if self.filtered is None else self.filtered[axis]
            # Reset on sign reversal, and clamp lag to the current measured error.
            value = raw if old is None or old*raw <= 0 else old + alpha*(raw-old)
            filtered.append(math.copysign(min(abs(value), abs(raw)), raw))
        self.filtered = tuple(filtered)
        desired = list(filtered)
        if self.previous_error is not None and gap and continuing:
            for i in range(2):
                velocity = (error[i]-self.previous_error[i]) / gap
                lead = max(-p["prediction_limit"], min(p["prediction_limit"],
                           velocity * p["prediction_ms"]/1000))
                desired[i] += lead
        self.previous_error = error
        t = min(1., dt / (p["response_ms"]/1000))
        if s.aim_mode == "linear":
            fraction = t
        elif s.aim_mode == "bezier":
            fraction = 3*t*t - 2*t*t*t  # cubic Bezier easing, P1=0, P2=1
        elif s.aim_mode == "adaptive":
            fraction = 1-math.exp(-dt/(p["response_ms"]/1000) *
                                  (1+2*min(1, math.hypot(*error)/p["fov"])))
        else:
            fraction = 1-math.exp(-dt/(p["response_ms"]/1000))
        delta = []
        for i, raw in enumerate(error):
            gain = p["gain_x" if i == 0 else "gain_y"]
            available = max(0., abs(raw)-p["deadzone"])
            # Lead or EMA may never reverse direction or exceed measured error.
            value = max(0., desired[i] * (1 if raw >= 0 else -1))
            delta.append(math.copysign(min(available, value*fraction) / gain, raw))
        length = math.hypot(*delta)
        cap = min(p["max_step"], p["max_speed"]*dt)
        scale = min(1., cap/max(length, 1e-9))
        return delta[0]*scale, delta[1]*scale


@dataclass(frozen=True)
class ScreenGeometry:
    """mss region in desktop points; inference boxes in actual captured pixels."""
    left: float
    top: float
    width: float
    height: float
    pixel_width: int
    pixel_height: int
    crosshair_x: float
    crosshair_y: float

    def point(self, x, y):
        return (self.left + x*self.width/self.pixel_width,
                self.top + y*self.height/self.pixel_height)

    def targets(self, detections):
        return [Target(*self.point(d.x1, d.y1), *self.point(d.x2, d.y2),
                       d.class_id, d.confidence) for d in detections]

    @property
    def crosshair(self):
        return self.crosshair_x, self.crosshair_y

    @property
    def local_crosshair(self):
        return ((self.crosshair_x-self.left)*self.pixel_width/self.width,
                (self.crosshair_y-self.top)*self.pixel_height/self.height)


class MotionAccumulator:
    """Keep sub-point motion until Quartz can emit integer deltas.

    Remainders are bounded below one point, cleared on reversal/reset, and
    clipped to the current measured error. Nothing is queued across frames.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.carry = [0., 0.]

    def step(self, delta, limits, max_step):
        result = []
        for axis, value in enumerate(delta):
            if value == 0 or value*self.carry[axis] < 0:
                self.carry[axis] = 0.
            total = self.carry[axis] + value
            limit = math.floor(max(0., limits[axis]))
            whole = math.copysign(min(abs(math.trunc(total)), limit), total)
            result.append(int(whole))
            self.carry[axis] = (total-whole) if abs(total-whole) < 1 else 0.
        # Quantization can cross a vector cap by <sqrt(2); keep the hard cap.
        while math.hypot(*result) > max_step:
            axis = 0 if abs(result[0]) >= abs(result[1]) else 1
            result[axis] -= 1 if result[axis] > 0 else -1
            self.carry[axis] = 0.
        return tuple(result)
