# Preguntas para Mariano (bloqueantes)

> Si una tarea depende de una respuesta de acá, el agente NO la implementa: busca la
> siguiente tarea que no dependa y la hace.

_(vacío por ahora)_

## M8 · empaquetado

1. `core/service/worker.py` lanza el runner con `cwd=CORE_DIR` y `[sys.executable, "-m", "service.runner"]`.
   Congelado eso se parchea desde el entry point (`sifid --runner` + `runner_argv`),
   pero cwd cae en `<bundle>/_internal`. ¿Conviene que `Worker` acepte `cwd`/`env`
   explícitos desde `create_app` para no depender del layout de PyInstaller?
2. El bundle one-dir pesa 191 MB (numpy/biopython/fastapi). ¿Aceptable para el
   instalable, o preferís que `sifi` standalone salga sin fastapi/uvicorn
   (`sifi.spec`) y el instalable use sólo el sidecar del servicio?
3. ¿La UI Tauri va a vivir en `ui/` con `tauri.conf.json` en la raíz? El CI la
   busca ahí y, si no está, saltea el `.msi` con warning.
