param(
  [Parameter(Mandatory=$true)]
  [string]$Title
)

$branch = git branch --show-current

if ($branch -eq "main") {
  Write-Error "Refusing to commit/push directly on main. Create a codex/* branch first."
  exit 1
}

python -m pytest -q tests
if ($LASTEXITCODE -ne 0) {
  Write-Error "pytest failed. Fix tests before creating PR."
  exit 1
}

python scripts\harness_check.py --json
if ($LASTEXITCODE -ne 0) {
  Write-Error "harness_check failed. Fix harness before creating PR."
  exit 1
}

git add -A

$hasChanges = git status --porcelain
if (-not $hasChanges) {
  Write-Host "No changes to commit."
} else {
  git commit -m $Title
}

git push -u origin $branch

$body = @"
## Goal
$Title

## Branch
$branch

## Checks run
- python -m pytest -q tests
- python scripts/harness_check.py --json

## Reviewer notes
See session-handoff.md and progress.md for Codex handoff details.
"@

$bodyPath = ".git\PR_BODY.md"
$body | Set-Content $bodyPath -Encoding utf8

gh pr create --base main --head $branch --title $Title --body-file $bodyPath
