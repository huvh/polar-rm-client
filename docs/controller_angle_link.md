# 实体工程控制器角度链路（Issue #10）

旧图传不经官方客户端的新增出口，参见[旧图传角度直发链路](legacy_angle_link.md)。
下文描述保留的 `Official Client Serial` 出口。

本实现补上客户端的**实体角度接收与转发**。已有的
`Custom Controller Egress` 仍是 `0x0306` 键鼠出口，不被改成角度入口。
软件离线验证不代表实体控制器、官方选手端、图传及机械臂已联调通过。

## 支持的合同

配置档案固定为 `standardrobotpp-engineer-2722e0d`，依据队内
[StandardRobot++ 2722e0d](https://gitee.com/SMBU-POLARBEAR/StandardRobotpp/tree/2722e0d2daba6113c86544d0c6d7918672669601)
的工程控制器发送源与机器人消费者。不同控制器不自动猜协议。

链路：实体控制器 UART → PC 的 Angle RX 串口 → 客户端校验与转发 →
PC 的 Angle TX 串口 → 官方选手端的自定义控制器串口入口 → 图传 →
机器人 `0x0302` 角度接收 → 工程机械臂 FOLLOW。

- 外层：`0xA5`、小端长度、8 位序号、CRC8、`0x0302`、30 字节载荷、CRC16。
- 前 24 字节：J0…J5，六个小端 IEEE-754 float32，单位为弧度。
- 后 6 字节：保留区。客户端转发时归零，绝不转发旧发送器越界读到的内容。
- 坐标是完成编码器零偏、方向、累计圈数及减速比处理后的关节坐标，
  不是世界坐标欧拉角。J4、J5 已在源端耦合，PC 不再换轴、取反或转成度。
- 接收验证使用实际源端已经执行的限幅：J0 ±2π、J1 [−1.1,1.2]、
  J2 [−2.5,0]、J3 ±4π、J4/J5 各 ±4.5π，float32 边界容差为 1e−5 rad。
  NaN、无穷及超出此档案范围的有限数都被丢弃，不刷新有效时间。
- RX 和 TX 均为明确选择的 115200、8N1 串口；TX 最大 30 Hz，只发最新新样本。
- `0x0309` 是反向机器人到控制器数据；`0x0311` 的 PRM1 键鼠及 MQTT
  `CustomControl` 是另一条链。本实现不把角度冒充 PRM1。

官方命令方向、源端具体坐标公式、机械臂现有变换和源文件位置见
[固件合同](../tools/firmware/controller_angle/README.md)。官方方向依据为
2025 V1.8.0 文档及该固定固件源码，不据此宣称适配所有后续赛季设备。

## 客户端设置与物理接线

在 System 中打开 `ControllerAngles` 设置。模块默认关闭，
`Forward Angles` 默认关闭，`Angle Mock Writes` 默认开启。

1. `Angle RX Port` 选择接收实体控制器发出的 0x0302 帧的串口。
   需要实际串口适配器/控制器串口输出，普通 HID 手柄不适用。
2. `Angle TX Port` 选择连接官方选手端自定义控制器入口的**另一条**串口。
   如果 PC 与选手端同机，软件需要两个独立可互通端点：客户端写 TX 端，
   选手端读其对端。仅选择控制器自身的 RX 口不会自动接通官方选手端。
   选手端驱动、设备枚举及物理适配器兼容性仍须现场验证。
3. 端口不允许 Auto；RX 与 TX 必须不同。`Rescan Serial Ports` 可刷新列表，
   不会改变当前选择。Linux 符号链接和大小写不敏感 COM 名也参与冲突检查。
4. 原有 RobotLink 会独立尝试连接遥测口，即使其模块未启用。仅使用角度链时，
   先把 `RobotLink → Port` 设为 Stub；需要机器人 USB 回读时，改为一个与
   角度 RX/TX 不同的明确端口。不要留下可能抢占控制器的 Auto。
5. 开启 `ControllerAngles` 后先保持 mock，用 `Show Angle Status` 检查
   valid、接收/转发状态和拦截原因。看见计数不是机器人已消费的证据。
6. 允许转发还需 `RobotLink` 启用、`Allow Drive` 开启、未急停及
   `Forward Angles` 开启，然后点击 `Arm Angle Forward`。
   Arm 只保存在本次进程中，配置文件不能让程序启动即转发。
7. 只有源端与车端固件、机械支撑、独立超时和实际接收映射验证完毕，
   才关闭 `Angle Mock Writes` 并重新 Arm。真实 Arm 会要求输入 ARM。
   切换 mock/真实、换端口或其他配置变更都会撤销先前授权。

原有 `Custom Controller Egress` 的 0x0306 键鼠功能保留。不同端口可并存；
同一真实串口不能由两个 writer 抢写。角度 worker 关闭尚未完成时，键鼠出口
也会等待，不把“已请求停止”当成“端口已经释放”。

## 失联、恢复与安全边界

- 有效角度只由经过长度、命令、CRC、序号、数值校验的 0x0302 更新。
  其他裁判包、0x0309、0x0311、错误角度都不能延长有效期。
- 软件台架默认：年龄 **小于 300 ms** 有效，恰好 300 ms 即失效。
  这是待现场评估的看门狗参数，不是测出的安全停车时间。
- 超时会清除可消费角度并锁住转发。没有周期性重发旧角度，也不发送
  “全零角度急停帧”，因为零角度本身是一个真实机械臂运动目标。
- 恢复有效 RX 后可以显示新角度，但必须再次 Arm；Arm 后还需另一帧新样本，
  不会立即重放先前缓存。8 位序号支持 255→0，重复和半范围内的迟到包不续命；
  超时/重连清除序号基线，控制器重启后仍需重新授权。
- 配置变更、关闭模块、撤回 Allow Drive、E-stop、锁定控制、失联和输出失败
  都会撤销授权。UI 许可超过 250 ms 未更新也撤销，即使后台仍收到角度。
- 串口失败后需关闭再打开接收模块，收到新鲜数据后重新 Arm；不会自动
  重连并恢复真发。输入积压超过 512 字节直接清除，禁止回放旧动作队列。
- 不完整帧的总等待时间最多 100 ms；缓存最大 1024 字节，单次最多读 512 字节。
  CRC 有效的其他整帧会整体跳过，不扫描其内容寻找嵌套角度命令。
- 一个 OS 写操作一旦开始就无法撤回。串口写超时配置为 20 ms；若驱动本身
  卡住，只保留这一 worker，不创建替代 writer。UI 锁定/关闭仍可立即更新
  授权状态，但最终停止必须由机器人独立超时及物理停止手段兜底。

车端补丁进入既有 SAFE 输出路径，不等于已经验证重载机械臂的重力安全保持。
调试时必须固定/支撑机械臂，先禁止实际执行器动作，再做板级验收。

## 固件安装与验证

先在精确参考版本的**可丢弃副本**检查补丁，不修改唯一工程：

```sh
python tools/firmware/controller_angle/apply_controller_angle.py /path/to/StandardRobotpp --dry-run
python tools/firmware/controller_angle/apply_controller_angle.py /path/to/StandardRobotpp
```

安装器修正 0x0302 数据源、角度专属新鲜度、完整六轴快照、工程臂失效门禁、
发送器 30 字节越界读及 34 ms 发送节奏。它不选 UART/DMA/引脚、不编译烧录、
不启用机器人输出。撤销和补丁组合顺序见[固件说明](../tools/firmware/controller_angle/README.md)。

离线回归：

```sh
python tests/test_controller_angle_integration.py
python tests/test_controller_angle_safety_review.py
python tests/test_controller_frame_regressions.py
python tests/test_transport_safety_regressions.py
POLAR_REFEREE_REFERENCE=/path/to/clean/StandardRobotpp python tools/firmware/controller_angle/test_controller_angle.py
```

仍需实物证明：六轴数值与方向、实际选手端转发和车端 0x0302 到达、停止角度但
持续其他裁判数据时的独立超时、机械支撑下的失联/恢复策略，以及旧键鼠通路。
没有硬件证据前，不关闭 Issue #10 的“实际接收端消费”验收项。
