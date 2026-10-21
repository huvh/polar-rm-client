# 全后端官方对齐覆盖审计（恢复重建版）

日期：2026-10-21。对象：POLAR RM Client。后端不只有图传；本报告按设备、视频、输入、裁判业务、安全和运行基础逐项列实证与验收。

**最终自动化结论：第二轮冻结树447 PASS / 13 SKIP / 5 INCOMPLETE / 0 FAIL，仍为NO-GO，不是全范围通过。** 已完成源码层重建与464套offline范围运行；缺失的外部固件/平台验证和未实现能力保留，不伪装为实机合格。精确树、计数与两轮失败历史见文末，统一记录见 [最终验证报告](full_backend_verification_rebuilt_20261021.md)。

## 恢复状态与证据口径

本轮恢复基线提交 `222899de17d211755b7a0a3b2851144ff8016c6c`，树 `32e942ec4c8112ecf1024488f1e23a0f71bcecb9`，由已保存的 2026-10-20 完整补丁恢复。该树与此前审计起点相同；下面“基线”仅指此树，不代表重建中的最终代码。

此前工作区曾保存到历史提交 `2700ada1ac80f4d2722da870fbcb816e17cb82dc`、历史树 `939857e1822000cf086150661864d539edae7b7b`，但该工作区及未完成全量输出在父任务中断后丢失。本文由保留的研究和测试记录重建，**不是旧文件逐字恢复，也不证明当前新树已包含那些修复**。原提交号和 PASS 只作历史索引；当前代码必须重新核验、重新运行，不能沿用历史 PASS。

证据等级：S=源码/版本固定官方包的静态分析；A=合成数据、fake 设备、localhost 回环、主机侧编译或 offscreen；O=指定官方软件实际互通；H=指定设备/固件/无线/机器人实机；Q=现场资格及人工签认。S/A 不能升级为 O/H/Q。测试文件名表示覆盖入口，非本轮已执行证明。

基线的突出缺口：V2 是“部分遥测与受监督 Air”而非完整 11 上行/25 下行；readiness/核心资格与实际 profile 不一致；桥的第二客户端可排队而非真正拒绝；CC 默认 HID 键码与官方213接收实现不同。初始化、配对、Windows 实机和完整官方替代始终没有通过。

## 24 项完整能力矩阵

