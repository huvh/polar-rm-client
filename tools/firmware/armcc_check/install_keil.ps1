# install_keil.ps1 —— 一条龙装 MDK-Lite + ARM Compiler 5 + STM32F4xx DFP（要管理员）
#
#   右键"以管理员身份运行 PowerShell"，或者：
#     Start-Process pwsh -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#         '-File','D:\...\tools\firmware\armcc_check\install_keil.ps1'
#   跑完看同目录 install_log.txt。
#
# 三件事都必须做，缺一样 uVision 就编不了这个工程：
#   1) MDK543a.exe --batch-install            静默装 MDK-Lite（实测不用点向导）
#   2) 把 ARMCC 5.06u7 铺进 <KeilRoot>\ARM\ARMCC 并在 TOOLS.INI 注册 ARMCCPATH
#      —— MDK 5.38+ 本体已经不带 AC5，而本工程锁 ARMCC 5 + RVDS 端口，
#         不注册时 uVision 直接 "ARM-Compiler 'Default Compiler Version 5' is not available"。
#   3) 装 Keil.STM32F4xx_DFP（工程 PackID 要 2.17.1）
#      —— 不装也能编译（HAL/CMSIS 都在仓库里），但 uVision 每次 Build 会重写
#         MDK-ARM/RTE/_standard_robot/RTE_Components.h，把
#         #define CMSIS_device_header "stm32f4xx.h" 删掉；烧录要的 Flash 算法也在这个 pack 里。
param(
    [string]$MdkExe   = 'D:\keilpk\MDK543a.exe',
    [string]$Ac5Msi   = 'D:\keilpk\ARMCompiler506_b960.msi',
    [string]$DfpPack  = 'D:\keilpk\Keil.STM32F4xx_DFP.2.17.1.pack',
    [string]$KeilRoot = 'D:\LocalAppData\Keil_v5'
)
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot 'install_log.txt'
function L($m) { ($(Get-Date -Format 'HH:mm:ss') + '  ' + $m) | Add-Content -Path $log }
"=== install $(Get-Date) KeilRoot=$KeilRoot ===" | Set-Content -Encoding utf8 $log
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L '不是管理员，退出（请 -Verb RunAs 重跑）'; Write-Error 'need administrator'; exit 1
}
$UV4 = Join-Path $KeilRoot 'UV4\UV4.exe'

# 1) MDK-Lite：安装器默认目录是 %LOCALAPPDATA%\Keil_v5，所以把 LOCALAPPDATA 指到 D 盘
#    （C 盘只剩几 GB，装 3.6GB 会撑爆）
New-Item -ItemType Directory -Force -Path (Split-Path $KeilRoot) | Out-Null
$env:LOCALAPPDATA = (Split-Path $KeilRoot)
if (-not (Test-Path $UV4)) {
    L '步骤1: MDK543a.exe --batch-install'
    $p = Start-Process $MdkExe -ArgumentList '--batch-install' -PassThru
    $dl = (Get-Date).AddMinutes(12)
    while (-not (Test-Path $UV4) -and (Get-Date) -lt $dl) { Start-Sleep -Seconds 5 }
    if (-not (Test-Path $UV4)) { L '  静默安装没出 UV4，弹向导手工点'; Start-Process $MdkExe }
    $dl = (Get-Date).AddMinutes(25)
    while (-not (Test-Path $UV4) -and (Get-Date) -lt $dl) { Start-Sleep -Seconds 10 }
}
if (-not (Test-Path $UV4)) { L 'FAILED: MDK 未装上'; exit 1 }
$n = Get-ChildItem $KeilRoot -Recurse -File -EA SilentlyContinue | Measure-Object -Property Length -Sum
L ("步骤1 OK: UV4 存在，{0} 文件 / {1} MB" -f $n.Count, [math]::Round($n.Sum / 1MB, 0))

