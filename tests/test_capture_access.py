from types import SimpleNamespace
import sys

import numpy as np
import pytest

from oculo import screen_access
from oculo.capture import ScreenSource
from oculo.config import Settings


class Consent:
    def __init__(self, allowed=False, grant=False):
        self.allowed, self.grant, self.requests = allowed, grant, 0
    def CGPreflightScreenCaptureAccess(self):
        return self.allowed
    def CGRequestScreenCaptureAccess(self):
        self.requests += 1
        self.allowed = self.grant
        return self.grant


def test_screen_consent_preflight_does_not_prompt(monkeypatch):
    api = Consent()
    monkeypatch.setattr(screen_access.sys, "platform", "darwin")
    monkeypatch.setattr(screen_access, "_api", lambda:api)
    assert not screen_access.screen_capture_allowed()
    assert api.requests == 0
    assert not screen_access.screen_capture_allowed(request=True)
    assert api.requests == 1
    api.grant = True
    assert screen_access.screen_capture_allowed(request=True)
    assert api.requests == 2
    assert screen_access.screen_capture_allowed(request=True)
    assert api.requests == 2


def test_screen_source_refuses_wallpaper_only_without_consent(monkeypatch):
    monkeypatch.setattr(screen_access, "screen_capture_allowed", lambda **kw:False)
    with pytest.raises(PermissionError, match="otras aplicaciones"):
        ScreenSource()


def test_screen_capture_keeps_pixels_geometry_and_checks_revocation(monkeypatch):
    allowed = [True]
    monkeypatch.setattr(screen_access, "screen_capture_allowed", lambda **kw:allowed[0])
    class Capture:
        monitors = [{}, {"left":-1000,"top":0,"width":1000,"height":800}]
        closed = False
        def grab(self, region):
            self.region = region
            frame = np.zeros((region["height"]*2, region["width"]*2,4), np.uint8)
            frame[:,:,1] = 123  # distinguish actual app pixels from synthetic preview
            return frame
        def close(self):
            self.closed = True
    backend = Capture()
    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=lambda:backend))
    source = ScreenSource()
    frame = source.read(Settings(zone_width=200,zone_height=100,zone_offset_x=50,aim_limit_fov=True))
    assert frame.shape == (200,400,3)
    assert np.all(frame[:,:,1] == 123)
    assert source.geometry.crosshair == (-500,400)
    assert source.geometry.local_crosshair == (100,100)
    assert source.bounds == (-1000,0,1000,800)
    allowed[0] = False
    with pytest.raises(PermissionError):
        source.read(Settings())
    source.close()
    assert backend.closed


def test_full_monitor_capture_ignores_saved_center_crop(monkeypatch):
    monkeypatch.setattr(screen_access,"screen_capture_allowed",lambda **kw:True)
    class Capture:
        monitors=[{},dict(left=-1000,top=0,width=1000,height=800)]
        region=None
        def grab(self,region):
            self.region=region
            return np.zeros((region["height"],region["width"],4),np.uint8)
        def close(self):
            pass
    backend=Capture()
    monkeypatch.setitem(sys.modules,"mss",SimpleNamespace(mss=lambda:backend))
    source=ScreenSource()
    frame=source.read(Settings(zone_enabled=True,zone_width=200,zone_height=100,
                               zone_offset_x=500,aim_limit_fov=False))
    assert frame.shape==(800,1000,3)
    assert backend.region==dict(left=-1000,top=0,width=1000,height=800)
    assert source.geometry.local_crosshair==(500,400)
    source.close()
