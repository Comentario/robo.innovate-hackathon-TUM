# Brazo de referencia: Panda + MoveIt 2

Para el ensayo habitual con arranque y cierre automáticos, usar el [lanzador único](rehearsal.md). Los comandos siguientes permiten manejar servidor y cliente por separado.

Esta prueba cubre la preparación de persona 3 sin integrar percepción de persona 1.
Reutiliza el planificador, las ocho acciones por ladrillo y el journal existentes.
El adaptador opcional convierte centros de ladrillo a poses de `panda_hand`, pide
trayectorias a MoveIt/OMPL y reproduce sus articulaciones en RViz.

Es simulación cinemática: no hay dinámica de contacto, controlador real ni
verificación física del agarre. `confirm` comprueba el estado sintético de la
escena; el resultado continúa pendiente de una observación independiente.

## Reproducir

Requisitos de esta máquina: Ubuntu 22.04, ROS 2 Humble y RViz instalados.
Desde la raíz del nuevo repositorio:

```bash
# Una vez: descarga y extracción local, sin sudo ni instalación del sistema.
python3 scripts/install_local_moveit.py

# Terminal 1: servidor de planificación y RViz, dominio ROS 88.
scripts/arm_demo.sh launch

# Terminal 2: un ciclo NUEVO; usar una ruta de journal que aún no tenga ciclo.
scripts/arm_demo.sh --state artifacts/panda_cycle_01.sqlite3 \
  --output artifacts/panda_cycle_01.json --probes --speed 8 --hold 3600
```

Verás un Panda articulado, una pinza y dos soportes con ladrillos pequeños.
El brazo traslada las piezas desde la zona de recogida al pallet con la receta
`mixed`. `--speed` acelera solamente la reproducción visual. `--hold` conserva la
publicación del resultado al terminar; Ctrl+C cierra el cliente. Para otro ciclo,
cierra y vuelve a arrancar también el servidor: no restaures una escena parcial
como si fuese un pallet vacío. Los bloqueos impiden clientes/servidores duplicados.

El proceso rechaza un journal ocupado antes de cambiar la escena y rechaza
una escena que contenga objetos de un ciclo anterior. Esta CLI básica no implementa
reanudación del brazo: un fallo, timeout o despacho sin respuesta requiere revisar
el checkpoint. No usar `integration resume` para mover este brazo ni borrar un
journal para ocultar un fallo. Los ensayos fallidos se conservan para diagnóstico.

El informe convencional de integración también puede leer este journal:

```bash
python3 -m integration inspect --state artifacts/panda_cycle_01.sqlite3 \
  --output artifacts/panda_cycle_01_status.json
scripts/arm_demo.sh test
```

## Qué comprueba

- Estado inicial y trayectorias planificadas con las geometrías de colisión del
  Panda, soportes, piezas restantes y objeto adjunto a la pinza.
- Conservación de las exclusiones de autocolisión del modelo. Únicamente la pieza
  seleccionada puede tocar los enlaces declarados de la pinza.
- Apertura/cierre sintéticos con seis estados intermedios comprobados.
- Cinemática directa del extremo tras cada trayectoria: error de posición máximo
  de 4 mm respecto al objetivo de referencia; orientación restringida por MoveIt.
- Objetivos negativos con `--probes`: punto a 2 m del brazo y objetivo bloqueado
  por una caja. No se reproducen sus trayectorias.
- Hasta tres intentos de planificación de un camino rechazado, antes de mover.
  No se repite una acción ya despachada o detenida.
- Journal previo al despacho y reconocimiento explícito. Un rechazo de
  planificación conserva lo colocado; una excepción posterior al movimiento se
  trata como resultado incierto.

MoveIt comprueba colisiones con su resolución de planificación; esto no sustituye
una comprobación industrial continua, calibración ni pruebas físicas. La pose
alcanzada se obtiene del modelo articulado, no de un sensor externo.

## Parámetros y sustitución por otro robot

`config/cell_panda.json` usa piezas SINTÉTICAS de 60 × 25 × 20 mm, separación para
la pinza y soportes con 5 mm de holgura geométrica bajo las piezas. Es una maqueta
para probar interfaces y movimiento, no una especificación de los ladrillos del
reto. El pallet no está compactado y no se evalúa su estabilidad física.

