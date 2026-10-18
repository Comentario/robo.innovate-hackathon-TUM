# Recuperación articulada con Panda y MoveIt

Para el ensayo habitual con arranque y cierre automáticos, usar el [lanzador único](rehearsal.md). Los comandos siguientes permiten manejar servidor y cliente por separado.

Esta demo conecta la reconciliación del pallet parcial con el adaptador Panda.
Continúa usando únicamente la maqueta cinemática y el inventario sintético;
no incorpora percepción de persona 1 ni controla hardware.

## Reproducir

Desde la raíz, con las dependencias de `reference_arm.md` preparadas:

```bash
# Terminal 1: escena inicialmente vacía y RViz.
scripts/arm_demo.sh launch

# Terminal 2: usar un directorio nuevo; nunca sobrescribir un journal anterior.
scripts/arm_demo.sh recovery --output-dir artifacts/panda_recovery_new \
  --speed 3 --pause 8 --hold 1800
```

`--speed 1` muestra la duración normal de las trayectorias. El servidor debe
estar recién iniciado al comenzar este ensayo completo. Durante la recuperación
interna **no se reinicia MoveIt ni se vacía el pallet**. Se destruye y reconstruye
el cliente Python para probar que puede recuperar su estado sin volver a READY.

## Secuencia visible

1. El brazo coloca cuatro piezas completas y se detiene antes de mover la quinta.
   La demo inyecta un resultado incierto, no un choque físico ni un agarre real.
2. Guarda el checkpoint de articulaciones, objetos, adjuntos y escena de colisión.
3. Reconstruye el cliente desde MoveIt y contrasta la escena con ese checkpoint.
   No publica READY ni recoloca los ladrillos en sus posiciones iniciales.
4. Comprueba pinza abierta, ausencia de adjuntos, articulaciones coherentes y
   validez por colisiones. Registra el intento antes de ejecutar una trayectoria
   MoveIt a la posición segura configurada.
5. Obtiene de la escena las poses de las piezas, reconoce el prefijo colocado y
   genera la propuesta de recuperación. Las cuatro posiciones quedan señaladas
   mediante contornos verdes sin alterar el tono del ladrillo.
6. Crea un run hijo Panda y ejecuta las 64 acciones de los pasos 5–12. Cada
   objetivo usa IK con colisiones y planificación OMPL; las trayectorias se
   reproducen de forma continua como en la demo habitual.
7. Comprueba que las cuatro geometrías preservadas no cambiaron y conserva la
   historia del run padre. La validación final sigue awaiting_observation.

Puede haber pausas de cálculo entre trayectorias. Los intentos de planificación
rechazados se recalculan como máximo tres veces **antes de mover**; nunca se
reenvía una acción ejecutada o de resultado incierto. Si un plan no se obtiene,
el ciclo se detiene y conserva la escena alcanzada.

## Puertas de verificación

- `Journal.recover_simulation` sigue admitiendo solamente el simulador lógico.
- `Journal.recover_reference_simulation` exige el adaptador concreto Panda en
  modo simulation_only y que el run padre tenga ese mismo backend.
- La preparación de posición segura tiene un registro previo persistente.
  Timeout, excepción o caída dejan un resultado incierto que no se reintenta.
- El hash de escena incluye posiciones articulares, pinza, objetos, geometría,
  adjuntos, matriz de colisiones, transformaciones y octomap. Se ignoran solo
  stamps de headers; no las poses ni objetos cuyo identificador sea stamp.
- Las poses de MoveIt se componen como objeto × forma: no se interpreta una
  pose relativa de la caja como una posición absoluta en el origen.
- La reconciliación se vuelve a consultar contra la escena actual, además de
  comprobar run, plan, checkpoint y propuesta. Una diferencia bloquea el hijo.
- El run hijo pasa por awaiting_reference_activation antes de quedar listo.
  Si su activación falla, queda stopped con cursor cero; no se despachan tareas.
  Una caída durante esa fase exige inspección, no reanudación automática.
- Un ejecutor padre o un reconocimiento tardío no pueden recuperar el control
  del ciclo transferido al hijo.

El hash no autentica un sensor ni convierte el modelo en evidencia física. Este
flujo conoce las caras/tonos por el fixture y lee posiciones del simulador, no
por una cámara. La pinza abierta es una configuración articular, no una medición
independiente de que no haya un objeto real dentro.

## Archivos producidos

- `state.sqlite3`: padre, hijo, reservas, checkpoint y preparación Panda.
- `stopped_run.json` y `robot_checkpoint.json`: estado previo a la restauración.
- `restored_scene.json`: escena reconstruida antes de mover a posición segura.
- `home_preparation.json`: resultado del movimiento de recuperación auditado.
- `reconciliation.json` y `proposal.json`: evidencia sintética y tareas pendientes.
- `final_scene.json`, `result.json` e `index.html`: comprobación final, trayectorias
  y reporte en inglés. Se generan cuando acaba el ensayo, incluso si el hijo se
  detiene por un rechazo de planificación posterior.

Los artefactos se ignoran por Git; los ensayos fallidos se conservan. Para otro
ensayo completo se elige un directorio nuevo y se reinicia el servidor.

## Límites

La reconstrucción recupera el cliente mientras MoveIt conserva su escena. No
restaura un mundo perdido por caída del servidor ni un robot físico desde JSON.
La demo parte de una parada antes del quinto pick y sin objeto adjunto. Si hay
una pieza sostenida, pinza cerrada, geometría perdida o estado en colisión,
bloquea el movimiento: no inventa una maniobra para soltarla.

La sustitución de piezas faltantes permanece disponible en el simulador lógico.
Esta demo articulada conserva el mismo inventario y exige que todas las piezas
conocidas sigan presentes en la escena. SDK real, sensores, cancelación de una
trayectoria física en curso y recuperación de una pieza sostenida requieren un
adaptador y procedimientos propios del equipo del evento.

## Evidencia de esta entrega

El ensayo `artifacts/panda_recovery_03` terminó con 12 posiciones confirmadas,
4 geometrías preservadas sin cambios y 64 acciones nuevas. El hijo planificó
56 trayectorias con resultado MoveIt SUCCESS; la vuelta a posición segura
se registró por separado. El checkpoint anterior a la reconstrucción coincide
con la escena restaurada y el historial del padre permanece intacto.

Pasaron 67 pruebas del núcleo, 11 del adaptador Panda y 10 de transporte ROS
(88 en total). Los tests incluyen cambios de escena, pinza ocupada, poses
compuestas, preparación sin respuesta, activación fallida y selección de
objetivos IK con colisiones. Las pruebas de contrato usan stubs; el ensayo
articulado completo se ejecutó además con MoveIt y RViz.

Informe local: `artifacts/panda_recovery_03/index.html`.
Captura: `artifacts/panda_recovery_03/rviz_recovery.png`.
Comprobaciones: `artifacts/panda_recovery_03/verification.json`.
Los ensayos anteriores se conservan para diagnóstico y no se presentan como
recuperaciones completas satisfactorias.
