param(
  [Parameter(Mandatory=$true)]
  [string]$Title
)

$branch = git branch --show-current

if ($branch -eq "main") {
  Write-Error "Refusing to commit/push directly on main. Create a codex/* branch first."
  exit 1
}

if (-not $branch.StartsWith("codex/")) {
  Write-Error "Refusing to finish from non-codex branch '$branch'. Use a codex/* branch."
  exit 1
}

$baseRef = "origin/main"
git rev-parse --verify --quiet $baseRef *> $null
if ($LASTEXITCODE -ne 0) {
  $baseRef = "main"
}

function Normalize-GitPath {
  param([string]$PathText)
  return ($PathText -replace '\\','/')
}

$changedFiles = @()
$changedFiles += git diff --name-only "$baseRef...HEAD"
$changedFiles += git diff --name-only
$changedFiles += git diff --name-only --cached
$changedFiles += git ls-files --others --exclude-standard
$changedFiles = @($changedFiles | Where-Object { $_ } | ForEach-Object { Normalize-GitPath $_ } | Sort-Object -Unique)

$sensitivePrefixes = @(
  "src/",
  "studio/",
  "tests/",
  "scripts/",
  ".rules/",
  ".github/workflows/"
)
$sensitiveFiles = @(
  "pyproject.toml",
  "AGENTS.md"
)
$contextFiles = @(
  "session-handoff.md",
  "progress.md",
  "docs/AI_CONTEXT.md",
  "docs/REPO_MAP.md"
)

$touchesSensitive = $false
foreach ($path in $changedFiles) {
  if ($sensitiveFiles -contains $path) {
    $touchesSensitive = $true
    break
  }
  foreach ($prefix in $sensitivePrefixes) {
    if ($path.StartsWith($prefix)) {
      $touchesSensitive = $true
      break
    }
  }
  if ($touchesSensitive) {
    break
  }
}

$touchesContext = $false
foreach ($path in $changedFiles) {
  if ($contextFiles -contains $path) {
    $touchesContext = $true
    break
  }
}

if ($touchesSensitive -and -not $touchesContext) {
  Write-Error "Branch changes protected project files but did not update session-handoff.md, progress.md, docs/AI_CONTEXT.md, or docs/REPO_MAP.md."
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
