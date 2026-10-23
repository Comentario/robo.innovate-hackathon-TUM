# Tarea 3: línea de dehacking en SimPy

Implementación independiente de tareas 1 y 2. No consume datos de persona 1 ni
controla un robot. Todas las etiquetas del visor están en inglés.

## Reproducir

Desde la raíz del repositorio, Python 3.10+:

```bash
python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt
python3 scripts/plant_demo.py --compare --output-dir artifacts/plant_line_01
```

Abrir `artifacts/plant_line_01/index.html`. No necesita servidor, Internet ni ROS.
La comparación está en `comparison.html`; cada escenario tiene su propio visor.
El lanzador se niega a sobrescribir una carpeta existente: usar otro nombre para
conservar la evidencia. El HTML es reproducción del modelo calculado; cambiar los
parámetros requiere editar una copia del JSON y ejecutar de nuevo con `--config`.
Play/Pause, velocidad, desplazamiento temporal, Restart, Final result y selector
del conjunto de dos capas permiten inspeccionar la ejecución. Las capas ocultas
no muestran colores antes de su inspección. Los sensores son señales virtuales.

Verificación independiente de los tests del planificador:

```bash
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_plant -v
```

## Proceso y límites físicos

1. Muelle carga un stack de entrada.
2. Dehacker retira un conjunto de dos capas (no corta físicamente ladrillos).
3. Transportador con capacidad finita alimenta un separador de capas.
4. El separador expone las dos capas en dos líneas de inspección.
5. Cada línea inspecciona y pide el robot compartido para retirar/reemplazar.
6. Ambas capas corregidas deben estar disponibles para volver a emparejarlas.
7. Transportador de salida entrega al reapilador, que completa pallets de 14 capas.

El transporte masivo usa mecanismos de capa idealizados. No está validada la
sujeción de una sola capa real, sus huecos/apoyos, masa/temperatura, alcance,
colisiones o resistencia. Se evalúa viabilidad temporal y flujo, no diseño mecánico.
La operación robot incluye retirada al rechazo y colocación desde suministro
aprobado; se reserva una pieza antes de retirar otra. El suministro es finito y
es del mismo producto. No se opera sobre toda la pila mediante picks individuales.

Las colas finitas `Store` y el límite de conjuntos simultáneos producen
contrapresión. Las dos líneas pueden inspeccionar simultáneamente; un recurso
`Resource` serializa las transacciones del robot. La variante de dos robots es
un supuesto de estaciones independientes, no dos brazos dentro de la misma zona
sin comprobación de interferencias. La mesa de emparejamiento se limita mediante
el máximo global de conjuntos en proceso. No se presupone orden FIFO entre pares
que tardan tiempos diferentes en corregirse; ambos tienen el mismo producto.

Cada ciclo emite presencia, sujeción, accionamiento, fin de carrera y confirmación
de transferencia. Son reconocimientos del modelo, no lectura de sensores reales
ni lógica PLC validada. El fallo configurado retiene fin de carrera, espera timeout
y detiene nuevos movimientos; las otras unidades conservan su ubicación en el
ledger. No hay reintento/reinicio automático después de ese fallo o de falta de
repuestos. Las retenciones no se liberan automáticamente al detener los drives.
No representa un sistema de seguridad certificado.

## Datos oficiales y supuestos

De `UTUM Brick Coloration.pdf`, diapositiva 18:

- Carro de horno: 28.800 ladrillos, 36 stacks de 800.
- Stack: 10 × 4 × 20. Capa: 40. Conjunto doble: 80.
- Ladrillo: 245 × 67 × 69 mm.
- Pallet de salida: 10 × 4 × 14 = 560.
- Caudal indicado: 1.500–3.000 ladrillos/h.

El JSON preserva esos datos; la demo ejecuta **dos stacks**, no el carro completo.
No es un flujo de un pallet de 800 a uno de 560: se acumula salida entre stacks.
1.600 de entrada con reemplazo uno a uno dan 2 pallets completos y 480 restantes.
Para simular todo el carro: `input_stacks: 36` y ampliar
`max_simulation_seconds` (por ejemplo 100000); contabilizará 51 pallets + 240.
El inicio de suministro es un intervalo de llegada después de t=0. Las tasas de
lote incluyen ese inicio y el vaciado final; no son estimadores rigurosos de
capacidad estacionaria ni prueba de mejora frente a humanos.

Todos los tiempos son supuestos modificables, incluso separación de capas,
inspección y picks industriales. Tasas de defecto/error y stock son sintéticos.
No se extraen ciclos cronometrando capturas sueltas del video. La primera demo
supone inspección perfecta, pero el escenario imperfecto permite falsos aceptados
y rechazados: el control usa decisiones simuladas de visión, nunca la calidad
latente para aprobar una salida. La calidad latente se usa para generar esas
observaciones y auditar los KPIs. No hay clasificación bajo oclusión.

## Producto y mezcla

