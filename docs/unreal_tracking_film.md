# Vídeo nativo de seguimiento · revisión greenfield_30

Petición vigente: sin límite de duración. Se descartó el límite provisional de
un minuto. No hay dashboard, rótulos, métricas ni especificaciones sobre el vídeo.
La simulación nativa sigue fijada a `greenfield_30`, aunque la planta WebGL esté
siendo corregida de forma independiente. No incorporar esos cambios concurrentes
ni presentarlos como implementados en esta iteración.

## Realización

- Vuelta completa de cámara de 360° alrededor de la planta.
- Seguimiento del brick aceptado **9568**, desde la carga del layer hasta su
  pallet de salida, consultando `Simulation::pose` en cada fotograma.
- Extracción de la fila completa a 1×, desde la elevación hasta la colocación en
  el subbelt. Plano sostenido de cinco segundos para insertar el vídeo Franka.
- Llegada a inspección y vista de cámara/lente/iluminación. Se congela el reloj
  nativo siete segundos mientras gira la cámara, dejando un segundo punto de
  inserción para el vídeo real del algoritmo.
- El brick **9567**, inmediatamente posterior en el mismo flujo, está rechazado
  en el lote original. Se muestra su empuje y descenso por el descarte, y se
  recupera el seguimiento del 9568 a su posición nativa en ese mismo instante.
- Formación, buffers, apilado y traslado del pallet hasta su carro. Alejamiento
  final. El brick puede quedar físicamente oculto dentro de su pallet; no se
  inventa una vista a través del producto ni se altera la posición para verlo.

Todos los movimientos mostrados transcurren a **1×**, con muestreo a 30 fps.
Las pausas de cámara mantienen toda la planta congelada. Las esperas largas por
acumulación se acortan mediante cortes entre intervalos de tiempo; no mediante
aceleración de los mecanismos. `edit-plan.json` y `trace.csv` hacen auditables
esos cortes y las poses. Los vídeos físicos los aporta el equipo y no se generan
ni se incorporan sin sus archivos. Los puntos de inserción solo figuran en el
plan de edición, no sobre la imagen.

La cámara no certifica percepción: los estados de aceptación/rechazo son los del
input sintético original. Comparar el algoritmo real con la simulación requiere
el vídeo y la evidencia de percepción correspondientes.

## Corrección del descarte

La exportación original omitió `THREE.DoubleSide`. Los 54 paneles finos de las
seis fajas de descarte perdían una cara en Unreal, aunque su opacidad fuera 1.
Se restaura `doubleSided` en esos materiales y se usa un material opaco separado
`M_FactorySurfaceTwoSided`, sin cambiar posiciones, geometría ni física del lote.
El exportador conserva ahora esa propiedad para futuras exportaciones.

## Captura y verificación

`FactoryFilm.cpp` genera el plan desde los eventos C++ del lote y obtiene las
poses de los dos IDs seleccionados. Las trayectorias del producto no se editan.
`tests_native/verify_film.py` contrasta cada pose registrada contra los dos
records de la referencia original y comprueba velocidad 1× y pausas.

El render permite capturas PNG de prueba o salida BGRA nativa por TCP loopback a
FFmpeg/NVENC. El master usa H.264 4:4:4 con modo lossless y no pasa por noVNC,
JPEG ni grabación de escritorio. El muestreo del archivo es independiente de lo
que tarde la GPU en renderizar cada fotograma. Se esperan varios frames de
estabilización temporal por imagen antes de capturar.

`unreal/tools/render_film_cloud.sh` recibe una etiqueta nueva, anchura, stride
(1 para master; mayor solo para pruebas) y `png`/`stream`. Los resultados quedan
en `Saved/Films/<etiqueta>/` en la VM. Nunca entregar un stride de prueba como
si fuera vídeo a velocidad real.

## Checkpoint de render

- Corrección del descarte verificada visualmente y guardada en `a4b8550`.
- Proyecto sin `FactoryPresentation`, velocidad interactiva inicial 1×.
- Editor y build Game Linux compilados y empaquetados con éxito.
- Probes de cámara en `artifacts/unreal_film/probe-clean-v1` y `probe-clean-v2`;
  se contrastaron 166 poses contra la referencia, error máximo < 1e-12 m.
- Prueba de captura directa 4K por loopback con H.264 High 4:4:4 Predictive,
  `yuvj444p`; copia de revisión H.264 High `yuv420p`. La conversión de color a
  YUV precede a la compresión lossless del master.
- Render completo: `Saved/Films/tracking-4k-v5-part0` a `part3` en la VM.
  Rangos `[0,1800)`, `[1800,3600)`, `[3600,5400)`, `[5400,7198)`.
  Todos calculan el mismo plan y usan 8 frames de estabilización por imagen,
  con estabilización adicional al cambiar de plano o saltar una espera.
- Ensamblado: `assemble_film_cloud.sh tracking-4k-v5`, sin recodificar los
  tramos. Produce 7,198 frames, 239.933 s a 30 fps, y puntos de inserción JSON.
  La verificación final debe comprobar la continuidad de todos los frames,
  giro de 360°, pausas del reloj y poses antes de declarar la entrega completa.
