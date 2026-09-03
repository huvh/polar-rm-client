# 模块 ↔ 后端实现 对照（通俗版，脚本生成）

> 生成命令：`python tools/module_backend_map.py`（本文件即其输出，改代码后重跑即可）
> 
> **怎么读**：一行 = 一个模块。`附近出现的段字段`=模块名附近 8 行内数到的段字段（**弱证据，只用来指路**，见第 4 节）
> `其它通路`=官方裁判 / MQTT / 本地视觉 / 串口这几条非段通路；`上行`=它会不会往车里发东西；`主要落点`=可直接点开核对的文件
> 整行数据列全空 = 这个模块后端其实没人喂数据

## 0. 先弄清楚：客户端的数据一共从哪几条路进来

| 通路 | 是什么 | 谁能给 | 缺了会怎样 |
|---|---|---|---|
| **队内 0x5A 下行** | 咱们自己电控板通过 USB 线/图传吐出的 15 个自定义段 | 队内 StandardRobot++ 固件（`usb_task.c`） | 依赖它的模块只能靠官方数据或干脆空着 |
| **官方裁判协议** | 裁判系统发给机器人的标准报文（血量、比分、伤害、增益…） | 赛场裁判系统 + `backend/protocol.py` | 战况类模块全瞎 |
| **MQTT / 图传** | 官方云端那套（PRM1） | `backend/mqtt_backend.py` | 远程指挥类模块不可用 |
| **本地视觉** | 同济视觉 / NUC 那一路识别结果 | `backend/video_backend.py` | 视觉自瞄退化成只看血量 |
| **上行（客户端发出去）** | 0x01 控制指令、0x02 调参、0x03 虚拟遥控器键位、0x04 底盘自转与云台直控 | 只有插了 USB 线（或走通图传）才到得了车 | 只能看不能开 |

## 1. 59 个模块逐个对照

列说明：**证据计数**是在模块名出现位置上下各 8 行的代码里数出来的字段/关键字出现次数，
不是官方结论，但每条都附了出处，点进去就能核对。`—` 表示该模块在这条通路上没有证据。


### 分类 Combat（7 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **ArmorAutoAim** | 开 | 7 | — | 本地视觉(同济)x4、MQTT/图传x1 | — | `rm_client/ui/polar/renderers/esp_wireframe.py`、`rm_client/ui/polar_app.py` |
| **EnergyAutoAim** | 关 | 7 | — | 本地视觉(同济)x4、官方裁判协议x1 | — | `rm_client/app.py`、`rm_client/backend/readiness.py` |
| **ArmorLock** | 关 | 3 | — | — | — | `rm_client/ui/minecraft_hud.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **HeroLob** | 关 | 26 | — | 官方裁判协议x2 | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/ui/polar/mixins/config_actions_mixin.py` |
| **FireControlStub** | 关 | 3 | — | — | — | （只在注册表里出现，**没有消费端**） |
| **FrictionWheel** | 关 | 3 | — | — | — | `rm_client/ui/polar/renderers/module_list.py`、`rm_client/ui/minecraft_hud.py` |
| **LockState** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/esp_wireframe.py`、`rm_client/ui/polar/renderers/module_list.py` |

### 分类 Movement（4 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **SpinMode** | 开 | 4 | — | 官方裁判协议x3、MQTT/图传x1、本地视觉(同济)x1 | — | `rm_client/auto_spin.py`、`rm_client/ui/polar/mixins/config_actions_mixin.py` |
| **AutoSpinOnHit** | 关 | 8 | — | — | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **ChassisAssist** | 关 | 3 | — | — | — | `rm_client/control.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **PowerGuard** | 关 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/module_list.py` |

### 分类 Vision（6 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **CameraFeed** | 开 | 5 | — | 本地视觉(同济)x6、MQTT/图传x1 | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/app.py` |
| **TongjiVisionBridge** | 开 | 9 | — | 本地视觉(同济)x5、MQTT/图传x2、官方裁判协议x1 | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/ui/polar_app.py` |
| **CameraCalibration** | 开 | 7 | — | — | — | `rm_client/ui/polar/mixins/config_actions_mixin.py` |
| **Armor3DESP** | 开 | 8 | — | — | — | `rm_client/ui/polar/renderers/esp_wireframe.py`、`rm_client/config_store.py` |
| **RobotOverlay** | 开 | 12 | — | 本地视觉(同济)x2 | — | `rm_client/ui/polar/renderers/esp_wireframe.py`、`rm_client/app.py` |
| **RadarOverlay** | 关 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/module_list.py` |

