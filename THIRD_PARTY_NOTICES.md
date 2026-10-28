# 第三方实现参考

## 本机 Endfield 设置页适配

- 按用户要求，从 `W:\yj games\Arknights Endfield` 只读提取设置页 prefab、14 张纹理、10 组原始动画及 `defaultfont_cn.ttf`，用于视频、音频、游戏、键位、准星和 HUD 六页的本地适配。20 个源分包的偏移、MD5、SHA-256 与逐对象来源保存在 `rm_client/ui/endfield/settings/assets/PROVENANCE.json`。
- Qt 表现层采样本体进退、切页、页签闪动、下拉和双选项切换曲线，偏好草稿和事务仍由客户端持有。游戏场景模糊和专有 shader 未嵌入 Qt；背景和控件材质由 Qt 适配，不宣称运行原游戏渲染器。
- 游戏 UI、动画、字体及商标权利归 HYPERGRYPH 等相应权利人，不因本项目源码许可获得再分发授权。本次未发布资源或推送仓库，运行时不再依赖游戏安装目录和离线解包工具。

## 本机 Endfield Wiki 终端适配

- 2026-10-24 按用户提供的 `C:\endfield_ui\Endfield_Wiki_UI` 及本机游戏资源只读导出，准备终端所需的几何图标、编号、背景装饰和 24 组动画曲线；运行文件位于 `rm_client/ui/endfield/wiki/assets`。逐项原始路径、包名、对象 ID、输出哈希及灰色材质适配记录在 `PROVENANCE.json`。
- 终端保留 RoboMaster 原有六分类、模块/设置 ID 和动作路由；未导入游戏玩法、百科条目或游戏进程。运行时不依赖 Unity、EndfieldStudio、UnityPy 或游戏安装目录。
- 提取使用 EIHRTeam/EndfieldStudio 的离线 `original --full` 输出，曲线解码使用 UnityPy；这些工具不进入客户端运行环境。文字使用包内附有 OFL 的 Noto Sans SC，同既有 Endfield 包版本一致。新增导航 SVG 为本项目代码绘制资源。
- 游戏素材及动画数据权利归各自权利人；本项目代码许可不授予这些素材的再分发权。此次仅完成用户授权的本地适配，没有发布素材或推送仓库。

## EndfieldHUD 与随源 Esc 运行包

