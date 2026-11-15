"""macOS screen-recording consent. No capture or permission prompts at import."""
from __future__ import annotations
import ctypes
from functools import lru_cache
import sys

PERMISSION_HELP = (
    "macOS no permite capturar otras aplicaciones. Activa Oculo en Ajustes del Sistema → "
    "Privacidad y seguridad → Grabación de pantalla (o Grabación de pantalla y audio del sistema). "
    "Después cierra y vuelve a abrir Oculo desde Aplicaciones. Si ya aparece activado tras "
    "instalar una versión nueva, desactívalo y actívalo otra vez."
)


@lru_cache(maxsize=1)
def _api():
    api = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    for name in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"):
        fn = getattr(api, name)
        fn.argtypes = []
        fn.restype = ctypes.c_bool
    return api


def screen_capture_allowed(request=False):
    if sys.platform != "darwin":
        return True
    api = _api()
    if api.CGPreflightScreenCaptureAccess():
        return True
    if request:
        api.CGRequestScreenCaptureAccess()
        # Some macOS releases require relaunch even after accepting the dialog.
        return bool(api.CGPreflightScreenCaptureAccess())
    return False


def require_screen_capture():
    if not screen_capture_allowed():
        raise PermissionError(PERMISSION_HELP)
