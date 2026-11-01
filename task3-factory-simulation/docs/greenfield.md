# Concepto 1: instalación nueva autónoma

Esta propuesta aborda la escasez de personal para un trabajo físicamente exigente y repetitivo. No modela una estación de revisión humana. El prototipo anterior permanece intacto en `plant_sim` y `artifacts/plant_automation_01`; su punto de partida es el commit `86b820d`.

## Abrir y reproducir

Desde la raíz del repositorio:

```bash
python3 scripts/greenfield_demo.py --compare --output-dir artifacts/greenfield_02
```

Abrir `artifacts/greenfield_02/index.html`. Funciona offline, sin servidor ni GPU remota. `comparison.html` compara escenarios; cada uno tiene su propia reproducción 3D. Una ejecución no sobrescribe una carpeta existente: seleccionar otro nombre al repetirla.

Dependencia ya utilizada por el prototipo: `python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt`.

Pruebas:

```bash
PYTHONPATH=.deps/plant_sim:. python3 -m unittest discover -s tests_greenfield -v
```

## Arquitectura concreta

1. Muelle automático: recibe un stack de 800 ladrillos, 10×4×20. La demostración física dispone de dos posiciones de entrada, 1.600 piezas; los 36 stacks de un kiln cart son contexto del reto, no una geometría completa validada en esta escena.
2. Pórtico de retención de capa: retira una capa de 40 y la lleva a una de las bandejas libres. La retención/gripper industrial y su validación de carga siguen pendientes; no se presupone que el gripper LEGO sirva para ladrillos reales.
3. Distribuidor de filas: separa primero la fila delantera, sin atravesar las restantes. Alimenta dos células por distribuidor. Una célula aislada antes del arranque no recibe material.
4. Cada célula dosifica piezas y tiene ocho zonas exclusivas de inspección, cámara con iluminación controlada y desvío. La identificación de color/calidad es sintética en este estudio; no ejecuta percepción sobre imágenes renderizadas ni modifica el módulo de persona 1.
5. Decisión incierta: segunda exposición automática una sola vez. Si persiste la duda, cuarentena automática. Defectuoso observado: rechazo. Ninguna de estas rutas espera una clasificación humana.
6. Aprobados: tres transportadores de acumulación, uno por tono aceptado, con 20 zonas físicas de 0,30 m cada uno. Se reserva la zona siguiente antes de mover. Si la entrada está ocupada, se utiliza una reserva automática de hasta 50 bolsillos por célula. La recuperación reserva una zona antes del retorno; el desvío evita esperar por esa misma zona mientras se retiene el mecanismo que necesita la recuperación (interbloqueo circular). Depósito y recuperación comparten el mecanismo de transferencia: no hay manipulaciones simultáneas ficticias. Falta de espacio produce contrapresión, sin descartar material aprobado.
7. Selector mecánico de tonos y formador de filas: reserva inventario suficiente para una capa completa con receta 13/13/14, variando el tono extra. Alterna tonos vecinos y comprueba que no existan filas/columnas monocromas. Las filas terminadas se empujan a un nido de capa. No hay un robot haciendo un ciclo de pick-and-place por cada pieza buena.
8. Pórtico común, centradores y pozo guiado: deposita una capa, comprueba posición y baja el soporte 69 mm. La siguiente capa llega al mismo plano; las anteriores y el pallet descienden físicamente juntos. Tras 14 capas verifica cantidades, producto y distribución vertical y libera 560 piezas. El transportador adelanta los pallets ya terminados antes de descargar el siguiente; no los atraviesa. Los paneles de guía se elevan y confirman fin de carrera antes de descargar el pallet y alimentar el vacío; se cierran antes de reanudar el apilado.

Los tonos `Warm`, `Copper`, `Russet` y la receta en tercios son hipótesis ilustrativas del equipo para tonos **aceptables** de un solo producto. Oscuro no equivale automáticamente a defecto. La pertenencia a la calidad aceptada depende del producto. No se mezclan marcas/SKUs para completar cuotas. Se conservan sobrantes aprobados y pallets parciales entre lotes; no se inventa suministro ilimitado de reemplazo.

## Automatización y fallos

