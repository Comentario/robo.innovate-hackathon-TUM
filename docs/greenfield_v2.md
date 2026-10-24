# Greenfield v2: mecanismos y demo para jurado

Punto de retorno: **`6a6a167`**, escena anterior `artifacts/greenfield_02/index.html`. Esta versión conserva el apilador descendente y sustituye las transferencias sin mecanismo visible.

## Reproducir

```bash
python3 scripts/greenfield_demo.py --compare --output-dir artifacts/greenfield_03
```

Abrir `artifacts/greenfield_03/index.html`. Interfaz y etiquetas en inglés. Las vistas **Dehacking / Inspection / Blending / Palletizing** cambian el encuadre. Hacer clic sobre una cámara, o **Camera view**, abre una proyección cenital de la propia escena, con bounding boxes por ID y estado de observación. El selector permite ver cada cámara. La reproducción cambia la velocidad visual, no la duración del proceso ni los KPIs. Las vistas cercanas y la cámara seleccionan 1× para apreciar las carreras; Full line usa 20× para recorrer el lote.

La cámara es **virtual**, con decisiones sintéticas; no se presenta como ejecución de OpenCV sobre imágenes reales. Cinco apariencias: dos extremos rechazados y tres tonos intermedios aceptados. No se cambia el algoritmo ni el JSON de persona 1.

## Qué cambia físicamente

| Transferencia | Mecanismo representado y gobernado por el modelo |
|---|---|
| Entrada / pallets vacíos | Transportadores de rodillos y transferencia en ángulo recto; retorno de vacíos sin atravesar los ya aparcados |
| Capa → fila | Plataforma de extracción con rodillos; se extrae primero la fila frontal |
| Fila → célula | Shuttle de rodillos que se alinea, recibe diez piezas, se desplaza lateralmente con ellas y las descarga |
| Separación de piezas | Empujador de selección individual, retracción y rodillos transversales |
| Inspección y acumulación | Zonas de rodillos independientes, sensor por zona y tope retráctil; no una única faja continua |
| Rechazo / cuarentena | Empujador lateral, superficie de transferencia, chute inclinado con guías y compartimento de recogida |
| Aprobado → tono | Shuttle de rodillos que recibe, se alinea con el tono y descarga sobre el buffer |
| Reserva excepcional | Pinza cartesiana visible: aproximación libre, cierre, transporte, apertura y retirada |
| Mezcla → capa | Selector sobre raíles sin mesa superpuesta, banda de indexado de fila, rodillos continuos hasta el nido y empujador de fila con retorno |
| Capa → pallet | Pórtico, centrado, descenso de 69 mm, apertura de guías y descarga del pallet verificado |

Los auxiliares de los shuttles y empujadores tienen sus propias trayectorias SimPy; se mueven junto a las piezas que soportan o empujan. No es una animación decorativa separada del reloj productivo.

Los topes reciben órdenes de apertura y cierre. Se cuentan **80 ms para retraer**, se mueve la pieza y se cuentan **80 ms para levantar** el tope de la zona liberada. La visualización interpola la carrera del mismo evento. Los rodillos de una zona ocupada pueden detenerse mientras otras zonas funcionan: es acumulación por zonas, no deslizamiento sobre una faja común. Los indicadores distinguen zona libre, ocupada y en movimiento.

Los rodillos y los cuerpos fijos quedan debajo del plano de apoyo; los shuttles viajan por huecos entre mesas. Las conexiones pequeñas permiten un traspaso soportado por el propio largo del ladrillo. No se representa una pieza suspendida entre mesas distantes.

## Cambio del control de mezcla

Antes se esperaba inventario para toda la capa. Ahora se inicia cada fila cuando hay material observado suficiente para esa fila, manteniendo la cuota final 13/13/14 y los controles de distribución. No se consulta el color de piezas todavía sin observar para decidir la mezcla. Un final de lote puede dejar filas parciales: permanecen identificadas como WIP y no se declaran pallets entregados.

La recuperación de reserva toma el mecanismo y una entrada libre de forma compatible. No reserva una entrada mientras espera un mecanismo que ya está reteniendo otra pieza a la espera de esa entrada: evita el interbloqueo circular.

## Dimensionamiento y comparación

Candidata: ocho células, tres buffers de **30 zonas de 0,30 m** por célula, 9 m por buffer. Aumentar almacenamiento también aumenta la longitud de la instalación: selector, formador y apilador se desplazan 3 m; no se insertan piezas extra en la geometría antigua. El perfil de pórtico permanece en 1,0 m/s.

El lote de comparación tiene cuatro stacks de 800, **3.200 piezas**, mismos productos, semilla y modelo de observación entre alternativas. La liberación ofrecida de 7.500 piezas/h es una consigna, **no el caudal realmente conseguido** por el dehacker. Los recursos y sus movimientos limitan el caudal real.