- 可选 Windows Esc 菜单使用 [DDDuoDuo/EndfieldHUD](https://github.com/DDDuoDuo/EndfieldHUD) 的原生场景与渲染器；构建固定到 `cdbd4f573c8fa3b9c2048fa3d1b089e69196537b`。上游采用 MIT License，原始授权全文保留在 `licenses/EndfieldHUD-LICENSE.txt`。
- 按仓库维护者于 2026-10-22 明确要求，完整菜单运行包位于 `rm_client/ui/endfield/menu/assets`，由完整性清单记录全部文件：包括所需原始图片/字体/场景数据、经校验的 Windows x64 原生适配 DLL、三个 RM 2027 场地预览与网格，以及原始许可/来源/哈希清单。不自动下载、安装或运行游戏，不打包用户配置、日志、整个游戏或上游 exe。
- 个人覆盖包、启动画面和可选语音仍保留在被忽略的 `user_data/endfield_pack`。普通菜单不依赖这些可选文件。字体的 OFL、上游 MIT/CREDITS 和官方模型来源随包保存；分发边界见 `licenses/Endfield-Menu-PACK-NOTICE.md`。
- 开源渲染器的 MIT 授权不授予终末地游戏素材的再分发权。游戏素材的版权、商标及其他权利仍归各权利人；Windows 资源缺失时保留准备诊断；完整的本地准备流程见 `docs/endfield/PACK_SETUP.md`，不以空清单或更换菜单代替资源。接入范围与限制见 `docs/endfield/SOURCE_PORT.md`。

## AndroidLiquidGlass-kmp

- 本项目的 GPU 液态玻璃镜片参考了本地 `AndroidLiquidGlass-kmp` 的镜片数学结构，包括圆角 SDF、窄边折射带、圆形折射曲线和边缘色差思路。
- POLAR-RM 使用 PySide6/OpenGL 重新实现，没有嵌入 Compose 运行时。
- 上游许可证：Apache License 2.0。

## DynamicIsland-System-for-mc-hacked-client

- 灵动岛参考其目标宽高平滑、内容裁剪和 EaseOutExpo 时序，在 POLAR-RM 中重新实现。
- 未迁移 Minecraft 功能或品牌素材。

## OpenZen 与 TestClient

- ModuleList 与保留的旧 ClickGUI 仅迁移界面结构、布局规则和动效语言；RM 模块及业务逻辑由 POLAR-RM 自身实现。
- `assets/fonts` 中的 `MaterialIcons-Regular.ttf`（Material Icons Outlined，Google，Apache License 2.0）、`Poppins-Regular/Medium/Bold.ttf`（ITF，SIL Open Font License 1.1）与 `zenicon-Regular.ttf`（OpenZen 自带图标字体）复制自本机 OpenZen 工程的资源目录，用于恢复启动页场景图标与 Poppins 排版；其余权利归各自权利人所有。

## Sigma Jello ClickGUI

- Jello ClickGUI 的坐标、颜色、视觉层级、动画时序、字体、核心 UI 图片和短交互音效取自用户提供的本机 Sigma Jello 5.1.0 JAR，用于本地客户端的一比一界面复刻。
- 提取基准 JAR 的 SHA-256 为 `3ce1573562fa2c17394400d8c4cafcd9ac8d68ea128040c9eea5f3873bec7406`；提交中的 23 个 Jello 图片、字体和短音效文件均已逐文件哈希回查为该 JAR 内的原始字节。
- 随项目保存的原始资源仅包括 Helvetica Neue Light/Medium 字体、Options/勾选/滚动条端帽/八方向阴影图片，以及 `activate`、`deactivate` 等八个短 UI 音效；相关权利归各自权利人所有。
- 未迁移音乐播放器、小游戏、音乐、游戏逻辑或其他 Sigma 运行时代码与资源。
- 新增的 `Jello-Regular.ttf` 为原始 JAR 的 `regular.ttf`（SHA-256 `462fa16c0bccee134ac8dcd5b0d5cbc4e992d5d32de620ce290ba784ba46638a`），用于键盘已绑定键的原版排版。字体权利归原权利人，不因本项目提交而变成开源授权。
- Jello UI 现按功能封装于 `rm_client/ui/jello/`：24 个已有图片/字体/短音效资源逐文件保持原始字节，迁移前位置及哈希见 `JELLO_RESOURCES.json`。路径重组不改变第三方权利或再分发条件。

## CS2 随源素材与可选本机覆盖包

- 原生顶栏字体、击杀标记、购买图标及短音效通过离线白名单导入器从用户本机 CS2 资源只读提取；不修改 Steam 安装、游戏配置或运行进程。
- 经用户明确确认拥有公开再分发授权，已审核的 37 个图片、字体和短音效连同清单位于 `assets/cs2_ui_pack`，进入 Git 并随普通资源构建分发。清单记录 34 个运行时白名单资源和 3 个保留的离线导出变体的 SHA-256；后者不自动启用。
- 可选个人覆盖包仍位于 `user_data/cs2_ui_pack`，不进入 Git。有效覆盖包优先，否则使用随源包；不需要本机安装 CS2。`-Cs2UiPackPath` 仍用于发布时显式指定覆盖包，不会收集其余用户数据。
- 这些 Valve/第三方素材并非本项目或解包工具的开源授权内容。本次分发依据用户确认的授权，不因提交而变成开源授权；原版权、商标和适用许可仍归各权利人。仅拥有本地游戏文件不等于拥有再分发权。
- 项目原创的 RM 购买图标位于 `assets/ui/cs2_buy`。CS2 准星代码由独立实现的格式解析器处理，不复制 CS2 引擎代码。

## Minecraft 1.21.11 HUD 资源

- Hotbar、选择框、心、护甲、饱食度、BossBar、状态背景、背包容器和 `ascii.png` 位图字体来自用户提供的本机 Minecraft 1.21.11 Fabric 客户端 JAR。
- 提取基准 JAR 的 SHA-256 为 `1473c9489ac50fda3c435049a76a70d61a10b8610db27f5ba9d8756b686cd3bd`；提交中的 23 个 Minecraft HUD 资源文件均已逐文件哈希回查为该 JAR 内的原始字节。新增 `inventory.png` 对应 `assets/minecraft/textures/gui/container/inventory.png`，SHA-256 为 `c2f850076ad7ebd7a1b27d017fe5f66ac388f54de374de988cb79f86b1d59a65`。
- 资源只用于本地 Minecraft 战斗 HUD 预设；相关商标、视觉资源和其他权利归 Mojang/Microsoft 及各自权利人所有。本项目未打包完整 Minecraft 客户端或游戏代码。
- 视觉修订另取本地 JAR 的两张 bitmap 字体表/provider 配置及九个伤害类别物品纹理；额外 13 个原始资源的哈希/来源记录在 `assets/minecraft_hud/presentation_manifest.json`。Steve 皮肤及人物预览已删除。Mod 图标为项目原创的功能性像素物品，不是以上原版物品的替代名称。
- `unifont.zip` 来自本机 Minecraft asset index 29，SHA-1 为 `ccd5ac4767ce0a9c71d1dd62f2dc25449789b5dd`。其中字体版本为 GNU Unifont 17.0.01，原始授权全文保留在压缩包及 `assets/minecraft_hud/UNIFONT_LICENSE.txt`：编译字体采用 SIL OFL 1.1 和 GPL（带字体嵌入例外），具体适用条款以该授权全文为准。字体未修改。

## Endfield 游戏公告页

- 更新日志使用游戏 `WebviewConfig/BulletinConfig.bin` 中 `targets.game.entry` 指向的官方公告页静态资源。版权归 HYPERGRYPH；保留原脚本版权头，不将它们纳入本项目原创代码许可。
- `rm_client/ui/endfield/changelog/assets/PROVENANCE.json` 记录官方资源 URL、原始 SHA-256 和本地适配后的 SHA-256。适配限于资源地址、日志数据接口与终端标签文案；布局、组件和 CSS 动画沿用原页。
- HarmonyOS Sans 的四个 WOFF2 字体逐字节取自本机游戏 `sdkresources/font`，未修改。该本地资源包不依赖游戏运行、登录态或账号凭据。

## RoboMaster 学生客户端 UI 参考

- 学生客户端语言包中的界面标题和字段说明用于核对受伤害、结算、补弹、飞镖、性能点等展示项；未复制完整语言包、Unity 资源、登录实现或通信代码。
- 16px 增益图标及新版 32px 功能性 Mod 物品图标由本项目绘制，不是 Minecraft 药水、原版装备的直接更名或 DJI 原图。
- 背包不显示人物；此前原创机甲立绘与未完成的 YSM 角色工作已移除。

## rm-native-viewer

- `PDL1` 遥测字段和固定 300 字节 `0x0310` H.264 分块行为参考 <https://github.com/dkjsiogu/rm-native-viewer>。
- 本项目只实现 Python 侧的边界检查与状态映射，不嵌入其 Rust/Slint 运行时，也未复制临时检查用的仓库快照。
- 检查到的上游快照根目录未包含明确的 `LICENSE` 文件；若后续复制上游源码或分发其二进制，必须先单独完成授权审查。

## ITL Hero Shoot

- Hero 吊射的 yaw/pitch 标定、炮口出口随 pitch 移动和重定位失效约束参考 RoboMaster 社区文章 <https://bbs.robomaster.com/article/1883342?source=11> 及其示例仓库 <https://github.com/qwq9966qwq/ITL_Hero_Shoot>。
- 本项目重新实现为无自动发射输出的 fail-closed 决策预览；未把参考项目的仿真结果声明为真车或比赛认证。

## FFmpeg

- Windows x64 便携候选包外置携带未修改的 Gyan.dev FFmpeg full build；该构建为 GPLv3。
- 固定版本为 `2026-01-29-git-c898ddb8fe-full_build`，固定 SHA-256 为 `79BDD4C65ADC74D4CA937B6A9D939349806D6C66C8A42C848B0E866BCBDF4EB7`。
- 对应上游源码提交为 <https://github.com/FFmpeg/FFmpeg/commit/c898ddb8fe>。完整 GPLv3 文本、构建参数、来源与对应源码说明随便携包放在 `licenses/`。
- 发布脚本只从显式参数复制经哈希校验的本地二进制；程序和清单均不记录开发机绝对路径。