SimPy posee los recursos y el reloj. Three.js reproduce las mismas posiciones y trayectorias por ID, sin copias visuales independientes. Los fotoeléctricos virtuales se encienden por presencia geométrica. El panel muestra eventos de estación, trayecto, velocidad, tiempo y progreso. Las confirmaciones de agarre/fin de carrera son señales virtuales supuestas; hay un caso de confirmación crítica ausente que inhibe el movimiento. No hay PLC ni hardware conectado.

La referencia incluye un atasco de posición conocida, con retroceso limitado y confirmación de retorno, y un error de centrado de 8 mm, corregido automáticamente. Error de 20 mm o ausencia de confirmación crítica llevan a `SAFE HOLD` y conservan el material. No se promete recuperarse autónomamente de cualquier fallo mecánico; mantenimiento y reparación quedan fuera del flujo productivo nominal.

## Por qué dura ese tiempo

Cada desplazamiento usa `max(|Δx|, |Δy|, |Δz|) / velocidad`: ejes coordinados y duración fijada por el eje limitante. A ello se suman exposición, inferencia, confirmaciones, agarre y liberación. Son velocidades de ingeniería y tiempos supuestos configurables, no ciclos medidos. El bloqueo por buffers, la disponibilidad del pórtico común, la mezcla de inventario y los fallos afectan al tiempo final. No se aplica otro factor de disponibilidad del 85% encima de los fallos explícitos.

La nueva arquitectura es una candidata verificable, **no un óptimo demostrado**. Dos y cuatro células usan el mismo material y las mismas decisiones por ID. La comparación incluye incertidumbre alta, rechazo alto, una célula aislada, fallo de alineación y confirmación ausente. Los runs detenidos están censurados y no se comparan como capacidad sostenida.

## KPIs que sí se pueden defender

- **Released conforming product**: piezas conformes en pallets completos físicamente descargados ×3.600 / tiempo total. Incluye llenado y vaciado del lote.
- **Conforming material formed**: añade el pallet parcial. No equivale a producto entregado.
- Pallets completos, material parcial, rechazo, cuarentena y stock/WIP retenido, con balance por identidad.
- Cumplimiento de receta por capa, filas/columnas monocromas y columnas verticales por pallet.
- Reinspecciones y recuperaciones realmente confirmadas.
- Duración de movimientos y esperas programadas por estación. Sus sumas pueden superar el tiempo total si varias piezas se mueven en paralelo; no son automáticamente porcentajes de utilización.

La conformidad real se conoce únicamente porque el generador sintético tiene ground truth. Esa verdad se utiliza para evaluar, **nunca para impedir una falsa aceptación**. Un escenario con errores de clasificación puede formar producto incorrecto: el modelo debe mostrarlo. Las tasas de error por defecto son supuestos ideales que requieren medición de persona 1 para estimar una planta real.

La meta configurable es 3.000 conformes/h; la simulación puede quedar por debajo. No se ajusta el reloj para alcanzarla. No hay baseline manual medido, CAPEX cotizado ni ahorro/ROI demostrado. Las estimaciones de personal del mentor son contexto de demanda de automatización, no empleos cuya eliminación esté garantizada.

## Referencias y límites

Las URLs, valores y alcance se distribuyen con cada informe en `catalog.json`/`run.json` y están visibles en **Engineering basis**:

