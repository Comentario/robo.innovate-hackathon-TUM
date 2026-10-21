# Persona 1 → planificación → brazo de referencia

La clasificación pertenece a persona 1: recibe RGB, mide Lab (luminosidad y
cromaticidad), agrupa con K-means y entrega sus clases en JSON. Nuestro flujo
consume ese resultado; no vuelve a clasificar ni añade revisión manual.

## Ejecutar la integración

Con las dependencias del brazo de referencia preparadas, desde la raíz:

```bash
python3 scripts/rehearse.py person1
```

Arranca MoveIt/RViz, lee `examples/person1/inventory_with_color.json`, planifica
el pallet y ejecuta sus doce colocaciones con los IDs originales. Cierra con
Ctrl+C; el journal, informe y entrada quedan guardados en un directorio nuevo.

Para usar otra entrega, basta especificar su JSON enriquecido:

```bash
python3 scripts/rehearse.py person1 --inventory /ruta/inventory_with_color.json
```

Una receta propia se pasa con `--recipe /ruta/recipe.json`. Debe utilizar los
nombres de grupo que realmente contiene el inventario. Por defecto se usan
pesos iguales entre sus grupos, política mixed y receta estricta: es una
hipótesis del equipo, no una nueva clasificación ni un requisito oficial.

El contrato admite el número de grupos entregado: uno (`uniform`), dos o tres
(`color_group_N`). K-means no tiene que producir siempre tres. El JSON de pallet
versionado tiene dos; la exportación `wall_exposure_light.json` de persona 1
tiene tres y también se comprobó en planificación/preparación de la simulación.

## Qué se conserva y qué se simula

`integration.person1_simulation.prepare_person1_simulation`:

1. Lee la exportación a través del adaptador de contrato. Conserva IDs, grupos,
   scores, centros Lab y cajas px. No mide color ni ejecuta K-means.
2. No aplica un filtro de score adicional (`min_score=0`): las 70 clasificaciones
   del pallet se aceptan tal como llegan. Respeta unknown y flags de no elegibilidad
   declarados por persona 1, sin inventar clases para esos casos.
3. Genera el plan con nuestro planificador existente y selecciona doce IDs.
4. Prepara una escena sintética nueva solo con esos doce. Las otras 58 piezas
   permanecen en el inventario de origen; no se declaran recogidas ni descartadas.
5. Compila las mismas ocho fases por pieza y utiliza el adaptador Panda,
   planificación de trayectorias, pinza, objetos adjuntos y journal existentes.

El snapshot de entrada sigue siendo `source=perception`, sin poses métricas.
Se conserva completo en `person1_handoff.json`. El snapshot de staging es otro
objeto, `source=synthetic`, vinculado al anterior y a su plan; sus coordenadas
proceden de la cuadrícula de la maqueta, no de convertir píxeles a metros.
Por eso no se elimina la protección de ejecución de percepción sin poses medidas.

Los colores de RViz se dibujan convirtiendo **los centros Lab ya entregados** a RGB
con OpenCV. Esto solo representa el color en pantalla; no calcula grupos ni
reclasifica piezas. La planificación no depende de OpenCV; esta representación
opcional del brazo sí usa OpenCV/NumPy, disponibles en el entorno probado.

La escena tiene piezas en miniatura, dimensiones y posiciones de la maqueta.
No reproduce el apilamiento físico ni la accesibilidad de la foto de origen.
No identifica caras ocultas. Sigue siendo reproducción cinemática, sin robot
real ni calibración de cámara. La validación física continúa pendiente.

## Evidencia de este avance

- La revisión manual añadida se retiró en un commit de reversión independiente.
- Ejecución completa real de MoveIt/RViz con el JSON de pallet: doce IDs originales,
  grupos intactos, 96 acciones confirmadas en la escena, sin filtro adicional.
- Otro ciclo a velocidad 3 completó también las doce posiciones. Su captura
  muestra en RViz el ID, grupo, procedencia y número de piezas en staging.
- Exportación real de tres grupos: 104 piezas elegibles, doce posiciones con
  cuatro de cada grupo y preparación geométrica correcta. No se presenta como
  un segundo ensayo articulado de tres grupos ni como una pared recogible.
- 82 pruebas del núcleo y 12 del adaptador pasan. Las pruebas nuevas verifican
  la conservación de los scores más bajos, uno/dos/tres grupos, receta configurable,
  staging separado del dato real y ausencia de llamadas K-means en la conversión
  de color para pantalla.

Artefactos locales: `artifacts/person1_arm_integration_01/` contiene el ciclo
completo, `person1_handoff.json`, `result.json`, journal y resumen HTML.
`artifacts/person1_arm_visual_check/rviz_person1.png` muestra la integración
articulada; ese ensayo también terminó en completed. La preparación real de tres
grupos se guardó en `person1_arm_integration_01/three_group_preflight.json`.

## Continuación modular

Ya está conectado el intercambio por JSON hasta la ejecución del simulador.
El código productor sigue en la rama de persona 1: no es necesario copiarlo al
planificador para consumir sus archivos. Un futuro SDK sustituirá el adaptador del
robot; las poses medidas/calibradas sustituirán la geometría sintética. El escenario
recovery existente conserva su fixture de demostración; la combinación de esa
recuperación con este nuevo escenario puede incorporarse como siguiente incremento.
