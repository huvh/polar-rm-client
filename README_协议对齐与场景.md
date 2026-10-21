# POLAR-RM 协议对齐与场景

## 官方 12.0.0.213：显式选择 V2，不迁移旧配置

本轮静态核验的学生端 **12.0.0.213** 内嵌 MQTT descriptor 对应
`rm2026-v2.0.0`。官方赛事引擎 **12.0.0.137** 是同一官方下载页的 V2 后续版本，
不是 MQTT schema 拥有者；端到端配对和真实硬件行为仍未验证。
来源为[官方下载页](https://bbs.robomaster.com/wiki/20204847/804784?source=7)和
[通信协议页](https://bbs.robomaster.com/wiki/20204847/811363?source=7)。
其他版本保持“未验证”，不按版本号大小猜测或回退。

`DEFAULT_PROFILE = rm2026-v1.3.1` 继续作为既有协议身份保留，旧 `default` 和用户配置
不自动改写。`OfficialEvent` 只选择场景/网络策略，**不会自动把 V1 换成 V2**。
“官方场景”或“MQTT 已连接”不是 schema 匹配证明。

### 新用户安全暂存预设

通过 `ConfigManager -> Import Config` 显式导入
`configs/official_213_v2_safe.json`；新构建便携包中为 `defaults/official_213_v2_safe.json`。
发布脚本仅提供带 SHA-256 清单的独立模板，不自动复制到用户配置或替用户选择。
导入使用既有校验/停止旧后端/异步重建路径，形成独立配置，不覆盖 `default`。

它选择 V2，但刻意留在 **LabDebug / 本地回环 / Synthetic 视频**。
RobotLink、角度转发、DT7/CC、无线键鼠、自瞄和小陀螺真实出口关闭，串口 Stub，经济 mock，
Auto Save / Load On Start / Auto Connect 关闭。不替你选择机器人、不生成资格、不 Arm。
模块开关不是网络防火墙，后端仍由场景生命周期管理；这个暂存预设绝非实链已打通。

纯离线检查命令只读 JSON，不连接网络、枚举设备或更改配置：

```powershell
python tools/check_official_profile.py --config configs/official_213_v2_safe.json --client-version 12.0.0.213 --engine-version 12.0.0.137
```

`--config` 也可指向实际 `user_data/configs/<你的配置>.json`。
返回码 0 仅表示已审阅客户端 schema 与所选 profile 匹配；2 是配置错误/不支持或明确不匹配；
3 是版本未验证/配置没有显式 profile。输出始终保留 `pairing_verified=false` 和
`hardware_qualified=false`。`engine_status=REVIEWED_V2_SUCCESSOR_NOT_PAIR_VALIDATED`
不是引擎拥有同一 MQTT schema 的断言。

### 真实官方联调需要操作员显式完成

1. 保持控制 `LOCKED`、停止旧会话，确认设备安全。核对真实官方客户端版本，再确认
   `MQTTLink -> Referee Profile` 完整值为 `rm2026-v2.0.0`。旧 V1 配置先保留，使用独立配置。
2. 显式选择 `OfficialEvent`，按真实比赛选择制式、红蓝方、角色与机器人编号。
   MQTT ClientId 必须与官方端同一机器人，使用 `1–9` 或 `101–109`，不是选手端 ID。
   核对 `MQTTLink -> Host/Port`，官方默认 `192.168.12.1:3333`，仿真需填写该实例真实地址。
   本配置不会安装驱动或修改操作系统网络。
3. 初次连接只观察，不点击键鼠、经济、部署或模式切换等主动上行，继续 `LOCKED` 并关闭
   设备出口。**切换 OfficialEvent 会重新应用经济 live 默认**，如需 mock 演练，须再次显式
   将 `EconomyPanel -> Mock Requests` 和 `ProjectileShop -> Mock Request` 设为 ON，不能假定
   暂存 mock 永久生效。核对诊断中的活动 `referee_profile` / `protocol_version`、订阅成功、
   真实且新鲜的比赛阶段与机器人状态；本地 mock 或单纯连接成功不是正式回读。
4. 使用官方转发视频时，须先让官方端同一机器人正常显示视频，再按自定义客户端指南确认
   外发。`UDPVideo` 的 `3334` 与 `CameraFeed -> UDP HEVC` 只对应已支持转发入口。
   RC150 USB 接收的 Windows factory/UI **尚未实现**；不能把软件骨架或描述符识别当作独立图传打通。
5. 真正需要输出时，在有人监管的安全台架/场地通过 `MatchReadiness` 创建本次资格会话，
   完成当前构建、profile、机器人和固件绑定的适用验证：实际视频/键鼠回读、急停、固件失联归零、
   丢链恢复与持续运行；角色专用能力另验并双人签字。只有 readiness 允许、证据未过期，才由
   操作员执行 `Arm Match Control`。不支持的能力继续关闭，证据不足保持 `NOT READY`，不得绕门禁。
   断连或修改身份/profile 不得恢复旧授权，需重新核查并人工 Arm。

预设、离线诊断和静态匹配都不是现场资格。详见 [实战就绪性](BACKEND_MATCH_READINESS.md)。
下表仅保留 V1.3.1 历史契约，不是 213/V2 的完整主题/字段清单；运行时以显式 profile 为准。

## 官方链路（V1.3.1）

| 链路 | 参数 | 本地实现 |
| --- | --- | --- |
| 裁判 MQTT | `192.168.12.1:3333`，客户端 `192.168.12.2` | `RmMqttBackend` |
| UDP 图传 | `:3334`，HEVC | `RmVideoBackend` + 常驻 ffmpeg |
| KeyboardMouseControl | 上行 75 Hz，QoS1 | `KeyboardControlBridge -> BackendManager.publish_keyboard_mouse` |
| CustomControl / 0x0311 | 图传链路上行 75 Hz，最多 30 bytes | MQTT `CustomControl`；115200 串口强制拒绝 |
| CustomByteBlock / 0x0310 | 图传链路下行，最多 300 bytes | Native H.264/遥测复用解码 |
| 事件命令 | 上行 10 Hz | `OfficialSafety` 分 topic 限频 |

`MapClickInfo` 为下行，`MapClickCmd` 为上行。旧的 `MapClickInfoNotify` 不再发布。`sentry_control` 为 0=自动、1=半自动。

## 键鼠与控制

官方 keyboard bit 0..15 依次为 `W,S,A,D,Shift,Ctrl,Q,E,R,F,G,Z,X,C,V,B`。鼠标 x/y/z、左/右/中键一并编码。活动输入和释放帧按 75 Hz 节奏发送，安全层在未收到正式比赛阶段、急停或非允许场景时 fail-closed。

F12 会先发布一个全零 `KeyboardMouseControl`，随后锁止全部上行。解锁需要 `Ctrl+Shift+F12`，且不能替代真车急停验证。

应用正常退出也会尽力发送全零 KMC；机器人固件仍必须独立实现失联超时归零。运行时 readiness 审计结果保存在 `RobotState.backend_stats["readiness"]`，缺少现场证据时固定显示 `NOT READY FOR REAL MATCH`。

ArmorAutoAim 的真实输出使用官方 CustomControl 容器中的队内载荷：

```text
<4sBBHhhBB
magic="PRM1", version=1, kind=1, sequence,
yaw_centideg, pitch_centideg, target_id, flags
flags bit0=tracking, bit1=fire（桌面端恒为 0）
```

该格式不是官方定义的云台语义；机器人固件必须实现并现场验证后，才可关闭 `ArmorAutoAim -> Mock Output`。Hero 吊射仍只提供轨迹与标定决策辅助，不自动开火。

`SpinMode` / `AutoSpinOnHit` 使用同一容器的独立队内载荷：

```text
<4sBBHhBB
magic="PRM1", version=1, kind=2, sequence,
speed_dps, direction(0 Auto / 1 CW / 2 CCW), flags(enabled/power_guard)
```

该输出同样默认 Mock；关闭 Mock 前必须完成机器人固件解析和超时归零测试。它只经 MQTT `CustomControl` 发布，不写 115200 串口，也不含任何开火位。

## 场景

| 场景 | MQTT | UDP | 115200 串口 | 经济/键鼠 |
| --- | --- | --- | --- | --- |
| `LabDebug` | 本地、发布 Mock | 本地 | Stub | Mock |
| `CampusSimulation` | 本地可真实发布 | 本地 | Stub | 经济由场景强制 Mock；键鼠可用于仿真 |
| `OfficialEvent` | 官方地址、真实发布 | 官方 3334 | Stub（不承载 0x0311） | 正式 MQTT，受比赛阶段门控 |

启动页 Config/ClickGUI 快捷入口也会先应用所选场景，不再绕过后端初始化。默认 `RobotState.current_stage=NOT_STARTED`，在收到真实 `GameStatus` 前不会伪造“比赛中”。

## 视频与发布包

解码器按 `POLAR_FFMPEG`、`bin/ffmpeg.exe`、系统 ffmpeg、`imageio-ffmpeg` 的顺序解析。`tools/build_release.ps1` 从 Git 跟踪文件构建发布物并复制可用 ffmpeg 到 `bin/ffmpeg.exe`，同时验证核心模块、默认 JSON 和 Python 编译。

## 实战边界

当前状态仍为 **NOT READY FOR REAL MATCH**。详见 `BACKEND_MATCH_READINESS.md`；真车、正式裁判系统、正式图传和固件 schema 的现场证据不可由桌面测试替代。
