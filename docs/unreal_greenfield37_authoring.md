# Última planta en Unreal: revisión visual e iluminación

Se fijó una copia de `artifacts/greenfield_37/index.html` al comenzar esta revisión:
SHA-256 `f8bacc33c4f74261bd20ff8c1fa176772f4eb72b97557afa97d48b17eb28eadd`.
La referencia sigue **pendiente de validación**. Esta copia sustituye a las
anteriores para el presente estudio visual; no se modificó el HTML original.

## Qué está subido y funcionando

En `brickflow-cinematic-4gpu` se creó un proyecto independiente:
`~/workspace/brickflow-review37-f8bacc33/`.

El nuevo modo de autoría carga la geometría, materiales y poses observadas del
replay preparado. Se compiló y se renderizó con Unreal Engine 5.8.4/Vulkan.
Se prepararon cinco estados congelados: entrada; inspección cerrada; inspección
con su cubierta de servicio abierta; almacén; carga lateral en mitad de la
extensión real de las horquillas del registro fuente. Hay alrededor de 443.500
instancias visibles por estado, conservando únicamente el LOD de mayor detalle.

**Estos estados no reproducen el movimiento ni constituyen el port nativo de la
simulación 37.** Sirven para adelantar geometría, encuadres e iluminación mientras
se valida la lógica. El modo de revisión no inicia el modelo C++ anterior, no
inventa tracks y no permite confundir sus contadores con resultados nativos.
El movimiento continuo de la versión nueva sigue pendiente de implementación.

La referencia actual incorpora depósito directo del bridge en stock y carga
lateral del camión por vehículos autónomos con extensión de horquillas. No hay
plataforma de handoff intermedia ni dockLift en el inventario observado. Las
cubiertas de inspección y distribución son ahora opacas; la vista de servicio
usa la apertura que ya existe en el viewer fuente.

## Comparación de luz realizada

Se renderizaron ocho pares A/B a 1600 × 900, manteniendo exactamente la misma
geometría, pose, cámara y exposición. Cada par compara el rig anterior con once
fuentes RectLight adicionales de estudio. Son pruebas, no un acabado aprobado.

- [Visor A/B autocontenido](../artifacts/unreal_migration37/reference37-f8bacc33/lighting-ab.html).
- [Panel de las ocho comparaciones](../artifacts/unreal_migration37/reference37-f8bacc33/lighting-comparison.jpg).
- [Comprobaciones de importación y A/B](../artifacts/unreal_migration37/reference37-f8bacc33/unreal-stills/verification.json).

| Zona | Resultado observado | Siguiente ajuste de presentación |
| --- | --- | --- |
| Horquillas/pallet/camión | Sin relleno, partes del vehículo y la carga quedan casi negras; con la prueba se separan horquillas, base del pallet y borde de plataforma. | **Primera prioridad:** conservar cobertura lateral amplia y ajustar su equilibrio con la luz superior. |
| Cuatro posiciones de carga | El rig antiguo deja las posiciones exteriores muy oscuras. | Mantener luces propias del área de camiones, con cobertura continua para todo el recorrido. |
| Caras del stock | La prueba permite leer mejor ladrillos laterales, pies del pallet y soportes. | Reducir luz sobre las caras superiores y el parche claro del suelo; conservar sombras de contacto. |
| Inspección abierta | La carcasa gana detalle, pero el relleno de prueba ilumina demasiado algunos raíles y superficies claras. | Reducir potencia y concentrar cobertura en el conjunto óptico, usando un encuadre más cercano. |
| Inspección cerrada | La carcasa exterior se ve mejor, pero los interiores siguen realmente ocultos. | Evitar iluminar más el techo; reservar la apertura de servicio para el plano explicativo. |
| Inputs y dehacking | Mejora la lectura lateral de los pallets. | Refinar con el encuadre final cercano: el preset fuente es una vista amplia. |
| Vista general | La logística necesita cobertura adicional y el área de carga se distingue mejor con la prueba. | Reencuadrar la vista general y equilibrar intensidad entre producción, stock y carga. |

La mejora fuerte está en la logística. La prueba todavía ilumina demasiado
algunas tapas, raíles y zonas del suelo; no conviene adoptar las once potencias
sin ajustes. Se mantuvo la exposición fija. No se cambiaron colores de bricks,
grupos, scores, rutas ni posiciones para mejorar la presentación.

El rig de prueba y los cinco manifests están en:
`~/workspace/brickflow-native/Saved/Exploration37/review37-f8bacc33/`.
Los PNG y sus evidencias están en:
`~/workspace/brickflow-review37-f8bacc33/Saved/ReviewStills/lighting-v2/`.

## Revisión interactiva

Hay un escritorio de revisión separado, display `:82`, con noVNC solamente en
loopback `6081`. Para abrirlo desde el equipo con acceso SSH a Brev:

```bash
ssh -N -L 6081:127.0.0.1:6081 brickflow-cinematic-4gpu
```

Abrir `http://localhost:6081/vnc.html?autoconnect=1&resize=scale&path=websockify`.

Controles: `1`–`8`, encuadres de entrada a vista general; `9`, detalle de
horquillas; `0`, detalle del stock; `L`, alternar rig base y candidato; botón
derecho y arrastre, órbita; rueda, zoom. El estado de carga lateral está
congelado: la navegación mueve únicamente la cámara.

El ejecutable anterior sigue en su proyecto y escritorio propios. Su archivo
`Content/Data/factory.json` mantiene SHA-256
`ccd649ee95efc0ce623106fea8f95181651cb67cf581973c20e981900790f019`.
No se generó otra película de la nueva planta.

## Verificación y límites

- Compilación de `BrickflowEditor` satisfactoria en el proyecto separado.
- Prueba del exportador con el Three.js exacto del HTML: formato legacy
  conservado, exclusión de ancestros ocultos, un solo LOD, bricks visibles y
  colores alineados tras eliminar matrices de escala cero.
- En las ocho comparaciones se verificaron todas las matrices empaquetadas
  mediante muestras de origen y tres ejes de la primera y última instancia de
  cada lote: 406 o 424 lotes, según estado. Error máximo observado de las
  muestras: 0,000306 cm. Esto comprueba la conversión de coordenadas, no toda
  la física ni cada vértice de todas las instancias.
- A/B conservó geometría, cámara, tiempo y muestras de transformación.
- La primera prueba con más luces excedió la reserva por defecto de culling de
  sombras virtuales. Se amplió a 512 MiB **solo en el modo de revisión** y se
  repitieron las capturas. Los 16 renders de `lighting-v2` no registraron ese
  aviso ni errores fatales. Las pruebas iniciales se conservaron aparte.

Los contadores del replay fuente actual son observaciones sintéticas: 57.600
inspeccionados, 6.936 rechazados, 86 pallets producidos/almacenados y 64
cargados/expedidos; duración de replay 22.497,172 s. No son resultados del
modelo nativo ni validación industrial. Las diferencias con los contadores del
estudio anterior corresponden a otra copia de la referencia.

Herramientas reproducibles: `stage_review_cloud.py`, `preview_review_cloud.sh`,
`verify_review_scene.py`, `start_review_interactive_cloud.sh` y
`build_review_ab.py`, en `unreal/tools/`. El esquema de entrada es
`brickflow.unreal-lighting-scene.v1`; sus flags distinguen `snapshotOnly=true`
y `nativeSimulationPorted=false`.
