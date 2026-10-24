# Mecánica de transferencias: revisión 11

Demo: `artifacts/greenfield_11/index.html`. Checkpoint previo: `8683301`. Mantiene ocho células, dos dehackers, dos palletizadores y los dos carros de descarte fijos. No modifica la percepción ni los grupos de persona 1.

## 1. Mesa verde y descarga

La extensión de 730×600 mm se representa como transportador fijo verde con banda, rodillos de retorno, accionamiento inferior y bastidor. El empujador recibe sobre ella el ladrillo; después su banda lo lleva en X hasta la rampa. El chute y sus guías rojas continúan desde el borde de esa mesa. La boca de llegada lateral permanece libre. Se conservan el tramo horizontal y la trayectoria de descenso ya registrados.

## 2. Cómo se separa una fila sin insertar una cuchilla

Cada una de las cuatro bahías tiene dos nidos de alimentación con rodillos y motores independientes; no es una sola faja que mueve selectivamente sus ladrillos. En un nido:

1. Se posiciona la cassette receptora. El conjunto restante de la capa avanza simultáneamente, no solo la fila delantera.
2. La fila delantera llega a X=4,64 m, parcialmente sobre la cassette. La fila siguiente queda a X=4,395 m. Un pad superior de 160 mm de longitud en X contacta con la parte superior de la fila siguiente; el resto permanece sobre rodillos frenados. No se introduce una pieza en el intersticio.
3. Los rodillos de salida, accionados de forma independiente, llevan la fila delantera hasta X=4,74 m. Se forma así una separación de 100 mm, comprobada antes del movimiento transversal.
4. La cassette transporta la fila a la célula reservada. Se libera la sujeción antes del siguiente indexado.

Una fila de diez piezas pesa 18 kg con la masa asumida de 1,8 kg; una capa pesa 72 kg. La simulación utiliza geometría nominal. En planta se necesita medir el frente del paquete, verificar diez piezas en la fila y ajustar el pad a la receta y a la variación de huecos. La propuesta evita depender de que quepa una cuchilla en un hueco de milímetros; **no demuestra todavía la tracción ni la fuerza necesaria para separar ladrillos adheridos**. Deben verificarse presión, deslizamiento y corriente/par; una falta de confirmación inhibe la extracción. No se afirma aceptar cualquier separación arbitraria entre piezas.

El caso de fallo `hold_down_fault_bay` detiene el proceso antes de extraer la fila. Los eventos `pack_index_start`, `hold_down_confirmed` y `row_gap_verified` documentan la secuencia, pero son sensores nominales del modelo, no observaciones físicas independientes.

## 3. Mesas que se desplazan

Sí existe el principio industrial: un transportador de rodillos montado sobre un carro lineal, con un accionamiento distinto para la traslación. La escena representa en las veinte mesas móviles (cuatro de entrada, ocho de clasificación y ocho selectores) perfiles soportados, transmisión dentada, motores/cajas de accionamiento, acoplamiento al carro y retorno de cable. Los rodillos de cada mesa transportan en X; su eje lineal desplaza el conjunto en Z.