### 分类 Strategy（12 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **MapMarker** | 关 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/esp_wireframe.py` |
| **TacticalMap** | 开 | 10 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/minecraft_hud.py` |
| **SentinelCommand** | 关 | 2 | — | — | — | （只在注册表里出现，**没有消费端**） |
| **AirSupport** | 关 | 2 | — | — | — | （只在注册表里出现，**没有消费端**） |
| **MatchTimer** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar_app.py` |
| **BaseOutpostStatus** | 开 | 4 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py` |
| **VictoryPointStatus** | 关 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py` |
| **EconomyPanel** | 开 | 5 | — | MQTT/图传x6、官方裁判协议x1、本地视觉(同济)x1 | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/scenarios.py` |
| **ProjectileShop** | 开 | 3 | 0x08 裁判警告 RefereeWarning x12、0x0A 本体状态 RobotStatus（热量/电容/转速） x6 | MQTT/图传x6、官方裁判协议x1、本地视觉(同济)x1 | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/scenarios.py` |
| **MatchChat** | 开 | 4 | — | 官方裁判协议x4、本地视觉(同济)x4 | — | `rm_client/ui/polar_app.py`、`rm_client/ui/polar/mixins/video_backend_mixin.py` |
| **BuffStatus** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/module_list.py` |
| **ProjectileAllowance** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py` |

### 分类 System（15 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **Scenario** | 开 | 5 | — | MQTT/图传x6 | — | `rm_client/scenarios.py`、`rm_client/ui/polar/renderers/startup_scene.py` |
| **StartupVisual** | 开 | 10 | — | — | — | `rm_client/ui/polar/renderers/startup_scene.py`、`rm_client/ui/polar/mixins/persistence_mixin.py` |
| **MatchMode** | 开 | 3 | — | MQTT/图传x2 | — | `rm_client/config_store.py`、`rm_client/ui/polar/mixins/persistence_mixin.py` |
| **RobotProfile** | 开 | 6 | 0x0A 本体状态 RobotStatus（热量/电容/转速） x5、0x08 裁判警告 RefereeWarning x4 | 官方裁判协议x1 | — | `rm_client/robot_profiles.py`、`rm_client/ui/polar/mixins/persistence_mixin.py` |
| **AllianceProfile** | 开 | 2 | — | MQTT/图传x1 | — | `rm_client/config_store.py`、`rm_client/ui/polar/renderers/tactical_map.py` |
| **ConfigManager** | 开 | 6 | — | — | — | `rm_client/ui/polar/mixins/persistence_mixin.py`、`rm_client/ui/polar/mixins/input_dispatch_mixin.py` |
| **EmergencyStop** | 开 | 2 | — | — | — | （只在注册表里出现，**没有消费端**） |
| **MatchReadiness** | 开 | 1 | — | — | — | （只在注册表里出现，**没有消费端**） |
| **AudioFeedback** | 开 | 13 | — | — | — | `rm_client/ui/polar/mixins/config_actions_mixin.py`、`rm_client/ui/polar/mixins/persistence_mixin.py` |
| **QuickActionWheel** | 开 | 14 | — | — | — | `rm_client/ui/polar_app.py`、`rm_client/ui/polar/mixins/input_dispatch_mixin.py` |
| **MQTTLink** | 关 | 3 | — | — | — | `rm_client/scenarios.py` |
| **UDPVideo** | 关 | 3 | — | — | — | `rm_client/scenarios.py` |
| **SerialBridge** | 关 | 3 | — | 官方裁判协议x3、MQTT/图传x3、本地视觉(同济)x3 | — | `rm_client/scenarios.py` |
| **RobotLink** | 关 | 29 | — | 官方裁判协议x1、MQTT/图传x1、本地视觉(同济)x1 | — | `rm_client/backend/manager.py`、`rm_client/backend/polar_transport.py` |
| **JumpPTEWheelLES** | 开 | 4 | — | — | — | （只在注册表里出现，**没有消费端**） |

