<#
.SYNOPSIS
  Git pre-commit build check.
.DESCRIPTION
  git commit 前自动运行编译检查。编译失败时阻止提交。
  编译失败属于可复现缺陷，应回到 bug-fixer：收集日志、分析根因、最小修复、重新验证。

  启用方式：
  - 方案 A：git config core.hooksPath .claude/hooks，并提供 pre-commit 包装脚本
  - 方案 B：手动在 .git/hooks/pre-commit 中调用本脚本
#>

$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$hasXmake = Test-Path "$rootDir\xmake.lua"
$hasCmake = Test-Path "$rootDir\CMakeLists.txt"
$hasPackageJson = Test-Path "$rootDir\package.json"
$hasCargoToml = Test-Path "$rootDir\Cargo.toml"
$hasGoMod = Test-Path "$rootDir\go.mod"
$hasCsproj = Get-ChildItem "$rootDir" -Filter "*.csproj" -Recurse -ErrorAction SilentlyContinue
$hasPyProject = (Test-Path "$rootDir\pyproject.toml") -or (Test-Path "$rootDir\setup.py")

$buildFailed = $false
$buildCommand = ""

if ($hasXmake) {
  $buildCommand = "xmake build"
  Write-Host "[pre-commit] xmake 项目，运行编译检查..."
  & xmake build 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} elseif ($hasCmake) {
  $buildCommand = "cmake --build build"
  Write-Host "[pre-commit] CMake 项目，运行编译检查..."
  & cmake --build build 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} elseif ($hasPackageJson) {
  $buildCommand = "npm run build"
  Write-Host "[pre-commit] Node.js 项目，运行编译检查..."
  if (Test-Path "$rootDir\node_modules") {
    & npm --prefix "$rootDir" run build 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
  } else {
    Write-Host "[pre-commit] 未找到 node_modules，跳过 npm build。"
  }
} elseif ($hasCargoToml) {
  $buildCommand = "cargo build"
  Write-Host "[pre-commit] Rust 项目，运行编译检查..."
  & cargo build --manifest-path "$rootDir\Cargo.toml" 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} elseif ($hasGoMod) {
  $buildCommand = "go build ./..."
  Write-Host "[pre-commit] Go 项目，运行编译检查..."
  & go build ./... 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} elseif ($hasCsproj) {
  $buildCommand = "dotnet build"
  Write-Host "[pre-commit] .NET 项目，运行编译检查..."
  & dotnet build "$rootDir" 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} elseif ($hasPyProject) {
  $buildCommand = "python -m compileall"
  Write-Host "[pre-commit] Python 项目，运行语法检查..."
  & python -m compileall "$rootDir" -q 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { $buildFailed = $true }
} else {
  Write-Host "[pre-commit] 未检测到已知项目类型，跳过编译检查。"
}

if ($buildFailed) {
  Write-Host "[pre-commit] 编译检查未通过，阻止提交。"
  Write-Host "[pre-commit] 失败命令：$buildCommand"
  Write-Host "[pre-commit] 请进入 bug-fixer：收集错误日志，建立复现，分析根因，最小修复后重新提交。"
  exit 1
}

exit 0
