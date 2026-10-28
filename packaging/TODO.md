# TODO · M8 empaquetado

Estado: sidecars one-dir + ensamblado Linux probados de verdad; CI y PowerShell
escritos pero **sin correr** en esta ventana (no hay Windows ni runners locales).

## Hecho

- `packaging/pyinstaller/{sifid,sifi}.spec` (one-dir) + `sifid_entry.py`,
  `sifi_entry.py`, `_common.py`.
- `packaging/vendor/fetch_binaries.sh` (idempotente, `--check` verifica sha256
  contra `MANIFEST.json`, funciona offline) + `README.md` + carpetas `<plat>`.
- `scripts/build_linux.sh` → `dist/sifi-desk-linux/` con `sifid`/`sifi`,
  `packaging/vendor/linux-x86_64/` y verificación `sifid --help` + `sifi version`.
  Corrido en esta máquina: OK (191 MB, Python 3.12, PyInstaller 6.22.3).
- `scripts/package_deb.sh`, `scripts/package_appimage.sh` (tolera falta de
  appimagetool).
- `.github/workflows/build.yml`: matrix ubuntu/windows, pytest, sidecars, `.deb`,
  `.AppImage`, `.msi` Tauri tolerante a fallo, artefactos y release por tag.
- `scripts/build_windows.ps1` equivalente PowerShell.

## Falta / pendiente

1. **Probar `build_windows.ps1` en un Windows real** (acá no hay pwsh). Riesgos:
   `bash` de Git for Windows para `fetch_binaries.sh`, y que el `.msi` de Tauri
   todavía no tiene `ui/tauri.conf.json` (hoy se saltea con warning).
2. **RNAplfold para Windows**: no hay binario estático oficial; hay que compilar
   ViennaRNA con MSYS2/MinGW o usar el instalador y copiar `RNAplfold.exe` a
   `packaging/vendor/win32-AMD64/`. El bundle Windows hoy sale sin él.
3. **Pin de hashes**: `MANIFEST.json` se genera al bajar; falta revisarlo y
   commitearlo por plataforma (hoy está gitignoreado junto con los binarios).
4. **AppImage sin probar** (no hay appimagetool en esta máquina): el script
   scrapea el binario a `build/appimagetool` y, si falla, sale 0 sin artefacto.
5. **No hay `pyproject.toml`** en el repo: el CI instala
   `packaging/requirements-build.txt`. Si aparece el paquete, cambiar a
   `pip install -e .[dev]`.
6. **UI**: `build_linux.sh` copia `dist/ui`, `ui/dist` o `agent/dist` si existen;
   no hay UI compilada en este worktree, así que el bundle sale API/CLI-only.
7. **Firma de código** (Windows Authenticode / Linux) sin hacer: fuera del
   alcance de M8.
8. `core/service/worker.py` lanza el runner con `cwd=CORE_DIR`; congelado cae en
   `<bundle>/_internal`, que existe, pero conviene que el core acepte `cwd`
   opcional (anotado en `docs/PREGUNTAS.md`).
