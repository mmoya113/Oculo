import math
import threading
import time

import pytest

from oculo.aim import AimEngine, ScreenGeometry, Target, options
from oculo.aim_runtime import AimRuntime
from oculo.config import Settings


def box(x, y=0, cls=0):
    return Target(x-10, y-20, x+10, y+20, cls)


@pytest.mark.parametrize("mode", ["linear", "bezier", "exponential", "adaptive"])
@pytest.mark.parametrize("hz", [30, 60, 120])
def test_closed_loop_stationary_converges_without_overshoot(mode, hz):
    s = Settings(aim_mode=mode, aim_deadzone=1, aim_fov=500)
    engine, x, y = AimEngine(), 120., -50.
    for i in range(hz*15):
        dx, dy = engine.step([box(x, y)], (0, 0), i/hz, s)
        assert 0 <= dx <= max(0, x-1) + 1e-9
        assert min(0, y+1)-1e-9 <= dy <= 0
        assert math.hypot(dx, dy) <= s.aim_max_step + 1e-9
        x -= dx
        y -= dy
    assert math.hypot(x, y) < 2


@pytest.mark.parametrize("mode", ["linear", "bezier", "exponential", "adaptive"])
def test_camera_and_target_reversals_never_send_wrong_direction(mode):
    engine = AimEngine()
    s = Settings(aim_mode=mode, aim_prediction_ms=100, aim_prediction_limit=30,
                 aim_ema=.05, aim_lost_ms=0)
    # Screen-space trace includes camera motion, crossing the reticle and jitter.
    for i, x in enumerate([80, 65, 50, 25, 6, 1, -3, -20, -40, -4, 8, 2, -1]*10):
        dx, dy = engine.step([box(x)], (0, 0), i/60, s)
        assert dx*x >= 0
        assert abs(dx) <= max(0, abs(x)-s.aim_deadzone) + 1e-9
        assert dy == 0


def test_nearest_fov_and_sticky_grace_no_blind_motion():
    e, s = AimEngine(), Settings(aim_fov=100, aim_match_radius=30)
    e.step([box(80), box(40), box(105)], (0,0), 0, s)
    assert e.target.point(.5) == (40,0)
    e.step([box(42), box(5)], (0,0), .02, s)
    assert e.target.point(.5) == (42,0)
    assert e.step([box(5)], (0,0), .04, s) == (0,0)
    e.step([box(5)], (0,0), .18, s)
    assert e.target.point(.5) == (5,0)


def test_no_target_outside_fov_and_invalid_boxes():
    e, s = AimEngine(), Settings(aim_fov=20, aim_limit_fov=True)
    assert e.step([box(21), box(float("nan")), Target(10,0,0,10,0)], (0,0), 0, s) == (0,0)


def test_nonsticky_selects_nearest_and_class_change_resets():
    e, s = AimEngine(), Settings(aim_sticky=False)
    e.step([box(40)], (0,0), 0, s)
    e.step([box(42), box(-5, cls=1)], (0,0), .02, s)
    assert e.target.class_id == 1
    assert e.filtered[0] == -5


def test_retina_negative_monitor_offset_and_crop():
    g = ScreenGeometry(-1400, 200, 640, 400, 1280, 800, -1280, 450)
    assert g.point(240,500) == (-1280,450)
    assert g.local_crosshair == (240,500)
    assert g.targets([box(240,500)])[0].point(.5) == g.crosshair
    # Unequal scaling is handled per axis, never assumed to be 2x.
    assert ScreenGeometry(10,20,100,100,200,100,60,70).point(100,50) == (60,70)


def test_presets_roundtrip_and_nonfinite_limits(tmp_path):
    s = Settings.from_dict({"aim_gain_x":float("nan"), "aim_fov":float("inf"),
                            "aim_mode":"bezier", "obsolete":42})
    assert options(s)["gain_x"] == 1
    assert options(s)["fov"] == 180
    p = tmp_path / "settings.json"
    s.save(p)
    assert Settings.load(p).aim_mode == "bezier"
    assert Settings.from_dict({"confidence":.3}).aim_enabled is False


