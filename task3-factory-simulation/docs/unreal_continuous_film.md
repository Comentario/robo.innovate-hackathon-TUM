# Toma continua · segunda revisión de cámara

Esta revisión reemplaza los cortes de la primera película. Se conserva la
planta nativa fijada a greenfield_30 y sus trayectorias. No se incorporan los
cambios concurrentes del viewer WebGL.

- El reloj empieza en 0: entrada de los pallets/carro, dehacking de los layers
  superiores y distribución hacia los loading belts. Después sigue el ID 9568.
- No hay omisiones de tiempo entre fases. El reloj nativo es una función
  continua cuya velocidad también es continua. Las pausas entran y salen con
  rampas suaves; el producto siempre usa `Simulation::pose`.
- El row se ve de perfil, mirando a lo largo de X hacia el origen, con el
  subbelt en el lado izquierdo de la imagen. Cámara fija durante toda la
  extracción, transferencia y pausa Franka. FOV horizontal 55°, observador en
  UE `(2770, midpointZ-80, 285)` cm, mira a `(2150, midpointZ, 165)` cm.
  Es una correspondencia del plano de visión de las referencias, no una
  calibración de intrínsecos/distancias de la cámara física.
- Todas las perspectivas se enlazan mediante blends quintic con velocidad y
  aceleración nulas en los extremos. El objetivo seguido se suaviza usando
  poses nativas cercanas; ese filtro solo afecta a la cámara, nunca al ladrillo.
- Formación/reconstrucción del pallet: aproximadamente 16×, con rampas de 4 s.
  Outfeed, elevación, bridge y depósito: 1×, incluyendo las esperas originales.
- Tras el depósito y liberación, aceleración gradual a 40× mientras la cámara
  se aleja; luego una órbita completa en plano amplio. Se comprueba que avancen
  miles de inspecciones en el intervalo nativo mostrado.

`FilmTiming.h` contiene la integral analítica de las rampas; `film_clock_test`
comprueba monotonía y continuidad de velocidad. La auditoría nativa exporta
cada pose, cámara, objetivo, lente, velocidad e inspeccionados sin renderizar.
No sustituye las pruebas de imagen: se usa primero para detectar errores de
continuidad y se identificará como `cameraAuditOnly`.

## Comprobaciones previas al master

La auditoría final de los 11,867 frames pasó: poses originales con error máximo
1.0303e-12 m, reloj sin skips, velocidad continua entre fases, cambios de cámara
sin saltos, perfil fijo en toda la extracción, bridge a 1× y 5,727 inspecciones
adicionales en el timelapse final. `cameraAuditOnly=true`: todavía no es la
verificación del archivo de vídeo terminado.

Se revisaron imágenes renderizadas de la entrada, dehacking y perfil. La cámara
inicial evita la columna que tapaba los pallets; dos rellenos de estudio, sin
geometría visible, aclaran inputs y transferencia. Se mantienen todas las
estructuras de la planta. Las transiciones de cámara interpolan objetivo,
distancia y dirección orbital con curvas quintic, evitando pasar cerca del
objetivo al cambiar de lado.

Render final: `Saved/Films/continuous-4k-v4-part0` .. `part3` en la VM.
Rangos `[0,2967)`, `[2967,5934)`, `[5934,8901)`, `[8901,11867)`.
El ensamblado solo concatena segmentos calculados con el mismo reloj y cámara
analítica; no introduce cortes de perspectiva ni salta estados. Verificar de
nuevo la traza completa y los frames codificados antes de entregar.

## Recogida automática

`unreal/tools/collect_continuous_film.sh`, ejecutado desde la raíz del repo,
espera al ensamblado, comprueba la traza renderizada completa, genera el review
1080p y descarga los MP4 en `artifacts/unreal_continuous/delivery/`. Los nombres
locales son `brickflow-continuous-4k.mp4` y `brickflow-continuous-1080p.mp4`.
Compara ambos SHA-256 con los originales remotos y conserva los metadatos.
`collection.status` indica el estado; `collection.log` está en el directorio
padre. Un estado de descarga verificada no implica revisión visual terminada.
El master 4:4:4 permanece en la VM; no se descarga automáticamente.

## Entrega terminada

- `artifacts/unreal_continuous/delivery/brickflow-continuous-4k.mp4`:
  3840×2160, 30 fps, 11,867 frames, 395.567 s, 3,527,237,541 bytes.
- `artifacts/unreal_continuous/delivery/brickflow-continuous-1080p.mp4`:
  1920×1080, mismos frames y duración, 519,016,447 bytes.
- Ambos hashes coinciden con los originales remotos. La traza del render
  completo pasó (`cameraAuditOnly=false`); error máximo de pose 1.0303e-12 m.
- `packet-verification.json` comprueba los 11,867 timestamps del MP4 4K:
  error máximo 3.34e-7 s frente a la rejilla uniforme de 30 fps y DTS creciente.
- Se revisaron muestras codificadas de inputs, dehacking, perfil, inspección,
  apilado, bridge y cierre; están en `delivery/quality-frames/`.
- Handles: Franka 100.0333 s durante 5 s; detección 129.6333 s durante 7 s.

La concatenación del master MKV emitió advertencias de DTS; ese contenedor
no tiene la verificación de timestamps del MP4. Los entregables MP4 son los
archivos verificados para evaluación y presentación. El master conserva los
segmentos lossless originales por separado para una futura remultiplexación.
