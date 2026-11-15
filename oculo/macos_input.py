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
        def bind(lib, name, result, *args):
            f = getattr(lib, name)
            f.restype, f.argtypes = result, list(args)
            return f
        for name in ("CGPreflightListenEventAccess", "CGRequestListenEventAccess",
                     "CGPreflightPostEventAccess", "CGRequestPostEventAccess"):
            bind(self.cg, name, C.c_bool)
        bind(self.cg, "CGEventSourceCreate", C.c_void_p, C.c_int)
        bind(self.cg, "CGEventSourceButtonState", C.c_bool, C.c_int, C.c_uint32)
        bind(self.cg, "CGEventSourceKeyState", C.c_bool, C.c_int, C.c_uint16)
        bind(self.cg, "CGEventCreate", C.c_void_p, C.c_void_p)
        bind(self.cg, "CGEventGetLocation", Point, C.c_void_p)
        bind(self.cg, "CGEventCreateMouseEvent", C.c_void_p, C.c_void_p,
             C.c_uint32, Point, C.c_uint32)
        bind(self.cg, "CGEventSetIntegerValueField", None, C.c_void_p, C.c_uint32, C.c_int64)
        bind(self.cg, "CGEventPost", None, C.c_uint32, C.c_void_p)
        bind(self.cf, "CFRelease", None, C.c_void_p)

    def permissions(self):
        return {"posting": bool(self.cg.CGPreflightPostEventAccess()),
                "listening": bool(self.cg.CGPreflightListenEventAccess())}

    def ready(self):
        return all(self.permissions().values())

    def permission_message(self):
        p = self.permissions()
        missing = []
        if not p["posting"]:
            missing.append("Accesibilidad para mover el ratón")
        if not p["listening"]:
            missing.append("Monitorización de entrada para leer activación y parada")
        return "Falta " + " y ".join(missing) if missing else "Permisos de ratón concedidos"

    def request_permissions(self):
        p = self.permissions()
        if not p["posting"]:
            self.cg.CGRequestPostEventAccess()
        if not p["listening"]:
            self.cg.CGRequestListenEventAccess()
        return self.permissions()

    def position(self):
        event = self.cg.CGEventCreate(None)
        if not event:
            raise RuntimeError("Quartz no pudo leer la posición del cursor.")
        try:
            point = self.cg.CGEventGetLocation(event)
            return point.x, point.y
        finally:
            self.cf.CFRelease(event)

    def pressed(self, binding):
        kind, _, name = binding.partition(":")
        if kind == "mouse":
            button = {"left":0, "right":1, "middle":2, "4":3, "5":4}.get(name)
            return button is not None and self.cg.CGEventSourceButtonState(0, button)
        return name in KEYS and self.cg.CGEventSourceKeyState(0, KEYS[name])

    def move(self, dx, dy):
        if not self.ready():
            raise PermissionError(self.permission_message())
        if int(dx) != dx or int(dy) != dy:
            raise ValueError("El movimiento de Quartz requiere pasos enteros acumulados.")
        x, y = self.position()
        right, left = self.pressed("mouse:right"), self.pressed("mouse:left")
        kind, button = (6, 0) if left else ((7, 1) if right else (5, 0))
        # Current session source, as recommended for a user-session application.
        source = self.cg.CGEventSourceCreate(0)
        if not source:
            raise RuntimeError("Quartz no pudo crear la fuente de entrada.")
        try:
            event = self.cg.CGEventCreateMouseEvent(source, kind, Point(x+dx, y+dy), button)
            if not event:
                raise RuntimeError("Quartz no pudo crear el movimiento.")
            try:
                self.cg.CGEventSetIntegerValueField(event, 4, dx)
                self.cg.CGEventSetIntegerValueField(event, 5, dy)
                self.cg.CGEventPost(0, event)
            finally:
                self.cf.CFRelease(event)
        finally:
            self.cf.CFRelease(source)
