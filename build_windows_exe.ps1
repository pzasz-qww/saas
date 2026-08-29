param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$pythonPath = Join-Path $projectRoot "venv\Scripts\python.exe"
$specPath = Join-Path $projectRoot "PracaPDV.spec"
$buildRunId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID
$buildPath = Join-Path $projectRoot "build\$buildRunId"
$distPath = Join-Path $projectRoot "dist\$buildRunId"
$releasePath = Join-Path $projectRoot "release\PRACA_PDV_PORTABLE-$buildRunId"
$executablePath = Join-Path $distPath "PracaPDV.exe"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Ambiente virtual não encontrado em $pythonPath"
}

& $pythonPath -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw (
        "PyInstaller não está instalado. Execute: " +
        ".\venv\Scripts\python.exe -m pip install -r requirements-build.txt"
    )
}

if (-not $SkipTests) {
    Write-Host "Executando checks antes do build..." -ForegroundColor Cyan
    & $pythonPath manage.py check
    if ($LASTEXITCODE -ne 0) {
        throw "O check do Django falhou."
    }
    & $pythonPath manage.py test config.tests --verbosity 1
    if ($LASTEXITCODE -ne 0) {
        throw "Os testes do empacotamento falharam."
    }
}

Write-Host "Gerando PracaPDV.exe..." -ForegroundColor Cyan
& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $buildPath `
    --distpath $distPath `
    $specPath
if ($LASTEXITCODE -ne 0) {
    throw "O PyInstaller não conseguiu gerar o executável."
}
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "O executável esperado não foi criado em $executablePath"
}

New-Item -ItemType Directory -Path $releasePath -Force | Out-Null
Copy-Item `
    -LiteralPath $executablePath `
    -Destination $releasePath
Copy-Item `
    -LiteralPath (Join-Path $projectRoot "packaging\LEIA-ME-EXECUTAVEL.txt") `
    -Destination $releasePath

$sha256 = [System.Security.Cryptography.SHA256]::Create()
$executableStream = [System.IO.File]::OpenRead($executablePath)
try {
    $hashBytes = $sha256.ComputeHash($executableStream)
    $hashText = -join ($hashBytes | ForEach-Object { $_.ToString("X2") })
}
finally {
    $executableStream.Dispose()
    $sha256.Dispose()
}
$sizeMb = [Math]::Round(
    (Get-Item -LiteralPath $executablePath).Length / 1MB,
    2
)

Write-Host ""
Write-Host "Build concluído." -ForegroundColor Green
Write-Host "Executável: $releasePath\PracaPDV.exe"
Write-Host "Tamanho: $sizeMb MB"
Write-Host "SHA-256: $hashText"
