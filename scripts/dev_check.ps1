param(
  [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$env:PYTHONPATH = "$repoRoot\src;$env:PYTHONPATH"

function Invoke-DevStep {
  param(
    [string]$Name,
    [string[]]$Command
  )
  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  & $Command[0] @($Command | Select-Object -Skip 1)
  if ($LASTEXITCODE -ne 0) {
    throw "Dev check failed at: $Name"
  }
}

Invoke-DevStep "Python unit tests" @("python", "-m", "pytest", "-q", "tests")
Invoke-DevStep "Harness and rule check" @("python", "scripts\harness_check.py", "--json")
Invoke-DevStep "Benchmark skeleton" @("python", "scripts\run_benchmarks.py", "--cases", "benchmarks\cases", "--json")
Invoke-DevStep "Frontend smoke contracts" @("npm", "run", "test", "--prefix", "studio\frontend")

if (-not $SkipFrontendBuild) {
  Invoke-DevStep "Frontend production build" @("npm", "run", "build", "--prefix", "studio\frontend")
}

Invoke-DevStep "Private plans ignored" @("git", "check-ignore", "-q", "--", "_private/plans/COREWEAVER_AGENT_V1_1_0_TRUE_SWARM_REBUILD_PLAN.md")

Write-Host ""
Write-Host "DEV CHECK PASS" -ForegroundColor Green
