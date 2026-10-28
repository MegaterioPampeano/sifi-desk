#Requires -Version 5.1
<#
.SYNOPSIS
    Compila el instalable de siFi-Desk en Windows (M8): dist\sifi-desk-windows\.
.DESCRIPTION
    Equivalente a scripts/build_linux.sh. One-dir, un solo EXE + copia `sifi`
    (el dispatch es por argv[0], ver packaging/pyinstaller/sifid_entry.py).

    Resultado: dist\sifi-desk-windows\{sifid.exe, sifi.exe, _internal\, packaging\vendor\win32-AMD64\}
    y, si hay ui\tauri.conf.json y cargo, el .msi de Tauri.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
.EXAMPLE
    .\scripts\build_windows.ps1 -NoTests -SkipMsi
#>
[CmdletBinding()]
param(
    [switch]$NoTests,
    [switch]$SkipMsi,
    [switch]$FetchOnly,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Repo  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Bundle = Join-Path $Repo "dist\sifi-desk-windows"
Set-Location $Repo

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step "0/5 entorno"
& $Python -c "import sys; assert sys.version_info >= (3,10), sys.version"
if ($LASTEXITCODE -ne 0) { throw "hace falta Python >= 3.10" }
& $Python -m PyInstaller --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "falta PyInstaller: $Python -m pip install -r packaging\requirements-build.txt"
}
& $Python -c "import sys,platform;print(f'{sys.platform}-{platform.machine()}')"

Step "1/5 vendor"
$fetch = Join-Path $Repo "packaging\vendor\fetch_binaries.sh"
if (Test-Path $fetch) {
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        & bash $fetch --check
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "binarios incompletos: el bundle sale sin bowtie/RNAplfold"
            & bash $fetch
            $env:SIFI_VENDOR_OPTIONAL = "1"
        }
    } else {
        Write-Warning "no hay bash (Git for Windows): copiá los binarios a mano en packaging\vendor\win32-AMD64\"
        $env:SIFI_VENDOR_OPTIONAL = "1"
    }
}
if ($FetchOnly) { Write-Host "`n-FetchOnly: listo"; exit 0 }

if (-not $NoTests) {
    Step "2/5 tests"
    & $Python -m pytest -q tests
    if ($LASTEXITCODE -ne 0) { throw "tests en rojo" }
} else {
    Step "2/5 tests (omitidos)"
}

Step "3/5 sidecar one-dir (PyInstaller)"
& $Python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $Repo "dist") --workpath (Join-Path $Repo "build\pyinstaller") `
    "packaging\pyinstaller\sifid.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

Step "4/5 verificación"
if (-not (Test-Path $Bundle)) { throw "no se generó $Bundle" }
& (Join-Path $Bundle "sifid.exe") --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "sifid.exe --help falló" }
& (Join-Path $Bundle "sifi.exe") version
if ($LASTEXITCODE -ne 0) { throw "sifi.exe version falló" }
Get-ChildItem $Bundle | Select-Object -ExpandProperty Name | ForEach-Object { Write-Host "   $_" }

Step "5/5 .msi (Tauri, opcional)"
$tauriConf = Join-Path $Repo "ui\tauri.conf.json"
if ($SkipMsi) {
    Write-Host "omitido (-SkipMsi)"
} elseif (-not (Test-Path $tauriConf)) {
    Write-Warning "falta ui\tauri.conf.json: salteo el .msi (el bundle one-dir ya sirve)"
} elseif (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Warning "falta cargo/Rust: salteo el .msi"
} else {
    Push-Location (Join-Path $Repo "ui")
    try {
        npm ci
        npm run tauri build
        if ($LASTEXITCODE -ne 0) { Write-Warning "tauri build falló: el bundle one-dir sigue válido" }
    } finally {
        Pop-Location
    }
}

Write-Host "`nlisto: dist\sifi-desk-windows\" -ForegroundColor Green