Se comparan 2, 4, 6 y 8 células. Más células y más buffers significan más hardware y superficie; no se afirma óptimo económico sin cotizaciones. Las cifras iniciales de 1.337/h corresponden a otra arquitectura, otro tamaño de lote y otra configuración; no se atribuye toda la diferencia a un algoritmo.

El dashboard cuenta como entrega únicamente los pallets completos físicamente descargados. Muestra aparte material formado, parcial, rechazado, en cuarentena y WIP. La referencia del organizador de 1.500–3.000/h no constituye un baseline medido de las instalaciones manuales. No hay ahorro de personal, ROI ni mejora industrial demostrada. Una variante detenida aparece como **Stopped**, no como capacidad comparable.

## Base de equipos

Referencia de acumulación: [Interroll EC5000 cilíndrico](https://www.interroll.com/fileadmin/user_upload/Downloads__PDF_/Drives___Controls/DC_Platform/EC5000_Catalog_PDF/EN/EC5000_50mm_IP54_EN.pdf), perfil **35 W, 30:1**, máximo 0,60 m/s; se seleccionan 0,30/0,35 m/s. La ficha indica 350 N con cabezal de transmisión. Se representa rodillo de referencia de 0,50 m en una zona de ancho aproximado 0,56 m. El montaje de zonas de 0,30 m, el paso de rodillos, transmisión, par, desgaste y polvo deben validarse: no es una máquina completa certificada por el proveedor. La temperatura ambiente de esta referencia es 0–40 °C; verificar producto y entorno reales.

El concepto de control por zonas se apoya también en [MultiControl / DC Platform](https://www.interroll.com/fileadmin/Downloads/Catalogs/RollerDrive_and_Controls/DC_Platform_EN.pdf). Los topes de 80 ms, empujadores, pinza, chutes, interfaces y sus ciclos son hipótesis declaradas de ingeniería. Se mantienen las referencias previas de pórtico, transportador de pallets, cámara y sensor, con sus límites visibles en Engineering evidence.

## Límites y comprobación

- No se simula contacto, fricción o vuelco de ladrillos. La pinza y las superficies representan cómo se aplica y soporta el movimiento; falta validar los agarres y los actuadores reales.
- El movimiento interno de material **dentro de los compartimentos cerrados** se abstrae como recogida/acomodo. No se afirma simular cómo caen o se asientan los rechazos. Esa zona queda explícitamente fuera del muestreo de colisiones externas; las rutas abiertas sí se muestrean.
- Un compartimento tiene distribución geométrica de dos columnas, veinte posiciones y diez niveles (400 piezas); su resistencia/carga no se certifica con este cálculo geométrico. También se respetan los límites globales de stock configurados.
- Las pruebas verifican empujador y pieza coordinados, fila sobre su shuttle, topes abiertos antes de avanzar, trayectorias rígidas de capas, receta, conteo de pallets, incertidumbre, errores y paros. La revisión de navegador comprueba vistas, sensores/topes, cámara virtual, ausencia de errores, contadores y diseño móvil.
- Persisten los límites previos de masa 1,8 kg asumida y orientación provisional de la huella del stack. La validación de hardware y el baseline real siguen pendientes.

## Resultado verificado de esta versión

Semilla 8; 3200 piezas; 2353.42 s. Se liberan 4 pallets, 2240 piezas: **3426.50 conformes/h liberados**. Material formado: 3671.25/h; parcial 160, stock/WIP 404, rechazo 383, cuarentena 13. Son resultados sintéticos, no una medición en ACME.

| Escenario | Estado | Conformes liberados/h |
|---|---|---:|
| Autonomous reference | completed_with_residual_stock | 3426.50 |
| Two-cell alternative | completed_with_residual_stock | 539.43 |
| Four-cell alternative | completed_with_residual_stock | 1824.26 |
| Six-cell alternative | completed_with_residual_stock | 2429.35 |
| One cell isolated before dispatch | completed_with_residual_stock | 2578.69 |
| More uncertain observations | completed_with_residual_stock | 3573.05 |
| High rejection | safe_hold | Detenido; no comparable |
| Alignment outside recovery range | safe_hold | Detenido; no comparable |
| Missing source confirmation | safe_hold | Detenido; no comparable |

Se verificaron **20 pruebas** de modelo y representación. Edge offline comprobó 3.200 IDs, 784 zonas, espera y movimiento simultáneos con topes consistentes, cámaras y bounding boxes, cuatro pallets descargados, móvil y paro protegido. Las capturas están en `artifacts/greenfield_03/verification`. El payload visual omite repetición técnica y compacta órdenes de topes, pero conserva todas las trayectorias físicas: la prueba comprueba posiciones equivalentes. `run.json` mantiene el registro completo.
