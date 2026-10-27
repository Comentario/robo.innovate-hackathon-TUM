# Brickflow · Unreal nativo

Proyecto: `Brickflow/Brickflow.uproject`, Unreal Engine **5.8.4**, Linux x86-64.
La simulación completa corre en C++20. La geometría JSON no contiene animaciones
ni un replay de Python/JavaScript. La referencia fijada es `greenfield_30`.

## Ejecutar

En Linux con GPU NVIDIA, Vulkan y un escritorio gráfico:

```bash
./Brickflow.sh -vulkan -ResX=1920 -ResY=1080 -Windowed
```

En la VM `brickflow-cinematic`, el build está en
`/home/shadeform/workspace/brickflow-native/Packaged/Linux/`.
El proyecto editable está en `/home/shadeform/workspace/brickflow-native/`.

El primer lote se calcula antes de habilitar los controles. Cambiar una receta
recalcula el lote determinista, conserva el tiempo visible y aplica la petición
en los límites de pallet de la planificación. `Restart batch` inicia un lote
nuevo con la receta seleccionada más recientemente.

- `Space`: reproducción/pausa; `S`: velocidad; `1`–`6`: capítulos.
- `E`: evidencia; botón derecho y arrastre: órbita; rueda: distancia.
- Barra temporal: buscar; `Queue recipe`: solicitar receta.
- Las tasas principales describen el lote completo; inspección y output muestran
  el estado en el instante visible. El panel Evidence explica la fórmula.

## Entregables locales

- `artifacts/unreal_native/brickflow-native-pitch.mp4`: tour 1080p, 24 segundos.
- `artifacts/unreal_native/brickflow-linux-native.tar.gz`: build Linux completo.
- `artifacts/unreal_native/mixed-chapter0.png`: vista general de Unreal.
- `artifacts/unreal_native/perception-native.png`: detalle de inspección.
- `artifacts/unreal_native/evidence-native.png`: panel de evidencia.
- `artifacts/unreal_native/*verification.json`: contrastes numéricos.

Extraer el build con `tar -xzf brickflow-linux-native.tar.gz` y ejecutar
`Linux/Brickflow.sh`. El ZIP de Unreal y las herramientas pesadas están en la
VM; el editor no es necesario para ejecutar el build empaquetado.

## Compilar y capturar en Brev

Los scripts `tools/*_cloud.sh` usan rutas explícitas de esa VM y se ejecutan con
`brev exec brickflow-cinematic @ruta/al/script.sh`. El orden de preparación es
instalar engine, preparar geometría, crear material en editor, compilar y
empaquetar. `prepare_geometry.py` requiere Playwright/Chromium, solo al preparar
assets; el ejecutable no los necesita.

`preview_cloud.sh` usa Vulkan sobre Xvfb con `-RenderOffscreen` para revisión
automatizada. Acepta modo, capítulo, tiempo y anchura; `-BrickflowPackaged`
selecciona el ejecutable independiente. Genera PNG y evidencia JSON con los
pallets completos, sus IDs y tiempos. `tests_native/compare_unreal.py` contrasta
esa evidencia con las cachés originales.

El modo `-BrickflowMovie=/ruta/nueva -BrickflowMovieFrames=576` produce un tour
de 24 segundos a 24 fps, un segundo simulado por frame (24×). Usar una carpeta
nueva para cada captura. `tools/encode_pitch_cloud.sh` convierte los PNG a MP4.
Es render offline; no constituye una medida de FPS interactivos.

## Alcance y evidencia

La escena reproduce inspección, rechazo, canales/reservas finitas, mezcla,
formación, apilado y despacho del modelo fijado. Conserva identidad de bricks.
Mixed y Single coinciden numéricamente con la referencia, incluidos los 78
pallets. Las poses también se contrastan contra el JavaScript original.

El input actual es sintético con semilla. No representa percepción independiente
de persona 1 ni capacidad industrial medida. Las recetas son heurísticas de la
demo y el movimiento es cinemático, sin validación física independiente.
`docs/unreal_native_goal.md` registra pruebas, límites y estado de entrega.

La VM se factura mientras permanece activa. No borrar la instancia antes de
comprobar los respaldos del build y del proyecto.