| 编号 | 能力及性质 | 基线实现及可查入口 | 自动化覆盖入口 | 仍需证明的边界 |
|---|---|---|---|---|
| D01 | 设备发现/串口选择，官方兼容加本地策略 | `serial_ports.py`：`resolve_port/resolve_rc_port/resolve_cc_port`；扫描缓存、异步 snapshot、同分拒绝 | `tools/test_port_picking.py`、`test_serial_rescan_nonblocking`、`test_angle_port_admission_characterization` | Windows 驱动枚举、热插拔、多同型设备；枚举不安装驱动，不证明模式正确 |
| D02 | 驱动和接收器初始化，外部前提 | 官方包有 daemon/helper；POLAR 无完整等价初始化调用链 | 官方包校验、静态设备调用分析 | .NET/VC++/DJI/FTDI 驱动、权限、型号/固件与正式控制会话；不能把 helper 当无副作用视频专用服务 |
| D03 | 角色/阵营/MQTT 身份 | registry ClientId 1–9/101–109；`manager.set_client_id` 锁定/归零/撤 epoch 后重连；`robot_profiles.py` 与 `robot_roles.py` | `referee_integration_test`、`robot_roles_test`、`test_polar_role_epoch` | 与官方登录角色和实车一致；本地角色选择不是认证/对频 |
| D04 | 队伍/信道/接收器配对 | 未见完整生产等价流程；`AllianceProfile` 为本地配置，ClientId 为 MQTT 身份 | 官方 helper 命令方向/条件/回执静态证据 | 继续保留官方流程；不猜指令、不自动对频 |
| V01 | 现代官方 UDP 视频导出 | `video_backend.py`、`FrameAssembler`，8 字节大端分片与连续视频解码 | `test_udp_ingress_evidence`、`test_udp_codec_evidence`、`test_udp_receiver_admission`、`test_decode_publication_epoch` | 官方画面与导出先正常；真实编码器、IP、混源、丢片及无线长稳 |
| V02 | 旧 RNDIS raw H.264 和工程捕获桥 | legacy raw UDP；`tools/legacy_video_bridge.py` 显式适配器→loopback18080，官方端保留8080/设备所有权 | `test_legacy_vt02_ingress`、`test_legacy_video_bridge`、`test_udp_h264_hud_handoff` | Npcap/BPF、Windows RNDIS、权限、真实取流链；不是 DJI 支持的导出 API |
| V03 | Native0310/PDL1，队内扩展 | `native_viewer_telemetry.py`、`manager._apply_custom_byte_block`，300字节分块与独立 seq/epoch | `test_native_stream_policy`、`test_native_telemetry_epoch`、`test_native_video_activation`、`test_custom_byte_block_characterization` | 对端版本、载荷合同、真实像素；不解释任意官方0310内容 |
| I01 | 官方 MQTT 键鼠 | `KeyboardControlBridge`→选定 codec→`RmMqttBackend`；75Hz、阶段/资格/epoch、专用零帧；基线缺最终SUBACK门 | `backend_protocol_test`、`referee_integration_test`、`test_stage_freshness`、`test_mqtt_subscription_admission` | 实际官方消费；基线 V2 普通KMC仍拒绝，不能以编码器存在声称启用 |
| I02 | DT7 直连键鼠 | `dt7_link.py/dt7_worker.py`；22字节0x5A/0x2000、独立CRC初值、961200、默认mock、异步owner/归零 | `dt7_alignment_test`、`test_dt7_worker_dispatch`、`test_dt7_recovery_policy`、DT7 release flush | DT7固件、DR16/DBUS、摇杆优先和实物丢线；reserved1024是本地中立策略，不声称字节照抄官方0 |
| I03 | CC0306键鼠 | `cc_link.py`、异步writer，两个键码、1920×1080绝对鼠标、左右键、FTDI选口 | `tools/dt7_link/test_cc_link.py`、`test_cc_worker_dispatch`、`test_device_egress_safety` | 基线HID假设错误；官方213用Win32 VK。写串口成功不证明官方实际执行 |
| I04 | 六轴角度接收/转发，队内语义 | `controller_angles.py`、manager；A5/0302/30字节，6个float32弧度+6零字节；显式不同端口、Arm后新帧、≤30Hz/300ms/250ms许可心跳 | `test_controller_angle_integration`、`test_controller_angle_safety_review`、`test_controller_angle_receipt_boundary`、`test_angle_writer_handoff` | 语义绑定 StandardRobot++ `2722e0d`；实体轴向、重力安全、车端独立超时未验 |
| I05 | PRM1 kind1/2/3，队内载荷 | `team_control.py`，视觉/自转/键鼠经官方CustomControl容器；`gimbal_egress_owner` 单出口 | `polar_bridge_test`、radio KM、firmware KM host tests | 官方只定义容器；固件消费者、键位和新鲜度合同独立验收 |
| I06 | POLAR0x5A串口/TCP，队内独立链路 | `polar_protocol.json`→spec/link/transport/bridge；0x04自转、0x1F回读，与裁判并行 | `polar_spec_test`、`polar_link_test`、`polar_bridge_test`、`polar_integration_test`、control/motion epoch | 固件段布局/消费者/RC模式；本地deadman不替代车端watchdog，不按场景名一刀切关闭 |
| R01 | 裁判MQTT会话/protobuf | `mqtt_backend.py`、`referee/wire.py/validation.py`；精确topic、QoS≤1、current owner、retained隔离、有界队列 | subscription/retained/callback receipt/decoded batch epoch tests | 官方broker授权、拒绝、重投、版本；CONNACK不是SUBACK，topic名不是协议认证 |
| R02 | 协议版本/下行投影 | 默认V1.3.1、V1.1.0学生只读、V2部分档案；presence；基线V2 Radar拒绝 | V2 codec/projection/runtime、frontend projection contract | 每个topic逐字段到消费者；不自动升级配置，24/25不等于完整25 |
| R03 | 经济/复活/英雄/工程/飞镖/哨兵/Air | `economy.py`、年度rules、`tactical_map.py`、economy/video mixin与manager上行 | buy matrix、V2 action/air、window economy tests | 各自动作的源角色/目标/阶段/费用/确认；基线仅受监督Air；enqueue/金币变化非唯一ACK |
| R04 | 比赛新鲜度/状态所有权 | `safety.observe_stage_receipt`只用当前收件；本地1秒控制阶段期，过期锁定/手动重Arm；HUD不续命 | stage freshness、stage owner、official receive/scalar writer、overlay contract | 真实时钟/负载/断流；控制1秒、readiness/动作字段2秒、OfficialMatchFeed事件2.5秒各有owner，不是统一HUD TTL，均非厂商承诺 |
| R05 | A5裁判串口/路由 | `serial_backend.py/serial_stream.py/protocol.py`；长度/CRC/重同步，raw亦禁0310/0311走115200 | serial codec/lifecycle、transport safety | 真实波特率与端口归属；不替代官方图传高速通道 |
| S01 | 急停/人工授权/资格 | `OfficialSafety`、qualification/readiness/emergency；先零/撤权再清理，解除回LOCKED，证据绑定build/robot/firmware/profile | field candidate、estop nonblocking、input owner/cleanup、qualification observations | 机械归零时间、双人签认；本地HMAC非外部认证；基线V2能力误标需修 |
| L01 | 启停/超时/重连/所有权 | lifecycle/teardown/writer/mqtt cleanup；旧owner未退休不抢口，慢驱动与UI隔离 | async lifecycle、composite retry、writer close、start admission、window lifecycle | 真实Windows驱动/FFmpeg退出；请求停止不等于已释放，不承诺硬实时 |
| C01 | 配置保存/迁移 | config_store/configuration；先完整验证、别名迁移、源文件不自动改写；temp/fsync/replace；双文件非断电原子 | configuration transactions/quiescence、profile file/save identity、JSON nesting | 断电、多进程/只读盘；保留draft，不恢复临时Arm/资格 |
| L02 | 日志/诊断/回放 | field_log/preflight/replay；有界异步，accepted/written/dropped分开，回放不外发 | field log lifecycle、audio replay、build preflight | 磁盘与flush结果；分享裁判/设备日志前脱敏；诊断不能证明互通 |
| B01 | 车载USB↔TCP桥 | `tools/car_bridge/bridge_server.py`↔TcpByteStream↔polar transport，裸字节双向 | loopback/transport/evidence/admission tests | 基线第二客户端积压、stuck reader/close失败、多CDC/once；无认证，只可信网络；车端watchdog未验 |
| X01 | 私有视觉/同济/自瞄/吊射/聊天 | vision/tongji/hero_lob/auto_spin/match_chat；独立有效性和控制门；默认LocalChatTransport | tongji integration、autoaim settings、postprocess performance、native epoch | 私有预测不是官方真值；EnergyAutoAim无真实出口；本地聊天非官方联网聊天 |

### 本次重建相对基线的变化

