# Revisión de persona 1 — 21 de octubre de 2026

Rama revisada: `origin/persona1/perception`, commit
`3e705b42516d98e98239a15941b5b5b4c172247e`. Comparada con la revisión anterior
`e71ddf3`. La rama se extrajo en `/tmp/munich-p1-final-review` para ejecutarla
sin reemplazar nuestros módulos ni cambiar la rama de trabajo.

## Resultado

La entrega es utilizable como entrada **offline de planificación** a través de
un adaptador explícito. Para ese intercambio basta su JSON enriquecido; no hace
falta que el planificador cargue imágenes, OpenCV ni el detector. El JSON parcial
anterior no basta porque todos sus colores siguen siendo `unknown`.

No equivale a percepción operativa de una celda física. Faltan poses métricas en
el frame de la celda, identificación de la cara observada, persistencia de IDs
entre capturas y estabilidad de las clases entre escenas. El adaptador no crea
esos datos a partir de los píxeles.

## Implementación revisada y reproducida

- Detector de pallet v0.2: alineación ECC del fondo vacío, diferencia Lab,
  morfología, componentes, estimación de filas/celdas y refinamientos locales de
  límites. Mantiene priors de dimensiones y orientación aproximadamente alineada.
- Detector experimental de pared: segmentación/clustering y recuperación de
  juntas/componentes; exporta parciales, posibles merges y elegibilidad para color.
  Detectar ladrillos de una pared no demuestra que sean piezas recogibles.
- Estimador: mediana Lab del interior del bbox, evaluación de K=1,2,3 con tamaño
  mínimo, Delta E, silhouette y compactación. Los centros se ordenan por L*.
- Inventario: schema `0.2`, estado `color_estimated` o `color_inconclusive`, grupos
  relativos y puntuación. Conserva geometría y las exclusiones del detector.
- Se inspeccionaron los scripts de diagnóstico/regresión y sus requisitos de
  entrada. Algunos dependen de artefactos `outputs/` y etiquetas de un dataset
  externo que no está incluido en la rama; no son un comando autónomo de tests.

No usa una red neuronal. Usa visión clásica y K-means (aprendizaje no supervisado),
sin entrenar una NN. El dataset se usa como escenas de desarrollo/evaluación.
No hay evidencia aquí para exigir una NN antes de integrar el contrato.

## Evidencia reproducida

1. Diez imágenes de pallet: conteos 2,6,10,17,22,25,32,37,51,70 exactos y IDs
   únicos. Esto verifica conteo en estas muestras, no precisión general.
2. Once escenas de pared: geometría y flags reproducidos exactamente respecto
   a los inventarios publicados. No se dispone aquí de ground truth independiente
   para afirmar que todos esos componentes son ladrillos correctos.
3. Doce inventarios de color: resultados reproducidos exactamente desde las
   imágenes y sus cajas, incluidos grupos, puntuaciones y centros.
4. El inventario parcial regenerado de 70 tiene las mismas cajas e IDs. Añade
   `source_detector` y `eligible_for_color: true`; tres centros difieren en hasta
   0.04 px de distancia respecto al archivo publicado. No se afirma igualdad
   exacta del JSON de geometría; el resultado de color desde el JSON publicado sí
   se reprodujo exactamente.
5. Las cifras IoU de sus notas no se revalidaron: las etiquetas OBB referenciadas
   por la regresión no están incluidas. No confundirlas con los conteos anteriores.

Los resultados locales están en `artifacts/person1_review/3e705b4/`:
`results.json`, `wall_results.json`, `classification_preview.png` y el script del
ensayo. OpenCV 4.5.4 y NumPy 1.21.5 en este entorno; no se instalaron dependencias.

## Hallazgos para la integración

