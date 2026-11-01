# Revisión 14: eliminar el desvío aéreo de aprobados

Punto de retorno: `66b1b40`. Vista: `artifacts/greenfield_14/index.html`.

El manipulador anterior no recuperaba averías: almacenaba piezas aprobadas cuando su cola de tono estaba llena. Su gran pórtico ocultaba un problema de coordinación de flujo y no justificaba cruzar por encima del pusher de descarte.

## Diagnóstico y cambio

La fila de salida esperaba a reunir sus diez piezas antes de retirar la primera. En un desbordamiento observado había 20 Russet, 14 Copper y 3 Warm. Ahora empieza a retirar piezas siguiendo el mismo patrón conforme están disponibles. No cambia la receta final, los tonos del productor ni la restricción de no tener tres iguales consecutivos.

El distribuidor elige la menor acumulación observada cuando tiene dos celdas libres; no usa el color futuro del ladrillo sin observar. La saturación de un tono no demuestra por sí sola que deba acelerarse toda la faja.

Se eliminan los ocho pórticos de reserva, sus grippers, sus movimientos verticales y las mesas verdes. Se sustituyen por tres bandas reversibles por celda, al nivel de la línea, atendidas por el selector horizontal existente. El selector tiene un recorrido ampliado, apoyado sobre raíles, con referencia [Festo ELGA-TB-KF-70](https://media.festo.com/media/202997_documentation.pdf): hasta 5 m de carrera y 350 N en esta familia; el recorrido de diseño es 3,75 m. No equivale a una integración certificada.

En cada banda, todas las piezas almacenadas avanzan y retroceden juntas. Las reversas de 400/700 mm sincronizan la entrega con el selector, conservando 300 mm de separación entre centros almacenados. Una banda común no hace avanzar una sola pieza mientras mantiene inmóviles las demás. La transferencia a los rodillos receptores se limita a su referencia de 0,60 m/s.

Hay un motor y detección de entrada/encoder por banda, no un motor o sensor por posición. Son 24 bandas reversibles frente a los ocho pórticos anteriores de tres ejes. Los 544 accionamientos de acumulación principales se conservan. No se afirma que el CAPEX sea mínimo: se intercambian complejidad vertical por longitud horizontal y reserva. La primera banda de 12 posiciones no bastó; otra distribución llenó una de 20. Se configuraron 24 posiciones por tono tras observar un pico de 22. Son 576 posiciones de reserva frente a 400 previas, sin aumentar el número de motores de las bandas.

También se corrigió la clasificación del accionamiento SORTER en el modelo: es un servo horizontal y utiliza la rampa declarada de servo, no la de los rodillos. La banda de arrastre de la mesa receptora se muestra físicamente; las bolas pasivas no impulsan por sí mismas.

## Orientación y continuidad

La cámara de pose está fijada al bastidor de entrada. El centrador local corrige pequeños giros, con 0,4 s seleccionados en el ejemplo de 8°. Si la pose excede el rango de 10°, se retiene esa celda y las otras continúan; no se lanza un manipulador aéreo a rescatar la pieza ni se produce un E-stop de toda la planta por ese caso. Las poses y confirmaciones son sintéticas: prueban secuencia, no fuerza de agarre ni visión real.

## Comparación y límites

Mismo lote de 3.200 piezas y semilla 8:

| Configuración | Conformes expedidos/h | Entradas a reserva | Entradas aéreas a reserva |
|---|---:|---:|---:|
| Revisión 13 | 2.049,799 | 217 | 217 |
| Revisión 14 | 2.218,309 | 110 | 0 |

El aumento es de 8,22 %; las entradas a reserva se reducen un 49,31 %. Se conservan los perfiles de arranque/frenado y los límites de mezcla. El lote de referencia expide cuatro pallets completos; los pallets parciales y el WIP no se cuentan como expedidos y se mantienen por ID. No todas las métricas mejoran: el reparto del inventario residual cambia y la reserva horizontal ocupa más longitud.

Las semillas 8, 18 y 28 completaron el lote; tasas 2.218,309, 2.226,299 y 2.180,206/h. No es un intervalo estadístico ni una medición en planta. La tercera distribución detectó la falta de reserva y se repitió tras corregirla; se conserva la evidencia de las pruebas fallidas.

La auditoría barre las trayectorias contra las envolventes orientadas de las estructuras estáticas exportadas del visor. No certifica todos los pares de mecanismos móviles, contactos, fricción, cables o cargas. Las pruebas incluyen movimiento solidario de toda la banda, ausencia de PICKER de reserva, cotas constantes, capacidad finita, balance, mezcla, asignación de servo y aislamiento local de pose.

```bash
python3 scripts/greenfield_demo.py --output-dir artifacts/new_flow_run
python3 scripts/greenfield_scene_audit.py artifacts/new_flow_run/run.json scene.json --output static-audit.json
```

Evidencia de la revisión: `artifacts/greenfield_14/verification/`. Todo lo visual permanece en inglés. No se modifica la percepción Lab/K-means de persona 1.

Verificación final: 68 pruebas superadas, incluidas las nuevas pruebas de reserva y de aislamiento/corrección local. El visor offline mantiene WebGL activo con 3.200 IDs. Los archivos de geometría exportada y resultados de semillas se conservan en la carpeta de verificación.
