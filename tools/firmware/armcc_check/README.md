# armcc_check —— 用真 ARMCC 5.06 给固件工程做编译/链接体检

> 一句话：**不装 Keil、不写注册表、不碰破解工具**，就能拿 Keil 那套
> `ARMCC 5.06 + C99 + 警告即错误` 把整个 `standard_robot.uvprojx` 过一遍。

## 0. 为什么要有这个工具

`prepare_hero_build.py --gcc-check`（GCC 差分，见 `../host_bridge/GAPS.md` §8.3）
只能证明"补丁没引入新问题"，证明不了**真实工具链**能不能编过 —— 因为本工程
`<pCCUsed>5060422::V5.06 update 4::ARMCC</pCCUsed>`，FreeRTOS 用的还是
`portable/RVDS/ARM_CM4F`（ARMCC 专用内联汇编），换编译器就不等价。

本目录的 `armcc_check.py` 直接读 `.uvprojx` 里工程自己的 include / define /
`MiscControls`，用真 ARMCC 把 162 个编译单元全过一遍，再做两次链接。

## 1. 本机实测结果（2026-09-03，英雄配置 + 三个桥全装上）

| 阶段 | 命令里的动作 | 结果 |
|---|---|---|
| 编译 | `armcc -c` x161 + `armasm` x1 | **162/162 全过，0 error / 0 warning** |
| 符号解析 | `armlink --partial`（+2 个 ARM 库） | **rc=0，L6218E 未定义符号 0 个** |
| 完整链接 | `armlink --scatter`（F407 内存布局） | `Fatal error: L6050U: The code size of this image (109628 bytes) exceeds the maximum allowed for this version of the linker.` |

第三条**不是代码问题**：那是 MDK-Lite 免费授权的 32KB 代码上限，本工程镜像
109,628 字节（约 107KB）。符号、段布局、入口、库全都过了，只差授权放行。
`armcc_check.py` 把这条单独识别成"只差授权"，不计入失败。

顺带一个必须记住的结论：**这份固件没法用 GCC 出镜像**。
`components/algorithm/AHRS.lib` 与 `arm_cortexM4lf_math.lib` 是 ARM 目标格式
（armar/armlink 专用），GNU `ld` 读不了 —— 上板只能用 ARMCC 链接。

## 2. 跑起来

```powershell
# 依赖两样东西的位置，默认取环境变量（或 --ac5 / --mappings 覆盖）
$env:ARMCC5_ROOT = "D:\ac5root\PFiles\ARM_Compiler_5.06u7"   # armcc/armasm/armlink
$env:ARM_MAPPINGS = "D:\keilroot\ARM\sw\mappings"            # 里面有 mdk_lite.elmap

python tools/firmware/armcc_check/armcc_check.py <StandardRobotpp路径> --mode all
```

如果本机装了 MDK（`%LOCALAPPDATA%\Keil_v5` 或 `C:\Keil_v5`），脚本会自动去
`ARM\ARMCC` 和 `ARM\sw\mappings` 找，不用设环境变量。中间产物落在
`%TEMP%\rm_armcc_check\`（含 `armcc_check.log` 全量命令与输出、`map.txt`）。

退出码：0 通过（授权上限只提示）/ 1 有真实编译或链接错误 / 2 环境没凑齐。

## 3. license 这一关是怎么过的

ARMCC 5.06 独立发行版（"ARM Compiler 5.06 update 7"）默认要 `ARMLMD_LICENSE_FILE`
指的 license 文件；而 **MDK-Lite 不查 license server**，它读一个映射文件
`<KeilRoot>\ARM\sw\mappings\mdk_lite.elmap`。所以把两个环境变量给对就行：

```powershell
$env:ARM_PRODUCT_PATH = "D:\keilroot\ARM\sw\mappings"   # 含 mdk_lite.elmap 的目录
$env:ARM_TOOL_VARIANT = "mdk_lite"
```

没给对时的两种表现，可用来自查：
- 只给 `ARM_TOOL_VARIANT` 不给对的 `ARM_PRODUCT_PATH` → `C9511E: Unable to
  determine the current toolkit`（其实 `ARM_PRODUCT_PATH` 留空让它自己按
  工具链目录推断反而更稳）。
- 什么都不给 → `C9555E: Failed to check out a license`。

## 4. 两样东西怎么离线搞到（都不需要管理员）

来源：中科大 RoboWalker 电控培训包的 `robo-electro-control.zip`
（`http://home.ustc.edu.cn/~yssickjgd/net_disk/robo-electro-control.zip`，
1,985,488,401 字节，支持 Range）。**别跑包里的 `keygen.exe`**，那是破解器。

### 4.1 ARM Compiler 5.06 update 7（build 960）

zip 里的 `.../ac5 Installer/data/ARMCompiler506_b960.msi`：压缩 84,701,792
字节，起始偏移（含本地文件头之后的裸 DEFLATE 数据起点）64,883,733，
解压 86,360,064，CRC32 `1129913143`。