# 2) ARM Compiler 5：先试正常安装，再把解出来的文件兜底铺进 <KeilRoot>\ARM\ARMCC
$armcc = Join-Path $KeilRoot 'ARM\ARMCC\bin\armcc.exe'
if (-not (Test-Path $armcc)) {
    if (Test-Path $Ac5Msi) {
        L '步骤2: msiexec /i ARMCompiler506_b960.msi'
        $q = Start-Process msiexec -ArgumentList '/i', "`"$Ac5Msi`"", '/qn',
                           "TARGETDIR=$KeilRoot\ARM\ARMCC" -Wait -PassThru
        L "  msiexec exit=$($q.ExitCode)"
    }
}
if (-not (Test-Path $armcc)) {
    $extract = 'D:\ac5root'
    if (-not (Test-Path (Join-Path $extract 'PFiles\ARM_Compiler_5.06u7\bin\armcc.exe'))) {
        L "步骤2 兜底: msiexec /a 解出 AC5 到 $extract"
        Start-Process msiexec -ArgumentList '/a', "`"$Ac5Msi`"", '/qn', "TARGETDIR=$extract" -Wait
    }
    $src = Join-Path $extract 'PFiles\ARM_Compiler_5.06u7'
    if (Test-Path (Join-Path $src 'bin\armcc.exe')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $KeilRoot 'ARM\ARMCC') | Out-Null
        Copy-Item "$src\*" (Join-Path $KeilRoot 'ARM\ARMCC') -Recurse -Force
        L ("  已复制 AC5 -> " + (Test-Path $armcc))
    } else { L '  找不到 AC5 文件，uVision 会报没有 Compiler 5' }
}
# 注册进 TOOLS.INI，否则 uVision 找不到 V5
$ini = Join-Path $KeilRoot 'TOOLS.INI'
if ((Test-Path $ini) -and -not ((Get-Content $ini -Raw) -match 'ARMCCPATH\d+="\.\.?\s*\\?\\?ARMCC"')) {
    Copy-Item $ini "$ini.bak" -Force
    $t = Get-Content $ini -Raw
    $anchor = ($t -split "`n" | Where-Object { $_ -match '^ARMCCPATH0=' } | Select-Object -First 1)
    if ($anchor) {
        $t = $t.Replace($anchor, $anchor.TrimEnd() + "`nARMCCPATH1=`".\ARMCC`" (`"V5.06.7`")")
        Set-Content -Path $ini -Value $t -Encoding ascii -NoNewline
        L '步骤2 OK: TOOLS.INI 已注册 ARMCCPATH1=".\ARMCC" ("V5.06.7")'
    } else { L '步骤2 WARN: TOOLS.INI 里没找到 ARMCCPATH0，无法注册 V5' }
}

# 3) DFP pack
if (Test-Path $DfpPack) {
    $packs = if (Select-String -Path $ini -Pattern 'RTEPATH="([^"]+)"' -Quiet) {
        [regex]::Match((Get-Content $ini -Raw), 'RTEPATH="([^"]+)"').Groups[1].Value
    } else { Join-Path $env:LOCALAPPDATA 'Arm\Packs' }
    $dst = Join-Path $packs 'Keil\STM32F4xx_DFP\2.17.1'
    if (-not (Test-Path (Join-Path $dst 'Keil.STM32F4xx_DFP.pdsc'))) {
        L "步骤3: 解包 DFP -> $dst"
        # 实测 PackInstaller.exe -i ... -a --skip-touch 返回 2（不认这组参数），
        # UV4 -f 会弹窗口挂住；而 .pack 本身就是 zip，直接解到 RTEPATH 下 uVision 就认。
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($DfpPack, $dst)
        L ("  DFP pdsc: " + (Test-Path (Join-Path $dst 'Keil.STM32F4xx_DFP.pdsc')))
        L '  注：装了 pack 之后 uVision 重写 RTE_Components.h 才会保留 CMSIS_device_header'
    } else { L '步骤3: DFP 已存在' }
} else { L "步骤3 WARN: 没找到 $DfpPack" }
L '=== 完成。编译： ==='
L ('  & "' + $UV4 + '" -b "<repo>\MDK-ARM\standard_robot.uvprojx" -j0 -o build_log.txt')
L 'DONE'
Write-Output "完成，看 $log"
