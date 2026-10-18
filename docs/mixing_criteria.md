# Criterios de mezcla v0.1 — decisiones del equipo

## Base oficial

Fuente consultada el 18-10-2026:
https://roboinnovate.mirmi.tum.de/hackathon/hackathon-2026/ — reto #08 Marmon.

El objetivo es formar paquetes visualmente equilibrados con ladrillos cocidos
que tienen variaciones naturales de color. Se permiten mezclas suaves y mezclas
de colores intencionadas; también importa la apariencia de la pared terminada.
Se mencionan superficies texturadas y heterogéneas. No se publican proporciones,
umbrales de calidad, dimensiones ni robot específico para este reto.

## Política provisional, configurable

1. **Receta global**: pesos por categoría, normalizados a proporciones. Los
   ejemplos usan tercios únicamente para demostrar el sistema. Sin receta,
   la API conserva las proporciones del inventario.
2. **Disponibilidad**: jamás repetir IDs ni superar existencias. La demo usa
   `reject`: rechazar si la receta redondeada no se puede cumplir. Alternativa
   `redistribute`: sustituir según disponibilidad y reportar desviación.
3. **Patrón**: `mixed` prioriza evitar categorías iguales vecinas; `smooth`
   prioriza reducir diferencias de tono entre vecinos. Después se busca
   equilibrio en fila/capa. Ambas son heurísticas voraces, no óptimos globales.
4. **Secuencia**: completar capas desde abajo, en orden de fila/columna.
   El adaptador de ejecución deberá validar soporte, agarre y accesibilidad.
5. **Evaluación**: desviación L1 de receta, vecinos del mismo tono y, en modo
   suave, distancia media de tono entre vecinos. Son métricas de diagnóstico,
   no puntuaciones oficiales ni certificados de aceptación.

`config/mixed.json` y `config/smooth.json` permiten cambiar la receta, forma,
modo y política de faltantes sin editar código. Los valores de tono del ejemplo
son sintéticos entre 0 y 1; percepción deberá aportar una escala calibrada.

Reducir distancias locales puede crear zonas o gradientes. Es solo nuestra
primera aproximación a «suave»: habrá que contrastarla con muestras y con la
interpretación de Marmon, incluida la forma en que se extraen los ladrillos del
paquete para construir una pared. No se asume que minimizar distancias locales
sea la receta industrial correcta.

## Fronteras de módulos

- Percepción entrega ID y categoría; sus cambios de detector no alteran el planificador.
- Selección de mezcla decide cantidades, sin coordenadas del robot.
- Patrón distribuye categorías en una cuadrícula lógica.
- Secuenciación asigna IDs y ordena pasos.
- Integración transforma posiciones lógicas en poses y gestiona fallos/reservas.

Confirmar durante el evento: receta y tolerancias, aspecto deseado (paquete y
pared), categorías/escala de tono, caras visibles, geometría, orientación de
capas, acceso a fuentes y criterio del jurado. Si cambia el patrón geométrico,
se sustituye el generador de patrón; si cambia el robot, su adaptador.
