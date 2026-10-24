# Dos líneas de cuatro células: alimentación, descarte y salida compartida

Punto de retorno anterior: **`6e912e2`**, `artifacts/greenfield_03/index.html`. Se conservan sus archivos e informes. Esta versión mantiene ocho células y cambia la logística, sin tocar la percepción de persona 1.

```bash
python3 scripts/greenfield_demo.py --compare --output-dir artifacts/greenfield_04
```

Abrir `artifacts/greenfield_04/index.html`. La configuración nueva está en `config/greenfield_dual.json`. El modelo de células sigue en `greenfield/model.py`; los procesos de planta paralelos están en `greenfield/twin.py`. La configuración anterior `config/greenfield.json` sigue permitiendo reproducir el prototipo de una línea.

## Flujo representado

1. Un carro de transferencia por raíles llega desde inventario con cuatro stacks de 800 piezas. Es un **lote de demostración**, no el kiln cart industrial completo de 36 stacks. Las interfaces por stack de entrada y por pallet de salida mantienen 800 y 560 piezas.
2. Un puente compartido recoge cada stack completo introduciendo las horquillas por un lateral del pallet. Las horquillas bajan fuera de la carga, entran por los huecos de la madera, elevan el stack, lo trasladan y lo depositan en el dock A o B. No atraviesan los ladrillos al bajar. El recorrido elevado deja la carga por encima de los pórticos locales. Los dehackers se aparcan fuera del volumen de entrega.
3. Cada dehacker atiende solamente dos mesas distribuidoras y cuatro células. A y B tienen recursos y trayectorias independientes: pueden operar simultáneamente.
4. Las ocho células conservan detección, acumulación por tonos y formación incremental de filas. Se ha acortado el cuerpo del shuttle para que no invada la siguiente mesa, añadido el puente de rodillos antes de Inspection y representado el pusher con guía transversal, cilindro fijo, vástago y pala. La pala se aproxima hasta contacto antes de mover el ladrillo y se retira antes de atravesar la fila.
5. Cada línea tiene su propio Guided Palletizing. El primer pallet de madera se alimenta y **sube al plano de soporte antes de la primera capa**. Después desciende con cada capa. Los marcos de guía son abiertos para que se vean las capas.
6. Cada pallet terminado pasa a un buffer de salida de su línea. Una reserva de acceso permite que ambos buffers reciban material sin conducir dos pallets al mismo punto. Un shuttle común recoge uno, cruza hasta la posición libre del carro de expedición y lo descarga sobre un tramo de rodillos.
7. El carro común reúne los pallets completos en cuatro posiciones y sale por sus raíles a producto terminado. Si el lote acaba con menos de cuatro pallets completos, también se despacha ese carro parcialmente ocupado. **Un pallet de ladrillos incompleto nunca se declara entregado.**

El merge es exclusivo en el punto compartido. La producción A/B sí es paralela; no se simula que dos cargas puedan ocupar físicamente el mismo shuttle a la vez. Su espera se incluye en el tiempo final.

## Recorridos y producción

Con la geometría actual, la separación máxima entre el centro del stack y una bandeja local baja de aproximadamente 12,55 m a 4,55 m; el apilador trabaja hasta unos 6 m lateralmente desde su centro, frente a unos 14 m en el esquema anterior. Estos son recorridos geométricos, no promesas de duplicar el caudal: el puente de inventario, la inspección, las reservas y el merge siguen limitando el sistema.

La comparación mantiene ocho células. Incluye el modelo anterior —con logística diferente, identificado como tal—, puente más lento, servicio de descarga más largo, una célula aislada, rechazo elevado, indisponibilidad de recogida y falta de confirmación de capa. Los resultados detenidos no son capacidades comparables.

## Un solo descarte oficial

Antes, `reject` identificaba una pieza observada fuera de criterio y `quarantine` una observación que seguía siendo incierta después de la segunda captura. La segunda **no era una pieza aprobada ni volvía automáticamente a producción**.

Ahora ambas siguen **la misma ruta física de descarte**. La diferencia se guarda únicamente como motivo, sin dos pilas de colores. Un empujador envía la pieza por un chute guiado a los transportadores de recogida de su línea. Sus zonas se reservan antes de avanzar; los dos sentidos de llegada comparten un único acceso al carro.

Cada línea tiene un carro receptor y carros de reserva. El límite operativo es 120 piezas, no un suministro infinito. Al llegar al límite:

- se bloquea temporalmente la recepción;
- se cierra el portillo y se retira el carro cargado por el carril de servicio;
- entra un carro vacío y se confirma su presencia;
- el carro retirado llega al área de descarga, se vacía mediante un servicio temporizado y vuelve vacío a la cola de reservas.