```powershell
curl.exe -s -r 64883733-149585524 -o ac5.deflate <zipURL>
# 裸 DEFLATE 还原成 msi（zlib.decompressobj(-15) + CRC32 校验，见 GAPS.md §8.5）
msiexec /a ARMCompiler506_b960.msi /qn TARGETDIR=D:\ac5root     # 免管理员，只解文件不装
```

`/a`（admin-image）只把文件铺出来，不写注册表，所以能免提权。得到
`D:\ac5root\PFiles\ARM_Compiler_5.06u7\{bin,bin64,include,lib,sw}`。

注意 **MDK5.43a 本体已经不带 ARMCC 5**（zip 里只有 `ARM/ARMCLANG`，即 AC6），
所以本工程这种锁 ARMCC 5 + RVDS 端口的活儿，必须单独装 AC5；uVision 里
Options → Target → Code Generation → "Use default compiler version 5" 也要有
AC5 才选得到。

### 4.2 `mdk_lite.elmap`（免 license 的钥匙）

`MDK543a.exe` 本身就是"PE + 尾部 zip"：PE 结构到 2,364,416 字节为止，
后面 849.8MB 是个普通 zip（7,445 个条目）。所以不用安装就能取文件：

```powershell
curl.exe -s -r 274800150-1157468696 -o mdk543a.deflate <zipURL>   # 还原成 MDK543a.exe
# CRC32 2925489275，解压 893,488,656 字节
python -c "import zipfile;z=zipfile.ZipFile(r'D:\keilpk\MDK543a.exe');[open(r'D:\keilroot'+'\\'+i.filename.replace('/',chr(92)),'wb').write(z.read(i)) for i in z.infolist() if i.filename.startswith('ARM/sw/') and not i.is_dir()]"
```

`ARM/sw/mappings/` 里一共 16 个 `.elmap`（`mdk_lite` / `mdk_pro` / `mdk_std` /
`mdk_cm4` / …），这就是 MDK 各授权档位的本地映射，`mdk_lite.elmap` 对应免费
Lite 档。整包解压是 3.1GB，没必要 —— 拿这 16 个文件就够跑编译器了。

## 5. 还是想要 uVision / 要出 hex 怎么办

1. 装 `MDK543a.exe`（要管理员，UAC 点"是"；`SETUP.INI` 里默认目录是
   `%LOCALAPPDATA%\Keil_v5`，C 盘紧的话先把 `LOCALAPPDATA` 指到 D 盘再启动安装器）；
   再装 §4.1 那个 AC5 msi（正常 `/i` 安装，它会把 ARMCC 铺进 Keil 根目录）。
2. 工程 `PackID` 要的是 `Keil.STM32F4xx_DFP.2.17.1`，官方直链可用：
   `https://www.keil.com/pack/Keil.STM32F4xx_DFP.2.17.1.pack`（289MB，已验证 200）。
3. **出 hex 必须有能过 32KB 的授权**（队里/学校那份 MDK License，
   File → License Management 挂上 `.ulf`）。Lite 档在这份固件上必然 L6050U。
4. 命令行编译（装好后）：
   ```powershell
   & "$env:LOCALAPPDATA\Keil_v5\UV4\UV4.exe" -b <repo>\MDK-ARM\standard_robot.uvprojx -j0 -o build_log.txt
   ```
   退出码 0 = 无错，1 = 仅警告，>=2 = 有错误。

## 6. 已修掉的一个真问题（就是本工具抓出来的）

`application/IMU/IMU_solve.c:452` 无条件用 `__GYRO_BIAS_YAW`，但仓库里 11 个
`robot_param_*.h` 只有 3 个定义了它，**英雄（`robot_param_mecannum_hero.h`）和
步兵（`robot_param_omni_infantry.h`）两个都没有** → ARMCC：
`Error: #20: identifier "__GYRO_BIAS_YAW" is undefined`。
上游基线（步兵配置）同样编不过，不是我们打补丁搞坏的。

现在由 `../prepare_hero_build.py` 的 `switch_to_hero()` 在 `robot_param.h` 里插
一段 `#ifndef __GYRO_BIAS_YAW` 兜底定义（值先沿用仓库其它机型的
`0.003096855f`），`--revert` 会一起还原。**换车/换 IMU 记得实车重新标定。**


## 7. 已经真的装上 MDK 了（2026-09-03 补充）

同目录 `install_keil.ps1` 就是一条龙脚本（要管理员，UAC 点"是"），它按顺序做三件事，
**三件都必须做**，少一件 uVision 就编不了这个工程：

1. `MDK543a.exe --batch-install` —— **实测这个静默参数有效**，不用点向导。
   装到哪由 `SETUP.INI` 的 `DefaultDir="%LOCALAPPDATA%\Keil_v5"` 决定，所以脚本
   先把子进程的 `LOCALAPPDATA` 指到 D 盘（C 盘只剩几 GB，3.58GB 装不下）。
   落地结果：`D:\LocalAppData\Keil_v5`，7908 文件 / 3581MB，注册表
   `HKLM\SOFTWARE\WOW6432Node\Keil\Products\MDK` 已写入，`TOOLS.INI` 里
   `TOOL_VARIANT=mdk_lite`、`RTEPATH="D:\LocalAppData\Arm\Packs"`。
