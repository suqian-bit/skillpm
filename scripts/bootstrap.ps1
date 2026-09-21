# 一条命令搞定（Windows）：没装过就克隆+安装，装过就更新。
#
# 首次（在 PowerShell 里复制这一行）：
#   git clone https://github.com/suqian-bit/skillpm.git $env:USERPROFILE\.skillpm-src; `
#     Set-ExecutionPolicy -Scope Process Bypass -Force; `
#     & "$env:USERPROFILE\.skillpm-src\scripts\bootstrap.ps1"
#
# 注意是 & 调用，不是 powershell -File：-File 会另起一个进程，
# 那个进程改的 PATH 对你当前窗口没有任何影响，装完还得重开窗口。
#
# 以后更新：
#   Set-ExecutionPolicy -Scope Process Bypass -Force; `
#     & "$env:USERPROFILE\.skillpm-src\scripts\bootstrap.ps1"
param([string]$Mode = "auto", [string]$Prefix = "", [switch]$Yes)
$ErrorActionPreference = "Stop"
$Repo = if ($env:SKILLPM_REPO) { $env:SKILLPM_REPO } else { "https://github.com/suqian-bit/skillpm.git" }
$Src  = Join-Path $env:USERPROFILE ".skillpm-src"   # 写死，别让人找不到

if (Test-Path (Join-Path $Src ".git")) {
    Write-Host "已有源码：$Src"
} else {
    Write-Host "克隆到 $Src …"
    git clone $Repo $Src
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "克隆失败。最常见的原因是这台机器还没把 SSH 公钥配到 GitLab 上。"
        Write-Host "两条路："
        Write-Host "  1) 配 SSH key：ssh-keygen -t ed25519 然后把 ~\.ssh\id_ed25519.pub 贴到 GitLab 的 SSH Keys"
        Write-Host "  2) 走 HTTP（需要一个 GitLab 访问令牌）："
        Write-Host "     `$env:SKILLPM_REPO = '<本工具仓库的 git 地址>'"
        Write-Host "     再跑一次这条命令"
        exit 1
    }
}
& (Join-Path $Src "scripts\install.ps1") -Mode $Mode -Prefix $Prefix -Yes:$Yes
