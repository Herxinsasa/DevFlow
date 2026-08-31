<#
.SYNOPSIS
  Verify that staged code is covered by the latest code review.
.DESCRIPTION
  A repository-level hook routes every staged code file to its nearest DevFlow
  project. -Snapshot runs in the DevFlow project that owns this script and
  prints hashes for that project's current changed code.
#>

param(
  [switch]$Snapshot,
  [string[]]$Files
)

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$codePattern = '\.(ps1|py|js|mjs|cjs|ts|jsx|tsx|vue|rs|go|java|cs|cpp|c|h|cxx|hpp|swift|kt|kts|proto|lua|qml|ui)$'
$markerPath = ".claude/devflow-version.json"

function Normalize-Path([string]$path) {
  $normalized = $path.Trim() -replace '\\', '/'
  while ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
  return $normalized
}

function Get-GitRoot {
  $value = & git -C "$projectRoot" rev-parse --show-toplevel 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $value) { throw "Cannot determine the Git repository root." }
  return [IO.Path]::GetFullPath("$value".Trim())
}

$gitRoot = Get-GitRoot

function Get-ProjectPrefix([string]$root) {
  $normalizedGit = (Normalize-Path ([IO.Path]::GetFullPath($gitRoot))).TrimEnd('/')
  $normalizedRoot = (Normalize-Path ([IO.Path]::GetFullPath($root))).TrimEnd('/')
  if ($normalizedRoot.Equals($normalizedGit, [StringComparison]::OrdinalIgnoreCase)) { return "" }
  if (-not $normalizedRoot.StartsWith("$normalizedGit/", [StringComparison]::OrdinalIgnoreCase)) {
    throw "DevFlow project is outside the Git repository: $root"
  }
  return $normalizedRoot.Substring($normalizedGit.Length + 1)
}

$currentProjectPrefix = Get-ProjectPrefix $projectRoot

function Get-KnownProjectPrefixes {
  $markers = @()
  $indexPaths = @(& git -C "$gitRoot" ls-files --cached 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "Cannot inspect tracked DevFlow project markers." }
  foreach ($path in $indexPaths) {
    $normalized = Normalize-Path "$path"
    if ($normalized -eq $markerPath) {
      $markers += ""
    } elseif ($normalized.EndsWith("/$markerPath", [StringComparison]::OrdinalIgnoreCase)) {
      $markers += $normalized.Substring(0, $normalized.Length - $markerPath.Length - 1)
    }
  }
  return @($markers | Sort-Object -Unique)
}

$knownProjectPrefixes = @(Get-KnownProjectPrefixes)

function Test-ProjectMarker([string]$prefix) {
  if ($knownProjectPrefixes -contains $prefix) { return $true }
  $marker = if ($prefix) {
    Join-Path $gitRoot (($prefix + "/" + $markerPath) -replace '/', [IO.Path]::DirectorySeparatorChar)
  } else {
    Join-Path $gitRoot ($markerPath -replace '/', [IO.Path]::DirectorySeparatorChar)
  }
  return Test-Path -LiteralPath $marker -PathType Leaf
}

function Get-OwnerPrefix([string]$path) {
  $normalized = Normalize-Path $path
  $parent = Split-Path -Parent ($normalized -replace '/', [IO.Path]::DirectorySeparatorChar)
  $candidate = Normalize-Path $parent
  if ($candidate -eq ".") { $candidate = "" }
  while ($true) {
    if (Test-ProjectMarker $candidate) { return $candidate }
    if (-not $candidate) { break }
    $next = Normalize-Path (Split-Path -Parent ($candidate -replace '/', [IO.Path]::DirectorySeparatorChar))
    if ($next -eq "." -or $next -eq $candidate) { $candidate = "" } else { $candidate = $next }
  }
  return $null
}

function Test-CodePath([string]$path) {
  $normalized = Normalize-Path $path
  return $normalized -match $codePattern -and $normalized -notmatch '(^|/)\.claude/'
}

