# 把本机这套系统打成可以整包拷走的 Docker 镜像包
#
# 用法（仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File deploy\docker-pack.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\docker-pack.ps1 -Tag 2.2 -NoCache
#
# 产物：
#   deploy\docker-dist\jijiantongzhi-images.tar   两个镜像，目标机器 docker load 直接导入
#   deploy\docker-dist\docker-compose.yml         目标机器用的 compose（只引用镜像）
#   deploy\docker-dist\env.example / install.sh / install.bat / 安装说明.md
#   deploy\jijiantongzhi-docker-<Tag>.zip         上面整个目录打成一个包

param(
    [string]$Tag = "2.1",
    [switch]$NoCache,
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dist = Join-Path $repo "deploy\docker-dist"
$zip = Join-Path $repo ("deploy\jijiantongzhi-docker-" + $Tag + ".zip")
$backendImage = "jijiantongzhi-backend:$Tag"
$frontendImage = "jijiantongzhi-frontend:$Tag"

Write-Host "==> 检查 Docker" -ForegroundColor Cyan
docker info --format "{{.ServerVersion}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker 没在运行，先把 Docker Desktop 打开" }

$cacheArg = @()
if ($NoCache) { $cacheArg = @("--no-cache") }

Push-Location $repo
try {
    Write-Host "==> 构建后端镜像 $backendImage" -ForegroundColor Cyan
    docker build @cacheArg -f docker/Dockerfile.backend -t $backendImage .
    if ($LASTEXITCODE -ne 0) { throw "后端镜像构建失败" }

    Write-Host "==> 构建前端镜像 $frontendImage（vite base=/jijiantongzhi/）" -ForegroundColor Cyan
    docker build @cacheArg -f docker/Dockerfile.frontend -t $frontendImage .
    if ($LASTEXITCODE -ne 0) { throw "前端镜像构建失败" }
} finally {
    Pop-Location
}

Write-Host "==> 准备分发目录 $dist" -ForegroundColor Cyan
if (Test-Path $dist) { [System.IO.Directory]::Delete($dist, $true) }
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$tar = Join-Path $dist "jijiantongzhi-images.tar"
Write-Host "==> 导出镜像到 $tar（几百 MB，稍等）" -ForegroundColor Cyan
docker save -o $tar $backendImage $frontendImage
if ($LASTEXITCODE -ne 0) { throw "docker save 失败" }

# compose 里的镜像标签跟着 -Tag 走
$compose = Get-Content (Join-Path $repo "deploy\docker-compose.yml") -Raw -Encoding UTF8
$compose = $compose -replace "jijiantongzhi-backend:\S+", $backendImage
$compose = $compose -replace "jijiantongzhi-frontend:\S+", $frontendImage
Set-Content -Path (Join-Path $dist "docker-compose.yml") -Value $compose -Encoding UTF8 -NoNewline

Copy-Item (Join-Path $repo "deploy\env.example") (Join-Path $dist "env.example") -Force
Copy-Item (Join-Path $repo "deploy\install.sh") (Join-Path $dist "install.sh") -Force
Copy-Item (Join-Path $repo "deploy\install.bat") (Join-Path $dist "install.bat") -Force
Copy-Item (Join-Path $repo "deploy\安装说明.md") (Join-Path $dist "安装说明.md") -Force

$size = [math]::Round((Get-Item -LiteralPath $tar).Length / 1MB, 1)
Write-Host ("    镜像包 " + $size + " MB") -ForegroundColor DarkGray

if (-not $NoZip) {
    if ([System.IO.File]::Exists($zip)) { [System.IO.File]::Delete($zip) }
    Write-Host "==> 压缩成 $zip" -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $zip -CompressionLevel Optimal
    $zsize = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
    Write-Host ("    压缩包 " + $zsize + " MB") -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "打包完成：" -ForegroundColor Green
Write-Host ("  分发目录 : " + $dist)
if (-not $NoZip) { Write-Host ("  压缩包   : " + $zip) }
Write-Host ""
Write-Host "目标机器上（Linux）：" -ForegroundColor Yellow
Write-Host "  unzip jijiantongzhi-docker-$Tag.zip -d /opt/jijiantongzhi-docker"
Write-Host "  cd /opt/jijiantongzhi-docker && sudo bash install.sh"
Write-Host "目标机器上（Windows + Docker Desktop）：双击 install.bat"
