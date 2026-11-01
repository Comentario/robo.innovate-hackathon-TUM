# Celda y contrato de ejecución — primera versión

## Objetivo

Convertir un plan lógico de persona 2 en acciones explícitas de un consumidor
sustituible. El ejemplo tiene zona de recogida, pallet y punto de referencia de
herramienta. Sus dimensiones, poses y giros son sintéticos. No define el brazo
del evento ni sustituye el trabajo de integración de persona 3.

## Sin ROS ni SDK

```bash
python3 -m execution
python3 -m execution --fail-step 5 --fail-phase orient --output artifacts/orient_failure.json
python3 -m execution --fail-step 5 --fail-phase pick --unknown --output artifacts/unknown_pick.json
```

La primera ejecución confirma 12 ladrillos, mediante 96 acciones. Los casos con
fallo terminan con código 3. Los informes incluyen job, comandos, confirmaciones,
stock disponible, ladrillo sostenido/colocado sin confirmar y estado incierto.
No iniciar otra ejecución para «reanudar»: siempre es una simulación nueva.

## Celda configurable

`config/cell.json` declara unidades en metros, frame, tamaño de ladrillo, origen
y separación de la cuadrícula de recogida, capacidad/origen/separación del pallet,
altura de aproximación, volumen de trabajo y mapa de orientaciones a cuaterniones.
El fixture supone ladrillos inicialmente alineados y erguidos. Actualmente solo
acepta yaw 0/180°; no se inventan giros para orientación sin mapa.

Las posiciones son centros de referencia del ladrillo, no poses TCP del robot.
Un adaptador físico deberá incorporar la transformación entre objeto y agarre.
Los IDs se ubican en una cuadrícula de recogida por el orden del inventario
sintético; las poses reales futuras vendrán de percepción y del registro de IDs.

## Preflight y límites

Antes de emitir acciones se comprueban contrato del plan, IDs/caras, capacidad,
mapas de orientación, solapamiento estático entre origen y destinos, tamaño y
límites de todos los waypoints. Las capas deben tocarse y estar alineadas.

Estos controles no comprueban alcance real del brazo, cinemática inversa,
trayectorias libres de colisión, estabilidad estructural ni contactos/agarre.
El volumen configurado es una caja ilustrativa, no una prueba de alcanzabilidad.

## Contrato sustituible

`compile_job(plan, inventory, cell_config)` produce comandos con `action_id`,
`step`, `brick_id`, `phase`, `frame`, `object_pose` y placement original. Job y
acciones tienen identificadores deterministas; no existe deduplicación persistente.

El adaptador implementa `perform(command) -> ActionResult` y declara `mode`.
La demo solo instancia `SimulatedAdapter` (`mode="simulation_only"`). Un futuro
adaptador SDK traducirá los comandos y reportará sus resultados; nunca cambia
las cuotas ni el patrón del módulo planning.

Cada ladrillo sigue:

```text
approach_pick → pick → lift → orient → approach_place → place → confirm → retreat
```

Resultados: `succeeded`, `failed_before_action` o `unknown`. Una excepción o
respuesta inválida se trata como incierta. Un timeout de SDK no es un fracaso
antes de actuar ni una confirmación. La sesión se detiene y exige reconciliación;
no hay reintentos automáticos, rollback ni recuperación de pallets parciales.

| Fallo inyectado | Estado conservado |
|---|---|
| Antes de pick 5 | 4 confirmados, quinto sigue disponible |
| Orientar o colocar el quinto, después del pick | 4 confirmados y quinto sostenido |
| Confirmar el quinto, después de place | 4 confirmados y quinto colocado sin confirmar |
| Resultado desconocido del pick | 4 confirmados y quinto incierto, no disponible |

Los eventos diferencian confirmaciones de órdenes emitidas. Es un contrato
síncrono inicial: el transporte de acciones asíncronas, cancelación, reservas
compartidas y persistencia requiere diseño con persona 3 y la plataforma real.

## Vista opcional de la celda en RViz

```bash
bash scripts/ros_preview.sh --cell config/cell.json --period 0.2
bash scripts/ros_preview.sh rviz-cell
```

Se ven dos mesas, stock de origen, ladrillos confirmados en destino, un marcador
cian de herramienta y una línea de waypoints. La herramienta se desplaza entre
estados reconocidos; no se interpola una trayectoria ni hay brazo articulado.
El color rojo señala detención; un ladrillo naranja en destino está sin confirmar.
La línea no es un camino comprobado contra colisiones.

Fallo después del agarre:

```bash
bash scripts/ros_preview.sh --cell config/cell.json --period 0.2 --fail-step 5 --fail-phase orient
```

Se conserva el quinto ladrillo como sostenido. Para resultado incierto se puede
usar `--unknown`. Cerrar el publicador anterior antes de iniciar otro sobre los
mismos topics. Mantenerlo abierto para conservar estado y TF en RViz.

## Próximo nivel

Elegir con persona 3 un brazo de referencia, obtener URDF/SRDF y pinza, resolver
TCP/poses reales y conectar planificación de movimiento (MoveIt u otro SDK).
La celda actual prepara esa frontera, pero no demuestra todavía un pick-and-place
físico ni una simulación de brazo con colisiones.
