"""Small Quartz adapter. Imported lazily; never installs a global event tap."""
from __future__ import annotations
import ctypes as C
import sys
from pathlib import Path
from dataclasses import dataclass

# Hardware keycodes (US physical positions); UI names make this explicit.
KEYS = dict(zip("asdfhgzxcvbqwerty", [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,16]))
KEYS.update(dict(zip("uiojklmn", [32,34,31,38,40,37,46,45])))
KEYS.update({"space":49, "shift":56, "control":59, "option":58,
             "command":55, "escape":53, "f6":97, "f7":98, "f8":100,
             "f9":101, "f10":109, "f11":103, "f12":111})
BINDINGS = ["mouse:right", "mouse:left", "mouse:middle", "mouse:4", "mouse:5"] + [
    "key:"+k for k in KEYS]


@dataclass(frozen=True)
class InputMethod:
    label: str
    tap: int
    relative_only: bool


INPUT_METHODS = {
    "quartz_hid": InputMethod("Entrada 1 · estándar", 0, False),
    "quartz_session": InputMethod("Entrada 2 · sesión", 1, False),
    "relative_hid": InputMethod("Entrada 3 · delta relativo", 0, True),
    "relative_session": InputMethod("Entrada 4 · delta de sesión", 1, True),
}


class Point(C.Structure):
    _fields_ = [("x", C.c_double), ("y", C.c_double)]


class QuartzInput:
    def __init__(self, method="quartz_hid"):
        self.set_method(method)
        if sys.platform != "darwin":
            raise RuntimeError("El control del ratón requiere macOS.")
        self.cg = C.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.ax = C.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        def bind(lib, name, result, *args):
            f = getattr(lib, name)
            f.restype, f.argtypes = result, list(args)
            return f
        for name in ("CGPreflightListenEventAccess", "CGRequestListenEventAccess",
                     "CGPreflightPostEventAccess", "CGRequestPostEventAccess"):
            bind(self.cg, name, C.c_bool)
        bind(self.ax, "AXIsProcessTrusted", C.c_bool)
        bind(self.ax, "AXIsProcessTrustedWithOptions", C.c_bool, C.c_void_p)
        bind(self.cf, "CFDictionaryCreateMutable", C.c_void_p,
             C.c_void_p, C.c_long, C.c_void_p, C.c_void_p)
        bind(self.cf, "CFDictionarySetValue", None, C.c_void_p, C.c_void_p, C.c_void_p)
        bind(self.cg, "CGEventSourceCreate", C.c_void_p, C.c_int)
        bind(self.cg, "CGEventSourceSetLocalEventsSuppressionInterval", None,
             C.c_void_p, C.c_double)
        bind(self.cg, "CGEventSourceSetLocalEventsFilterDuringSuppressionState", None,
             C.c_void_p, C.c_uint32, C.c_uint32)
        bind(self.cg, "CGEventSourceButtonState", C.c_bool, C.c_int, C.c_uint32)
        bind(self.cg, "CGEventSourceKeyState", C.c_bool, C.c_int, C.c_uint16)
        bind(self.cg, "CGEventCreate", C.c_void_p, C.c_void_p)
        bind(self.cg, "CGEventGetLocation", Point, C.c_void_p)
        bind(self.cg, "CGEventCreateMouseEvent", C.c_void_p, C.c_void_p,
             C.c_uint32, Point, C.c_uint32)
        bind(self.cg, "CGEventSetIntegerValueField", None, C.c_void_p, C.c_uint32, C.c_int64)
        bind(self.cg, "CGEventPost", None, C.c_uint32, C.c_void_p)
        bind(self.cf, "CFRelease", None, C.c_void_p)

    def set_method(self, method):
        if not isinstance(method, str) or method not in INPUT_METHODS:
            raise ValueError("Método de entrada desconocido: " + str(method))
        self.method = method

    @property
    def moves_cursor(self):
        return not INPUT_METHODS[self.method].relative_only

    def permissions(self):
        # Accessibility trust is the grant shown in System Settings. The Quartz
        # posting preflight is a separate diagnostic, not the Accessibility grant.
        return {"posting": bool(self.ax.AXIsProcessTrusted()),
                "listening": bool(self.cg.CGPreflightListenEventAccess())}

    def ready(self):
        return all(self.permissions().values())

    def permission_message(self):
        p = self.permissions()
        missing = []
        if not p["posting"]:
            missing.append("macOS no reconoce Accesibilidad para esta copia de Oculo. "
                           "Si el interruptor ya está encendido, elimina la entrada antigua "
                           "con − y vuelve a añadir la app que estás usando")
        if not p["listening"]:
            missing.append("macOS no reconoce Monitorización de entrada para leer activación y parada")
        return ". ".join(missing) if missing else "Accesibilidad y entrada reconocidas por macOS"

    def request_permissions(self):
        p = self.permissions()
        if not p["posting"]:
            self._prompt_accessibility()
        if not p["listening"]:
            self.cg.CGRequestListenEventAccess()
        return self.permissions()

    def _prompt_accessibility(self):
        key_callbacks = C.addressof(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks"))
        value_callbacks = C.addressof(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryValueCallBacks"))
        options = self.cf.CFDictionaryCreateMutable(None, 0, key_callbacks, value_callbacks)
        if not options:
            raise RuntimeError("No se pudo solicitar Accesibilidad.")
        try:
            key = C.c_void_p.in_dll(self.ax, "kAXTrustedCheckOptionPrompt").value
            true = C.c_void_p.in_dll(self.cf, "kCFBooleanTrue").value
            self.cf.CFDictionarySetValue(options, key, true)
            self.ax.AXIsProcessTrustedWithOptions(options)
        finally:
            self.cf.CFRelease(options)

    def permission_report(self):
        p = self.permissions()
        preflight = bool(self.cg.CGPreflightPostEventAccess())
        app = running_app_path()
        report = (f'Accesibilidad: {"reconocida" if p["posting"] else "no reconocida para esta copia"} · '
                  f'Entrada: {"reconocida" if p["listening"] else "no reconocida"}. '
                  f'App en uso: {app}.')
        if p["posting"] and not preflight:
            report += " La comprobación de envío de Quartz difiere; usa la prueba del cursor para verificar el resultado real."
        if not p["posting"]:
            report += " Si ya está activada, elimina Oculo de la lista con − y añade exactamente esta copia, después ciérrala y ábrela."
        if ".app" in app and not app.startswith("/Applications/"):
            report += " Instálala y ábrela desde Aplicaciones antes de autorizarla."
        return report

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
            # Preserve physical keyboard/mouse input while posting synthetic steps.
            self.cg.CGEventSourceSetLocalEventsSuppressionInterval(source, 0.)
            for state in (0, 1):
                self.cg.CGEventSourceSetLocalEventsFilterDuringSuppressionState(source, 7, state)
            method = INPUT_METHODS[self.method]
            destination = Point(x, y) if method.relative_only else Point(x+dx, y+dy)
            event = self.cg.CGEventCreateMouseEvent(source, kind, destination, button)
            if not event:
                raise RuntimeError("Quartz no pudo crear el movimiento.")
            try:
                self.cg.CGEventSetIntegerValueField(event, 4, dx)
                self.cg.CGEventSetIntegerValueField(event, 5, dy)
                self.cg.CGEventPost(method.tap, event)
            finally:
                self.cf.CFRelease(event)
        finally:
            self.cf.CFRelease(source)


def running_app_path():
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return str(parent)
    return str(executable)
