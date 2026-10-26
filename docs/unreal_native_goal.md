# Objetivo activo: Brickflow nativo en Unreal

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
- [ ] Transferencia e instalación de Unreal completadas.
- [x] Núcleo C++ de eventos/recursos probado con sanitizadores.
- [x] Modelo completo C++ contrastado con Mixed/Single (conteos y los 78 pallets).
- [ ] Escena nativa y UI propias verificadas en Unreal.
- [ ] Build y material de pitch entregados y respaldados.

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
