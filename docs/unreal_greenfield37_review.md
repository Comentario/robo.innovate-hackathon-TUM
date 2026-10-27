# Estudio de greenfield_37 para Unreal

Estado: **referencia no validada; preparación de autoría, sin película nueva**.
Se trabajó en `brickflow-cinematic-4gpu`. La simulación nativa sigue fijada a
greenfield_30; este estudio no sustituye su geometría ni su lógica.

## Referencia observada

El archivo `artifacts/greenfield_37/index.html` se regeneró durante la revisión.
Se conservaron dos observaciones separadas por SHA-256:

- Inicial: `9a2d911750e252a69ad737b009704a9c6440722aa08c67bfd14a04681018bb2c`.
- Actualizada: `699975328736402c8da79fce60c6423bbea461d52371ee17be9c58fa7bfacb6f`.

La segunda añadió optimizaciones de selección y reservas, corrigió el handoff
al eje de la lane (`job.lane.z`) y cambió la representación de las superficies
de transporte por cassettes de rodillos con LOD. El análisis final y los activos
candidatos corresponden a esa segunda copia, conservada en
`artifacts/unreal_migration37/reference-input/`.

Esa copia no incluye replay preparado; para observar su modelo se usó el modo
explícito `?build` de su propio viewer. No se modificó la lógica de la referencia.
Que sus comprobaciones internas terminen no equivale a validación independiente.

## Recorrido realizado

Se abrió el ejecutable real de Unreal, se cambió de perspectiva mediante sus
controles y se orbitó/ajustó zoom con ratón. Se observaron la planta completa,
la inspección, la formación y el despacho. Las capturas internas
`artifacts/unreal_migration37/native-camera/` pertenecen a la base nativa 30.

En el viewer 37 se recorrieron los ocho presets y se revisaron vistas de
almacén, carga y planta completa. Se conservaron posiciones y orientación de
las cámaras, además de su conversión a Unreal: centímetros, Z vertical y FOV
horizontal equivalente. No son una secuencia de vídeo.

## Diferencias que afectan a la adaptación

| Área | Núcleo Unreal actual | Referencia 37 observada |
| --- | --- | --- |
| Alimentación | Un cart, 28.800 ladrillos | Dos carts consecutivos, 57.600 ladrillos; retorno transversal del vacío |
| Producción | Política Mixed/Single por fase | Lanes pares Mixed y lanes impares Single simultáneamente; 18 wells activos |
| Final de recorrido | Pallet terminado y transporte de salida | Handoff, AMR, almacén clasificado, muelle y camión |
| Almacén | Sin ese ciclo logístico | Cuatro productos con nueve posiciones finitas cada uno |
| Transporte | Registros y movimientos del modelo 30 | Cuatro AMR omnidireccionales y sus horquillas; reservas de tareas completas |
| Pedidos | Sin ese ciclo | Cuatro muelles, pedidos de ocho pallets y salida de camiones |
| Visibilidad | `visible` de inicio | También `hiddenAt` para material y vehículos expedidos |
| Geometría | Instancias del esquema nativo v1 | Rodillos detallados y 57 grupos LOD; requiere decodificar lotes compactos |

Los nombres, capacidades, dimensiones y reservas son configuración/heurísticas
de esta demo. Las formas del almacén no son CAD verificado del fabricante.
La clasificación `good/shade` de esta referencia es sintética. El futuro puerto
debe conservar grupos y scores del productor mediante el intake adapter.

El cargador actual devuelve la transformación base cuando no encuentra un
registro. Cargar únicamente los meshes nuevos dejaría actores inmóviles.
Faltan tipos nativos para `cartShuttle`, `amr`, `amrFork`, `dockLift` y `truck`,
además del segundo cart, su material y las transiciones de logística.

La separación prevista es: producción/planificación simultánea en el núcleo;
almacén, pedidos y tráfico en un módulo logístico; bindings/visibilidad/LOD en
la escena; cámaras derivadas de eventos y coordenadas. Las métricas JSON deben
distinguir `produced`, `stored`, `loaded` y `shipped`.

## Observaciones de la ejecución sintética

Las dos copias observadas dieron estos acumulados:

| Contador | Observado |
| --- | ---: |
| Ladrillos inspeccionados | 57.600 |
| Ladrillos rechazados | 7.020 |
| Pallets completos producidos | 90 |
| Pallets que pasaron por almacenamiento | 90 |
| Pallets cargados y expedidos | 64 |
| Stock final en posiciones de almacén | 26 |

Se observan 10 posiciones libres y 26 ocupadas al final. El cierre de entrada
no significa que todos los pallets se hayan expedido: la política del código
espera ocho pallets del producto para comenzar el siguiente pedido.

Hay un punto visual concreto pendiente de revisión: los registros de camiones
de pedidos posteriores tienen `visible=0`. Su aparición puede preceder a la
creación del pedido y superponerse en la posición inicial. Se observó en las
vistas y en los registros; no se corrigió silenciosamente la referencia.

## Preparación disponible

Carpeta local:
`artifacts/unreal_migration37/reference37-69997532-compact/`.
Misma preparación en la VM:
`~/workspace/brickflow-native/Saved/Exploration37/reference37-69997532-compact/`.

- `source-inventory.json`: actores, movimientos, hitos, productos y pedidos.
- `factory-candidate.json`: geometría de autoría v2, marcada `unvalidated` y
  `nativeSimulationPorted=false`. Conserva 459.782 instancias contando todos los
  niveles LOD; no se dibujan todas simultáneamente. Usa 457 lotes compactos y
  1.464 instancias convencionales, unos 40 MB.
- Texturas PNG y tres vistas WebGL internas para comprender la referencia.
- `camera-bookmarks-unreal.json`: ocho encuadres de estudio con coordenadas UE.
- `migration-contract.json`: diferencias de estado, actores y métricas.
- `preparation-checks.json`: comprobaciones estructurales de materiales,
  geometrías, ocho cámaras y 458.318 matrices de instancias empaquetadas.

`inspect_reference_cloud.py` requiere el hash explícito de la entrada y escribe
en una carpeta de salida separada. `export_geometry.js` conserva su formato
legacy por defecto; el modo de revisión guarda matrices por lotes y LOD.
Estas comprobaciones son de estructura de datos, no de colisiones, mecánica,
percepción física ni requisitos oficiales de Marmon.

El hash de `Content/Data/factory.json` en Unreal sigue siendo
`ccd649ee95efc0ce623106fea8f95181651cb67cf581973c20e981900790f019`.
La base activa y los vídeos existentes se conservaron.
