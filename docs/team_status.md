# Estado del equipo: cubrimos personas 2 y 3

Persona 1 continúa con percepción. Se revisó `origin/persona1/perception` en `e71ddf3`: detector OpenCV clásico,
formato de inventario parcial y cinco escenas reproducidas. La estimación de
tono sigue pendiente; no se considera integrado su módulo.
Ver `person1_review_2026-10-18.md` para resultados y propuesta de contrato.

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

Verificaciones actuales: 67 pruebas sin ROS, 11 pruebas del adaptador Panda y
10 pruebas de transporte/consumo ROS. Se probó pausa entre procesos y restauración hasta completar 12 colocaciones.

## Cuando llegue persona 1

1. Revisar los nuevos cambios respecto a `e71ddf3`; la detección actual no usa NN.
2. Convertir su formato al snapshot canónico manteniendo IDs, clases y caras.
3. Acordar significado de score, desconocidos y disponibilidad de cada ladrillo.
4. Evaluar errores con imágenes representativas, separadas de ajuste/entrenamiento.
5. Convertir posiciones medidas al frame de celda; no usar píxeles como metros.
6. Integrar observaciones independientes del pallet o verificaciones por paso.

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
