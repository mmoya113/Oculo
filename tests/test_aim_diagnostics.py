import math
import subprocess
import sys

import pytest

from oculo.aim import MotionAccumulator
from oculo.aim_runtime import AimRuntime
from oculo.config import Settings
from oculo.input_probe import MovementProbe
from test_aim import FakeInput, box


def test_fractional_motion_emits_whole_points_and_clears_on_reverse():
    m = MotionAccumulator()
    result = [m.step((.2,0),(10,10),8)[0] for _ in range(10)]
    assert sum(result) == 2
    assert all(isinstance(v,int) for v in result)
    m.step((.6,0),(10,10),8)
    assert m.step((-.6,0),(10,10),8) == (0,0)
    assert m.step((-.6,0),(10,10),8) == (-1,0)
    m.reset()
    assert m.step((.6,0),(10,10),8) == (0,0)


def test_quantization_never_exceeds_current_error_or_vector_step_cap():
    m = MotionAccumulator()
    for _ in range(100):
        dx,dy = m.step((.8,.8),(.5,4),1)
        assert dx == 0
        assert math.hypot(dx,dy) <= 1
    m.reset()
    for _ in range(100):
        assert math.hypot(*m.step((.8,.8),(5,5),1)) <= 1


def setup_runtime(**kw):
    b, clock = FakeInput(), [1.]
    s = Settings(aim_enabled=True, **kw)
    r = AimRuntime(s,lambda:b,lambda:clock[0])
    b.keys.add(s.aim_activation)
    r.tick()
    return r,b,s,clock


def test_stale_reason_survives_120hz_polls_and_reports_age():
    r,b,s,t = setup_runtime()
    r.submit([box(40)],(0,0),.7,"screen")
    r.tick()
    assert r.diagnostics["stage"] == "stale"
    assert r.diagnostics["stale"] == 1
    for _ in range(20):
        r.tick()
    assert "caducada" in r.status
    assert r.diagnostics["stale"] == 1
    assert r.diagnostics["age_ms"] == pytest.approx(300)
    assert not b.moves


@pytest.mark.parametrize("targets,stage", [([],"no_detection"),([box(500)],"outside_fov"),
                                          ([box(0)],"deadzone"),([box(60)],"posting")])
def test_runtime_reasons_distinguish_detector_fov_deadzone_and_post(targets,stage):
    r,b,s,t = setup_runtime(aim_limit_fov=True)
    r.submit(targets,(0,0),t[0],"screen")
    r.tick()
    assert r.diagnostics["stage"] == stage
    assert r.diagnostics["activation"]
    assert r.diagnostics["detections"] == len(targets)
    assert bool(b.moves) == (stage == "posting")


@pytest.mark.parametrize("mode",["linear","bezier","exponential","adaptive"])
def test_runtime_small_error_eventually_posts_integer_motion_in_all_modes(mode):
    r,b,s,t = setup_runtime(aim_mode=mode,aim_deadzone=0)
    for _ in range(180):
        t[0] += 1/60
        r.submit([box(5)],(0,0),t[0],"screen")
        r.tick()
    assert b.moves
    assert all(isinstance(v,int) for move in b.moves for v in move)
    # Release discards any fractional remainder.
    b.keys.clear()
    r.tick()
    assert r._motion.carry == [0,0]


def test_no_new_frame_cannot_keep_reporting_posting():
    r,b,s,t = setup_runtime()
    r.submit([box(50)],(0,0),t[0],"screen")
    r.tick()
    t[0] += 1
    r.tick()
    assert r.diagnostics["stage"] == "stale"
    assert len(b.moves) == 1


class ProbeInput(FakeInput):
    def __init__(self, accepted=True):
        super().__init__()
        self.cursor = [100.,100.]
        self.accepted = accepted
    def position(self):
        return tuple(self.cursor)
    def permission_message(self):
        return "Falta Accesibilidad"
    def move(self,dx,dy):
        super().move(dx,dy)
        if self.accepted:
            self.cursor[0] += dx
            self.cursor[1] += dy


@pytest.mark.parametrize("accepted,expected",[(True,"correcta"),(False,"No se observó")])
def test_probe_checks_actual_cursor_displacement_without_detections(accepted,expected):
    b,t = ProbeInput(accepted), [0.]
    probe = MovementProbe(b,clock=lambda:t[0])
    assert "3 s" in probe.tick()
    assert not b.moves
    t[0] = 3.1
    probe.tick()
    assert b.moves == [(12,0)]
    t[0] = 3.3
    assert expected in probe.tick()
    assert probe.done
    probe.tick()
    assert len(b.moves) == 1


@pytest.mark.parametrize("binding",["key:f8","mouse:right"])
def test_probe_cancel_and_buttons_prevent_posting(binding):
    b,t = ProbeInput(),[4.]
    p = MovementProbe(b,clock=lambda:t[0])
    b.keys.add(binding)
    t[0] = 8.
    assert "cancelada" in p.tick()
    assert not b.moves


def test_probe_revoked_permission_cancels():
    b=ProbeInput()
    p=MovementProbe(b)
    b.allowed=False
    assert "Accesibilidad" in p.tick()
    assert p.done and not b.moves


