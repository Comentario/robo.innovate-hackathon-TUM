# Cabinas de servicio de la referencia final 37

La exportación anterior ocultaba `inspectionCovers` y `routingCovers` antes de
exportar la geometría estática. Las cabinas no estaban transparentes en Unreal:
no existían en el asset. La corrección conserva los 324 meshes originales en un
suplemento independiente `enclosures.json` (9 piezas de inspección y 45 de
routing por carril, seis carriles). No se infieren formas nuevas ni se cambia el
calendario de producción.

`export_source_enclosures.py` exporta esos grupos directamente de la referencia
fijada por SHA-256; `export_source_replay.py` integra el mismo suplemento en las
exportaciones nuevas. `scene.json` registra `enclosures` y `enclosuresSha256`.
La geometría estática y el replay previos se pueden reutilizar sin reexportarlos.

En Unreal, `FactorySourceEnclosures.cpp` carga el suplemento con los materiales,
texturas y transformaciones fuente. Las carcasas están cerradas por defecto.
La atención de la cámara sobre el módulo/carril cercano reduce gradualmente
`Coverage` a 0,28; los otros carriles permanecen cerrados. Se promedian muestras
de atención en una ventana fija de ±1,08 s de **video**, por lo que la transición
es reproducible al empezar cualquier chunk y no depende de frames anteriores.
Al alejarse o salir del módulo, la cubierta vuelve a 1. El plano general final
recupera todas las carcasas cerradas.

`M_FactoryEnclosureFade` usa transparencia suave con iluminación de superficie y
un relleno discreto derivado del color original. Conserva el tono verde/gris y
permite leer el volumen durante el corte. La prueba inicial de dither se descartó
por granulado; no forma parte del material final. `BrickflowEnclosuresClosed`
es una opción de prueba para comparar cubiertas opacas con la misma cámara,
no una opción de la cola de presentación.

## Verificación ejecutada

Se compiló un clon independiente `brickflow-final37-cabins-native` con UE 5.8.4,
sin sustituir los binarios del proyecto que estaba renderizando. Se comprobaron
inodos/hashes separados del módulo y de `scene.json`; el replay compartido por
enlace mantiene SHA-256 `7556a950873f2751e9c8e64ec843acd2ab2a78b580ec628844288e662d63bf45`.
La auditoría C++ de los 16.402 frames del recorrido 02 conserva exactamente todos
los campos originales de cámara y reloj (diferencia numérica máxima 0).
La cobertura llega a 0,28 en ambos módulos y vuelve a 1 al final; los mayores
cambios entre frames son 0,02825 y 0,02187. El comprobador reproducible es
`tests_native/check_source_enclosures.py`.

Se revisaron capturas Vulkan reales de inspección abierta/cerrada en el frame
5265, routing abierto/cerrado en el 5800 y general cerrado en el 16000. También
se capturó WebGL desde los mismos tiempos, posiciones, objetivos y FOV para
comparar los volúmenes originales cerrados. Coinciden las carcasas, aperturas y
soportes en esas muestras; la iluminación cinematográfica difiere deliberadamente
de la fuente. Esta revisión es una comparación visual por muestras, no una
validación exhaustiva de todos los píxeles ni una validación física independiente.

La varilla señalada se revisó en el instante indicado, 5:12 del recorrido 02
(frame 9360), comparando Unreal y WebGL a cámara y tiempo iguales. Corresponde al
mástil de `guideGate` `gate-1-2`: posición fuente `[53.65, 1.8475, -6.2]`, sección
35 × 35 mm y longitud 0,985 m. Su base toca el borde superior de la puerta a
1,355 m; su extremo superior llega al cuerpo fijo del actuador a 2,34 m. La pieza
existe en ambas versiones y se conserva. La captura ampliada y su proyección
fuente permiten identificarla sin atribuir un defecto inexistente a Unreal.

La rama de compatibilidad `bankLift` también reproduce la fórmula fuente, pero
el replay final 37 contiene cero actores de ese tipo: esa rama no explica ni
modifica el elemento señalado. La iluminación más contrastada de Unreal hace
más visible la varilla de acero que en la referencia WebGL.
