# 卸掉 skillpm 本身（Windows）。
#
#   Set-ExecutionPolicy -Scope Process Bypass -Force; & scripts\uninstall.ps1
#   ...\uninstall.ps1 -All      连 %USERPROFILE%\.skillpm 一起删（配置、状态、缓存、备份）
#
# 这个脚本不动已经装到各宿主目录里的 Skill。
# 要先清 Skill，卸载之前跑：skillpm uninstall --yes
param([switch]$All)
$ErrorActionPreference = "Continue"
$removed = $false

function Have($name) { $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }
$py = @("py", "python", "python3") | Where-Object { Have $_ } | Select-Object -First 1

# 1) pip 装的（含老版本留下的 UNKNOWN 空壳包）
if ($py) {
    foreach ($pkg in @("skillpm", "UNKNOWN")) {
        & $py -m pip show $pkg 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "卸载 pip 包 $pkg …"
            & $py -m pip uninstall -y $pkg 2>$null | Out-Null
            $removed = $true
        }
    }
}

# 2) 启动器
$marker = Join-Path $env:USERPROFILE ".skillpm\.installed-at"
if (Test-Path $marker) {
    $launcher = Get-Content $marker -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($launcher -and (Test-Path $launcher)) {
        Remove-Item $launcher -Force; Write-Host "删掉启动器 $launcher"; $removed = $true
    }
}
foreach ($d in @((Join-Path $env:LOCALAPPDATA "Programs\skillpm"),
                 (Join-Path $env:USERPROFILE ".local\bin"),
                 (Join-Path $env:USERPROFILE "bin"))) {
    $f = Join-Path $d "skillpm.cmd"
    if ((Test-Path $f) -and ((Get-Content $f -TotalCount 3) -match "skillpm\\scripts\\install")) {
        Remove-Item $f -Force; Write-Host "删掉启动器 $f"; $removed = $true
    }
}

# 3) 配置和状态
$home_dir = Join-Path $env:USERPROFILE ".skillpm"
if ($All) {
    if (Test-Path $home_dir) {
        $ans = Read-Host "要删掉 $home_dir 吗？里面有配置、安装记录、仓库缓存和备份。[y/N]"
        if ($ans -match '^(y|yes)$') {
            Remove-Item $home_dir -Recurse -Force; Write-Host "已删除 $home_dir"; $removed = $true
        } else { Write-Host "保留 $home_dir" }
    }
} elseif (Test-Path $home_dir) {
    Write-Host "保留了 $home_dir（配置和安装记录）；要一起删加 -All"
}

if ($removed) { Write-Host "卸载完成。" } else { Write-Host "没找到已安装的 skillpm。" }
Write-Host "提示：已经装到各宿主目录里的 Skill 不受影响；要清它们请先跑 skillpm uninstall --yes"
# 上面 pip show 在「不是 pip 装的」时返回 1，会被当成整个脚本的退出码——走到这里就是成功
exit 0
