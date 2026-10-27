# Réplica de render con cuatro GPU

Instancia `brickflow-cinematic-4gpu`, Brev ID `eztxpn39l`, creada el 27/10/2026.
Oferta consultada por CLI: `verda_RTXPro6000x4`, 9.396 USD/h; 120 vCPU,
360 GiB RAM, disco 1 TB, cuatro RTX PRO 6000 Blackwell Server Edition de
96 GB. El sistema instalado es Ubuntu 24.04.4 y driver NVIDIA 580.126.09.
La instancia original `brickflow-cinematic` se conserva.

Unreal 5.8.4 se instaló desde el ZIP original del propietario: SHA-256
`cdff1e0c02010eb4fcf9c38d293cfd0f1afda09272256c146d73db52f570f607`.
Se copiaron proyecto, assets, configuración y binarios; todos sus hashes
coinciden. Blender 4.5.3 arranca. El entorno Python requiere actualización
a 3.12 en esta imagen para recuperar Playwright/Chromium.

Prueba `Saved/Films/four-gpu-smoke-v1-part0` .. `part3`: cada proceso declaró
`Using device at index N of 4` para N=0,1,2,3, produjo dos frames H264 1080p
y cerró Unreal y encoder con código 0. Esto prueba asignación y funcionamiento;
no es una medición del factor de aceleración de un render completo.

Rutas idénticas en ambas VM:

- `~/workspace/brickflow-native`: proyecto editable, binarios y scripts.
- `~/workspace/brickflow-cinematic`: Blender, Python, escena histórica y tools.
- `~/workspace/brickflow-cinematic/tools/unreal-5.8.4`: instalación de Unreal.

`render_film_cloud.sh` acepta el índice Vulkan como octavo argumento opcional.
El lanzador de cuatro GPU calcula intervalos contiguos sin alterar la cámara
ni la simulación. Un prefijo nuevo evita sobrescribir capturas previas:

```bash
bash ~/workspace/brickflow-native/launch_four_gpu_cloud.sh new-prefix 3840 0 11867
```

La copia entre VM usa una clave temporal exclusiva, restringida en destino,
con identidad de host fijada mediante la conexión autenticada de Brev.
No se copiaron las credenciales personales del equipo local.

Los históricos de `Saved` se trasladan tras cerrar los renders. Los PID y
archivos temporales `transfer-*` no se restauran. Estado en la VM original:
`Saved/Migration/copy.status`; log `Saved/Migration/copy.log`.
En este checkpoint el software ya funciona y la transferencia de históricos
continúa. Las carpetas `.migration` y `.engine-transfer` son staging temporal.
