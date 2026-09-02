# 模块 ↔ 后端实现对照表（通俗版）

生成日期：2026-09-03。口径：`build_default_registry()` 的 59 个模块，
消费点用 `registry.get("X")`/`_bool_on("X")` 全仓扫描得出，再人工核对。
孤儿设置项的逐项细节在 `SETTINGS_GAPS.md`，本文只回答"每个 mod 背后是谁在干活"。

## 先认清四条数据管道（"后端"其实是四套东西）

| 管道 | 代码位置 | 是什么 | 谁用它 |
|---|---|---|---|
| A. 官方裁判系统 | `backend/protocol.py` + `backend/manager.py`（解码器：GameStatus、RobotPower、Buff、Position、MapClickInfo…） | 大疆官方裁判 UDP/MQTT 报文 → `RobotState` 字段；客户端回发 CommonCommand/MapClickCmd/空中支援等 | 所有比分/血量/buff/弹药类 HUD |
| B. 队内上位机链路 | `backend/polar_protocol.json`（唯一真相源）、`polar_spec.py`、`polar_link.py`、`polar_bridge.py`、`polar_transport.py` | 你战队 Gitee（StandardRobotpp）固件的 USB/串口协议：下行 0x01 Debug / 0x02 IMU / 0x0A RobotStatus / 0x0D Buff / 0x1F ChassisState(需 host_bridge 补丁)；上行 0x01 robot_cmd / virtual_rc / chassis_cmd | RobotLink、控车三件套（WASD/小陀螺/受击自转）、真车状态显示 |
| C. 视觉链路 | `vision.py`、`backend/video_backend.py`、`backend/tongji_bridge.py`、`tongji_yolo.py` | 摄像头帧 → 装甲板检测/预测（`ArmorObservation`） | ESP、自瞄、准星热力、目标卡 |
| D. 本地纯 UI | `ui/polar/**`（渲染器 + Mixin）、`persistence_mixin.py` | 画面、布局、配置存盘 | 外观类模块 |

一句话总则：**HUD 类模块 = 管道 A/B 数据的显示面；控车类模块 = 写进管道 B 的机器人命令；外观类 = 根本没有后端。**

## Combat 战斗

| 模块 | 后端实现 | 状态 |
|---|---|---|
| `ArmorAutoAim` | 选靶在 `esp_wireframe.select_armor_by_priority`（视觉数据），FOV 闸、mock 输出门在 `manager.py:1622`；输出走管道 B 云台字段（需 RC 上档） | ✅ 真实现（mock 档不动车） |
| `EnergyAutoAim` | **无视觉管线也无发送出口**，`readiness.py` 诚实性闸门作证，故意不接 | ⛔ 按设计空转 |
| `ArmorLock` | 后端无"锁定点"实现；UI 开关+锁框外观 | ⛔ 占位 |
| `HeroLob` | 英雄吊射辅助：装填状态读自管道 A/B，按键经 `handle_control_key_event`；策略参数（Mode）无固件出口 | ◑ 显示真、策略占位 |
| `FireControlStub` | 描述自陈"不输出真实发射命令"；`fire` 在协议 spec 里标 `never_set` | ⛔ 按设计空壳 |
| `FrictionWheel` | `manager.py` 硬编 `friction_on=False`——客户端从不驱动摩擦轮 | ⛔ 无数据源无出口 |
| `LockState` | 锁定框显示在 `esp_wireframe`（真）；`Lock Source` 无实现（Radar 要地图→像素投影，Manual 无手选子系统） | ◑ 显示真、来源未接 |

## Movement 移动（真正"开车"的三家 + 两家告警）

| 模块 | 后端实现 | 状态 |
|---|---|---|
| `SpinMode` | **指令+回读闭环**：下行 0x04 `spin_cmd`、状态读 0x1F `spin_state`（固件需 `tools/firmware/host_bridge/` 补丁）；未打补丁降级为"指令已发、无法确认"，不假装成功。旧 SHIFT 边沿翻转已废 | ✅ 实车可用（仿真已验） |
| `AutoSpinOnHit` | 受击事件（管道 A `PostHP` + 管道 B `0x0A`）→ `desired spin`，与 `SpinMode` 同一条 0x04/0x1F 闭环 | ✅ 已对齐受击自转 |
| `ChassisAssist` | WASD/鼠标 → `control.py:build_command` → 管道 B 上行 robot_cmd(0x01)/virtual_rc；`Power Limit` 项真读；`Buffer Protect` 无实现 | ◑ 开车真、缓冲保护未做 |
| `PowerGuard` | 两个告警阈值已接（读管道 B `0x0A` power_limit/heat）；`Auto Limit` 自动限功率=新增控车行为，未授权不做 | ◑ 告警真、限功率未做 |
| `JumpPTEWheelLES` | 全仓零消费点——跳跃/PTE/轮环/抗退后在队内链路没有对应命令段 | ⛔ 纯占位 |

