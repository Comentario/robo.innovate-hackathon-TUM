# Marmon — Munich Hackathon 2026

Preparación para el reto #8: Intelligent Brick Blending and Palletizing.

## Tarea 3 · ocho células en dos líneas paralelas

```bash
python3 scripts/greenfield_demo.py --compare --output-dir artifacts/greenfield_04
```

Abrir `artifacts/greenfield_04/index.html`. Carro de inventario, puente de entrega,
dos dehackers, dos apiladores y salida común sobre carro. Un solo descarte con
carros que se recogen, vacían y retornan. El panel de cámaras es desplegable y
Layer history permite inspeccionar todas las capas formadas.

Arquitectura, supuestos y límites: [doble línea](docs/greenfield_dual.md).
Punto de retorno anterior: `6e912e2`, `artifacts/greenfield_03/index.html`.
Antecedentes: [greenfield v2](docs/greenfield_v2.md).

## Tarea 3: prototipo anterior de planta 3D con SimPy

```bash
python3 scripts/plant_demo.py --compare --output-dir artifacts/plant_automation_01
```

Abrir `artifacts/plant_automation_01/index.html` y `comparison.html`. Escena 3D offline con
pórticos, transportadores, cámaras, sensores virtuales y seguimiento de cada ID.
Punto de retorno 3D: `345c027` / `task3-3d-checkpoint`.
Los ciclos ahora derivan de distancias, velocidades y pausas de automatización;
ver [automatización y tiempos](docs/plant_automation.md).
Punto de retorno 2D: `dc8cab1` / etiqueta `task3-2d-checkpoint`. Línea independiente:
dehacking de dos capas, separación, inspección, corrección selectiva, emparejamiento
y reapilado. Incluye buffers finitos, sensores virtuales y fallos. Todos los ciclos
son supuestos configurables; no representa validación física ni mejora industrial
medida. Uso y límites: [planta 3D](docs/plant_3d.md);
[modelo de proceso](docs/plant_simulation.md).

## Ensayo del brazo con un comando

```bash
python3 scripts/rehearse.py normal
python3 scripts/rehearse.py recovery
python3 scripts/rehearse.py person1
python3 scripts/rehearse.py person1-recovery
```

Ejecutar uno cada vez. Abre MoveIt y RViz, muestra el progreso en inglés y conserva
el journal y un informe por ensayo. Ver [guion de reproducción](docs/rehearsal.md).
Requiere las dependencias de [brazo de referencia](docs/reference_arm.md).

## Persona 2: planificación

Python 3.10+, sin dependencias externas. Desde la raíz:

```bash
python3 -m planning data/inventory.json --rows 2 --columns 3 --layers 2
python3 -m unittest discover -s tests -v
```

El ejemplo usa inventario sintético y genera JSON por stdout; no controla hardware.
Consulta `interfaces.md` y `docs/person_2_notes.md` antes de integrar.

## Colaboración

- Rama actual: `persona2/planning`, creada desde `main` (todavía no existe `dev`).
- Acordar una rama compartida `dev`; dirigir allí los PR antes de integrar a `main`.
- Hacer un commit por cambio coherente, con su comprobación y documentación.
- Actualizar `interfaces.md` cuando cambien entradas o salidas.
- Mantener percepción (persona 1), planificación (persona 2) y ejecución (persona 3) independientes.
- Para recuperar un estado, preferir una rama desde el commit estable o `git revert`.

El roadmap original está en `docs/roadmap_graph.md`.

## Políticas configurables

```bash
python3 -m planning data/inventory.json --config config/mixed.json
python3 -m planning data/inventory.json --config config/smooth.json
```

Los ejemplos no son recetas oficiales. Ver `docs/mixing_criteria.md` para el
fundamento del reto, criterios provisionales, limitaciones y decisiones pendientes.
VS Code: abrir esta carpeta con `code --new-window .`; no requiere instalar paquetes.

## Comparación visual por capas

```bash
python3 -m planning.visualize
```

Abrir `artifacts/mixing_comparison.svg` en un navegador o vista previa SVG.
Se generan también planes y métricas en `artifacts/mixing_comparison.json`.
Compara ambos modos y políticas de faltantes sobre tres inventarios sintéticos.
Consultar `docs/visual_comparison.md` para interpretar resultados y limitaciones.
Los artefactos se regeneran desde `data/scenarios.json` y no se versionan.

## Ejemplo de intercambio entre módulos

```bash
python3 -m planning examples/handoff/inventory.json --config examples/handoff/config.json
```

