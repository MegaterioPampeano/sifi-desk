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
| Linux x86_64| `linux-x86_64/`          | `bowtie-1.3.1-linux-x86_64.zip` (oficial) + ViennaRNA compilado |
| Windows x64 | `win32-AMD64/`           | bowtie **compilado** (el release 1.3.1 no trae win) + ViennaRNA compilado |

Los binarios **no** se versionan (son pesados y tienen licencias propias); este
repo sólo guarda el `.gitkeep` de cada carpeta, el script que los arma y los
**pins** (`pins.sh`: URL + sha256 de cada fuente).

## Armarlos (build y CI)

```bash
bash scripts/build_vendor_linux.sh              # Linux: baja bowtie, compila VRNA
bash packaging/vendor/build_vendor_windows.sh   # Windows: compila los dos (MSYS2/MinGW64)
```

* Todo sale de `pins.sh` y se verifica con sha256: si el upstream cambió, el
  build **falla** (actualizar el pin es un commit explícito, no un accidente).
* Cachea en `build/dl/` (descargas) y `build/vendor/<plat>/` (binarios); el CI
  cachea ambos directorios.
* Windows no tiene binario oficial ni de bowtie 1.3.1 ni de ViennaRNA: se
  compilan con MinGW64 y se copian las DLLs de runtime (`libgcc_s_seh-1.dll`,
  `libstdc++-6.dll`, `libwinpthread-1.dll`) al lado de los `.exe`.

## Otros modos de `fetch_binaries.sh`

```bash
bash packaging/vendor/fetch_binaries.sh            # auto (fuentes locales o descarga)
bash packaging/vendor/fetch_binaries.sh --check    # sólo verifica sha256/existencia
bash packaging/vendor/fetch_binaries.sh --force    # rehacer
```

* Idempotente: si el archivo ya está, no descarga nada (`--force` para rehacer).
* Deja un `MANIFEST.json` con el sha256 de cada binario; `--check` lo verifica y
  falla si algo cambió o falta (es el modo que usa el build y el CI, offline).
* Fuentes en orden: `SIFI_VENDOR_SRC`, `build/` del checkout, `PATH` y por último
  descarga (bowtie del release oficial con hash fijado).
* Sin red: si los binarios ya están, `--check` y los builds funcionan offline.
* `SIFI_VENDOR_OPTIONAL=1` permite compilar el bundle sin binarios (queda sin
  bowtie/RNAplfold): es **sólo para desarrollo** y hay que pedirlo explícitamente;
  el build y el CI fallan si faltan.

Los `.spec` copian esa carpeta al bundle en la **misma ruta relativa**
(`packaging/vendor/<plat>/`), que es la primera que mira `core/sifi/tools.py`.
