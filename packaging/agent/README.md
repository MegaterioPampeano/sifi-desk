# El agente dentro del instalable (M10)

El instalable de siFi-Desk lleva **también el agente**: el perfil de dsh, el
bundle `sifi-tools` con las 7 tools del producto, la persona
(`prompts/system.md`) y el cliente HTTP del servicio. Lo que **no** lleva es el
*runtime* del harness.

```
<bundle>/agent/
  package.json  package-lock.json        (el agente, npm privado)
  src/                                   api/client/tools/dsh-tools
  prompts/system.md                      persona (fuente única)
  bin/                                   entrypoints + lista de tools
  test/                                  banco de pruebas del agente
  dsh/                                   DSH_HOME del producto
    package.json  package-lock.json      pin: @deepseek-ai/dsh 0.2.1-rc.2
    profiles/sifi/{package.json,cordis.yml,cordis.patch.yml}
    bundles/sifi-tools/{package.json,index.mjs}
  install.sh                             bootstrap sin sudo → ~/.sifi/agent
  agent_doctor.py                        chequeo que usa `sifi doctor`
  INFO.json                              inventario + pin (lo escribe el build)
```

Tamaño en el artefacto: **~150 kB** de código (medido con `du`: 576 kB del
checkout incluye `dist/` viejo y tests; el `INFO.json` del build da el número
exacto). Impacto en el `.deb`: despreciable.

## Requisito de runtime: decisión (b), Node y dsh como prerrequisito

dsh corre sobre Node. Había dos caminos y se midieron los dos:

| opción | qué suma al bundle | medido acá |
|---|---|---|
| (a) embeber runtime | Node portátil | `node-v22.22.0-linux-x64`: **30,8 MB** comprimido, **205 MB** expandido (`bin/node` solo: **123 MB**) |
| | árbol de dsh (`npm ci`) | **884 MB**, **621 paquetes** (`@deepseek-ai/*` = 566 MB, más `node-pty` 26 MB, `sherpa-onnx` 32 MB, `sharp` 46 MB — **nativos por plataforma**) |
| (b) prerrequisito | nada en el artefacto | `.deb` sigue en **62 MB** |

Total de (a): ~1,1 GB de bundle, `.deb` estimado **≥ 300 MB** (hoy 62 MB con
191 MB de bundle), más un `node_modules` distinto por plataforma/arquitectura y
un `npm ci` de 621 paquetes que habría que correr en cada build (12 s con cache,
minutos en frío). Contra D2 (62 MB, revisar sólo con pedido concreto de tamaño)
esto no se sostiene: el `.deb` pesaría 5× y la mitad de lo embebido sería código
que no usamos (LLM providers, TTS, office).

**Decisión: (b)**. El instalable trae el agente; Node 22+ y dsh 0.2.1-rc.2 se
declaran prerrequisito y se verifican **en `sifi doctor`**, que es lo primero que
corre el usuario (y lo primero que corre el CI).

Contrapartida asumida: instalar el agente requiere red la primera vez
(`npm ci` desde el `package-lock.json`, con hashes de integridad) o un Node
instalado por el usuario. Ambos se detectan y se explican; nada falla en
silencio.

## Cómo queda andando (usuario final)

```bash
# 1. prerrequisito: Node 22+ (no hace falta sudo si usás el tarball oficial)
node -v && npm -v

# 2. bootstrap (copia el agente a un directorio escribible y baja el harness)
bash /opt/sifi-desk/agent/install.sh            # → ~/.sifi/agent (884 MB)
bash /opt/sifi-desk/agent/install.sh --light    # o sin el CLI de dsh: usá el del PATH

# 3. verificar / usar
sifi doctor
DSH_HOME=~/.sifi/agent/dsh dsh --profile sifi --dump-config
SIFID_URL=http://127.0.0.1:8765 DSH_HOME=~/.sifi/agent/dsh \
  dsh --profile sifi headless "Llamá a sifi_panels y resumí los paneles"
```

`install.sh` no toca nada del sistema: copia a `~/.sifi/agent` (o
`$SIFI_AGENT_HOME`), corre `npm ci` y marca el lock con un hash para ser
idempotente. `--light` no instala el CLI `dsh` y usa el del `PATH` (requiere
`npm i -g @deepseek-ai/dsh@0.2.1-rc.2`).

## Qué verifica `sifi doctor`

El bloque del agente lo agrega `packaging/pyinstaller/sifid_entry.py` (rama
`sifi`) llamando a `agent_doctor.report()`. No toca `core/`: si el agente no está
en el bundle, imprime `· agente: no incluido` y doctor queda igual que siempre.

```
✓ agente: node v22.22.0 (/usr/bin/node)
✓ agente: dsh 0.2.1-rc.2 (/home/u/.sifi/agent/dsh/node_modules/.bin/dsh)
✓ agente: harness instalado en /home/u/.sifi/agent
✓ agente: perfil `sifi` monta · bundle sifi-tools ×3 · 7 tools · DSH_HOME=...
```

Si el agente está incluido y el runtime no sirve, doctor sale **1** y dice qué
falta (Node viejo, dsh ausente, harness sin instalar, perfil que no monta). Búsqueda
de runtime, en orden: `SIFI_NODE`/`SIFI_DSH` → `<agent_home>/dsh/node_modules/.bin`
→ `PATH`.

## Verificación en el build

- `scripts/build_linux.sh` copia el agente (paso 4/6), corre `sifi doctor` y
  muestra el tamaño del bloque `agent/`.
- CI (`.github/workflows/build.yml`) instala Node 22 sólo para **probar** que el
  perfil monta: `npm ci` dentro del bundle + `dsh --profile sifi --dump-config`
  con `grep sifi-tools`. Ese `node_modules` se borra antes de subir el artefacto.
- Windows: `scripts/build_windows.ps1` copia el agente y corre `sifi doctor`;
  falta probarlo en un Windows real (ver `packaging/TODO.md`).
