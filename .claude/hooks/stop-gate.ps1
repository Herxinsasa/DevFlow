<#
.SYNOPSIS
  Claude Code Stop gate.
.DESCRIPTION
  Stop 前检查是否存在未审查的代码变更。
  读取 .claude/.review-status.json；只认可“通过”或“有条件通过”。
  stop_hook_active 为 true 时放行，避免 hook 自身造成循环。
#>

$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$claudeDir = Split-Path -Parent $PSScriptRoot
$reviewStatusFile = Join-Path $claudeDir ".review-status.json"

$stdinRaw = ""
$piped = @($input)
if ($piped.Count -gt 0) {
  $stdinRaw = ($piped | ForEach-Object { "$_" }) -join ""
}
elseif ([Console]::IsInputRedirected) {
  try {
    if ([Console]::In.Peek() -ne -1) {
      $stdinRaw = [Console]::In.ReadToEnd()
    }
  } catch {
    $stdinRaw = ""
  }
}

$stopHookActive = $false
if (-not [string]::IsNullOrWhiteSpace($stdinRaw)) {
  try {
    $hookIn = $stdinRaw | ConvertFrom-Json
    if ($null -ne $hookIn.stop_hook_active -and [bool]$hookIn.stop_hook_active) {
      $stopHookActive = $true
    }
  } catch {
    $stopHookActive = $false
  }
}

if ($stopHookActive) { exit 0 }

$status = & git -C "$rootDir" status --porcelain 2>&1
if ($LASTEXITCODE -ne 0) { exit 0 }
if (-not $status) { exit 0 }

$changedCodeFiles = @()
foreach ($lineRaw in ($status -split "`n")) {
  $line = $lineRaw.Trim()
  if ($line.Length -le 2) { continue }
  $file = $line.Substring(2).Trim()
  if ($file -match '^\.claude[/\\]') { continue }
  if ($file -match '\.(ps1|py|js|ts|jsx|tsx|rs|go|java|cs|cpp|h|cxx|hpp|swift|kt|proto|lua|qml|ui)$') {
    $changedCodeFiles += $file
  }
}

if ($changedCodeFiles.Count -eq 0) { exit 0 }

$reviewed = $false
$blockReason = ""

if (Test-Path $reviewStatusFile) {
  try {
    $reviewData = Get-Content $reviewStatusFile -Raw | ConvertFrom-Json
    $lastReviewTime = [DateTime]::Parse($reviewData.last_review)
    $elapsed = (Get-Date) - $lastReviewTime
    $conclusion = [string]$reviewData.conclusion
    $validConclusion = $conclusion -eq "通过" -or $conclusion -eq "有条件通过" -or $conclusion -eq "PASS"

    if (-not $validConclusion) {
      $blockReason = "最近一次 code-review 结论不是通过或有条件通过。"
    } elseif ($elapsed.TotalMinutes -ge 30) {
      $blockReason = "最近一次 code-review 已超过 30 分钟。"
    } else {
      $reviewedFiles = @($reviewData.reviewed_files)
      $unreviewedFiles = $changedCodeFiles | Where-Object { $_ -notin $reviewedFiles }

      $reviewScope = [string]$reviewData.review_scope
      if ($reviewScope -eq "partial" -and $unreviewedFiles.Count -gt 0) {
        $blockReason = "最近一次 code-review 是部分审查，仍有文件未覆盖。"
      } elseif ($unreviewedFiles.Count -gt 0) {
        $blockReason = "存在未被最近一次 code-review 覆盖的代码文件。"
      } else {
        $reviewed = $true
      }
    }
  } catch {
    $blockReason = "无法解析 .claude/.review-status.json。"
    $reviewed = $false
  }
} else {
  $blockReason = "未找到 .claude/.review-status.json。"
}

if ($reviewed) { exit 0 }

$preview = ($changedCodeFiles | Select-Object -First 10) -join ", "
$suffix = ""
if ($changedCodeFiles.Count -gt 10) {
  $suffix = " （另有 $($changedCodeFiles.Count - 10) 个文件）"
}

if ([string]::IsNullOrWhiteSpace($blockReason)) {
  $blockReason = "存在未审查的代码变更。"
}

$reason = "$blockReason 请先完成 code-review。文件示例：$preview$suffix"
$payload = @{ decision = "block"; reason = $reason } | ConvertTo-Json -Compress -Depth 5
[Console]::Out.WriteLine($payload)
exit 0
