$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location (Join-Path $repoRoot 'frontend')
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    npm run format:check
    if ($LASTEXITCODE -ne 0) { throw 'Frontend format check failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
finally { Pop-Location }

foreach ($projectName in @('backend', 'ai')) {
    $project = Join-Path $repoRoot $projectName
    $projectPython = Join-Path $project '.venv\Scripts\python.exe'
    if (-not (Test-Path $projectPython)) { throw "Install development dependencies in $project first." }

    Push-Location $project
    try {
        & $projectPython -m pytest
        if ($LASTEXITCODE -ne 0) { throw "$projectName tests failed." }
        & $projectPython -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw "$projectName lint failed." }
        & $projectPython -m ruff format --check .
        if ($LASTEXITCODE -ne 0) { throw "$projectName format check failed." }
    }
    finally { Pop-Location }
}

Write-Host 'All checks passed.'
