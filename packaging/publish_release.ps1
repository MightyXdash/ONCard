param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    [string]$Repo = "MightyXdash/ONCard"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VersionScript = Join-Path $RepoRoot "packaging\read_version.py"
$Version = & $PythonExe $VersionScript version
$Tag = "v$Version"
$NotesPath = Join-Path $RepoRoot "release_notes\$Tag.md"
$InstallerPath = Join-Path $RepoRoot "build\installer\ONCard-Setup-$Version.exe"

if (-not (Test-Path $InstallerPath)) {
    throw "Installer not found at $InstallerPath"
}
if (-not (Test-Path $NotesPath)) {
    throw "Release notes not found at $NotesPath"
}

$credentialText = "protocol=https`nhost=github.com`n" | git credential fill
$token = $null
foreach ($line in $credentialText) {
    if ($line -like "password=*") {
        $token = $line.Substring(9)
    }
}
if (-not $token) {
    throw "Could not retrieve GitHub token from git credentials."
}

$headers = @{
    Accept = "application/vnd.github+json"
    Authorization = "Bearer $token"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "ONCard-Release-Publisher"
}

$releaseBody = [System.IO.File]::ReadAllText($NotesPath)
$releaseApi = "https://api.github.com/repos/$Repo/releases"
$existing = $null
try {
    $existing = Invoke-RestMethod -Uri "$releaseApi/tags/$Tag" -Headers $headers -Method Get
} catch {
    $existing = $null
}

if ($existing) {
    $payload = @{
        tag_name = $Tag
        name = "ONCard $Version"
        body = $releaseBody
        draft = $false
        prerelease = $false
    } | ConvertTo-Json
    $release = Invoke-RestMethod -Uri $existing.url -Headers $headers -Method Patch -Body $payload -ContentType "application/json"
} else {
    $payload = @{
        tag_name = $Tag
        target_commitish = "main"
        name = "ONCard $Version"
        body = $releaseBody
        draft = $false
        prerelease = $false
    } | ConvertTo-Json
    $release = Invoke-RestMethod -Uri $releaseApi -Headers $headers -Method Post -Body $payload -ContentType "application/json"
}

$assetName = Split-Path $InstallerPath -Leaf
$uploadUrl = ($release.upload_url -replace "\{.*$", "") + "?name=$([uri]::EscapeDataString($assetName))"
$releaseId = $release.id
$assets = Invoke-RestMethod -Uri "$releaseApi/$releaseId/assets" -Headers $headers -Method Get
foreach ($asset in $assets) {
    if ($asset.name -eq $assetName) {
        Invoke-RestMethod -Uri $asset.url -Headers $headers -Method Delete
    }
}

Invoke-RestMethod -Uri $uploadUrl -Headers @{
    Authorization = "Bearer $token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "Content-Type" = "application/octet-stream"
    "User-Agent" = "ONCard-Release-Publisher"
} -Method Post -InFile $InstallerPath

Write-Host "Published release $Tag with installer $assetName"
