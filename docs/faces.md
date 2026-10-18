# Tonalidad por cara — propuesta v0.3

Un ladrillo puede tener tonos distintos en cada cara. No se debe inferir el tono
de una cara oculta a partir de otra. Se conserva la API v0.2 de categoría por
ladrillo y se añade `planning.faces.make_face_plan` como extensión independiente.

## Entrada

Cada ladrillo contiene `id`, `faces` y `allowed_orientations`:

```json
{
  "id": "brick_01",
  "faces": {
    "front": {"color_group": "dark"},
    "back": {"color_group": "light"},
    "top": null
  },
  "allowed_orientations": [
    {"id": "front_out", "visible_face": "front"},
    {"id": "back_out", "visible_face": "back"}
  ]
}
```

`null` o ausencia de una cara significa no observada. Solo se eligen caras
observadas y referenciadas por una orientación permitida. Las caras observadas
pueden incluir metadatos adicionales, pero el MVP consume su `color_group`.
Los identificadores de caras están ligados al ladrillo físico; percepción debe
mantenerlos estables, incluso si el ladrillo se mueve.

Las orientaciones las declara integración según el agarre permitido. En los
fixtures son hipótesis sintéticas, no capacidades verificadas del robot. Un
`orientation_id` no es todavía un ángulo, pose o instrucción de giro ejecutable.

## Selección y salida

Se exige receta explícita. Primero se calculan cuotas enteras con la misma regla
que v0.2. Una asignación por emparejamiento busca ladrillos distintos cuyas caras
permitidas cubran esas cuotas; puede reasignar un ladrillo flexible para preservar
otro tono escaso. Con `reject` se rechaza si no existe tal asignación. Con
`redistribute` se cubren las cuotas posibles y se completa por déficit de tonos
entre los candidatos restantes; esta sustitución es heurística.

Después, el patrón mixed/smooth y la secuencia se calculan con la cara elegida.
La salida usa `schema_version="0.3"`; cada placement añade `visible_face` y
`orientation_id`. `face_policy` identifica caras permitidas no observadas,
ladrillos sin candidatos observados y el origen declarado de orientaciones.

Esta versión optimiza una sola cara de exposición por posición. No evalúa a la
vez frontal/lateral/superior ni predice el aspecto de una pared al desempaquetar.
Los valores de tono de smooth siguen siendo representativos de la categoría,
no medidas calibradas por cara ni una descripción de textura.

## Reproducir

```bash
python3 -m demo --face-aware --inventory examples/faces/inventory.json --config examples/faces/config.json --output artifacts/faces_run.json
```

En este ejemplo todos los frentes son oscuros. Para cumplir 4/4/4, el planificador
debe elegir algunas caras posteriores. Los tops no observados nunca se usan.

## Acuerdos pendientes

Qué caras cuentan en el paquete y en la pared, orientación de exposición por
posición, giros físicamente permitidos, textura/variación dentro de una cara y
cómo adquirir/calibrar observaciones múltiples sin perder identidad.
