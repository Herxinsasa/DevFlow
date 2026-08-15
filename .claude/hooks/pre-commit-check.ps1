$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$credentialTool = Join-Path $PSScriptRoot "build-credential.py"

& python $credentialTool verify-clean --root $rootDir
if ($LASTEXITCODE -eq 11) {
  Write-Host "[pre-commit] Unstaged code changes exist. Stage or set them aside before building so the build matches the commit."
  exit 1
}
if ($LASTEXITCODE -ne 0) {
  Write-Host "[pre-commit] Unable to compare the worktree and index."
  exit 1
}

& python $credentialTool check --root $rootDir --mode staged
if ($LASTEXITCODE -eq 0) {
  Write-Host "[pre-commit] Reusing valid build credential or no code build is required."
  exit 0
}
if ($LASTEXITCODE -ne 10) {
  Write-Host "[pre-commit] Unable to inspect the build credential."
  exit 1
}

$buildFailed = $false
$buildCommand = $null

if (Test-Path "$rootDir\xmake.lua") {
  $buildCommand = "xmake build"
  & xmake build 2>&1 | Out-Host
  $buildFailed = $LASTEXITCODE -ne 0
} elseif (Test-Path "$rootDir\CMakeLists.txt") {
  $buildCommand = "cmake --build build"
  & cmake --build "$rootDir\build" 2>&1 | Out-Host
  $buildFailed = $LASTEXITCODE -ne 0
} elseif (Test-Path "$rootDir\package.json") {
  if (-not (Test-Path "$rootDir\node_modules")) {
    Write-Host "[pre-commit] node_modules not found; build cannot be verified."
    exit 1
  }
  $buildCommand = "npm run build"
  & npm --prefix $rootDir run build 2>&1 | Out-Host
  $buildFailed = $LASTEXITCODE -ne 0
} elseif (Test-Path "$rootDir\Cargo.toml") {
  $buildCommand = "cargo build"
  & cargo build --manifest-path "$rootDir\Cargo.toml" 2>&1 | Out-Host
  $buildFailed = $LASTEXITCODE -ne 0
} elseif (Test-Path "$rootDir\go.mod") {
  $buildCommand = "go build ./..."
  Push-Location $rootDir
  try { & go build ./... 2>&1 | Out-Host; $buildFailed = $LASTEXITCODE -ne 0 } finally { Pop-Location }
} else {
  $csproj = Get-ChildItem $rootDir -Filter "*.csproj" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($csproj) {
    $buildCommand = "dotnet build"
    & dotnet build $csproj.FullName 2>&1 | Out-Host
    $buildFailed = $LASTEXITCODE -ne 0
  } elseif ((Test-Path "$rootDir\pyproject.toml") -or
            (Test-Path "$rootDir\setup.py") -or
            (Get-ChildItem $rootDir -Filter "*.py" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    $buildCommand = "python -m compileall"
    & python -m compileall $rootDir -q 2>&1 | Out-Host
    $buildFailed = $LASTEXITCODE -ne 0
  } else {
    Write-Host "[pre-commit] No known build entry; record manual validation instead."
    exit 1
  }
}

if ($buildFailed) {
  Write-Host "[pre-commit] Build failed: $buildCommand"
  exit 1
}

& python $credentialTool record --root $rootDir --command $buildCommand --target project --mode staged
if ($LASTEXITCODE -ne 0) {
  Write-Host "[pre-commit] Build passed but credential recording failed."
  exit 1
}
exit 0
