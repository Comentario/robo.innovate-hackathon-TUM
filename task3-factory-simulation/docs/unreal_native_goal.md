# Checkpoint completado: Brickflow nativo en Unreal

Actualización posterior: la versión de vídeo sin UI y con seguimiento a 1× se
documenta en `unreal_tracking_film.md`. Las capturas y pruebas de UI de este
documento corresponden al checkpoint anterior.

Referencia solicitada: `artifacts/greenfield_30/index.html`, SHA-256
`7573180b519dfa27f1b97b6cd682659b5235f129f1ad7d4f9b73f25db808805b`.
Modelo incluido: `572c87cac2f8addb`. El JavaScript actual coincide con el modelo
embebido al fijar esta referencia. Mantener esa referencia aunque continúen
otros cambios en el repositorio.

El propietario pide recrear **toda la simulación en Unreal**, con lógica C++ o
Blueprints y una presentación propia. No basta con reproducir los fotogramas
de Blender, un vídeo, un USD animado o ejecutar Python/JavaScript ocultamente.
Los scripts de preparación pueden extraer datos y construir assets, pero el
programa entregado debe simular y actualizar la escena por sí mismo en Unreal.

Se activó un Goal persistente en este hilo. No existe una skill local llamada
`goal`; se consultó la función Goals documentada por OpenAI:
https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex .
El objetivo solo estará completo tras comprobar los resultados y los artefactos.

## Arquitectura y criterios de terminación

1. Instalar el ZIP Linux Unreal 5.8.4 facilitado por el propietario en Brev;
   comprobar editor, Vulkan y RTX PRO 6000.
2. Implementar núcleo determinista C++: eventos, recursos, reservas, transporte,
   inspección, rechazo, buffers finitos, receta, formación, apilado y despacho.
3. Contrastar Mixed y Single con la referencia fijada, incluida identidad de
   material, pureza, ausencia de duplicados, conteos, tiempos y composición de
   pallets. Documentar cualquier divergencia; no ajustar las cifras para ocultarla.
4. Crear escena nativa de Unreal, con geometría instanciada, mecanismos completos
   y movimiento derivado del estado C++. USD/Blender sirven como comparación y
   como origen opcional de assets estáticos, nunca como motor de simulación.
5. Implementar controles de reproducción, cámaras, selección de receta y cambios
   en el límite del pallet, conservando identidad, grupos y scores del productor.
6. Construir una interfaz original profesional en Slate/UMG. Verificar que todas
   las métricas procedan del mismo estado nativo y mantengan su interpretación.
7. Ejecutar en Unreal, verificar el flujo completo y entregar build/proyecto,
   imágenes y secuencia de pitch con evidencia y límites. Guardar checkpoints
   locales y commits coherentes en `persona2/planning`.

## Dirección de presentación

El propietario solicita una experiencia al nivel visual de una presentación
tecnológica de Silicon Valley. No se reproduce el dashboard WebGL anterior.

- Escena de fábrica protagonista, con encuadres y transiciones de cámara guiados.
- Fondo grafito, tipografía sobria, espaciado amplio, acentos discretos, materiales
  industriales y luz de producto. No incorporar logotipos de terceros.
- Capítulos: **Overview**, **Perception**, **Blending**, **Formation**, **Dispatch**,
  **Evidence**. Rótulos y controles visibles en inglés.
- Métricas principales con jerarquía clara: **Estimated shipped bricks/h**,
  **Completed pallets/h**, **Inspection progress**, **Complete output**.
- Reproducción y velocidad accesibles; evidencia técnica bajo demanda. No llenar
  la escena de paneles, etiquetas o detalles de implementación por defecto.
- Mostrar la base del lote y el carácter modelado/sintético. No introducir ROI,
  inversión, energía o mejora de capacidad sin evidencia de esta misma revisión.

## Referencia numérica

Los replays incluidos en revisión 30 registran:

| Modo | Inspeccionados | Rechazados | Formados | Pallets completos | Tiempo del lote, s | Conformes expedidos/h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 28,800 | 3,468 | 24,960 | 42 | 9,022.226535951013 | 9,384.823099110414 |
| Single | 28,800 | 3,468 | 24,960 | 36 | 9,112.457967568462 | 7,964.481181510014 |

Son equivalentes horarios de un lote sintético; no mediciones industriales.
Las recetas son heurísticas de la demo, no requisitos oficiales de Marmon.
Los grupos/colores y aceptabilidad se generan con semilla; no fingir percepción
independiente de persona 1. Los ACK sintéticos tampoco son validación visual.

## Checkpoint de implementación

- [x] Objetivo fijado y fuente 30 identificada por hash.
- [x] Archivo Linux Unreal 5.8.4 identificado, 39,819,212,076 bytes.
- [x] Transferencia e instalación de Unreal completadas; SHA-256 coincide con el ZIP original.
- [x] Núcleo C++ de eventos/recursos probado con sanitizadores.
- [x] Modelo completo C++ contrastado con Mixed/Single (conteos y los 78 pallets).
- [x] Escena nativa y UI propias verificadas en Unreal y ejecutable Linux.
- [x] Build Linux y material de pitch entregados y respaldados.

Los archivos nuevos del núcleo están bajo `unreal/Brickflow/Source/Brickflow/Core`.
El runtime usa coroutines C++20, orden estable de eventos y recursos finitos.
No se incorporan cambios al modelo JavaScript de referencia.

