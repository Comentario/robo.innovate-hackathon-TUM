# Recuperación con el inventario de persona 1

El mismo flujo que consume su JSON y mueve el brazo ahora permite parar y
continuar sin repetir las primeras colocaciones. La clasificación sigue siendo
la entregada por persona 1; no se mide Lab ni se ejecuta K-means de nuevo.

## Ejecutar

Con la celda de referencia libre, desde la raíz:

```bash
python3 scripts/rehearse.py person1-recovery
```

Usar otro inventario y, opcionalmente, otra receta:

```bash
python3 scripts/rehearse.py person1-recovery \
  --inventory /ruta/inventory_with_color.json --recipe /ruta/recipe.json
```

La demostración de recuperación requiere doce posiciones, porque su guion coloca
cuatro y después completa ocho. Sin `--recipe`, reparte pesos iguales entre los
grupos realmente recibidos. El escenario normal `person1` sigue disponible.
Para reproducir los tres grupos con una exportación original versionada:

```bash
python3 scripts/rehearse.py person1-recovery \
  --inventory examples/person1/inventory_three_groups.json
```

La exportación de tres grupos procede de una pared: la demo únicamente utiliza
sus IDs/clases para un staging sintético. No afirma que esa pared sea recogible.

## Qué se ve

1. El brazo coloca las primeras cuatro piezas usando sus IDs originales.
2. Se detiene durante ocho segundos antes de mover la quinta. Es una parada
   inyectada, no un choque ni un agarre físico fallido.
3. Guarda estado y escena y reconstruye solo el cliente. MoveIt conserva el pallet.
4. Contrasta articulaciones/objetos, confirma pinza vacía y vuelve a home con una
   trayectoria comprobada, registrando el intento antes de mover.
5. Crea un ciclo hijo: las cuatro posiciones previas tienen contorno verde y no
   se vuelven a recoger. Ejecuta las 64 acciones de las ocho piezas restantes.
6. Al terminar se ven doce posiciones colocadas. Ctrl+C cierra la demostración;
   se conservan journal, JSON, informes y logs.

No cambia la receta, el patrón de grupos ni los IDs. Continúan los centros Lab
usados para representar los colores en RViz y todos los scores del productor,
sin filtro adicional. Las coordenadas son las de la maqueta, no de la fotografía.

## Continuidad y límites

El nuevo job conserva `person1_handoff` y la procedencia del snapshot de staging.
El reconciliador rechaza cambios de grupo/score de un ID conocido e IDs que no
formaban parte de ese lote simulado. No introduce como sustitutos los IDs que
quedaron fuera del staging: añadir nuevas piezas físicas requiere otra operación
explícita. Esto verifica el contrato, no vuelve a juzgar su clasificación.

El adaptador rechaza la activación si se pierde o cambia esa procedencia. La
transacción conserva el checkpoint y las acciones inciertas del ciclo padre;
el hijo tiene IDs de acción nuevos y excluye todas las acciones de las cuatro
colocaciones preservadas. No reutiliza el ejecutor de acknowledgements para Panda.

La recuperación demostrada reconstruye el cliente mientras el servidor/escena
sigue disponible. No resuelve automáticamente pérdida total del servidor, pinza
con pieza, escena incompleta ni ejecución con un SDK físico desconocido.
La comprobación física de las colocaciones sigue separada de la clasificación
Lab ya realizada por persona 1.

## Evidencia

Se ejecutaron dos ensayos completos reales de MoveIt/RViz:

| Inventario del productor | Grupos | Final | Prefijo preservado | Acciones del hijo |
|---|---:|---:|---:|---:|
| `bricks_70` | 2 | 12/12 | 4, sin cambios | 64 |
| `wall_exposure_light` | 3 | 12/12 | 4, sin cambios | 64 |

En ambos se verificaron las cuatro banderas de `producer_continuity`: procedencia,
IDs/grupos/scores, plan/receta y ausencia de filtro adicional. No se repitieron
acciones de las cuatro primeras piezas. El ciclo padre quedó archivado sin
modificar su checkpoint. Pasan 89 pruebas del núcleo y 14 del adaptador Panda.

Artefactos locales: `artifacts/person1_recovery_01/` y
`artifacts/person1_recovery_three_groups_01/`. `index.html` muestra la propuesta y
el resultado; `summary.html` resume el ensayo. `result.json`, `state.sqlite3`,
`person1_handoff.json`, checkpoints, escena final y logs conservan la evidencia.
`verification.json` contiene comprobaciones posteriores sobre esos resultados.
La captura real `person1_recovery_01/rviz_recovery.png` muestra el final con las
cuatro posiciones resaltadas. El segundo ensayo también terminó correctamente,
aunque su ventana se cerró al finalizar el tiempo de hold antes de capturarla.

La transición al equipo del evento queda preparada en `event_connection.md`.
