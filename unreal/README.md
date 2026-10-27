# Brickflow · Unreal nativo

Proyecto: `Brickflow/Brickflow.uproject`, Unreal Engine **5.8.4**, Linux x86-64.
La simulación completa corre en C++20. La geometría JSON no contiene animaciones
ni un replay de Python/JavaScript. La referencia fijada es `greenfield_30`.

## Ejecutar

### Evaluar desde el navegador de este equipo

Acceso interactivo por escritorio remoto noVNC sobre túnel SSH:
`http://localhost:6080/vnc.html?autoconnect=1&resize=scale&view_only=0&path=websockify`.
La GPU y Unreal permanecen en Brev. El navegador transmite imagen e inputs;
el motor sigue siendo el ejecutable nativo. No es un enlace público y solo
funciona en el equipo donde se abre el túnel.

Para restablecerlo desde WSL si el túnel se cierra:

```bash
/tmp/brickflow-brev-bin/brev exec brickflow-cinematic @unreal/tools/start_interactive_cloud.sh
/tmp/brickflow-brev-bin/brev port-forward brickflow-cinematic -p 6080:6080
```

El escritorio usa Xvfb `:81`, x11vnc en loopback `5901` y websockify/noVNC en
loopback `6080`. Los PID y logs están en `Saved/Interactive/` en la VM. Las
dependencias de esta VM son `xvfb x11vnc novnc websockify openbox x11-utils`.
Se verificó la conexión WebSocket en Chromium y el cambio de cámara mediante
clics enviados desde el navegador. Se usa transmisión de escritorio para
evaluación; no se ha medido latencia ni calidad de streaming para un pitch.

### Ejecutable Linux

En Linux con GPU NVIDIA, Vulkan y un escritorio gráfico:

```bash
./Brickflow.sh -vulkan -ResX=1920 -ResY=1080 -Windowed
```

En la VM `brickflow-cinematic`, el build está en
`/home/shadeform/workspace/brickflow-native/Packaged/Linux/`.
El proyecto editable está en `/home/shadeform/workspace/brickflow-native/`.

La versión actual no crea UI ni dashboard. Arranca a 1×; `Space` reproduce o
pausa. Botón derecho y arrastre orbitan y la rueda cambia la distancia. Las
teclas `1`–`6` conservan encuadres de evaluación. Las métricas siguen disponibles
en la evidencia JSON, pero no se dibujan sobre la planta.

El vídeo de seguimiento usa `-BrickflowFilm=/ruta/nueva` y calcula su cámara a
partir de los eventos y poses nativos. Ver `docs/unreal_tracking_film.md` para los
puntos de inserción de vídeos físicos, cortes de espera y verificación.

## Entregables locales de la versión anterior (con UI)

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

El tour anterior de 24 segundos se conserva como histórico. El render vigente
se genera con `tools/render_film_cloud.sh`: 30 fps, movimientos nativos a 1×,
sin UI y con master NVENC lossless. El stride debe ser 1 para el vídeo final;
los strides mayores solo sirven para revisar encuadres.

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
