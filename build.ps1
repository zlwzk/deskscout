<#
打包脚本：生成单文件 DeskScout.exe
用法：.\build.ps1
#>
param(
    [switch]$SkipCheck
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "找不到虚拟环境：$python。请先运行 C:\Python3xx\python.exe -m venv .venv 并安装 pillow、pyinstaller。"
}

if (-not $SkipCheck) {
    Write-Host "检查语法…"
    & $python -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('deskscout', quiet=1) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "语法检查未通过" }
    Write-Host "生成图标资源…"
    & $python "dev\make_assets.py"
}

if (-not (Test-Path -LiteralPath "assets\icon.ico")) {
    throw "缺少 assets\icon.ico"
}

Write-Host "开始打包（onefile / windowed）…"
& $pyinstaller --noconfirm --clean --onefile --windowed `
    --name DeskScout `
    --icon "assets\icon.ico" `
    --add-data "assets\app.png;assets" `
    --version-file "version_info.txt" `
    --exclude-module tkinter.test `
    --exclude-module unittest `
    --exclude-module pydoc `
    "DeskScout.py"

if ($LASTEXITCODE -ne 0) { throw "打包失败" }

$exe = Join-Path $root "dist\DeskScout.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "没有生成 $exe" }

$size = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 1)
Write-Host "打包完成：$exe ($size MB)"
