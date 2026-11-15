"""Latest-observation mailbox and independent 120 Hz activation/stop polling.

The detector cannot queue movement. A frame is consumed once, and a slow
inference never prevents emergency input from being polled. All OS calls
remain on this thread; stop/configure serialize against posting an event.
"""
from __future__ import annotations
import threading
import time

from .aim import AimEngine, options
from .macos_input import BINDINGS


class AimRuntime:
    def __init__(self, settings, backend_factory=None, clock=time.monotonic):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._settings = settings.copy()
        self._latest = None
        self._generation = 0
        self._consumed = 0
        self._engine = AimEngine()
        self._backend = None
        self._factory = backend_factory
        self._clock = clock
        self._latched = False
        self._active = False
        self._status = "Desactivado"
        self._thread = None

    @property
    def status(self):
        with self._lock:
            return self._status

    def configure(self, settings):
        with self._lock:
            if settings != self._settings:
                # Explicit off -> on rearms panic. Other changes never rearm it.
                if not self._settings.aim_enabled and settings.aim_enabled:
                    self._latched = False
                self._settings = settings.copy()
                self._latest = None
                self._engine.reset()
                self._active = False

    def submit(self, targets, crosshair, captured_at, context, settings=None):
        with self._lock:
            if settings is not None and settings != self._settings:
                return  # in-flight inference from an obsolete configuration
            if self._latest and self._latest[3] != context:
                self._engine.reset()
            self._generation += 1
            self._latest = (targets, crosshair, captured_at, context)

    def panic(self):
        with self._lock:
            self._latched = True
            self._engine.reset()
            self._latest = None
            self._active = False
            self._status = "PARADA · desactiva y reactiva Aim para rearmar"

    def start(self):
        self._thread = threading.Thread(target=self._run, name="Oculo-input", daemon=True)
        self._thread.start()

    def close(self):
        with self._lock:
            self._stop.set()
            self._latest = None
            self._engine.reset()
        if self._thread:
            self._thread.join(timeout=1)

    def tick(self):
        with self._lock:
            s = self._settings
            if self._stop.is_set():
                return
            if self._latched:
                self._status = "PARADA · desactiva y reactiva Aim para rearmar"
                return
            if not s.aim_enabled or s.source != "screen":
                self._engine.reset()
                self._active = False
                self._status = "Desactivado" if not s.aim_enabled else "Solo pantalla · vídeo/cámara sin movimiento"
                return
            if (s.aim_activation not in BINDINGS or s.aim_emergency not in BINDINGS
                    or s.aim_activation == s.aim_emergency):
                raise ValueError("Elige activación y parada válidas y diferentes.")
            if self._backend is None:
                if self._factory is None:
                    from .macos_input import QuartzInput
                    self._backend = QuartzInput()
                else:
                    self._backend = self._factory()
            if not self._backend.ready():
                self._engine.reset()
                self._active = False
                self._latest = None
                self._status = "Concede Accesibilidad y Monitorización de entrada en macOS"
                return
            if self._backend.pressed(s.aim_emergency):
                self.panic()
                return
            active = self._backend.pressed(s.aim_activation)
            if not active or not self._active:
                self._engine.reset()
                self._consumed = self._generation
            self._active = active
            self._status = "Activo" if active else "Preparado · mantén " + s.aim_activation
            if not active or self._latest is None or self._consumed == self._generation:
                return
            self._consumed = self._generation
            targets, crosshair, captured, _ = self._latest
            now = self._clock()
            if not 0 <= now-captured <= options(s)["stale_ms"]/1000:
                self._engine.reset()
                self._status = "Imagen caducada · sin movimiento"
                return
            dx, dy = self._engine.step(targets, crosshair, captured, s)
            if dx or dy:
                self._backend.move(dx, dy)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.panic()
                with self._lock:
                    self._status = f"PARADA · {exc}"
                # Keep the error until explicitly rearmed.
                while self._latched and not self._stop.wait(1/120):
                    pass
            self._stop.wait(1/120)
