# Marmon — Munich Hackathon 2026

Preparación para el reto #8: Intelligent Brick Blending and Palletizing.

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
