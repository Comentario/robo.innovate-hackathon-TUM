# Automatización y trazabilidad de tiempos — tarea 3

## Checkpoints

- `345c027` / etiqueta local `task3-3d-checkpoint`: primera escena 3D.
- `dc8cab1` / `task3-2d-checkpoint`: modelo y esquema 2D inicial.
- Los artefactos anteriores `plant_line_01` y `plant_3d_01` no se sobrescriben.

## Reproducir

```bash
python3 scripts/plant_demo.py --compare --output-dir artifacts/plant_automation_01
# Comparar otra configuración (otra carpeta para conservar evidencia):
python3 scripts/plant_demo.py --infeed-speed 0.25 --robot-speed 3 --output-dir artifacts/plant_automation_other
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_plant -v
```

Abrir `index.html`. La sección **Why this run takes this long** muestra carga por
estación y fórmula del caudal. **Cycle trace and distance / speed calculations**
muestra cada operación y las esperas explícitas; click en una fila para ir a ese
instante. **Engineering settings and occupancy interlocks** muestra velocidades,
pausas y permisos. Las entradas de configuración son supuestos de ingeniería,
NO mediciones de fábrica ni especificaciones oficiales del robot.

## Por qué dejó de dar 2006 segundos

La versión anterior asignaba duraciones globales (8 segundos para un movimiento,
3 para otro) y ajustaba las trayectorias a esos tiempos. En esta revisión:

- Los movimientos se planifican ANTES de ejecutarlos en SimPy.
- Cada submovimiento usa distancia / velocidad configurada.
- Ejes X/Z se desplazan simultáneamente: manda el tiempo del eje más lento.
- La aproximación/retracción vertical es una fase separada; el cabezal ya no
  baja en diagonal atravesando equipos.
- Agarre, liberación, exposición, inferencia y confirmación estable son pausas
  explícitas, con sus propias entradas en `automation`.
- SimPy consume esas mismas subfases y el visor reproduce sus trayectorias exactas.
- Un permiso ocupado inhibe el movimiento hasta liberarse. Las esperas también
  aparecen en el informe y en el trace del conjunto.

La antigua tabla `seconds` se retira del JSON operativo. Si aparece en una copia
vieja no determina el tiempo; la prueba de regresión confirma esa independencia.

Ejemplo de entrada: 5,5 m / 0,4 m/s = 13,75 s, más 0,2 s de estabilización =
13,95 s. El modelo usa velocidad constante; no introduce aceleraciones, masa,
inercia ni fricción. X/Z simultáneo significa `max(|dx|/vx, |dz|/vz)`, no la
longitud diagonal dividida por una velocidad vectorial.

El escenario base (semilla 8, mismos 1600 ladrillos) termina en 4235,7295 s:
`1600 × 3600 / 4235,7295 = 1359,86 ladrillos/h`. Hay 177 reemplazos de calidad y
354 transacciones de pick/place. El robot está activo aproximadamente el 95,9 %
del tiempo; es la mayor carga de trabajo. El resultado NO demuestra alcanzar la
demanda de entrada de 3000/h ni mejorar a los humanos. Es una predicción explicable
bajo velocidades/recorridos declarados, pendiente de medición y optimización.
No se ha ajustado ningún parámetro para forzar el resultado a 2006 segundos.

El tiempo global se mide sobre el reloj común. NO es la suma de las cargas de las
estaciones, porque se solapan. Las tasas incluyen arranque y vaciado del lote;
no equivalen a capacidad estacionaria. Los tiempos de operaciones son planificados;
en un escenario abortado los activos se recortan al instante de parada, mientras
los totales planificados de travel/dwell conservan la receta ordenada.
La primera liberación es configurable (`initial_arrival_s`, por defecto 0).

## Correcciones de layout y ocupación

1. Entrada alargada a 5,5 m de recorrido útil, con detección PE_IN al final.
2. Un único puesto físico de entrada reservado antes del dehacking. No se
   depositan varias parejas sobre la misma posición mientras esperan.
