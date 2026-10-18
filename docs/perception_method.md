# Dataset, visión clásica y redes neuronales

No conocemos todavía el método de persona 1. Trabajar con datasets no demuestra
que esté entrenando una NN: las mismas imágenes se pueden usar para calibrar
umbrales y evaluar segmentación, contornos y categorías por color.

La visión clásica usa operaciones/reglas como conversión de espacio de color,
umbrales, máscaras y contornos. Una red también es matemática: la diferencia es
que aprende parámetros a partir de datos. La elección se debe evaluar con imágenes
representativas y errores, no con la presencia de un dataset ni con la etiqueta IA.

Conviene distinguir localizar ladrillos, identificar sus caras y clasificar su
apariencia. Un detector neuronal no resuelve automáticamente el tono de todas
las caras ni permite conocer superficies ocultas. Un modelo preentrenado puede
necesitar adaptación; no asumimos que reconozca las clases del reto.

Persona 1 debe entregar ejemplos de entrada/salida, método, clases y significado
de confianza, métricas sobre imágenes apartadas del ajuste y casos de error por
iluminación/textura/solapamiento. Nuestra integración acepta inventarios de ambos
métodos y exige observaciones de caras y poses explícitas cuando corresponda.

Referencias primarias consultadas el 18-10-2026:
- https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html
- https://docs.opencv.org/4.x/d4/d73/tutorial_py_contours_begin.html