| Hallazgo | Consecuencia y tratamiento |
|---|---|
| Inventario principal: 70 piezas, grupos 1/2 con 19/51; centros Lab [88.32,-7.42,20.63] y [92.20,-7.14,14.29] | Ambos son claros en L*. No equivalen a los marrones dark/medium/light de nuestra maqueta. Preservar etiquetas y centros. |
| El clustering usa Lab completo | Separa también cromaticidad, no solo luminosidad. Una política smooth por L* sería una elección adicional, no la definición completa de sus grupos. |
| Cada imagen recalcula sus grupos | No comparar `color_group_1` de dos capturas como categoría material fija. Las muestras exposure_dark/light producen K=2/K=3 con la misma geometría. Esto evidencia variación entre esas muestras, sin establecer una tasa de error general. |
| `color_score` combina margen entre centros y uniformidad interior | No es probabilidad calibrada de acierto. En el pallet varía entre 0.001 y 0.906; 13/70 están por debajo de 0.5. |
| IDs espaciales por fila/columna, dentro de una imagen | No proporcionan tracking tras retirar o mover piezas. Hacer correspondencia explícita antes de cerrar un lazo cámara–robot. |
| Solo bbox/centro px, sin identidad de cara | No generar metros, profundidades ni orientación física de caras. El plan se marca `face_aware=false` y la ejecución se rechaza sin poses medidas. |
| Parciales/merges/unknown | Se excluyen con causas auditadas; no se sustituyen por tonos inferidos. |
| README raíz e interfaces aún dicen color pendiente/score 0.0 | Documentación parcialmente desactualizada; el código y schema 0.2 ya entregan color. La documentación local de integración describe el contrato real. |
| Dependencias sin manifiesto versionado y regresiones con rutas locales | Conviene añadir versiones/instrucciones de pruebas reproducibles antes de presentar la percepción como paquete autónomo. |

## Conexión preparada en nuestra rama

`integration/person1_intake.py` no importa OpenCV ni código de persona 1:

- Valida schema/estado, centros, grupos, IDs, score, geometría en píxeles y flags.
- Convierte a `inventory-snapshot-0.1`, fuente `perception`, sin inventar caras ni
  poses. Conserva etiquetas, scores y geometría para auditoría.
- Exige umbral explícito; excluye desconocidos, geometría no elegible y scores
  inferiores al umbral, con causas visibles.
- Vincula snapshot a la huella del JSON y al umbral. IDs se documentan como locales
  a la imagen. No combina inventarios de distintas capturas automáticamente.
- Usa una receta explícita en las categorías reales; rechaza nuestra receta vieja
  de tres tonos si no hay ese inventario. No realiza renombrado implícito.

El ejemplo `examples/person1/inventory_with_color.json` es una copia sin cambios
del archivo publicado en el commit revisado. Su config usa una mezcla provisional
50/50 de dos grupos y un pallet lógico de doce posiciones. Ni esa receta ni el
umbral 0.5 son requisitos del evento o parámetros calibrados.

```bash
python3 -m integration.person1_intake examples/person1/inventory_with_color.json \
  --min-score 0.5 --config examples/person1/config.json \
  --output-dir artifacts/person1_intake_new
```

Resultado probado: 57 aceptados (13 grupo 1, 44 grupo 2), 13 excluidos y doce
posiciones únicas con seis de cada grupo. Produce snapshot, auditoría, plan e
informe HTML en inglés. **No ordena ningún movimiento.** La ejecución con la
celda Panda se rechaza por ausencia de poses métricas, como debe ocurrir.

Comprobación: 74 pruebas del núcleo pasan, incluidas siete del nuevo adaptador.
No se ha repetido RViz: el cambio no modifica el adaptador del brazo.

## Organización del siguiente paso

No se ha hecho merge completo, push ni PR. Se incorporó el contrato JSON a través
de un ejemplo y adaptador propios, no los módulos/esqueletos de la rama ajena.
La rama de persona 1 mantiene archivos comunes que deben reconciliarse al integrar
su código: conservar nuestras implementaciones de planning/integration, y fusionar
README/interfaces en lugar de reemplazarlos por los esqueletos.

Antes de percepción–robot real: fijar política de clases compartidas (referencia
Lab o clasificación calibrada si se necesitan clases estables), definir tracking
o protocolo de lote estático, calibrar cámara→celda y determinar caras y piezas
recogibles. Después probar observación independiente del pallet. Se puede avanzar
con la interfaz offline actual sin esperar a esos datos físicos.
