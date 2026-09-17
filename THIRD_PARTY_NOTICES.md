# 第三方实现参考

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

## Minecraft 1.21.11 HUD 资源

- Hotbar、选择框、心、护甲、饱食度、BossBar、状态背景、背包容器和 `ascii.png` 位图字体来自用户提供的本机 Minecraft 1.21.11 Fabric 客户端 JAR。
- 提取基准 JAR 的 SHA-256 为 `1473c9489ac50fda3c435049a76a70d61a10b8610db27f5ba9d8756b686cd3bd`；提交中的 23 个 Minecraft HUD 资源文件均已逐文件哈希回查为该 JAR 内的原始字节。新增 `inventory.png` 对应 `assets/minecraft/textures/gui/container/inventory.png`，SHA-256 为 `c2f850076ad7ebd7a1b27d017fe5f66ac388f54de374de988cb79f86b1d59a65`。
- 资源只用于本地 Minecraft 战斗 HUD 预设；相关商标、视觉资源和其他权利归 Mojang/Microsoft 及各自权利人所有。本项目未打包完整 Minecraft 客户端或游戏代码。
- 视觉修订另取本地 JAR 的 wide Steve 皮肤、两张 bitmap 字体表/provider 配置及九个伤害类别物品纹理；额外 14 个原始资源的哈希/来源记录在 `assets/minecraft_hud/presentation_manifest.json`。Mod 图标为项目原创的功能性像素物品，不是以上原版物品的替代名称。
- `unifont.zip` 来自本机 Minecraft asset index 29，SHA-1 为 `ccd5ac4767ce0a9c71d1dd62f2dc25449789b5dd`。其中字体版本为 GNU Unifont 17.0.01，原始授权全文保留在压缩包及 `assets/minecraft_hud/UNIFONT_LICENSE.txt`：编译字体采用 SIL OFL 1.1 和 GPL（带字体嵌入例外），具体适用条款以该授权全文为准。字体未修改。

## RoboMaster 学生客户端 UI 参考

- 学生客户端语言包中的界面标题和字段说明用于核对受伤害、结算、补弹、飞镖、性能点等展示项；未复制完整语言包、Unity 资源、登录实现或通信代码。
- 16px 增益图标及新版 32px 功能性 Mod 物品图标由本项目绘制，不是 Minecraft 药水、原版装备的直接更名或 DJI 原图。

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
