# 裁判系统接入与队内电控边界

## 当前结论

本轮完成年度协议隔离、MQTT 收发验证与队内源代码核对，不等于完成真车验收。
**NOT READY FOR REAL MATCH**：没有正式裁判系统、已烧录固件、图传、物理急停和双人签字证据，不能 Arm 比赛控制。
不修改液态玻璃材质、shader 或战斗 HUD，不自动配置网卡、烧录固件或连接车端。

## 核对基线

| 来源 | 本轮核对内容 / 固定版本 |
| --- | --- |
| [StandardRobot++ MCU](https://gitee.com/SMBU-POLARBEAR/StandardRobotpp) | `2722e0d2daba6113c86544d0c6d7918672669601`；15 个客户端使用的消息 ID 全匹配 |
| [standard_robot_pp_ros2](https://github.com/SMBU-PolarBear-Robotics-Team/standard_robot_pp_ros2) | `e5af8d29157977350c59cab0e698ee42080eba41`；7 个语义 ID 与 MCU 表不同，不能互换 |
| [pb_rm_interfaces](https://github.com/SMBU-PolarBear-Robotics-Team/pb_rm_interfaces) | `66c8bee0d389b0eed9e84157c26d026b95ebae4c`；README 的裁判串口基线是 V1.7.0（20241225），不是当前自定义客户端 MQTT 协议 |
| 本地 2026 通信协议 V1.3.1（20260519） | PDF SHA-256 `0197a5f97f7171dc74cd5040d4e5872afb92db44a0307e682a4efd3f2688db42`；独立字段表覆盖 25 下行、11 上行及一个嵌套结构 |
| 本地学生客户端 `12.0.0.30_3v3_Student` | IL2CPP 元数据 SHA-256 `c5a103b7049c7846b316943c65179799b514ef38a54f7ed4bc51ccc9b1722e87`；有旧 `RemoteControl`，没有当前 `KeyboardMouseControl / CustomControl / MapClickCmd` 类型 |
| 本地赛事引擎 `12.0.0.137_Student` | 私有登录/TCP 与自定义客户端 MQTT 不同；不能直接连接 RMServer 私有 TCP 来代替自定义接口 |

这是固定基线，不宣称 V1.3.1 是未来或当前官网的最新版本。学生版元数据只能证明类型存在，不替代实际服务抓包。
源代码 ID 核对也不证明结构体 ABI、已烧录版本、RC 仲裁或车真的能动。

### 必须区分的链路

- 官方自定义客户端：MQTT 指令名 topic、Protobuf；普通图传 UDP；Native `0x0310` 来自 `CustomByteBlock`。
- 官方裁判串口：`0xA5` 帧，独立的年度串口协议；`0x0311` 不通过普通 115200 裁判串口发送。
- MCU 上位机：队内 StandardRobot++ `0x5A`，沿用已对齐的 MCU ID、CRC、虚拟 RC 及回读桥。
- ROS2 驱动：虽然也是 `0x5A`，GameStatus/Event/RobotStatus/RFID/GroundPosition/JointState/RobotMotion 七个 ID 不同；不做自动混用。
- DT7/DR16：遥控器链路与客户端出口的独立配置、端口识别和资格闸门。
- PRM1：队内应用载荷，不是官方裁判消息定义；schema/固件哈希/台架证据未齐时继续 Mock。

## 使用步骤

### 正式 V1.3.1 接口

1. 在 `System → MQTTLink → Referee Profile` 选择 `rm2026-v1.3.1`。
2. 按协议设置客户端网卡 `192.168.12.2`，服务端 `192.168.12.1`；MQTT `3333`，普通图传 UDP `3334`。现场有不同配置时由操作员明确修改 Host/Port。
3. MQTT ClientId 使用机器人 ID `1–9 / 101–109`，不是选手端 `0x0103` 或随机 UUID。RobotProfile 改身份会清空输入、重建连接并锁定控制。
4. 使用已有启动流程启用后端。检查 backend stats 的 profile、协议版本、连接状态、无效包计数及阶段来源；真实比赛阶段仅由裁判数据确认。
5. 先只读观察，然后按 `FIELD_CANDIDATE.md` 跑现场资格流程。配置中的开关、收到 MATCH 或重连均不能自行 Arm。

### 本地旧学生版预览

1. 先按官方说明启动赛事引擎、学生客户端并启用其自定义客户端 MQTT 服务。
2. 显式选择 `rm2026-v1.1.0-student-readonly`；同机预览可以手动设置 `127.0.0.1:3333`，实际地址以学生客户端服务设置为准。
3. 只接收旧版 24 个下行 topic，并转换已核实的共享标量字段；兼容旧 `RaderInfoToClient / SentinelStatusSync / GuardCtrlResult` 名称。
4. 旧版非 optional 标量按完整快照处理；飞镖闸门 bool 转换为当前显示枚举。旧机器人血量/弹药数组没有规定角色顺序，保留在 `backend_stats.student_legacy_roster`，**不猜 7+7 或 5+5**。
5. 旧技术核心等未核实字段保留在 `student_legacy_fields` 供只读抓包核对，不伪造当前字段。
6. 此模式禁止全部上行、经济操作与比赛资格认证，**不把新 KMC 自动转换成旧 RemoteControl**。F12 仍锁住本地输出，但无法向旧协议服务发送新 KMC；需要物理急停。

预览模式目前通过字段合同和本机模拟 MQTT 验证；还需要学生客户端实际二进制负载抓包确认完整互通。

## 模块结构与年度维护

```text
backend/referee/
  registry.py                  显式版本、传输参数、上行白名单、限频、只读策略
  wire.py / validation.py      通用 Protobuf primitive + 有界严格验证
  rm2026/
    contract.py / codec.py     V1.3.1 字段合同、编解码
    state_adapter.py           年度字段 → 稳定 RobotState / HUD 投影
    economy_rules.py          该版本的价格与动作可用条件
  student_legacy/              独立旧版只读合同、解码、字段转换
backend/protocol.py            旧 import 路径兼容门面
backend/team_control.py        队内 PRM1 载荷；不随裁判年度改动
```

下一年新增独立 codec、字段合同、状态适配器、规则和经过审查的 registry 条目；显式扩展 adapter/rules 工厂和测试。
不要修改旧合同来“就地升级”、猜最接近年度或通过数据内容自动选协议。串口年度协议、队内固件桥和规则数值须分别核对，当前隔离不代表已经支持下一年全部规则。

协议切换会停止 Native 解码、清理 Hero 源覆盖、裁判缓存和接收队列、重置权威阶段并锁定输入。
资格证据同时绑定构建、协议版本、profile、机器人、固件哈希；旧 profile 的证据不能用于新 profile。
不认识的 profile 停止 MQTT，保持锁定，不降级到默认版。

## 已修复的接入问题

- Paho 2 回调 `ReasonCode` 不支持 `int()`：使用其 `value`；退出使用兼容的 `loop_stop()`。
- 删除没有官方依据的 `ClientStatus` JSON、retained 状态和 Last Will；只订阅精确下行 topic，不收上行回声/任意前缀。
- 严格拒绝截断、溢出 varint、错误 wire type、非有限浮点、非法 UTF-8、未知部署/比赛阶段；坏消息不部分更新状态。
- 尊重 V1.3.1 optional 字段存在性，防止缺失字段变零并清掉血量、阶段、模块状态或动作许可；本机 HP=0 不被较旧团队快照“复活”。
- 端点/身份/profile/断线变更废弃接收 epoch，旧连接回调不能重新注入消息。
- Arm 的机器人身份必须同时匹配 MQTT ClientId、运行时机器人与资格证据；配置里的未知 profile 保留到后端检查，不能悄悄回退当前年。
- 重连由主线程退避创建**新的 Paho Client**，关闭库内部原对象自动重连，避免 QoS1 未确认运动指令重放。初连失败也退避；新连接只补全零 KMC，必须重新人工授权。
- QoS、上行 topic、载荷与年度限频先验证再进入 socket；只读版不能通过 Mock 或急停特殊出口绕过。

## 验证与仍需现场完成的事

新增测试覆盖所有 V1.3.1 下行字段、部分更新、旧版投影隔离、资格绑定、真正 Paho 2 本机 MQTT 收发及未确认运动的断线重连。
它只绑定临时 localhost 端口，不生成现场 PASS 证据。发布脚本把这套测试作为强制门，并记录 profile/合同来源与本说明文件哈希。

本轮结果（2026-09-17）：
- `verify_all.py`：55 组离线检查通过；使用新建的固定 MCU 基线临时副本，真实 C 头文件/行为测试未因缺少固件而跳过，结束后副本工作树干净。
- `referee_integration_test.py`：263 项通过，仅 localhost 模拟 MQTT，不生成现场证据。
- `field_candidate_test.py`、`dt7_alignment_test.py`（96 项）、`smoke_test.py`、`gpu_compositor_test.py`：通过。
- `gpu_renderer_runtime_smoke.py`、`startup_gpu_runtime_smoke.py`：Windows 实际 OpenGL 路径通过。
- Python 编译检查、PowerShell 发布脚本语法检查：通过。未重新生成便携发布物，也未做本轮正式服务或真车验收。

源代码审查工具 `tools/audit_team_protocol.py --firmware <MCU 克隆> --ros-driver <ROS2 克隆> --output <报告>` 只读核对 ID/源码哈希，不编译、打补丁、烧录或连接串口。
上游 MCU 当前没有 `host_chassis_bridge.h / host_km_link.h`，显式自转/云台/PRM1 功能仍需已有固件补丁与**实际烧录哈希及回读**证明。
固件回归测试补齐了转接安装器连带修改的 `remote_control.c` 快照和失败路径还原；开发用 `requirements-build.txt` 固定 Zig 编译器，不让测试污染电控工作树，也不要求现场联网安装。

剩余现场门：真实服务协议抓包、机器人身份、DT7/DR16 仲裁、按键/鼠标回读闭环、松键归零、断链 watchdog、物理急停、正式图传与 Hero 生命周期、经济操作、完整时长 soak、双人签字。
源码与离线测试通过最多表示“可进入现场验收”，不表示接上 DT7 就一定能控制车辆。
已存在的旧 release ZIP 不会随源码提交自动更新；需要从新 Git commit 显式重打包并再次验证。