- D01–D04、I02–I04、B01：被动设备身份诊断与Auto拒选、CC默认VK和显式旧HID、0302精确长度、桥单owner/换代backlog已重建。角色选择不是配对，旧接收器初始化/驱动与真实无线仍外部前提；角度安全门不放宽。
- I01、R01–R04、S01：V2当前具有11上行/25下行结构与逐动作准入，不再是基线partial。SUBACK、owner/epoch、现场资格、阶段超时与最终锁内复查共同控制出口；V1默认与学生只读不变。可解码/typed/raw投影不等于每字段都有专用HUD。
- R03：Common、空中到己方Sentry、付费Map有独立确认/报价链；Air保留受监督链；Performance空中控制模式在PREPARE单次确认。Dart来源修为空中，不新增发射；Rune只激活。Sentry6和争议custom Map仍明确拒绝，目标资格与支付ACK未凭空补齐。
- X01及R02消费者：私有视觉/吊射有限数和真实布尔、旧owner事务、聊天阶段、observed capacitor0已修；Rune环数不污染私有百分比，Radar官方厘米和定位离线标记不再猜测。PathPlan和若干新增raw字段未新增renderer。
- V01–V03、I05–I06、R05、L01–L02、C01：保留既有链路/出口边界，未声称变为官方全套替代。新增安全预设仅显式导入LabDebug/mock/loopback/Synthetic，不自动迁移或启动硬件。各原场景仍须最终聚合，O/H/Q没有新增通过。

## 每条控制出口的权限边界

| 通道 | 不得放宽的现有规则 | 不得误宣传 |
|---|---|---|
| POLAR0x5A | RobotCmd fire恒0；virtual_rc仅W/A/S/D；自转专用0x04与回读收敛 | 不可推论所有其他通道也无按钮或开火键 |
| 官方KMC | 真实键鼠字段经当前profile/阶段/SUBACK/资格/Arm/急停 | 可编码≠已授权≠实车执行 |
| DT7 | 默认mock、Real TX/Allow Drive；默认拦Q/E与按钮；显式Allow Fire Keys改变出口掩码；保留既有LabDebug台架例外 | 不为对齐新增火控授权；台架例外非比赛资格 |
| CC0306 | 模块/Allow Drive/急停、端口owner、中立帧；键码域独立核验 | 载荷有左右鼠标键，不能称无控制出口 |
| 角度 | 显式Arm、新鲜输入、心跳/端口/epoch；超时停转发、不自动重Arm | 零角度是运动目标，不能拿发送全零当安全停止；停串口不证明重力安全 |
| PRM1/桥 | 私有固件合同及各自门禁；桥只传字节 | 连接/写成功或synthetic回读不等于车辆安全 |

## 26 个分层验收场景

设备身份：
- A01 无/单/多/错设备，机器人CDC与DT7同时存在，多候选不得随机Auto。
- A02 热插拔、COM变号、枚举慢/异常；UI不阻塞、扫描不改配置。
- A03 RX/TX、DT7、CC、A5/0x5A别名碰撞；旧owner未关闭不得新建writer。
- A04 红蓝全部合法ID及非法0/10/100/110/非ASCII；切ID先锁、隔离旧epoch，无配对副作用。
- H01 实际型号/固件/驱动与官方会话，错ID/未对频/失败恢复；保留硬件验收，不自动执行。

视频输入：
- A05 UDP乱序/缺片/冲突/超长/混源；raw跨SPS/PPS/起始码、GOP恢复，不混拼或自动猜格式。
- A06 换源、解码退出、旧帧迟到/未来时间戳、停止/重启失败，不让旧epoch画面续命。
- H02 相机→无线→官方正常画面→明确导出/工程桥→POLAR真实像素；捕获/解码/长稳分别留证。
- A07 键鼠按松、增量、限频、满队列、失焦/模态、慢/短/失败写与重连；不补旧动作、中立帧不吞。
- A08 DT7独立黄金帧/CRC/seq/reserved；CC VK域与绝对坐标，不能混用相对增量。
- H03 DT7/DR16/DBUS与CC官方消费分别逐键，物理摇杆优先、拔线/崩溃、机器人独立超时。
- A09 角度分片/错CRC/错命令、重复/迟到/回绕、NaN/Inf/越限、积压/Arm前半帧/慢TX。
- H04 六轴单位方向/耦合、官方转发、车端超时；只停角度而其他裁判继续时仍失效，固定机械臂后验。

裁判业务：
- A10 CONNACK但SUBACK不全/拒绝/旧MID/client，普通动作拒绝，专用固定零仍可用。
- A11 每topic独立样例wire→版本codec→presence→正确目标→消费者；负数/零/false/缺失/错类型/超长。
- A12 V1/学生只读/V2切换和清理失败；状态/结果/资格不跨代；新支持不能只保留旧partial拒绝测试。
- A13 延迟消费/retained/乱序、HUD持续但GameStatus停、更换epoch/最终锁内过期；收件恢复不自动Arm。
- A14 每业务的源角色/目标/阶段/费用/取消/重复/错误回执，RMUC/RMUL规则范围；不自动重试扣费请求。
- O01 指定client/engine/profile实际往返、身份/订阅/字段/结果；无nonce不得声称逐请求强关联ACK。

运行安全：
- A15 每出口F12/解除/锁定/换配置/退出/异常；一条失败不跳过其他，解除仍LOCKED。
- A16 伪造/过期/改build/firmware/robot/profile/video资格与旧签字；能力按当前profile核实。
- A17 构造/start拒绝、晚返回、close失败、重试/重入；区分请求/入队/写出/归零/释放。
- A18 坏JSON/深嵌套/旧别名、保存/回滚失败、同名重载/导入；不丢draft、不持久化Arm。
- A19 日志满/慢/磁盘错/flush超时与回放；丢失可见、emit非落盘、回放不外发。
- A20 桥双客户端预发/EOF/半写/超时/stuck reader/close失败、多CDC/once；旧队列不入新session。
- H05 每条实际链路拔线/停进程/恢复，车端watchdog、整局长稳、Windows退出；不拿fake时限当机械时限。