### 分类 Render（15 个）

| 模块 | 开关 | 设置项 | 附近出现的段字段（弱证据） | 其它通路 | 上行 | 主要落点 |
|---|---|---:|---|---|---|---|
| **EliminationFX** | 开 | 28 | — | 本地视觉(同济)x4、官方裁判协议x1、MQTT/图传x1 | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/config_store.py` |
| **LiquidTacticalMap** | 开 | 5 | — | — | — | `rm_client/ui/polar_app.py` |
| **ThermalPowerPanel** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py` |
| **BuffTimeline** | 开 | 3 | 0x0A 本体状态 RobotStatus（热量/电容/转速） x3 | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar_app.py` |
| **HUD** | 开 | 23 | 0x0D 增益 Buff x6、0x0A 本体状态 RobotStatus（热量/电容/转速） x5 | 本地视觉(同济)x10、官方裁判协议x5 | — | `rm_client/ui/polar_app.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **UIScale** | 开 | 8 | — | — | — | `rm_client/ui/polar/mixins/persistence_mixin.py`、`rm_client/ui/polar_app.py` |
| **Crosshair** | 开 | 3 | — | — | — | `rm_client/ui/polar_app.py`、`rm_client/app.py` |
| **CombatTargetHUD** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/combat_target_hud.py` |
| **MinecraftCombatHUD** | 关 | 11 | — | — | — | `rm_client/ui/polar/mixins/video_backend_mixin.py`、`rm_client/ui/polar/mixins/config_actions_mixin.py` |
| **ChassisGimbalIndicator** | 开 | 5 | — | — | — | `rm_client/ui/polar_app.py` |
| **ClickGui** | 关 | 5 | — | 本地视觉(同济)x2、官方裁判协议x1 | — | `rm_client/ui/polar_app.py`、`rm_client/ui/jello_clickgui.py` |
| **GimbalPower** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/module_list.py` |
| **PowerLimit** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **SpeedLimit** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/module_list.py` |
| **Capacitor** | 开 | 3 | — | — | — | `rm_client/ui/polar/renderers/tactical_map.py`、`rm_client/ui/polar/renderers/module_list.py` |

## 2. 真·没有后端的模块

下面这些模块的名字**只出现在注册表**（rm_client/model.py 的 build_default_registry()）里，
全仓没有任何实现读它 —— 界面上能勾、能存盘，但什么都不会发生。

| 模块 | 分类 | 设置项数 | 建议 |
|---|---|---:|---|
| **EmergencyStop** | System | 2 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |
| **MatchReadiness** | System | 1 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |
| **FireControlStub** | Combat | 3 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |
| **SentinelCommand** | Strategy | 2 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |
| **AirSupport** | Strategy | 2 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |
| **JumpPTEWheelLES** | System | 4 | 要么接上、要么从界面删掉；留着比删掉更坏：操作员会以为它在起作用 |

> 为什么这里**不列**「有 UI 落点但没数到段字段」那一档：这个客户端的数据流是
> PolarStateBridge.apply(段) 写进共享的 RobotState，渲染层再读 state.xxx，
> 而「本模块开没开」是在别处判的。名字邻近度抓不到这种跨函数数据流，所以那种空列全凭运气，
> 不作判定依据（第一版把 48 个模块全误判成「不碰机器人数据」，就是这条坑）。

## 3. 已知不准的地方（别当真到那份上）

先交代被整文件丢掉的「清单文件」（它们只列名字、不含实现）：
- ``rm_client/match_modes.py`：出现 26 个模块名，平均每 6 行就点一个（清单，不含实现）`

1. 统计窗口只有上下各 8 行、段字段要命中 >= 2 次才写表 —— 取向是「宁可少写也不要写错」，所以**空列不代表这个模块一定没读该段**，只代表附近没数到；相邻模块共用绘制代码时仍可能互相记到；
2. 通用字段名（如 `energy`、`heat`）在多个段里都有，出现次数会被各段都记一份；
3. `—` 不等于"这个模块一定没用"，只等于"在它自己那几行代码附近没找到这类关键字"；
4. 真要改某个模块，先看第 1 列模块名在 `polar_app.py` / `ui/` 里的实现，别看这张表。
## 4. 重点模块：数据到底从哪个函数进来（人写的，带行号）

第 1 节是机器数出来的，只会指路；这一节是逐条核过代码写的。要改哪个模块，先看这里。

### 开车 / 控车这条线（队内 0x5A 上行）

| 模块 | 后端实现在哪 | 说人话 |
|---|---|---|
| **RobotLink** | 编码：`backend/polar_link.py:597 encode_robot_cmd`(0x01)、`<br>:636 encode_virtual_rc`(0x03 键位图)、`<br>:678 encode_chassis_cmd`(0x04 自转+云台直控)；`<br>成帧与串口：`backend/polar_transport.py:487 / :506 / :513`；`<br>开关判定：`backend/manager.py:371` | 整条「客户端往车里发东西」的路都归它。松键时它会补发一次全零（`:513`），所以固件那边不会因为停发而冻在最后一帧 |
| **SpinMode** / **AutoSpinOnHit** | `auto_spin.py:44`（受击后限时开自转）→ 上面那个 `encode_chassis_cmd()`（上行 0x04）；状态回读是固件下行 0x1F | 以前只能借 SHIFT 键，而固件对 SHIFT 是边沿翻转 —— **关不掉**；现在是显式 ON/OFF + 回读闭环 |
| **EmergencyStop** | 行为在 `backend/safety.py`(OfficialSafety) 与 `manager.py:222 release_estop()`；但注册表里那个 `EmergencyStop` 模块**没有任何代码读它** | 急停本身是真有的，只是「界面那个模块条目」和它之间没接线 —— 界面上那个开关是装饰 |

### 看数据这条线

| 模块 | 后端实现在哪 | 说人话 |
|---|---|---|
| **HUD** / **CombatTargetHUD** / **RobotOverlay** / **RadarOverlay** / **TacticalMap** | 渲染在 `ui/polar_app.py` 与 `ui/polar/renderers/*`；数据一律读共享的 `RobotState`，由 `backend/polar_bridge.py` 的 `apply(segment)` 按段号写进来 | 队内 15 个下行段和官方裁判报文**汇到同一个 RobotState**，所以这些面板不区分数据是谁给的 —— 这也是「没插 USB 线时界面照样动」的原因 |
| **BuffTimeline** | `ui/polar/renderers/tactical_map.py`（地图下方那条带）；数据是下行 0x0D Buff | 这个模块以前一个消费者都没有，现在才真有一排标签；带上的剩余秒数就是「时间轴」开关管的东西 |
| **CameraFeed** / **TongjiVisionBridge** / **Armor3DESP** | `backend/video_backend.py` + `ui/polar/mixins/video_backend_mixin.py`；3D 线框在 `renderers/esp_wireframe.py` | 走本地视觉这一路，跟队内 0x5A 无关，不插 USB 线也能用 |
| **MQTTLink** / **UDPVideo** | `backend/mqtt_backend.py` / `backend/video_backend.py` | 界面上有「自动连接 / 重组」这类开关，但**刻意没接**（接上会让官方场景自己去抢端口），理由写在 `tools/SETTINGS_GAPS.md` |
| **SerialBridge** | `backend/serial_backend.py`（官方裁判串口那一路） | 与队内 0x5A 是两条互相独立的串口链路，互不代管 |
| **HeroLob** | 26 个设置项，主要被 `ui/polar/mixins/` 引用 | 英雄投石那套界面参数；**注意**它和固件里的「英雄兵种」是两回事，固件侧不接这些参数 |

### 和这次 DT7 适配直接相关的那一条

上行 0x03 的键位图到了车上是**或**进 `rc_ctrl.key.v` 的 —— 固件那边叫 `HOST_RC_HOST_KEYS` 这本账（`tools/firmware/host_bridge/RC_LINKS.md` §3）。而比赛链路本身是「电脑 USB 插 DT7 → 无线 → 车上 DR16 → UART3 的 18 字节帧」，那个帧自带驾驶员的键位与鼠标。两者是叠加、不是互相接管：驾驶员松手或客户端掉线，各自那份账都会归零。

