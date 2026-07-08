# 自动推送 — git post-commit hook
# 提交后自动推送到远程仓库

$ErrorActionPreference = "Continue"

$branch = & git branch --show-current 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  无法获取当前分支，跳过自动推送。"
    exit 0
}

$branch = $branch.Trim()
Write-Host "🚀 自动推送至 origin/$branch ..."

$pushResult = & git push origin $branch 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  自动推送失败，请手动 git push。"
    Write-Host ($pushResult | Select-Object -Last 5)
} else {
    Write-Host "✅ 已推送至 origin/$branch"
}
exit 0
