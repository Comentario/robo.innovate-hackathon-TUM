# Ensayo completo con un solo comando

Desde el workspace de Múnich en VS Code, abrir una terminal. Las dependencias
ROS Humble y MoveIt local deben estar preparadas como indica `reference_arm.md`.
Cerrar primero las terminales de demos anteriores con Ctrl+C; el lanzador rechaza
sesiones ocupadas y nunca termina una sesión ajena.

```bash
python3 scripts/rehearse.py normal
# Después de cerrar el ensayo anterior:
python3 scripts/rehearse.py recovery
```

El comando inicia una escena vacía, MoveIt y RViz, y después el ejecutor.
En RViz aparecen el paso actual, la acción y cuántos ladrillos hay colocados en
la escena. `normal` recoge y coloca los doce. `recovery` coloca cuatro, muestra
STOPPED durante ocho segundos, reconstruye el cliente, verifica la escena y
completa las ocho posiciones restantes. Los contornos verdes identifican las
cuatro posiciones preservadas. No se reinicia el servidor durante esa recuperación.

Cada ensayo crea su propio `artifacts/rehearsal_FECHA_HORA/`. `summary.html`
resume el resultado en inglés; `result.json` contiene la evidencia, `state.sqlite3`
el journal, y `server.log`/`client.log` permiten investigar un fallo. En recuperación
se añade `index.html` con la evaluación de reconciliación. Abrir `summary.html`
cuando termine el comando o se cierre con Ctrl+C.

La vista final permanece diez minutos; Ctrl+C cierra los procesos de este ensayo
y conserva sus archivos. Un fallo también cierra esos procesos y deja evidencia.
Para una presentación lenta usar `--speed 1`; el valor predeterminado es 3.
`--hold 30` conserva la vista final treinta segundos. Una carpeta explícita con
`--output-dir artifacts/mi_ensayo` debe ser nueva: no se sobrescriben journals.

Para verificar sin abrir una ventana:

```bash
python3 scripts/rehearse.py normal --headless --speed 5 --hold 0
```

Esto es reproducción cinemática con trayectorias MoveIt y piezas sintéticas.
No hay física de contacto ni robot real ni percepción de persona 1 integrada.
El contador representa objetos colocados en la escena; no una medición externa.
Una ejecución completada sigue esperando observación independiente del pallet.
El lanzador inicia un ensayo nuevo, no recupera una sesión anterior abortada.
Si se interrumpe mientras transporta una pieza, conservar el journal y evaluar
esa escena antes de plantear recuperación: no repetir acciones automáticamente.

## Comprobación realizada

El 18 de octubre de 2026 se ejecutaron desde una escena nueva ambos escenarios
con el lanzador: normal completó doce colocaciones; recuperación conservó cuatro
objetos sin cambios y completó doce con 64 acciones nuevas. Los registros locales
están en `artifacts/rehearsal_20261018_233930_514441/` y
`artifacts/rehearsal_20261018_234118_411502/`. Se comprobó además el rechazo de una
segunda sesión, el cierre por SIGTERM con journal conservado y la legibilidad
de las etiquetas en una captura real de RViz (`artifacts/rehearsal_visual_final/rviz_status.png`).
Las once pruebas del adaptador pasan, incluida la distinción visual entre
colocaciones de la escena y validación independiente pendiente. Los ensayos
`rehearsal_visual_check` y `rehearsal_visual_final` se interrumpieron deliberadamente
para comprobar el cierre; no deben interpretarse como ciclos completados.