`examples/handoff/plan.json` contiene una salida de referencia. Consultar
`docs/handoff.md` para los requisitos de percepción/ejecución y los acuerdos
pendientes de reservas y recuperación. Todas las demos y visualizaciones están
en inglés; la documentación puede estar en español.

## Prueba de integración sin hardware

```bash
python3 -m demo
python3 -m demo --fail-step 5 --output artifacts/dry_run_failure.json
```

La primera ejecución confirma 12 colocaciones simuladas (código 0). La segunda
se detiene antes del paso 5, con 4 confirmaciones (código 3 esperado).
Ver `docs/integration_demo.md` para interpretar eventos, rechazos y límites.

## Demo animada en el navegador

```bash
python3 -m demo.browser
```

Abrir `artifacts/brick_demo.html` en Chrome o Edge. Incluye reproducción por pasos,
comparación mixed/smooth, fallo antes del pick 5 y escenarios de tonalidad por
cara con restricciones de orientación. No requiere servidor ni dependencias.
Ver `docs/browser_demo.md` para un guion visual y `docs/faces.md` para el contrato.

## ROS 2 opcional y adaptación a otros SDK

El núcleo de planificación no depende de ROS. Para probar el transporte con
ROS 2 Humble y ver un pallet 3D en RViz, en dos terminales:

```bash
bash scripts/ros_preview.sh
bash scripts/ros_preview.sh rviz
```

Son cubos animados, sin brazo ni planificación de trayectorias. Otro SDK podrá
consumir el mismo plan mediante su propio adaptador. Ver `docs/adapters.md`.
Pruebas del transporte opcional: `bash scripts/ros_preview.sh test`.

## Celda y acciones de ejecución

```bash
# Sin ROS: 12 ladrillos / 96 acciones reconocidas por el adaptador simulado
python3 -m execution
# Vista de recogida, herramienta de referencia y pallet (dos terminales)
bash scripts/ros_preview.sh --cell config/cell.json --period 0.2
bash scripts/ros_preview.sh rviz-cell
```

Para detener después de recoger el quinto ladrillo, añadir
`--fail-step 5 --fail-phase orient` al publicador. Cerrar la ejecución anterior
antes de iniciar otra. Ver `docs/cell_execution.md` para configuración, contrato,
estados inciertos y límites: aún no hay brazo articulado ni trayectorias con
colisiones comprobadas.

## Personas 2 y 3: integración persistente

Persona 1 continúa con percepción. Podemos preparar y probar el flujo con una
instantánea sintética canónica, sin depender de su detector:

```bash
python3 -m integration run --state artifacts/persona23.sqlite3 --pause-after 10
python3 -m integration resume --state artifacts/persona23.sqlite3
python3 -m integration inspect --state artifacts/persona23.sqlite3
```

La pausa devuelve código 4. Se generan reportes HTML en inglés además del JSON.
Un journal corresponde a un ciclo de celda; no volver a lanzar run sobre el
mismo estado para repetir acciones. Ver `docs/orchestration.md` y
`docs/perception_method.md` para contratos, evidencia final y método de percepción.

Para mostrar un journal persistente en RViz:

```bash
bash scripts/ros_preview.sh --snapshot examples/perception/snapshot.json --cell config/cell.json --state artifacts/persona23.sqlite3 --period 0.2
```

Un estado existente abre solo una vista del checkpoint, sin repetir acciones.
Cerrar cualquier publicador anterior antes de ejecutar este comando.

## Brazo articulado de referencia (persona 3)

La demo opcional Panda + MoveIt usa nuestro contrato de ejecución y journal,
con trayectorias y colisiones planificadas y reproducción cinemática en RViz.
Consulta [reproducción, parámetros y límites](docs/reference_arm.md).
Percepción de persona 1 sigue sin integrarse.

## Recuperación de un pallet parcial

```bash
python3 -m integration.recovery_demo --output-dir artifacts/recovery_demo
```

Abrir `index.html` en el directorio generado. La demo conserva cuatro posiciones,
sustituye una pieza faltante y ejecuta solo lo pendiente en un run simulado nuevo.
Ver [contrato, CLI y límites](docs/recovery.md). No reanuda automáticamente el
Panda ni hardware, y no incorpora todavía el módulo de persona 1.


## Recuperación con el Panda en RViz

```bash
scripts/arm_demo.sh launch
# En otra terminal, con un directorio nuevo:
scripts/arm_demo.sh recovery --output-dir artifacts/panda_recovery --speed 3
```

