"""User-triggered, single 12-point desktop motion probe; no detector required."""
import math
import time


class MovementProbe:
    def __init__(self, backend, emergency="key:f8", clock=time.monotonic):
        self.backend, self.emergency, self.clock = backend, emergency, clock
        self.started = self.clock()
        self.sent_at = None
        self.before = None
        self.done = False

    def cancel(self):
        self.done = True
        return "Prueba cancelada · no se enviarán más movimientos"

    def tick(self):
        if self.done:
            return "Prueba terminada"
        if not self.backend.ready():
            self.done = True
            return self.backend.permission_message()
        if self.backend.pressed(self.emergency) or self.backend.pressed("key:f8"):
            return self.cancel()
        now = self.clock()
        if self.sent_at is None:
            remaining = 3-(now-self.started)
            if remaining > 0:
                return f"Prueba en {math.ceil(remaining)} s · suelta botones y no muevas el ratón"
            if any(self.backend.pressed("mouse:"+b) for b in ("left","right","middle","4","5")):
                self.done = True
                return "Prueba cancelada · suelta todos los botones del ratón y repite"
            self.before = self.backend.position()
            self.backend.move(12, 0)
            self.sent_at = now
            return "Paso de prueba enviado · comprobando el cursor"
        if now-self.sent_at < .15:
            return "Comprobando el movimiento del cursor"
        self.done = True
        after = self.backend.position()
        dx, dy = after[0]-self.before[0], after[1]-self.before[1]
        if abs(dx-12) <= 3 and abs(dy) <= 3:
            return "Prueba correcta · macOS movió el cursor. Activa Aim para probar la detección."
        if math.hypot(dx,dy) < 1:
            return "No se observó movimiento · coloca el cursor lejos del borde; si Accesibilidad ya está activada, elimina la entrada antigua con − y vuelve a añadir la app instalada"
        return "Prueba no concluyente · deja el ratón quieto y repite"
