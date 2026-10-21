# Revisión manual de clases y umbrales

Esta herramienta prepara evidencia de referencia para comparar la clasificación
de persona 1 con decisiones humanas explícitas. No fabrica etiquetas a partir de
sus predicciones ni convierte la revisión de una foto en validación física.

## Antes de etiquetar

Acordar qué significa cada grupo. Persona 1 usa Lab completo: no separa únicamente
luminosidad. Por tanto, evaluar con una regla nueva de «más claro/más oscuro»
puede medir desacuerdo entre criterios, no un fallo de su algoritmo. Escribir el
criterio visual de cada grupo y mantener una correspondencia explícita con los
nombres `color_group_1` y `color_group_2`. Si no se puede establecer una separación
visual defendible, no forzarla para justificar la receta: registrar incertidumbre
y revisar la política de clases con persona 1.

Los criterios pueden incluir muestras de referencia identificadas por ID y una
descripción de la diferencia buscada. No copiar la clase predicha como respuesta
humana. Las referencias de material real, cuando existan, son más sólidas que
juzgar una foto afectada por luz y cámara.

## Página de anotación

```bash
python3 -m demo.person1_visual --output-dir artifacts/person1_reference_new
```

Abrir el HTML generado con `?review=1` al final de la URL, o activar **Hide
predictions for reference labeling**. Se ocultan el plan, los scores, clases y
colores de decisión; quedan cajas neutras con los IDs y la foto original.
Esto reduce la exposición en pantalla, pero no garantiza una revisión ciega:
el revisor puede haber visto predicciones anteriormente. El JSON registra si
la sesión de la aplicación mostró predicciones, sin certificar conocimiento previo.

1. Introducir **Reviewer** y una definición acordada para cada grupo. Hasta
   entonces no se habilita la asignación de clases.
2. Seleccionar una caja de la imagen. En **Your reference group**, asignar un
   grupo o **Uncertain / cannot assess**. No hay respuestas preseleccionadas.
3. Añadir una nota si ayuda. **Next unreviewed piece** recorre IDs todavía sin
   decisión, incluidos los que el filtro automático habría descartado.
4. Las definiciones se bloquean al guardar la primera etiqueta. **Clear all draft
   labels** elimina las etiquetas locales y permite revisar los criterios; no
   modifica el inventario de persona 1 ni los JSON ya exportados.
5. Usar **Export annotations** para conservar una copia. El borrador local depende
   del almacenamiento del navegador: no reemplaza el archivo exportado. **Import
   annotations** restaura una copia; rechaza otra imagen/inventario, duplicados o
   etiquetas inválidas antes de cambiar el borrador actual.

El archivo usa `person1-reference-review-0.1`, vincula hashes de imagen e inventario,
ID de revisor, definiciones y anotaciones. Una pieza no revisada no aparece en la
lista; una dudosa lleva `reference_group: uncertain`. Ninguna de las dos se cuenta
como acierto. No hay etiquetas humanas reales incluidas en esta entrega.

## Evaluar la copia exportada

```bash
python3 -m integration.person1_reference evaluate \
  --annotations /ruta/bricks_70_reference.json \
  --output-dir artifacts/person1_reference_evaluation_new
```

Abrir `index.html` en esa carpeta. `evaluation.json` conserva las cifras, los IDs discrepantes y la huella del
archivo de referencia para distinguir revisiones. Los directorios deben ser nuevos: no se sobrescribe evidencia.
El evaluador utiliza por defecto la imagen, inventario y receta versionados de
persona 1; `--image`, `--inventory` y `--config` permiten especificarlos.

Por cada umbral se muestran: piezas aceptadas, aceptadas con referencia definida,
coincidencias y discrepancias entre referencia/predicción, aceptadas sin decisión
humana definida, piezas descartadas pese a coincidir con el revisor y viabilidad
de la receta. Las fracciones usan solo el denominador revisado y definido. Se
incluyen cobertura total, matriz de confusión y piezas dudosas/no revisadas.

No se recomienda automáticamente un umbral, incluso si todas las etiquetas
coinciden. Una muestra seleccionada o parcial puede estar sesgada. Para calibrar
hay que mantener criterios fijos, revisar imágenes representativas y separar las
usadas para elegir el umbral de las usadas para comprobarlo. Esas decisiones
requieren datos adicionales; esta foto no prueba el comportamiento en el evento.

## Estado inicial y prueba reproducible

```bash
python3 -m integration.person1_reference template \
  --output-dir artifacts/person1_reference_template_new
python3 -m integration.person1_reference evaluate \
  --annotations artifacts/person1_reference_template_new/reference.json \
  --output-dir artifacts/person1_reference_empty_new
```

La plantilla tiene cero anotaciones. La evaluación permanece
`awaiting_reference_labels`, con cero cobertura y fracciones sin valor, no «100 %».
`threshold_validated` y `physical_validation` siguen siendo falsos.

Verificado: 84 pruebas del núcleo, seis nuevas para referencias, cobertura,
incertidumbre, captura incorrecta, exclusiones y no sobrescritura. La prueba de
navegador verifica ocultación, criterios obligatorios, notas, exportación, borrador
tras recarga e importación vinculada; usa etiquetas marcadas TEST que se borran.
No se han usado como evaluación humana real ni incorporado al inventario.
Evidencia local en `artifacts/person1_reference_ready/` y
`artifacts/person1_reference_tests.log`; evaluación inicial vacía en
`artifacts/person1_reference_baseline_ready/`.
