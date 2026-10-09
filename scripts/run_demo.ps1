$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install uv and Python 3.11 before running the demo.' }
}
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath 'fixtures\manifest.json')) {
    & .venv\Scripts\python.exe fixtures\generate.py
    if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed.' }
}
Push-Location -LiteralPath frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
New-Item -ItemType Directory -Path storage -Force | Out-Null
$listener = Get-NetTCPConnection -State Listen -LocalPort 8100 -ErrorAction SilentlyContinue
if ($listener) {
    $health = Invoke-RestMethod 'http://127.0.0.1:8100/api/health'
    if ($health.status -ne 'ok' -or $health.service -ne 'document-intelligence-rag') { throw 'Port 8100 is already occupied by another service.' }
} else {
    $server = Start-Process -FilePath "$projectRoot\.venv\Scripts\python.exe" -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8100') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\storage\server.log" -RedirectStandardError "$projectRoot\storage\server-error.log" -PassThru
    $server.Id | Set-Content storage\server.pid
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Invoke-RestMethod 'http://127.0.0.1:8100/api/health' | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'The server did not become ready. Inspect storage/server-error.log.' }
}
Start-Process 'http://127.0.0.1:8100'
Write-Host 'Document Intelligence: http://127.0.0.1:8100'
Write-Host 'Use Load demo documents in the library. Server PID/logs are in ignored storage/.'
