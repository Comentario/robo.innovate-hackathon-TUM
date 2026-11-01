# Revisión 12: capacidad y coherencia mecánica

Checkpoint anterior: `97aaa4b`. Demo: `artifacts/greenfield_12/index.html`.

La referencia del mentor es 1.500 ladrillos/h; 3.000/h es una ambición de capacidad, no una razón para alterar tiempos. Las cifras son estimaciones del concepto, no caudal de una máquina instalada.

## Rodillos por zonas

Una zona de 300 mm incluye un rodillo motorizado conectado a rodillos libres, control y detección de ocupación. Se puede detener una zona sin detener toda la línea. Un sensor por zona informa al control de si puede admitir material; no hay un cilindro de tope por ladrillo. Los indicadores están montados sobre carcasas.

[Interroll MultiControl](https://www.interroll.com/fileadmin/Downloads/User_Manuals/Controls/MultiControl/MultiControl_Supplement_EN.pdf) documenta liberación individual/coordinada y cuatro zonas por controlador. [Ficha MultiControl AI](https://www.interroll.com/products/controls/multicontrol-ai): 24/48 V DC, IP54, ambiente −30 a +40 °C. [Manual EC5000](https://www.interroll.com/fileadmin/Downloads/User_Manuals/RollerDrive/User_Manual_EC5000_EN.pdf): 35 W, 30:1 hasta 0,60 m/s; 18:1 hasta 1,00 m/s para transferencias cortas. No se supone que la tolerancia térmica ambiental garantice el contacto con ladrillos calientes.

Se representan al menos tres rodillos bajo una pieza de 245 mm, siguiendo las [bases de planificación](https://www.interroll.com/fileadmin/products/product_data/Rollers_Technical_Information_Planning/Foerderrollen_2023-07_Planungsgrundlagen_EN.pdf). Selección de acumulación: 0,30 m/s, aceleración/frenado 1 m/s² y 10 ms de margen de control; distancia de parada estimada 48 mm, pendiente de puesta a punto con producto.

## Cambios físicos

- Las horquillas soportan el pallet y mordazas laterales contienen el stack. Se elimina la cesta que subía alrededor de la carga. Referencia del principio: [KINSHOFER KM332/KM333](https://www.kinshofer.com/us/crane/general-construction/brick-stack-grapples). La integración de mordazas altas con horquillas es propia, no un conjunto certificado. Tiempo supuesto: 170 mm / 0,10 m/s + 0,30 s de confirmación = 2 s.
- La transferencia de capas primero sale en X del área del soporte de inventario y después se desplaza lateralmente. Se elimina una interferencia real con ese soporte.
- El manipulador auxiliar almacena aprobados cuando su cola está llena; la reinspección es otra exposición de cámara. No representa una avería. Plano de transferencia elevado y retorno sobre un tramo libre, evitando descender sobre sensores.
- Reserva, selector y elevador de descarte tienen recursos separados. La inspección se libera después de retirar físicamente la pieza, no al terminar todo su almacenamiento.
- El descarte usa una transferencia roja horizontal y elevador guiado hacia el colector inferior. Evita fingir el contacto de un ladrillo horizontal sobre una pendiente. Los carros de descarte siguen fijos.
- Los laterales de transportadores con movimiento Z se dibujan a sus costados, no atravesando la salida. Puentes de apilado cubren las cuatro células de cada línea.
- Ninguna capa ni pallet, incluidos los parciales, puede contener tres tonos iguales consecutivos en fila, columna o altura. El apilador espera una capa compatible cuando es necesario.

## Comparación en igualdad de condiciones

Ocho células, misma semilla, 3.200 piezas, mismas velocidades y mecanismos. Perfil de arranque/parada desde reposo en cada movimiento: rodillos 1, servo 3 y transporte pesado 0,3 m/s². Los ejes [Festo ELGC-TB](https://www.festo.com/media/catalog/202998_documentation.pdf) tienen máximos de familia de hasta 1,5 m/s y 15 m/s²; eso no califica la carga ni la integración.

| Zonas por tono | Motores de inspección + tonos | Controladores de cuatro zonas | Conformes expedidos/h |
|---|---:|---:|---:|
| **20** | **544** | **136** | **1.951,694** |
| 24 | 640 | 160 | 2.027,881 |
| 30 | 784 | 196 | 2.116,583 |

Se seleccionan 20: 30 zonas requieren 240 motores más (+44 %) para +8,45 % de caudal en este lote. No hay cotizaciones ni optimización económica completa. Los motores de logística, descarte y ejes son adicionales a este recuento.

La misma configuración de 20 zonas da 3.602,021/h con distancia/velocidad y esperas explícitas, sin resolver rampas. Es una referencia nominal diferente, no una garantía física ni un intervalo estadístico. Las cifras cuentan 2.240 piezas expedidas en cuatro pallets completos y el tiempo total del lote, incluyendo llenado/vaciado. Hay WIP y pallets parciales; no se cuentan como expedidos.

## Verificación y reproducción

`greenfield/interference.py` barre trayectorias completas contra envolventes orientadas de las mallas estáticas exportadas por el visor. Incluye material y cabezal/vástago de reserva, permite contacto superficial de apoyo y excluye el asentamiento dentro de depósitos. No certifica pares de mecanismos móviles, cables, fricción o agarre. Exportación: `JSON.stringify(GREENFIELD.collisionScene())` en el navegador.

```bash
python3 scripts/greenfield_demo.py --output-dir artifacts/new_run
python3 scripts/greenfield_demo.py --config config/greenfield_dual_nominal.json --output-dir artifacts/new_nominal
python3 scripts/greenfield_scene_audit.py artifacts/new_run/run.json scene.json --output static-audit.json
```

Los 56 tests de la revisión seleccionada pasan, incluida la geometría exportada. La prueba de escena es continua por segmentos, no solo dos capturas. Evidencia local: `artifacts/greenfield_12/verification/`. La animación y las decisiones de cámara siguen siendo sintéticas; no se modifica persona 1.


## Revisión 13: liberar zonas sin detener cada pieza

Checkpoint base `cfe2a03`; vista actual `artifacts/greenfield_13/index.html`. El objetivo de diseño es 3.000/h; 1.500/h queda como referencia del mentor. No se replica otra instalación en esta demo.

El control reserva una zona adicional de frenado antes de permitir velocidad no nula al cruzar una frontera. Si esa reserva no está disponible, desacelera hasta detenerse. El último tramo antes de cámara/selección siempre termina detenido. Las velocidades y aceleraciones máximas se conservan. Es una interpretación del principio de liberación coordinada documentado por Interroll, no su programa PLC certificado.

Resultado con los mismos 544 accionamientos de inspección/tonos: **2.049,799 conformes expedidos/h**, frente a 1.951,694 con parada completa en cada frontera: **+5,03 % sin hardware adicional**. No se confunde con los 3.602,021/h de la referencia nominal que no resuelve rampas. No se afirma haber alcanzado aún 3.000/h con estas rampas.

Se verifica continuidad de velocidad y tiempo en cada frontera que se cruza en movimiento, reserva de frenado, mezcla y conservación. El cálculo de perfil admite velocidades inicial/final no nulas y comprueba distancia mínima de frenado. El siguiente aumento debe basarse en los mecanismos que realmente limitan la línea; aumentar cola o motores indiscriminadamente dio poco rendimiento en la comparación de revisión 12.
