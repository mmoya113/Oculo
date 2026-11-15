# Oculo

App de escritorio para **macOS** que hace **detección de objetos en tiempo real** con modelos YOLO en formato ONNX. Captura la pantalla, un vídeo o la webcam, pasa cada imagen por el modelo y muestra las cajas, las estadísticas y los datos numéricos de cada detección.

Oculo captura, detecta, dibuja y registra. El **Aim assist opcional**, desactivado por defecto, envía movimientos relativos de ratón solo con la fuente Pantalla y mientras mantienes la activación. Las cajas se muestran en el visor; el FOV y la mira opcionales se superponen sobre el monitor elegido.

## Qué hace

| Bloque | Opciones |
|---|---|
| **Modelo** | Selector entre todos los `.onnx` de la carpeta, confianza mínima, solape NMS (IoU), máximo de detecciones, filtro de clases |
| **Fuente** | Pantalla (con selector de monitor), archivo de vídeo (con bucle), webcam, límite de FPS |
| **Zona de detección** | Rectángulo centrado con ancho, alto y desplazamiento X/Y, más presets (320², 640², 1280×720) |
| **Visor** | Color de caja, un color por clase, estilo (esquinas o caja completa), grosor, etiquetas, confianza, punto central, coordenadas, estadísticas |
| **Datos** | Tabla en vivo con centro y tamaño de cada caja, y registro en CSV |
| **Presets** | Guardar y cargar toda la configuración como JSON |
| **Pantalla completa** | Tecla `F` (o el botón de la cabecera): el visor ocupa toda la pantalla. `Esc` para salir |

## Instalación (app)

1. Descarga `Oculo.dmg` desde **Releases** (o desde el artifact del último workflow en la pestaña **Actions**).
2. Ábrelo y arrastra **Oculo** a **Aplicaciones**.
3. La app no está firmada con una cuenta de Apple Developer, así que la primera vez macOS la bloqueará. Abre **Ajustes del Sistema → Privacidad y seguridad** y pulsa **Abrir igualmente**, o ejecuta en Terminal:
   ```bash
   xattr -cr /Applications/Oculo.app
   ```
4. Al usar la fuente **Pantalla**, macOS pedirá permiso de **Grabación de pantalla**. Concédelo y reinicia la app. Si falta ese permiso, Oculo muestra un aviso y no inicia una captura limitada al escritorio. Si instalas una versión nueva y solo ves el fondo, desactiva y reactiva el permiso de Oculo, cierra la app y ábrela desde Aplicaciones.

> El build es para Apple Silicon (arm64). Cada versión nueva cuenta como una app distinta para macOS, así que puede volver a pedirte el permiso de pantalla.

## Modelos

Pulsa **Carpeta de modelos** en la app, copia ahí tus `.onnx` y pulsa **↻**.

- App instalada: `~/Library/Application Support/Oculo/models`
- En desarrollo: la carpeta `models/` de este repo

Formatos de salida soportados: **YOLOv8 / YOLO11** `(1, 4 + clases, N)` y modelos **end2end** `(1, N, 6)` (YOLOv10 o exportados con `nms=True`). El formato antiguo de YOLOv5 (con columna de «objectness») no está soportado.

Para convertir un `.pt` de Ultralytics:

```bash
pip install ultralytics
yolo export model=mi_modelo.pt format=onnx imgsz=640
```

Para una primera prueba sirve el modelo genérico `yolov8n` (80 clases de COCO: personas, coches, etc.) exportado con ese mismo comando.

## Desarrollo

```bash
git clone https://github.com/mmoya113/oculo.git
cd oculo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m oculo          # arrancar la app
python -m pytest         # tests
```

Construir el `.app` y el `.dmg` en local (en un Mac):

```bash
python scripts/make_icon.py
iconutil -c icns build/Oculo.iconset -o build/Oculo.icns
pyinstaller Oculo.spec --noconfirm
hdiutil create -volname Oculo -srcfolder dist/Oculo.app -ov -format UDZO dist/Oculo.dmg
```

### Releases automáticas

El workflow `.github/workflows/build.yml` construye el `.dmg` en cada push a `main` y lo deja como artifact. Para publicar una Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Arquitectura

