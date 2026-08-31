$ErrorActionPreference = "Continue"
$hookProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$credentialTool = Join-Path $PSScriptRoot "build-credential.py"
$gitRoot = & git -C $hookProjectRoot rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
  Write-Host "[pre-commit] Unable to determine the Git repository root."
  exit 1
}
$gitRoot = [IO.Path]::GetFullPath("$gitRoot".Trim())

$scopeJson = & python $credentialTool scopes --root $gitRoot --mode staged
if ($LASTEXITCODE -ne 0) {
  Write-Host "[pre-commit] Unable to assign staged code to DevFlow projects."
  exit 1
}
try {
  $scopes = @($scopeJson | ConvertFrom-Json)
} catch {
  Write-Host "[pre-commit] Invalid project scope data from build credential tool."
  exit 1
}

if ($scopes.Count -eq 0) {
  Write-Host "[pre-commit] No staged code requires a build check."
  exit 0
}

foreach ($scope in $scopes) {
  $projectRoot = if ([string]$scope -eq ".") {
    $gitRoot
  } else {
    Join-Path $gitRoot (([string]$scope) -replace '/', [IO.Path]::DirectorySeparatorChar)
  }

  & python $credentialTool verify-clean --root $projectRoot
  if ($LASTEXITCODE -eq 11) {
    Write-Host "[pre-commit] $scope has unstaged code changes. Stage or set them aside before building so the build matches the commit."
    exit 1
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[pre-commit] Unable to compare the worktree and index for $scope."
    exit 1
  }

  & python $credentialTool check --root $projectRoot --mode staged
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[pre-commit] Reusing a valid build credential for $scope."
    continue
  }
  if ($LASTEXITCODE -ne 10) {
    Write-Host "[pre-commit] Unable to inspect the build credential for $scope."
    exit 1
  }

  $buildFailed = $false
  $buildCommand = $null
  if (Test-Path "$projectRoot\xmake.lua") {
    $buildCommand = "xmake build"
    Push-Location $projectRoot
    try { & xmake build 2>&1 | Out-Host; $buildFailed = $LASTEXITCODE -ne 0 } finally { Pop-Location }
  } elseif (Test-Path "$projectRoot\CMakeLists.txt") {
    $buildCommand = "cmake --build build"
    & cmake --build "$projectRoot\build" 2>&1 | Out-Host
    $buildFailed = $LASTEXITCODE -ne 0
  } elseif (Test-Path "$projectRoot\package.json") {
    if (-not (Test-Path "$projectRoot\node_modules")) {
      Write-Host "[pre-commit] $scope has no node_modules; build cannot be verified."
      exit 1
    }
    $buildCommand = "npm run build"
    & npm --prefix $projectRoot run build 2>&1 | Out-Host
    $buildFailed = $LASTEXITCODE -ne 0
  } elseif (Test-Path "$projectRoot\Cargo.toml") {
    $buildCommand = "cargo build"
    & cargo build --manifest-path "$projectRoot\Cargo.toml" 2>&1 | Out-Host
    $buildFailed = $LASTEXITCODE -ne 0
  } elseif (Test-Path "$projectRoot\go.mod") {
    $buildCommand = "go build ./..."
    Push-Location $projectRoot
    try { & go build ./... 2>&1 | Out-Host; $buildFailed = $LASTEXITCODE -ne 0 } finally { Pop-Location }
  } else {
    $csproj = Get-ChildItem $projectRoot -Filter "*.csproj" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($csproj) {
      $buildCommand = "dotnet build"
      & dotnet build $csproj.FullName 2>&1 | Out-Host
      $buildFailed = $LASTEXITCODE -ne 0
    } elseif ((Test-Path "$projectRoot\pyproject.toml") -or
              (Test-Path "$projectRoot\setup.py") -or
              (Get-ChildItem $projectRoot -Filter "*.py" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
      $buildCommand = "python -m compileall"
      & python -m compileall $projectRoot -q 2>&1 | Out-Host
      $buildFailed = $LASTEXITCODE -ne 0
    } else {
      Write-Host "[pre-commit] No known build entry for $scope; record manual validation instead."
      exit 1
    }
  }

  if ($buildFailed) {
    Write-Host "[pre-commit] Build failed for $scope`: $buildCommand"
    exit 1
  }

  & python $credentialTool record --root $projectRoot --command $buildCommand --target project --mode staged
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[pre-commit] Build passed for $scope but credential recording failed."
    exit 1
  }
}

Write-Host "[pre-commit] Build checks passed for $($scopes.Count) DevFlow project(s)."
exit 0
