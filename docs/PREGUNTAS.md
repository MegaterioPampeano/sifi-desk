# Preguntas para Mariano (bloqueantes)

> Si una tarea depende de una respuesta de acá, el agente NO la implementa: busca la
> siguiente tarea que no dependa y la hace.

_(vacío por ahora)_

## Desde `ventana` (M5) — contrato con `sifid`

1. **Puerto y token.** El frontend asume hoy `http://127.0.0.1:8791` fijo dentro
   de Tauri y sin header de autenticación. El roadmap (§5.3) pide puerto efímero
   + token de sesión por request: ¿cómo anuncia `sifid` el puerto? (¿stdout,
   archivo en `%LOCALAPPDATA%`, flag `--print-port`?) Sin eso, `main.rs` no puede
   pasárselo a la UI.
2. **Chat del agente.** La maqueta expone `POST /agent/chat` (extensión propia).
   El contrato de §5.3 no lo incluye: ¿el chat va contra `sifid` o contra el
   harness de `agent/adapter/`? Mientras no se defina, la UI sólo funciona
   contra la maqueta.
3. **`binaries/sifid`.** `tauri.conf.json` usa `externalBin: binaries/sifid`:
   confirmar el nombre exacto que va a producir el PyInstaller de M8
   (`sifid-<target-triple>[.exe]`) y si `sifid` acepta `serve --host --port`.