```
                    ┌──────────────────────── worker.py (QThread) ────────────────────────┐
                    │                                                                     │
  Pantalla ─┐       │   capture.py        inference.py         overlay.py                 │
  Vídeo ────┼──────▶│   imagen BGR  ───▶  detecciones   ───▶   imagen dibujada  ──señal──▶│──▶ ui/main_window.py
  Webcam ───┘       │                          │                                          │      (visor + tabla)
                    │                          └──────────▶   datalog.py  ──▶  CSV        │
                    └─────────────────────────────▲───────────────────────────────────────┘
                                                  │ copia de Settings en cada cambio
                                            ui/main_window.py (controles)
```

Hay tres hilos: la entrada se comprueba aparte a 120 Hz para que una inferencia lenta no impida la parada global. El **hilo principal** lleva la interfaz; el **worker** hace el trabajo pesado. Se comunican así:

- Interfaz → worker: una copia del objeto `Settings`, protegida con un candado.
- Worker → interfaz: señales de Qt (`frame_ready`, `stats`, `error`, `model_loaded`).

### `oculo/config.py` — ajustes y rutas

Define la dataclass `Settings` con todos los ajustes de la app y las funciones que dicen dónde están `models/`, `logs/` y `settings.json`. Los ajustes se guardan como JSON, y `from_dict` ignora las claves que no conoce, así que un archivo antiguo nunca rompe la app.

Para **añadir una opción nueva**: añade un campo a `Settings`, crea su control en `main_window.py` con `_slider`/`_check`/`_spin`/`_combo`, y úsalo donde haga falta. Guardado, presets y sincronización salen gratis.

### `oculo/capture.py` — captura

Tres fuentes con el mismo contrato: `read(settings)` devuelve una imagen BGR de NumPy, o `None`.

- `ScreenSource` usa `mss` y captura todo el monitor por defecto. Si activas el límite FOV, puedes usar la zona recortada para reducir el coste de captura. Vídeo y webcam conservan sus controles de recorte.
- `VideoSource` y `CameraSource` usan `cv2.VideoCapture` y recortan la zona después de leer.
- `zone_rect()` calcula el rectángulo centrado y lo mantiene dentro de la imagen.

Para **añadir otra fuente**, escribe una clase con `read()` y `close()` y añádela a `open_source()`.

### `oculo/inference.py` — el modelo

El módulo clave. Usa ONNX Runtime directamente, sin Ultralytics ni PyTorch, para que se vea cada paso:

1. **`letterbox()`** — escala la imagen al tamaño del modelo sin deformarla, rellenando con gris. Devuelve la escala y el relleno para poder deshacerlo después.
2. **`Detector.preprocess()`** — BGR→RGB, de `(alto, ancho, 3)` a `(1, 3, alto, ancho)`, valores de 0 a 1.
3. **`session.run()`** — ejecuta la red. En Mac intenta primero CoreML (GPU / Neural Engine) y cae a CPU si el modelo no es compatible. El chip «Motor» de la app muestra cuál se usa.
4. **`decode()`** — interpreta la salida cruda. En YOLOv8 son miles de candidatos `[cx, cy, ancho, alto, puntuaciones…]`: se queda con la mejor clase de cada uno, filtra por confianza y convierte a esquinas.
5. **`nms()`** — elimina las cajas duplicadas del mismo objeto usando IoU.
6. **`Detector.detect()`** — deshace el letterbox y devuelve objetos `Detection` en píxeles de la imagen original.

Cada `Detection` tiene `x1, y1, x2, y2, confidence, class_id, class_name` y las propiedades calculadas `cx`, `cy`, `width`, `height`.

### `oculo/overlay.py` — dibujo

`render()` convierte el array en `QImage` y pinta con `QPainter`: cajas (completas o solo esquinas), etiqueta, punto central, coordenadas y estadísticas. Se dibuja sobre una copia de la imagen que solo se muestra en el visor de la app.

### `oculo/datalog.py` — datos numéricos

Con «Guardar detecciones en un CSV» activado, cada detección es una fila en `logs/detecciones_FECHA.csv`:

| Columna | Significado |
|---|---|
| `time_s`, `frame` | Momento y número de imagen |
| `model`, `class_id`, `class_name`, `confidence` | Qué se detectó y con qué seguridad |
| `x1, y1, x2, y2` | Esquinas de la caja |
| `cx, cy` | **Centro de la caja** |
| `w, h` | Tamaño |
| `cx_norm, cy_norm` | Centro de 0 a 1, independiente de la resolución |

