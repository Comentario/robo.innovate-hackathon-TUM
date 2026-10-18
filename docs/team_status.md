# Estado del equipo: cubrimos personas 2 y 3

Persona 1 continúa con percepción. No tenemos todavía su rama, formato ni método.
No se considera integrado su módulo ni se afirma que use una NN.

## Implementado y comprobado con fixtures sintéticos

- Planificación: receta, equilibrio por capas/filas, patrón, secuencia y selección
  de una cara observada por ladrillo con orientaciones declaradas.
- Entrada canónica de percepción con snapshots identificados y adaptador explícito.
- Orquestación: geometría configurable, reservas locales de un ciclo, acciones,
  reconocimientos y journal persistente previo a cada despacho.
- Monitor: informes HTML/JSON y vista RViz opcional del checkpoint.
- Restauración de simulación pausada, sin repetir acciones reconocidas.
- Rechazo de replays, ejecutores con estado antiguo y acciones sin reconocimiento.
- Validador final independiente de las confirmaciones del ejecutor; sin
  observaciones reales el resultado permanece awaiting_observation.

Verificaciones actuales: 49 pruebas sin ROS y 10 pruebas de transporte/consumo
ROS. Se probó pausa entre procesos y restauración hasta completar 12 colocaciones.

## Cuando llegue persona 1

1. Revisar código y ejemplo de salida antes de decidir si su método necesita NN.
2. Convertir su formato al snapshot canónico manteniendo IDs, clases y caras.
3. Acordar significado de score, desconocidos y disponibilidad de cada ladrillo.
4. Evaluar errores con imágenes representativas, separadas de ajuste/entrenamiento.
5. Convertir posiciones medidas al frame de celda; no usar píxeles como metros.
6. Integrar observaciones independientes del pallet o verificaciones por paso.

## Pendientes de persona 3 que ahora son nuestros

- Brazo de referencia articulado con pinza, IK, alcance y trayectorias con
  colisiones comprobadas. El marcador actual de herramienta no hace eso.
- Adaptador del SDK real cuando se conozca la tecnología del evento.
- Reconciliación de acciones inciertas y replanificación de pallets parciales.
- Cola de producción, reset de ciclo físico, reserva compartida y persistencia
  operativa más allá del journal local de una sola celda simulada.

## Pendientes del reto

Muestras reales, criterios de aceptación visual, exposición de varias caras,
geometría/layout/agarre reales y validación física. Las reglas actuales siguen
siendo hipótesis configurables del equipo, no requisitos industriales confirmados.
