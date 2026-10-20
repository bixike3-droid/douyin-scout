# 给打包产物签名（拿到代码签名证书后使用）
#
# 用法：
#   .\scripts\sign_exe.ps1 -Pfx "C:\cert\源镜.pfx" -Password "证书密码"
#   .\scripts\sign_exe.ps1 -Pfx "C:\cert\源镜.pfx" -Password "证书密码" -Timestamp "http://timestamp.digicert.com"
#
# 说明：
# - EV 证书通常是 USB Key，不导出 .pfx；那种情况直接用厂商工具（如 SafeNet）签名即可
# - 只有签名过的 exe 才会显示“已验证的发布者”，否则 SmartScreen 一定提示未知发布者

param(
    [Parameter(Mandatory = $true)][string]$Pfx,
    [Parameter(Mandatory = $true)][string]$Password,
    [string]$Target = "dist\yuanjing\源镜\源镜.exe",
    [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    $kits = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'x64' } | Select-Object -Last 1
    if (-not $kits) { throw "找不到 signtool.exe，请安装 Windows SDK（签名工具）后重试" }
    $signtool = $kits.FullName
} else {
    $signtool = $signtool.Source
}

if (-not (Test-Path $Target)) { throw "找不到待签名文件：$Target，请先运行打包" }

Write-Host "签名：$Target"
& $signtool sign /fd SHA256 /f $Pfx /p $Password /tr $Timestamp /td SHA256 $Target
if ($LASTEXITCODE -ne 0) { throw "签名失败（exit=$LASTEXITCODE）" }

& $signtool verify /pa /v $Target
if ($LASTEXITCODE -ne 0) { throw "签名校验失败" }

$status = (Get-AuthenticodeSignature $Target)
Write-Host ("签名状态：{0}，签名者：{1}" -f $status.Status, $status.SignerCertificate.Subject)
