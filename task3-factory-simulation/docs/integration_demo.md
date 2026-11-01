# Prueba de integración sin hardware

Esta demo de persona 2 permite comprobar el contrato mientras no estén disponibles
los módulos reales de las personas 1 y 3. Su ejecutor es sustituible y no sustituye
al orquestador definitivo. No abre conexiones al robot ni modifica stock compartido.
Todos los mensajes de la demo están en inglés.

## Ejecutar desde la raíz

```bash
python3 -m demo
python3 -m demo --fail-step 5 --output artifacts/dry_run_failure.json
```

El primer comando termina con código 0, `Status: completed` y 12 confirmaciones.
El segundo termina intencionadamente con código 3, `Status: stopped` y 4
confirmaciones. El fallo se inyecta antes de recoger el ladrillo del paso 5.
En el JSON permanecen los otros 8 ladrillos y los eventos de detención/liberación
simulados. No ejecutar este segundo comando con `&&` si se quiere seguir con
otras comprobaciones: el código 3 indica la detención esperada.

Opciones: `--inventory PATH`, `--config PATH`, `--output PATH`, `--fail-step N`.
Código 2: entrada inválida o rechazo del plan. Si falta inventario, el informe
contiene `status="rejected"`, ninguna confirmación y ningún evento de ejecución.

## Límites comprobados

- Instantánea de inventario → planificador real → consumidor simulado.
- Validación previa de versión, dimensiones, orden, IDs, categorías y cantidades.
- Reserva simulada del conjunto elegido antes de confirmar colocaciones.
- Retirada del inventario simulado únicamente tras confirmar cada colocación.
- Detención inmediata ante fallo; registro de confirmaciones y stock restante.
- Los datos de entrada no se modifican y no se contacta hardware.

El validador de la demo comprueba coherencia del contrato, no autorización,
calidad visual, geometría física, límites de la celda ni trayectorias.
Cada ejecución comienza desde una instantánea nueva: no hay persistencia de
reservas, bloqueo compartido, reanudación ni replanificación de pallets parciales.
El JSON es evidencia de la simulación, no una instrucción para repetir picks.

## Sustituir los extremos con el equipo

Persona 1 debe producir un inventario compatible; se sustituye el archivo de
ejemplo con `--inventory`. Persona 3 puede usar `validate_plan(plan, inventory)`
como referencia de las comprobaciones de consumo, manteniendo sus propios
contratos físicos. Antes de hardware hay que acordar quién reserva, cómo se
identifican instantáneas y cómo se reconcilia un fallo real (que podría haber
ocurrido después del pick, a diferencia del fallo controlado de esta demo).