La cola es FIFO y se compacta bajo exclusión mutua: ningún carro atraviesa a otro. Si no hay un carro de reserva libre, la recepción espera el retorno de uno. Si el servicio de recogida está indisponible, el sistema entra en paro protegido. Los ladrillos se conservan por identidad y motivo; no se reclasifican como buenos.

El mentor describió transporte manual de estos carros. Aquí se representa como **logística auxiliar programada**, compatible con ese servicio; no es una estación humana de clasificación. Los 20 s de descarga y velocidades de traslado son hipótesis configurables, pendientes de medir. El acomodo dentro del carro y la descarga dentro del recinto cerrado se abstraen: no se afirma simular caída, fricción o manipulación humana individual.

## Representación visual

- Sensores con postes y escuadras unidos al bastidor, receptores y haces rojos de referencia. Los haces son una ayuda gráfica; no se afirma que la radiación infrarroja real sea visible.
- Cámara fijada al pórtico y paneles de iluminación. El panel **Inspection cameras** está plegado en la barra lateral y se abre con clic; no depende de acertar a un objeto 3D. Line A / Line B y el selector de cámara permiten revisar las ocho posiciones.
- Empujadores ligados a guías/cilindros y shuttles con carros, ruedas y raíles soportados. Las holguras entre transportadores se representan sin mesas superpuestas.
- Etiquetas por línea en azul y ámbar. El botón alterna **stages / all / off**; las etiquetas de todas las estaciones se muestran en stages y los tonos se añaden en all o en una vista cercana.
- **Layer history** muestra todas las capas completas ya formadas en el tiempo de reproducción. Cada tarjeta contiene sus 40 tonos; se puede seleccionar para inspeccionar el momento de formación. La geometría no se sustituye por ese gráfico.

Las imágenes y bounding boxes de la cámara siguen siendo una proyección de la escena con decisiones sintéticas, no una ejecución de visión sobre píxeles reales.

## Cargas y referencias

Con masa asumida 1,8 kg:

- una capa y herramienta: 40×1,8 +30 = **102 kg**;
- stack completo, madera y horquilla asumida: 800×1,8 +25 +200 = **1.665 kg**;
- carro de inventario de cuatro stacks y tara asumida de 1.000 kg: **6.860 kg**;
- cuatro pallets de salida y la misma tara de referencia: **5.132 kg**.

El puente de stacks utiliza una **base de diseño de 2 t**, distinta del pórtico de capas. [Demag KBK de doble viga](https://www.demagcranes.com/en-au/products/cranes/kbk-light-crane-system/kbk-double-girder-suspension-cranes) es una referencia de principio para transporte aéreo y grandes áreas, no una selección certificada para este vano, edificio, horquilla y movimientos. Los carros tienen una base de diseño de 8 t. La estructura, retención, accionamientos, temperatura y aceleraciones requieren validación de un integrador. No se usa el límite del pórtico ligero para justificar mover el stack entero.

Se mantienen las referencias de rodillos, sensores, cámaras y transporte de pallets del prototipo. La escena es cinemática con recursos y tiempos, no un solver de contacto. Las comprobaciones de envolventes muestreadas excluyen herramientas y el interior de carros/recinto de descarga. No equivalen a una prueba continua de colisiones.

## Resultado reproducido y verificación

Lote nominal: 3.200 piezas inspeccionadas en 2.241,249 s; 2.520 conformes colocadas, 2.240 expedidas en cuatro pallets completos y 280 conservadas en pallets parciales. Se descartan 396 piezas (383 fuera de criterio y 13 sin resolución); quedan 284 piezas conformes en acumuladores. El balance conserva las 3.200 identidades. Las 63 capas completas pasan las comprobaciones de mezcla sin filas ni columnas monocromáticas.

El caudal de salida del lote es **3.597,994 ladrillos conformes/h**, contando únicamente pallets completos cargados sobre el carro de expedición. No es una medición ni una garantía de capacidad industrial. El modelo anterior de ocho células da 3.426,503/h bajo su logística diferente; no se presenta la duplicación de dehackers como duplicación del caudal.

Pasaron 29 pruebas de modelo y contratos (20 anteriores y 9 de logística dual), incluyendo concurrencia real A/B, soporte del primer pallet, acceso exclusivo al merge, capacidad y retorno de carros, y parada por falta de confirmación. La comprobación de envolventes externas pasó en 162 instantes; conserva las exclusiones descritas arriba.

La revisión de navegador se ejecutó sin acceso HTTP/HTTPS: WebGL activo, 3.200 piezas, ocho cámaras, 63 tarjetas de capas al final, cuatro pallets expedidos y ausencia de errores JavaScript. El ancho móvil de 430 px no produce desbordamiento horizontal. Capturas y datos de navegador: `artifacts/greenfield_04/verification/`. El renderizado de la cámara usa un contexto independiente para mantener visible la escena principal al desplegar el panel.