function Get-WorkingCodeFiles {
  $tracked = @(& git -C "$gitRoot" diff HEAD --name-only --diff-filter=ACMRDTUXB 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "Cannot read working tree diff." }
  $untracked = @(& git -C "$gitRoot" ls-files --others --exclude-standard 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "Cannot read untracked files." }
  return @($tracked + $untracked |
    ForEach-Object { Normalize-Path "$_" } |
    Where-Object { (Test-CodePath $_) -and (Get-OwnerPrefix $_) -eq $currentProjectPrefix } |
    Sort-Object -Unique)
}

function Get-StagedCodeFiles {
  $paths = @(& git -C "$gitRoot" diff --cached --name-only --diff-filter=ACMRDTUXB 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "Cannot read staged diff." }
  return @($paths |
    ForEach-Object { Normalize-Path "$_" } |
    Where-Object { Test-CodePath $_ } |
    Sort-Object -Unique)
}

function Resolve-InputPath([string]$path) {
  $normalized = Normalize-Path $path
  if ([IO.Path]::IsPathRooted($path)) {
    $absolute = Normalize-Path ([IO.Path]::GetFullPath($path))
    $git = (Normalize-Path $gitRoot).TrimEnd('/')
    if (-not $absolute.StartsWith("$git/", [StringComparison]::OrdinalIgnoreCase)) {
      throw "Review file is outside the Git repository: $path"
    }
    return $absolute.Substring($git.Length + 1)
  }
  if ($currentProjectPrefix -and -not ($normalized -eq $currentProjectPrefix -or $normalized.StartsWith("$currentProjectPrefix/"))) {
    return "$currentProjectPrefix/$normalized"
  }
  return $normalized
}

function Get-WorkingBlobHash([string]$path) {
  $relativePath = $path -replace '/', [IO.Path]::DirectorySeparatorChar
  $absolutePath = Join-Path $gitRoot $relativePath
  if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) { return "DELETED" }
  $hash = & git -C "$gitRoot" hash-object -- "$path" 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $hash) { throw "Cannot hash working file: $path" }
  return "$hash".Trim()
}

function Get-StagedBlobHash([string]$path) {
  & git -C "$gitRoot" cat-file -e ":$path" 2>$null
  if ($LASTEXITCODE -ne 0) { return "DELETED" }
  $hash = & git -C "$gitRoot" rev-parse ":$path" 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $hash) { throw "Cannot hash staged file: $path" }
  return "$hash".Trim()
}

