# 在 Windows 上打一个可以整包拷到服务器部署的压缩包
#
# 用法（仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
#
# 产物：deploy\jijiantongzhi-deploy.zip
# 里面已经包含构建好的 frontend\dist，服务器上不需要装 Node。

param(
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutFile) { $OutFile = Join-Path $repo "deploy\jijiantongzhi-deploy.zip" }

Write-Host "==> 构建前端" -ForegroundColor Cyan
Push-Location (Join-Path $repo "frontend")
try {
    if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
    npm run build
} finally {
    Pop-Location
}
if (-not (Test-Path (Join-Path $repo "frontend\dist\index.html"))) {
    throw "前端构建失败，没有产出 frontend\dist\index.html"
}

$staging = Join-Path $env:TEMP ("jijiantongzhi-pack-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$target = Join-Path $staging "jijiantongzhi"
New-Item -ItemType Directory -Force -Path $target | Out-Null

Write-Host "==> 复制文件（跳过 node_modules / .venv / 运行时数据）" -ForegroundColor Cyan
$skip = @("node_modules", ".venv", "venv", "__pycache__", ".git", "work", "data")
$excludeDirs = @()

function Copy-Tree($from, $to) {
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Get-ChildItem -LiteralPath $from -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            if ($script:skip -contains $_.Name) { return }
            # backend\data 里有系统库和密钥，绝不打包
            if ($_.FullName -match "\\backend\\data$") { return }
            Copy-Tree $_.FullName (Join-Path $to $_.Name)
        } else {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $to $_.Name) -Force
        }
    }
}

Copy-Tree $repo $target

if (Test-Path $OutFile) { Remove-Item -LiteralPath $OutFile -Force }
Write-Host "==> 压缩" -ForegroundColor Cyan
Compress-Archive -Path $target -DestinationPath $OutFile -CompressionLevel Optimal
Remove-Item -Recurse -Force -LiteralPath $staging

$size = [math]::Round((Get-Item -LiteralPath $OutFile).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$OutFile （$size MB）" -ForegroundColor Green
Write-Host ""
Write-Host "拷到服务器后：" -ForegroundColor Yellow
Write-Host "  unzip jijiantongzhi-deploy.zip -d /opt"
Write-Host "  cd /opt/jijiantongzhi && sudo bash deploy/deploy.sh"
