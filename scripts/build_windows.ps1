#Requires -Version 5.1
<#
.SYNOPSIS
    Compila el instalable de siFi-Desk en Windows: dist\sifi-desk-windows\.
.DESCRIPTION
    Equivalente a scripts/build_linux.sh. One-dir, un solo EXE + copia `sifi`
    (el dispatch es por argv[0], ver packaging/pyinstaller/sifid_entry.py).

    Resultado: dist\sifi-desk-windows\
        sifid.exe, sifi.exe, sifid-x86_64-pc-windows-msvc.exe   (D6: nombre Tauri)
        agent\                            (perfil dsh + sifi-tools + persona + tools)
        packaging\vendor\win32-AMD64\     (bowtie, RNAplfold)
        _internal\, licenses\
    y, si hay cargo y ui\tauri\tauri.conf.json, el .msi de Tauri.

    Binarios externos: si faltan, este script los COMPILA con MSYS2/MinGW64
    (packaging\vendor\build_vendor_windows.sh, fuentes con sha256 fijado). Si no
    puede, **falla**: un instalable sin bowtie/RNAplfold no corre nada. Para un
    bundle de desarrollo incompleto hay que pedirlo: -VendorOptional.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
.EXAMPLE
    .\scripts\build_windows.ps1 -NoTests -SkipMsi
