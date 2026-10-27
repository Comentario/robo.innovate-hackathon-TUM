# Réplica de render con cuatro GPU

Instancia `brickflow-cinematic-4gpu`, Brev ID `eztxpn39l`, creada el 27/10/2026.
Oferta consultada por CLI: `verda_RTXPro6000x4`, 9.396 USD/h; 120 vCPU,
360 GiB RAM, disco 1 TB, cuatro RTX PRO 6000 Blackwell Server Edition de
96 GB. El sistema instalado es Ubuntu 24.04.4 y driver NVIDIA 580.126.09.
La instancia original `brickflow-cinematic` (`79khozc7`) fue eliminada de Brev
después de verificar íntegramente su restauración en esta VM.

Unreal 5.8.4 se instaló desde el ZIP original del propietario: SHA-256
`cdff1e0c02010eb4fcf9c38d293cfd0f1afda09272256c146d73db52f570f607`.
Se copiaron proyecto, assets, configuración y binarios; todos sus hashes
coinciden. Blender 4.5.3 arranca. El entorno virtual se actualizó a Python 3.12:
Playwright 1.64.1 importa correctamente y Chromium 156.0.8078.4 arranca headless.

Prueba `Saved/Films/four-gpu-smoke-v1-part0` .. `part3`: cada proceso declaró
`Using device at index N of 4` para N=0,1,2,3, produjo dos frames H264 1080p
y cerró Unreal y encoder con código 0. Esto prueba asignación y funcionamiento;
no es una medición del factor de aceleración de un render completo.

Prueba adicional `four-gpu-codec-smoke-v2`: doce frames por tarjeta, todos los
renders y encoders con código 0. `gpu-codec-processes.csv` registra cuatro UUID
distintos ejecutando FFmpeg. El índice selecciona tanto el adaptador Vulkan
como el codificador NVENC, evitando concentrar los cuatro encoders en GPU 0.

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
La transferencia y restauración terminaron. SHA-256 del archivo de históricos:
`e04523a1e03d06da56ab7d423ca7b51ba753a1490903c436ea149cc6fc99f2c9`.
Se comprobaron las 2,333 entradas restauradas, hashes del proyecto y del vídeo,
traza nativa completa y timestamps del MP4. Evidencia local:
`artifacts/unreal_four_gpu/final-verification.json` y `source-retirement.json`.
La clave temporal que usaba la VM anterior se revocó tras eliminarla.

## Segunda VM dedicada a Jacob

`brickflow-cinematic-jacob-4gpu`, ID `f9firmbdt`, misma oferta
`verda_RTXPro6000x4`, Ubuntu 24.04.4 y driver 580.126.09. El miembro
`jacob.behrendt03-5174e3` / `jacob.behrendt03@gmail.com` tiene acceso SSH
confirmado por Brev a `shadeform`. La VM está creada en la organización del
propietario; no se transfirieron credenciales personales ni se inició sesión
suplantando a Jacob.

`replicate_peer_cloud.sh` copia software, proyecto, repositorio, configuración
y artefactos completos desde la primera VM de cuatro GPU. Reinstala Unreal
desde el mismo ZIP verificado y recupera Chromium para el entorno copiado.
No genera otra película. Excluye staging de transferencia, PID y registros
administrativos que son propios de cada máquina. En este checkpoint la copia
de Jacob sigue en marcha. Las dos ofertas suman 18.792 USD/h.

Jacob puede conectar con su cuenta:

```bash
brev login
brev org set a.saldarriaga-6a4314-xdgb
brev shell brickflow-cinematic-jacob-4gpu
```
