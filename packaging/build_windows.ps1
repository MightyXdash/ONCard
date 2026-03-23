param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $RepoRoot "build"
$InstallerOutDir = Join-Path $BuildRoot "installer"
$VersionScript = Join-Path $RepoRoot "packaging\read_version.py"
$IconPng = Join-Path $RepoRoot "assets\icons\app\app_logo.png"
$IconIco = Join-Path $RepoRoot "assets\icons\app\app_logo.ico"

New-Item -ItemType Directory -Force -Path $BuildRoot, $InstallerOutDir | Out-Null

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found at $PythonExe"
}

$AppVersion = & $PythonExe $VersionScript version
$FileVersion = & $PythonExe $VersionScript fileversion
$Publisher = & $PythonExe $VersionScript publisher
$AppName = & $PythonExe $VersionScript appname
$Description = & $PythonExe $VersionScript description
$InternalName = & $PythonExe $VersionScript internalname
$OriginalFilename = & $PythonExe $VersionScript originalfilename
$CopyrightText = & $PythonExe $VersionScript copyright
$PyInstallerOutputDir = Join-Path $BuildRoot "pyinstaller-$AppVersion"
$PyInstallerDistDir = Join-Path $PyInstallerOutputDir "dist"
$PyInstallerWorkDir = Join-Path $PyInstallerOutputDir "build"
$PyInstallerSpecDir = Join-Path $PyInstallerOutputDir "spec"
$WrapperWorkDir = Join-Path $PyInstallerOutputDir "wrapper-build"
$WrapperSpecDir = Join-Path $PyInstallerOutputDir "wrapper-spec"
$VersionFile = Join-Path $PyInstallerOutputDir "pyinstaller_version_info.txt"

New-Item -ItemType Directory -Force -Path $PyInstallerOutputDir, $PyInstallerDistDir, $PyInstallerWorkDir, $PyInstallerSpecDir, $WrapperWorkDir, $WrapperSpecDir | Out-Null

Write-Host "Installing build dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $RepoRoot "requirements.txt")
& $PythonExe -m pip install pyinstaller pillow

if ((Test-Path $IconPng) -and -not (Test-Path $IconIco)) {
    Write-Host "Generating .ico from PNG..."
    & $PythonExe (Join-Path $RepoRoot "packaging\make_icon.py") $IconPng $IconIco
}

Write-Host "Building ONCard with PyInstaller..."
$env:PYTHONPATH = "$RepoRoot\src"
$versionParts = $FileVersion.Split(".")
$versionFileBody = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), $($versionParts[3])),
    prodvers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), $($versionParts[3])),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '$Publisher'),
          StringStruct('FileDescription', '$Description'),
          StringStruct('FileVersion', '$FileVersion'),
          StringStruct('InternalName', '$InternalName'),
          StringStruct('OriginalFilename', '$OriginalFilename'),
          StringStruct('ProductName', '$AppName'),
          StringStruct('ProductVersion', '$AppVersion'),
          StringStruct('LegalCopyright', '$CopyrightText')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
$versionFileBody | Set-Content -Path $VersionFile -Encoding UTF8

$addData = "$RepoRoot\assets;assets"
$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "ONCard",
    "--paths", "$RepoRoot\src",
    "--hidden-import", "studymate.app",
    "--collect-submodules", "studymate",
    "--distpath", $PyInstallerDistDir,
    "--workpath", $PyInstallerWorkDir,
    "--specpath", $PyInstallerSpecDir,
    "--version-file", $VersionFile,
    "--add-data", $addData,
    (Join-Path $RepoRoot "main.py")
)
if (Test-Path $IconIco) {
    $pyinstallerArgs += "--icon"
    $pyinstallerArgs += $IconIco
}
& $PythonExe @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$DistDir = Join-Path $PyInstallerDistDir "ONCard"
if (-not (Test-Path $DistDir)) {
    throw "Could not find PyInstaller output directory."
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
    (Join-Path $RepoRoot "packaging\ONCard.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed with exit code $LASTEXITCODE"
}

Write-Host "Wrapping installer for updater compatibility..."
$InnerInstallerPath = Join-Path $InstallerOutDir "ONCard-Installer-$AppVersion.exe"
if (-not (Test-Path $InnerInstallerPath)) {
    throw "Inner installer not found at $InnerInstallerPath"
}
$WrapperName = "ONCard-Setup-$AppVersion"
$wrapperAddData = "$InnerInstallerPath;."
$wrapperArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", $WrapperName,
    "--distpath", $InstallerOutDir,
    "--workpath", $WrapperWorkDir,
    "--specpath", $WrapperSpecDir,
    "--add-data", $wrapperAddData,
    (Join-Path $RepoRoot "packaging\update_wrapper.py")
)
if (Test-Path $IconIco) {
    $wrapperArgs += "--icon"
    $wrapperArgs += $IconIco
}
& $PythonExe @wrapperArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installer wrapper build failed with exit code $LASTEXITCODE"
}
$WrapperPath = Join-Path $InstallerOutDir "$WrapperName.exe"
if (-not (Test-Path $WrapperPath)) {
    throw "Wrapped installer not found at $WrapperPath"
}

Write-Host "Build complete."
