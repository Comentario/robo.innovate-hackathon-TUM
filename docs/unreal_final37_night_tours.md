# Recorridos nocturnos de la versión final 37

La referencia declarada final por el propietario es `greenfield_37`, SHA-256
`3aa2ec3d3828a691e7020f4deca4dc86d093b69da1569b57c73865352a03f7c5`.
Se conserva una copia fijada; una modificación posterior del HTML no cambia esta cola.

## Qué reproduce Unreal

El exportador offline extrae el calendario preparado de la referencia y su geometría.
Un reproductor C++20 evalúa sus 57.901 registros y 4.374.724 segmentos en Unreal.
No ejecuta Python ni JavaScript para mover la planta durante el render. Esto es
**reproducción nativa del calendario fuente**, no una implementación independiente
nueva del planificador de producción. El planificador nativo anterior sigue separado.
No se modifican grupos, puntuaciones, clasificación, decisiones o trayectorias.

La auditoría compara 15.454 poses/visibilidades calculadas por el demo con C++:
error máximo observado cero en las muestras. Es correspondencia de software;
no demuestra validación física independiente. Los paneles de servicio que ocultan
inspección y routing se muestran mediante el cutaway definido por la propia fuente.
Los componentes conservan su geometría, incluido el segundo sensor instalado;
solo se superpone **un** video real de detección.

## Dirección de cámara y montaje

Diez rutas, 3840 × 2160, 30 fps; copias de evaluación 1920 × 1080.
Duraciones aproximadas 539–599 segundos; se quitó el límite de un minuto.
Cada ruta conserva el ladrillo `38371` del **segundo** kiln cart, pallet `wood-46`,
orden `truck-2-1`, desde la llegada del cart hasta la salida en camión.
Al inicio ya hay 23 pallets almacenados. El timelapse final procesa otros 5.076
ladrillos inspeccionados del calendario fuente.

El recorrido incluye dehacking, extracción de fila de perfil, subbelt, inspección,
routing, formación de capas, pallet completo, puente, inventario, AMR, horquillas
extensibles y carga lateral. Cambia altura, ángulo, velocidad de esperas y sentido
del giro final entre alternativas. Los cambios de encuadre usan curvas suaves;
la posición del ladrillo se evalúa en el reloj continuo de la fuente, sin saltos.
Las aceleraciones y desaceleraciones también son continuas.

No hay dashboard. La única indicación agregada es `TIMELAPSE ×N`, calculada del
factor de tiempo en cada instante, incluida la rampa. Se oculta a velocidad normal.

El clip físico de Franka se alinea editorialmente con agarre y transferencia.
Una breve retención solo acompaña la comparación del manipulador. La grabación
real del clasificador conserva sus 319 frames y anotaciones originales; durante
esa superposición la simulación **avanza siempre a 1×**, sin pausa. Los IDs reales
y sintéticos no están emparejados y el montaje no acredita sincronización física
calibrada. Ambos clips se incluyen en **cada** recorrido, con bordes suaves y fundidos.

## Servicios y recuperación

VM propia: `brickflow-cinematic-4gpu`. No se usa la VM de Jacob.

- Proyecto aislado: `~/workspace/brickflow-final37-native`.
- Assets, planes, estado y películas: `~/workspace/brickflow-final37-night`.
- Servicio cloud: `brickflow-final37-night.service`, habilitado al arranque.
- Servicio de entrega WSL: `brickflow-final37-delivery.service`, habilitado para el usuario.
- Galería Windows: `D:\Hackathon\Munich Hackathon 2026\Videos_Unreal\Final37_Night_Tours\index.html`.

El servicio espera gates de exportación, hash, compilación y preflight. Cuatro
trabajadores independientes fijan explícitamente adaptador Vulkan y GPU NVENC.
Cada trabajador conserva una GPU durante un recorrido. El render se verifica
por tramos de 1.800 frames: ante un fallo se reintenta hasta tres veces el tramo;
un reinicio del servicio reutiliza resultados comprobados. Un watchdog detecta
capturas detenidas. Los procesos pertenecen al grupo del servicio para no dejar
encoders huérfanos.

Después de completar todos los tramos de una ruta, el servicio compone las dos
fuentes reales y el indicador de velocidad. Comprueba resolución, decodificación,
frames, cadencia PTS/DTS y hashes. Solo entonces publica `delivery.json`. Los MP4
finales, JSON y trazas permanecen; los chunks de video reproducibles de esa ruta
se eliminan **después** de verificar la película, para conservar espacio cloud.
Los renders y revisiones anteriores no se modifican.

La entrega local consulta periódicamente el estado cloud, descarga archivos con
reanudación, verifica SHA-256 y copia al disco D mediante Windows. Si Windows/WSL
está suspendido, el render cloud continúa y la copia se reanuda al regresar WSL.
La galería solo publica enlaces de reproducción cuando la entrega está verificada;
no se recarga mientras un video se reproduce.

