# pins.sh — fuentes versionadas de los binarios externos (M10).
#
# Única fuente de verdad para las URLs y los sha256: la leen
# `packaging/vendor/fetch_binaries.sh`, `scripts/build_vendor_linux.sh` y
# `packaging/vendor/build_vendor_windows.sh`. Ningún binario se versiona en el
# repo: se compila (o se baja el zip oficial de Linux) y **si el hash no
# coincide el build falla**.
#
# Actualizar un pin = cambiar versión + hash acá, en un commit, y correr el
# smoke: usa `bowtie-build` + `RNAplfold` de verdad, así que un binario distinto
# se nota ahí y no en la máquina del usuario.

BOWTIE_VERSION="1.3.1"
# Linux x86_64: release oficial (binarios precompilados, ~52 MB de zip).
BOWTIE_URL_LINUX="https://github.com/BenLangmead/bowtie/releases/download/v${BOWTIE_VERSION}/bowtie-${BOWTIE_VERSION}-linux-x86_64.zip"
BOWTIE_SHA_LINUX="e538cf41bc1661981ea19dd187d5feea50a48664e6c879bd0fd2bcde80aa91ca"
# Windows: el release de bowtie 1.3.1 NO trae binarios win (sólo linux/macos),
# así que se compila del fuente con MSYS2/MinGW64 (build_vendor_windows.sh).
BOWTIE_SRC_URL="https://github.com/BenLangmead/bowtie/archive/refs/tags/v${BOWTIE_VERSION}.tar.gz"
BOWTIE_SRC_SHA="147d9fe9652f7c5f351bfc0eb012e06981986fb43bd6bdfe88a95c02eabc6573"

VIENNA_VERSION="2.7.2"
VIENNA_SRC_URL="https://www.tbi.univie.ac.at/RNA/download/sourcecode/2_7_x/ViennaRNA-${VIENNA_VERSION}.tar.gz"
VIENNA_SRC_SHA="1ab5f4a4f76fc85a2243546088e45f5d85f2d7a56cc656e969b005cce9bfab5f"