#>
[CmdletBinding()]
param(
    [switch]$NoTests,
    [switch]$SkipMsi,
    [switch]$NoZip,
    [switch]$FetchOnly,
    [switch]$VendorOptional,
    [string]$Python = "python",
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Repo  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Bundle = Join-Path $Repo "dist\sifi-desk-windows"
$TauriDir = Join-Path $Repo "ui\tauri"          # D3: la raíz de Tauri es ui/tauri
Set-Location $Repo

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Die($msg) { Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

Step "0/6 entorno"
& $Python -c "import sys; assert sys.version_info >= (3,10), sys.version"
if ($LASTEXITCODE -ne 0) { Die "hace falta Python >= 3.10" }
& $Python -m PyInstaller --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Die "falta PyInstaller: $Python -m pip install -r packaging\requirements-build.txt"
}
& $Python -c "import sys,platform;print(f'{sys.platform}-{platform.machine()}')"

Step "1/6 binarios externos (bowtie + RNAplfold)"
$vendorDir = Join-Path $Repo "packaging\vendor\win32-AMD64"
$check = Join-Path $Repo "packaging\vendor\fetch_binaries.sh"
$bash = (Get-Command bash -ErrorAction SilentlyContinue)
if (-not $bash) {
    $cand = "C:\msys64\usr\bin\bash.exe"
    if (Test-Path $cand) { $bash = Get-Command $cand }
}
if (-not $bash) {
    if ($VendorOptional) {
        Write-Warning "sin bash (MSYS2/Git): sigo SIN binarios (-VendorOptional)"
    } else {
        Die "no hay bash. Instalá MSYS2 (https://www.msys2.org) o Git for Windows,
   o pasá -VendorOptional para un bundle de desarrollo SIN bowtie/RNAplfold."
    }
}

$vendorOk = $false
if ($bash) {
    & $bash.Path $check
    $vendorOk = ($LASTEXITCODE -eq 0)
}
if (-not $vendorOk) {
    Write-Host "-- faltan binarios: los compilo con MSYS2/MinGW64 (fuentes con sha256 fijado)"
    $buildVendor = Join-Path $Repo "packaging\vendor\build_vendor_windows.sh"
    if ($bash -and (Test-Path $buildVendor)) {
        & $bash.Path $buildVendor
        if ($LASTEXITCODE -eq 0) {
            & $bash.Path $check
            $vendorOk = ($LASTEXITCODE -eq 0)
        }
    }
}
if (-not $vendorOk) {
    if ($VendorOptional) {
        Write-Warning "binarios incompletos: el bundle sale SIN bowtie/RNAplfold (-VendorOptional)"
        Write-Warning "sin ellos el smoke del pipeline NO se puede correr"
    } else {
        Die @"faltan binarios en packaging\vendor\win32-AMD64 y no se pudieron compilar.
   El instalable sin bowtie/RNAplfold no puede diseñar nada, así que no se arma.
   Arreglá MSYS2/MinGW64 (pacman -S mingw-w64-x86_64-toolchain) o, para un bundle
   de desarrollo incompleto, pasá -VendorOptional.
"@
    }
}
if ($FetchOnly) { Write-Host "`n-FetchOnly: listo"; exit 0 }

if (-not $NoTests) {
    Step "2/6 tests"
    & $Python -m pytest -q tests
    if ($LASTEXITCODE -ne 0) { Die "tests en rojo" }
} else {
    Step "2/6 tests (omitidos)"
}

Step "3/6 sidecar one-dir (PyInstaller)"
& $Python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $Repo "dist") --workpath (Join-Path $Repo "build\pyinstaller") `
    "packaging\pyinstaller\sifid.spec"
if ($LASTEXITCODE -ne 0) { Die "PyInstaller falló" }

Step "4/6 ensamblado (agente + sidecar Tauri)"
if (-not (Test-Path $Bundle)) { Die "no se generó $Bundle" }

# Agente (M10): código + perfil de dsh. El runtime (Node + árbol de dsh) es
# prerrequisito y lo verifica `sifi doctor` (packaging\agent\README.md).
if ($bash) {
    & $bash.Path (Join-Path $Repo "packaging\agent\bundle_agent.sh") (Join-Path $Bundle "agent")
    if ($LASTEXITCODE -ne 0) { Die "no pude copiar el agente al bundle" }
} else {
    $src = Join-Path $Repo "agent"
    $dst = Join-Path $Bundle "agent"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    foreach ($item in @("package.json", "src", "prompts", "bin", "dsh")) {
        $from = Join-Path $src $item
        if (Test-Path $from) { Copy-Item -Recurse -Force $from (Join-Path $dst $item) }
    }
    Copy-Item -Force (Join-Path $Repo "packaging\agent\install.sh") (Join-Path $dst "install.sh")
}

# D6: Tauri espera `binaries\sifid-<target-triple>.exe`.
$sidecar = Join-Path $Bundle "sifid-$TargetTriple.exe"
Copy-Item -Force (Join-Path $Bundle "sifid.exe") $sidecar
if (Test-Path (Join-Path $TauriDir "src-tauri")) {
    $binDir = Join-Path $TauriDir "src-tauri\binaries"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    Copy-Item -Force (Join-Path $Bundle "sifid.exe") (Join-Path $binDir "sifid-$TargetTriple.exe")
    Write-Host "   sidecar Tauri: ui\tauri\src-tauri\binaries\sifid-$TargetTriple.exe"
}

Step "5/6 verificación"
& (Join-Path $Bundle "sifid.exe") --help | Out-Null
if ($LASTEXITCODE -ne 0) { Die "sifid.exe --help falló" }
& (Join-Path $Bundle "sifi.exe") version | Out-Null
if ($LASTEXITCODE -ne 0) { Die "sifi.exe version falló" }
& $sidecar --help | Out-Null
if ($LASTEXITCODE -ne 0) { Die "el sidecar $TargetTriple no arranca" }
# `doctor` informa también el agente (Node/dsh/perfil): no corta el build si el
# agente no tiene runtime en esta máquina, pero deja el diagnóstico en el log.
& (Join-Path $Bundle "sifi.exe") doctor
Get-ChildItem $Bundle | Select-Object -ExpandProperty Name | ForEach-Object { Write-Host "   $_" }
$sizeMb = [math]::Round((Get-ChildItem $Bundle -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "   tamaño: $sizeMb MB"

Step "5c/6 smoke (corrida real con tests\data)"
if (-not (Test-Path (Join-Path $vendorDir "bowtie-build.exe"))) {
    if ($VendorOptional) {
        Write-Warning "sin bowtie-build.exe: salteo el smoke (-VendorOptional)"
    } else {
        Die "sin bowtie-build.exe en el bundle: no puedo probar el pipeline, y un
   instalable que no pasó el smoke no se publica."
    }
} else {
    $smoke = Join-Path ([System.IO.Path]::GetTempPath()) ("sifi-smoke-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $smoke | Out-Null
    Push-Location $smoke
    try {
        & (Join-Path $vendorDir "bowtie-build.exe") -q (Join-Path $Repo "tests\data\toy.fa") (Join-Path $smoke "toyidx")
        if ($LASTEXITCODE -ne 0) { Die "bowtie-build del bundle falló (el instalable no podría indexar nada)" }
        & (Join-Path $Bundle "sifi.exe") design -q (Join-Path $Repo "tests\data\query.fa") `
            -d $smoke --db-name toyidx -o (Join-Path $smoke "out") --quiet
        if ($LASTEXITCODE -ne 0) { Die "sifi design falló sobre el índice de juguete" }
        & $Python -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8"))["records"][0]; assert r["error"] is None, r["error"]; assert r["summary"]["n_sirnas"] > 0; print("   CLI OK ·", r["query_name"], "·", r["summary"]["n_sirnas"], "siRNAs")' (Join-Path $smoke "out\results.json")
        if ($LASTEXITCODE -ne 0) { Die "el smoke no encontró siRNAs: el bundle no diseña" }
    } finally {
        Pop-Location
    }
    Remove-Item -Recurse -Force $smoke -ErrorAction SilentlyContinue
    Write-Host "-- smoke OK"
}

