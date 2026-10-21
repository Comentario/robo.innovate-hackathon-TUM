# ROS 2 Humble — comandos básicos

Guía rápida para ejecutar desde una terminal de Ubuntu/WSL.
The `marmon_perception` package, `perception_node` executable and `/perception`
node are now implemented. See `../perception/README.md` for the required
parameters, Fast DDS image transport profile, and a complete dataset test.

## Conceptos rápidos

- **Nodo:** programa que participa en el sistema ROS.
- **Tópico:** canal por el que se publican y reciben mensajes.
- **Mensaje:** estructura de datos transmitida, como una imagen.
- **Paquete:** código, dependencias y ejecutables organizados para ROS.
- **Workspace:** espacio de trabajo donde se construyen los paquetes.
- **Parámetro:** configuración de un nodo.
- **Servicio:** petición con respuesta.
- **Acción:** tarea con progreso, resultado y posibilidad de cancelación.
- **QoS:** configuración de comunicación, como fiabilidad y tamaño de cola.

## Preparar y construir

```bash
# Habilitar ROS 2 en cada terminal nueva.
source /opt/ros/humble/setup.bash

# Construir los paquetes desde la raíz de un workspace configurado.
colcon build

# Cargar los paquetes construidos; requiere que ya exista install/.
source install/setup.bash
```

`source` carga la configuración en la terminal actual. Primero se carga ROS
y después el workspace.

## Ejecutar e inspeccionar nodos

```bash
# Ejecutar: ros2 run <paquete> <ejecutable>.
ros2 run marmon_perception perception_node

# Listar los nodos descubiertos.
ros2 node list

# Ver publicaciones, suscripciones y servicios de un nodo.
ros2 node info /perception

# Iniciar componentes mediante un archivo de lanzamiento existente.
ros2 launch marmon_perception perception.launch.py
```

The launch file above is illustrative and has not been implemented.
Para detener un proceso iniciado en la terminal, utiliza **Ctrl+C**.
ROS 2 no necesita ejecutar `roscore`.

## Revisar tópicos y mensajes

```bash
# Listar tópicos junto con sus tipos de mensaje.
ros2 topic list -t

# Ver publishers, subscriptions y QoS de un tópico.
ros2 topic info /camera/image_raw --verbose

# Mostrar los mensajes que van llegando; detener con Ctrl+C.
ros2 topic echo /perception/inventory

# Medir la frecuencia de mensajes recibidos por esta herramienta.
ros2 topic hz /camera/image_raw

# Consultar la estructura de un mensaje estándar de imagen.
ros2 interface show sensor_msgs/msg/Image

# Consultar la estructura de un mensaje de texto.
ros2 interface show std_msgs/msg/String
```

Los tópicos de cámara e inventario son los valores predeterminados. La QoS de quien publica y
quien recibe debe ser compatible para intercambiar mensajes.

### Prueba sencilla con texto

Con ROS cargado en ambas terminales, inicia primero este receptor:

```bash
ros2 topic echo /prueba std_msgs/msg/String
```

En otra terminal, publica un único mensaje:

```bash
ros2 topic pub --once /prueba std_msgs/msg/String "{data: 'Hola ROS 2'}"
```

Deberías ver el texto en el receptor. Esta prueba no requiere nuestro nodo.

## Consultar y configurar parámetros

```bash
# Listar los parámetros de un nodo.
ros2 param list /perception

# Consultar un parámetro.
ros2 param get /perception detector_mode

# Establecer un parámetro al iniciar el nodo.
ros2 run marmon_perception perception_node --ros-args -p detector_mode:=pallet

# Solicitar un cambio durante la ejecución.
ros2 param set /perception detector_mode wall
```

The perception node declares these parameters as read-only. The `param set`
example is rejected: restart the node with the desired configuration instead.

## Grabar datos y consultar ayuda

```bash
# Grabar un tópico en una carpeta nueva; detener con Ctrl+C.
ros2 bag record -o /tmp/prueba_ros2_bag /prueba

# Reproducir la grabación para volver a publicar sus mensajes.
ros2 bag play /tmp/prueba_ros2_bag

# Ver los comandos disponibles y la ayuda de uno concreto.
ros2 --help
ros2 topic --help
ros2 topic pub --help
```

`ros2 bag record` genera archivos: elige una carpeta fuera del repositorio o
dentro de `outputs/`, que está ignorada por Git. El destino debe ser nuevo.
