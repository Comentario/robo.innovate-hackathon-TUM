# Revisión de iluminación para presentación

Fecha: 28 de octubre de 2026. Se revisó el MP4 4K entregado de la simulación
nativa greenfield_30, de 395,567 s. **El diagnóstico corresponde a ese render;
las correcciones propuestas todavía no se han aplicado ni renderizado.**
No se generó una película nueva ni se modificó la simulación activa.

Se extrajeron del vídeo existente 16 fotogramas: 0, 36, 93, 100,5, 120, 130,5,
140, 155, 220, 260, 291, 310, 330, 345, 370 y 390 segundos. Se inspeccionaron
las muestras, incluidas las dos pausas para insertar vídeos físicos y la salida
del pallet. Es una revisión por muestras, no una inspección de todos los frames.

Material de evaluación local:

- [Panel ilustrado de ocho zonas](../artifacts/unreal_lighting_review/lighting-review-board.jpg).
- [Visor con observaciones y propuestas](../artifacts/unreal_lighting_review/index.html),
  autocontenido, con opción de ocultar las marcas.
- [Las 16 muestras](../artifacts/unreal_lighting_review/all-frames.jpg).
- [Evidencia y hashes](../artifacts/unreal_lighting_review/evidence.json).

Los recuadros del panel son anotaciones de revisión. No representan una
corrección de luz sobre la imagen ni se incorporan al vídeo de presentación.

## Hallazgos y prioridad

El problema principal es la separación visual: superficies superiores claras
reciben bastante luz, mientras caras verticales y mecanismos bajo los pórticos
quedan oscuros. Subir globalmente la exposición reduciría el margen en barras
blancas, rodillos y tapas amarillas; conviene empezar por rellenos locales.

P1 identifica el primer pase de corrección; P2, el segundo. Son prioridades de
presentación propuestas, no requisitos oficiales ni mediciones fotométricas.

| Zona | Referencia del vídeo | Prioridad | Observación y ajuste propuesto |
| --- | --- | --- | --- |
| L01 · Inputs | 00:00 | P2 | Los ladrillos superiores se leen bien; mejorar caras bajas, base del pallet y separación con el cabezal mediante rebote lateral amplio. Conservar el relleno ya existente. |
| L02 · Dehacking | 00:36 | P2 | Los vástagos oscuros y bajos de las vigas se confunden con el pórtico. Probar luz lateral/trasera suave que defina el contorno del cabezal. |
| L03 · Row → subbelt | 01:33 y pausa en 01:40,500 | **P1** | Mejorar bordes de la faja receptora y piezas del gripper. Redistribuir el relleno de perfil hacia caras laterales del row y añadir separación suave del lado opuesto. Evitar que la superficie cian sea el foco principal. Mantener la cámara de perfil. |
| L04 · Inspección/rechazo | Pausa en 02:10,500 y salida en 02:20 | **P1** | Barras blancas y rodillos atraen más atención que el conjunto del sensor. Probar relleno lateral neutro sobre carcasa/soportes y equilibrar las barras tras comprobar material y emisión. La faja de descarte se ve opaca en las muestras. |
| L05 · Distribución | 02:35 | P2 | Los numerosos reflejos de los rodillos compiten con ladrillos pequeños; algunas caras laterales pierden contraste. Probar luz cruzada suave. Si persiste, revisar rugosidad sin cambiar el color del ladrillo seguido. |
| L06 · Formación | 03:40, 04:20 y 04:51 | **P1** | El interior del well queda más oscuro que los rodillos exteriores. Probar relleno lateral bajo y una separación trasera sutil, conservando sombras de contacto. Las barras que ocultan el pallet son además un problema de encuadre. |
| L07 · Bridge | 05:10, 05:30 y 05:45 | **P1** | La tapa amarilla destaca, pero el frontal del pallet transportado queda muy sombreado dentro del gripper. Cubrir todo el recorrido con fuentes amplias desde dos lados oblicuos; evitar un foco pegado a cámara. |
| L08 · Vista general | 06:10 y 06:30 | P2 | El output se distingue mejor que parte de inputs/pórticos. Reequilibrar cobertura y separación de las estructuras durante toda la órbita. El fondo negro puede mantenerse como decisión estética. |