[Festo ELGC-TB](https://www.festo.com/media/catalog/202998_documentation.pdf) es una referencia de eje lineal para las células: la talla 80 aporta hasta 250 N de avance y 1,5 m/s, con repetibilidad ±0,1 mm. No se interpreta esa fuerza como capacidad de carga vertical ni se afirma que toda la mesa sea un producto Festo. La guía larga de las filas utiliza la referencia de pórtico Güdel ya catalogada; el stroke real, momentos, motor y apoyo deben dimensionarse.

## 4. Qué ocurre entre dos transportadores

Los puntos de transferencia se representan con puentes metálicos apoyados, superficies a nivel, guías y reservas de acceso. Incluye:

| Interfaz | Solución representada | Condición de avance |
|---|---|---|
| Mesa de capa → cassette | Puente de 69 mm hasta el borde de los rodillos; fila y resto del paquete apoyados | Posición de docking alcanzada; sujeción confirmada antes de separar |
| Cassette → intake | Puente de 25 mm en las posiciones de salida | Célula receptora reservada |
| Zonas individuales | Chapa de 8 mm cubriendo la separación entre módulos | Reserva de zona y permiso del motor de rodillos |
| Cola de tonos → selector | Puente de 80 mm hasta el borde de la cassette | Cola y cassette sincronizadas |
| Selector → formador | Puente de 60 mm hacia la mesa de entrada | Empujador aparcado arriba mientras llegan piezas |
| Pallet → carro de transferencia | Puentes de apoyo, rodillos, guías laterales y carro retenido sobre raíles | Recurso de merge exclusivo |

Estas dimensiones describen puentes, **no huecos libres que se pretenda saltar**. El objetivo de diseño es limitar la holgura expuesta residual a ≤5 mm y el desnivel a ≤2 mm para una pieza individual; aún no son tolerancias medidas o calificadas. Hay que probar bordes trapezoidales/rotos, rigidez de la chapa, desgaste, rozamiento y temperatura. Una cassette no debe descargar fuera de posición; el modelo usa su final de trayectoria y la reserva como confirmación nominal. En hardware esa condición requiere sensores de posición/docking independientes.

La documentación [Interroll SHC](https://www.interroll.com/fileadmin/Downloads/Catalogs/Conveyors_SHC/Catalogs/SHC_Catalog_EN.pdf) describe transferencias de paso pequeño y guías. Su módulo para objetos desde 100×100 mm no se declara seleccionado para estas piezas de 67 mm de ancho. La solución de unión mostrada sigue siendo propia y debe comprobarse con el producto real.

## 5. Empujadores rígidos y despeje del formador

Los vástagos se dibujan ahora como perfiles rígidos alineados con un único eje, sin deformar cilindros para unir puntos cambiantes. Las carreras del modelo de los empujadores de entrada y de formación son de un solo eje por paso: posicionar, bajar, empujar, subir y retornar.

El formador permanece elevado durante la llegada y el indexado de las diez piezas. Solo baja después de completar la fila, empuja y vuelve a subir antes del retorno. La anchura de la pala se reduce a 690 mm para respetar las guías del conjunto. Los montantes de las palas arrancan por encima de su borde superior para no invadir el ladrillo en la cara de contacto.

La reserva de la primera zona de inspección limita las admisiones. Se elimina una espera fija adicional de un segundo que no aportaba separación: el sensor confirma la entrada y la siguiente pieza debe esperar a que la zona quede disponible. No se aumenta una velocidad nominal para obtener el KPI.

## 6. Salida de pallets con accionamiento visible

[HORSTMANN VWG](https://www.horstmann-anlagentechnik.de/project/transfer-car/?lang=en) documenta carros sobre raíles con motorreductor accionando un eje de ruedas, rodillos de guiado lateral y transportador de rodillos a bordo, para 1.200 kg. Se usa como referencia del principio frente a los 1.033 kg asumidos del pallet lleno (560×1,8+25).

La escena añade motorreductor, eje, apoyos de ruedas, conductor de alimentación protegido, topes de fin de recorrido y guías laterales del producto. Los carros de inventario y expedición también muestran su accionamiento. La altura reducida y la configuración concreta no son una instalación del proveedor aprobada. Las guías de carga restringen desplazamientos laterales; no sustituyen un estudio de estabilidad del stack.

## 7. Desalineación, guiado y límites

Los carriles individuales tienen guías junto a la pieza, con 20 mm de holgura lateral nominal por lado, en lugar de dejar todo el ancho de la mesa libre. Se añaden guías a las cassettes y a las filas formadas. Las transiciones de pallets tienen contención lateral.

Se inyecta una desviación angular **sintética de 8°** en B00000, una vez aislado en la mesa de singulación: mordazas opuestas centran la pieza antes de entrar al carril estrecho. La escena interpola ese giro durante el centrado y representa la bajada/apertura de las mordazas. Si el valor supera ±10°, el proceso se detiene antes de la entrada. Se probó explícitamente el caso de 90°. No se afirma que la cámara de persona 1 esté midiendo esa orientación.

La geometría y la lógica representan contención y detección de fallos del producto. **No se simulan fricción, aceleraciones, impactos ni balanceo real**; los límites de fuerza y estabilidad deben verificarse físicamente. Las envolventes AABB muestreadas no prueban todas las colisiones de herramientas ni las rotaciones de las piezas. No se presenta el modelo como una validación de seguridad industrial.

## Resultado y verificación

- Un lote nominal nuevo: 3.200 inspeccionados, 2.240 expedidos en cuatro pallets completos, 200 en pallets parciales, 364 en WIP y 396 en los dos carros fijos. Balance: 3.200.
- 61 capas con receta y filas/columnas verificadas.
- **3.569,822 conformes/h expedidos**, frente a 3.459,141/h en la revisión anterior. Tiempo y KPIs provienen de las secuencias nuevas; no de un valor objetivo impuesto.
- **46 pruebas** pasaron, incluyendo la regresión anterior, indexado de todas las piezas restantes, filas traseras inmóviles durante extracción, carreras ortogonales, despeje del formador y fallos de sujeción/orientación. Se reutilizó el lote nominal para evitar simularlo una vez por prueba; los fallos necesarios se ejecutaron aparte.
- Navegador offline: WebGL, veinte accionamientos de cassettes, ocho sujeciones de paquete, vástagos sin rotación diagonal, desviación angular visible, ficha del carro con imagen, ocho cámaras, 3.200 piezas y 61 tarjetas de capas. Ancho móvil 430 px sin desbordamiento.
- Evidencia: `artifacts/greenfield_11/verification/`.


## Secuencia explícita y componentes de revisión 11

1. El transportador del paquete y los rodillos receptores avanzan sincronizados: se desplazan todas las piezas restantes.
2. Ambos se detienen. La sujeción superior baja sobre la fila siguiente y se confirma su posición. No se introduce ninguna cuchilla entre ladrillos.
3. Solo los rodillos independientes de extracción avanzan la fila delantera 100 mm. El resto permanece sobre el transportador detenido, con la fila siguiente retenida.
4. Se detiene la extracción y se verifica la separación; entonces se permite el desplazamiento lateral de la cassette. La sujeción sube antes de indexar de nuevo.

La última fila no requiere sujetar otra fila inexistente. Los eventos `feed_phase` permiten reconstruir esta secuencia. Confirmaciones y separación son sintéticas, no medidas en una máquina. Es necesario validar fuerza de sujeción, frenado, tolerancias y aceleración con ladrillos reales.

Las zonas posteriores utilizan **ZPA**: cada zona reserva la siguiente antes de activar sus rodillos, y queda detenida cuando no hay espacio. Las guías grises son fijas, con 20 mm de holgura lateral por lado. No son cientos de topes amarillos accionados verticalmente. Esto ahorra cilindros, pero exige motores de zona, sensores y control. [Interroll MultiControl](https://www.interroll.com/fileadmin/Downloads/User_Manuals/Controls/MultiControl/MultiControl_Supplement_EN.pdf) documenta control de hasta cuatro zonas y liberación ZPA; la aptitud para ladrillos calientes/polvorientos queda pendiente.

El empujador tiene dos movimientos separados: un cilindro vertical baja el bastidor que soporta la guía horizontal; el carro horizontal mueve una pala de vástago rígido. Después se retrae y sube el bastidor para dejar entrar material. Cuerpos y vástagos mantienen dimensiones constantes. Las cadenas portacables son eslabones rígidos guiados en una bandeja con retorno en U. El transporte de pallets muestra motorreductor, piñón y cremallera fija; HORSTMANN se mantiene como referencia de carro sobre raíles, no como fabricante de esta variante propia de cremallera.

El descarte conserva mesa verde a nivel y bolas de transferencia. Una banda transversal enrasada conduce hacia una rampa con boca ensanchada y guías rojas continuas, sin muro atravesado en la entrada. Las bolas pasivas no generan movimiento por sí mismas. No se simulan fricción ni deslizamiento.

La retención anterior telescópica queda sustituida por una **cesta rígida de fondo abierto que se eleva completa**, basada en [Eichinger 1059](https://eichinger.de/de/ladegabeln-schutzkoerbe/): cesta arriba para recoger, abajo durante transporte. No se deforma, escala ni se construye alrededor de la carga. Se añaden cuatro maniobras de cuatro segundos por stack: abrir antes de insertar horquillas, cerrar antes de elevar, abrir después del apoyo y cerrar vacía antes del desplazamiento elevado. La mecanización, bloqueo, dimensiones y masa de 400 kg son supuestos propios; no constituyen una configuración certificada del fabricante. Carga total supuesta: 1.865 kg bajo un objetivo de puente de 2 t. La fotografía oficial permite distinguir el producto de referencia de nuestra adaptación.

## Comparación reproducible de capacidad y hardware

Mismo lote sintético de 3.200 piezas, ocho células y misma semilla. El caudal corresponde a piezas conformes **expedidas en pallets completos**, dividido por el tiempo del lote; no es una medición de régimen permanente.

| Zonas por tono | Motores de zona | Controladores de cuatro zonas | Cilindros de tope vertical | Conformes expedidos/h |
|---|---:|---:|---:|---:|
| 20 | 544 | 136 | 0 | 2.990,739 |
| **24 (referencia)** | **640** | **160** | **0** | **3.530,974** |
| 30 | 784 | 196 | 0 | 3.558,934 |

Se seleccionan 24: 144 motores menos que 30, con caudal 0,79 % menor en este lote. No es un óptimo global ni un análisis económico sin cotizaciones. Cuatro pallets completos (2.240 piezas), 280 piezas en pallets parciales y 284 WIP; 396 piezas descartadas en dos depósitos fijos. Balance íntegro, cero piezas malas colocadas en la verdad sintética, sin filas/columnas monocromáticas. No significa rendimiento perfecto de percepción real.

Evidencia: `artifacts/greenfield_11/run.json`, `comparison.json`, comparativas de 20/30 zonas y capturas de navegador en `verification/`. Los resultados anteriores de esta página describen checkpoints históricos; esta sección y el informe 11 son la referencia vigente.

Para reproducir las tres variantes en una carpeta nueva: `python3 scripts/greenfield_demo.py --compare-zpa --output-dir artifacts/greenfield_zpa_study`. Para actualizar únicamente el visor con resultados existentes: `python3 scripts/greenfield_refresh_view.py artifacts/greenfield_11 --output-dir artifacts/greenfield_11`.

Verificación de revisión 11: 46 pruebas previas más tres pruebas de secuencia/ZPA/cesta superadas. Navegador Edge offline: WebGL activo, 3.200 IDs, 63 capas, ocho cámaras, 20 ejes transversales, ocho sujeciones y dos depósitos fijos; ancho móvil 430 px sin desbordamiento. Comprobados vástagos de dimensiones constantes y determinante unitario de las transformaciones de todos los eslabones en tres instantes.