## Vision 视觉（全部吃管道 C）

| 模块 | 后端实现 | 状态 |
|---|---|---|
| `CameraFeed` | `video_backend_mixin` → `video_backend.py`（UDP 拉流/解码，`UDPVideo` 给地址） | ✅ 真 |
| `TongjiVisionBridge` | `tongji_bridge.py`/`tongji_yolo.py`：同济 Tracker 协议，四点装甲+多装甲重投影 | ✅ 真（其 2 项孤儿是本地模型档） |
| `CameraCalibration` | 标定参数进 `vision.py`；未标定时画面有 `UNCALIBRATED` 诊断、预测盘被闸 | ✅ 真 |
| `Armor3DESP` | `esp_wireframe.draw_armor_3d_esp`：观测/预测线框、渲染后端切换（GPU/CPU） | ✅ 真 |
| `RobotOverlay` | 同上渲染族；`Color/Distance/Robot ID/Armor Boxes/3D Depth/Max Targets/Only Secondary/Predict Plates` 全部有真实读取点（第 17/20 批接线） | ✅ 整模块清零孤儿 |
| `RadarOverlay` | 雷达标记唯一消费者 `tactical_map.draw_radar_overlay`；数据源=裁判 `RadarInfoToClient` → `state.radar_detections`（manager.py:1223）；`Map` 第 21 批已接（默认 Both=旧画面） | ✅ 整模块清零孤儿 |

## Strategy 战略（数据吃管道 A，指令回发裁判）

| 模块 | 后端实现 | 状态 |
|---|---|---|
| `TacticalMap` | 面板几何/外观（`tactical_map.py`）+ 场地布局来自 `match_modes.py`；地图点击编 `MapClickCmd` | ✅ 真 |
| `LiquidTacticalMap` | 液态玻璃地图外观分支（`draw_liquid_tactical_map_hud`），同一份数据 | ✅ 纯外观（真） |
| `MapMarker` | 点击→`protocol.py encode_map_click*`（真实报文 `MapClickCmd`）+ 裁判侧 10Hz 限流；`Repeat` 需新增外发流量，待授权 | ◑ 发送真、重复广播未做 |
| `MatchTimer` | GameStatus 解码 `stage_remain_time`/`sync_time_stamp` | ✅ 真显示 |
| `BaseOutpostStatus` | GameStatus 的己方/敌方哨兵基地血量与状态字段（fields 4/5/9/10） | ✅ 真显示 |
| `VictoryPointStatus` | 裁判比分/进度报文 | ✅ 真显示 |
| `EconomyPanel` | `remaining_economy` 解码 + 0x0202 第4字段（雷达等级/加密等级之争，等你们对协议版本）；购买出口在 `economy.py` | ◑ 数据真、2 项等确认 |
| `ProjectileShop` | 弹速/伤害/剩余弹（PowerHeat、`remaining_ammo`）→ `economy.py` 编 `CommonCommand` 发裁判 | ✅ 真（买得起发得出） |
| `MatchChat` | 快捷消息/指挥 → 管道 A 聊天报文 | ✅ 真 |
| `SentinelCommand` | 官方有 `SentryCtrlCommand` 编解码，但**客户端零调用者**；队内链路无此管道 | ⛔ B 类：建议要么接哨兵兵链路再做，要么删开关 |
| `AirSupport` | 模块自己的发送零调用；**真出口其实在 `economy.py`**（经济面板购买流会发 `encode_air_support_command`）。模块级重复发送口建议删 | ⛔ B 类：功能有、这个口是摆设 |

## Render 渲染（多数是外观，数据源都在 A/B）

