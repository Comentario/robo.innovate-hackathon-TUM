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
