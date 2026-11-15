"""One fresh observation per step, independent activation and panic polling."""
from __future__ import annotations
import math
import threading
import time

from .aim import AimEngine, MotionAccumulator, options
from .macos_input import BINDINGS


class AimRuntime:
    def __init__(self, settings, backend_factory=None, clock=time.monotonic):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._settings = settings.copy()
        self._latest = None
        self._generation = self._consumed = 0
        self._engine = AimEngine()
        self._motion = MotionAccumulator()
        self._backend = None
        self._factory = backend_factory
        self._clock = clock
        self._latched = self._active = False
        self._status = "Desactivado"
        self._thread = None
        self._info = dict(stage="disabled", activation=False, detections=0, in_fov=0,
                          samples=0, stale=0, posted=0, age_ms=None, delta=(0,0))

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def diagnostics(self):
        with self._lock:
            result = dict(self._info)
            result["status"] = self._status
            return result

    def _result(self, stage, status):
        self._info["stage"] = stage
        self._status = status

    def _reset(self):
        self._engine.reset()
        self._motion.reset()

    def configure(self, settings):
        with self._lock:
            if settings != self._settings:
                if not self._settings.aim_enabled and settings.aim_enabled:
                    self._latched = False
                self._settings = settings.copy()
                self._latest = None
                self._reset()
                self._active = False
                self._info.update(activation=False, detections=0, in_fov=0, age_ms=None)

    def submit(self, targets, crosshair, captured_at, context, settings=None):
        with self._lock:
            if settings is not None and settings != self._settings:
                return
            if self._latest and self._latest[3] != context:
                self._reset()
            self._generation += 1
            self._latest = (targets, crosshair, captured_at, context)

    def panic(self):
        with self._lock:
            self._latched = True
            self._reset()
            self._latest = None
            self._active = False
            self._info["activation"] = False
            self._result("panic", "PARADA · desactiva y reactiva Aim para rearmar")

    def start(self):
        self._thread = threading.Thread(target=self._run, name="Oculo-input", daemon=True)
        self._thread.start()

    def close(self):
        with self._lock:
            self._stop.set()
            self._latest = None
            self._reset()
        if self._thread:
            self._thread.join(timeout=1)

    def tick(self):
        with self._lock:
            s = self._settings
            if self._stop.is_set() or self._latched:
                return
            if not s.aim_enabled or s.source != "screen":
                self._reset()
                self._active = False
                self._info["activation"] = False
                self._result("disabled", "Desactivado" if not s.aim_enabled else
                             "Solo pantalla · vídeo/cámara sin movimiento")
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
                self._reset()
                self._active = False
                self._info["activation"] = False
                self._latest = None
                reason = (self._backend.permission_message() if
                          hasattr(self._backend, "permission_message") else
                          "Concede Accesibilidad y Monitorización de entrada en macOS")
                self._result("permission", reason)
                return
            if self._backend.pressed(s.aim_emergency):
                self.panic()
                return
            active = self._backend.pressed(s.aim_activation)
            self._info["activation"] = active
            if not active or not self._active:
                self._reset()
                self._consumed = self._generation
                self._result("waiting_frame" if active else "waiting_activation",
                             "Tecla detectada · esperando imagen nueva" if active else
                             "Preparado · mantén " + s.aim_activation)
            self._active = active
            if self._latest is not None:
                self._info["age_ms"] = (self._clock()-self._latest[2])*1000
            if not active or self._latest is None:
                return
            targets, crosshair, captured, _ = self._latest
            age = self._clock()-captured
            p = options(s)
            if self._consumed == self._generation:
                # Keep the last rejection reason visible between polls.
                if age > p["stale_ms"]/1000 and self._info["stage"] != "stale":
                    self._reset()
                    self._result("stale", "Sin imagen reciente · esperando detección nueva")
                return
            self._consumed = self._generation
            self._info["samples"] += 1
            self._info["detections"] = len(targets)
            candidates = [t for t in targets if t.valid() and math.dist(
                t.point(p["point_y"]), crosshair) <= p["fov"]]
            self._info["in_fov"] = len(candidates)
            if not 0 <= age <= p["stale_ms"]/1000:
                self._reset()
                self._info["stale"] += 1
                self._result("stale", f"Imagen caducada: {age*1000:.0f} ms > "
                             f"{s.aim_stale_ms} ms · reduce la zona/modelo o revisa caducidad")
                return
            dx, dy = self._engine.step(targets, crosshair, captured, s)
            target = self._engine.target
            if not targets or not candidates or target is None or not (dx or dy):
                self._motion.reset()
                if not targets:
                    self._result("no_detection", "Tecla detectada · no hay detecciones")
                elif not candidates:
                    self._result("outside_fov", "Tecla detectada · las detecciones están fuera del FOV")
                elif target is None or self._engine.previous_error is None:
                    self._result("sticky_wait", "Objetivo perdido · esperando recuperar o cambiar objetivo")
                else:
                    self._result("deadzone", "Objetivo dentro de la zona muerta · no hace falta mover")
                return
            point = target.point(p["point_y"])
            limits = [max(0., abs(point[i]-crosshair[i])-p["deadzone"])/
                      p["gain_x" if i == 0 else "gain_y"] for i in range(2)]
            if max(limits) < 1:
                self._motion.reset()
                self._result("deadzone", "Objetivo suficientemente centrado · sin movimiento")
                return
            mx, my = self._motion.step((dx,dy), limits, p["max_step"])
            self._info["delta"] = (mx,my)
            if mx or my:
                self._backend.move(mx, my)
                self._info["posted"] += 1
                self._result("posting", f"Enviando movimiento · X {mx:+d}, Y {my:+d}")
            else:
                self._result("subpixel", "Objetivo detectado · acumulando un paso pequeño")

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.panic()
                with self._lock:
                    self._result("error", f"PARADA · {exc}")
                while self._latched and not self._stop.wait(1/120):
                    pass
            self._stop.wait(1/120)
