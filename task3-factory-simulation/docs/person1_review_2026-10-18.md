# Revisión de persona 1 y propuesta de integración

Revisión local del 18 de octubre de 2026. Rama remota `persona1/perception`,
commit `e71ddf3` (`feat(perception): add brick detector and partial inventory`).
Se hizo fetch y se revisó una extracción aislada en `/tmp`; no se hizo merge,
cherry-pick ni cambio de rama. Seguimos en `persona2/planning`.

Código revisado:
https://github.com/Comentario/robo.innovate-hackathon-TUM/tree/e71ddf3/perception

Esta propuesta todavía requiere acuerdo con persona 1; no se le ha enviado
ningún mensaje ni se ha cambiado su rama.

## Qué hace realmente

Usa OpenCV y NumPy, sin red neuronal ni entrenamiento. Calcula la distancia
entre imagen y fondo vacío en Lab, aplica umbral y apertura morfológica,
elimina componentes pequeños y separa piezas mediante dimensiones nominales,
orientaciones en imagen y cortes por proyección/geometría. Genera cajas,
centros e IDs ordenados por posición, además de un inventario parcial.

`color_estimator` y `camera_adapter` son todavía esqueletos. El script carga
imágenes de disco; el gestor de inventario construye/guarda el documento, pero
no sigue identidades físicas entre imágenes. En la entrega actual todos los
`color_group` son `unknown` y todos los `color_score` son `0.0`.

El roadmap de su rama permite una primera versión con segmentación, cajas,
promedios de color y rangos de tono. No requiere una NN. Trabajar con un dataset
no implica entrenar una red: aquí se utiliza para probar el detector.

## Reproducción independiente

Se ejecutó el código de ese commit en aislamiento, cambiando en memoria las
rutas de entrada/salida para no sobrescribir su ejemplo ni nuestros módulos.
Entorno disponible: OpenCV 4.5.4, NumPy 1.21.5, Python 3.10.

| Escena incluida | Conteo esperado según el ejemplo | Resultado | Tono disponible |
|---|---:|---:|---|
| bricks_02.png | 2 | 2 | No |
| bricks_06.png | 6 | 6 | No |
| bricks_10.png | 10 | 10 | No |
| bricks_17.png | 17 | 17 | No |
| bricks_25.png | 25 | 25 | No |

En las cinco escenas los IDs son únicos dentro de cada documento, las cajas
están dentro de la imagen y los centros dentro de sus cajas. El documento de
17 piezas coincide exactamente con el inventario versionado.

Evidencia local, ignorada por Git:
`artifacts/person1_review/e71ddf3/review_results.json`, `preview_17.png` e
`inventory_17.json`. La atribución del dataset permanece en su rama en
`data/images/zenodo_detection/README.md`.

Esto no mide IoU, precisión/recall contra anotaciones independientes ni calidad
de color. Los conteos esperados proceden de las escenas seleccionadas; no
constituyen una evaluación de generalización. La vista de 17 piezas confirma
que algunas etiquetas se superponen y que los cortes necesitan revisión fina.
Las imágenes entregadas no incluyen etiquetas dark/medium/light de referencia.

## Diferencias de contrato

| Productor actual | Nuestro consumidor | Acuerdo propuesto |
|---|---|---|
| schema_version: "0.1" | inventory-snapshot-0.1 | Convertir mediante adaptador explícito; no cambiar el productor por ahora. |
| image_id | snapshot_id | Añadir ID único de captura/lote; un nombre de archivo reutilizado no identifica una observación nueva. |
| bricks | items | Validar cada detección y conservar los metadatos originales. |
| brick_001, brick_002… | ID físico para reservas/acciones | Son locales a una imagen. Para planificación estática, distinguir captura+ID; para ejecutar, exigir seguimiento o un lote inmóvil identificado. |
| bbox_px / center_px | Sin poses para plan-only; metros para ejecución | Conservar píxeles para diagnóstico. Poses métricas requieren calibración, profundidad/altura y transformación de frame. |
| color_group: unknown | Categoría de receta | Bloquear decisiones de mezcla hasta disponer de clasificaciones válidas. No sustituir por medium ni por categorías sintéticas. |
| color_score: 0.0 | score opcional entre 0 y 1 | Acordar significado y rango. El 0 actual es un placeholder, no una confianza calibrada. |
| processing_status: partial | Sin estado parcial equivalente en el snapshot | Añadir puerta de aceptación en el adaptador; no convertir ciegamente un parcial en inventario listo. |
| Sin caras/rotaciones físicas | face_aware opcional | Empezar con face_aware=false. No inventar caras opuestas ni traducir horizontal/vertical de imagen a orientaciones del robot. |

