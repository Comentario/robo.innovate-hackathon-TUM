# Versiones de superposición para elegir

Se conserva V1 y se generaron cinco variantes nuevas, V2–V6. Cada una tiene
28 segundos, 840 frames a 30 fps, archivo 4K y revisión 1080p. Todas muestran
el mismo intervalo del render y el mismo ciclo físico del Franka a 1×.

La ubicación de entrega solicitada es:
`D:\Hackathon\Munich Hackathon 2026\Videos_Unreal\`.
Abrir `Review_Index.html` para acceder al comparador y a la prueba de inspección.
La copia antigua de V1 en `Brickflow-Franka-Overlay-v1` también se conserva.
`Base_Render_Current` reúne los MP4 4K y 1080p de la película completa que sirve
de fuente para estas pruebas; no se recodifican al centralizarlos.

## Opciones del Franka

| Versión | Cambio de composición | Criterio para elegir |
| --- | --- | --- |
| V1 · Original | Retrato grande a la derecha, esquinas redondeadas y sombra. | Referencia guardada sin cambios. |
| V2 · Right compact | Retrato derecho menor, sombra más ligera y fundidos algo más largos. | Buen equilibrio entre legibilidad del robot y contexto de la planta. |
| V3 · Left compact | Posición a la izquierda. | Deja el array de entrada despejado, pero tapa parte del subbelt receptor; menos adecuada para explicar el depósito. |
| V4 · Soft overlay | Bordes difuminados, sin sombra y opacidad 94 %. | Integración más suave; parte de la simulación se transparenta por detrás del vídeo real. |
| V5 · Lower-right inset | Retrato pequeño en esquina inferior derecha; salida más temprana. | Máxima presencia de la planta, a costa de ver el brazo más pequeño. |
| V6 · Floating right | Retrato derecho con entrada lateral/vertical muy suave y esquinas algo mayores. | Opción más dinámica; la posición termina de asentarse antes de la fase central del agarre. |

Para comenzar la selección, comparar V2 y V5 frente a V1. Es una recomendación
editorial, no una elección aprobada por el propietario. Los clips individuales
no llevan rótulos ni métricas. El mosaico de seis sí lleva nombres para revisar.

El comparador `Franka_Variants/index.html` permite seleccionar dos versiones,
usar una barra temporal común y saltar al fundido, traslado, depósito o salida.
Incluye acceso a cada 4K. `compare-six.mp4` muestra las seis a la vez.

El compositor ahora acepta `--layout-profile`; sin perfil conserva el layout
original. El filtro por defecto se comparó byte a byte con el de V1. También
se comprobaron los hashes de ambos MP4 originales antes y después de las cinco
codificaciones. El preset versionado es
`unreal/editorial/franka-overlay-variants.json`.

Los doce MP4 se verificaron en la VM mediante conteo decodificado completo,
duración, timestamps PTS uniformes, DTS creciente y SHA-256. La galería abrió
en Chromium, cargó las seis opciones y respondió al seek y reproducción
sincronizados sin errores de JavaScript. La revisión visual por muestras se
registra separadamente; esas pruebas técnicas no sustituyen la evaluación del
montaje por parte del propietario.

## Inspección con una sola cámara

Se usa `Demo_Video1.mp4`, 848 × 658, 319 frames a 30 fps: 10,633 s de una única
vista de ladrillos reales con cajas, etiquetas GOOD/BAD e IDs ya grabados.
SHA-256: `9649e3d6f42b9591d8dfdbb7b99ef796abc4dbb3e5da712afa5b24dba104c354`.

La prueba `Inspection_Overlay_v1` utiliza el intervalo 01:58–02:26 del render
actual: acercamiento al sensor, pausa original de inspección y rechazo.
La única superposición aparece en la zona superior izquierda para dejar el
portal de inspección y la salida de descarte visibles. Entra entre 02:09 y
02:10,200 del film y sale entre 02:19,200 y 02:20,800. El vídeo fuente se muestra
completo a 1× y sostiene brevemente su última imagen durante el fundido final.

No se añadieron una segunda fuente, nuevas clasificaciones, cambios de score
ni correspondencias entre IDs físicos y sintéticos. Las detecciones son las
que aparecen en el archivo proporcionado; este montaje no demuestra su
precisión ni una ganancia de exactitud por dos cámaras. La salida 4K escala la
fuente de 848 × 658 y no añade detalle óptico al vídeo original.

Herramientas: `unreal/tools/composite_inspection.py` y
`unreal/tools/build_franka_choices.py`. Son ediciones del render existente,
no nuevas películas de la planta pendiente de validación.

## Entrega y comprobaciones

`Videos_Unreal/Review_Index.html` reúne el comparador, la inspección y la
película completa. Se entregan 17 MP4: seis opciones del Franka en 4K y 1080p,
inspección en ambas resoluciones, base completa en ambas resoluciones y mosaico
de comparación de seis vistas. El mosaico conserva el aspecto de cada clip en
un lienzo de 1920 × 720; los MP4 de evaluación individuales son 1920 × 1080.

Se comprobaron las muestras de entrada, traslado, depósito y salida de las
seis composiciones, además de nueve imágenes de inspección. Las copias en
Windows coinciden por SHA-256 con las fuentes verificadas. Los enlaces del
índice y las seis selecciones de la galería se comprobaron tras la entrega.
V1 y el render base completo mantienen sus hashes previos.

`unreal/tools/export_video_reviews.py` permite repetir la entrega y generar su
manifest. La opción `--windows-native` usa CopyFile y SHA-256 de Windows; el
modo de reanudación solo sustituye copias parciales menores de esta carpeta
generada y conserva cualquier archivo distinto de tamaño completo. Las copias
temporales se verifican antes de publicarse con su nombre final.
