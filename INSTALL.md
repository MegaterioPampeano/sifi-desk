# INSTALL.md — instalar siFi-Desk en otra máquina

Tres caminos, del más rápido al más "de producción". Todos asumen **Linux x86_64**
(Windows está en `packaging/README.md`, es más artesanal: MSYS2 para compilar bowtie y ViennaRNA).

## 1. Instalación de desarrollo (recomendada para la prueba)

```bash
git clone <repo> sifi-desk && cd sifi-desk
bash scripts/instalar.sh --paneles      # venv + deps + binarios + paneles (~170 MB de descarga)
```

Ese único comando deja: `.venv/`, bowtie 1.3.1 (sha256 fijado), RNAplfold si está en el PATH,
y los paneles de maíz B73, abeja, humano y Sulcia registrados en `~/.sifidesk/paneles`.

Después:

```bash
. .venv/bin/activate
python -m service.app --port 8790 --data-dir ~/.sifidesk/sifid \
    --panels-root ~/.sifidesk/paneles --ui-dir ui --token CAMBIAME
# http://127.0.0.1:8790   (el token va en X-Sifi-Token; la UI lo pide una vez)
```

Y el dossier A–D:

```bash
SIFI_BLASTN=$(command -v blastn) python core/cli.py dossier \
    docs/dossier_ventanas.json out/dossier --hilos 8
```

### Lo que hay que tener en el sistema

| pieza | ¿obligatoria? | cómo |
|---|---|---|
| python ≥ 3.10 | sí | paquete del sistema |
| `bowtie` + `bowtie-build` | sí | `scripts/instalar.sh` lo baja con hash fijado |
| `RNAplfold` | sí para eficiencia | `sudo apt-get install vienna-rna` o `scripts/build_vendor_linux.sh` |
| `blastn` (BLAST+) | sólo dossier/off-target fino | `sudo apt-get install ncbi-blast+` |
| `libpango`, `libharfbuzz` | sólo para el PDF | `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b` |
| `node ≥ 22` | sólo el agente | ver `packaging/agent/README.md` |

Sin `RNAplfold` el diseño corre igual pero sin el término de accesibilidad; sin `blastn` no hay
dossier y el off-target queda en bowtie (perfectos + mismatches), que es suficiente para el día a día.

## 2. Bundle autocontenido (sin python en la máquina destino)

```bash
bash scripts/build_linux.sh            # → dist/sifi-desk-linux/   (~200 MB)
bash scripts/build_linux.sh --deb      # → dist/sifi-desk_<ver>_amd64.deb
bash scripts/build_linux.sh --appimage # → dist/sifi-desk-x86_64.AppImage
```

El bundle trae python embebido, `sifid`, `sifi` y los binarios. **No trae los paneles**
(son datos, no programa): se copian aparte con `rsync -a ~/.sifidesk/panels/ destino:`.

## 3. Copiar una instalación que ya funciona

Lo más rápido si las dos máquinas se ven por red:

```bash
rsync -a --exclude .venv --exclude build --exclude .git ./ destino:~/sifi-desk/
rsync -a ~/.sifidesk/paneles/ destino:~/.sifidesk/paneles/
```

Los paneles ya vienen indexados (bowtie no es portable entre arquitecturas; si cambia
de x86_64 a ARM, hay que reindexar: `python3 core/cli.py panel add --panel-id X --fasta .../seqs.fa`).

## Verificación

```bash
python3 core/cli.py doctor        # binarios + versiones
python3 -m pytest -q tests/unit   # 169 tests
make golden                       # paridad 1:1 contra siFi original
```

## Paneles: qué hay y qué falta

| id | qué es | secuencias | cómo se consigue |
|---|---|---|---|
| `chicharrita` | TSA GITV de *Dalbulus maidis* | 56.117 | **no** está en NCBI como genoma: copiar de una instalación existente |
| `maiz` | CDS B73 GCF_902167145.3 | 57.345 | `scripts/bajar_paneles.sh` |
| `polinizador` | CDS *Apis mellifera* GCF_003254395.2 | 23.471 | idem |
| `humano` | CDS GRCh38.p14 GCF_000001405.40 | 146.337 | idem (≈25 min de indexado) |
| `simbionte` | Sulcia GCF_000147035.1 (proxy) | 1 (genoma) | idem |

⚠️ Los paneles `v1` que aparecen en `~/.sifidesk/panels/*/v1` son **decoys de 1–2 secuencias
de las pruebas**: no sirven para decidir nada. `resolve_panel` elige por fecha de creación,
así que un panel real siempre les gana — pero si querés sacarlos: `sifi panel` no tiene `remove`
en el CLI, se borran con `rm -rf ~/.sifidesk/panels/<id>/v1`.