Coloca cuatro piezas, se detiene, reconstruye el cliente desde MoveIt y continúa
sin volver a recoger las cuatro posiciones verificadas. Ver
[reproducción y límites](docs/reference_arm_recovery.md). No controla hardware.

## Inventario entregado por persona 1

Entrada offline revisada en `3e705b4`: planificar conservando los grupos Lab
relativos, sin requerir OpenCV en nuestro núcleo.

```bash
python3 -m integration.person1_intake examples/person1/inventory_with_color.json \
  --min-score 0 --config examples/person1/config.json \
  --output-dir artifacts/person1_intake_new
```

Se consumen sus clases sin filtro de score adicional. La receta 50/50 es una
hipótesis explícita de la demo. El informe HTML
explica aceptados/excluidos y las doce posiciones. No ejecuta el robot: faltan
poses métricas y caras. Ver [revisión y límites](docs/person1_review_2026-10-21.md).

## Ver imagen, filtro y plan con los mismos IDs

```bash
python3 -m demo.person1_visual --output-dir artifacts/person1_visual_new
```

Abrir el `index.html` generado. Seleccionar un ladrillo en la foto o en el plan
para ver su correspondencia y motivo de aceptación/exclusión. Cambiar el umbral
permite comprobar cuándo la receta deja de ser viable. Página autónoma, en inglés,
sin ejecutar el robot. Ver [guion de la demo](docs/person1_visual.md).

## Inventario de persona 1 con el brazo

```bash
python3 scripts/rehearse.py person1
# Otro archivo entregado por persona 1:
python3 scripts/rehearse.py person1 --inventory /ruta/inventory_with_color.json
```

Usa directamente sus grupos Lab/K-means, IDs y puntuaciones, sin reclasificación
ni revisión manual. Planifica y coloca doce piezas en RViz con poses explícitamente
simuladas. Los centros Lab solo se convierten a RGB para dibujarlos. Ver
[integración incremental](docs/person1_simulation.md).

## Recuperación con el inventario de persona 1

```bash
python3 scripts/rehearse.py person1-recovery
# Exportación original con tres grupos:
python3 scripts/rehearse.py person1-recovery \
  --inventory examples/person1/inventory_three_groups.json
```

Coloca cuatro piezas, reconstruye el cliente y completa las ocho restantes con
64 acciones nuevas, conservando la receta y los IDs/grupos/scores entregados.
Ver [recuperación integrada](docs/person1_recovery.md). Para sustituir la maqueta
por el equipo del evento, ver [datos y conexión pendientes](docs/event_connection.md)
y `config/event_connection.template.json`, una plantilla informativa desactivada.

Para retocar únicamente la vista 3D sin volver a ejecutar la simulación:

```bash
python3 scripts/greenfield_refresh_view.py artifacts/greenfield_04 --output-dir artifacts/greenfield_05
```

Abrir `artifacts/greenfield_05/index.html`: estructuras reforzadas, Inspection panel ampliado e inspector de componentes con hover/clic. El informe y los KPIs se reutilizan sin cambios.

Última demostración con ciclos corregidos: `artifacts/greenfield_06/index.html`. Incluye empujador con despeje/contacto modelados, chute conectado, retención del stack, circuito automático visible (`Watch cart cycle`) e imágenes de fabricante en las fichas. Ver `docs/greenfield_dual.md` para resultados, referencias y límites.

Vista actual: `artifacts/greenfield_07/index.html`. Retención de rejilla metálica, boca abierta del chute y dos carros de descarte fijos en los extremos. Se retiró el circuito de recogida de la escena. Los KPIs corresponden al nuevo lote simulado; ver `docs/greenfield_dual.md`.

Ajuste visual actual: `artifacts/greenfield_08/index.html` (chapa plana de unión y carros orientados hacia la descarga; mismo lote y KPIs de greenfield_07).

Última corrección: `artifacts/greenfield_09/index.html`. Plataforma plana de 730×600 mm conectada a la mesa; ambos carros con cara receptora abierta hacia el transportador. Incluye primeros planos en `artifacts/greenfield_09/verification/`.

Revisión mecánica actual: `artifacts/greenfield_11/index.html`. Indexado del paquete completo con sujeción superior, extracción de fila, accionamientos visibles, puentes/guías, palas rígidas y centrado de una desviación angular. Explicación de las transferencias y límites físicos: [docs/transfer_mechanics.md](docs/transfer_mechanics.md).