2. **ARM Compiler 5 必须单独注册**：MDK 5.43a 不带 AC5，装完 uVision 会直接
   `*** Target 'standard_robot' uses ARM-Compiler 'Default Compiler Version 5' which is not available`
   并 `Build aborted`。脚本把 AC5 铺进 `<KeilRoot>\ARM\ARMCC` 并在 `TOOLS.INI`
   的 `[ARMADS]` 里加一行 `ARMCCPATH1=".\ARMCC" ("V5.06.7")`（原文件备份成
   `TOOLS.INI.bak`）。
3. **DFP pack 也要装**：缺 `Keil.STM32F4xx_DFP` 时编译虽然照过，但 uVision 每次
   Build 会把 `MDK-ARM/RTE/_standard_robot/RTE_Components.h` 重写，
   **把 `#define CMSIS_device_header "stm32f4xx.h"` 删掉**（烧录用到的 Flash 算法
   `STM32F4xx_1024.FLM` 也在这个 pack 里）。pack 是 zip，直接解到
   `RTEPATH\Keil\STM32F4xx_DFP\2.17.1` 即可（`PackInstaller.exe -i ... -a --skip-touch`
   实测返回 2 不成功）。装好后 `RTE_Components.h` 会重新带上那行 define。

命令行编译（脚本第 4 步手跑）：

```powershell
& "D:\LocalAppData\Keil_v5\UV4\UV4.exe" -b "<repo>\MDK-ARM\standard_robot.uvprojx" -j0 -o build_log.txt
```

本目录留了三份原始日志，都是 `UV4 -b ... -j0 -o` 直接产出的：
`uvision_build_log_full.txt`（首次全量）、`uvision_build_log_withpack.txt`（装好 DFP 之后）、
`uvision_build_log_dt7.txt`（**DT7 适配之后**的复测，见下面第 8 节）。

uVision 5.43.1.0 全量编译实测（37 秒）：

```
*** Using Compiler 'V5.06 update 7 (build 960)', folder: 'D:\LocalAppData\Keil_v5\ARM\ARMCC\Bin'
Build target 'standard_robot'
assembling startup_stm32f407xx.s...        (1 个)
compiling ...                              (161 个)
linking...
standard_tpye_c\standard_tpye_c.axf: error: L6050U: The code size of this image (140444 bytes)
    exceeds the maximum allowed for this version of the linker.
"standard_tpye_c\standard_tpye_c.axf" - 1 Error(s), 0 Warning(s).
Target not created.
```

也就是说 IDE 这条路与 §1 的命令行结论完全一致：**编译 162/162 全过、0 warning，
唯一拦下的是 MDK-Lite 的 32KB 链接上限**。想产出 `.axf/.hex`，只需要一份能过
32KB 的 MDK 授权（File -> License Management 挂上队里/学校的 `.ulf`），
不需要改任何代码。

---

## 8. DT7（比赛链路）适配后的复测（2026-09-03 晚）

改动：`__RC_TYPE` 由 `RC_ET08A` 切到 `RC_DT7`（`prepare_hero_build.py --rc dt7`），
外加"驾驶键位记账合并"（`HOST_RC_DRIVER_KEYS | HOST_RC_HOST_KEYS` 写回 `key.v`，
三处落点见 `../host_bridge/RC_LINKS.md` §3）。

| 工具链 | 命令 | 结果 |
|---|---|---|
| ARMCC 5.06 命令行 | `armcc_check.py <树> --mode all --objdir D:\rmbuild\armcc_dt7b` | 162/162 单元 0 error 0 warning；`armlink --partial` rc=0、未定义符号 0；完整链接只差授权：`L6050U`（镜像 109100 字节 > 32768） |
| 同一套代码换回 et08a | `prepare_hero_build.py <树> --rc et08a` + `--mode compile` | 162/162 通过 —— 两种遥控器配置都能编 |
| uVision 5.43.1 IDE | `UV4 -b standard_robot.uvprojx -j0 -o ...` | `Using Compiler 'V5.06 update 7 (build 960)'` → 全部 .c/.s 编译通过、**0 Warning(s)** → `L6050U: ... (139824 bytes)` → `1 Error(s), 0 Warning(s)` |

结论没变，只是更硬了：**代码本身在真工具链下干净，挡路的只有 MDK-Lite 的 32KB 授权上限。**
出 hex 需要一份能过 32KB 的正式授权（不能改用 GCC 绕：`AHRS.lib` 与
`arm_cortexM4lf_math.lib` 是 ARM armar 格式，GNU ld 读不了）。

uVision 每次 Build 会重写 `MDK-ARM/RTE/_standard_robot/RTE_Components.h` 并生成
`MDK-ARM/standard_tpye_c/`（约 246MB）与 `MDK-ARM/RTE/Device/`，三者都不在 .gitignore 里；
跑完务必 `git checkout --` 前者、删掉后两者，否则工作树会被 200 多兆的构建产物污染。
`RTE/Device` 里的 `.dbgconf.base@0.0.0` 是只读文件，删除要先 `chmod S_IWRITE`。
