param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $RepoRoot "build"
$NuitkaOutputDir = Join-Path $BuildRoot "nuitka"
$InstallerOutDir = Join-Path $BuildRoot "installer"
$VersionScript = Join-Path $RepoRoot "packaging\read_version.py"
$IconPng = Join-Path $RepoRoot "assets\icons\app\app_logo.png"
$IconIco = Join-Path $RepoRoot "assets\icons\app\app_logo.ico"

New-Item -ItemType Directory -Force -Path $BuildRoot, $NuitkaOutputDir, $InstallerOutDir | Out-Null

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found at $PythonExe"
}

$AppVersion = & $PythonExe $VersionScript version
$FileVersion = & $PythonExe $VersionScript fileversion
$Publisher = & $PythonExe $VersionScript publisher
$AppName = & $PythonExe $VersionScript appname

Write-Host "Installing build dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $RepoRoot "requirements.txt")
& $PythonExe -m pip install nuitka ordered-set zstandard pillow

if ((Test-Path $IconPng) -and -not (Test-Path $IconIco)) {
    Write-Host "Generating .ico from PNG..."
    & $PythonExe (Join-Path $RepoRoot "packaging\make_icon.py") $IconPng $IconIco
}

Write-Host "Building ONCards with Nuitka..."
$env:PYTHONPATH = "$RepoRoot\src"
$nuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--mingw64",
    "--enable-plugin=pyside6",
    "--include-package=studymate",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--output-dir=$NuitkaOutputDir",
    "--output-filename=ONCards.exe",
    "--include-data-dir=$RepoRoot\assets=assets",
    "--company-name=$Publisher",
    "--product-name=$AppName",
    "--file-version=$FileVersion",
    "--product-version=$FileVersion",
    (Join-Path $RepoRoot "main.py")
)
if (Test-Path $IconIco) {
    $nuitkaArgs += "--windows-icon-from-ico=$IconIco"
}
& $PythonExe @nuitkaArgs

$DistDir = Join-Path $NuitkaOutputDir "main.dist"
if (-not (Test-Path $DistDir)) {
    $DistDir = Join-Path $NuitkaOutputDir "ONCards.dist"
}
if (-not (Test-Path $DistDir)) {
    throw "Could not find Nuitka standalone output directory."
}

Write-Host "Locating Inno Setup..."
$IsccCandidates = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$IsccPath = $IsccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $IsccPath) {
    throw "Inno Setup compiler (ISCC.exe) was not found."
}

Write-Host "Building installer with Inno Setup..."
& $IsccPath `
    "/DAppVersion=$AppVersion" `
    "/DAppPublisher=$Publisher" `
    "/DAppName=$AppName" `
    "/DSourceRoot=$RepoRoot" `
    "/DBuildOutput=$DistDir" `
    "/DInstallerOutput=$InstallerOutDir" `
    (Join-Path $RepoRoot "packaging\ONCards.iss")

Write-Host "Build complete."