Revisión 11: ZPA sin cilindros de tope por zona, bastidor elevable y empujador independientes, cadena portacables articulada, accionamiento de salida por cremallera, descarte conectado y cesta rígida elevable con referencia Eichinger. Configuración de 24 zonas por tono: 3.530,974 conformes expedidos/h en el lote sintético; comparar 20/24/30 en `artifacts/greenfield_11/comparison.html`. Checkpoint previo `8683301`.

Revisión vigente: `artifacts/greenfield_12/index.html`. Ocho células, buffers de 20 zonas y mecanismos independientes. Estimación con arranque/frenado: 1.952 conformes expedidos/h; referencia nominal con otra hipótesis de movimiento: 3.602/h. Comparación de hardware, fuentes y límites: [docs/engineering_revision_12.md](docs/engineering_revision_12.md). Los apartados anteriores describen checkpoints históricos.

Vista actual: `artifacts/greenfield_13/index.html`. Liberación coordinada con reserva de frenado: 2.050/h estimados, +5,03 % con el mismo hardware. Objetivo de diseño: 3.000/h; referencia del mentor: 1.500/h. La revisión 12 sigue como punto de comparación.

Vista vigente: `artifacts/greenfield_14/index.html`. Sin pórticos de reserva: filas incrementales, bandas reversibles al nivel de la línea y reparto por acumulación. Estimación de referencia 2.218/h; tres distribuciones completadas. Explicación y límites: [docs/flow_optimization_14.md](docs/flow_optimization_14.md).

Revisión 15: `artifacts/greenfield_15/index.html`. Banda diagonal continua de descarte, sin parada intermedia: 2.264 conformes expedidos/h en el lote sintético. Checkpoint anterior `d56c3b7`. Ver [transferencia y alcance](docs/diagonal_transfer_15.md).


Última bajada de descarte: `artifacts/greenfield_16_final/index.html`, con pendiente real y sin ocho ascensores. Configuración: `config/greenfield_decline.json`. Ver [alcance y reproducción](docs/descending_discard_16.md).

Estudio de capacidad por capas: `artifacts/layer_repair_capacity_04/index.html`. Evalúa dos estaciones de inspección/corrección selectiva, conservando dehacking y apilado; incluye un carro completo de 28.800 ladrillos, repuestos y mezcla sin tres tonos iguales. Es un modelo de capacidad separado, no un caudal ya validado en el 3D. Ver [supuestos, resultados y referencias](docs/selective_layer_repair.md).


Demo vigente: `artifacts/greenfield_17_final/index.html`. Transporte continuo sin almacenes por tonos ni bandas de reserva; alimentación por filas y salidas fijas. Tres distribuciones completadas: 4.074–4.237 ladrillos conformes expedidos/h. El objetivo visible de 5.000/h sigue siendo un objetivo. Para generar un lote nuevo: `python3 scripts/greenfield_demo.py --output-dir artifacts/my_flow_demo`. Ver [apertura, cambios y verificación](docs/demo_flow_17.md).

Current visual update: `artifacts/greenfield_18/index.html`. See [supported transfers, inlet/outlet guides and verification](docs/visual_junctions_18.md). The recorded production run and KPIs are unchanged.

Latest junction cleanup: `artifacts/greenfield_19/index.html`; see [revision 19 checks and scope](docs/visual_junctions_19.md).

Latest recalculated demo: `artifacts/greenfield_20_checked/index.html`. [Guided transfers, manufacturer principles and verification](docs/guided_transfers_20.md). Estimated conforming shipped rate: 3,888.672 bricks/h for the revised synthetic cycle.

Current transfer-station demo: `artifacts/greenfield_21/index.html`. [Powered receiving transport, wider outlet, guided divert actuator and support checks](docs/transfer_station_21.md).

Current visual refinement: `artifacts/greenfield_22/index.html`. [Guided actuator mount and flared row entry](docs/guided_mount_22.md). Production timing is unchanged.

Latest separator fix: `artifacts/greenfield_23/index.html`; [visual correction and checks](docs/separator_fix_23.md).

Current loop seam correction: `artifacts/greenfield_24/index.html`; [continuous guide joints](docs/loop_rail_seams_24.md).

Current equipment-reference demo: `artifacts/greenfield_25/index.html`. [Official images, published specifications, custom integration scope and inspector verification](docs/equipment_inspector_25.md). Hover and click functional assemblies; production data and dashboard layout are unchanged.

Current executive demo: `artifacts/greenfield_26/index.html`. [Preserved production metrics, investment/energy scenarios, measured envelope and visual presentation](docs/executive_presentation_26.md). Estimated bricks/h remains 3,889; formed/h remains 4,166.
