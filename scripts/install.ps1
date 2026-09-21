# 装 skillpm（Windows）。内网外网慢，默认完全不碰 PyPI。
#
#   Set-ExecutionPolicy -Scope Process Bypass -Force; & scripts\install.ps1
#
#   ↑ 用 & 调用，装完 PATH 在当前窗口就生效。
#     写成 powershell -File scripts\install.ps1 也能装，但那是另起一个进程，
#     它改的 PATH 传不回你的窗口，得重开一个终端才认得 skillpm。
#   ...\install.ps1 -Mode launcher    只做启动器（最快，零网络）
#   ...\install.ps1 -Mode pip         用 pip 装
#   ...\install.ps1 -Prefix D:\bin    指定装到哪
#   ...\install.ps1 -Yes            不问任何问题（批量铺开、CI）
#
# 重复运行 = 更新：会先 git pull 再重新链接。
param(
    [ValidateSet("auto", "launcher", "pip")] [string]$Mode = "auto",
    [string]$Prefix = "",
    [switch]$Yes        # 不弹任何询问（批量铺开、CI 用）；PATH 直接加
)
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $PSScriptRoot

# 这个脚本是在你那个窗口里跑的，还是被 powershell -File 起成了独立子进程？
# 子进程改 $env:PATH 对调用方毫无影响，所以结尾那句话必须分开说。
function In-CallerSession {
    # 看本进程自己的命令行：带 -File <某个.ps1> 说明是 powershell -File 起的独立进程；
    # 用 & 调用或点源时，命令行里没有脚本名，说明就在调用者的会话里。
    # 纯 .NET，不依赖 WMI，也不会被策略挡住。
    try {
        $argv = [Environment]::GetCommandLineArgs()
        for ($i = 1; $i -lt $argv.Count; $i++) {
            if ($argv[$i] -match '(?i)^-(f|fi|fil|file)$') { return $false }
        }
        return $true
    } catch {
        return $false      # 判断不了就按「子进程」说，宁可让人多开个窗口，也别给假保证
    }
}

function Have($name) { $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

function Get-Python {
    $seen = @()
    foreach ($c in @("py", "python", "python3")) {
        if (-not (Have $c)) { continue }
        # 应用商店的 python.exe 是个占位壳，跑 -c 什么都不输出，所以这里以输出为准
        $v = & $c -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if (-not $v) { continue }
        $seen += "$c -> $v"
        $parts = $v.Trim().Split('.')
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 8) { return $c }
    }
    if ($seen.Count) {
        throw "Python 版本太低（需要 3.8 以上）：$($seen -join '；')"
    }
    throw "没找到可用的 Python 3.8+。去 python.org 装一个，安装时务必勾上 Add python.exe to PATH。"
}

