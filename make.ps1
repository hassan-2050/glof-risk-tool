<#
  Windows shim for the Makefile. GNU make is not installed by default on
  Windows; this forwards the same targets to the same Python commands so a
  Windows developer and the Linux container run identical code paths.
  Usage:  ./make.ps1 reproduce
#>
param([Parameter(Position = 0)][string]$Target = "help")

$env:PYTHONHASHSEED = "0"
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

switch ($Target) {
    "setup"              { & $py -m pip install -r requirements.txt }
    "reproduce"          { & $py -m src.cli reproduce }
    "watcher-eval"       { & $py -m src.cli stage 7 }
    "reporter-eval"      { & $py -m src.cli stage 14 }
    "verify-determinism" { & $py -m src.cli verify-determinism }
    "list-stages"        { & $py -m src.cli list-stages }
    "test"               { & $py -m pytest -q tests }
    "fetch-data"         { & $py -m src.data.fetch }
    "clean"              { Remove-Item -Recurse -Force outputs, .determinism_check -ErrorAction SilentlyContinue; New-Item -ItemType Directory outputs | Out-Null }
    "docker-build"       { docker build -t glof-risk-tool:latest . }
    "docker-reproduce"   { docker run --rm --network none glof-risk-tool:latest make reproduce }
    default {
        Write-Host "targets: setup reproduce watcher-eval reporter-eval verify-determinism list-stages test fetch-data clean docker-build docker-reproduce"
    }
}
exit $LASTEXITCODE
