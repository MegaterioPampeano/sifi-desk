# packaging/ — cómo se arma siFi-Desk (M8)

siFi-Desk es una app de escritorio. El núcleo científico es Python puro
(`core/sifi`, `core/service`), así que el "instalador" es un **Python embebido +
dos binarios externos** puestos en una carpeta autocontenida. No hay daemon del
sistema, no hay `pip install`, no hay Python del usuario involucrado.

Distribución: **Windows primero**, después Linux. **No hay macOS** (ni spec ni
firma; si aparece, hay que rehacer `packaging/pyinstaller/*.spec` con
`BUNDLE`/`target_arch` propios y notarizar).

## Qué se construye, y dónde

| artefacto | comando | sale en | contenido |
|---|---|---|---|
| bundle de escritorio (Linux) | `bash scripts/build_linux.sh` | `dist/sifi-desk-linux/` | `sifid`, `sifi`, `_internal/`, `packaging/vendor/linux-x86_64/`, `licenses/` |
| bundle de escritorio (Windows) | `powershell -File scripts/build_windows.ps1` | `dist/sifi-desk-windows/` | ídem con `.exe` |
| `.zip` para repartir (Windows) | idem (paso 4b) | `dist/sifi-desk-windows.zip` | el bundle completo + `LEEME.txt` |
| `.deb` | `bash scripts/build_linux.sh --deb` | `dist/sifi-desk_<ver>_amd64.deb` | bundle en `/opt/sifi-desk` + lanzadores en `/usr/bin` |
| `.AppImage` | `bash scripts/package_appimage.sh dist/sifi-desk-linux` | `dist/*.AppImage` | bundle + `AppRun` (necesita `appimagetool`) |
| `.msi` (Tauri) | `scripts/build_windows.ps1` (sin `-SkipMsi`) | `ui/src-tauri/target/release/bundle/msi/*.msi` | sólo si existe `ui/tauri.conf.json` + Rust |
| CLI sola (servidores) | `python3 -m PyInstaller packaging/pyinstaller/sifi.spec` | `dist/sifi-cli/` | `sifi` sin FastAPI/uvicorn |

Los dos sidecars (`sifid.spec`, `sifi.spec`) son **one-dir, nunca one-file**:
one-file descomprime en un `/tmp` nuevo en cada arranque (3-5 s), deja basura y
rompe los binarios externos que se lanzan por `subprocess`/`execv`.

En el bundle de escritorio hay **un solo ejecutable** (`sifid`) y `sifi` es una
**copia del mismo binario**: el modo se elige por `argv[0]`
(`packaging/pyinstaller/sifid_entry.py`). Así hay un único `_internal/` (~190 MB
con Python 3.12 + numpy + biopython + fastapi) y no dos.

## Compilar a mano

Sin `sudo`, con PyInstaller de usuario (el sistema tiene PEP 668: `pip3` a secas
falla):

```bash
pip3 install --user --break-system-packages pyinstaller        # o un venv
bash scripts/fetch_binaries.sh                                 # binarios → packaging/vendor/<plat>/
bash scripts/build_linux.sh                                    # tests + build + smoke real
ls -la dist/sifi-desk-linux/                                   # sifid, sifi, _internal, packaging, licenses
```

`scripts/build_linux.sh` hace, en orden: tests, chequeo de binarios, PyInstaller,
ensamblado (UI compilada si existe) y un **smoke de verdad**: arma el índice de
juguete con el `bowtie-build` del bundle, corre `sifi design` y corre la misma
corrida **por la API** (eso ejercita el runner congelado, `sifid --runner`, que es
la parte que `--help` no prueba). Flags: `--no-tests`, `--no-smoke`, `--cli-only`,
`--deb`.

En Windows, el equivalente es `scripts/build_windows.ps1` (`-NoTests`, `-SkipMsi`,
`-NoZip`, `-FetchOnly`, `-Python <exe>`).

## Probar el artefacto

Lo mínimo (lo que corre el build):

```bash
B=dist/sifi-desk-linux
$B/sifid --help                 # el sidecar arranca
$B/sifi doctor                  # resuelve bowtie + RNAplfold del bundle y dice versión/sha256
$B/sifi version
```

Una corrida real, desde **fuera del repo** (así se detecta cualquier dependencia
del cwd o de rutas relativas):

```bash
T=$(mktemp -d); cd $T
$B/packaging/vendor/linux-x86_64/bowtie-build -q /ruta/repo/tests/data/toy.fa toyidx
$B/sifi design -q /ruta/repo/tests/data/query.fa -d $T --db-name toyidx -o $T/out --quiet
python3 -m json.tool $T/out/results.json | head
```

