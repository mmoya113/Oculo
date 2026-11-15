# Oculo

App de escritorio para **macOS** que hace **detección de objetos en tiempo real** con modelos YOLO en formato ONNX. Captura la pantalla, un vídeo o la webcam, pasa cada imagen por el modelo y muestra las cajas, las estadísticas y los datos numéricos de cada detección.

Oculo **solo observa**: captura, detecta, dibuja y registra. No envía ningún evento de ratón ni de teclado, y no dibuja nada encima de otras ventanas.

## Qué hace

| Bloque | Opciones |
|---|---|
| **Modelo** | Selector entre todos los `.onnx` de la carpeta, confianza mínima, solape NMS (IoU), máximo de detecciones, filtro de clases |
| **Fuente** | Pantalla (con selector de monitor), archivo de vídeo (con bucle), webcam, límite de FPS |
| **Zona de detección** | Rectángulo centrado con ancho, alto y desplazamiento X/Y, más presets (320², 640², 1280×720) |
| **Visor** | Color de caja, un color por clase, estilo (esquinas o caja completa), grosor, etiquetas, confianza, punto central, coordenadas, estadísticas |
| **Datos** | Tabla en vivo con centro y tamaño de cada caja, y registro en CSV |
| **Presets** | Guardar y cargar toda la configuración como JSON |

## Instalación (app)

1. Descarga `Oculo.dmg` desde **Releases** (o desde el artifact del último workflow en la pestaña **Actions**).
2. Ábrelo y arrastra **Oculo** a **Aplicaciones**.
3. La app no está firmada con una cuenta de Apple Developer, así que la primera vez macOS la bloqueará. Abre **Ajustes del Sistema → Privacidad y seguridad** y pulsa **Abrir igualmente**, o ejecuta en Terminal:
   ```bash
   xattr -cr /Applications/Oculo.app
   ```
4. Al usar la fuente **Pantalla**, macOS pedirá permiso de **Grabación de pantalla**. Concédelo y reinicia la app. Sin ese permiso solo se ve el fondo de escritorio.

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

Hay dos hilos. El **hilo principal** lleva la interfaz; el **worker** hace el trabajo pesado. Se comunican así:

- Interfaz → worker: una copia del objeto `Settings`, protegida con un candado.
- Worker → interfaz: señales de Qt (`frame_ready`, `stats`, `error`, `model_loaded`).

### `oculo/config.py` — ajustes y rutas

Define la dataclass `Settings` con todos los ajustes de la app y las funciones que dicen dónde están `models/`, `logs/` y `settings.json`. Los ajustes se guardan como JSON, y `from_dict` ignora las claves que no conoce, así que un archivo antiguo nunca rompe la app.

Para **añadir una opción nueva**: añade un campo a `Settings`, crea su control en `main_window.py` con `_slider`/`_check`/`_spin`/`_combo`, y úsalo donde haga falta. Guardado, presets y sincronización salen gratis.

### `oculo/capture.py` — captura

Tres fuentes con el mismo contrato: `read(settings)` devuelve una imagen BGR de NumPy, o `None`.

- `ScreenSource` usa `mss` y captura **solo la zona de detección**, no la pantalla entera. Capturar 640×640 es mucho más rápido que una pantalla Retina completa.
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

Oculo no es un port de Aimmy. Comparte la parte de visión y deja fuera, a propósito, todo lo que actúa sobre el juego.

| | Aimmy | Oculo |
|---|---|---|
| Plataforma | Windows (C# / WPF) | macOS (Python / Qt) |
| Modelos | ONNX, YOLOv8 | ONNX, YOLOv8 / YOLO11 / end2end |
| Selector de modelos desde carpeta | Sí | Sí |
| Confianza mínima | Sí | Sí, más IoU, máximo de detecciones y filtro de clases |
| Zona de análisis | FOV centrado | Rectángulo con ancho, alto y desplazamiento |
| Fuentes | Pantalla | Pantalla, vídeo y webcam |
| Visualización | Overlay sobre el juego | Visor propio dentro de la app |
| Datos | — | Tabla en vivo y CSV |
| Presets de configuración | Sí | Sí (JSON) |
| Movimiento del ratón, suavizado, predicción, disparo automático | Sí | **No, y no se añadirá** |

## Ideas para seguir aprendiendo

- Grabar el visor a un archivo de vídeo con `cv2.VideoWriter`.
- Un mapa de calor con las posiciones de las detecciones de un vídeo entero.
- Seguimiento de objetos entre imágenes (asignar un ID a cada caja con IoU).
- Entrenar un modelo propio con Ultralytics y tus propias imágenes.
