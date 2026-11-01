# Persona 2 — decisiones y pendientes

## Interpretación

El roadmap pide equilibrio visual por filas/capas y evitar acumulaciones del
mismo tono. No establece que el color indique marca o calidad, ni explica el
objetivo industrial exacto. Confirmarlo con el enunciado oficial.

## MVP

- `blend_planner`: asignación incremental por déficit respecto al objetivo,
  limitada por existencias. Determinista; sin optimización avanzada.
- `pallet_pattern_planner`: asignación voraz que prioriza evitar vecinos del
  mismo tono y después el equilibrio de fila/capa respecto a la mezcla elegida.
- `placement_sequence_planner`: orden por capas, filas y columnas; IDs únicos.

La heurística no garantiza ausencia de agrupamientos ni un óptimo global.
Las métricas permiten distinguir un plan válido de una buena mezcla visual.
Sin una receta explícita se preserva la proporción disponible; una mezcla de
tercios es solo un ejemplo de configuración, no un requisito del reto.

## Antes de integrar

Acordar con persona 1 IDs, categorías, disponibilidad y actualización del inventario.
Acordar con persona 3 contrato, reservas de ladrillos, fallos y replanificación.
Confirmar dimensiones, orientación de ladrillos, capacidad, tolerancia de color,
receta objetivo y criterio de evaluación oficial. La geometría de capas
alternadas y estabilidad física quedan pendientes del hardware/enunciado.

No se ha probado con cámara ni robot. El dataset es sintético.

## Actualización tras consultar la fuente oficial

La motivación industrial y las políticas nuevas están en `mixing_criteria.md`.
La API sigue admitiendo la estrategia inicial y añade mezcla suave configurable.
La salida evoluciona a v0.2; coordinar su adopción antes de integrar.

## Equilibrio local y adaptadores

Mixed asigna ahora cuotas por capa y fila. Las métricas separan desviación de
receta y distribución de la mezcla disponible. ROS 2 se ofrece como transporte
opcional y vista RViz; el núcleo no importa ROS ni depende de un SDK de robot.