Las coordenadas están en píxeles de la **imagen analizada** (la zona), con el origen arriba a la izquierda y la Y creciendo hacia abajo. Ejemplo para explorarlo:

```python
import pandas as pd
df = pd.read_csv("logs/detecciones_....csv")
print(df.groupby("class_name")["confidence"].describe())
df.plot.scatter(x="cx", y="cy")     # dónde aparecen los objetos
```

### `oculo/worker.py` — el bucle

`DetectionWorker.run()` es el bucle principal, numerado en el código del 1 al 8: recargar modelo si cambió, reabrir fuente si cambió, capturar, inferir, registrar, calcular FPS, dibujar y emitir, y respetar el límite de FPS.

### `oculo/ui/` — interfaz

- `main_window.py` — la ventana. Cada control se crea con una fábrica que lo enlaza en los dos sentidos con un campo de `Settings`.
- `theme.py` — paleta, tipografía (San Francisco, la fuente del sistema en macOS) y hoja de estilos QSS.
- `branding.py` — el logo, dibujado por código; de ahí salen el icono de la ventana y el `.icns`.

## Comparación con Aimmy

Oculo implementa un motor original de Aim assist inspirado en las funciones solicitadas de Aimmy.

| | Aimmy | Oculo |
|---|---|---|
| Plataforma | Windows (C# / WPF) | macOS (Python / Qt) |
| Modelos | ONNX, YOLOv8 | ONNX, YOLOv8 / YOLO11 / end2end |
| Selector de modelos desde carpeta | Sí | Sí |
| Confianza mínima | Sí | Sí, más IoU, máximo de detecciones y filtro de clases |
| Zona de análisis | FOV centrado | Rectángulo con ancho, alto y desplazamiento |
| Fuentes | Pantalla | Pantalla, vídeo y webcam |
| Visualización | Overlay sobre el juego | Visor de detecciones y FOV opcional sobre el escritorio |
| Datos | — | Tabla en vivo y CSV |
| Presets de configuración | Sí | Sí (JSON) |
| Movimiento del ratón, suavizado, predicción | Sí | Sí, opcional con activación mantenida |
| Disparo automático | Sí | No |

## Ideas para seguir aprendiendo

- Grabar el visor a un archivo de vídeo con `cv2.VideoWriter`.
- Un mapa de calor con las posiciones de las detecciones de un vídeo entero.
- Seguimiento de objetos entre imágenes (asignar un ID a cada caja con IoU).
- Entrenar un modelo propio con Ultralytics y tus propias imágenes.


## Aim assist y nueva interfaz

La interfaz separa **Aim**, **Detección** y **Visor / datos**, con estado del control siempre visible. En macOS, Qt 6.9+ expande el contenido bajo la barra de título transparente y conserva los controles nativos de cerrar, minimizar y pantalla completa. Se fuerza la apariencia oscura del sistema para evitar la franja blanca. El DMG actual requiere **macOS 14+ y Apple Silicon** (dependencias actuales de Qt/ONNX).

1. Añade tu modelo ONNX y selecciona **Pantalla**, monitor y zona. La mira se considera en el centro del monitor seleccionado; usa el juego a pantalla completa, centrado. No se detecta automáticamente una ventana de juego ni su sensibilidad.
2. En **Ajustes del Sistema → Privacidad y seguridad**, concede **Grabación de pantalla**, **Accesibilidad** y **Monitorización de entrada** a Oculo; reinícialo si macOS lo pide. Oculo muestra el permiso que falta sin intentar eludirlo.
3. Pulsa **Iniciar**, habilita **Aim assist** y mantén **clic derecho**. Se pueden elegir otros botones o teclas físicas US. **F8** (posiblemente Fn+F8) detiene globalmente el Aim y queda bloqueado hasta deshabilitarlo y habilitarlo otra vez. **Parada Aim** funciona desde la cabecera. La parada no genera clics ni libera botones que tú mantienes.
4. Empieza con Exponential, respuesta 180 ms, EMA 0.65, predicción 0, paso 8, velocidad 400 y ganancia 1. El FOV es un **radio en puntos macOS**, independiente de Retina; 180 puntos equivalen a 360 píxeles con escala 2x.
5. Ajusta la ganancia visual X/Y: si un punto enviado desplaza el objetivo unos dos puntos en sentido contrario, usa ganancia 2. Un valor demasiado bajo puede provocar sobrecorrecciones con la sensibilidad del juego. Aumenta respuesta y reduce paso/velocidad si hay latencia.

### Selección y movimiento

Se elige el punto de la caja más cercano a la mira. Por defecto se consideran todas las detecciones del monitor; el FOV circular solo restringe la selección si activas explícitamente su límite. El punto vertical va de 0 (arriba) a 1 (abajo). El seguimiento sticky asocia por clase, distancia y solape; conserva identidad durante el plazo de retención, **sin mover cuando no hay detección**. Dos objetos de la misma clase que se cruzan pueden intercambiar identidad: no hay un modelo de reidentificación.

Cada imagen produce como máximo un paso relativo, sin colas de trayectorias ni posiciones absolutas del objetivo. Para dt (máximo 1/30 s), tau = respuesta en segundos y t = min(1, dt/tau):

- **Linear:** fracción = t.
- **Bezier:** fracción = 3t² − 2t³, curva cúbica con controles 0 y 1; se aplica al paso de realimentación, no a una trayectoria aleatoria.
- **Exponential:** fracción = 1 − exp(−dt/tau).
- **Adaptive:** fracción = 1 − exp(−dt/tau × (1 + 2 min(1, distancia/FOV))).

La EMA del error usa alpha = 1 − (1 − peso)^(dt×60), se reinicia al invertir dirección y se limita al error observado. La predicción opcional usa la variación del error en pantalla / dt, con horizonte y desplazamiento máximos. El movimiento final se limita por eje al error actual menos zona muerta, se divide por la ganancia y se limita en longitud por paso máximo y velocidad×dt. Cambiar objetivo, modelo, monitor, recorte, ajustes o activación reinicia el historial. No se envían pasos de imágenes caducadas, repetidas o fuera de orden. Los presets antiguos siguen siendo compatibles.

### Retina, GeForce NOW y límites de validación

Las cajas de inferencia se convierten usando el tamaño real de la captura dividido por el tamaño lógico de la región; X e Y se convierten por separado y se conservan los orígenes negativos de monitores secundarios. La mira permanece en el centro **del monitor**, aunque el recorte esté desplazado. Se publican eventos Quartz con deltas relativos y destino relativo al cursor actual; no se coloca el cursor sobre coordenadas de las cajas.

GeForce NOW y otros juegos pueden ignorar eventos Quartz, usar entrada raw/cursor bloqueado, sensibilidad no lineal o añadir retraso de red. No hay garantía de compatibilidad ni de ausencia de oscilación en un juego real: los límites matemáticos corresponden a la medición actual y a la ganancia configurada. Las cajas por sí solas no separan movimiento de cámara y objetivo; la predicción se deja en 0 por defecto. No se implementan bypasses de entrada o de protecciones del juego. Vídeo y webcam nunca controlan el ratón.

Las pruebas usan un backend falso: convergencia de bucle cerrado, inversión de movimiento, límites, pérdida de objetivo, coordenadas Retina/monitores, presets, caducidad, permisos, activación y parada. La CI además prueba el arranque del .app empaquetado; la respuesta real de GeForce NOW necesita una prueba manual en tu equipo con permisos y modelo.

### Descargar una compilación de una PR

Abre la PR → **Checks** → **Build macOS** → **Details**. Cuando la ejecución esté verde, abre su resumen y baja **Artifacts → Oculo-dmg** (requiere sesión de GitHub). Descomprime el ZIP, abre `Oculo.dmg` y arrastra Oculo a Aplicaciones. Las compilaciones de PR no crean una Release; el workflow también se ejecuta al integrar en main y permite ejecución manual.

Referencias de implementación: [área de título de Qt](https://www.qt.io/blog/expanded-client-areas-and-safe-areas-in-qt-6.9), [eventos de ratón Quartz](https://developer.apple.com/documentation/coregraphics/cgevent/init(mouseeventsource:mousetype:mousecursorposition:mousebutton:)), [captura macOS de MSS](https://github.com/BoboTiG/python-mss/blob/main/src/mss/darwin.py). El motor es una implementación original inspirada en las funciones solicitadas de Aimmy; no pretende ser un port literal de su algoritmo V2.


## Correcciones 1.0.1: captura, arrastre y FOV de escritorio

- **Mover la ventana:** arrastra una zona vacía de la cabecera o el nombre/logo de Oculo. Se conserva la barra oscura integrada y los controles nativos. Doble clic sobre la cabecera maximiza/restaura; los botones siguen funcionando.
- **Captura de otras apps:** Oculo comprueba el permiso real con `CGPreflightScreenCaptureAccess` antes de abrir MSS y antes de cada captura. Si falta o se revoca, detiene la captura/control en vez de mostrar solo el fondo y la propia app. El aviso incluye un botón para solicitar acceso y otro para abrir los permisos de macOS. La app no puede concederse este permiso por sí sola.
- **Después de reemplazar una versión:** instala en `/Applications/Oculo.app`, cierra la versión anterior y abre la nueva desde Aplicaciones. En Privacidad y seguridad → Grabación de pantalla (o Grabación de pantalla y audio del sistema), desactiva y reactiva Oculo si ya figuraba activado; después ciérralo y ábrelo otra vez. Si la entrada anterior sigue sin servir, elimínala con el botón menos de macOS y vuelve a añadir la app instalada. Los builds ad hoc sin certificado estable pueden necesitar renovar este permiso tras una actualización.
- **FOV opcional:** la opción «Mostrar FOV y mira sobre otras apps» crea una ventana transparente independiente en el monitor capturado. Está centrada en el monitor, no en el recorte ni en el visor, no recibe foco/clics y usa `canJoinAllSpaces` + `fullScreenAuxiliary` para acompañar los escritorios y ventanas a pantalla completa. Se oculta al detener, desactivar Aim, usar vídeo/webcam, cerrar Oculo o activar la parada. No se dibuja dentro de la imagen del visor; con captura MSS/Quartz la ventana se marca no compartible para evitar recapturar el FOV. Las restricciones de algunas apps/pantallas protegidas pueden impedir superposiciones.

Validación manual pendiente en el equipo del usuario: conceder el permiso al DMG instalado, colocar Chrome delante de la zona capturada y cambiar de escritorio con tres dedos. Las pruebas automáticas cubren denegación/revocación del permiso, fidelidad de píxeles y geometría, arrastre y botones, separación del FOV del visor y comportamiento pasivo de la superposición. La CI prueba además el arranque del .app empaquetado.


## 1.0.2: ayuda, configuración inicial y diagnóstico de movimiento

En la pestaña **Aim**, cada opción tiene un **?** con una explicación al pasar el ratón. Los ajustes de calibración/latencia están ocultos bajo «Mostrar ajustes avanzados» para empezar con menos controles.

Pulsa **Cargar configuración inicial** para aplicar Exponential, respuesta 180 ms, EMA 0,65, sin límite de FOV, círculo oculto, zona muerta 2, paso máximo 8, velocidad 400, predicción 0 y caducidad 200 ms. Conserva tu modelo, fuente, detección, colores y registro. Deja Aim desactivado para que tú lo habilites cuando estés listo. Es una base conservadora para probar, no una garantía de compatibilidad o calibración de tu juego. Los ajustes ya guardados no se reemplazan automáticamente al actualizar.

### Si hay cajas pero el ratón no se mueve

1. **Autorizar control del ratón** solicita los permisos específicos de macOS: Accesibilidad para publicar movimiento y Monitorización de entrada para leer la activación/parada. Grabación de pantalla solo permite ver las apps, no mover el ratón. Hay accesos directos a ambas secciones de Ajustes.
2. Pulsa **Probar movimiento del ratón (3 s)**, suelta los botones y deja el cursor quieto, lejos del borde. Esta prueba desactiva Aim y manda **un único paso de 12 puntos a la derecha**, sin modelo ni tecla de Aim, y después comprueba si cambió la posición del cursor. F8, la parada configurada, Parada Aim, Detener o cerrar Oculo cancelan los pasos pendientes. La prueba puede no ser concluyente si mueves el ratón o estás en un juego con cursor bloqueado; úsala en el escritorio.
3. Si la prueba mueve el cursor, pulsa Iniciar, habilita Aim y mantén la activación. La franja muestra el motivo real: esperando tecla, sin detecciones, fuera del FOV, retención del objetivo, suficientemente centrado, imagen caducada o envío de movimiento. También muestra tecla detectada, objetivos dentro del FOV, edad de imagen, descartes por retraso y número de envíos.
4. Una imagen que tarda más que el límite de caducidad se descarta. Antes el límite era 100 ms y el aviso desaparecía en el siguiente sondeo de entrada, por lo que podía verse «Activo» aunque nunca se enviase un movimiento. Ahora el aviso permanece visible; el nuevo perfil inicial usa 200 ms. Reduce la zona/modelo si llega tarde; aumentar mucho el límite empeora la respuesta y puede desestabilizar un juego.
5. Los pasos inferiores a un punto se acumulan hasta poder enviar un delta entero. Se reinician al soltar, parar, invertir dirección o perder la medición, y se limitan al error actual/paso máximo. Evita que el redondeo de los deltas Quartz deje siempre en cero las correcciones pequeñas. Se usa el estado/fuente de la sesión actual y deltas enteros de Quartz.

En el escritorio el cursor puede moverse sin que la caja detectada cambie de posición: mover el cursor no mueve el contenido de una ventana. En un juego el movimiento relativo controla la cámara, según su sensibilidad y soporte de entrada. «Enviando movimiento» confirma que Oculo llamó a Quartz; no confirma que un juego aceptase el evento. La prueba de escritorio sí comprueba el desplazamiento observado del cursor.

Referencias: [estado de eventos de sesión de Apple](https://developer.apple.com/documentation/coregraphics/cgeventsourcestateid), [deltas enteros de ratón](https://developer.apple.com/documentation/coregraphics/cgeventfield/mouseeventdeltax), [solicitud de acceso a entrada](https://developer.apple.com/documentation/coregraphics/cgrequestlisteneventaccess()).



## 1.0.3: pantalla completa sin límite FOV y Accesibilidad de la copia actual

- **Sin límite por defecto:** se consideran todas las detecciones válidas del monitor seleccionado. La captura de pantalla usa el monitor completo aunque un preset antiguo guardase un recorte 640×640. «Limitar búsqueda al círculo FOV» permite volver al límite/recorte de forma explícita. Las fuentes vídeo/webcam mantienen su recorte.
- **Círculo oculto al arrancar:** el FOV visual y la mira opcional empiezan ocultos incluso si antes se guardaron visibles. Mostrar el círculo no activa ningún límite. Aim mantiene su activación por tecla/botón y su parada de emergencia.
- **Comprobación correcta:** el permiso de Accesibilidad se consulta con `AXIsProcessTrusted` y se solicita con `AXIsProcessTrustedWithOptions` y la opción de mostrar el aviso nativo. El preflight de publicación de Quartz se conserva como diagnóstico separado: un resultado diferente no se presenta como si el interruptor de Accesibilidad estuviese apagado, ni bloquea por sí solo una copia reconocida por Accessibility. Monitorización de entrada sigue siendo necesaria para leer la activación/parada. La prueba del cursor verifica el resultado observado; consultar permisos no demuestra por sí solo que se haya movido.
- **Recomprobar permisos y copia de Oculo:** muestra la ruta de la app que se está usando, el reconocimiento de Accesibilidad/entrada y si difiere la comprobación de Quartz. No cambia ni reinicia permisos del sistema. Permite distinguir la copia instalada de una ejecutada desde un DMG u otra carpeta.

Si el interruptor de Oculo aparece encendido pero macOS no reconoce la copia actual:

1. Instala la versión final en `/Applications/Oculo.app`, cierra todas las copias de Oculo con ⌘Q y abre la de Aplicaciones.
2. En Privacidad y seguridad → Accesibilidad, **selecciona la entrada antigua de Oculo y elimínala con −**, en lugar de alternar repetidamente su interruptor.
3. Pulsa **+** y añade exactamente `/Applications/Oculo.app`; actívala y vuelve a abrir Oculo.
4. Usa «Recomprobar permisos y copia de Oculo» y «Probar movimiento del ratón (3 s)». Si el sistema indica que falta Monitorización de entrada, renueva también la entrada de esa misma copia allí.

Las compilaciones actuales usan firma ad hoc. Su requisito de firma puede identificar el hash de cada ejecutable; reemplazar el build puede dejar una entrada visible asociada a una copia anterior. La app no puede concederse permisos, modificar la base de permisos ni garantizar que macOS conserve la autorización al actualizar. Una identidad Developer ID estable requiere un certificado del propietario, no incluido en este repositorio.

Las pruebas adicionales cubren objetivos fuera del círculo con límite apagado, captura completa ignorando recortes antiguos, arranque con el círculo oculto y la discrepancia entre AX y el preflight de Quartz. El ensayo nativo construye la solicitud de Accesibilidad sin mostrar avisos ni conceder permisos, e intercepta los eventos antes de publicarlos.