API (lo que usa la UI):

```bash
$B/sifid --port 8791 --data-dir /tmp/sifid-demo &
curl -s localhost:8791/health
curl -s -X POST localhost:8791/runs -H 'content-type: application/json' \
  -d "{\"mode\":\"design\",\"query_path\":\"$T/q.fa\",\"db_dir\":\"$T\",\"db_name\":\"toyidx\"}"
curl -s localhost:8791/runs/<run_id>
curl -s localhost:8791/runs/<run_id>/results
```

Chequeos rápidos que ya salvaron un build:

- `sifi doctor` tiene que mostrar el path **dentro del bundle**
  (`.../sifi-desk-linux/packaging/vendor/linux-x86_64/bowtie`). Si muestra un path
  del repo, el bundle quedó leyendo de afuera.
- `_internal/sifi/score.yaml` **tiene que existir**. Si falta, `sifi design` muere
  con `FileNotFoundError: .../sifi/score.yaml` (pasó: `_common.py` no lo copiaba).
- `sifi --help` NO alcanza como verificación: no toca ni score.yaml, ni binarios,
  ni el runner.

## Binarios externos (`packaging/vendor/<sys.platform>-<machine>/`)

Layout, procedencia y licencias: `packaging/vendor/README.md`. Resumen:

```
packaging/vendor/linux-x86_64/    bowtie 1.3.1, bowtie-build, bowtie-align-s,
                                  bowtie-build-s, RNAplfold 2.7.2, MANIFEST.json
packaging/vendor/win32-AMD64/     ídem (.exe) — se arma en Windows/CI
```

Se bajan con `scripts/fetch_binaries.sh` (o `packaging/vendor/fetch_binaries.sh`,
que es el de verdad; el de `scripts/` sólo delega). Estrategias: `SIFI_VENDOR_SRC`,
`build/` del checkout, `PATH` y por último descarga (bowtie desde GitHub Releases;
ViennaRNA desde `SIFI_VIENNA_URL`).

**No se versionan** (son ~30 MB Linux / ~35 MB Windows y tienen licencias
propias). Consecuencia: un CI limpio sin red para esos hosts produce un bundle
**sin** bowtie/RNAplfold (`SIFI_VENDOR_OPTIONAL=1`, el workflow lo tolera y el
smoke se saltea). Es el agujero #1 a cerrar: ver `packaging/TODO.md`.

`core/sifi/tools.py` resuelve `packaging/vendor/<plat>/` **primero** y sin
variables de entorno: congelado, `sifi/tools.py` vive en
`<bundle>/_internal/sifi/tools.py`, `ROOT` cae en `<bundle>/` y el candidato es
`<bundle>/packaging/vendor/<plat>/`. Por eso el destino de los datos en los
`.spec` es esa misma ruta relativa y no `bin/`.

## CI (`.github/workflows/build.yml`)

`test` (matrix ubuntu/windows) → `build-linux` (.deb + .AppImage + bundle) y
`build-windows` (.zip + `.msi` si hay `ui/tauri.conf.json`) → artefactos subidos;
en tags `v*`, `release` adjunta los binarios al release.

## Qué falta para firmar

Nada de esto está hecho; hoy los artefactos salen **sin firma**.

1. **Windows (Authenticode)**: hace falta un certificado de code signing (OV o,
   mejor, EV/HSM). Con el `.pfx` a mano:
   `signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p <pass> sifid.exe sifi.exe`.
   Firmar **antes** de armar el `.zip`/`.msi`, y firmar también el `.msi`.
   Sin firma, SmartScreen va a tirar "editor desconocido" en cada release.
2. **`.msi`**: Tauri firma con `bundle.windows.certificateThumbprint` +
   `digestAlgorithm: "sha256"` + timestamp server; requiere que `ui/` exista (hoy
   no está en esta rama).
3. **Linux**: `.deb` → firmar el repo con `reprepro`/`dpkg-sig` y publicar la
   clave; `.AppImage` → GPG detached (`.AppImage.sig`) o, mejor, embebido con
   `appimagetool --sign`. Hoy sólo hay `SHA256SUMS.txt` en el bundle.
4. **Reproducibilidad**: `requirements-build.txt` está pinneado, pero no hay
   `--no-build-isolation`/hashes ni `SOURCE_DATE_EPOCH`; los `.so` de numpy
   dependen del wheel del runner.
5. **macOS**: no se distribuye (sin Developer ID ni notarización).

## Ver también

- `packaging/TODO.md` — estado y pendientes reales (probado / sin probar).
- `packaging/vendor/README.md` — binarios externos.
- `docs/ROADMAP.md` §8 — alcance del frente.
