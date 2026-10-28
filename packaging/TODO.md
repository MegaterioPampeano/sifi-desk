# TODO · empaquetado

Estado **M10 (empaquetado v2)**: el instalable de Linux lleva núcleo + UI (si está
compilada) + **agente**, y se construye desde cero en una máquina limpia (los
binarios externos se compilan/bajan con sha256 fijado y el build falla si el smoke
no puede correr). Verificado acá: bundle 179 MB, `.deb` 49 MB, `.AppImage` 53 MB,
`128 passed`, smoke CLI+API OK, `sifi doctor` con el agente en verde y perfil `sifi`
montando desde el bundle.

Windows: scripts reescritos (D3, D6, agente, vendor obligatorio) pero **sin correr
en un Windows real** en esta ventana.

## Hecho en M10

1. **El agente viaja en el instalable** — `packaging/agent/` es un mini-frente
   propio:
   - `bundle_agent.sh` copia `agent/` (perfil `dsh/profiles/sifi`, bundle
     `dsh/bundles/sifi-tools`, `src/`, `prompts/system.md`, `bin/`, `test/`) al
     artifacto, sin `node_modules`/`.env`/estado, y escribe `INFO.json` con el pin
     de dsh y el inventario. Medido: **23 archivos, 505 kB** (+`install.sh`,
     `INFO.json`; la carpeta en el bundle ocupa 592 kB).
   - `install.sh` (sin sudo) copia a `~/.sifi/agent` (`$SIFI_AGENT_HOME`) y corre
     `npm ci`; idempotente por hash del lock; `--light` no instala el CLI de dsh.
     Probado desde el bundle real: **621 paquetes en 11 s, 884 MB**.
   - `agent_doctor.py` + hook en `packaging/pyinstaller/sifid_entry.py`: `sifi
     doctor` informa node/dsh/harness y **monta el perfil de verdad**
     (`dsh --profile sifi --dump-config`). No toca `core/`.
   - **Decisión (b)**: Node 22+ y dsh son prerrequisito, no van embebidos.
     Medición: Node portátil 30,8 MB comprimido / 205 MB expandido (`bin/node`
     123 MB) + árbol de dsh 884 MB = ~1,1 GB → `.deb` ≥300 MB contra 62 MB de
     D2. Detalle en `packaging/agent/README.md`.
2. **Brecha #1 cerrada (binarios de `packaging/vendor/`)**
   - `packaging/vendor/pins.sh`: única fuente de verdad (URL + sha256) de bowtie
     1.3.1 (zip linux / fuente win) y ViennaRNA 2.7.2 (fuente).
   - `scripts/build_vendor_linux.sh`: baja bowtie del release (**sha256 verificado**)
     y **compila** RNAplfold (`--without-perl --without-python --without-doc
     --disable-openmp`), publica en `packaging/vendor/<plat>` con `MANIFEST.json`.
     Probado desde cero (borré `build/vendor` y `packaging/vendor/linux-x86_64`):
     bowtie sha256 ok, ViennaRNA sha256 ok, compilación OK, **6 binarios, 30,2 MB**.
   - `fetch_binaries.sh` ahora **falla** si falta un binario (antes avisaba) y
     verifica sha256 de cada descarga; URL custom sin `SIFI_*_SHA256` se rechaza.
   - `scripts/build_linux.sh`: si `--check` falla corre el build de vendor; si aun
     así falta, `exit 1`. `SIFI_VENDOR_OPTIONAL=1` sigue existiendo **sólo** si el
     que compila lo pide (nunca automático) y en ese caso fuerza `--no-smoke`.
   - El smoke ahora es **obligatorio**: sin `bowtie-build`/`RNAplfold` en el
     bundle, el paso 6/6 muere en vez de saltearse.