## V2 全部 11 上行：wire、业务与权限分开

官方213要求V2.0.0。下表为恢复前已完成的静态核对事实与重建验收目标，当前是否实现按新树验证记录填写。经济详细依据见 [官方经济动作证据](official_economy_action_evidence_20261021.md)。

| 消息 | 官方合同/重点 | 消费与验收目标 |
|---|---|---|
| KeyboardMouseControl | signed int32三轴、三按钮、16bit键、75Hz；y负向下 | 屏幕dy转换、当前Arm/阶段/SUBACK与专用零；不保留虚假的V2 partial资格 |
| CustomControl | ≤30bytes，75Hz，0311容器 | PRM1是队内合同，容器成功不证明车端消费 |
| MapClickCmd | range0指定/1不含哨兵/2含哨兵；7字节ID；field3为类别、field6为模式 | 普通1–3；含哨兵需费用确认与同队；213 custom用5/PDF用4冲突，明确拒绝，不偷偷改值 |
| AssemblyCommand | 工程2/102；operation0开始/1确认/2取消，difficulty1..4 | 表单与wire一致，失败/取消结果不得猜进度 |
| RobotPerformanceSelectionCommand | Hero自身3/4、Infantry自身1/2；另有同队Sentry控制方式 | 空中6/106在PREPARE可发shooter/chassis0 + sentry_control0自动/1半自动；字段级作用域，单次监督与锁回 |
| CommonCommand | cmd1/2数量；3..6忽略参数，采用本地param0；cmd5固定一包 | RMUC规则、Hero/Infantry补给、Engineer仅3/4复活；fresh can/quote与明确价格；不能复用旧V1 offer |
| HeroDeployModeEventCommand | Hero1/101，mode0/1 | 独立Hero资格；部署切断官方和自定义视频流，私有Native不是官方绕过承诺 |
| RuneActivateCommand | Infantry3/4/5及蓝方；activate1 | 未证0取消，UI不能冒充；环数与百分比区分 |
| DartCommand | 源为空中6/106，目标同队飞镖；target1..5为靶型非机器人ID | open=false不关闸，只不请求开启；UI launch_confirm保持false，不扩大射击授权 |
| SentryCtrlCommand | 空中6/106→同队7/107；1,3..12；固定50/100发 | 自动干预费50、半自动0另加商品费；target未知条件明确；6缺目标报价拒绝 |
| AirSupportCommand | 0暂停/1免费/2免费优先后1金币每秒/3付费解除反制并呼叫 | 3为同级地面复活比较价×2；照射非可解除；独立确认、无唯一ACK |

全部11类需严格类型/范围、精确来源角色、当前会话、最终发布检查；Map采用本地保守3秒间隔，Air10Hz是本地上限，不能称官方给定数值。

## V2 全部 25 下行：字段、目标与用户可见功能

| 消息 | 单位/目标与已核事实 | 不能夸大的消费边界 |
|---|---|---|
| GameStatus | 全局回合/阶段/秒，5Hz；结算结果/原因仅结算有效 | HUD应用不续心跳，换回合清旧结果；内部阶段减1才为公开值 |
| GlobalUnitStatus | HP己方1/2/3/4/7后敌方，弹量己方五角色；双方总伤害 | HP/弹量有消费；总伤害无新增专用HUD，不是购买ACK |
| GlobalLogisticsStatus | 团队金币、累计金币uint64、科技/加密 | 团队余额非本机交易确认 |
| GlobalSpecialMechanism | 机制ID及有符号秒数组 | 长度不齐/负数不猜，列表/时间线消费 |
| Event | ID/参数触发 | feed非完整历史，不是阶段心跳 |
| RobotInjuryStat | 本次存活累计伤害分类/killer | 首样本/复活/回合/累计下降不制造命中 |
| RobotRespawnStatus | 当前机器人的pending/free/pay/当前报价 | 官方空中不发布此项，不能拿它充同队Sentry报价 |
| RobotStaticStatus | 当前ID/type/场内/存活/性能/上限 | 显式0不沿用旧能力；max_chassis_energy应投影但无新增专用HUD |
| RobotDynamicStatus | 当前HP/热/火速/能量/经验/弹量/脱战及远补远疗许可 | 火速/经验/升级需求/倒计时为raw/dict部分消费；不可称专用HUD齐全 |
| RobotModuleStatus | 电源/RFID/装甲/图传/激光 | 字典/诊断；在线不等于可执行或授权 |
| RobotPosition | x/y/z/yaw/robot_id | 地图位置不同于Radar厘米单位，不让旧位置续期 |
| Buff | 目标/type/有符号level/秒 | 负防御为易伤，缺失不补效果 |
| PenaltyInfo | 类型/持续/累计，触发式 | 已知红牌拒绝；无消息或TTL到期不推导解除 |
| RobotPathPlanInfo | 起点分米、49个有符号偏移、发送者 | raw path_plan，未新增renderer；PDF相对起点/前点描述冲突不猜路径 |
| MapClickInfo | 与上行同形的通知 | marker显示，非自己请求ACK；类别/模式不反转 |
| RadarInfoToClient | repeated RadarSingleRobotInfo wrapper；厘米；0,0未知；highlight2定位离线 | 固定cm→m，不能按数值大小猜单位，1/2不当伤害buff；private/mock米需显式来源 |
| CustomByteBlock | 0310下行≤300bytes，50Hz | PDL1/Native为私有消费者，坏magic/旧epoch不生效 |
| TechCoreMotionStateSync | 难度/基础/放入/运动/旋转/敌核/步骤秒 | 工程UI，难度4合法，枚举非百分比 |
| RobotPerformanceSelectionSync | shooter/chassis当前机器人，sentry_control同队Sentry | 字段级不同目标，不能整个dict都标自身 |
| DeployModeStatusSync | 当前Hero部署0/1 | 部署UI与本地视频owner；收件时刻不由迟到应用续命 |
| RuneStatusSync | 1未激活/2中/3已激活；灯臂数、平均环数 | 8.5是8.5环非850%；私有进度分离，缺失不变0 |
| SentryStatusSync | 同队姿态/弱化/强化 | is_powered不是电源；无CD/累计强化/复活资格 |
| DartSelectTargetStatusSync | 同队飞镖靶与闸门 | 不新增发射权限，不是本次发射ACK |
| SentryCtrlResult | command_id/result_code0成功，无nonce | 213 Sync实现为stub，不保证发；旧重复不唯一对应本请求 |
| AirSupportStatusSync | 支援/免费秒/累计花费/照射/shooter枚举 | cost不是下一动作报价，shooter0/1/2不简化bool |

