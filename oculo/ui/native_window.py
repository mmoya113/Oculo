"""Minimal AppKit bridge for a passive overlay on every macOS Space."""
from __future__ import annotations
import ctypes as C
from functools import lru_cache
import sys
from PySide6.QtGui import QGuiApplication

# NSWindowCollectionBehavior: CanJoinAllSpaces, Stationary, IgnoresCycle,
# FullScreenAuxiliary. No moveToActiveSpace (mutually exclusive with AllSpaces).
OVERLAY_BEHAVIOR = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)


@lru_cache(maxsize=1)
def _objc():
    lib = C.CDLL("/usr/lib/libobjc.A.dylib")
    lib.sel_registerName.argtypes = [C.c_char_p]
    lib.sel_registerName.restype = C.c_void_p
    return lib


def native_call(receiver, selector, result=C.c_void_p, argtype=None, value=None):
    lib = _objc()
    # Separate typed function pointers avoid changing a shared objc_msgSend ABI.
    args = [C.c_void_p, C.c_void_p] + ([] if argtype is None else [argtype])
    fn = C.CFUNCTYPE(result, *args)(("objc_msgSend", lib))
    values = [receiver, lib.sel_registerName(selector.encode())]
    if argtype is not None:
        values.append(value)
    return fn(*values)


def overlay_window(widget):
    if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
        return None
    return native_call(int(widget.winId()), "window")


def configure_overlay(widget):
    window = overlay_window(widget)
    if not window:
        return
    for selector, kind, value in (
        ("setCollectionBehavior:", C.c_ulong, OVERLAY_BEHAVIOR),
        ("setLevel:", C.c_long, 25),  # NSStatusWindowLevel, above regular windows
        ("setIgnoresMouseEvents:", C.c_bool, True),
        ("setHidesOnDeactivate:", C.c_bool, False),
        ("setHasShadow:", C.c_bool, False),
        ("setSharingType:", C.c_ulong, 0),  # omit from legacy CGWindow capture
    ):
        native_call(window, selector, None, kind, value)
