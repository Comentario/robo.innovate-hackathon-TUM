# Integración de personas 2 y 3

Asumimos planificación y ejecución/integración. Persona 1 sigue desarrollando
percepción. Hasta recibir su formato, usamos una instantánea canónica versionada
y un productor sintético explícito; no simulamos haber conectado su módulo.

## Entrega esperada de percepción

`examples/perception/snapshot.json` es un ejemplo del contrato:
`schema_version="inventory-snapshot-0.1"`, `snapshot_id` único, `source` synthetic
(o perception), `face_aware` booleano e `items` con el inventario actual. El
adaptador de persona 1 convertirá su formato a este contrato; no se requiere que
cambie su detector. IDs numéricos se convierten explícitamente antes de ingresar.

Un dataset o una NN puede producir el mismo contrato. Con `face_aware=false`
se consumen categorías por ladrillo. Con true se consumen caras observadas y
orientaciones declaradas; no se inventan caras ocultas. `score`, si existe, debe
estar entre 0 y 1, pero no existe un filtro de confianza implícito.

Para planificar basta el inventario. Para ejecutar un snapshot source=perception
se exigen `units="m"`, `frame` igual al de la celda y `source_poses`, un mapa de
cada ID a `position_m` y `orientation_xyzw`. Cajas en píxeles no son poses en
metros. La transformación cámara/celda se debe implementar explícitamente. Solo
source=synthetic permite inventar una cuadrícula de recogida de demostración.

## Ejecutar y reabrir un estado

```bash
python3 -m integration plan --snapshot examples/perception/snapshot.json
python3 -m integration run --state artifacts/persona23.sqlite3 --pause-after 10
python3 -m integration resume --state artifacts/persona23.sqlite3
python3 -m integration inspect --state artifacts/persona23.sqlite3
```

Run confirma la instantánea, planifica, valida geometría, reserva IDs y ejecuta
con el adaptador simulado. Los reportes JSON y HTML en inglés se guardan por
run_id en artifacts/integration/. La pausa devuelve código 4; completado 0;
fallo detenido 3; entrada/estado inválido 2; observación final discrepante 5.

La restauración automática es únicamente para simulación pausada entre acciones
ya reconocidas. Conserva cursor, stock, ladrillo sostenido y confirmaciones, sin
repetir acciones previas. No reinicia automáticamente ejecuciones detenidas por
fallo ni admite restauración física automática.

## Registro persistente y límites

SQLite reserva una celda/ciclo y los IDs seleccionados. Se registra la acción
pendiente ANTES de llamar al adaptador; después se guarda reconocimiento y estado.
Si el proceso cae en ese intervalo, inspect muestra dispatch_unacknowledged y
resume se rechaza. Es necesaria reconciliación de inventario, pinza y pallet.
Un emisor no puede reutilizar el snapshot ni un segundo ejecutor usar un estado
anterior para emitir la misma acción.

Es un journal local de un ciclo de celda. No es una reserva distribuida, una
cola de producción ni una garantía de exactly-once en un SDK. No hay reset físico
ni reconciliación automática. Tras completar un ciclo se conserva la ocupación
para impedir otro pallet encima del existente. Para repetir fixtures sintéticos
se puede elegir OTRO archivo --state: eso representa una celda simulada vacía.
No usar ese procedimiento para eludir el estado de una celda real.

## Validación final separada de las confirmaciones

Sin cámara/observación independiente el informe muestra awaiting_observation,
aunque todas las acciones estén confirmadas. La evidencia final requiere:

```json
{
  "schema_version": "pallet-observation-0.1",
  "observation_id": "observation-001",
  "run_id": "ID_DEL_INFORME",
  "plan_digest": "DIGEST_DEL_INFORME",
  "source": "perception",
  "placements": [
    {"layer": 0, "row": 0, "column": 0, "brick_id": "brick_001", "color_group": "dark", "visible_face": "front"}
  ]
}
```

El ejemplo es parcial, no pasará como pallet completo. El validador detecta
posiciones faltantes/extra/duplicadas, IDs, tonos y caras incorrectos, y rechaza
evidencia de otro plan/run. Guarda observaciones sin permitir alterar un ID ya
registrado. Campos source reflejan la declaración del productor, sin autenticarla.

```bash
python3 -m integration validate --state artifacts/persona23.sqlite3 --observations final_observations.json
```

No generar esa evidencia copiando el plan y presentándola como percepción. Para
probar el validador se usa source=synthetic y el reporte lo indica expresamente.
Las caras inferiores ocultas pueden requerir observaciones acumuladas por paso;
no se consideran observadas solo porque su posición estaba planificada.

## Estado que sigue pendiente

Entrega real de persona 1, ajuste del adaptador a su formato, calibración y poses,
observación final real, brazo de referencia/IK/colisiones, adaptador del SDK real,
reservas de producción y reconciliación/replanificación del pallet parcial.

## El mismo journal en RViz

```bash
bash scripts/ros_preview.sh --snapshot examples/perception/snapshot.json --cell config/cell.json --state artifacts/persona23.sqlite3 --period 0.2
bash scripts/ros_preview.sh rviz-cell
```

Si el journal está vacío, se crea un ciclo y cada acción pasa por el registro
persistente antes de reconocerse. Si ya existe, se restaura SOLO la vista del
último estado sintético, sin emitir acciones. Las nuevas solicitudes sobre esa
celda se rechazan sin borrar el pallet conocido. La restauración no implica
reconciliación física; nunca se ejecuta automáticamente un checkpoint hardware.

Para reanudar una simulación pausada usar el comando integration resume indicado
arriba, y volver a abrir la vista para cargar su estado actualizado. Cerrar el
publicador previo antes de iniciar otro con los mismos topics. La cadencia de
publicación cede tiempo entre acciones para guardar estado y entregar mensajes.