本次恢复后已重新读取 descriptor（SHA256 `db398c02c9c6636852ab02693df3c51a77b9b219f836e9b1b3deb88b34091b50`）独立统计并逐字段核对：官方二进制为 **36个message type/167字段**；当前本地为 **37张field表/175字段条目**；MQTT为 **36 topics=11上行+25下行**。差8不是缺字段：二进制只有一张8字段的`MapClickInfoNotify`，本地按`MapClickCmd/MapClickInfo`两个方向各列一次。应用这个类型别名后，本次number/type/repeated差异为0；另有两处字段命名别名：RobotPosition#5 `robotid/robot_id`、TechCore#2 `status/basic_state`。

PDF另是37个message代码块，接受CustomControl全角分号后可数174条带编号声明；`RadarInfoToClient`的伪声明没有字段名/编号，且把子消息写成uint32，不是合法schema。PDF表格可补其编号1，但wrapper的实际nested-message类型由二进制descriptor补证，不能称纯PDF175条合法字段。早期抽取草稿171条还漏了全角分号和两个packed字段，不作为正确计数。以上为当前静态结构检查，不是全量运行测试、完整HUD、官方互通或现场资格。

## 已发现问题：原状态与重建验收

| 项 | 历史发现/修复要点 | 当前恢复状态 |
|---|---|---|
| F01 | readiness固定V1、核心资格误标V2 partial；先统一真实profile能力，后完整V2再按实际支持和角色开放 | 新树profile/manager/上行角色及签名资格/Arm竞态focused已独立通过；最终聚合仍另验，不沿用旧828e2b8或4aa80cd结论 |
| F02 | TCP桥同步accept使次客户端积压重放；stuck reader/close失败丢owner、多CDC首选、once无效；初始log异常亦泄漏listener | 新树18方法独立通过：持续拒绝busy、旧listener退休、owner保留、构造/start/日志异常清理；仅fake/loopback |
| F03 | CC默认HID与213 Win32 Keybd_event不符，W应0x57非0x1A | 新树device contract14方法独立通过：VK默认、显式旧HID、用户数值override保留，不放宽键位 |
| F04 | 旧模块地图把历史/本地聊天/部分版本当当前官方覆盖 | 本文按层级重建，不能用过时表作为现状 |
| F05 | SUBACK有诊断但未封住ordinary publish和Arm最终门 | 新树subscription13、上行/经济准入focused通过：当前session/SUBACK及最终复查，专用固定零保留；真实连接仅localhost broker |
| F06 | repeated int32 packed/unpacked未恢复符号 | 新树codec24方法独立通过，含负数、混合chunk、无符号、畸形边界；不是官方互通 |
| F07 | V2经济只看protocol，RMUL可误套RMUC420秒/150金币 | 新树纯规则13、经济MQTT10、经济UI11均独立通过：actual state/qualification owner显式RMUC、profile/robot、initial/final重查；UI三mode一致和确认变化有界复核。最终全量另验，目标未知/缺报价仍明确保留 |

F07的赛制是一致性绑定，不冒充官方wire认证。Common/Sentry/付费Map需确认后当前不可变snapshot的对象身份；同值新收件可在确认过程中重新核对，但最终边界替换必须拒绝。payload先冻结，旧session/authority/owner/SUBACK/价格或字段过期不能发送。不自动重试，不把6秒生效套旧V1的5秒失败事务。

### 历史全量的六项失败，必须逐项新验

此前全量并未完成为PASS，恢复负责人保留的六项失败如下；以下是定位线索，不是未经复跑就判定“仅测试错误”：

| 旧失败入口 | 已知分歧/应验内容 | 新树结果 |
|---|---|---|
| `backend_protocol_test` | Rune平均环数分离后旧百分比期望；同时验真实显示与不写私有进度 | 恢复后独立199 checks通过，含Rune2.5环与mock值不变；最终树仍须聚合 |
| `hud_batch10_settings_test` | 显式0容量的旧期望；另有capacitor明确0真bug，不能仅改断言 | 恢复后独立29 checks通过；消费者22方法已另外验证observed0不是mock fallback |
| `test_backend_policy_boundaries` | Inf处理改为拒绝后的旧抛异常期望；仍须fail-closed | 恢复后独立7方法通过；非有限数保持未知/拒绝，最终树仍须聚合 |
| `test_ui_localization` | 新toast缺约20条翻译；不删用户可见报错绕测试 | 恢复后独立15方法通过；包含literal toast扫描，不改变持久化ID/确认短语 |
| `test_ui_state_regressions` | AST抽取未包含`_finite_number`；验证真实方法依赖 | 恢复后独立30方法通过，见文末；最终树仍须聚合 |
| `test_v2_air_ui_external` | 旧MATCH-only/partial文案与新V2能力不符；另有历史modal id复用flake | 恢复后独立18方法通过、GUARD_CALL_COUNT0；wrapper强引用与3秒watchdog保留，实际SUBACK/三mode/确认snapshot补齐 |

