$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$env:PYTHONPATH = "src"

python -m unittest discover -s tests -v
python -m catalyst.demo