def test_gain_limits_frame_gap_and_duplicate_observations():
    e, s = AimEngine(), Settings(aim_gain_x=2, aim_deadzone=0)
    a = e.step([box(40)], (0,0), 1, s)[0]
    assert e.step([box(40)], (0,0), 1, s) == (0,0)
    assert e.step([box(40)], (0,0), .5, s) == (0,0)
    b = e.step([box(-40)], (0,0), 10, s)[0]
    assert a == pytest.approx(-b)


class FakeInput:
    def __init__(self):
        self.keys = set()
        self.moves = []
        self.allowed = True
    def ready(self):
        return self.allowed
    def pressed(self, binding):
        return binding in self.keys
    def move(self, dx, dy):
        self.moves.append((dx,dy))


def runtime():
    backend = FakeInput()
    s = Settings(aim_enabled=True)
    clock = [1.]
    r = AimRuntime(s, lambda:backend, lambda:clock[0])
    return r, backend, s, clock


def submit(r, clock, x=60, context="screen"):
    r.submit([box(x)], (0,0), clock[0], context)


def test_release_panic_rearm_and_once_per_frame():
    r, b, s, t = runtime()
    b.keys.add("mouse:right")
    r.tick()  # activation consumes old observations
    submit(r,t)
    r.tick()
    r.tick()
    assert len(b.moves) == 1
    b.keys.clear()
    r.tick()
    t[0] += .02
    submit(r,t)
    r.tick()
    assert len(b.moves) == 1
    b.keys.update(["mouse:right", "key:f8"])
    r.tick()
    assert "PARADA" in r.status
    b.keys.remove("key:f8")
    submit(r,t)
    r.tick()
    assert len(b.moves) == 1
    s.aim_enabled = False
    r.configure(s)
    s.aim_enabled = True
    r.configure(s)
    r.tick()
    t[0] += .02
    submit(r,t)
    r.tick()
    assert len(b.moves) == 2
    r.close()
    submit(r,t)
    r.tick()
    assert len(b.moves) == 2


@pytest.mark.parametrize("source", ["video", "camera"])
def test_non_screen_never_constructs_backend(source):
    s = Settings(aim_enabled=True, source=source)
    r = AimRuntime(s, lambda:pytest.fail("must not initialize OS input"))
    r.tick()
    assert "sin movimiento" in r.status


def test_permissions_stale_and_context_reset():
    r,b,s,t = runtime()
    b.keys.add("mouse:right")
    r.tick()
    submit(r,t)
    t[0] += 1
    r.tick()
    assert not b.moves
    assert "caducada" in r.status
    b.allowed = False
    submit(r,t)
    r.tick()
    assert not b.moves
    b.allowed = True
    r.tick()
    submit(r,t,context="other-monitor")
    r.tick()
    assert len(b.moves) == 1


def test_emergency_polling_runs_without_detector_frames():
    r,b,s,t = runtime()
    r.start()
    b.keys.add("key:f8")
    deadline = time.monotonic()+1
    while "PARADA" not in r.status and time.monotonic() < deadline:
        time.sleep(.005)
    r.close()
    assert "PARADA" in r.status
    assert not b.moves


def test_identical_or_unknown_binding_rejected():
    r,b,s,t = runtime()
    s.aim_emergency = s.aim_activation
    r.configure(s)
    with pytest.raises(ValueError):
        r.tick()


def test_inflight_frame_from_old_settings_is_rejected():
    r,b,s,t = runtime()
    b.keys.add("mouse:right")
    r.tick()
    old = s.copy()
    s.zone_offset_x = 20
    r.configure(s)
    r.tick()
    r.submit([box(60)], (0,0), t[0], "old", old)
    r.tick()
    assert not b.moves
    r.submit([box(60)], (0,0), t[0], "new", s)
    r.tick()
    assert len(b.moves) == 1


def test_macos_adapter_loads_without_prompt_or_posting():
    import sys
    if sys.platform != "darwin":
        pytest.skip("Quartz is macOS only")
    import subprocess
    # Quartz may initialize Apple's main bundle before Qt locates its plugins.
    # Isolate the native probe; the actual app constructs QApplication first.
    result = subprocess.run([sys.executable, "-c",
        "from oculo.macos_input import QuartzInput; b=QuartzInput(); "
        "assert isinstance(b.ready(), bool); "
        "assert b.pressed('key:unknown') is False"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
