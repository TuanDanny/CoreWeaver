param(
  [Parameter(Mandatory=$true)]
  [string]$Name
)

$slug = $Name.ToLower() `
  -replace '[^a-z0-9]+','-' `
  -replace '^-','' `
  -replace '-$',''

$branch = "codex/$slug"

git switch main
git pull origin main
git switch -c $branch

Write-Host ""
Write-Host "Created branch: $branch"
Write-Host ""
Write-Host "Prompt for Codex:"
Write-Host "Read AGENTS.md, ARCHITECTURE.md, docs/HARNESS_ENGINEERING.md, progress.md, and session-handoff.md."
Write-Host "Current branch is $branch."
Write-Host "Goal: $Name"
Write-Host "Follow the Mandatory Git Workflow in AGENTS.md."