if ($NoZip) {
    Write-Host "omitido (-NoZip)"
} else {
    Step "5b/6 zip del bundle"
    $leeme = Join-Path $Bundle "LEEME.txt"
    $texto = @"
siFi-Desk (Windows) — bundle de escritorio
==========================================

Ejecutables:
  sifid.exe    servicio local (API HTTP en 127.0.0.1:8765) + cola de corridas
  sifi.exe     CLI headless (design, offtarget, panel, score, doctor, version)
  sifid-$TargetTriple.exe   mismo servicio con el nombre que usa el .msi (Tauri)

Agente (agent\):
  Perfil de dsh + las 7 tools del producto + la persona + sifi doctor lo verifica.
  Requiere Node 22+ y dsh (no van embebidos: pesan ~1 GB). Para dejarlo andando:
      bash agent/install.sh          (desde Git Bash / MSYS2)
  y después:
      set DSH_HOME=%USERPROFILE%\.sifi\agent\dsh
      dsh --profile sifi --dump-config

Primeros pasos:
  sifi.exe doctor
  sifid.exe --help

Descomprimir la carpeta completa (no mover los .exe fuera de _internal\).
Los binarios externos (bowtie, RNAplfold) están en packaging\vendor\win32-AMD64\.
Licencias en licenses\. Uso no comercial.
"@
    Set-Content -Path $leeme -Value $texto -Encoding UTF8
    $zip = Join-Path $Repo "dist\sifi-desk-windows.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $Bundle "*") -DestinationPath $zip `
        -CompressionLevel Optimal -Force
    Write-Host "   dist\sifi-desk-windows.zip"
}

Step "6/6 .msi (Tauri, opcional)"
$tauriConf = Join-Path $TauriDir "tauri.conf.json"
if ($SkipMsi) {
    Write-Host "omitido (-SkipMsi)"
} elseif (-not (Test-Path $tauriConf)) {
    Write-Warning "falta ui\tauri\tauri.conf.json: salteo el .msi (el bundle one-dir ya sirve)"
} elseif (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Warning "falta cargo/Rust: salteo el .msi"
} else {
    Push-Location $TauriDir
    try {
        if (Test-Path "package.json") { npm ci; if ($LASTEXITCODE -ne 0) { npm install } }
        npm run tauri build
        if ($LASTEXITCODE -ne 0) { Write-Warning "tauri build falló: el bundle one-dir sigue válido" }
    } finally {
        Pop-Location
    }
}

Write-Host "`nlisto: dist\sifi-desk-windows\" -ForegroundColor Green
