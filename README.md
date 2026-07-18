# POLAR-RM 自定义客户端

> 液态玻璃、Dynamic Island、页面过渡和高刷新动画的实现必须遵循
> [《POLAR-RM 液态玻璃与灵动动画规范》](README_液态玻璃与灵动动画规范.md)。
>
> 弹丸、补血、复活和空中支援的规则与正式请求边界见
> [《POLAR-RM 经济操作与裁判链路》](README_经济操作与裁判链路.md)。

这是一个使用 Python 编写的 RoboMaster 2026 自定义客户端。当前版本基于 PySide6/QPainter 渲染，提供 POLAR 风格 ClickGUI 结构：同一套 RM 模块注册表、四种 GUI 模式、共享设置系统、进入 HUD 后启用摄像头图传、POLAR 风格覆盖层、按键绑定捕获、本地配置文件，以及 MQTT/UDP/串口等通信接口预留。

## 运行

```powershell
cd rm_custom_client
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

`requirements.txt` 只装 **Python 包**（PySide6、OpenCV、OpenVINO、numpy、MQTT/串口等）。

击杀特效（GD656 图/音）和同济 Local 检测权重（`yolov5.xml/.bin`）**已随本仓库资源目录提供**，不是 pip 包，无需再从 GitHub 用 pip 安装。完整同济 C++ 自瞄工程见 [TongjiSuperPower/sp_vision_25](https://github.com/TongjiSuperPower/sp_vision_25)，仅在真机/UDP 外挂时另 clone 编译。详情见 `requirements.txt` 注释与 `THIRD_PARTY_NOTICES.md`。

启动后会依次选择运行场景、比赛制式和机器人配置，然后进入图传/HUD 主界面。启动选择页默认使用德克萨斯视频壁纸和鼠标视差；摄像头会延迟到进入主 HUD 后才打开，避免启动页直接显示真实摄像头画面。

## 启动壁纸

启动页底部点击 `Wallpaper` 可以直接打开液态玻璃壁纸库，不需要先进入 ClickGUI。客户端内置以下壁纸：

- `TexasMP4`：默认德克萨斯视频壁纸。
- `VendingMachine4K`：Vending Machine Girl 视频壁纸。
- `Default3000925581Pkg`：Wallpaper Engine 场景兼容模式。
- `ParticleGrid`：视频不可用时的交互粒子网格。

壁纸库支持导入 `mp4 / webm / mov / avi / mkv / gif / png / jpg`。导入文件会复制到 `assets/wallpapers/user/`，当前选择会随 config 自动保存；用户壁纸可以删除，内置壁纸不会被删除。

`StartupVisual -> Motion Quality` 控制启动页运动质量：

- `Smooth60`：默认模式，界面、鼠标视差和玻璃插值按 60 FPS 更新。
- `Balanced30`：降低玻璃缓存分辨率和动画负载。
- `Source`：跟随壁纸媒体的原始帧率。

`StartupVisual -> Glass Style` 默认使用 `LiquidGlass`。镜片先组合壁纸/视频与控件轨道，再在圆角内侧执行折射和边缘色散；文字与图标保持在镜片上层。视频解码在后台线程运行，界面只消费完整发布的最新帧，不会因解码落后而积累播放延迟。

第一级选择运行场景：

- `OfficialEvent`：官方赛事网络预设，真实机器人输出默认仍保持 mock。
- `CampusSimulation`：校内模拟或 SharkDataServer 本地仿真预设。
- `LabDebug`：实验室本地调试，使用摄像头或合成图传。

第二级选择比赛制式：

- `RMUC7v7`：`28m x 15m` 官方战场，默认显示基地、前哨站、经济、Buff、弹丸、热量、底盘功率和剩余比赛时间。
- `RMUL3v3`：`12m x 8m` 官方战场，默认显示控制区、胜利点、队友状态、经济、弹丸兑换、热量、底盘功率和剩余比赛时间。

协议与场景对齐说明见 `README_协议对齐与场景.md`。

## 快捷键

- `Right Shift` 或 `F8`：打开/关闭 ClickGUI。
- `F9`：切换 GUI 模式。
- 长按 `Tab`：放大 `TacticalMap`；松开 `Tab` 后回到缩略小地图。修改 `TacticalMap` 模块绑定键后，新的绑定键也会作为长按查看键。
- 启动页：`1/2/3` 选择运行场景，然后 `1/2` 选择 `RMUC7v7/RMUL3v3`；`Backspace` 返回场景选择。
- `B`：打开/关闭独立经济工作区；`ProjectileShop` 绑定键直接进入弹丸页。
- 经济工作区：滚轮/方向键浏览，`Enter` 确认，远程弹丸、补血、复活和支援需长按 600ms，`Esc` 取消或关闭。
- 左键点击模块：根据当前 GUI 模式选择模块或切换模块开关。
- 右键点击模块：在内嵌式 GUI 中展开/折叠设置。
- 模块右侧 `KEY`/`K` 按钮或 `Keybind` 设置行：打开 POLAR 风格按键绑定覆盖层。
- 按键绑定覆盖层中按任意键即可绑定；按 `ESC` 清空绑定。
- `PolarOld` 模式中，左键拖动分类标题可移动面板，右键点击分类标题可展开/折叠。

## 已实现 GUI 模式

- `PolarOld`：横向可拖拽分类小面板，右键展开，模块内嵌设置，模块高度带动画。
- `PolarPanel`：居中 `600x400` 主面板，80 alpha 遮罩，`0.98 -> 1.0` 打开缩放，左侧模块列表，右侧设置面板，分类图标栏，搜索栏，Profile/Scale 文本，Toast 和 KeybindOverlay。
- `PolarNew`：顶部分类列，`120px` 分类面板，深色圆角面板，滚动、tooltip 和可展开设置。
- `PolarDropdown`：下拉式分类面板，启用行带强调渐变，包含滑条、开关、模式控件和按键绑定入口。

四种模式都操作同一套 RM 模块与设置，不会拆成互相独立的界面。

## HUD 模式

`HUD` 模块的 `Right Display` 设置可以选择以下右侧显示模式。`TacticalMap` 当前作为独立左上 HUD 绘制在 `POLAR-RM` 水印下方，因此右侧可以保持 `ModuleListHud`，不会互相遮挡。

- `ModuleListHud`
- `TacticalMapHud`
- `KeyBindsHud`
- `RobotListHud`
- `TargetHud`
- `StatusCardsHud`
- `RMIndicatorsHud`

右侧条目按右对齐绘制，并带有 POLAR 风格滑入、淡入和宽高动画。

## 官方地图小地图

`TacticalMap` 使用从本地官方规则 PDF 提取的地图位图资源：

- `assets/maps/rmuc_7v7_official.png`：RMUC 7v7 官方场地模块图。
- `assets/maps/rmul_3v3_official.png`：RMUL 3v3 官方场地图/尺寸图。

地图底图只做等比缩放和暗化处理，方便叠加信息；不会修改官方地图结构。机器人点位、雷达脉冲、地图标点和区域高亮都通过米制坐标转换后绘制：

- 7v7 坐标尺寸：`28m x 15m`。
- 3v3 坐标尺寸：`12m x 8m`。
- `MatchMode -> Alliance = Blue` 且 `TacticalMap -> Mirror Blue = ON` 时只镜像显示，不改变原始坐标数据。

`ModuleListHud` 还提供 `HUD -> ModuleList Style`：

- `PolarLegacy`
- `RainbowRight`
- `GlowRows`
- `Segmented`
- `DynamicIsland`
- `KeyBindsRows`
- `StatusBars`
- `RobotCards`

## 配置文件

客户端配置保存在 `configs/` 目录，默认配置为 `configs/default.json`。配置会保存模块开关、按键绑定、设置值、GUI 模式、HUD 模式、比赛场景、7v7/3v3 模式、小地图设置、UI 缩放和面板展开/位置。

`ConfigManager` 模块提供这些入口：

- `Profile`：选择当前配置文件。
- `Auto Save`：默认开启，修改模块或设置后自动保存。
- `Load On Start`：默认开启，启动时加载当前配置。
- `Save Current`：立即保存当前界面配置。
- `Reload Profile`：重新读取当前配置。
- `Import Config`：打开文件选择器，把外部 `.json` 配置复制进 `configs/` 并加入 Profile 列表。

配置加载顺序是：默认模块注册表 -> 当前场景/比赛模式默认值 -> 用户配置覆盖 -> 运行时连接参数同步。坏字段会被跳过，不会让客户端无法启动。

## UI 缩放

不同尺寸显示器可以通过 `UIScale` 模块调整：

- `Auto Scale`：根据当前窗口尺寸自动缩放。
- `HUD Scale`：控制水印和 HUD 覆盖层大小。
- `GUI Scale`：控制 ClickGUI 大小。
- `Animation Speed`：控制主要 UI 动画速度。

大屏幕上如果 UI 显得过小，优先打开 `UIScale` 模块并调高 `HUD Scale` 或 `GUI Scale`。

## RM 模块

- `ArmorAutoAim`：打车/装甲板自瞄 UI，包含白色轮廓锁定框和预留云台输出接口。
- `EnergyAutoAim`：7v7 能量机关自瞄 UI，包含符进度显示和预留能量机关预测/输出接口。
- `SpinMode`：小陀螺底盘状态、参数和预留底盘输出接口。
- `RobotOverlay` / `RadarOverlay`：装甲板框、机器人 ID、距离、血量和雷达高亮覆盖层。
- `RobotTargetHUD`：目标血量、热量、距离和锁定状态卡片。
- `ModuleList`、`KeyBinds`、`Watermark`、`DynamicIsland`：可配置 RM HUD 覆盖层。
- RMUI 语义模块：`GimbalPower`、`PowerLimit`、`SpeedLimit`、`Capacitor`、`FrictionWheel`、`LockState`、`BuffStatus`、`ProjectileAllowance`、`JumpPTEWheelLES`。
- 比赛 HUD 语义模块：`MatchMode`、`TacticalMap`、`MatchTimer`、`BaseOutpostStatus`、`VictoryPointStatus`、`EconomyPanel`、`ProjectileShop`、`ThermalPowerPanel`、`BuffTimeline`。`EconomyPanel` 提供独立工作区，并按比赛制式、机器人、实时金币、弹量、脱战和复活状态过滤操作。

当前没有实现真实发射和真实底盘控制。所有控制输出默认都是 mock/stub。

## 接入点

- 摄像头：OpenCV 摄像头作为当前机器人图传；摄像头不可用时绘制合成场地图传。
- UDP：`UDPVideoReceiver` 按 SharkDataSever 的 8 字节包头重组图传分片。
- MQTT：`MQTTTransport` 可在代码中启用，用于订阅 SharkDataSever 主题。
- 官方自定义客户端桥：`OfficialMqttBridge` 保留 `KeyboardMouseControl` 和 `CustomControl` 发布边界，真实发布默认 mock。
- 串口：`SerialBridgeStub` 保留未来 RS232/机器人桥接边界。
- 串口帧编解码：`RefereeFrameCodec` 实现 RoboMaster 风格 `0xA5` 帧头、CRC8 头校验、`cmd_id`、载荷和 CRC16 尾校验。

## 冒烟测试

```powershell
.\.venv\Scripts\python.exe tests\smoke_test.py
```

## 模块切换与击杀音效

- `AudioFeedback` 默认开启。ClickGUI 点击或绑定键切换模块时，开启播放较亮的提示音，关闭播放较沉的提示音；配置加载、场景初始化和内部状态同步不会播放。
- `AudioFeedback -> UI Volume` 控制界面提示音音量，三个 `Preview` 操作可分别试听开启、关闭和无效操作音效。
- `EliminationFX -> Sound Enabled / Sound Volume` 独立控制 GD656 击杀音效。音频会预加载，短音效后端无法解码 OGG 时自动回退到 Qt 媒体播放器。
- LiquidBounce 点击音效来源及许可证位于 `assets/ui_sounds/`；GD656 击杀音效保持原始文件名和预设映射。
- `AudioFeedback -> Sound Theme` 可选择 `Polar Classic`：开启模块播放 `module_on.wav`，关闭播放 `module_off.wav`；也可切换其他交互音色或导入自定义音效。

## 启动页渲染

- 视频壁纸在可用的 OpenGL 上下文中作为纹理合成，鼠标视差和相邻源帧交叉淡化不再依赖 QPainter 全屏缩放。
- 视频解码和玻璃快照仍在后台线程处理；OpenGL、视频或着色器不可用时自动回退到原有 QPainter 路径。