if ($Snapshot) {
  if ($Files -and $Files.Count -gt 0) {
    $files = @($Files |
      ForEach-Object { Resolve-InputPath "$_" } |
      Where-Object { (Test-CodePath $_) -and (Get-OwnerPrefix $_) -eq $currentProjectPrefix } |
      Sort-Object -Unique)
  } else {
    $files = @(Get-WorkingCodeFiles)
  }
  $hashes = [ordered]@{}
  foreach ($file in $files) { $hashes[$file] = Get-WorkingBlobHash $file }
  $fingerprintInput = @($hashes.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n"
  $fingerprintBytes = [Text.Encoding]::UTF8.GetBytes($fingerprintInput)
  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    $fingerprint = ([BitConverter]::ToString($sha256.ComputeHash($fingerprintBytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
  [ordered]@{
    project_root = if ($currentProjectPrefix) { $currentProjectPrefix } else { "." }
    reviewed_files = $files
    reviewed_file_hashes = $hashes
    diff_fingerprint = $fingerprint
  } | ConvertTo-Json -Depth 6
  exit 0
}

$stagedFiles = @(Get-StagedCodeFiles)
if ($stagedFiles.Count -eq 0) {
  Write-Host "[pre-commit] No staged code files; review check skipped."
  exit 0
}

$groups = [ordered]@{}
$unassigned = @()
foreach ($file in $stagedFiles) {
  $owner = Get-OwnerPrefix $file
  if ($null -eq $owner) {
    $unassigned += $file
  } else {
    $key = if ($owner) { $owner } else { "." }
    if (-not $groups.Contains($key)) { $groups[$key] = @() }
    $groups[$key] += $file
  }
}

if ($unassigned.Count -gt 0) {
  Write-Host "[pre-commit] Staged code has no owning DevFlow project:"
  $unassigned | ForEach-Object { Write-Host "  - $_" }
  exit 1
}

$allFailures = @()
foreach ($key in $groups.Keys) {
  $prefix = if ($key -eq ".") { "" } else { $key }
  $scopeRoot = if ($prefix) { Join-Path $gitRoot ($prefix -replace '/', [IO.Path]::DirectorySeparatorChar) } else { $gitRoot }
  $reviewStatusFile = Join-Path $scopeRoot ".claude/.review-status.json"
  $scopeFailures = @()
  if (-not (Test-Path -LiteralPath $reviewStatusFile)) {
    $allFailures += "$key`: missing .claude/.review-status.json"
    continue
  }
  try {
    $reviewData = Get-Content -LiteralPath $reviewStatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    $allFailures += "$key`: invalid .claude/.review-status.json"
    continue
  }

  $validConclusion = (@("通过", "有条件通过", "PASS") -contains [string]$reviewData.conclusion) -or
    (@("passed", "conditional_pass") -contains [string]$reviewData.status) -or
    (@("passed", "conditional") -contains [string]$reviewData.conclusion)
  if (-not $validConclusion -or (@("failed", "不通过") -contains [string]$reviewData.conclusion)) {
    $scopeFailures += "latest code-review did not pass"
  }
  $reviewScope = if ($reviewData.scope -ne $null) { [string]$reviewData.scope } else { [string]$reviewData.review_scope }
  if ($reviewScope -ne "full") { $scopeFailures += "latest review is incomplete" }
  if ($reviewData.uncovered_scope -and @($reviewData.uncovered_scope).Count -gt 0) {
    $scopeFailures += "latest review has uncovered delivery scope"
  }
  $isConditional = (@("有条件通过", "conditional") -contains [string]$reviewData.conclusion) -or
    ([string]$reviewData.status -eq "conditional_pass")
  if ($isConditional -and (-not $reviewData.accepted_risks -or @($reviewData.accepted_risks).Count -eq 0)) {
    $scopeFailures += "conditional review has no accepted risk record"
  }
  $reviewer = if ($reviewData.reviewer) { [string]$reviewData.reviewer } else { [string]$reviewData.review_agent_name }
  if ($reviewer -ne "code-reviewer") { $scopeFailures += "independent code-reviewer marker is missing" }
  $credentialRoot = if ($reviewData.project_root) { Normalize-Path ([string]$reviewData.project_root) } else { $null }
  if ($credentialRoot -and $credentialRoot -ne $key) { $scopeFailures += "credential project_root does not match this project" }

  $reviewedHashes = $reviewData.reviewed_file_hashes
  if ($null -eq $reviewedHashes) {
    $scopeFailures += "review status has no file hashes"
  } else {
    foreach ($file in @($groups[$key])) {
      $property = $reviewedHashes.PSObject.Properties[$file]
      if ($null -eq $property) {
        $scopeFailures += "$file (not reviewed)"
      } elseif ([string]$property.Value -ne (Get-StagedBlobHash $file)) {
        $scopeFailures += "$file (changed after review)"
      }
    }
  }
  foreach ($failure in $scopeFailures) { $allFailures += "$key`: $failure" }
}

if ($allFailures.Count -gt 0) {
  Write-Host "[pre-commit] Code review check failed:"
  $allFailures | ForEach-Object { Write-Host "  - $_" }
  Write-Host "[pre-commit] Run code-review for each affected DevFlow project before committing."
  exit 1
}

Write-Host "[pre-commit] Review credentials cover staged code in $($groups.Count) DevFlow project(s)."
exit 0