3. **D3/D6** — raíz de Tauri = `ui/tauri/` en `.github/workflows/build.yml` y
   `scripts/build_windows.ps1`; el sidecar se emite como
   `sifid-<target-triple>[.exe]` (`x86_64-unknown-linux-gnu`,
   `x86_64-pc-windows-msvc`) y en Linux se deja además en
   `ui/tauri/src-tauri/binaries/`. Hardlinks: `sifi`/sidecar no duplican 13 MB
   (bajó el bundle de 205 → 179 MB y el `.deb` de 62 → 49 MB).
4. **`.AppImage` sin sudo**: `scripts/package_appimage.sh` baja `appimagetool`
   1.9.1 a `packaging/.tools/` (gitignoreado, sha256 fijado) y lo corre con
   `--appimage-extract-and-run` (no necesita FUSE ni root). Si falla, imprime el
   log y sale **1** (antes salía 0 sin artefacto). Generado y probado acá:
   `dist/sifi-desk-x86_64.AppImage` (53 MB), `--help` responde con el `sifid` real.

## Falta / pendiente

1. **Windows real**: `build_windows.ps1` + `packaging/vendor/build_vendor_windows.sh`
   (MSYS2/MinGW64) están escritos y revisados, no corridos. Riesgo principal: que
   bowtie 1.3.1 compile con el MinGW posix-threads del runner y que el `.exe` de
   RNAplfold encuentre sus DLLs (`collect_dlls` copia `libgcc_s_seh-1.dll`,
   `libstdc++-6.dll`, `libwinpthread-1.dll`). Si falla, el CI queda rojo a
   propósito: no se publica un zip sin bowtie/RNAplfold.
2. **`ui/tauri/src-tauri/src/main.rs` busca `sifid` plano** junto al `.exe`, pero
   Tauri deja el `externalBin` como `sifid-<triple>`. El `.msi` va a arrancar sin
   sidecar hasta que el frente UI lo resuelva (o pase a
   `tauri_plugin_shell::ShellExt::sidecar`). No se tocó `ui/**` (M10 no lo tiene).
3. **Instalación del harness requiere red** la primera vez (`npm ci`: 621
   paquetes, 884 MB en `~/.sifi/agent`). Alternativa para redes cerradas:
   publicar un tarball del `node_modules` como release propia y dar
   `SIFI_AGENT_TARBALL`+sha256 (mismo mecanismo que `SIFI_VIENNA_URL`).
4. **dsh del sistema ≠ pin**: acá hay 0.2.0-rc.2 global; `doctor` lo marca con `!`
   (no rompe) y `install.sh` completo instala 0.2.1-rc.2 en `~/.sifi/agent`. Si el
   producto fija 0.2.1-rc.2, conviene que `sifi-tools` suba el warning a error.
5. **AppImage y FUSE**: el `.AppImage` generado se probó con
   `--appimage-extract-and-run`; en máquinas sin `libfuse2` el usuario necesita
   ese flag (documentado en el `LEEME`? no: falta en el README de usuario).
6. **Firma de código** (Authenticode / Linux) sigue sin hacer: fuera de alcance.
7. **UI compilada**: `build_linux.sh` copia `dist/ui`, `ui/dist` o `agent/dist` si
   existen; en este worktree no hay build de UI, así que el bundle sale API/CLI +
   agente (el `.msi`/`.deb` con UI depende de compilar Tauri).
8. `core/service/worker.py` lanza el runner con `cwd=CORE_DIR`; congelado cae en
   `<bundle>/_internal`, que existe, pero conviene que el core acepte `cwd`
   opcional (anotado en `docs/PREGUNTAS.md`).

## Comandos

```bash
# Linux, de cero (compila binarios si faltan) — el que usa el CI
bash scripts/build_linux.sh --deb --appimage

# sólo binarios externos (cacheable en CI)
bash scripts/build_vendor_linux.sh

# bundle de desarrollo sin binarios (NO publicable)
SIFI_VENDOR_OPTIONAL=1 bash scripts/build_linux.sh --no-smoke
```