- [Güdel FP](https://www.gudel.com/products/linearaxis/fp): perfil FP-4 de 2.000 N y 75 m/min. No combinar con la velocidad del perfil ligero. Se selecciona 1 m/s y carga de capa 40×1,8 +30 =102 kg. Es una referencia de eje; EOAT, eje vertical, dinámica y configuración completa requieren validación.
- [mk GUF-P 2000](https://www.mk-group.com/en/products/conveyor-technology/belt-conveyors/guf-p-2000.html): hasta 125 kg y 80 m/min, según variante. Cada buffer seleccionado tiene 6 m, 36 kg y 0,35 m/s.
- [Interroll PM9710](https://www.interroll.com/fileadmin/products/product_data/PM-9710/PM9710_EN.pdf): 1.250 kg/m, 3.000 kg/accionamiento y 0,1–0,5 m/s. Stack supuesto: 1.465 kg incluyendo pallet supuesto de 25 kg; distribución de apoyo de 1,2 m pendiente de verificar. Temperatura publicada +5…45 °C: confirmar la temperatura real del producto/entorno antes de seleccionar equipos para salida de horno.
- [Basler a2A2600-64ucBAS](https://docs.baslerweb.com/a2a2600-64ucbas): cámara color/global shutter/trigger; sus fps no demuestran precisión de clasificación.
- [SICK WTB4C](https://www.sick.com/media/docs/7/97/097/operating_instructions_wtb4c_3pxxx_axx_de_en_fr_pt_es_it_ja_zh_ru_im0070097.pdf): respuesta 0,5 ms como referencia para presencia; no es un sensor de seguridad.
- [LINGL/Triangle Brick](https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf): referencia industrial de mezcla, formadores de filas y marcos descendentes. No es un datasheet del selector personalizado de esta escena.

Dimensiones exteriores y cantidades: material del organizador, 245×67×69 mm, 800 entrada y 560 salida. **Orientación provisional**: 10 aristas cortas transversalmente y 4 largas en profundidad, huella 0,67×0,98 m. No inferir la orientación únicamente del número 10×4. Masa **1,8 kg asumida**, no un SKU ACME confirmado; una ficha de [US Brick King](https://usbrick.com/wp-content/uploads/2025/05/USBrick-TechSpecs-1.pdf) sirve únicamente como comparador, no certificación ACME.

Se auditan continuidad de trayectorias, exclusividad por ID, tiempos derivados, pallets sin IDs repetidos y mezcla. Se comprueban envolventes de ladrillos en un muestreo de posiciones; esto **no es una prueba continua de ausencia de colisiones**, no incluye herramientas/cables y no valida contacto, fricción, vuelco, retención o integridad estructural. La guía alinea una carga rígida: no deforma ladrillos cocidos ni supone que sus irregularidades desaparezcan. El paso siguiente para industrialización es validar agarre, tolerancias, temperatura, polvo y tiempos con el integrador.

## Evidencia de esta versión

Quince pruebas del concepto cubren balances, identidad, transferencia rígida de capas, guías abiertas antes de descargar/alimentar pallets, descenso de 69 mm, mezcla, errores de clasificación, cuarentena y fallos. El núcleo previo conserva sus 89 pruebas. La escena se comprueba offline en Edge, con 1.600 IDs, vistas de mezcla/apilado y ancho móvil. El informe de ejecución es regenerable y los artefactos voluminosos no se incluyen en Git.

La referencia de cuatro células queda por debajo de la meta de 3.000 conformes/h. La actividad del mecanismo compartido de desvío y reserva muestra una restricción concreta que debe investigarse: depósitos y recuperaciones consumen trayectos verticales y no pueden ejecutarse a la vez. Optimizar ese mecanismo o redistribuir stock entre células requiere otro escenario y validación de hardware; no basta con aumentar la velocidad gráfica de reproducción.

Una observación importante: el escenario con más incertidumbre puede mostrar mayor tasa de pallets liberados por hora en este lote porque envía más piezas a cuarentena y reduce trabajo posterior. Eso **no demuestra una mejora del proceso**: cambian el rendimiento material y el inventario residual. Comparar siempre rechazo, cuarentena, material formado y stock retenido junto con el caudal.

### Resultado reproducido (semilla 8)

Referencia: 3014.86 s; 1.600 inspeccionados; 1.120 liberados en dos pallets; 120 en pallet parcial; 176 rechazados; 6 en cuarentena y 178 en stock/WIP. Dos recuperaciones confirmadas. El muestreo de envolventes no encontró intersecciones en 130 instantes; no equivale a validar colisiones continuas ni herramientas.

| Escenario | Estado | Conformes liberados/h |
|---|---|---:|
| Autonomous reference | completed_with_residual_stock | 1337.38 |
| Two-cell alternative | completed_with_residual_stock | 779.52 |
| One cell isolated before dispatch | completed_with_residual_stock | 1107.77 |
| More uncertain observations | completed_with_residual_stock | 1702.76 |
| High rejection | completed_with_residual_stock | 781.22 |
| Alignment outside recovery range | safe_hold | No comparable: censurado |
| Missing source confirmation | safe_hold | No comparable: censurado |
