"""Bounded, user-triggered test of a Quartz route inside native GeForce NOW.

Camera response is explicitly confirmed by the user. Cursor position or a
successful CGEventPost call cannot establish acceptance by a streamed game.
"""
import math
import time


def is_native_gfn_frontmost():
    # Read-only public AppKit API. Never activate or modify the NVIDIA client.
    import ctypes as C
    from .ui.native_window import native_call, _objc
    C.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    lib = _objc()
    lib.objc_getClass.argtypes = [C.c_char_p]
    lib.objc_getClass.restype = C.c_void_p
    pool = native_call(native_call(lib.objc_getClass(b"NSAutoreleasePool"), "alloc"), "init")
    try:
        workspace = native_call(lib.objc_getClass(b"NSWorkspace"), "sharedWorkspace")
        app = native_call(workspace, "frontmostApplication")
        identifier = native_call(app, "bundleIdentifier")
        raw = native_call(identifier, "UTF8String", C.c_char_p)
        bundle = raw.decode() if raw else ""
        return bundle.startswith("com.nvidia.gfnpc.")
    finally:
        native_call(pool, "drain", None)


class GFNMovementProbe:
    """Four 8-point steps, 150 ms apart, after a 5-second focus countdown."""
    pattern = (8, 8, -8, -8)

    def __init__(self, backend, emergency="key:f8", clock=time.monotonic,
                 foreground=is_native_gfn_frontmost):
        self.backend, self.emergency, self.clock = backend, emergency, clock
        self.foreground = foreground
        self.started = self.clock()
        self.last_sent = None
        self.sent_steps = 0
        self.done = False
        self.method = backend.method

    def cancel(self):
        self.done = True
        return "Prueba de GeForce NOW cancelada · sin más envíos"

    def tick(self):
        if self.done:
            return "Prueba terminada"
        if not self.backend.ready():
            self.done = True
            return self.backend.permission_message()
        if self.backend.pressed(self.emergency) or self.backend.pressed("key:f8"):
            return self.cancel()
        now = self.clock()
        remaining = 5-(now-self.started)
        if remaining > 0:
            return f"Prueba en {math.ceil(remaining)} s · entra en GeForce NOW y deja el ratón quieto"
        if not self.foreground():
            self.done = True
            return "Prueba cancelada · GeForce NOW nativo debe estar en primer plano"
        if any(self.backend.pressed("mouse:"+b) for b in ("left","right","middle","4","5")):
            self.done = True
            return "Prueba cancelada · suelta los botones del ratón y repite"
        if self.last_sent is not None and now-self.last_sent < .15:
            return "Probando la entrada en GeForce NOW · F8 cancela"
        self.backend.move(self.pattern[self.sent_steps], 0)
        self.sent_steps += 1
        self.last_sent = now
        if self.sent_steps == len(self.pattern):
            self.done = True
            return "Prueba enviada · comprueba la cámara y marca si se movió al volver a Oculo"
        return "Probando la entrada en GeForce NOW · F8 cancela"
