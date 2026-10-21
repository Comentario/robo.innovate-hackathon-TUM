# Conectar el equipo del evento

El flujo simulado ya conecta JSON de persona 1, planificación, ejecución Panda,
parada y recuperación. La transición física consiste en proporcionar datos reales
a sus fronteras y adaptar el SDK; no en rehacer la clasificación.

`config/event_connection.template.json` reúne los datos pendientes. Es una plantilla
informativa desactivada, no un `cell-0.1` ejecutable. Los valores null son desconocidos;
no se han rellenado con dimensiones ni configuraciones de la maqueta.

## Datos para sustituir la maqueta

| Área | Información necesaria | Dónde se conecta |
|---|---|---|
| Robot/control | Fabricante, modelo, SDK/versión, unidades, estados del controlador, base y TCP | Implementación de `execution.ExecutionAdapter` |
| Pinza | Tipo, acciones y confirmaciones disponibles, offset TCP–centro de pieza | Adaptación de pick/place y poses objetivo |
| Celda | Dimensiones reales del ladrillo, soportes, pallet, origen, límites y home | Nueva configuración `cell-0.1`; no reutilizar silenciosamente `cell_panda.json` |
| Cámara/poses | Frame y transformación medida a la celda; posiciones y orientación métricas por ID | `snapshot.source_poses`, `frame` y `units='m'` |
| Lote e identidad | Correspondencia entre IDs de imagen y piezas presentes durante el ciclo | Snapshot de inventario congelado y reconciliación explícita |
| Caras | Qué cara observó el productor y qué orientaciones se pueden ejecutar | Contrato face-aware cuando haya observaciones de caras |

Las poses describen el centro del ladrillo, no directamente el TCP. El adaptador
aplica el offset de agarre y la conversión de unidades del SDK. Los píxeles nunca
se interpretan como metros. El método para obtener poses dependerá de la cámara
y sensores que se entreguen: todavía no se supone ninguno.

La celda inicial admite piezas verticales con yaw 0/180°. Si la tecnología exige
otras orientaciones o geometrías, habrá que ampliar ese modelo con la información
real; no tratar esas poses como ya soportadas por el ejemplo.

## Integración incremental al conocer el SDK

1. Completar la plantilla con los datos del equipo y definir frames/unidades.
   Mantener los grupos Lab/K-means y scores de persona 1 tal como los entrega.
2. Crear la configuración física y el productor de poses métricas. El snapshot
   real conserva `source='perception'`. La ruta existente rechaza su ejecución
   cuando faltan poses medidas o su frame no coincide con el de la celda.
3. Implementar `perform(command) -> ActionResult` usando el SDK disponible,
   declarando `mode=hardware` y un backend propio.
   Se mantienen las fases de recoger, elevar, orientar, colocar y confirmar.
   Un fallo comprobado antes de actuar devuelve `failed_before_action`; una
   ejecución confirmada devuelve `succeeded`; un resultado incierto, `unknown`.
   No convertir un timeout en éxito ni repetir automáticamente la acción.
4. Probar la configuración y las respuestas del SDK con la plataforma disponible,
   y después comprobar recogida/colocación con piezas reales. Conectar sus estados
   y evidencias al monitor/journal existente. Las confirmaciones sintéticas no
   sustituyen a las del equipo físico.
5. Adaptar la reconciliación a la evidencia disponible. Para continuar se necesita
   saber qué quedó colocado, qué está disponible, el estado de la pinza y del
   robot. Una observación incompleta conserva el ciclo detenido; no se copia el
   permiso de recuperación de la maqueta al hardware.

La identidad y las categorías se vinculan al snapshot usado para el ciclo. No se
mezcla sin correspondencia explícita una nueva captura o un nuevo clustering con
un lote a medio ejecutar. La recuperación actual exige continuidad del lote de
persona 1; no realiza tracking ni clasificación alternativos.

La validación del pallet físico comprueba el resultado de colocación y usa su
contrato de observación independiente. Esto no añade una revisión manual de la
clasificación del compañero.

No se ha implementado un adaptador físico inventado ni se ha dado por calibrado
un equipo que todavía no conocemos. El núcleo y los ensayos repetibles quedan
preparados para incorporar esos datos cuando se entreguen.

Los jobs de staging de persona 1 no se pueden enviar a un adaptador que declare
modo hardware: el ejecutor los rechaza antes de actuar. El recorrido físico debe
partir de poses reales, no de habilitar el job de la maqueta.