Compilación del núcleo independiente: Clang 20.1.8 incluido en el mismo ZIP de
Unreal, C++20, sin `fast-math` y con `-ffp-contract=off`. GCC 11 del WSL presenta
un fallo interno al compilar las coroutines de ensamblado; no se usa para ese
binario. El runtime aislado pasó AddressSanitizer/UBSan/LeakSanitizer fuera del
sandbox (LeakSanitizer no funciona con su aislamiento).

`tests_native/simulation_run.cpp` ejecuta la simulación completa en C++ sin
Python, JavaScript ni Unreal. `tests_native/compare_reference.py` es solo una
herramienta externa de verificación, y compara sus resultados con las cachés
fijadas. Para Mixed y Single coinciden todos los IDs y su orden dentro de cada
pallet, lane, carro y posición de salida, conteos y receta. Los errores de
tiempo son inferiores a 1e-7 s, la tolerancia de comparación. Los resultados se
guardan en `artifacts/cinematic/reference_30/comparison.json`.

También se compararon 1,218 muestras de poses con la función `pose` del
JavaScript original (612 Mixed y 606 Single), cubriendo traslación, giro,
movimientos rígidos y caminos. Error máximo de componente: 1.137e-12.
El test `tests_native/compare_poses.js` conserva el resultado bajo los artefactos.

El proyecto `unreal/Brickflow/Brickflow.uproject` compila con Unreal 5.8.4 en la VM.
Usa interfaz Slate original, cámaras, reproducción, búsqueda temporal, recetas
y geometría instanciada con drivers C++. La configuración exige Skin Cache para
ray tracing; el primer arranque detectó y corrigió esa omisión. El lanzamiento
gráfico posterior terminó con código cero y generó captura y evidencia nativas;
la revisión de imagen y comparación de esa evidencia continúan.

Instalación remota: `/home/shadeform/workspace/brickflow-cinematic/tools/unreal-5.8.4`.
Proyecto remoto: `/home/shadeform/workspace/brickflow-native`.
El archivo descargado directamente en cloud se verificó contra el original:
`cdff1e0c02010eb4fcf9c38d293cfd0f1afda09272256c146d73db52f570f607`.
Los enlaces de descarga temporales se mantuvieron fuera del repositorio y se
eliminaron tras verificar el archivo.

El lote Mixed completo pasó también AddressSanitizer, UBSan y LeakSanitizer con
Clang 20.1.8 (10,152,491 eventos; sin diagnósticos de memoria). La ejecución
dentro de Unreal coincide con los 42 pallets y los 23,520 IDs expedidos de
Mixed. El ejecutable Linux empaquetado coincide con los 36 pallets y los
20,160 IDs expedidos de Single, error máximo de tiempo 9.095e-13 s.

Se revisaron las capturas `artifacts/unreal_native/mixed-chapter0.png` y
`single-chapter3-packaged.png`: fábrica y UI renderizadas en Vulkan con la GPU
NVIDIA. La conversión Y/Z ya convierte el winding CCW de Three al CW de Unreal;
no debe invertirse una segunda vez. La iluminación cubre la longitud de la
instalación. Los materiales tienen activado el uso con instancias estáticas.

`unreal/tools/package_cloud.sh` genera el ejecutable Linux con BuildCookRun;
`preview_cloud.sh` acepta `-BrickflowPackaged` para comprobarlo sin editor.
La preparación Python solo crea assets en el editor, y sus plugins se excluyen
del target Game. La exportación JSON contiene geometría y bindings, no tracks
de reproducción. El estado de cada brick lo calcula el núcleo C++.

El modo `-BrickflowMovie=... -BrickflowMovieFrames=576` captura 24 segundos a
24 fps, con un segundo simulado por fotograma. Recorre los seis capítulos con
cámaras nativas. Es captura offline acelerada, no prueba de rendimiento a 24 fps.
El vídeo final `artifacts/unreal_native/brickflow-native-pitch.mp4` tiene 576
fotogramas, 1920×1080, 24 fps y 24 segundos; se revisaron las vistas Overview,
Perception y Evidence. Se conserva la distinción entre lote completo y métricas
del instante visible. La captura es silenciosa y deja espacio a la narración
del presentador.

El build Linux está respaldado localmente en
`artifacts/unreal_native/brickflow-linux-native.tar.gz` (505 MiB); SHA-256 local
y remoto coinciden:
`5a37fd38bb2955c61a089ba5b21bb4eea092d5fbf9fa551eb2d6b7ff1be4ef8b`.
Corresponde al checkpoint de presentación `4403871`; la prueba automatizada
posterior añade un flag diagnóstico, sin cambiar el comportamiento normal.
SHA-256 del vídeo: `644f0fa9ab7e48eb4fc7e229e08ab752dab31e790d1009dd8dbb31ea8355dc95`.

El flag diagnóstico `-BrickflowExerciseControls` llama los mismos handlers que
usa Slate: alternar reproducción, recorrer velocidades, cambiar capítulo,
buscar tiempo, solicitar Single durante Mixed y reiniciar. La prueba en el
editor completó los tres recálculos y recuperó la referencia Single exacta
(36 pallets, 20,160 IDs). La comprobación equivalente en el ejecutable
empaquetado también pasó: mismos 36 pallets y 20,160 IDs, error máximo
9.095e-13 s. Es una prueba automatizada de los handlers nativos; no sustituye
una prueba manual de usabilidad ni una validación física del proceso.

El proyecto y las herramientas quedan guardados en `persona2/planning`.
La VM continúa activa a la tarifa indicada de $2.63/h; no se eliminó la instancia.
