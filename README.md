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
