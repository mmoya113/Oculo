"""Small Quartz adapter. Imported lazily; never installs a global event tap."""
from __future__ import annotations
import ctypes as C
import sys

# Hardware keycodes (US physical positions); UI names make this explicit.
KEYS = dict(zip("asdfhgzxcvbqwerty", [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,16]))
KEYS.update(dict(zip("uiojklmn", [32,34,31,38,40,37,46,45])))
KEYS.update({"space":49, "shift":56, "control":59, "option":58,
             "command":55, "escape":53, "f6":97, "f7":98, "f8":100,
             "f9":101, "f10":109, "f11":103, "f12":111})
BINDINGS = ["mouse:right", "mouse:left", "mouse:middle", "mouse:4", "mouse:5"] + [
    "key:"+k for k in KEYS]


class Point(C.Structure):
    _fields_ = [("x", C.c_double), ("y", C.c_double)]


class QuartzInput:
    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("El control del ratón requiere macOS.")
        self.cg = C.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.ax = C.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        def bind(lib, name, result, *args):
            f = getattr(lib, name)
            f.restype, f.argtypes = result, list(args)
            return f
        bind(self.ax, "AXIsProcessTrusted", C.c_bool)
        bind(self.cg, "CGPreflightListenEventAccess", C.c_bool)
        bind(self.cg, "CGEventSourceButtonState", C.c_bool, C.c_int, C.c_uint32)
        bind(self.cg, "CGEventSourceKeyState", C.c_bool, C.c_int, C.c_uint16)
        bind(self.cg, "CGEventCreate", C.c_void_p, C.c_void_p)
        bind(self.cg, "CGEventGetLocation", Point, C.c_void_p)
        bind(self.cg, "CGEventCreateMouseEvent", C.c_void_p, C.c_void_p,
             C.c_uint32, Point, C.c_uint32)
        bind(self.cg, "CGEventSetDoubleValueField", None, C.c_void_p, C.c_uint32, C.c_double)
        bind(self.cg, "CGEventPost", None, C.c_uint32, C.c_void_p)
        bind(self.cf, "CFRelease", None, C.c_void_p)

    def ready(self):
        return self.ax.AXIsProcessTrusted() and self.cg.CGPreflightListenEventAccess()

    def pressed(self, binding):
        kind, _, name = binding.partition(":")
        if kind == "mouse":
            button = {"left":0, "right":1, "middle":2, "4":3, "5":4}.get(name)
            return button is not None and self.cg.CGEventSourceButtonState(1, button)
        return name in KEYS and self.cg.CGEventSourceKeyState(1, KEYS[name])

    def move(self, dx, dy):
        event = self.cg.CGEventCreate(None)
        if not event:
            raise RuntimeError("Quartz no pudo leer la posición del cursor.")
        try:
            position = self.cg.CGEventGetLocation(event)
        finally:
            self.cf.CFRelease(event)
        # Relative deltas plus a relative cursor destination. Never warp to target.
        right, left = self.pressed("mouse:right"), self.pressed("mouse:left")
        kind, button = (6, 0) if left else ((7, 1) if right else (5, 0))
        event = self.cg.CGEventCreateMouseEvent(None, kind,
                                               Point(position.x+dx, position.y+dy), button)
        if not event:
            raise RuntimeError("Quartz no pudo crear el movimiento.")
        try:
            self.cg.CGEventSetDoubleValueField(event, 4, dx)  # mouseEventDeltaX
            self.cg.CGEventSetDoubleValueField(event, 5, dy)  # mouseEventDeltaY
            self.cg.CGEventPost(0, event)  # kCGHIDEventTap
        finally:
            self.cf.CFRelease(event)
