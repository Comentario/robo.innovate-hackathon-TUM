# Laboratorio visual — persona 2

## Ejecutar y abrir

Desde la raíz del repositorio, sin instalar dependencias:

```bash
python3 -m planning.visualize
```

Abrir `artifacts/mixing_comparison.svg` en el navegador o con una vista previa
SVG de VS Code. Es una imagen vectorial local, sin servidor ni conexión a Internet.
El JSON contiguo conserva los planes completos, IDs, métricas y rechazos.
Para seleccionar otra entrada/salida:

```bash
python3 -m planning.visualize --scenarios data/scenarios.json --output artifacts/comparison.svg
```

En cada escenario las columnas son `mixed` / `smooth`; la primera fila usa
`reject` y la segunda `redistribute`. Cada plan muestra todas sus capas. Los
números sobre los ladrillos son pasos de colocación globales; el título de cada
celda contiene su ID y posición. Los colores y tonos son ilustrativos.

## Escenarios reproducibles

Cuadrícula 2 × 3 × 2: 12 posiciones, receta objetivo 4 oscuros, 4 medios y 4 claros.

| Inventario | Resultado estricto | Selección redistribuida | Error L1 |
|---|---|---|---|
| 6 oscuros, 6 medios, 6 claros | cumple receta | 4 / 4 / 4 | 0 |
| 14 oscuros, 2 medios, 2 claros | rechaza | 8 / 2 / 2 | 0.667 |
| 9 oscuros, 0 medios, 9 claros | rechaza | 6 / 0 / 6 | 0.667 |

Los dos modos parten de la misma selección. L1 es la suma de diferencias
absolutas entre proporciones reales y objetivo; no es un porcentaje de error.
Los vecinos incluyen izquierda/derecha, arriba/abajo y capas adyacentes.
La distancia media usa dark=0, medium=0.5, light=1 en ambos modos, para poder
compararlos; no se modifican las métricas originales del contrato del planificador.

## Lo aprendido

- En el caso equilibrado, `mixed` produce 3 pares iguales de 20 y distancia
  media 0.675; `smooth` produce 8 de 20 y distancia 0.350. La receta es idéntica.
- Sin tono medio, `mixed` alterna los dos extremos: 0 pares iguales y distancia
  1.000. `smooth` forma zonas: 14 pares iguales y distancia 0.300.
- Menor distancia local no equivale automáticamente a mejor aspecto industrial.
  Ningún modo debe elegirse solo por una métrica aislada.
- Una receta imposible debe seguir siendo un rechazo con política estricta;
  el visualizador no cambia de política a escondidas.

## Criterio de revisión provisional

Mantener `mixed` + receta explícita + `reject` como punto de partida de la demo.
Conservar `smooth` como alternativa para discutir muestras con Marmon. Revisar
manualmente las capas, la desviación de receta y los agrupamientos antes de
escoger una política. No fijar umbrales de aceptación hasta contar con muestras
y con la apariencia deseada para paquete/pared.

Siguiente integración: acordar IDs/categorías y disponibilidad con persona 1;
reservas, confirmaciones y recuperación ante fallos con persona 3. El laboratorio
no modela poses, estabilidad, agarre, cámara ni construcción de una pared.
