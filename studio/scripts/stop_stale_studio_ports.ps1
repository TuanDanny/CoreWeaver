param(
  [Parameter(Mandatory=$true)]
  [string]$Root,
  [string]$PortsCsv = "8000,5173"
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$frontendRoot = (Join-Path $resolvedRoot "studio\frontend")
$Ports = @($PortsCsv -split "," | ForEach-Object { [int]($_.Trim()) })
$sawFailure = $false

foreach ($port in $Ports) {
  $listeners = @(Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" })
  foreach ($listener in $listeners) {
    $pidValue = [int]$listener.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
    $commandLine = [string]($process.CommandLine)
    Write-Host "Port $port is in use by PID $pidValue"
    Write-Host $commandLine

    $isBackend = $port -eq 8000 -and $commandLine -like "*studio.backend.server:app*" -and $commandLine -like "*uvicorn*"
    $isFrontend = ($commandLine -like "*vite*" -and $commandLine -like "*$frontendRoot*") -or ($commandLine -like "*studio\frontend*" -and $commandLine -like "*vite*")
    $isStudioOwned = $isBackend -or ($commandLine -like "*$resolvedRoot*" -and $isFrontend)

    if ($isStudioOwned) {
      Write-Host "Killing stale Studio process $pidValue on port $port"
      Stop-Process -Id $pidValue -Force
    } else {
      Write-Host "Refusing to kill unknown process on port $port."
      Write-Host "Close it manually or change ports. PID: $pidValue"
      $sawFailure = $true
    }
  }
}

if ($sawFailure) {
  exit 1
}
exit 0
