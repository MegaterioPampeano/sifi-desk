# desktop/ — lanzadores de escritorio

Dos entradas, una por versión, para comparar cara a cara.

## siFi Desk (nuestro)

`desktop/sifi-desk.sh` levanta el servicio si no está corriendo (`systemd-run --user`,
puerto 8790, datos en `~/.sifidesk/sifid`) y abre la interfaz en el navegador con el token
de `~/.sifidesk/token`.

## siFi 21 original (2019)

`desktop/build_sifi21_gui.sh` arma todo en espacio de usuario, sin root:

1. **micromamba** en `~/bin/micromamba` (descarga el binario estático).
2. **Entorno Python 2.7 + PyQt4** en `~/sifi21-env`:
   `python=2.7 pyqt=4.11.4 numpy=1.16 biopython=1.76 pillow scipy=1.2` desde conda-forge
   y, por pip, `matplotlib==2.2.5 seaborn==0.9.0 pandas==0.24.2`.
   *matplotlib no puede venir de conda*: arrastra pyqt5 y choca con qt4 (icu/freetype).
3. **Copia del código** a `~/sifi21/app` (el `vendor/` queda intacto).
4. **Tres parches mínimos**, documentados en el script:
   - `FileDialog` (módulo de pywin32) → shim vacío, el original no lo usa.
   - ruta de datos: `QDesktopServices.DataLocation` + `split('Local')[0]` es lógica de
     Windows y arma rutas inválidas → se fija en `~/.sifidesk/sifi21/`.
   - binarios: `ToCopy/{Bowtie,RNAplfold}` traen `.exe` de Windows → symlinks a bowtie
     1.3.1 y RNAplfold de `build/`, con los nombres que el original invoca (`bowtie`,
     `bowtie-align-s`, ..., `RNAplfold`). Ojo: el `bowtie` del repo es un **wrapper** que
     hace `execv` de `bowtie-align-s`; hay que llevarse los hermanos también.
5. Lanzador `~/sifi21/sifi21-gui.sh` (hace `cd app`, PATH con los binarios, `python main.py`).

### Verificado

- Ventana real renderizada (tabs *Off-target prediction* / *Database managment*), 1200×800.
- `bowtie-build` desde la carpeta de datos → índices válidos (`demo_maiz`, `demo_humano`).
- `run_pipeline` completo en py2 con el código original: 880 alineamientos, JSON + PNG de
  diseño en 0,9 s.
- Gotchas: `QWidget.grab()` no existe en Qt4 (usar `QtGui.QPixmap.grabWidget`), y
  `run_pipeline` abre un diálogo bloqueante para elegir el target principal
  (`get_main_target()`), así que en pruebas desatendidas hay que fijarlo a mano.

### Notas de operación

- La GUI necesita sesión X. Si la pantalla está negra: `sudo systemctl start lightdm`
  (hay NOPASSWD para eso); `lightdm` queda `inactive` cuando se usa la tele por DRM.
- `desktop/sifi-original.sh` queda como alternativa sin ventana: corre el motor y abre sus
  dos gráficos, útil para guiones.