function On-Path($dir) {
    ($env:PATH -split ';' | ForEach-Object { $_.TrimEnd('\') }) -contains $dir.TrimEnd('\')
}

# 挑一个已经在 PATH 里、而且能写的目录，省得装完还要改环境变量
function Pick-Bin {
    if ($Prefix) { return $Prefix }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\skillpm"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE "bin")
    )
    foreach ($d in $candidates) { if ((On-Path $d) -and (Test-Path $d)) { return $d } }
    return $candidates[0]
}

# 广播「环境变量变了」。直接写注册表不会自动通知，别人不重启就看不到新 PATH。
function Send-EnvChanged {
    if (-not ("Win32.NativeMethods" -as [type])) {
        Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam,
    string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
    }
    $r = [UIntPtr]::Zero
    [void][Win32.NativeMethods]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero,
        "Environment", 2, 5000, [ref]$r)
}

function Add-ToUserPath($dir) {
    if (On-Path $dir) { return }
    # 关键：必须读注册表原值。[Environment]::GetEnvironmentVariable(...,"User") 会把
    # %JAVA_HOME%\bin 这种引用**展开成当时的值**，再写回去就等于把别人的引用永久焊死了。
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
    try {
        $current = $key.GetValue("PATH", "",
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kind = if ($key.GetValue("PATH") -ne $null) { $key.GetValueKind("PATH") }
                else { [Microsoft.Win32.RegistryValueKind]::ExpandString }
        if ($current -and ($current -split ';' | ForEach-Object { $_.TrimEnd('\') }) -contains $dir.TrimEnd('\')) {
            Write-Host "（用户 PATH 里已经有了，新开一个终端就生效）"
            return
        }
        $new = if ($current) { "$current;$dir" } else { $dir }
        # 超长的用户 PATH 写回去有被截断的风险——宁可不写，也不能把别人的 PATH 弄坏
        if ($new.Length -gt 4000) {
            Write-Host "你的用户 PATH 已经有 $($current.Length) 个字符，再加就有截断风险，这里不动它。"
            Write-Host "请自己手动加，或者直接用全路径：$dir\skillpm.cmd"
            return
        }
        if (-not $Yes) {
            $answer = Read-Host "$dir 不在 PATH 里。要加进用户 PATH 吗？[Y/n]"
            if (-not ($answer -eq "" -or $answer -match '^(y|yes)$')) {
                Write-Host "那你自己把这个目录加进 PATH：$dir"
                return
            }
        }
        $key.SetValue("PATH", $new, $kind)          # 保持原来的类型，别把 ExpandString 降成 String
    } finally {
        if ($key) { $key.Close() }
    }
    Send-EnvChanged
    $env:PATH = "$env:PATH;$dir"     # 进程级：只有在调用者会话里跑时，这一句才对用户有意义
    Write-Host ""
    if (In-CallerSession) {
        Write-Host "已加进用户 PATH，当前这个窗口已经生效，直接往下敲就行。"
    } else {
        Write-Host "已加进用户 PATH。但这个脚本是独立进程，改不了你调用它的那个窗口——"
        Write-Host "要么新开一个 PowerShell，要么在当前窗口粘这一行刷新："
        Write-Host "  `$env:PATH = [Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + [Environment]::GetEnvironmentVariable('PATH','User')"
        Write-Host "（想一步到位：下次用 `& `"`$env:USERPROFILE\.skillpm-src\scripts\install.ps1`"` 这种写法调用，"
        Write-Host "  脚本就在你当前会话里跑，装完立刻能用。）"
    }
}

function Sync-Source {
    # 重复运行就是更新：先把源码拉到最新
    if ((Test-Path (Join-Path $Dir ".git")) -and (Have git)) {
        Write-Host "拉取最新源码…"
        Push-Location $Dir
        try { git pull --ff-only 2>&1 | Out-Null } catch { Write-Host "  git pull 没成功，用当前版本继续" }
        Pop-Location
    }
}

function Install-Launcher($py) {
    $bin = Pick-Bin
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $src = Join-Path $Dir "src"
    $default_src = Join-Path (Join-Path $env:USERPROFILE ".skillpm-src") "src"
    # .cmd 让 cmd 和 PowerShell 都能直接敲 skillpm。
    #
    # 用户名带中文时（C:\Users\王某）路径不能直接写进 .cmd：批处理由 cmd.exe 按
    # OEM 代码页读，写成 ASCII 会变成一串 ?，启动器当场作废。
    # 源码目录本来就写死在 %USERPROFILE%\.skillpm-src，所以默认情况让 Python
    # 自己去读环境变量——整个文件保持纯 ASCII，用户名是什么都不影响。
    # 只有装在非默认位置时才落地真实路径，那种情况按 OEM 编码写。
    if ($src -eq $default_src) {
        $locate = "os.path.join(os.environ['USERPROFILE'],'.skillpm-src','src')"
        $enc = "ASCII"
    } else {
        $locate = "r'$src'"
        $enc = "Oem"
    }
    $cmd = @"
@echo off
rem generated by skillpm\scripts\install.ps1
"$py" -c "import sys,os;sys.path.insert(0,$locate);from skillpm.cli import main;sys.exit(main())" %*
"@
    Set-Content -Path (Join-Path $bin "skillpm.cmd") -Value $cmd -Encoding $enc
    $home_dir = Join-Path $env:USERPROFILE ".skillpm"
    New-Item -ItemType Directory -Force -Path $home_dir | Out-Null
    Set-Content -Path (Join-Path $home_dir ".installed-at") -Value (Join-Path $bin "skillpm.cmd") -Encoding UTF8
    Write-Host "装好了：$bin\skillpm.cmd"
    Add-ToUserPath $bin
    Write-Host ""
    if (In-CallerSession) { Write-Host "验证：skillpm -v" }
    else { Write-Host "验证（新窗口里）：skillpm -v" }
    Write-Host "以后升级：直接敲 skillpm self-update（在哪个目录都行）"
}

function Install-Pip($py) {
    # --no-build-isolation：用本机已有的 setuptools，不去 PyPI 下东西
    Write-Host "用 pip 安装（不走 PyPI）…"
    & $py -m pip install --no-build-isolation --user $Dir
    $scripts = & $py -c "import site,os;print(os.path.join(site.USER_BASE,'Scripts'))"
    Write-Host "装好了：$scripts\skillpm.exe"
    Add-ToUserPath $scripts
    Write-Host "验证：skillpm -v"
}

if (-not (Test-Path (Join-Path $Dir "src\skillpm\cli.py"))) {
    throw "源码不完整：$Dir 下找不到 src\skillpm\cli.py。把这个目录删掉重新克隆一次。"
}
$py = Get-Python
Sync-Source
switch ($Mode) {
    "pip"      { Install-Pip $py }
    "launcher" { Install-Launcher $py }
    default    { Install-Launcher $py }   # 启动器更干净：升级只要 git pull，卸载只要删一个文件
}
