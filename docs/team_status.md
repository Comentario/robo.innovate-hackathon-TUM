# Estado del equipo: cubrimos personas 2 y 3

Persona 1 entregó clasificación Lab/K-means e inventario en `3e705b4`.
Nuestro módulo consume su JSON y ya lo conecta con planificación y ejecución
Panda/MoveIt de referencia, sin reclasificación ni revisión manual. Las posiciones
de recogida siguen siendo explícitamente simuladas. Ver `person1_simulation.md`.

## Implementado y comprobado con fixtures sintéticos

- Planificación: receta, equilibrio por capas/filas, patrón, secuencia y selección
  de una cara observada por ladrillo con orientaciones declaradas.
- Entrada canónica de percepción con snapshots identificados y adaptador explícito.
- Orquestación: geometría configurable, reservas locales de un ciclo, acciones,
  reconocimientos y journal persistente previo a cada despacho.
- Monitor: informes HTML/JSON y vista RViz opcional del checkpoint.
- Adaptador opcional Panda/MoveIt: brazo articulado, pinza, planificación OMPL,
  objetos adjuntos y colisiones de la maqueta. Ver `reference_arm.md`.
  La reproducción es cinemática y la confirmación sigue siendo sintética.
- Restauración de simulación pausada, sin repetir acciones reconocidas.
- Rechazo de replays, ejecutores con estado antiguo y acciones sin reconocimiento.
- Recuperación explícita del simulador lógico: prefijo verificado, sustitución
  por tono/cara compatible, nuevo run y rechazo de reconocimientos tardíos.
  Demo e interfaces en `recovery.md`; no se reanuda hardware ni Panda.
- Recuperación Panda verificada contra escena y articulaciones: reconstrucción
  del cliente, preparación auditada de posición segura y continuación con
  colisiones comprobadas. Ver `reference_arm_recovery.md` para límites.
- Validador final independiente de las confirmaciones del ejecutor; sin
  observaciones reales el resultado permanece awaiting_observation.

Verificaciones actuales: 82 pruebas sin ROS, 12 pruebas del adaptador Panda y
10 pruebas de transporte/consumo ROS. Se probó pausa entre procesos y restauración hasta completar 12 colocaciones.

## Entrega de persona 1 revisada

Revisada `3e705b4` el 21 de octubre: detectores de pallet/pared e inventarios
relativos Lab reproducidos. Adaptador offline `integration.person1_intake`,
fixture JSON sin cambios y receta provisional de dos grupos disponibles.
Flujo actual: 70/70 piezas sin filtro de score adicional; doce seleccionadas y
colocadas en el brazo de referencia (96 acciones). Se conservan sus IDs/clases.
Ver `person1_review_2026-10-21.md`. No se hizo merge del código de percepción.
La demo `python3 -m demo.person1_visual` enlaza imagen, decisiones e IDs del plan
sin filtro adicional por defecto; guion en `person1_visual.md`.
El lanzador `person1` consume el JSON de la entrega y usa una cuadrícula de staging
sintética para conectar el plan con el brazo; admite uno, dos o tres grupos.

Antes de ejecutar percepción real: fijar categorías estables entre capturas,
tracking/lote estático, caras observadas, poses métricas y calibración de celda.
El score no es probabilidad calibrada. La validación final sigue requiriendo
observaciones independientes del pallet.

## Pendientes de persona 3 que ahora son nuestros

- Validar y calibrar el modelo del robot real; la maqueta Panda no determina
  alcance, agarres, estabilidad ni dimensiones del equipo del evento.
- Adaptador del SDK real cuando se conozca la tecnología del evento.
- Recuperación con el SDK real, ante pérdida del servidor/escena o una pieza
  sostenida. La demo Panda actual conserva un prefijo y la receta original.
- Cola de producción, reset de ciclo físico, reserva compartida y persistencia
  operativa más allá del journal local de una sola celda simulada.

## Pendientes del reto

Muestras reales, criterios de aceptación visual, exposición de varias caras,
geometría/layout/agarre reales y validación física. Las reglas actuales siguen
siendo hipótesis configurables del equipo, no requisitos industriales confirmados.
