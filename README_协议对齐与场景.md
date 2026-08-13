# POLAR-RM 协议对齐与场景

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
