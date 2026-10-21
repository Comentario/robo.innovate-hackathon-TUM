# Demo visual: imagen → inventario → plan

La página enlaza los IDs publicados por persona 1 con las detecciones de la
imagen original, el filtro explícito y el planificador de nuestro módulo.
Se abre como archivo local en Edge o Chrome, sin servidor, ROS ni OpenCV.
Todos los textos de la demo están en inglés.

## Generar

Desde la raíz del workspace de Múnich:

```bash
python3 -m demo.person1_visual --output-dir artifacts/person1_visual_new
```

Abrir `artifacts/person1_visual_new/index.html`. El directorio debe ser nuevo;
no se sobrescribe una revisión anterior. El HTML contiene imagen, datos, estilos
y lógica de selección: se puede copiar y abrir por sí solo sin red. Los enlaces
de atribución son opcionales y no intervienen en su funcionamiento.
`review.json` conserva los datos y planes usados por la página.

Entrada fijada: `examples/person1/inventory_with_color.json`, `config.json` y
`bricks_70.png`, de la entrega revisada `3e705b4`. La procedencia y licencia de la
imagen están en `examples/person1/README.md`, y la atribución aparece en el HTML.
La foto no se recolorea. Los bordes indican decisiones, no tonos de material.

## Guion para entender el resultado

1. Con mínimo 0.50, aparecen 70 detecciones, 57 aceptadas, 13 excluidas y doce
   posiciones planificadas. Las otras 45 aceptadas permanecen disponibles: no
   son errores, simplemente no se necesitan para este pallet lógico de doce.
2. Seleccionar `brick_001` en la imagen o en el plan: el mismo ID queda marcado
   en blanco en ambas vistas y en la auditoría. Su score es 0.561, pertenece a
   `color_group_1` y tiene una posición destino. El inspector muestra su recorte
   original y la geometría en píxeles; no inventa la identidad de la cara.
3. Seleccionar `brick_022` en la imagen o tabla: score 0.489, inferior al umbral
   0.50. Aparece excluido con la razón correspondiente y sin destino.
4. Usar **Next planned piece** para recorrer la correspondencia ID → posición.
   El menú **Highlight** atenúa el resto de detecciones sin cambiar el plan.
5. Cambiar el umbral a 0.75: quedan 18 aceptadas y 52 excluidas, pero no hay stock
   suficiente de cada grupo para cumplir la receta 50/50. El plan se bloquea y
   desaparecen todas las tarjetas anteriores. No se rebaja la receta en silencio.
6. A 0.90 queda una pieza y a 0.95 ninguna: no se muestra un plan válido. Volver a
   0.50 restaura el plan de doce posiciones, siempre con seis piezas de cada grupo.

Los seis umbrales disponibles se evaluaron en Python con el adaptador real y
`integration.prepare`. El navegador selecciona esos resultados; no implementa
un segundo algoritmo de planificación. Cambiar receta o añadir umbrales requiere
regenerar la página. No vuelve a ejecutar detección ni clasificación.

## Qué demuestra y qué sigue pendiente

Demuestra el intercambio offline entre percepción y planificación, la trazabilidad
de IDs, las exclusiones y el rechazo de recetas sin stock. La distribución por
capas es lógica; no representa accesibilidad de recogida ni estructura física.

La receta 50/50 y el umbral 0.50 son hipótesis del equipo. El score no es una
probabilidad calibrada. Los grupos son relativos a esta imagen y sus centros Lab;
no equivalen a los marrones dark/medium/light de la maqueta anterior. La imagen
muestra el aspecto real observado. No se predicen las caras ocultas.

No controla el brazo. Siguen pendientes poses métricas/calibración, identidad de
caras, tracking o protocolo de lote estático y validación independiente del pallet.

## Verificación

- 78 pruebas del núcleo pasan; cuatro nuevas comprueban la identidad de los planes
  respecto al planificador, la partición aceptados/excluidos, la protección de
  entradas/salidas y el HTML portable con texto de productor escapado.
- Comprobación real en Edge: contadores, clics imagen/plan, selección por teclado,
  bloqueo de receta, stock vacío, restauración del umbral, filtro de resaltado,
  avance al siguiente ID y ausencia de desbordamiento horizontal a 390 px.
- Evidencia local: `artifacts/person1_visual_final/browser_checks.json`,
  `browser_review.png` e `index.html`; log del núcleo en
  `artifacts/person1_visual_tests.log`.

## Revisión humana de los grupos

La página ahora permite definir criterios y registrar clases de referencia o
incertidumbre sin prellenar predicciones. Abrir con `?review=1` oculta clases y
scores del modelo. Ver `person1_reference.md` para exportar/evaluar la revisión
y comprender por qué esta herramienta todavía no valida un umbral.
