# Render profesional de Brickflow — revisión y ejecución

Fecha de revisión: 26-10-2026. Rama: `persona2/planning`.

## Decisión y estado

Crear una instancia **nueva** de Brev dedicada al render, según la preferencia
del propietario. Primera opción: **1× RTX PRO 6000 Blackwell Server Edition,
96 GB**, GPU completa, Ubuntu 22.04/24.04 x86_64, al menos 16 vCPU,
64 GB RAM y 150 GB SSD; preferibles 128 GB RAM y 250 GB para vídeo.
Comprobar disponibilidad, tarifa y acceso OptiX al desplegar. La captura del
propietario muestra otra instancia de ese modelo a USD 6.96/h; no es una
cotización para la instancia nueva. NVIDIA describe esta GPU como plataforma
para render y gráficos con núcleos RT y 96 GB:
https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/

Usar Blender 4.5 LTS o posterior, con driver compatible con la versión instalada
y con Blackwell. El criterio de aceptación es detectar la GPU real en OptiX y
renderizar un fotograma; la mera presencia de CUDA no basta. Manual:
https://docs.blender.org/manual/en/4.5/render/cycles/gpu_rendering.html

**Estado actualizado:** el propietario creó `brickflow-cinematic`; el CLI quedó
autenticado y se instalaron las herramientas en la VM. Ya hay renders de fábrica
1080p/4K realizados con OptiX, escena USD para Unreal y un tramo de movimiento
extraído del HTML exacto. Véase [ejecución cloud](cinematic_cloud_run.md) para
resultados, archivos, verificaciones y dependencias pendientes de Unreal.

## Lo que tenemos y lo que no se debe confundir

La familia histórica `scripts/greenfield_demo.py` usa Python/SimPy y produce
replays Three.js. La revisión ejecutiva 26 conserva 3,888.67 conformes
expedidos/h, 4,166.43 formados/h y 6.944 pallets completos/h del lote anterior.
Su inversión y energía son escenarios de ingeniería, no mediciones ni ofertas.
La revisión 27 añade un controlador de buffers separado del modelo físico.

La última demo local es distinta: `scripts/cart_demo.py` empaqueta la escena,
pero `greenfield/cart_model.js` ejecuta un simulador de eventos en JavaScript.
`greenfield/viewer_cart.js` representa 28,800 ladrillos instanciados, seis
flujos de inspección y dieciocho formadores. `window.CART_DEMO` expone escena,
cámara, renderer y búsqueda temporal. Es el punto de integración del render.
Estos cuatro archivos estaban sin seguimiento al comenzar la revisión; no se
incorporan al commit de este puente ni se modifica su contenido.

El constructor del carro genera tonos, aceptabilidad y variación mediante una
semilla. **No constituye una ejecución de la percepción real de persona 1.**
La integración real debe seguir consumiendo sus grupos, IDs y scores mediante
el adaptador, sin reclasificación ni filtro adicional. Un primer plano de una
inspección sintética se rotulará como tal.

Las cachés existentes de `artifacts/greenfield_28` no coinciden con la huella del
modelo actual observada durante esta revisión (`6b0450cc207bb779`). El empaquetador
solo inserta cachés que coinciden, de modo que un HTML nuevo recalcula el modelo
cuando no encuentra una. No usar los 8,000–9,100 bricks/h de cachés históricas
como resultado del código actual ni reutilizar las cifras de la revisión 26.
Congelar el HTML exportado, su SHA-256 y su evidencia antes del rodaje.

Esta revisión es de código, documentación y metadatos de replays. No equivale
a una revisión visual completa del último carro en navegador.

## Relación con el reto Marmon

El reto oficial #08 pide identificar categorías/tonos, planificar recogidas y
combinar percepción, picking, secuencia y paquetes para conservar el aspecto
del paquete y de la pared terminada, con superficies heterogéneas. Fuente:
https://roboinnovate.mirmi.tum.de/hackathon/hackathon-2026/