| 模块 | 后端实现 | 状态 |
|---|---|---|
| `EliminationFX` | 28 项全接：击杀事件（管道 A 报文）→ 提示音/荣誉徽章/加分标签，`config_actions` + 渲染族 | ✅ 全清 |
| `HUD` | 全局布局/密度/透明度，纯客户端 | ✅ 外观真 |
| `UIScale` | 缩放系数进渲染层 | ✅ 外观真 |
| `Crosshair` | `combat_target_hud.py`/`esp_wireframe.draw_crosshair`（第 17 批样式全接） | ✅ |
| `CombatTargetHUD` | 目标信息卡：视觉 + HP 数据 → `combat_target_hud.py` | ✅ |
| `MinecraftCombatHUD` | MC 排版合成（`ui/minecraft_hud.py`），复用同一份 state | ✅ |
| `ChassisGimbalIndicator` | 云台/底盘姿态箭头：管道 B `0x02 IMU`（yaw/pitch/roll）| ✅ |
| `ClickGui` | 设置界面本体（`jello_clickgui.py`）；`Save Layout` 全仓无此函数，假按钮 | ◑ 界面真、该按钮假 |
| `GimbalPower` | 云台电压：管道 B `0x0A RobotStatus` 电压字段（更正过"无数据源"误判） | ✅ |
| `PowerLimit` | 功率限制条：`chassis_power_limit`（0x0A）+ 管道 A PowerHeat | ✅ |
| `SpeedLimit` | 速度限制显示 | ✅ |
| `Capacitor` | 缓冲能量/底盘能量：`current/max_buffer_energy`（第 9 批并修了读 mock 字段的既有 bug） | ✅ 整模块清零 |
| `ThermalPowerPanel` | 热量/枪管冷却：`barrel_cooling/heat_limit` | ✅ |
| `BuffStatus` | 增益灯：`buff_indicator_state()` 映射，`RM 指示灯` 三个灯（第 10 批） | ✅ 整模块清零 |
| `BuffTimeline` | 第 19 批新建的面板消费者：裁判增益报文（带名字+剩余秒）→ 地图下方标签带 | ✅ 整模块清零 |
| `Scenario` | 不是场景"剧本"：切连接方式包（把官方/校园/实验室的地址端口写进 MQTTLink/UDPVideo/SerialBridge，`scenarios.py:134`） | ✅ 真 |
| `StartupVisual` | 启动动画（`startup_scene.py`），无后端 | ✅ 外观真 |
| `MatchMode` | 场地/时长/模块默认启停的真相源 `match_modes.py` | ✅ 真 |
| `RobotProfile` | 本机 robot_id → `manager.py:1810`：血量/增益"是不是我的"就靠它 | ✅ 真 |
| `AllianceProfile` | 阵营 → 地图镜像（`map_point` 蓝方翻转）| ✅ 真 |
| `ConfigManager` | 配置导入导出/存盘（`persistence_mixin.py`） | ✅ 真 |
| `EmergencyStop` | 真刹车：`polar_app.py:763/3198/3221` 调 `control.release_all` 松全部键位发零帧；其 2 个设置项是孤儿（显示文案类） | ✅ 功能真 |
| `MatchReadiness` | `readiness.py` 诚实闸门：所有 required 门才允许点亮"比赛就绪"，防止把 mock 桌面跑当成能上场 | ✅ 真（防事故设计） |
| `MQTTLink` | 连接参数 → `mqtt_backend.py` 真连接；`Auto Connect` 故意不接（接上会让新默认配置收不到裁判数据） | ◑ 连接真、1 项故意不接 |
| `UDPVideo` | 地址端口 → `video_backend.py` 收流；`Reassemble` 不接因后端本就交付整帧 | ◑ 同上 |
| `SerialBridge` | 串口参数 → `serial_backend.py`；`Mock Writes` 由场景写入 | ◑ 真 |
| `RobotLink` | **队内链路总闸**：29 项（端口/波特率/Send Hz/Allow Drive/Drive Channel/改绑…）由 `manager.py:371` + `polar_link/polar_bridge` 消费；场景与模块设置冲突时有优先级约定（场景赢，Port/Baud 两项等你们拍板） | ✅ 真 |

## 汇总口径

- 真控车（能动车）的模块只有 5 个：`ChassisAssist`、`SpinMode`、`AutoSpinOnHit`、`RobotLink`（闸）、`EmergencyStop`（停）。
- 其余全是"读数据 → 画画面"或纯外观；`fire` 字段在协议层被标 `never_set`，客户端没有任何发射出口。
- 空转/占位（有名字没后端）：`EnergyAutoAim`、`ArmorLock`、`FireControlStub`、`FrictionWheel`、`JumpPTEWheelLES`、`SentinelCommand`、`AirSupport`（模块口）。
- 孤儿设置全量现状：**22**，逐项处置在 `SETTINGS_GAPS.md`（7 刻意不做 / 5 需授权控车 / 4 新功能 / 2 等语义 / 2 等协议事实 / 1 无数据 / 4 B 类建议，数字以审计实测为准）。
