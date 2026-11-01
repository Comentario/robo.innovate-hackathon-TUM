# Contrato propuesto v0.1 — pendiente de acuerdo del equipo

## Entrada de planificación

Lista JSON de objetos con `id` (cadena no vacía, única) y `color_group`
(cadena no vacía). Atributos adicionales, como `score`, se ignoran.
Los identificadores numéricos del ejemplo conceptual del roadmap deben convertirse
explícitamente a cadenas en el adaptador de percepción.

Configuración: `rows`, `columns`, `layers` enteros positivos. Cada celda contiene
un ladrillo. Opcionalmente `target_ratios`: mapa de categoría a peso finito >= 0,
con suma positiva. Los pesos se normalizan; las categorías omitidas reciben peso
cero y no se seleccionan. Sin pesos explícitos, se mantiene la proporción del
inventario. Si no hay suficientes ladrillos elegibles, se rechaza el plan completo.
Si falta un tono, se redistribuye entre los tonos elegibles disponibles y se
reporta la desviación; no se inventan ladrillos.

## Salida de planificación

Objeto con `schema_version`, `shape`, `blend`, `placements` y `metrics`.
`blend` contiene cantidades por categoría. Cada placement tiene `step` (desde 1),
`brick_id`, `color_group`, `layer`, `row`, `column` (índices desde 0).
Se ejecuta una capa completa antes de la siguiente, por filas y columnas.
`metrics` contiene proporciones objetivo y reales, desviación L1 y cantidad de
pares vecinos del mismo tono (incluye vecinos verticales entre capas).

Estas posiciones son lógicas: persona 3 debe convertirlas a coordenadas físicas.
No representan poses, orientaciones, estabilidad estructural ni trayectorias
seguras. Rechazar planes incompatibles con el agarre, soporte o layout real.

## Integración

API: `planning.make_plan(inventory, rows=..., columns=..., layers=...,
target_ratios=None) -> dict`. Errores de contrato: `ValueError`.
CLI: `python3 -m planning INVENTORY --rows R --columns C --layers L
[--ratios '{"dark": 1, "light": 1}']`.
Éxito: JSON y código 0; error: mensaje por stderr y código 2.

## Extensión v0.2

`make_plan` acepta además `mode="mixed" | "smooth"`,
`tone_values=None | {categoria: valor_entre_0_y_1}` y
`shortage_policy="redistribute" | "reject"`. El modo suave requiere valores
finitos para las categorías seleccionadas. `reject` exige que las cantidades
coincidan con la receta redondeada por la misma asignación incremental, sin
limitación de existencias. La API mantiene `redistribute` por compatibilidad;
los ejemplos de configuración usan `reject`.

La salida v0.2 añade `policy` (modo, política de faltantes y escala de tonos)
y `metrics.mean_neighbor_tone_distance` (null en modo mixed; 0 sin vecinos).
La CLI acepta `--config PATH`; los argumentos de dimensiones y `--ratios`
prevalecen sobre el JSON. Las claves desconocidas se rechazan.

## Ejemplo reproducible de integración

Ver `examples/handoff/` y `docs/handoff.md`. La salida de referencia v0.2 es
un plan completo sobre inventario sintético. La gestión de disponibilidad,
reservas, confirmaciones y pallets parcialmente construidos aún no forma parte
de esta API; requiere coordinación con integración antes de ejecutar hardware.

## Extensión opcional por caras v0.3

Ver `docs/faces.md` y `examples/faces/`. `planning.faces.make_face_plan` consume
caras observadas y orientaciones permitidas, conserva IDs físicos únicos y
produce placements con `visible_face` y `orientation_id`. El consumidor simulado
valida ambas versiones, v0.2 y v0.3. La API anterior mantiene su comportamiento.

## Diagnóstico de distribución local (campos adicionales)

`metrics.distribution` publica conteos por capa y fila, objetivos locales de
receta y de la mezcla seleccionada, y errores L1 contra ambos. Esto distingue
falta de stock de acumulación espacial. Mixed asigna cuotas de mezcla por capa
y fila antes de penalizar vecinos iguales. Smooth conserva su criterio local.
El redondeo es determinista y no garantiza el óptimo visual global.

## Contrato de ejecución independiente de transporte

`execution.compile_job(plan, inventory, cell_config)` traduce placements a
acciones de referencia de objeto; `ExecutionAdapter.perform(command)` reconoce
cada acción con succeeded/failed_before_action/unknown. `config/cell.json` y
`docs/cell_execution.md` definen poses, fases y estados. No cambia el contrato
del planificador ni exige ROS. El modo ROS `--cell` publica estas mismas acciones
y estados de ejecución simulada sobre el adaptador opcional.

## Entrega de persona 1 e integración de personas 2 y 3

Ver `examples/perception/snapshot.json` y `docs/orchestration.md`: instantánea
versionada con ID, origen declarado, modalidad por caras y lista de items.
Planificar no exige poses. Ejecutar un origen perception exige poses métricas
por ID en el frame de la celda; nunca se reinterpretan píxeles como metros.
El adaptador de entrada se ajustará al productor real cuando llegue.

La evidencia final usa pallet-observation-0.1, vinculada a run_id y plan_digest.
Sin evidencia el estado es awaiting_observation, aunque la ejecución termine.
El journal SQLite conserva reservas de un ciclo, acciones pendientes y reconocidas.

## Recuperación explícita de un pallet parcial

