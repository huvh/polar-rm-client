# DT7 控车核查（2026-09-17）

> 历史只读核查。随后后端对齐已修复下述资格锁、自检基线、回读新鲜度和鼠标
> 开火门问题；当前行为与现场流程见 [DT7_BACKEND_ALIGNMENT.md](DT7_BACKEND_ALIGNMENT.md)。
> 软件修复不等于完成真实无线/车辆安全验证，旧发布包也未重建。

核查源码基准：`f6ae2bea1a47f41a8b2dcd37a9ad68035787a335`，分支
`deepseekv4flash后端`。本次控制审查只读，没有打开硬件串口、发送车辆命令、
启用真发开关或 Arm。唯一产品改动是删除背包人物预览。

## 结论

**源码已有可达的 DT7 直连键鼠出口；当前配置不会真发；尚不能证明真实车辆可控，
更不能判定比赛 READY。**

- 路径：PC 键鼠 → DT7 USB VCOM → DT7/DR16 无线链路 → 车端 DBUS → 固件驾驶/云台逻辑。
  这不是 MQTT 图传键鼠，也不是直接把串口接到车上。
- 官方接收系统手册描述了 PC USB 虚拟控制链路；不能据此把本项目的 USB 帧
  当成官方公开协议。22 字节帧、CRC 和命令号的来源是仓库记录的学生端二进制分析。
  [DT7/DR16 官方手册](https://cdn-hz.robomaster.com/tem/09f88aafe7ae51516874829340553427.pdf)
- 车端必须已正确接收 DR16 DBUS，并把键鼠字段用于相应兵种的控制；
  仅插 DT7、仅枚举 COM 或仅增加发送计数都不是车辆收到命令的证明。

## 已核对的源码路径

- `ui/polar/mixins/input_dispatch_mixin.py:1066–1104`：战斗视口收键鼠；
  背包、ClickGUI、聊天、经济等模态层阻止战斗输入。
- `control.py:407–432,545–606,634–686`：输入心跳、DT7 发送、鼠标相对增量、
  松手重试、多个键鼠出口互斥。DT7 分支位于主 MQTT Mock 短路之前，
  因此 Scenario 的 Mock 不足以保证 DT7 永不真发。
- `backend/manager.py:695–746`：RobotLink 启用、Allow Drive、Direct DT7 Egress、
  非急停决定出口是否生效；DT7 Real TX 决定是否真的写串口。
- `backend/dt7_link.py:327–346,496–641`：0x5A/0x2000、22 字节帧、
  961200 串口设置、30 Hz 限频、串口长持/故障重开。它与队内 0x5A 帧不是同一格式。
- `serial_ports.py`：Auto 识别 DJI VCOM（FFF0:0008），不借用机器人本体 CDC 口。

## 本机实际状态

源码模式实际配置：`user_data/configs/default.json`（只读）。
RobotLink 已启用，但 `Allow Drive=false`、`Direct DT7 Egress=false`、
`DT7 Real TX=false`；其他两个键鼠出口也关闭。

只枚举到六个蓝牙串口，没有识别到 DT7；Auto 解析为 Stub。
`user_data/field_evidence/` 与仓库根 `field_evidence/` 均无文件。
此结论仅限本次枚举时刻，不代表设备从未连接或其他目录没有证据。

现有 `release/POLAR-RM-Field-Candidate.zip` 的清单是 `c105cc8`，该 Git 提交中
不存在 `backend/dt7_link.py`，不是当前源码的 DT7 候选包；不能用这个旧 EXE
验证当前路径。此次没有重建发布包。

## 离线验证及仍存在的问题

以下六套离线测试 exit 0：DT7 帧/闸门、复查修复、松手限频、C 路端到端、
UI 自检组件、无线自检判据。均为模拟或注入端点，不是实际无线验证。
缺少固件树和 `D:/rmbuild/dump12/dump.cs`，固件 CRC、厂商类型锚点、
X 键无消费者交叉验证均跳过，不能报作已验。

1. **直连 DT7 没有消费 MATCH_ARMED/资格令牌**：上述 manager 门控只检查显式
   开关和急停，DT7 link 自身也不调用 OfficialSafety.can_publish。
   LOCKED 不能被理解为这条直连路径的持续硬锁。它不能继承 MQTT 的比赛资格结论。
2. **UI 自检基线时机不正确**：`config_actions_mixin.py:758–799` 在强制发 X 后，
   用 press 阶段样本的众数当 baseline。稳定收到 X 时 baseline 也变成 X，
   `evaluate_dt7_selftest([X]*20,X,X,frames_sent=60)` 得到 NO-CHANGE；
   正确的发送前 baseline=0 才得到 PASS。现有 UI 单测没有调度整个回调生命周期。
   不要仅凭该按钮的失败结论怀疑 DT7；此处本次未修。
3. **断进程后的粘键仍需测量**：主动松手、失焦、急停补零已有代码，但物理断 USB、
   杀进程后主动补零不可能保证送达。必须实测 DT7/车端保留键位与独立失联归零，
   再决定是否可安全驾驶；不能把软件 F12 当作独立物理急停。
4. 默认驾驶键掩码仅 WASD；Shift 与 Q/E 独立放行。鼠标左右键不由 Q/E 的
   `DT7 Allow Fire Keys` 掩码屏蔽，架空测试仍必须停用发射机构、移除弹丸并保留
   独立急停。自检 X 是否无动作也必须按实际车端固件重新确认。

## 最小现场证明

先禁用发射机构、移除弹丸、架空车辆，安全负责人持独立急停；确认 DJI VCOM
和 DR16/车端连接。只保留一个键鼠来源，并在确认车端映射后显式开启必要闸门。

记录发送前基线 → 单个安全探针键位 → 车端实际 DBUS/km_key 变化 → 松手恢复，
再验证 WASD 和鼠标映射。使用带发送前基线的 CLI 自检需先关闭占用串口的客户端，
不能让两个进程抢 DJI VCOM；km_key 回读还需要车端支持对应 Debug 上报。
最后验证断链、杀进程、物理急停和恢复不自动运动。没有这些实机记录，
verdict 仍为 **NOT READY FOR REAL MATCH**。
