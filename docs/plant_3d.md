# Tarea 3 — planta 3D con flujo y cinemática

Revisión actual: [automatización, reservas y trazabilidad de tiempos](plant_automation.md).
Los valores de 2002/2006 segundos de este documento corresponden a los checkpoints históricos.

## Punto de retorno

La versión anterior se conserva en el commit `dc8cab1` y en la etiqueta local
`task3-2d-checkpoint`. Los artefactos `artifacts/plant_line_01/` no se modifican.
No usar `git reset --hard` para recuperar esa versión: inspeccionarla con
`git show task3-2d-checkpoint:plant_sim/model.py`, o crear una rama desde la etiqueta.

## Ejecutar y visualizar

```bash
python3 scripts/plant_demo.py --compare --output-dir artifacts/plant_3d_01
```

Usar otra carpeta si esa ya existe. `index.html` contiene el modelo 3D local,
Three.js incluido y sin servidor/CDN. Requiere WebGL habilitado en el navegador.
No hace falta instalar otro paquete Python: SimPy es el mismo de la versión anterior.
La biblioteca Three.js 0.160.1 se versiona con licencia MIT en `third_party/three/`.

- Arrastrar: orbitar. Rueda: acercarse. Botón derecho + arrastrar: desplazar.
- `View`: vistas de dehacking, separación, corrección, reapilado y planta superior.
- `First unit checkpoints`: saltar explícitamente a operaciones del primer conjunto.
- `Restart cycle`: volver al inicio del primer dehacking (omite la espera inicial).
- `End of run`: resultado final. El slider permite cualquier instante, incluido t=0.
- Click sobre equipos: identificar estación. I/O muestra presencia, fin de carrera
  y comando de accionamiento. No son entradas de hardware reales.
- `Follow active unit`: centra gradualmente la cámara en una estación activa.
- El visor 2D anterior sigue disponible como `process_2d.html` en cada escenario.

## Qué se simula

SimPy sigue siendo la fuente de verdad para disponibilidad, colas, material,
inspección, corrección y tiempo. `plant_sim/mechanics.py` convierte sus operaciones
en trayectorias por ID de ladrillo y por herramienta; no inventa una segunda
secuencia ni modifica los resultados para ajustar la animación.

La revisión añade tiempo explícito a la transferencia de capas corregidas
(`seconds.lane_transfer`, 4 segundos supuestos). La carga del separador,
retirada de capa superior/inferior, emparejamiento y retorno de cabezal usan
subfases de los tiempos existentes. La geometría ya no cambia instantáneamente
entre estaciones. Los transportadores no activan una sujeción incompatible con
su avance; las mesas y pórticos sí tienen estados de sujeción virtuales.
Los eventos de corrección incluyen ID, posición y destino para seguir exactamente
la pieza que se mueve.

La planta muestra:

1. Stack de entrada y plataforma de carga.
2. Pórtico que retira dos capas y las deposita sobre el transportador.
3. Mesa de transferencia y estacionamientos para el buffer de entrada.
4. Separador que carga el conjunto, levanta primero la capa superior y después
   mueve la inferior a otra línea.
5. Dos transportadores con arcos de iluminación, cámaras y presencia virtual.
6. Robot cartesiano conceptual con ejes X/Z y bajada vertical para retirar una
   pieza, dejarla en rechazo y colocar otra desde el stock aprobado.
7. Transporte de capas corregidas a buffers de unión.
8. Pórtico de emparejado: coloca primero la capa inferior y después la superior.
9. Transportador de salida y pórtico de reapilado.
10. Descarga de pallets completos y acumulación del siguiente sin perder sobrantes.

Las medidas de los ladrillos son las del PPT. El patrón de agujeros del mesh es
ilustrativo, no CAD del producto. La planta se ordena en metros con Y vertical.
La orientación coloca los 10 ladrillos de ancho transversalmente a la marcha.
La longitud/posición de equipos, buffers, estructuras y vallado son una propuesta,
no una reproducción dimensional de la fábrica. Es un estudio de celda.

## Qué NO valida esta simulación

