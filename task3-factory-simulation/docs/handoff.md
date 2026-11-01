# Integración de persona 2 — propuesta v0.2

Esta propuesta permite probar la conexión sin cámara ni robot. Requiere acuerdo
con las otras personas; no representa una integración ya realizada.

## Reproducir el intercambio

Desde la raíz del repositorio:

```bash
python3 -m planning examples/handoff/inventory.json --config examples/handoff/config.json
python3 -m planning examples/handoff/inventory.json --config examples/handoff/config.json > artifacts/handoff_plan.json
```

Si `artifacts/` no existe, ejecutar primero `python3 -m planning.visualize`.
La salida del primer comando es JSON puro, utilizable por persona 3. En
`examples/handoff/plan.json` hay una referencia versionada generada con los
mismos archivos. La CLI devuelve 2 y no emite plan si no puede planificar.

## Persona 1 → planificación

- Entregar una instantánea con IDs únicos y estables (cadenas) y `color_group`.
- Publicar únicamente ladrillos disponibles para elegir. Un frame nuevo no
  debe reasignar el ID a un ladrillo distinto.
- `score` es opcional y actualmente se ignora. El filtrado de detecciones
  inciertas debe ocurrir antes de planificar; no existe un umbral implícito.
- Acordar categorías. No se exige que sean exactamente dark/medium/light,
  pero deben coincidir con la receta configurada.
- Las poses de recogida se mantienen en un registro externo indexado por ID.
  El planificador no necesita cámara ni coordenadas físicas.

## Planificación → persona 3

- Aceptar `schema_version="0.2"` y verificar dimensiones compatibles.
- Comprobar que todos los IDs siguen disponibles y reservarlos antes de ejecutar.
- Consumir `placements` por `step`, empezando en 1. `layer`, `row`, `column`
  empiezan en 0. Convertir la cuadrícula lógica al layout físico real.
- No interpretar la salida como trayectoria o certificación de estabilidad.
- Con `reject`, no ejecutar si la CLI falla o no llega un plan completo.
- Con `redistribute`, decidir explícitamente si se acepta la desviación publicada.

## Fallos y cambios de inventario — pendiente de implementar en integración

Propuesta de comportamiento: reservar el conjunto elegido, confirmar cada
colocación y actualizar inventario solo tras confirmación. Un pick fallido o un
ID desaparecido debe detener la secuencia y reconciliar inventario y pallet.
No volver a ejecutar ciegamente el mismo plan: podría duplicar colocaciones.

La API actual planifica pallets completos desde cero. No admite aún replanificar
un pallet parcial, versionar instantáneas, reservar stock ni confirmar pasos.
Estas capacidades se deben diseñar junto con persona 3 antes de conectar hardware.

## Checklist para la primera integración conjunta

1. Persona 1 produce la lista sin que cambiemos el planificador.
2. Persona 2 genera un plan completo sin duplicar IDs ni superar existencias.
3. Persona 3 consume los pasos en su simulación y registra cada confirmación.
4. Un inventario insuficiente produce rechazo sin comandos al robot.
5. Acordar un propietario de las reservas, cambios del contrato y recuperación.

Las demostraciones y visualizaciones se mantienen en inglés. La documentación
de coordinación puede estar en español.

## Banco de prueba disponible

`python3 -m demo` permite verificar ahora el intercambio con un ejecutor
simulado. Ver `integration_demo.md`. Las reservas y confirmaciones allí son
locales a la simulación: los acuerdos e implementación de integración real
indicados arriba siguen pendientes.
