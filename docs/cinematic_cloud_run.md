# Ejecución cloud de Brickflow

26-10-2026. Rama `persona2/planning`. El propietario eligió una instancia nueva,
`brickflow-cinematic`, a USD 2.63/h en Massed Compute. Acceso por CLI Brev
v0.6.337 autenticado por el propietario, sin compartir contraseñas en el chat.

## Herramientas y entorno

- Local WSL: CLI Brev y Playwright/Chromium en `/tmp`; se usan para conexión y
  captura. La configuración de login/SSH la administra Brev en el home del usuario.
- Cloud: Ubuntu 22.04.5, RTX PRO 6000 Blackwell Server Edition completa,
  97,887 MiB visibles por `nvidia-smi`, driver 580.126.09, CUDA compatible 13.0.
- Instalados en cloud: Blender 4.5.3 LTS oficial, verificado con el SHA-256
  publicado; Playwright 1.64.1 + Chromium, FFmpeg, librerías gráficas/Vulkan y Xvfb.
- Directorio remoto: `/home/shadeform/workspace/brickflow-cinematic`.
  La máquina usa `shadeform`, no `/home/ubuntu`.

Reproducción de instalación: `brev exec brickflow-cinematic @cinematic/setup_cloud.sh`.
El instalador no instala Unreal: necesita el ZIP Linux autenticado de Epic.

## Fuente congelada y resultados

Se consumió **el HTML indicado por el propietario**, sin regenerarlo desde los
archivos fuente que estaban siendo modificados en paralelo:

`artifacts/greenfield_28/index.html`

SHA-256, comprobado también sobre `source.html` en la VM:

`5f4a3a685b0b6f63920308a73d3df7bea83730a5c5d4d8d5c9e1c51613717453`

Lote registrado: 28,800 inspeccionados, 42 pallets completos, duración simulada
10,197.32509752284 s, equivalente de lote **8,303.353986 bricks/h** y
**14.827418 pallets/h**. No son resultados industriales medidos ni métricas de
la revisión 26. La captura se hace en el segundo 1,200 del replay; los totales
anteriores corresponden al lote completo, no al instante mostrado.

La imagen fija incluye 66,541 objetos visibles. La exportación para animación
incluye también objetos temporalmente ocultos: 66,877 objetos. Se conserva la
correspondencia por índice dentro del snapshot y se comprueba su hash antes de
cargar las muestras temporales.

Archivos locales bajo `artifacts/cinematic/` (artefactos regenerables, sin Git):

- `cloud-renders/hero-4k.png`: 3840×2160, 128 muestras, acabado executive.
- `cloud-renders/inspection.png`: 1920×1080, 64 muestras, detalle de inspección.
- `cloud-renders/*.blend`: escenas editables con texturas empaquetadas.
- `cloud-renders/*.receipt.json`: GPU usada, configuración, evidencia y tiempo.
- `inspection-motion.json.gz`: snapshot completo para el clip.
- `inspection-motion.json.motion.json.gz`: deltas de matrices y visibilidad.
- `unreal/Content/Factory/brickflow.usdc`: escena USD con geometría instanciada;
  aproximadamente 6.6 MiB, más texturas y evidencia.

El render general inicial 1080p/32 muestras tardó aproximadamente 6 s de render
y 12.17 s en el proceso completo. La imagen 4K/128 muestras tardó unos 12.28 s
en la fase de render/guardado. Estos tiempos son de planos concretos y no
constituyen un benchmark universal ni el coste total de preparación.

El acabado executive aplica un suelo oscuro, acero reflectante y detalle
superficial de ladrillo, manteniendo sus colores. No añade una máquina nueva,
recalcula recetas ni certifica el diseño mecánico.

## Movimiento y verificación

Se extrajo un clip de **96 fotogramas, 24 fps, cuatro segundos, velocidad 1×**,
vista `inspection`, inicio en t=1,200 s. Son 34,201 cambios de matrices/visibilidad.
Las curvas mantienen los intervalos sin cambios; no deben interpolar a través
de esperas. Blender usa quaterniones y la conversión rígida Y-up → Z-up.

`verify_motion.py` compara posiciones, escalas, rotaciones y visibilidad de cada
objeto modificado y una selección estable de objetos en espera, en todos los
fotogramas. Resultado cloud: **36,247 comprobaciones**, error máximo de matrices
**3.742410115137318e-7**, sin discrepancias. Hay una prueba adicional con Three.js
real y un fixture de importación Blender local. Son verificaciones numéricas de
la conversión, no observación independiente del proceso físico.

Comandos, ejecutados dentro del directorio remoto:

```bash
tools/blender-4.5.3-linux-x64/blender -b --python-exit-code 1 \
  --python render.py -- --scene inspection-motion.json.gz \
  --motion inspection-motion.motion.json.gz --animate \
  --output renders/inspection-motion/frame_ --width 1920 --samples 64 --look executive
tools/blender-4.5.3-linux-x64/blender -b renders/inspection-motion/frame_.blend \
  --python-exit-code 1 --python verify_motion.py -- \
  --scene inspection-motion.json.gz --motion inspection-motion.motion.json.gz \
  --output renders/inspection-motion/verification.json
```

Se codifica a H.264/1080p con FFmpeg y `finish_clip.sh` añade un rótulo inglés
que identifica la simulación, la entrada sintética y la velocidad de replay.
El recibo de vídeo de FFprobe comprueba resolución, fps, duración y fotogramas.
Los PNG se conservan para reintentos; la caché persistente de Cycles queda
habilitada en futuras ejecuciones animadas para reducir reconstrucciones.

## Unreal: preparación y dependencia pendiente

Se creó `cinematic/unreal/Brickflow.uproject` con USDImporter, scripting Python
y Movie Render Queue, y configuración de Lumen/hardware ray tracing. El script
`import_stage.py` abre el USD y guarda `/Game/Brickflow` una vez instalado el editor.
**Todavía no está ejecutado ni validado en Unreal.**

El archivo aportado inicialmente por el propietario es
`EpicInstaller-20.3.3-unrealEngine.exe`, el Launcher de Windows. No se instala en
la VM Linux. Hace falta el **ZIP del editor Linux**, descargado con la cuenta Epic
del propietario desde https://www.unrealengine.com/en-US/linux . El correo de
la cuenta no se guarda en estos documentos ni en los scripts.

Al recibir la ruta del ZIP: transferirlo, comprobar integridad de la transferencia,
extraerlo a `tools/unreal`, comprobar Vulkan/UnrealEditor y ejecutar el proyecto.
La configuración del proyecto no demuestra que ray tracing esté activo hasta
verificar el motor en ejecución. No usar `-NullRHI` para validar el render.

El USD exportado es un estado congelado. Sus materiales USDPreviewSurface son
aproximaciones de los shaders Blender: la microtextura procedural requiere
reconstrucción en Unreal. Su importación, unidades, cámaras y materiales siguen
pendientes de verificación en el motor. El movimiento animado está validado en
Blender, pero todavía no se exporta en este USD estático.

## Preservación y límites

No se alteraron percepción, planificación, ejecución ni las métricas del HTML.
Los cambios concurrentes de `greenfield/` se dejaron fuera de este trabajo.
La escena usa entrada sintética; no se presenta como percepción real de persona 1.
Los renders y muestras no validan física, seguridad, capacidad o calidad visual
industrial de una pared terminada. La película final del pitch sigue pendiente.

La instancia continúa activa para instalar Unreal y continuar la producción.
No se elimina automáticamente. Respaldar escenas, vídeos, USD y evidencia antes
de eliminarla; la eliminación de esta oferta sin stop/start borra sus discos.