## 历史测试账与当前验收账

以下都来自丢失工作区的保留记录，**不是本轮新树PASS**：
- 桥准入14、显式安全预设14、RC150离线骨架21方法通过。
- 历史经济树a4f925f上独立运行43方法：rules13、MQTT9、UI11、V2 uplink10。
- 历史消费者末阶段另一轮43方法：Performance4、event12、telemetry12、map contract15。
- Air首次17/18，observer_failure_after_enqueue模态fixture超时；单项通过。只存`id(widget)`不持wrapper有地址复用风险，823fadf保留强引用、不延长3秒watchdog。随后两个独立进程18/18，直跑GUARD_CALL_COUNT0。保留初失败，不倒填首次通过。
- 历史465套聚合未完成为PASS，且有上列六失败。不得将focused次数相加冒充全量数量。

**当前重建新树：尚未完成全范围验收。** 文末“恢复后本次新验记录”只适用于其明确阶段；后续只追加精确HEAD/tree、命令、平台/依赖、pass/fail/skip/incomplete及日志引用；统一聚合由集成人串行执行。

## 永久保留的具体限制

1. Windows驱动、官方软件实际往返、无线链路、实体机器人与Q：未验证。本轮不运行硬件/官方exe、不改系统网络、不操控用户Codex、不消耗其服务额度。
2. 旧接收器初始化/配对/信道未有完整生产替代；ClientId、串口选择不是硬件配对。
3. RC150旧工作区曾有离线选择/owner/raw bytes骨架，但**本轮明确未恢复该adapter，当前只有官方静态证据，不是已实现但未测试**。硬件factory、Windows实际枚举/open/read、HEVC增量decoder、UI/manager接入均未实现。旧21项测试只属历史，不能写成当前READY/真机出图。
4. Map ASCII官方213与PDF冲突，明确拒绝；PathPlan几何解释冲突，无新renderer。
5. Sentry6缺目标复活报价及费用包含关系，明确拒绝。其他固定费用请求只能说“提交给服务器判断”，目标alive/脱战/can/CD/强化时长未暴露。
6. 本地/同济/PRM1/PDL1/Native/0x5A/车载桥为队内扩展；不能声称厂商同等功能或所有私有载荷官方支持。
7. 安全213/V2预设只做显式LabDebug/mock/loopback/Synthetic staging，设备出口关闭，不替换默认V1、不改旧配置、不证明client213+engine137已配对或硬件合格。

## 官方来源（client/PDF已重新恢复；engine仅保留历史身份）

