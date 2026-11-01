# Demo animada local

Generar desde la raíz:

```bash
python3 -m demo.browser
```

Abrir `artifacts/brick_demo.html` en Chrome, Edge u otro navegador moderno. Es
un único archivo con datos, estilos y JavaScript incluidos: no requiere servidor,
Internet, dependencias nuevas ni instalación de extensiones. Después de cambiar
fixtures o planificador, regenerar el HTML y recargar el navegador.

## Guion de demostración (interfaz en inglés)

1. La página abre en **Different shades on each face**. Todos los frentes son
   oscuros; las caras posteriores permiten cubrir la receta 4/4/4.
2. Pulsar **Play** para ver colocaciones por capas. **Next step**, **Pause** y
   **Reset** permiten inspeccionar el proceso. **Show target pattern** muestra u
   oculta las posiciones futuras; las confirmadas aparecen con color completo.
3. En **Next pick**, revisar las caras observadas, la cara seleccionada y la
   orientación. El top no observado tiene una muestra rayada y nunca se elige.
4. Elegir **Before pick 5** y reproducir: cada modo confirma 4 colocaciones,
   señala el fallo y se detiene. Reset inicia una simulación nueva, no reanuda.
5. Cambiar a **Front faces only**: con **Reject impossible recipes**, ambos
   planes se rechazan aunque existan colores útiles en reversos no permitidos.
6. Elegir **Redistribute and report deviation**: se completa con frentes oscuros
   y se publica el error de receta. Comparar con los otros tres inventarios.

Las métricas marcadas **Final** describen el plan objetivo completo desde el
inicio; **Placed** cuenta únicamente confirmaciones de la animación. Los colores
son representativos de categorías, no mediciones fotométricas.

## Qué está conectado

El generador llama al planificador real y a `run_demo` para ambos modos/políticas,
con y sin fallo. El navegador reproduce esos resultados precomputados: no
reimplementa la selección de caras ni inventa colocaciones. Los controles no
modifican la receta arbitrariamente; se comparan las variantes precalculadas.

Se evalúa una cara de exposición por ladrillo; no es una simulación 3D, física,
de cámara, agarre o pared. Las orientaciones permitidas del ejemplo son
sintéticas. Ver `faces.md` para datos, contrato v0.3 y limitaciones.

## Verificación

```bash
python3 -m unittest discover -s tests -v
python3 tests/build_browser_smoke.py
```

El segundo comando genera `artifacts/brick_demo_smoke.html`. Abrirlo para
comprobar controles, reproducción temporizada, detención, recetas imposibles,
redistribución y reset. El resultado PASS/FAIL aparece al final. Es una página de
pruebas separada; para presentar, abrir `brick_demo.html`.

La implementación se comprobó con Edge headless: ejecución de JavaScript,
controles y reproducción aprobados, y captura de escritorio revisada. No se ha
verificado todavía con muestras reales ni con una celda robótica.
