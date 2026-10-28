# TODO de sifid (M3)

Lo que falta para que el servicio esté listo para la app/agente. Ordenado por lo que
primero duele. Lo que depende del core está en `NEEDS.md`.

## Antes de exponerlo fuera de loopback

- [ ] **Auth**: token bearer (`SIFID_TOKEN` o archivo en `<data-dir>/token`) y chequeo en
      todas las rutas salvo `/health`. Hoy escucha en 127.0.0.1 sin auth (v1).
- [ ] **CORS / CSRF**: si la UI corre en otro origen o en un navegador, whitelist explícita.
- [ ] Límite de tamaño del FASTA embebido y del `query_path` (evitar que un agente mande
      500 MB por accidente).
- [ ] `--host 0.0.0.0` debería exigir token configurado (abortar si no hay).

## Funcionalidad

- [ ] **Progreso real por registro** (bloqueado por `NEEDS.md` #1).
- [ ] **Multi-panel en una corrida** (bloqueado por `NEEDS.md` #3): hoy `panel_id` es uno.
- [ ] `GET /runs/{id}/artifacts/{name}` para bajar `sirnas.tsv`/FASTA de siRNAs y
      `GET /runs/{id}/log` para ver `stderr.log` (ahora hay que ir al run dir).
- [ ] `POST /runs/{id}/retry`: reencolar a partir del `spec.json` guardado (útil para
      `error`/`interrupted`).
- [ ] Borrar corridas (`DELETE /runs/{id}`) + retención/poda por antigüedad o cantidad.
- [ ] `GET /runs/{id}/results?format=csv|tsv` (el core ya escribe `sirnas.tsv`).
- [ ] Webhooks/SSE (`GET /runs/{id}/events`) para que el agente no haga polling.
- [ ] `POST /runs` multipart (`file=@query.fa`) para clientes que no comparten filesystem.
- [ ] Reanudar una corrida interrumpida en vez de sólo marcarla `error` (requiere que el
      core permita retomar por registro; ver `NEEDS.md` #2).

## Operación

- [ ] Unidad `systemd --user` (`sifid.service`) con `Restart=on-failure` y `--data-dir`
      fuera de `/tmp` (hoy el default es `~/.sifidesk/sifid`, que está bien; `/tmp` es sólo
      para pruebas).
- [ ] Rotación de `runs/` (los `out/` y `stderr.log` crecen; no hay límite).
- [ ] `/health` más profundo (`?deep=1`): verificar que bowtie/RNAplfold arrancan y que el
      `data-dir` es escribible; hoy sólo reporta estado del proceso y la cola.
- [ ] Métricas Prometheus (opcional): duración por corrida, tamaño de cola, tasa de error.
- [ ] Empaquetado: cuando M8 arme el bundle, `service` tiene que viajar con el core y los
      binarios; revisar que `CORE_DIR`/`PYTHONPATH` sigan resolviendo en el instalado.

## Deuda chica

- [ ] El manifest se sirve crudo desde `out/results.json`; si se poda el run dir, la fila
      queda `done` sin resultados (hoy `/results` devuelve 500 con mensaje claro). Mejor:
      guardar el manifest en la DB o comprimirlo en `<data-dir>/manifests/`.
- [ ] `progress.percent` con `total=0` da 0.0; no debería pasar porque se valida el FASTA,
      pero conviene un test de regresión si se agrega entrada por stream.
- [ ] Revisar concurrencia de `Store` bajo muchos lectores (una conexión + lock alcanza
      para un servicio local; si crece, pool de conexiones de sólo lectura).
