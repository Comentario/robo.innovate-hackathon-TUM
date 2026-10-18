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