La lectura de la carcasa del sensor y el brillo de las barras no demuestran
clipping del master ni una limitación física del sistema de inspección. Antes de
ajustar materiales, comprobar el histograma y la contribución de luz/emisión en
el render original. Tampoco se puede recuperar con luz una pieza realmente
oculta por otra: esos casos requieren revisar el encuadre por separado.

## Base técnica conservada

La función `CreateLighting()` de
[FactoryScene.cpp](../unreal/Brickflow/Source/Brickflow/FactoryScene.cpp)
define tres RectLights grandes de 35 × 35 m con intensidades de código de
1.800.000, 1.600.000 y 1.800.000; además hay dos rellenos sin sombras para inputs
y perfil, de 180.000 y 100.000. El SkyLight tiene intensidad 0,45. En esa función
no se configura explícitamente un cubemap del cielo, por lo que su contribución
real debe comprobarse antes de tratarlo como iluminación ambiental garantizada.

Min/MaxBrightness de exposición están fijados a 1 y el bias a 0. Estos nombres
de parámetros no se deben interpretar como una medición de EV o lux. El suelo
también recibe un material oscuro en la función de materiales; la sensación de
oscuridad no depende únicamente de la potencia de las luces.

El perfil versionado
[presentation-review.v1.json](../unreal/lighting/presentation-review.v1.json)
conserva configuración, zonas, propuestas, referencias temporales y criterios
de aceptación. Es un contrato de revisión, **no un preset ya aprobado ni un
archivo cargado automáticamente por Unreal**. No fija potencias nuevas sin
probarlas en la escena.

## Aplicación a la simulación final

Reutilizar las ocho zonas como anclas semánticas: cart de entrada, banco de
dehacking, envolvente de extracción, inspección, mesas de distribución, well,
recorrido del bridge y límites de planta. Recalcular posiciones y cobertura
desde los bounds y las cámaras definitivas; no copiar coordenadas absolutas de
greenfield_30 sobre otra planta.

El almacén, los AMR y los muelles/camiones de las referencias posteriores
requieren su propia revisión cuando estén en Unreal. Prever luz legible en
horquillas y base del pallet, caras del stock y entrada/interior del camión.
Son zonas previstas; no se presentan como defectos observados en este vídeo.

Orden de trabajo al disponer de la simulación final:

1. Capturar una base con cámaras, poses, reloj, exposición y codificación fijos.
2. Corregir primero L03, L04, L06 y L07 con fuentes amplias y luz neutra. Conservar
   el aspecto cálido del ladrillo y las sombras que explican contacto y volumen.
3. Comparar A/B al mismo instante y revisar en 4K y al tamaño de proyección 1080p.
   Mantener el perfil Franka y las pausas de cinco y siete segundos.
4. Revisar transiciones, todo el bridge a 1× y la órbita final. Evitar saltos de
   intensidad, exposición automática perceptible y discrepancias entre GPU.
5. Aprobar imágenes y pequeños previews antes de producir otro vídeo completo.

No se alteran rutas, velocidades, poses, clasificación, grupos ni scores para
conseguir mejor luz. El apoyo de estudio es únicamente de presentación y no
valida percepción física, seguridad o capacidad industrial.

## Reproducibilidad

Los JPEG de revisión, extraídos en la VM a 1600 × 900 desde el MP4 4K, están en
`artifacts/unreal_lighting_review/current-film/`. Para reconstruir el panel y el
visor desde esas muestras, con Pillow disponible:

```bash
python3 unreal/tools/review_lighting.py --verify-video
```

La opción comprueba SHA-256 del MP4 local contra la entrega anterior e inventaría
las 16 muestras. `evidence.json` distingue expresamente la revisión de base de
una modificación renderizada de iluminación.