Es una simulación de proceso con cinemática continua; **no un solver de física de
contacto**. No evalúa fricción, carga, rotura, temperatura, esfuerzos, deformación,
colisiones o estabilidad de una capa hueca durante el agarre. La sujeción ideal
representa una condición de diseño pendiente de validar. Tampoco verifica PLC,
seguridad o una interfaz de robot real. Las cámaras muestran su ubicación y un
volumen ilustrativo; las decisiones siguen siendo observaciones sintéticas del
modelo y no imágenes renderizadas procesadas por OpenCV.

Las herramientas siguen trayectorias de tomar/elevar/trasladar/depositar/retornar;
no se afirma optimización dinámica, jerk limitado o certificación de esas rutas.
La variante de dos robots es una hipótesis de capacidad: sus interferencias
físicas no están verificadas. El stock aprobado y los buffers son finitos, pero
la ocupación geométrica/contacto de todos los traslados bajo congestión todavía
requiere un simulador de física o una revisión CAD de trayectorias.

Los sensores virtuales reflejan el modelo temporal, no una validación visual
independiente. Un fallo congela el visor en el instante de parada y conserva el
ledger. Las rutas registradas son las rutas ordenadas, no una medida física de
lo que haría un actuador con un fallo real.

## Evidencia y comprobaciones

```bash
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_plant -v
python3 -m unittest discover -s tests -v
```

Se conservan los 89 tests del núcleo y se ejecutan 16 tests de proceso/mecánica.
Los nuevos contratos comprueban: una identidad por pieza, trayectorias continuas,
sin dos movimientos simultáneos del mismo ID ni herramienta, unión pieza/pinza
durante transporte, transferencia temporizada antes del emparejado, 14 alturas
físicas por pallet completo y trazas conservadas tras timeout.
Son pruebas de coherencia del modelo, no mediciones independientes de hardware.

Cada carpeta contiene `run.json`, `mechanics.json`, la auditoría de continuidad,
HTML 3D autónomo y esquema 2D. Las capturas de navegador se guardan aparte para
mostrar que WebGL realmente renderizó la escena. La prueba de navegador bloquea
HTTP/HTTPS y verifica reproducción offline, continuidad numérica, unión pinza/pieza,
KPIs finales, reinicio, pantalla móvil y parada por timeout.

Con semilla 8 y tiempos supuestos: 1600 ladrillos, 177 reemplazos, 2 pallets de 560
más 480 restantes; 273 aprobados en reserva. El lote dura 2006 segundos, frente a
2002 de la versión 2D sin transferencia explícita: 2871.386 ladrillos/h incluyendo
arranque y vaciado. Las 11 columnas monocromáticas siguen apareciendo: dibujarlo
en 3D no corrige el criterio de mezcla ni demuestra mejora frente a humanos.

## Siguiente validación industrial

Elegir con el mentor cómo sujetar capas reales y qué caras definen calidad,
medir ciclos, dimensionar posiciones/buffers y revisar colisiones. Si necesitamos
validar contacto y fuerzas, importar estos mecanismos a un simulador de cuerpos
rígidos y contrastar sus parámetros con ensayos reales. La línea 3D actual permite
revisar secuencia y flujo sin presentar esos resultados como física validada.


## Evidencia final de navegador

Comprobación en Edge con HTTP/HTTPS bloqueado: WebGL activo, 2050 instancias
materiales (1600 de entrada + 450 de reserva), ciclo completo de 1600 y reinicio
correcto. Error de unión pinza/pieza medido sobre coordenadas renderizadas durante
el transporte: < 1e-5 m. Timeout: escena detenida en el tiempo del modelo y alarma
visible. No son mediciones de precisión de hardware.

Capturas reales en `artifacts/plant_3d_01/`: `overview_3d.png`,
`separator_3d.png`, `correction_3d.png`, `restacking_3d.png`,
`completed_pallets_3d.png`. Resultados en `browser_3d_verification.json`.
Los pallets vacíos se desplazan durante los ciclos de muelle/intercambio; esos
movimientos auxiliares son hipótesis cinemáticas ligadas al mismo reloj.
