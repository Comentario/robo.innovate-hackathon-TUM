# Modelo Greenfield 37 en la VM de Jacob

La entrega de código `5661f111d3b1895db16972cf8ed2cf520e9db0a1` se instala en
`~/workspace/brickflow-final-model-5661f11/`. La ruta estable
`~/workspace/brickflow-final-model/` apunta a esa versión después de verificarla.

La demo grabada está en `artifacts/greenfield_37/index.html`. El replay corresponde
a `ccaf03c52e40aaca`; el código editable posterior queda identificado por sus
hashes en `task3_checkpoint/greenfield_37/provenance.json`.

Para abrirla desde el equipo propio, con acceso Brev a Jacob:

```bash
brev port-forward brickflow-cinematic-jacob-4gpu -p 8737:8737
```

Abrir `http://localhost:8737/index.html`. El servidor de la VM escucha solamente
en loopback. Su PID y log están en `http-server.pid` y `http-server.log` dentro
de la carpeta versionada. Si se reinicia la VM, restablecerlo con:

```bash
python3 -m http.server 8737 --bind 127.0.0.1 \
  --directory "$HOME/workspace/brickflow-final-model/artifacts/greenfield_37"
```

`deployment-manifest.json` identifica los archivos instalados y sus hashes.
`deployment-verification.json` registra la comprobación de integridad, sintaxis
y carga del replay en Chromium. La evidencia descargada al repositorio está en
`task3_checkpoint/unreal_jacob_four_gpu/model37-deployment-verification.json`.

La comprobación del navegador solo confirma carga y contadores; se desactivó la
animación durante esa prueba. No es una revisión visual independiente. No se
recompiló Unreal ni se completó un port nativo de la 37. Los proyectos nativos y
las variantes de cámara existentes se conservan en sus carpetas originales.
