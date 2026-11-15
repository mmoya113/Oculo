# Carpeta de modelos

Copia aquí tus modelos en formato **`.onnx`** y pulsa **↻** en la app.
Puedes tener todos los que quieras; se eligen desde el desplegable «Modelo».

- En desarrollo (`python -m oculo`) se usa esta carpeta.
- En la app instalada la carpeta está en
  `~/Library/Application Support/Oculo/models` (botón «Carpeta de modelos»).

¿Tienes un `.pt` de Ultralytics? Conviértelo así:

```bash
pip install ultralytics
yolo export model=mi_modelo.pt format=onnx imgsz=640
```
