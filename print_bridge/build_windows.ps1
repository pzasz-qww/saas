$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repo
& "$repo\venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ConectorPracaPDV --paths $repo --distpath "$PSScriptRoot\dist" --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" "$PSScriptRoot\desktop.py"
if ($LASTEXITCODE -ne 0) { throw 'Falha no empacotamento do conector.' }