Una corrida contiene un `product_id`: mismo producto, geometría y receta. No se
mezclan clientes/productos. Warm/Copper/Russet son tonos ilustrativos aceptados;
la receta de tercios es una hipótesis, no especificación ACME. Defecto y tono
aceptado son variables separadas. No se deduce una clasificación válida de fotos
del catálogo ni se reentrena/reclasifica el módulo de persona 1.

La elección de reemplazo favorece receta local y vecinos distintos. Con
`mixing_budget_per_layer: 0` no se cambian ladrillos ya aceptados. Eso **no garantiza**
una mezcla: las columnas monocromáticas y las capas estratificadas se reportan.
`input_pattern: stratified` expone el problema. Un presupuesto positivo permite
intercambiar buenos de tonos sobrerrepresentados, consume repuestos y ciclos, y
lleva los retirados a un buffer de reutilización contado. Ese buffer NO vuelve a
alimentar automáticamente el suministro. La heurística no garantiza ausencia
de filas/columnas uniformes, ni receta exacta (40 no es divisible entre 3).

Se reporta L1 por capa, filas/columnas monocromáticas y receta agregada de cada
pallet completo (`pallet_mix`). Una receta global correcta puede ocultar capas
mal distribuidas. Las estadísticas por capa incluyen capas corregidas que aún
no llegaron a salida si el escenario fue detenido: no comparar lotes incompletos
como si fueran completos. El informe conserva ese alcance.

## Comparación y KPIs

`--compare` produce ocho escenarios: base, alto rechazo, estratificado,
estratificado con intercambios, dos robots con alto rechazo, detector imperfecto,
falta de suministro y timeout del separador. Las comparaciones de capacidad usan
stock suficiente para no confundir velocidad con agotamiento; revisar los JSON
porque los stocks son parte de cada escenario. Semilla estable; las observaciones
por ID no cambian si se modifica la cantidad de robots.

Medimos producción total/conforme por hora, intervalo entre conjuntos, pallets
completos/parciales, fallos escapados, buenos descartados, uso/espera del robot,
bloqueo aguas abajo, inventario y distribución. A 3000/h hay 96 segundos por
conjunto doble. Exponer capas individuales no reduce automáticamente ese caudal:
lo determinan recursos, paralelismo y ciclos. No existe baseline humano medido,
por lo que todavía no se puede afirmar ahorro o aumento de producción real.

Balance global auditable por IDs únicos:

`input inicial + reserva inicial = salida + rechazo + reutilización + reserva restante + material pendiente/en proceso`

Los 800 y 560 no se fuerzan a coincidir ni se eliminan sobrantes. Incluso al
fallar hay ledger. `run.json` incluye parámetros/procedencia, eventos, posiciones
lógicas finales, IDs por pallet y estadísticas. El visor anima eventos de ese
mismo registro, no un guion independiente ni video generado.

## Próxima validación

Medir ciclos reales o pedir rangos al mentor, confirmar sujeción/separación de una
capa, caras que definen calidad, distribución de defectos/tonos por producto,
stock/reposición de buenos, disponibilidad, espacio de buffers y baseline humano.
Después: repeticiones con varias semillas, calentamiento/régimen estable,
intervalos de incertidumbre y política de mezcla entre capas con material reutilizable.

Referencias: https://simpy.readthedocs.io/en/stable/ y
https://simpy.readthedocs.io/en/stable/api_reference/simpy.resources.html.


## Verificación de esta implementación

- 89 tests existentes del núcleo: PASS.
- 10 tests de planta: conservación/IDs, pallets entre stacks, observación después
  de separación, sincronización de ambas capas, exclusión del robot, límite WIP,
  stockout, timeout, errores de visión, capacidad, mezcla y repetibilidad: PASS.
- Edge: inicio con capas no observadas, reproducción, desplazamiento temporal,
  reinicio, dos capas visibles mientras esperan, contadores finales, pantalla
  móvil y alarma del escenario de timeout: PASS.
- Evidencia local: `artifacts/plant_line_01/`, incluyendo `browser_verification.json`
  y captura real del navegador `viewer_midrun.png`.
- Demo seed 8: 1600 de salida, 177 reemplazos de calidad, 2 pallets de 560 y
  parcial de 480; 273 repuestos restantes; sin defectos escapados bajo detector
  perfecto. 2877.123 ladrillos/h incluyendo arranque/vaciado, con tiempos supuestos.
- Ocho escenarios generados; seis completan el lote y dos se detienen según diseño
  (stockout y timeout). Alto rechazo: 1250.543 ladrillos/h con un robot frente a
  2322.581 con dos bajo los mismos supuestos y suficiente stock. No demuestra
  alcance ni separación segura de dos robots reales.
- Estratificado: L1 medio de capa 1.102083; con intercambios presupuestados baja
  a 0.334166, pero el caudal baja de 2826.3 a 1163.636 ladrillos/h. Es un coste de
  esa heurística, no prueba de que mezclar siempre requiera ese coste industrial.