- [官方资源](https://bbs.robomaster.com/wiki/20204847/804784)：client12.0.0.213要求V2；engine12.0.0.137为后续版本，不自动证明pair。
- Client ZIP 420317398字节/170项CRC，SHA256 `661498326b6a0047d5cf73a4f9ceede3297cba4b0e745aa49c69a46eba873374`。
- Engine ZIP 429242136字节/939项CRC，SHA256 `61586fb4083399cbc5607f17e895af42b43b5199ee09522087f628e3354ea933`。
- [通信协议](https://bbs.robomaster.com/wiki/20204847/811363)：V2 20260626 SHA256 `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b`；V1.3.1 20260519 `0197a5f97f7171dc74cd5040d4e5872afb92db44a0307e682a4efd3f2688db42`。
- [RMUC规则](https://bbs.robomaster.com/wiki/20204847/809871)：V2.2.0 2026-08-07，SHA256 `88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5`。

哈希是文件身份，不是厂商签名。本报告不附官方二进制/反编译全文/用户原始视频/配置或凭据，不声称2027兼容或正式赛事资格。

## 恢复后本次新验记录

- 2026-10-21 04:00 UTC，HEAD `43c0b5f22e38fb3a3371894924d3805ceb9dfe53` 的车桥阶段：审计者重新执行 `PYTHONPATH=. ../client-verification-venv/bin/python -m unittest tests.test_car_bridge_admission_safety tests.test_car_bridge_evidence -v`，18方法（14+4）通过，1.914秒。真实连接仅127.0.0.1，串口为fake；包含让第三连接排在旧backlog后，验证换代不写旧bytes。重新只读复核owner/close/start/log异常；F02该阶段已修，不升级为硬件安全，也不覆盖其他尚未重建项。

- 2026-10-21 04:02 UTC，已保存消费者阶段 `43c0b5f` 的本轮独立复跑：`test_backend_feature_consumers`22 + `test_ui_state_regressions`30，共52方法通过（0.374秒）。自身真实observed capacitor容量0压住demo百分比；未观测或其他机器人0仍保留私有fallback，不能只改期望。旧六fail中的ui_state当前已通过，其他五项不因此算通过。
- 2026-10-21 04:03 UTC，HEAD `a52b8ab61d3d01975db31f87e3d721da7224ab72` 预设阶段：独立直跑 `tests/test_official_profile_preset.py`，14方法通过（1.100秒）。复核现有真实设置、默认V1不迁移、unknown版本不猜、pairing/hardware未合格、所有live出口关闭；真实offscreen reload用惰性transport替身，无设备连接。日志 `/tmp/audit_official_preset_rebuilt_20261021.log` 为当次临时诊断，正式持久化由交付归档另记。
- 2026-10-21 04:06 UTC，重建经济纯规则阶段：独立执行 `QT_QPA_PLATFORM=offscreen PYTHONPATH=. ../client-verification-venv/bin/python -m unittest tests.test_backend_policy_boundaries tests.test_v2_economy_rules -v`，7+13方法通过（0.004秒）；运行后HEAD为 `4d23745b968a49dcc4b6d647c2b61e5be2c6fe75`，上述两测试和经济规则文件无未提交变化。金额/固定数量、Engineer仅Common3/4、Sentry空中源/同队目标/模式费/6拒绝均与官方证据一致。旧六fail中的policy边界当前已过；MQTT/UI仍在重建，这不是完整经济链验收。
- 2026-10-21 04:10 UTC，HEAD `6735909cd648843c3f8b0fe6f1ba6158d96b3f20`：独立执行 `tests.test_referee_v2_economy_admission`10、`tests.test_referee_v2_uplink_admission`8、`tests.test_referee_v2_uplink_domains`8，共26方法通过（0.036秒）。覆盖11上行的真实guarded route、RMUC/owner/确认对象identity和最终竞态、付费Map与普通Map分路、空中PREPARE Performance、Dart空中源与Sentry6拒绝。fake broker，不证明服务器接受。日志 `/tmp/audit_v2_core_rebuilt_20261021.log`。
- 2026-10-21 04:11 UTC，同HEAD：独立复跑设备contract14、V2codec24、runtime profile17、manager admission6、MQTT subscription13，共74方法通过（0.154秒），日志 `/tmp/audit_rebuilt_contracts_20261021.log`。包含真实paho与127.0.0.1合成broker的SUBACK拒绝/retained隔离，不是官方broker；其余fake/合成，不执行设备。以上74与其他focused可能覆盖同一行为，不能累加为全量成绩。
- 2026-10-21 04:12 UTC，同HEAD：独立复跑 `test_backend_alignment_admission`12、`test_official_feed_receive_freshness`9、`test_qualification_observations`10，共31方法通过（0.091秒）。验证签名资格与真实profile/角色、核签中换owner、Arm通知撤权、迟到收件不续命；OfficialMatchFeed2.5秒与readiness2秒各自边界保留。日志 `/tmp/audit_rebuilt_admission_20261021.log`，无设备或真实资格发放。
- 2026-10-21 04:14 UTC，独立进程直跑 `tests/test_v2_air_ui_external.py`，18方法通过（1.122秒）、`GUARD_CALL_COUNT0`；运行结束HEAD `435685ca7d1a357963b5cf63bf520dc61d638f12`，本次fixture随后保存于`b5f20bd`。无旧PASS继承，未延长3秒watchdog。日志 `/tmp/audit_air_rebuilt_20261021.log`。
- 同时段独立直跑 `tests/backend_protocol_test.py` 199 checks与 `tests/hud_batch10_settings_test.py` 29 checks均通过，结束HEAD `78ad9d6`，fixture随后保存于`b5f20bd`。前者含本机生成H264→FFmpeg的合成像素链，无依赖skip；不是现场视频。再独立 `test_ui_localization`15方法通过（0.708秒）。三份日志分别为 `/tmp/audit_backend_protocol_rebuilt_20261021.log`、`/tmp/audit_hud_batch10_rebuilt_20261021.log`、`/tmp/audit_locale_rebuilt_20261021.log`。旧六失败至此各有新树独立通过证据，不代表最终聚合已经完成。
- 2026-10-21 04:15 UTC，HEAD `b5f20bd90d560ba1ac46c94c2fd7d355fdff266d`：经济UI11、Performance UI4、event form12、manager admission7，共34方法独立通过（0.325秒）。首次包式unittest使用`PYTHONPATH=.`发生3个同级测试模块import错误，保留日志 `/tmp/audit_ui_economy_rebuilt_20261021.log`；仅修正运行命令为`QT_QPA_PLATFORM=offscreen PYTHONPATH=.:tests ../client-verification-venv/bin/python -m unittest tests.test_v2_economy_ui_alignment tests.test_v2_performance_ui_alignment tests.test_event_command_alignment tests.test_v2_manager_admission -v`，未修改测试或生产，结果日志 `/tmp/audit_ui_economy_rebuilt_corrected_20261021.log`。真实Qt模态由Air18另验；此组dialog函数用替身驱动，不能混称同一证据等级。
- 2026-10-21 04:17 UTC，Radar/消费者最后阶段：独立运行 `test_tactical_map_telemetry`12、`test_tactical_map_contract`16、`test_backend_feature_consumers`23，共51方法通过（4.985秒）；`hud_batch21_radaroverlay_map_test.py`18 checks通过。结束HEAD `77434cfc472455978b3fcbcff2180edc208079e1`，生产阶段为`bda5a21`。覆盖官方固定厘米/特殊标记、完整offscreen窗口栅格合同、Hero四flag严格真实True。原固定reference保留为旧单位错误反例，没有重生成基线；独立expected只接受坐标/高亮两项明示delta。日志 `/tmp/audit_radar_consumers_rebuilt_20261021.log`、`/tmp/audit_radar_batch21_rebuilt_20261021.log`。不把音频设备缺失/字体缓存警告当真实平台验收。

本轮审计文档于2026-10-21 04:18 UTC冻结等待最终源码和统一聚合。上列各阶段日志中的HEAD可能随并行保存推进，只有所列具体测试/行为被本次独立确认；不能把阶段PASS外推为尚未完成的最终树全量PASS。

## 首轮冻结树聚合与修后待复验

2026-10-21 04:20:42 UTC启动，run_id `b7c9a53b9a784fafb8ac1c4c96ffe121`；冻结提交 `298af0b5633391b8152b42e841ccb821dee99ecc`，tree `b98eff9ee2eb61922cfc3c19d5fd1f53c2483b09`，起点干净。Linux x86_64 / CPython3.12.14 / PySide6 6.8.2 / paho2.1.0，selected offline464套。另有派生设置孤儿检查，所以JSON的465条结果是 **444 PASS、13 SKIP、5 INCOMPLETE、3 FAIL，结论NO-GO**，不是464全通过。起止源码指纹一致，`source_stability=PASS`。

证据为 `tmp_quality/rebuilt_backend_aggregate.json`、同名`.log`与`rebuilt_backend_aggregate_logs/`各stdout/stderr。这轮完整失败结果保留，不用后续focused覆盖。

| 首轮FAIL | 精确原因与修复边界 | 修后独立focused，不等于二轮聚合 |
|---|---|---|
| dt7_alignment_test | 旧fixture仅设置connected=True，没有当前client的SUBACK；新增惰性client真实_on_connect→完整SUBACK，并在新会话重建stage。未改生产/放宽Arm | 04:32直跑112 checks PASS，OFFLINE ONLY；日志 `/tmp/audit_postaggregate_dt7_20261021.log` |
| test_referee_v2_publish_guard | manager AST只抽3方法，遗漏新增真实_v2_action_admission及state/import依赖，AttributeError | 04:30直跑26方法PASS；将真实helper纳入切片，不stub门禁；日志 `/tmp/audit_postaggregate_publish_guard_20261021.log` |
| test_v2_air_ui_external | 同一AST遗漏，使普通armed manager方法异常被UI转toast，sent0；不是modal超时 | 04:30隔离进程18方法PASS、GUARD_CALL_COUNT0；3秒watchdog保留；日志 `/tmp/audit_postaggregate_air_20261021.log` |

早前独立Air18运行在manager经济实参新门加入前，故不能覆盖这个冻结树回归。这里明确重开并再验，不能继续称此前六失败一直全部闭合。修后上述三文件之外无生产改动；运行时基准为298af0b加三个待保存fixture差异。**第二轮完整聚合尚待执行。**

其余未完成不是“通过”：
- 13 SKIP：PowerShell缺失的发布归档套件1项；未显式选择外部固件树/准备fixture的12项主机编译/合同套件。不是13个测试方法，更不是12项硬件通过。
- 5 INCOMPLETE：polar_link缺队内Python CRC对照；legacy_video_bridge缺libpcap原生BPF检查；DT7 link缺固件及旧dump.cs；DT7 UI selftest缺外部application C；legacy patch逻辑要求安装、因此不进入只读验证。内部已完成断言不覆盖这些缺口。
- 6套未被offline profile选入：4套native desktop/GPU，1套同济外部集成，1套视觉检查。它们不是本轮SKIP计数的一部分。
- 静态检查由集成人报告234 modules / 3601 functions / 0 cycles PASS；不替代运行、Windows发布或O/H/Q。

## 第二轮最终结果（独立核对完整JSON）

2026-10-21 04:34:07 UTC启动，run_id `8db50feb2f4a472795dc503bf66eaa52`。冻结提交 `0f58747be4533ece2fc9c873189651db9cf2b368`，tree `e0ff067cf4559e7b43a0f43efd5a948795d55ae8`，起点干净。审计者于04:43 UTC只读核对 `tmp_quality/rebuilt_backend_aggregate_final.json`，确认 `run_state=completed`、起止源码一致。

- 最终465条结果：**447 PASS、13 SKIP、5 INCOMPLETE、0 FAIL**。其中464个选定套件为446 PASS/13 SKIP/5 INCOMPLETE，另1项派生设置孤儿检查PASS；不能混成447个独立测试方法，也不能说464套全通过。
- `source_stability=PASS`；823项声明源码输入的起止SHA256均为 `0195840a20c0b95b5ed007408f48a878b23af2572ea1b4d16c651ea724621af0`。这是运行期输入一致性，不是硬件或来源签名。
- 首轮3个FAIL在该完整二轮中分别为DT7 112 checks、publish guard26方法、Air18方法PASS。历史六入口也逐项在此轮PASS：backend199、HUD29、policy7、locale15、ui_state30、Air18。故修后不再仅凭focused推断闭合。
- 13 SKIP、5 INCOMPLETE及6个未选套件与上一节边界保持。完整结果仍为 **NO-GO (selected scope)**；当前不能宣称Windows发布、全部依赖/固件合同、官方实际互通或现场资格通过。
- 最终文件为 `tmp_quality/rebuilt_backend_aggregate_final.json`、同名`.log`和`rebuilt_backend_aggregate_final_logs/`。首轮完整日志保留；仓内主验收报告负责最终归档/提交身份，本矩阵只链接结论，不覆盖旧失败。

用户可见剩余应分三种：**未实现**包括RC150当前adapter及硬件factory/decoder/UI、旧接收器初始化/配对完整生产替代、若干新增字段专用HUD；**有明确拒绝/未支持边界**包括Sentry6目标报价缺失、Map custom的4/5版本冲突、非RMUC7v7的V2经济请求；**已实现但未现场验证**包括官方MQTT/设备/无线/Windows视频与输入出口。这些功能边界与上面的依赖/平台验证NO-GO分开统计，不能统一说成“只差实机测试”，也不影响本次保留的权限、Arm、超时、急停与出口隔离。