El planificador genérico acepta nombres de categorías arbitrarios; por eso
`unknown` debe bloquearse en la frontera con este productor, incluso si un
inventario técnicamente cumple el formato. Las clases admitidas y la política
ante incertidumbre deben acordarse, no deducirse de que el JSON sea válido.

## Integración por etapas

1. **Detección parcial (ya revisable).** Consumir el documento para revisar conteo,
   IDs, cajas y estado. No planificar mezcla ni despachar acciones con él.
2. **Estimación de tono (siguiente entrega de persona 1).** Una función/CLI que
   reciba imágenes/rutas por argumentos y devuelva el inventario; clases y
   desconocidos explícitos, método y configuración registrados. Probar ROIs o
   máscaras que reduzcan fondo y sombras; aportar ejemplos etiquetados por tono.
3. **Adaptador de planificación (nuestro bloque).** Convertir el formato real al
   snapshot canónico, conservando captura, IDs y procedencia. Rechazar parciales,
   IDs repetidos y clases no acordadas. Probar el planificador primero sin robot.
   Una demo con posiciones inventadas debe declararse sintética; no presentar
   esas coordenadas como observaciones de percepción.
4. **Identidad y coordenadas para ejecución (trabajo conjunto).** Acordar lote
   estático o tracking, frame de cámara/celda, unidades, calibración y poses
   medibles. Rechazar ejecución si solo hay píxeles. Validar agarres/orientaciones.
5. **Validación del pallet.** Una observación distinta de los reconocimientos del
   ejecutor, vinculada al run_id/plan_digest. El detector actual no valida el
   resultado final por el mero hecho de haber detectado el inventario inicial.

No necesitamos trasladar OpenCV al núcleo de planificación. El adaptador de
entrada y el adaptador del robot siguen siendo fronteras separadas. Una NN solo
se reconsideraría según errores medidos del método clásico y condiciones reales;
no por el hecho de que haya un dataset.

## Organización de Git

Las dos ramas comparten base en el commit inicial. Hay seis rutas modificadas
en ambas: `.gitignore`, `README.md`, `docs/person_2_notes.md`, `interfaces.md`,
`planning/__init__.py` e `integration/__init__.py`. Las dos últimas son esqueletos
en persona 1 y módulos funcionales aquí; no deben reemplazarse automáticamente.
Esto identifica solapamientos, no es el resultado de ejecutar un merge.

Propuesta para acordar:

- Persona 1 mantiene percepción, imágenes de ejemplo, formato de salida y sus
  notas. Declarar dependencias e instrucciones multiplataforma reproducibles.
- Nosotros mantenemos planificación, orquestación y robot. Un único adaptador
  convierte su exportación; no copiar lógica de percepción al planificador.
- Preparar un PR de integración con alcance explícito: percepción y ejemplos,
  conservando nuestros módulos funcionales y reconciliando documentación común.
  No hacer un merge ciego de todos los esqueletos ni un cherry-pick completo del
  commit actual, que los incluye junto con el detector.
- Antes de incorporar cambios, comparar contra el SHA revisado; si persona 1
  actualiza su rama, revisar el nuevo diff. Resolver formatos/documentación en
  un commit propio y ejecutar las pruebas de ambos módulos.

No se ha creado una rama compartida, PR ni push como parte de esta revisión.

## Puntos concretos para acordar con persona 1

- ¿Qué significa exactamente color_score y cómo se representa un tono incierto?
- ¿Cómo versionará la salida cuando color_estimator esté listo?
- ¿Los IDs durarán solo una imagen, un lote estático o varias capturas?
- ¿Qué cara está observando la cámara y qué información puede afirmar sobre ella?
- ¿Entregará una función/CLI parametrizable, configuración y comando de tests?
- ¿Qué muestras etiquetadas y condiciones de iluminación usará para validar tonos?

No hace falta resolver calibración física para probar plan-only, pero sí antes
de que una detección se utilice para recoger un ladrillo real.