def test_native_quartz_event_source_fields_without_posting_to_desktop():
    if sys.platform != "darwin":
        pytest.skip("Quartz is macOS only")
    script = """
import ctypes as C
from oculo.macos_input import QuartzInput, Point
b=QuartzInput()
assert set(b.permissions()) == {"posting","listening"}
b.ax.AXIsProcessTrusted=lambda:True
b.cg.CGPreflightPostEventAccess=lambda:False
b.cg.CGPreflightListenEventAccess=lambda:True
assert b.ready()
assert "difiere" in b.permission_report()
b.pressed=lambda binding:False
b.position=lambda:(100.,200.)
b.cg.CGEventGetIntegerValueField.argtypes=[C.c_void_p,C.c_uint32]
b.cg.CGEventGetIntegerValueField.restype=C.c_int64
seen=[]
def capture(tap,event):
    point=b.cg.CGEventGetLocation(event)
    seen.append((tap,point.x,point.y,b.cg.CGEventGetIntegerValueField(event,4),
                 b.cg.CGEventGetIntegerValueField(event,5)))
b.cg.CGEventPost=capture
b.move(12,-3)
assert seen == [(0,112.,197.,12,-3)],seen
"""
    result=subprocess.run([sys.executable,"-c",script],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_permissions_request_post_and_listen_separately_and_use_session_state():
    from types import SimpleNamespace
    from oculo.macos_input import QuartzInput
    flags = {"posting":False,"listening":False}
    requests=[]
    polled=[]
    b=QuartzInput.__new__(QuartzInput)
    b.ax=SimpleNamespace(AXIsProcessTrusted=lambda:flags["posting"])
    b._prompt_accessibility=lambda:requests.append("accessibility")
    b.cg=SimpleNamespace(
        CGPreflightPostEventAccess=lambda:False,
        CGPreflightListenEventAccess=lambda:flags["listening"],
        CGRequestPostEventAccess=lambda:requests.append("posting"),
        CGRequestListenEventAccess=lambda:requests.append("listening"),
        CGEventSourceKeyState=lambda state,key:polled.append((state,key)) or True,
        CGEventSourceButtonState=lambda state,key:polled.append((state,key)) or True)
    assert not b.ready()
    assert "Accesibilidad" in b.permission_message()
    assert "Monitorización" in b.permission_message()
    assert not all(b.request_permissions().values())  # requesting is not consent
    assert requests == ["accessibility","listening"]
    flags["posting"]=True
    assert "Accesibilidad" not in b.permission_message()
    flags["listening"]=True
    assert b.ready()
    assert b.pressed("key:a") and b.pressed("mouse:right")
    assert polled == [(0,0),(0,1)]


def test_full_monitor_mode_selects_detections_far_outside_hidden_circle():
    from oculo.aim import AimEngine
    s=Settings(aim_limit_fov=False,aim_fov=10,aim_show_fov=False)
    e=AimEngine()
    dx,dy=e.step([box(900)],(0,0),1,s)
    assert dx > 0 and dy == 0
    assert e.target.point(.5) == (900,0)
    s.aim_limit_fov=True
    assert e.step([box(900)],(0,0),1.02,s) == (0,0)


def test_runtime_full_monitor_diagnostics_do_not_apply_radius_filter():
    r,b,s,t=setup_runtime(aim_fov=10,aim_limit_fov=False)
    r.submit([box(900)],(0,0),t[0],"screen")
    r.tick()
    assert r.diagnostics["stage"] == "posting"
    assert r.diagnostics["in_fov"] == 1
    assert b.moves


def test_quartz_preflight_alone_does_not_override_denied_accessibility():
    from types import SimpleNamespace
    from oculo.macos_input import QuartzInput
    b=QuartzInput.__new__(QuartzInput)
    b.ax=SimpleNamespace(AXIsProcessTrusted=lambda:False)
    b.cg=SimpleNamespace(CGPreflightPostEventAccess=lambda:True,
                         CGPreflightListenEventAccess=lambda:True)
    assert not b.ready()
    assert "esta copia" in b.permission_message()


def test_native_accessibility_request_builds_prompt_options_without_prompting():
    if sys.platform != "darwin":
        pytest.skip("AppKit is macOS only")
    script = """
import ctypes as C
from oculo.macos_input import QuartzInput
b=QuartzInput()
b.cf.CFDictionaryGetValue.argtypes=[C.c_void_p,C.c_void_p]
b.cf.CFDictionaryGetValue.restype=C.c_void_p
seen=[]
def capture(options):
    key=C.c_void_p.in_dll(b.ax,"kAXTrustedCheckOptionPrompt").value
    true=C.c_void_p.in_dll(b.cf,"kCFBooleanTrue").value
    assert b.cf.CFDictionaryGetValue(options,key)==true
    seen.append(True)
    return False
b.ax.AXIsProcessTrustedWithOptions=capture
b._prompt_accessibility()
assert seen==[True]
"""
    result=subprocess.run([sys.executable,"-c",script],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