El resumen oficial público no fija 36 stacks, seis líneas, recetas exactas,
regla de tres vecinos, capacidad, inversión ni consumo: son decisiones o
supuestos del equipo. Mixed y Single no demuestran por sí solos una mezcla
Smooth satisfactoria. Mostrar la correspondencia paquete → pared con una
regla de extracción explícita es una oportunidad central del pitch; esa vista
todavía debe construirse y contrastarse con Marmon.

## Motor y arquitectura

**Nota de actualización:** esta recomendación corresponde a la primera fase
Blender/WebGL. La petición posterior se implementó como simulación C++ nativa
en Unreal 5.8.4; ver `unreal_native_goal.md` y `../unreal/README.md`.

Recomendación: conservar WebGL para la exploración en directo y usar
**Blender/Cycles/OptiX para el material cinematográfico**. Reutilizar el estado
de la escena; mantener percepción, planificación y ejecución independientes.
El render no decide recetas, IDs, tiempos de producción ni KPIs.

Unreal es una alternativa si el objetivo se convierte en una experiencia
interactiva con iluminación avanzada. Exige importar geometría, materiales,
instancias y movimiento, y probar la nueva reproducción. Pixel Streaming añade
servidor y WebRTC y necesita codificación de vídeo compatible:
https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-pixel-streaming-reference
Para el pitch actual, ese trabajo no aporta una ventaja demostrada frente a
un vídeo local de alta calidad más la demo interactiva existente.

## Puente implementado y uso en la instancia nueva

Subir el árbol de trabajo completo, incluyendo los cuatro archivos locales
del carro citados arriba; un clone del commit actual por sí solo no los incluye.
Usar un directorio persistente como `/home/ubuntu/workspace/brickflow`.

Instalar Blender oficial 4.5 LTS o posterior y verificar `blender --version` y
`nvidia-smi`. Crear un entorno Python con `python3-venv` disponible:

```bash
python3 -m venv .venv-render
.venv-render/bin/pip install playwright==1.64.1
.venv-render/bin/python -m playwright install --with-deps chromium
python3 scripts/cart_demo.py --output-dir artifacts/cinematic_source
.venv-render/bin/python cinematic/capture.py \
  --demo artifacts/cinematic_source/index.html \
  --time 1200 --view overview \
  --output artifacts/cinematic/overview.json.gz
blender -b --python-exit-code 1 --python cinematic/render.py -- \
  --scene artifacts/cinematic/overview.json.gz \
  --output artifacts/cinematic/overview.png --width 1920 --samples 32
```

`capture.py` abre el HTML real en Chromium, espera la simulación, la pausa,
busca el instante y conserva una captura WebGL de referencia. Exporta geometría,
grupos de materiales, UV, texturas de color, colores por instancia y matrices.
Líneas de grid, etiquetas HTML, paneles y luces originales no se exportan.
Se crea iluminación de estudio separada. No convierte automáticamente una
maqueta geométrica en CAD de fabricación ni añade detalle mecánico validado.

`render.py` conserva escala y colocación mediante una conversión rígida de ejes
Y-up → Z-up. Reutiliza mallas enlazadas, empaqueta texturas dentro del `.blend`,
usa Cycles, AgX y denoising, y exige una GPU OptiX. Ante ausencia de GPU falla;
`--cpu` existe únicamente para pruebas explícitas del importador. Emite PNG,
`.blend` editable y recibo JSON con GPU, tiempo, resolución, muestras y evidencia.
La cámara se conserva con encuadre de salida 16:9; comparar con la referencia
porque el viewport WebGL tiene otra proporción.

Verificación local realizada: sintaxis Python, exportación ejecutada con la
librería Three.js real y dos instancias de geometría compartida, composición
de matrices, colores, exclusión de proxies/escala cero y evidencia temporal.
El JSON resultante se importó en Blender 4.2.5 y se renderizó en CPU como prueba
del puente. Esta versión local se usa solo para el smoke test: la instancia
Blackwell necesita la versión y el driver indicados arriba. No se ha verificado
la captura del carro en Chromium, OptiX, texturas completas ni la calidad final
de la fábrica. La descarga local de Chromium fue rechazada por el usuario; no
se intentó sustituirla por otra descarga local.