Se detuvieron exclusivamente los dos visores propios antiguos que ocupaban GPU 0.
Sus argumentos quedan en `stopped-viewers.json`; los proyectos y servicios de acceso
se conservan. No se detiene automáticamente la VM al concluir, porque también es
el entorno de trabajo interactivo del propietario.

## Operación

```bash
ssh -o BatchMode=yes brickflow-cinematic-4gpu \
  'cat ~/workspace/brickflow-final37-night/status.json'
ssh -o BatchMode=yes brickflow-cinematic-4gpu \
  'sudo -n systemctl status --no-pager brickflow-final37-night.service'
ssh -o BatchMode=yes brickflow-cinematic-4gpu \
  'tail -60 ~/workspace/brickflow-final37-night/Logs/service.log'
```

En WSL:

```bash
systemctl --user status brickflow-final37-delivery.service
```

`status.json` informa trabajadores, etapa, último frame, tramos terminados,
recorridos listos y errores. `preflight.json` conserva los gates de aprobación
editorial/técnica. Una máquina o un proveedor pueden fallar: persistencia significa
reintentos y recuperación, no una garantía de disponibilidad del hardware.

## Verificaciones reproducibles

```bash
python3 tests_native/check_night_tour_plan.py \
  artifacts/unreal_night37/3aa2ec3d/facts.json
python3 -m py_compile unreal/tools/{export_source_replay,plan_night_tours,night_tours_worker,composite_night_tour,deliver_night_tours}.py
```

La auditoría C++ `tests_native/check_source_replay.cpp` se compila con
`unreal/Brickflow/Source/Brickflow/Core/SourceReplay.cpp` y recibe `replay.bin` y
`pose-samples.csv`. El preflight también captura los puntos críticos, verifica
60 frames de streaming 4K y un montaje técnico de 900 frames con ambos feeds.
Ese montaje técnico reutiliza deliberadamente el clip de prueba; **no** se publica
como recorrido. Las películas finales se generan de sus trazas completas.

`unreal/tools/verify_night_composite.py` ofrece una comprobación adicional sobre
los MP4 codificados: compara el interior de cada overlay con frames del video
real original y comprueba la continuidad de **todas** las trazas de captura,
incluidos los límites entre chunks. En el ensayo técnico se observaron errores
RGB medios de 1,90/255 para Franka y 1,42/255 para detección tras compresión.
Esta prueba verifica inclusión editorial, no correspondencia física entre IDs.

El servicio cloud `brickflow-final37-quality.service` ejecuta esa auditoría de
píxeles y de traza real automáticamente, conforme aparece cada `delivery.json`.
Guarda un resultado por recorrido en `Quality/tour-NN.json` y el resumen en
`quality-status.json`. Comprueba además el SHA-256 del master contra su manifiesto.
El objetivo de entrega se cierra solo tras revisar estos resultados junto con
los archivos efectivamente copiados al disco D. Este servicio es independiente
de la captura; instalarlo no reinicia los procesos de render activos.

Tras revisar una unión real entre los frames 1.799 y 1.800, se comprobó continuidad
visual y temporal (avance de 1/30 s nativo en ese punto). La revisión reveló que
la placa de agarre oculta parte de la capa desde la vista elevada. Se conserva
esa vista en los recorridos 1–4; en los recorridos 5–10, aún sin capturar al cambiar
sus planes, se prueban vistas de dehacking más bajas o intermedias. Una captura
nativa independiente confirma mayor visibilidad de la capa bajo el cabezal.
Las seis trazas nuevas se vuelven a auditar. No se cambian movimientos, tiempos,
superposiciones ni encuadres de transferencia/inspección. Los planes originales
quedan preservados en `Tours/original-camera` de la VM.

El recorrido 10 incorpora además un contraste real del calendario: después de
la inspección del ladrillo principal `38371`, sigue temporalmente al ladrillo
`37578`, ya marcado como rechazado por la referencia final. Sus eventos exactos
se conservan en `unreal/editorial/final37-inspection-contrast.json`; no se cambia
ningún grupo, puntuación, resultado o trayectoria. El rechazo llega 9,675 s
nativos después del paso inicial del principal por inspección. La cámara muestra
el empuje, la bajada por la faja opaca y la llegada al contenedor desde un ángulo
superior, antes de recuperar suavemente al principal. La fuente real del
clasificador aparece durante esta sección y la simulación permanece a 1× hasta
terminar el descenso y el fundido. Esto sigue siendo una comparación editorial
entre grabación física y referencia sintética, sin emparejar sus IDs.

Las otras nueve cámaras conservan sus planes al incorporar este contraste.
El recorrido 10 actualizado dura 566,41 s (16.993 frames a 30 fps); su traza completa
se volvió a auditar y una captura de Unreal confirmó la visibilidad del rechazo.
