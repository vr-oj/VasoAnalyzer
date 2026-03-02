$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot/../.."
$specPath = Join-Path $root "VasoAnalyzer.spec"
$installerScript = Join-Path $root "installer/windows/VasoAnalyzer.iss"
$distDir = Join-Path $root "dist/VasoAnalyzer"

Write-Host "==> Building VasoAnalyzer onedir bundle with PyInstaller"
pyinstaller --noconfirm $specPath

if (-not (Test-Path $distDir)) {
    throw "PyInstaller output not found at $distDir"
}

Write-Host "==> Copying document icons into dist"
Copy-Item (Join-Path $root "assets/icons/VasoDocument.ico") $distDir -Force
Copy-Item (Join-Path $root "assets/icons/VasoDocument.icns") $distDir -Force

Write-Host "==> Compiling Inno Setup installer"
$iscc = Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $iscc) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\iscc.exe",
        "C:\Program Files\Inno Setup 6\iscc.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    throw "iscc.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php"
}
& $iscc $installerScript

Write-Host "Installer build completed."