`cell-reconciliation-0.1` vincula evidencia completa al run, plan y huella del
checkpoint. `integration.recovery.assess_recovery` produce una propuesta sin
movimiento; `Journal.recover_simulation` crea un run hijo con un prefijo verificado
preservado y tareas restantes, únicamente para acknowledgement_simulator.
`execution.compile_job(..., preserved_placements=PREFIX)` excluye ese prefijo de
los picks y exige poses solo para las piezas aún disponibles. Ver `docs/recovery.md`.


## Recuperación de la referencia Panda

`Journal.recover_reference_simulation` es una vía distinta de la recuperación
lógica. Requiere el adaptador Panda concreto, checkpoint de escena, preparación
persistente de posición segura y comparación actual de la escena/articulaciones.
La evidencia cell-reconciliation-0.1 añade robot_scene y robot_scene_digest.
El hijo conserva panda_moveit_kinematic y queda listo solo tras activar su escena.
No habilita hardware ni `resume_simulation` para Panda. Ver
`docs/reference_arm_recovery.md` para el alcance de esta demo.

## Entrada de persona 1: color relativo schema 0.2

`integration.person1_intake.convert_inventory(value, min_score=...)` convierte
el inventario `color_estimated`/`accepted` de persona 1 a nuestro snapshot.
Conserva `uniform`/`color_group_N`, centros Lab, score heurístico y geometría px;
excluye unknown, parciales, posibles merges, no elegibles y scores bajo umbral.
No incorpora source_poses ni identidad de cara: `source=perception`,
`face_aware=false`. El snapshot sirve para planificar; ejecutar exige poses
métricas medidas como cualquier entrada de percepción. Los IDs son locales a
la imagen; categorías de capturas distintas no se equiparan automáticamente.
Ver `docs/person1_review_2026-10-21.md` y `examples/person1/`.

## Inventario de persona 1 en la celda de referencia

`integration.person1_simulation.prepare_person1_simulation(inventory, cell, config=None)`
consume clases/scores sin reclasificar ni filtrar por puntuación adicional. Devuelve
`observed_snapshot` (perception), `staged_snapshot` (synthetic), `plan`, `job` y
`handoff`. Solo los IDs seleccionados se colocan en la cuadrícula de staging.
El job conserva `person1_handoff` con centros Lab, huella del inventario, receta,
conteos y procedencia de geometría. Se preserva el bloqueo de ejecución del
snapshot real sin poses medidas. Ver `docs/person1_simulation.md`.

## Continuidad de persona 1 durante recuperación

El reconciliador conserva `job.person1_handoff` y el `producer` del snapshot de
staging en el ciclo hijo. Para ese lote, rechaza cambios de clase/score de IDs
conocidos e IDs no incluidos en el staging. El adaptador Panda verifica también
que no cambie la procedencia al activar el nuevo job. Receta, plan y prefijo
permanecen intactos; el hijo contiene únicamente acciones nuevas para el resto.
Los jobs con geometría `synthetic_staging_grid` no se admiten con `mode=hardware`.
Ver `docs/person1_recovery.md` y `docs/event_connection.md`.


## Task 3 — independent process simulation

`plant_sim.model.Plant(config).run()` consumes the versioned configuration in
`config/plant_demo.json`; it returns run status, config/provenance, KPIs, material
ledger, pallet IDs, per-layer/pallet mixing metrics and a timestamped event log.
Time is seconds; rates are bricks/hour; dimensions are millimeters. One product
per run. Input geometry is 10×4×20 and output 10×4×14 in the organizer example.
The synthetic detector is separate from the existing Person 1 adapter. No ROS or
hardware commands are emitted. `blocked` requires explicit reconciliation; no
automatic restart is implemented. Generated HTML is an offline event-log replay.
See `docs/plant_simulation.md` for assumptions, conservation and limitations.


### Task 3 mechanical trace, revision 1.1

The process config/report is now 1.1 and includes `seconds.lane_transfer` and
brick/lane/slot/destination context on correction operation-start events.
`compile_mechanics(report)` emits meter-based, Y-up identity tracks, tool paths,
attachment intervals and inspection observations. `validate_mechanics` audits
continuity and exclusive tool booking, not contact or collision physics.
Default `index.html` is now an offline Three.js 3D view; the 2D view is preserved
as `process_2d.html`. `mechanics.json` records paths separately from `run.json`.
No robot or PLC control is introduced. See `docs/plant_3d.md`.


### Task 3 automation revision 1.2

`automation` contains positive speeds [m/s], grip/release/settle/exposure/inference
pauses [s], and carry clearance [m]. `initial_arrival_s` is nonnegative. The old
`seconds` table no longer drives motion. Every operation-start event embeds its
actual `motion_plan`: ordered substeps, material/tool/auxiliary tracks and duration.
SimPy executes that recipe; the renderer reads it without re-planning.
`automation.timing` reports travel/dwell, explicit resource waits and shared-clock
rate arithmetic. Join nests and physical infeed/lane/pairer/stacker berths have
exclusive reservations. Photoeyes in the viewer use material coordinates;
sequence limit confirmations remain virtual. 3D export checks swept brick bounds
against fixed solids and refuses known penetrations. Scope excludes full contact,
brick-brick, tools/cables and dynamics. Multi-robot process capacity requires a
separate audited geometric layout before exporting 3D. See docs/plant_automation.md.
