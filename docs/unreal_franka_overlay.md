# Prueba visual: simulación y Franka físico

Se generó una prueba de **28 segundos, 30 fps**, usando exclusivamente el
render entregado y el vídeo físico proporcionado por el propietario.

Entregables:

- [Revisión 1080p](../artifacts/physical_composite/delivery/brickflow-franka-overlay-1080p.mp4).
- [Versión 4K](../artifacts/physical_composite/delivery/brickflow-franka-overlay-4k.mp4).
- [Plan de montaje y hashes](../artifacts/physical_composite/delivery/edit-plan.json).

Es un extracto para evaluar la transición, no una sustitución de toda la
película ni un render de la planta nueva.

También se guardaron copias para abrir directamente desde Windows en
`D:\Hackathon\Munich Hackathon 2026\Brickflow-Franka-Overlay-v1\`, junto al
plan de edición y una hoja de muestras de la transición.

## Fuentes y tratamiento

Simulación: `brickflow-continuous-4k.mp4`, el MP4 de la entrega anterior basada
en greenfield_30. Se usa el intervalo **01:24–01:52**, que incluye la llegada
al perfil fijo, extracción de la fila, transferencia y regreso al seguimiento.
El fondo conserva su movimiento, cámaras y reloj originales.

Vídeo físico: `D:\Hackathon\Munich Hackathon 2026\Conveyor-Placement.mov`.
Original HEVC 3840 × 2160, con metadato de rotación: su presentación correcta es
vertical, 2160 × 3840. Dura aproximadamente 43,3 s. SHA-256 del archivo original:
`96ffb283cabd0f757e2ca8c4d0f6b08ab0ed2a9ecca83d8aae0bb4a2a72801aa`.

Se preparó un proxy vertical 1080 × 1920 a 30 fps desde el segundo 4. Para el
montaje se utiliza el primer ciclo hasta el segundo 16,8 del original, a 1×.
No se estira el vídeo ni se recorta la acción del brazo. La orientación se
corrige usando la rotación del contenedor; los movimientos son los grabados.

El vídeo físico aparece a la derecha en una superposición vertical con bordes
redondeados y sombra suave. El actuador simulado y la faja receptora quedan
visibles a su izquierda. Durante el fundido se ven las dos fuentes superpuestas.
No se añadieron rótulos, métricas, vídeos sintéticos ni sonido al montaje.

## Tiempos de la prueba

| Momento en el extracto | Tratamiento |
| --- | --- |
| 00:00–00:06 | Simulación; transición de cámara original hacia el perfil. |
| 00:06–00:07,200 | Entrada gradual del vídeo físico. |
| 00:07,200–00:16,300 | Ambas fuentes visibles; agarre, traslado hacia la izquierda y depósito. |
| 00:16,300–00:18,100 | Salida gradual del vídeo físico. |
| 00:18,100–00:28 | Simulación y retorno original hacia el seguimiento del ladrillo. |

La correspondencia temporal propuesta es
`segundo del film = segundo del vídeo físico + 82,3`.
Se aproximan las fases de agarre y traslado mediante montaje; **no hay una
calibración geométrica entre cámaras ni sincronización de control del robot**.
La última imagen física se sostiene desde 00:15,100 del extracto para cerrar
el fundido sobre el depósito. Ese hold afecta solo al vídeo físico; la
simulación sigue reproduciendo su secuencia original.

## Calidad y verificación

- 4K: 3840 × 2160, H.264, 840 frames; 1080p: 1920 × 1080, mismos frames y duración.
- Codificación NVENC en la VM; composición FFmpeg con máscara y sombra de autoría.
- Decodificación completa del 4K sin errores y conteo decodificado de 840 frames
  en ambos archivos.
- Verificación de timestamps: 840 paquetes, 30 fps, DTS creciente y error máximo
  de presentación de aproximadamente 0,000000334 s frente a la rejilla uniforme.
- Revisión visual de muestras antes, durante y después del fundido, incluidos
  agarre, traslado y depósito. Esto no equivale a una revisión humana de cada
  frame ni a validación del robot o de la planta.
- Hashes locales comparados con los archivos remotos tras la descarga.

La herramienta reproducible es `unreal/tools/composite_franka.py`. Requiere
Pillow y FFmpeg con NVENC. Los archivos fuente originales se conservan. Los
metadatos del móvil no se transfieren al vídeo de presentación.