3. El separador necesita libres AMBAS entradas de las líneas de inspección.
4. Deposita cada capa en x=12; la faja la lleva a la cámara en x=13.
5. Tras inspección, avanza a x=14,4 para la corrección. El brazo ya no atraviesa
   la cámara o el panel de iluminación para coger un ladrillo.
6. Los huecos de unión se toman de un pool libre y se conservan hasta terminar
   el conjunto. No se asignan por módulo del ID (que podía reutilizar un hueco
   ocupado cuando los conjuntos acababan en distinto orden).
7. Hay permisos independientes para salida del emparejador y entrada del stacker.
8. Desplazamientos de muelle, retirada de pallet vacío y alimentación de vacío
   son movimientos explícitos. Los pallets siguen el mismo reloj que los ladrillos.
9. Corrección y emparejamiento tienen zonas separadas. El buffer de reutilización
   se mueve al lado opuesto del corrector para evitar el poste del separador.
10. Se ajustan profundidad y separación de las mordazas para no atravesar el
    ladrillo o el transportador en la representación geométrica.

Las posiciones están en `automation.LAYOUT`, y el visor recibe esa misma referencia
para los centros lógicos. La geometría estática corresponde a este layout.
El flujo permite estudiar más robots, pero la exportación 3D acepta solo UN robot
hasta diseñar y auditar otro workspace. En la comparación, se estudia velocidad
de ejes en lugar de dibujar dos robots sobre la misma estructura.

## Sensores, actuadores y secuencia

El panel muestra dos fuentes virtuales distintas, nombradas para no confundirlas:

- **PE_CAM_A/B, PE_CORR_A/B, PE_IN, PE_SEP, PE_OUT**: presencia calculada sobre las
  coordenadas actuales de los ladrillos en la escena. No se encienden solamente
  porque exista una orden de movimiento.
- **OCC**: ocupación lógica de estación en el proceso.
- **LS**: confirmación de final de la secuencia ordenada; puede fallar por timeout.
- **DRV**: orden de desplazamiento, apagada en pausas y esperas.
- **CLAMP**: estado lógico de sujeción. Se confirma después de la pausa de cierre.
- Límites virtuales de fuente, elevación, destino y home: se reinician al salir
  de una posición y se confirman al completar esa subfase.
- Permisos de entrada/salida: FREE, OCCUPIED o WAIT según la reserva del recurso.

La lógica espera la inspección antes de corregir y espera ambas capas antes de
emparejar. Fallo de confirmación o falta de suministro conservan inventario y
paran; no existe rearme automático. Esto es una secuencia virtual de automatización,
no PLC certificado ni medición de sensores físicos.

## Qué audita la comprobación geométrica

`clearance.py` aplica intersección continua de una caja alineada (cada ladrillo)
contra cajas de postes, rieles, cámaras y luminarias. Usa cada segmento lineal,
no únicamente capturas separadas. Una penetración detectada detiene la exportación
de la demo. Se conservan el resultado y el alcance en `mechanics.json`.

NO es un solver de colisiones de toda la celda: excluye cables, herramientas,
contactos entre ladrillos y dinámica. La ocupación de buffers se verifica además
mediante reservas exclusivas y pruebas de secuencia; eso no demuestra seguridad
industrial de una instalación física. Las superficies de apoyo no se tratan como
obstáculos de choque. Una auditoría geométrica favorable tampoco valida que una
pinza real sostenga una capa de ladrillos huecos.

La revisión inicial detectó una colisión REAL del modelo al llevar buenos al
buffer de reutilización. El exportador se negó a generar ese escenario; se
reubicó el buffer y se repitió la comprobación, en lugar de ocultar el fallo.

## Evidencia

24 contratos iniciales de proceso/automatización/mecánica, más regresión de la
ruta de reutilización, y 89 pruebas existentes del núcleo. `run.json` incluye
`automation.timing`: subfases, distancias, velocidades, pausas, operaciones,
esperas y cargas. `mechanics.json` incluye auditorías de continuidad y estructura.
Las capturas de Edge y `automation_browser_verification.json` comprueban WebGL
offline, tiempo/velocidad de la faja, presencia en cámara frente a corrección,
unión pinza/pieza, trace y timeout. Las pruebas numéricas NO son validación de hardware.
