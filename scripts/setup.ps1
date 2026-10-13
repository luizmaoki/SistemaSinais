param([switch]$Build)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if ($Build) { docker compose up --build -d } else { docker compose up -d }
if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar o Compose.' }
Write-Host 'Capital Intelligence: http://localhost:3000 | API: http://localhost:8000/docs'