`reference_arm.supports` configura las cajas de colisión y sus marcadores;
`reference_arm.grasp_offset_m` define la distancia mano-centro del objeto. La base
es fija, frame `world`, agarres verticales y yaw de 0/180°. El robot de referencia
sigue siendo Panda: otro brazo necesita URDF/SRDF, límites, cinemática y calibración
del agarre propios. No se adapta cambiando únicamente el nombre del robot.

El planificador no importa ROS. `arm_bridge/adapter.py` implementa
`ExecutionAdapter.perform()` y declara `simulation_only`. Un SDK del evento
sustituirá este adaptador, conservando planificación, contratos y journal; deberá
reconocer acciones reales y devolver `unknown` ante falta de confirmación.

Dependencias extraídas en `.deps/moveit`, ignoradas por Git. El manifiesto local
registra versiones y SHA-256; el instalador usa índices privados actualizados y
rechaza planes APT que eliminen o actualicen paquetes ya instalados. No ejecuta
scripts de instalación Debian ni modifica `/opt/ros/humble`.

Referencia oficial de MoveIt Humble:
https://moveit.picknik.ai/humble/doc/tutorials/quickstart_in_rviz/quickstart_in_rviz_tutorial.html

La tolerancia de desviación de la temporización OMPL se limita a 0,001 rad y la
resolución de segmentos a 0,001 del espacio articular; se conserva el rechazo
final de trayectorias inválidas. Referencia del algoritmo de temporización:
https://moveit.picknik.ai/humble/api/html/classtrajectory__processing_1_1TimeOptimalTrajectoryGeneration.html

## Evidencia local de la prueba completa

El ciclo `artifacts/panda_cycle_v2.sqlite3` terminó con 12 colocaciones y 96
acciones reconocidas. Sus 84 trayectorias tuvieron error MoveIt SUCCESS; el error
máximo de posición calculado mediante FK fue 1,99 mm. Ambos objetivos negativos
fueron rechazados. Informe: `artifacts/panda_cycle_v2_status.html`; evidencia
articular: `artifacts/panda_cycle_v2.json`; captura: `artifacts/panda_completed.png`.
Los artefactos locales no se versionan y se conservan los journals fallidos.

Los tests ROS usan el dominio 89, separado de la demo original (87) y Panda
(88). Las primeras comprobaciones compartían el dominio de la demo anterior y
sufrieron timeouts; las pruebas durables aisladas pasaron en 7,8 s conservando
los límites y las comprobaciones originales. No se rebaja la durabilidad SQLite.

## Reproducción visual continua

El muestreo de las trayectorias usa una única línea temporal monotónica y un
publicador de articulaciones a 50 Hz. Se conservan los tiempos de MoveIt;
`--speed 1` reproduce duración normal. Las marcas TF visuales avanzan con tiempo
monotónico anclado al instante inicial para evitar que correcciones del reloj de
WSL hagan que RViz descarte movimientos anteriores. No se cambia el reloj de
planificación de MoveIt.

La pieza agarrada usa `frame_locked` en `panda_hand`: RViz vuelve a aplicar su
transformación en cada fotograma. La pinza abre y cierra durante 0,7 s, después
de comprobar las posiciones intermedias, sin publicar esos estados de prueba.
La publicación Fast DDS es asíncrona y RViz se configura a 30 FPS. Esto sigue
siendo simulación cinemática; hay pausas reales al calcular cada trayectoria,
pero no se sustituyen los transportes por cambios instantáneos de posición.

Los eventos e informes incluyen `playback`: duración, número de actualizaciones
y separación máxima entre ellas. La primera trayectoria de la prueba local
`panda_smooth_01` publicó 204 actualizaciones en 4,47 s, con separación máxima de
33 ms. En esa prueba no se observaron avisos `TF_OLD_DATA` al verificar el inicio.

Para la demo de recuperación explícita con reconstrucción del cliente, consultar
`reference_arm_recovery.md`. Esa vía verifica la escena antes de continuar y no
utiliza `integration resume` ni reconocimientos del simulador lógico.
