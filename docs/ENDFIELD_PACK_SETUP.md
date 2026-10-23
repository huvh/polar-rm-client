# Windows 源码版：完整准备原生 Endfield Esc 资源包

对应 [issue #22](https://github.com/lulunomaro/polar-rm-client/issues/22)。
当前 main 已随附完整 `assets/endfield_pack`，正常拉取并重启即可使用；以下构建步骤
用于离线重建/维护，不是每台 Windows 电脑的首次启动要求。旧 Release 需要更新，
本地已有损坏的场景覆盖资源时仍保留诊断，请先备份检查该覆盖包。
**只创建 `BUILD_MANIFEST.json`、只下载上游 portable ZIP、或只编译一个 DLL 都不够。**
本流程保持已有原生菜单、动画、液态玻璃背景和真实 RM 场地，不替换菜单、不关闭功能。
准备工具不在客户端启动/绘制线程运行，也不会访问机器人、启动游戏或修改游戏文件。

已有完整包时不必重复构建：见[跨电脑完整迁移](endfield_delivery_video_reconnect_20261022.md)。
客户端支持只读 `assets/endfield_pack`；便携包支持 `resources/assets/endfield_pack`。
空的本地用户目录不会遮蔽它们，但公开分发第三方素材仍需要单独授权。
场景资源仍可由本地完整包覆盖；原生 DLL 优先使用当前版本随附的代码，避免旧本地 DLL
遮蔽修复。跨机器 Esc 背景发白的合成修复与排查见[说明](esc_white_background_20261023.md)。

## 1. 固定输入，而不是作者电脑路径

机器可读的唯一输入清单是 [`tools/endfield_pack_sources.json`](../tools/endfield_pack_sources.json)。
脚本在写任何运行包之前检查全部输入的 SHA-256、工具版本和源码版本。

| 输入 | 固定来源/身份 |
|---|---|
| EndfieldHUD 源码 | [DDDuoDuo/EndfieldHUD](https://github.com/DDDuoDuo/EndfieldHUD/tree/cdbd4f573c8fa3b9c2048fa3d1b089e69196537b)，commit `cdbd4f573c8fa3b9c2048fa3d1b089e69196537b` |
| 基础场景/字体资源 | [v1.2.0 / build18 Windows portable ZIP](https://github.com/DDDuoDuo/EndfieldHUD/releases/download/v1.2.0/EndfieldHUD-1.2.0-build18-windows-x64-portable.zip)，SHA-256 `b16f77c5dfa1c7e7cfe2ed96697347b880932a25507f6c8cb823ffec2a9a9341` |
| RM 三个 STEP 模型 | [RoboMaster 高校赛务：RMU 2027 场地图纸](https://bbs.robomaster.com/article/1970956?source=11)，V1.0.0；附件直链和大小已固定到输入清单 |
| POLAR 原生适配器 | 当前客户端 checkout 的 `native/endfield_bridge.cpp`，构建时记录完整 SHA-256 |

| 模型原始文件名 | SHA-256 | 向上轴 |
|---|---|---|
| `RMUC2027_V1.0.0.stp` | `a5ad3ede3b7674fc98f2e73b71717216383cb2b4b5dcdbe900c2038918bea8e0` | `z` |
| `RMUL2027_3V3_V1.0.0.stp` | `7d47c1b6a6a0253a732e46cb122bb84410b11d5134bcb5658104299db4a48ca4` | `-y` |
| `RMUL2027_1V1_V1.0.0.stp` | `954936e74885493836d73ba215e1c42efc3b6d40279478f5e5d626109e2cf6d1` | `-y` |

7v7 STEP 约 623 MiB，全部输入和编译中间文件需预留数 GiB；首次准备需数分钟，
不是运行时依赖。模型用于预览，不替代规则手册或现场实物。

## 2. 单独安装离线工具环境

Windows 11 x64、Python **3.12 x64**、Git、系统 `curl.exe`。在仓库根目录执行：

```powershell
# py 是 Windows Python launcher；也可用已安装的 Python 3.12 x64 完整路径。
py -3.12 -m venv .venv-endfield-tools
$ToolPy = (Resolve-Path .venv-endfield-tools/Scripts/python.exe).Path
& $ToolPy -m pip install -r requirements-endfield-tools.txt
if ($LASTEXITCODE -ne 0) { throw '工具环境安装失败' }
```

清单固定 Zig 0.14.1（内带 Clang 19.1.7 / Windows 交叉编译支持）、
cadquery-ocp 8.0.1.1.0、VTK 9.6.2、NumPy 2.5.4。
不需要单独下载 MSVC/Windows SDK，不使用旧的 Zig 0.13 固件验证环境。
**不要安装到 `.venv` 客户端运行环境，不要修改 `requirements-build.txt`。**
工具依赖必须由使用者显式安装；客户端不会首次启动联网安装它们。

## 3. 下载全部菜单必需输入

以下 PowerShell 使用仓库已固定的真实 URL，不需要替换 `PINNED_*` 占位符。
若你已经有逐字节匹配的输入，可直接用自己的目录进入下一节。

```powershell
$Pins = Get-Content -Raw -Encoding utf8 tools/endfield_pack_sources.json | ConvertFrom-Json
$Inputs = Join-Path (Get-Location) 'tmp_endfield_inputs_22'
if (Test-Path -LiteralPath $Inputs) { throw '请选择一个全新的输入目录，或复用已校验的下载文件' }
New-Item -ItemType Directory -Path $Inputs | Out-Null
$Models = Join-Path $Inputs 'models'
New-Item -ItemType Directory -Path $Models | Out-Null
$Package = Join-Path $Inputs 'EndfieldHUD-1.2.0-build18-windows-x64-portable.zip'
curl.exe --fail --location --retry 3 --output $Package $Pins.resource_url
if ($LASTEXITCODE -ne 0) { throw '基础资源下载失败' }
foreach ($Entry in $Pins.models.PSObject.Properties) {
    $Row = $Entry.Value
    curl.exe --fail --location --retry 3 --output (Join-Path $Models $Row.filename) $Row.url
    if ($LASTEXITCODE -ne 0) { throw ('模型下载失败: ' + $Row.filename) }
}
$Reference = Join-Path $Inputs 'EndfieldHUD'
git clone --no-checkout $Pins.reference_repository $Reference
if ($LASTEXITCODE -ne 0) { throw '源码克隆失败' }
git -C $Reference checkout --detach $Pins.reference_commit
if ($LASTEXITCODE -ne 0) { throw '固定源码 checkout 失败' }
```

下载失败不要使用 HTML 错误页、最新版本或其他简模替代。已有目录可以保留，
重试时明确指定其中的完整文件；准备脚本会再次核对哈希，不要求重新下载成功文件。

## 4. 一条命令完成导入、DLL 和三个模型

先关闭已打开的客户端；先前因缺包失败的原生 owner 不会在磁盘补包后自行重试，
准备并校验完成后需重新启动。

先按 [README](../README.md#运行) 准备客户端 `.venv`。下列 `$Target` 由客户端自己的
`RuntimePaths` 决定，尊重显式 `POLAR_USER_DATA_ROOT`，不是任意当前工作目录。

```powershell
$AppPy = (Resolve-Path .venv/Scripts/python.exe).Path
$Target = & $AppPy -c "from rm_client.runtime_paths import RuntimePaths; print(RuntimePaths.discover().user_data_root / 'endfield_pack')"
if ($LASTEXITCODE -ne 0) { throw '无法解析客户端运行目录' }
& $ToolPy tools/prepare_endfield_pack.py build `
    --package $Package --reference $Reference --models $Models --out $Target
if ($LASTEXITCODE -ne 0) { throw '完整菜单资源包没有发布；查看保留的诊断目录' }
& $AppPy tools/prepare_endfield_pack.py check --pack $Target
if ($LASTEXITCODE -ne 0) { throw '资源包校验失败，请勿启动原生菜单' }
& $AppPy main.py
```

从启动页进入 HUD 后按 Esc。工具会按顺序：

1. 校验 ZIP、三份 STEP、四个工具版本和上游 Git commit/干净源码。
2. 只导入基础场景、所需原始资源和字体/许可证；**不复制或运行上游 exe**。
3. 编译 POLAR C++20 适配 DLL，安装真实 `BUILD_MANIFEST.json` 与原子 `CURRENT.json`。
4. 用原有离线工具生成三个模型的 `.efmesh`、`.json`、`.png`，保留实际坐标与既有镜头。
5. 对全部 37 个上游资源核对独立锁表，核对 DLL/指针/源版本、所有文件哈希、
   模型来源/轴向/尺寸/有限值/顶点索引，最后才把**新**目录原子发布到 `$Target`。

目标已经存在时不会覆盖、合并、删除或修改。升级时先关闭客户端，保留旧包，
给 `--out` 指定一个新目录；校验成功后再由使用者显式切换整个目录。
失败或中断只会保留该次新建的 `.endfield-build-*` 诊断目录，**不会把半包标成可用**。
哈希校验不等于代码签名，不能从不可信来源收取 DLL 后自行补清单冒充可信构建。

### 完整目录结构

```text
user_data/endfield_pack/
  ENDFIELD_PACK_MANIFEST.json
  native_source_runtime/
    SOURCE_RUNTIME_MANIFEST.json
    resources/shell/catalog.ehscene
    resources/shell/runtime-input/...
    resources/licenses/...
    fonts/...
  native_renderer/
    CURRENT.json
    build_<adapter SHA256前16位>/
      polar_endfield.dll
      BUILD_MANIFEST.json
      EndfieldHUD-MIT-LICENSE.txt
  maps/
    RMUC7v7.efmesh / RMUC7v7.json / RMUC7v7.png
    RMUL3v3.efmesh / RMUL3v3.json / RMUL3v3.png
    RMUL1v1.efmesh / RMUL1v1.json / RMUL1v1.png
  licenses/
    EndfieldHUD-LICENSE / EndfieldHUD-CREDITS.md / SOURCES.json
```

`CURRENT.json` 中的二进制 SHA-256、版本目录和版本目录内的 `BUILD_MANIFEST.json`
必须一致；DLL 同时绑定当前 POLAR 适配器和固定的上游源码。
不同编译路径/环境可能产生不同 DLL 哈希，**以该次实际构建清单为准**，不承诺二进制逐位可复现。

## 5. 真实原生渲染验收（不接设备）

`check` 是完整性检查，不会加载 DLL，更不证明画面已经渲染。准备成功后运行：

```powershell
& $AppPy tools/verify_endfield_pack_runtime.py --pack $Target --out tmp_issue22_native
# 需要实际桌面 OpenGL/D3D，临时用户配置和惰性设备：
& $AppPy tools/verify_endfield_desktop.py --pack $Target --out tmp_issue22_desktop --cycles 3
```

输出目录必须新建。第一项实际创建本客户端拥有的 D3D 场景，检查三种模式、
1280×720/2560×1440、英/中文、非空帧与 owner 退出；第二项验证真实客户端 Esc、
模糊背景、全屏/设置交互和关闭/重进。测试不会把菜单预览支持等同于 1v1 比赛业务支持。
不运行游戏，不扫描串口，不放开驾驶/开火/经济请求，也不认证比赛资格。

## 6. Esc 必需和可选素材的边界

**以上流程已包含菜单全部必需资源，不需要用户安装终末地或自行解包。**
上游 [CREDITS](https://github.com/DDDuoDuo/EndfieldHUD/blob/cdbd4f573c8fa3b9c2048fa3d1b089e69196537b/CREDITS.md)
将游戏素材排除在 MIT 之外；本修复不把本机游戏导出或个人运行数据提交到 Git。
RM 模型来源与署名保存在 `licenses/SOURCES.json`；模型使用范围遵循官方来源说明。

以下均为**可选**，本安装流程和 #22 的菜单验收不依赖它们：

- `boot/`：原版启动加载条所用的 LoginRootPanel prefab、`loadingicon_loop.anim`、
  `login_loading_bg01/bg02/icon` 三张纹理及 `defaultfont_cn.ttf`。现有
  `prepare_endfield_boot.py` 接受显式 EndfieldStudio original/raw/metadata 导出目录
  （含 `_index.jsonl`）生成布局、曲线、图片和字体。它不是 VFS 解包器，也不会联网下载游戏素材。
- `audio/entering_aic.wav`、`audio/insufficient_power.wav`：已授权本机 EFOS 原音，
  需使用者另行提供；上游 portable 不含游戏语音，本流程不会伪造或合成原音。

当前工具构建菜单专用完整包，不提供可选游戏导出的追加安装模式。以后接入这些
素材时需扩展准备流程并保留来源；不要为了通过 `check` 手改哈希。
普通菜单运行不要求导入这些文件。

## 7. 常见问题

- `BUILD_MANIFEST.json` 缺失：缺的是整个准备流程，按第 2–4 节构建，不是补一个 JSON。
- 工具版本错误：检查使用的是 `$ToolPy`，不是 `.venv` 或固件验证 Zig 0.13。
- 输入 SHA 错误：参考输入清单重取固定文件；不取消校验、不换其他模型。
- `Pack adapter differs`：客户端适配器已更新，用当前 checkout 构建一个新包。
- 只有某模式失败：`check` 必须覆盖三个 `.efmesh`，不能用复制改名伪装其他场地。
- 移动目录后失效：确认移动的是整个 `endfield_pack`，且落在实际 `RuntimePaths` 用户目录。
- GPU/驱动创建失败：资源完整性成功不等于 D3D 可用；保存真实错误与驱动信息，
  不替换菜单、关闭玻璃或把离屏静态测试冒充桌面验收。