```bash
node tests/test_cinematic_export.js /tmp/brickflow-export.json.gz
blender -b --python-exit-code 1 --python cinematic/render.py -- \
  --scene /tmp/brickflow-export.json.gz --output /tmp/brickflow-export.png \
  --width 640 --samples 8 --cpu
```

Las exportaciones sin `--duration` congelan un estado del replay. Con
`--duration`, el capturador exporta muestras temporales con visibilidad y matrices
estables, y `render.py --motion ... --animate` genera la secuencia. La cámara no
inventa movimiento de máquinas. El render tampoco valida contactos, fuerzas,
seguridad o capacidad. Las confirmaciones sintéticas no son validación visual
independiente.

## Producción propuesta y criterios de aceptación

1. **Congelar evidencia.** Generar el HTML actual, ejecutar Mixed/Single,
   registrar resultado, integridad de IDs y receta, y fijar su hash.
2. **Toma de prueba.** Vista general y primer plano de inspección a 1080p,
   32 muestras. Comparar posiciones, colores, texturas y cámara con WebGL.
   Corregir fallos de importación antes de gastar en secuencias.
3. **Dirección de arte.** Materiales de acero/pintura/caucho/ladrillo,
   microtextura y bordes físicamente plausibles, fondo limpio y luces grandes.
   Preservar los tonos de clasificación. El acabado inicial es un punto de
   partida técnico, no una calidad cinematográfica ya aprobada.
4. **Movimiento.** Exportar transforms y visibilidad temporal del mismo replay,
   con IDs estables y muestreo determinista. Comparar inicio, mitad y final de
   picks/transferencias; no interpolar a través de esperas ni ocultar piezas.
5. **Final.** Vídeo 45–60 s, 24 fps, 4K si el benchmark lo permite, seis imágenes
   para slides, respaldo 1080p y demo WebGL para preguntas. Renderizar a PNG por
   fotograma y montar después para permitir reintentos parciales.

Storyboard propuesto, rótulos en inglés:

| Tiempo | Plano | Mensaje |
| --- | --- | --- |
| 0–6 s | Macro de textura y tonos reales o sintéticos rotulados | Natural variation. Consistent results. |
| 6–14 s | Inspección e ID enlazado con decisión | See every brick. |
| 14–23 s | Receta y colocación de una capa | Plan every placement. |
| 23–35 s | Revelado de fábrica con movimiento verificado | One coordinated flow. |
| 35–46 s | Pallet y pared con extracción documentada | Designed for the finished wall. |
| 46–60 s | Resultado y una métrica respaldada por el lote | From variation to visual balance. |

Estos son conceptos creativos; no entregables audiovisuales ya generados.
La pared y la integración temporal están pendientes. Evitar mezclar versiones
o introducir ROI, ahorro laboral o métricas industriales no medidos.

## Presupuesto y cierre de sesión

Crédito restante aproximado comunicado por el propietario: USD 680; no se ha
consultado el saldo real. A USD 6.96/h como referencia de la captura, 10 h serían
USD 69.60 y 24 h USD 167.04, solo cómputo. Confirmar precio de la instancia nueva,
disco y proveedor. Propuesta: primera prueba dentro de USD 25; primera fase de
producción dentro de USD 200 y reservar el resto para revisiones. No son límites
automáticos aplicados a la cuenta.

Benchmark: `coste ≈ fotogramas × segundos/fotograma / 3600 × tarifa`. Una película
de 60 s a 24 fps tiene 1,440 fotogramas; a 30 s/frame y USD 6.96/h costaría
USD 83.52 de render, antes de preparación y reintentos. Son supuestos, no una
predicción de rendimiento de esta escena. Medir varias vistas, no extrapolar
solo de la más sencilla. No reservar varias GPUs antes de medir.

Descargar PNG, `.blend`, recibos y fuente antes de apagar. En Brev, algunas
instancias admiten stop/start y otras requieren eliminación para detener el
cómputo; parar puede mantener coste de disco. Confirmar el comportamiento del
proveedor sin eliminar datos que todavía no estén respaldados:
https://docs.nvidia.com/brev/concepts/gpu-instances
