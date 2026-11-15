from types import SimpleNamespace

import pytest

from oculo.config import Settings
from oculo.gfn_probe import GFNMovementProbe
from oculo.input_probe import MovementProbe
from oculo.macos_input import INPUT_METHODS, QuartzInput
from test_aim import FakeInput, box
from test_aim_diagnostics import setup_runtime


class Input(FakeInput):
    def __init__(self, method="quartz_hid"):
        super().__init__()
        self.method=method
    def position(self):
        return 100.,100.
    def permission_message(self):
        return "Falta Accesibilidad"


def test_gfn_probe_sends_only_bounded_steps_after_countdown_and_foreground_check():
    b,t=Input("relative_hid"),[0.]
    p=GFNMovementProbe(b,clock=lambda:t[0],foreground=lambda:True)
    assert "5 s" in p.tick() and not b.moves
    for moment in (5.,5.2,5.4,5.6):
        t[0]=moment
        status=p.tick()
    assert b.moves==[(8,0),(8,0),(-8,0),(-8,0)]
    assert sum(dx for dx,dy in b.moves)==0
    assert p.done and p.sent_steps==4
    assert "marca" in status
    p.tick()
    assert len(b.moves)==4


def test_gfn_probe_never_posts_when_client_is_not_foreground():
    b,t=Input(),[0.]
    p=GFNMovementProbe(b,clock=lambda:t[0],foreground=lambda:False)
    t[0]=6.
    assert "primer plano" in p.tick()
    assert p.done and not b.moves


@pytest.mark.parametrize("reason",["focus","panic","permissions","mouse"])
def test_gfn_probe_cancels_between_steps_without_queued_events(reason):
    b,t,front=Input(),[0.],[True]
    p=GFNMovementProbe(b,clock=lambda:t[0],foreground=lambda:front[0])
    t[0]=5.
    p.tick()
    if reason=="focus":front[0]=False
    elif reason=="panic":b.keys.add("key:f8")
    elif reason=="permissions":b.allowed=False
    else:b.keys.add("mouse:right")
    t[0]=5.2
    p.tick()
    assert p.done and len(b.moves)==1
    t[0]=10.
    p.tick()
    assert len(b.moves)==1


def test_relative_desktop_probe_does_not_claim_game_acceptance_or_permission_failure():
    b,t=Input("relative_hid"),[0.]
    b.moves_cursor=False
    p=MovementProbe(b,clock=lambda:t[0])
    t[0]=3.
    p.tick()
    t[0]=3.3
    status=p.tick()
    assert p.done and "GeForce NOW" in status
    assert "correcta" not in status and "Accesibilidad" not in status


def test_input_change_preserves_smoothing_and_clears_pending_control_history():
    r,b,s,t=setup_runtime(aim_mode="adaptive")
    b.set_method=lambda method:setattr(b,"method",method)
    r.submit([box(60)],(0,0),t[0],"screen")
    r.tick()
    assert r.diagnostics["posted"]==1
    s.aim_input_method="relative_session"
    r.configure(s)
    assert r.diagnostics["posted"]==0
    assert r._motion.carry==[0,0]
    r.tick()
    t[0]+=.02
    r.submit([box(60)],(0,0),t[0],"screen")
    r.tick()
    assert b.method=="relative_session"
    assert s.aim_mode=="adaptive"
    assert r.diagnostics["input_method"]=="relative_session"
    assert r.diagnostics["posted"]==1


def test_input_presets_default_compatibility_and_result_validation(tmp_path):
    assert Settings.from_dict({}).aim_input_method=="quartz_hid"
    s=Settings.from_dict({"aim_input_method":"relative_hid",
        "input_test_results":{"relative_hid":"ignored","bad":"accepted","quartz_session":"unknown"}})
    path=tmp_path/"settings.json"
    s.save(path)
    assert Settings.load(path).input_test_results=={"relative_hid":"ignored"}
    assert Settings.from_dict({"aim_input_method":[],"input_test_results":None}).aim_input_method=="quartz_hid"


def test_unknown_native_input_method_fails_explicitly():
    with pytest.raises(ValueError,match="desconocido"):
        QuartzInput("bad")
