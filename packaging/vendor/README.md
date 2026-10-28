# Binarios externos (`packaging/vendor/`)

siFi-Desk no reimplementa el alineamiento ni la energía libre: usa **bowtie**
(`bowtie`, `bowtie-build`) y **RNAplfold** (ViennaRNA). Los tests no los necesitan
(corrren con `tests/data`), pero el instalable sí.

## Layout

```
packaging/vendor/<sys.platform>-<platform.machine>/
    bowtie            bowtie-1.3.1 (Artistic-2.0)
    bowtie-build
    RNAplfold         ViennaRNA (ViennaRNA License)
    LICENSE-bowtie.txt
    LICENSE-ViennaRNA.txt
```

Plataformas que usa el build:

| plataforma  | directorio               | origen                                  |
|-------------|--------------------------|-----------------------------------------|
| Linux x86_64| `linux-x86_64/`          | `bowtie-1.3.1-linux-x86_64.zip` + VRNA   |
| Windows x64 | `win32-AMD64/`           | `bowtie-1.3.1-win-x86_64.zip` + VRNA     |

Los binarios **no** se versionan (son pesados y tienen licencias propias); este
repo sólo guarda el `.gitkeep` de cada carpeta y el script que los baja.

## Bajar los binarios

```bash
bash packaging/vendor/fetch_binaries.sh            # plataforma actual
bash packaging/vendor/fetch_binaries.sh --all      # linux + windows
bash packaging/vendor/fetch_binaries.sh --check    # sólo verifica sha256/existencia
```

* Idempotente: si el archivo ya está, no descarga nada (`--force` para rehacer).
* Deja un `MANIFEST.json` con el sha256 de cada binario; `--check` lo verifica y
  falla si algo cambió o falta (es el modo que usa el build y el CI, offline).
* Fuentes en orden: `SIFI_VENDOR_SRC`, `build/` del checkout, `PATH` y por último
  descarga (bowtie 1.3.1 de GitHub Releases; ViennaRNA si pasás `SIFI_VIENNA_URL`).
* Sin red: si los binarios ya están, `--check` y los builds funcionan offline.
* `SIFI_VENDOR_OPTIONAL=1` permite compilar el bundle sin binarios (queda sin
  bowtie/RNAplfold: sirve para probar el empaquetado, no para entregar).

Los `.spec` copian esa carpeta al bundle en la **misma ruta relativa**
(`packaging/vendor/<plat>/`), que es la primera que mira `core/sifi/tools.py`.
