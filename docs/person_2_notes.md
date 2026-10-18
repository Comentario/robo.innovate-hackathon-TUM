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
