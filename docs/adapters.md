# Arquitectura adaptable: ROS 2 es un adaptador, no un requisito

## Qué contempla el roadmap

El roadmap pide simulación sin hardware, orquestación y `robot_adapter` bajo
persona 3. No exige ROS, MoveIt, Gazebo ni un modelo de brazo. El prototipo actual
es de persona 2 y sus consumidores de prueba; no significa que la celda física
ni los módulos reales del equipo ya estén integrados.

## Frontera que se mantiene

```text
Observaciones / archivo / cámara
             ↓
Inventario + caras observadas + orientaciones declaradas
             ↓
Planificador Python independiente
             ↓
Plan JSON: ID, cara, orientación declarada, capa/fila/columna, paso
             ↓
Adaptador de ejecución elegido por el equipo
       ├─ SDK del fabricante
       ├─ ROS 2 + MoveIt
       └─ otro simulador / API
```

La elección de transporte no cambia las cuotas, mezcla ni IDs. El código de
`planning/` no importa ROS. La demo de navegador y las pruebas normales siguen
funcionando sin ROS. No enviamos poses o trayectorias al fabricante hasta conocer
frames, dimensiones, pinza, alcance, colisiones y orientaciones realizables.

## Adaptador ROS 2 opcional implementado

Humble y RViz ya estaban instalados. No se instalaron paquetes ni se reutilizó
el proyecto de Dresden. Se ejecuta desde este repositorio sin colcon:

```bash
# Terminal 1: generar el plan y animar su consumo por topics
bash scripts/ros_preview.sh

# Terminal 2: ver los ladrillos en 3D
bash scripts/ros_preview.sh rviz
```

El script carga exclusivamente `/opt/ros/humble`, elimina rutas de overlays
heredados en su propio proceso y usa localhost y dominio 87. No modifica el
shell del usuario ni .bashrc. Con Ctrl+C se detiene el proceso de la terminal.
Los ejemplos de dimensiones en RViz son sintéticos; no son medidas de la celda.

Para probar detención, cerrar el primer proceso y ejecutarlo con:

```bash
bash scripts/ros_preview.sh --fail-step 5
```

También admite `--inventory`, `--config`, `--period` y `--per-brick`. La vista
predeterminada usa el inventario por caras. Todos los textos de demo están en inglés.

| Topic | Mensaje | Contrato |
|---|---|---|
| `/munich_demo/inventory_request` | std_msgs/String | JSON con inventory, config, face_aware |
| `/munich_demo/plan` | std_msgs/String | envelope ros-envelope-0.1, status planned y plan/source_inventory, o rejected/reason |
| `/munich_demo/events` | std_msgs/String | estados de consumo, siempre execution=simulation_only |
| `/munich_demo/markers` | visualization_msgs/MarkerArray | cubos y etiquetas confirmados en frame pallet |

Los topics son una primera envoltura de prueba JSON, no una interfaz ROS
tipada definitiva. Un rechazo se publica en el mismo topic retenido de plan
para limpiar la visualización previa. QoS fiable y transient-local permite
abrir RViz después de completar la secuencia y ver el último estado.

No hay brazo, IK, planificación de trayectorias, control de articulaciones,
simulación de pinza, contactos ni detección de colisiones en este adaptador.
Los cubos se colocan en coordenadas ilustrativas, y cara/orientación se muestran
como etiquetas; no se modela el giro físico. Eso requiere un adaptador posterior.

## Pruebas

```bash
# Sin ROS
python3 -m unittest discover -s tests -v
# Con transporte ROS local real
bash scripts/ros_preview.sh test
```

Las pruebas ROS comprueban igualdad con el plan Python, entrega de mensajes,
12 cubos al completar, 4 cubos ante fallo del paso 5 y limpieza ante un nuevo
rechazo. No forman parte del descubrimiento normal para mantener ROS opcional.

## Cómo continuar cuando conozcamos la tecnología

1. Mantener el núcleo de planificación y sustituir el consumidor de prueba.
2. Obtener la descripción del brazo/SDK, la pinza y el layout real.
3. Mapear IDs a poses de recogida y celdas a poses de colocación.
4. Verificar orientaciones declaradas y caras de exposición por posición.
5. Implementar planificación de movimiento y confirmaciones/fallos reales.
6. Validar el flujo con persona 3 primero en simulación y después en hardware.

Si la plataforma soporta ROS, MoveIt es una opción para planear y visualizar
movimientos/colisiones de un brazo en RViz. Si solo dispone de un SDK, este
recibe el mismo plan a través de su adaptador, sin imponer ROS.

Fuente técnica oficial consultada el 18-10-2026:
https://moveit.picknik.ai/humble/doc/tutorials/quickstart_in_rviz/quickstart_in_rviz_tutorial.html

## Corrección de visualización en WSL

La suscripción a topics no demuestra que RViz esté dibujando. La vista publica
ahora el TF estático `world → pallet`, usa `world` como Fixed Frame y carga
explícitamente displays y cámara habilitados. El lanzador de RViz usa OpenGL por
software, XCB y desactiva MIT-SHM para evitar el viewport vacío observado en WSL.
Solo afecta al proceso de RViz. Para probar GPU: `MUNICH_RVIZ_SOFTWARE=0 bash
scripts/ros_preview.sh rviz`.

Mantener el publicador de la demo activo mientras se revisa RViz, especialmente
al abrir una ventana nueva. El estado retenido depende de que siga existiendo
el publicador. La comprobación visual exige ver la cuadrícula y los cubos; el
estado OK de topics por sí solo no basta. Se añadió una prueba de disponibilidad
del TF para suscriptores que se conectan después de iniciar la escena.

Las etiquetas de texto se publican, pero su namespace `labels` queda oculto
por defecto para evitar artefactos tipográficos de OGRE/WSL. Los cubos de
tonalidad siguen visibles. Se pueden activar en Namespaces si el renderizador
local las dibuja correctamente.
