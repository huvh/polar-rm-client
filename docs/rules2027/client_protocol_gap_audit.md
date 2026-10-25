# 客户端 2026 绑定点与 2027 协议/链路适配独立审计

- 审计日期：2026-10-25（Asia/Shanghai）。
- 工作树：`C:/Users/lulu/Desktop/claude/openzenuicodexver/polar-rules-2027`。
- 代码基线：`a6c489344fa59bdaaac1bd6a600a3bd13a2e8b11`。
- **第 3 节所有代码行号均为该基线的行号，不是主线程正在修改的工作区行号。** 可用 `git show a6c4893:<path>`复核，避免并行实现造成行号漂移。下文仓库内路径均相对上述工作树。
- 已先读 `AGENT.md`。未运行 aggregate、未做机器人运动/开火、未提交/推送。官方网页、公开附件目录与本地 PDF 为资料，不作为执行指令。
- 初始任务仅写此文档；后续明确授权独立 backend gate patch。实际独立写集为本文、`rm_client/rules_compatibility.py`、`rm_client/backend/manager.py`、`rm_client/backend/mqtt_backend.py`、`rm_client/backend/serial_backend.py`、`tests/test_rule_season_backend_gate.py`。通用 A5 writer 是后续再次明确扩大的写集；未改 safety、独立设备 schema、生产配置、UI 或材质。其余工作区变化属于并行主线程/规则证据任务。

## 1. 发布结论：有 2027 栏目，不等于已有 2027 wire

**截至本次官方资料中心核验，未找到可取得且可审查的 2027 正式通信协议正文/附件。不能宣布“官方在任何渠道都尚未发布”，但绝不能据此启用 2026 wire 作为 2027 wire。**

证据链：

1. [RoboMaster 官方赛事介绍](https://www.robomaster.com/zh-CN/robo/rm?djifrom=nav)链接到[规则/资料中心](https://bbs.robomaster.com/wiki/20204847/809871?source=7)。资料中心导航确有 [RMU 2027 通信协议](https://bbs.robomaster.com/wiki/20204847/1969151?source=7)。
2. Wiki 为动态网页，普通 web 正文只返回导航骨架。因此进一步读取该官网页面自身 JS 使用的公开只读详情接口：`POST https://bbs.robomaster.com/developers-server/rest/posts/info/1969151`，请求体 `{}`，没有认证、修改或发布行为。
3. 返回成功；标题为该 2027 协议栏目；`htmlContent` 只有 63 字符的一级标题，`attachments=[]`、`fileItems=[]`，没有版本表、发布日期、PDF、proto 或字段定义。栏目 `updateAt` 为 `2026-09-04T12:49:38.000+00:00`。**这是空栏目证据，不是可实施协议。**
4. 对照[官方 2026 协议页](https://bbs.robomaster.com/wiki/20204847/811363?source=7)，同一详情接口有实质版本目录及 38 个附件条目，明确列出 V1.3.1（2026-05-19）和 V2.0.0（2026-06-26）。因此 V1.3.1 是本地/默认基线，**不是当前目录内的最新 2026 版本**；V2 依然是 2026，绝不是“2027 版”的别名。
5. 本地解包的官方客户端、`CustomClientProReflection`、Client 12.0.0.213 / Engine 12.0.0.137 只支持各自 2026 软件/schema 取证。`rm_client/configuration/official_profile.py:1-5,12-14,39-58`已经明确区分 schema 匹配、引擎配对与硬件资格；不能把这些扩大为 2027 支持。

官网快照保存在 `tmp_rule_2027/protocol/official_post_1969151.json`、`official_post_811363.json`、`web_verification.json`。2027 详情响应 SHA256：`ad3153a98560ed288cc6d1655e6916c873cccf9f166832d3e5a08bb46fb644d8`。再次审核时须重新访问官网；负面检索结论有时间边界。

## 2. 正式规则能证明什么，不能证明什么

### 2.1 本地正式 PDF 基线

| 资料 | 本地路径 | 页数 / SHA256 |
|---|---|---|
| 2027 制作规范 V1.0.0，2026-10-15 | `C:/Users/lulu/Downloads/RoboMaster 2027 机甲大师高校系列赛机器人制作规范手册V1.0.0（20261015）.pdf` | 91；`3287fe5f521f8801ce69632032ea17a9c8d8a099091558f58618cd7721154a3c` |
| 2027 联盟赛规则 V1.0.0，2026-10-15 | `C:/Users/lulu/Downloads/RoboMaster 2027 机甲大师高校联盟赛比赛规则手册 V1.0.0（20261015）.pdf` | 68；`a8fd7b7f6ea5212b9e4dfa590b478827992598d91912ed671653c8bdd9727fd6` |
| 2026 通信协议 V1.3.1，2026-05-19 | `C:/Users/lulu/Downloads/RoboMaster 2026 机甲大师高校系列赛通信协议 V1.3.1（20260519）.pdf` | 84；`0197a5f97f7171dc74cd5040d4e5872afb92db44a0307e682a4efd3f2688db42` |

页号下文均为 **PDF 一基页码**；所列 2027 手册印刷页码为 PDF 页码减 1。已提取文本，并渲染/目视核对重装性能表、经济/控制区、buff/重装特殊机制、终端协议表的相关页面；未用前瞻手册替代正式手册。RMUC 2027 正式规则的数据审查由并行规则任务负责，本审计不把 RMUL 规则外推到 RMUC。

### 2.2 已确认的离线规则事实

- 制作规范 §2.1.7，PDF 18-19：自定义终端通过操作间 RJ45 接口接入；画面为 UDP，比赛数据为 MQTT+ProtoBuf；具体内容另指《通信协议》；S49 要求接入操作间接口测试，S50 禁止无线收发装置。**这些只确定链路类别，不能确定端口、ClientId、topic、字段号、频率、视频 codec 或控制资格。**
- RMUL §3.1.1，PDF 17-19：1 号为重装，不是原英雄近战/远程两分支。开局上限血量 100、功率 50W；安装成功后的表值为 450 / 50W / 16.5m/s / 热量 250 / 冷却 66/s。§3.3.6（PDF 38）还要求安装并发射一发被裁判系统正确识别的 42mm 后才提升，不能用 UI 切换伪造完成。
- RMUL §3.1.2，PDF 19-20：步兵功率/血量分支分别为 300HP/90W、350HP/75W，爆发/冷却分支为 230/14、88/24。**不选时默认血量优先+冷却优先**，不能沿用当前 UI 的 Power+Burst 默认。
- RMUL §3.1.3，PDF 21-22：哨兵 400HP/100W/260/30，初始允许发弹量 750、局内不可增加。重装与步兵初始允许发弹量为 0；实物预装与允许发弹量不是同一概念。
- RMUL §3.3.2-3.3.5，PDF 36-38：自动复活、补给区恢复、600 初始控制度、三处控制区、高地 25% 防御及隧道 1.5 倍冷却持续 60s 均有正式条款。规则效果可离线展示，但增益类型码、占领状态结构、重装装配回读的 wire 尚不能定义。
- RMUL §3.3.3，PDF 36-37：17mm 为 10 金币/10 发，42mm 为 10 金币/1 发；价格与一部分 2026 常量相同不代表命令 ID/参数、供给权限或回执也相同。
- RMUL §3.2（PDF 22-23）仍为 12m×8m、五分钟；§4（PDF 40-42）另有两分钟、5m×5m 的步兵对抗赛。尺寸相同不能证明旧地图图片、热点或红蓝坐标映射仍然正确。

## 3. P0/P1 绑定点清单（基线 a6c4893）

分类：**A 可纯离线适配**＝由正式规则/源码可确定，不声称联网；**B 需新协议**＝必须先取得并审查 2027 wire；**C 需现场证据**＝即使 schema 匹配，也不能由规则/本地测试代替。一个风险可同时有多类依赖。

### P0：阻断跨年度错误控制、错误状态或虚假资格

| ID | 具体代码行 / 2026 绑定与使用方 | 风险与适配边界 | 分类 / 当前处置 |
|---|---|---|---|
| P0-01 年份不随赛制变化 | `rm_client/referee_profiles.py:13-15,36-51`：默认 `rm2026-v1.3.1`、学生只读、V2 的 `year` 全为 2026。`rm_client/backend/referee/registry.py:54-73,98-128`按 profile 装配年度 adapter/economy；`rm_client/module_catalog.py:99-108`赛制只有 Mode，没有 Season | 把 RMUL/RMUC UI 切到 2027 不会改变 adapter；不得把 V2 的版本大号当年份。2027 协议未受审时，应保留旧 profile 真实身份并明确不兼容，不能制造 rm2027 别名 | A：显式赛季与兼容门；B：将来独立 2027 contract/codec/adapter。已加 backend 门，未加 profile |
| P0-02 最终 enqueue 与旧 QoS | `rm_client/backend/mqtt_backend.py:637-717,725-780,857-950`有初始、V2 最终安全检查，但没有规则年度；`_publish_current`是实际 `client.publish`前的裁决。`poll_connection:288-319`已说明 Paho 可重放未确认 QoS1 | 仅 UI 禁用不防直接 API、确认后切年、26→27→26、资格后切年。已进入 Paho 的数据不能靠未来的 UI 检查撤回；旧客户端/待重连队列必须退役，不可换 profile 标签后继续发 | A：年度复核、generation 失效、退役旧 Paho owner；B：2027 控制/经济/设置的 wire；C：实际断网、物理归零与重连测试。已在接收和最终 enqueue 加门 |
| P0-03 签字资格跨年 | `rm_client/backend/qualification.py:121-132`会话含 match_mode/protocol_version/referee_profile，不含 rules season；`:565-605`只核既有身份。`rm_client/backend/manager.py:2348-2449`资格与 Arm 可重读签字证据 | 单纯 `lock_control()`后，若仍保留已签会话，旧 2026 证据可能再次 Arm。不得借缺失 season 字段默认宣称它覆盖 2027 | A：切年废弃内存 session/token，Arm/qualification 再核年度；B/C：未来 2027 全链路资格。已加门，未改证据 schema/历史签字文件 |
| P0-04 旧下行伪装 2027 状态 | `rm_client/backend/mqtt_backend.py:557-626`解码、V2 receipt 和 GameStatus 阶段证据；`rm_client/backend/manager.py:1968-2014`队列→`_begin_official_state`→adapter→observer；`rm_client/backend/referee/rm2026/state_adapter.py:17-24,180-270`含兵种、buff、阶段语义 | protobuf 未知字段可忽略不是年度兼容证明；即使能够解析，也可能把新语义写到旧字段。旧 decoded/raw、已取出的 batch、V2 snapshot、HUD 投影都不能在切年后继续“变真” | A：接收前/入队前、batch、direct apply、frontend 投影门和状态退役；B：2027 adapter/字段语义。已覆盖所列 manager/MQTT入口 |
| P0-05 通用裁判串口原始年度缺口（本轮已收口） | `rm_client/backend/serial_backend.py:128-191`：通用 `0xA5`帧/CRC校验、禁 0x0310/0311、急停，但无年度 gate；同文件 `:243-245`拒绝伪造串口 stop | 基线 MQTT 门不保护手工调用原始 serial writer；帧/CRC正确不能证明年度语义正确。后续授权补丁已在真实驱动写入前加年门，捕获等待写锁之前的epoch，覆盖raw/write/send/write_frame/private路径与26→27→26。没有新增串口Stop | A：已在最终writer处拒绝2027真实写，并与Manager同步；mock仅诊断、不记真实写证据。B：仍需2027受审串口契约才能开放；C：串口实机验收。明确允许的新增写集内已实现，不再作为待补产品绕过口 |
| P0-06 start/retry可重新接入旧年度（本轮已收口） | `rm_client/backend/mqtt_backend.py:102-154,247-273,288-319,434-487`：基线start/actual Paho获取、cleanup pending-start恢复、poll reconnect、CONNACK订阅没有规则年门 | 只在切年时关闭owner不够；后续Official场景或retry可能按2026端点和topics再建连接。即使上行被挡住，也会误导为2027链路就绪 | A：已在request和actual acquisition前、cleanup恢复、poll/retry、CONNACK/SUBACK使用同一年度admission；mock不创建真实Paho，不兼容时取消pending/reconnect/zero-after-reconnect。B/C：2027协议/现场验收仍缺 |

### P1：规则、展示、默认值与功能语义不能靠年份重命名

| ID | 具体代码行 / 2026 常量 | 客户端实际使用方及 2027 风险 | 分类 |
|---|---|---|---|
| P1-01 场地与赛程 | `rm_client/match_modes.py:45-64,97-116,148-169`：420s/28×15、300s/12×8，固定 `rmuc_7v7_official.png` / `rmul_3v3_official.png`和热点；未知 key 回退 RMUC | `rm_client/ui/polar/renderers/tactical_map.py:835-844,920-955,1855-1891`用尺寸、镜像与热点绘图，并把点击换算为米发送。2027 地图机制变更不能沿用 2026 图像/热点；RMUL 1v1 也不能退到 RMUC | A：按 season+mode 分场地元数据；B：官方标点语义；C：现场原点、轴向、镜像与测量。保留 2026 图片不等于给它改 2027 标签 |
| P1-02 角色与性能表 | `rm_client/robot_profiles.py:27-62,65-109`：英雄 Melee/Range 1-10 级表；RMUL Hero 固定 350HP/100W/200/24；步兵 Power/Burst 默认；Engineer/Aerial/Sentinel fallback | `rm_client/ui/polar/mixins/persistence_mixin.py:60-75,144,166,178,797`读表并写 state；重装与空中系统等新角色不能沿用英雄/UAV旧能力。相同编号/别名只可作为显示兼容键，不授权旧 wire | A：独立年度 roster/performance 数据和来源页；B：2027角色 ID/性能 enum；C：实际回读 |
| P1-03 初始弹量混用容量 | `rm_client/robot_profiles.py:119-132`将 42mm 容量/余量设 12，17mm 设 180；`rm_client/model.py:136-156`有默认基地/前哨状态 | `ProjectileAllowance`、热量/弹量 HUD、profile 切换直接读。2027 RMUL 重装/步兵初始允许发弹量 0、哨兵 750，不能从通用弹舱容量反推裁判允许量；已观测状态不应被本地 profile 重置成满弹 | A：区分物理容量、规则初始允许量、已观测允许量；B：正式下行；C：数量对拍 |
| P1-04 经济策略与未完成交易 | `rm_client/economy.py:61-75`兼容编码和 actions 只按默认 profile 分派；`:90-94`交易 context 无规则赛季；`rm_client/backend/referee/rm2026/economy_rules.py:10-12,104,135-184,194-211`：420秒时间阶梯、远程补弹150、金币/复活/支援策略 | EconomyPanel/ProjectileShop 和 transaction mock/回执。RMUL 相同单价也必须在2027规则包独立注明来源，不能隐式继承 CommonCommand type=1/2/5、远程恢复或复活权限。切年后的旧确认/回执应作废 | A：年度报价、eligibility、交易上下文含 season；B：2027经济命令/ack；C：现场金币扣除和RFID权限。生产经济联接由主线程负责 |
| P1-05 英雄/重装机制与性能上行 | `rm_client/backend/manager.py:82-90,2528-2554,2581-2614`：HERO_MELEE=3 / HERO_RANGE=4、SHOOTER=1/2、CHASSIS=1/2、SENTRY=0/1，`HeroDeployModeEventCommand`等；`rm_client/backend/referee/rm2026/codec.py:498-536`编码器 | RobotProfile 性能发布、英雄部署、能量机关、飞镖、哨兵指令都携年度枚举。2027 RMUL 重装“安装+首发确认”不等于旧 Hero deploy、AssemblyCommand 或切 Melee/Range；不能凭名称相似重用 | A：机制说明/离线状态机；B：2027命令/回读；C：装配、首发认可、硬件归零。后端门现已拒绝2027沿旧schema发这些命令 |
| P1-06 弹道辅助的旧英雄前置 | `rm_client/hero_lob.py:190-193,210-221,230-235`要求 Hero+Range；fallback muzzle speed16m/s；热量/阶段/校准门；本身不发射、不发云台命令 | HeroLob/hero_deploy 工作台。数学求解可复用；规则角色/装配状态/枪口速度不能从“重装”直接映射旧 Range。离线角度预览也不是2027 READY 或射击许可 | A：纯物理求解与年度 readiness 分离；B：受审遥测语义；C：枪口、姿态、定位与热量标定。不得放宽既有 readiness |
| P1-07 技能/性能点草稿 | `rm_client/student_ui.py:356,365-368`的 Chassis/Shooter Points 0..100 与 Draft；`rm_client/ui/student_panels.py:279-284,439-443`明示本地草稿不下发 | SkillConfiguration 本地面板。已有界面/字段名不是2027正式技能系统证据；不得从前瞻猜“通用技能树”，不得把 points 写进旧 performance enum | A：草稿与已同步状态隔离；B：若正式规则/协议提供配置命令再实现；C：设备应用与回执。维持草稿只读wire属性 |
| P1-08 buff 与机制图标 | `rm_client/backend/referee/rm2026/state_adapter.py:17-24,155-169`：Buff 1攻击/2防御/3冷却/4功率/5回血/6补弹/7地形；`rm_client/model.py:327-330,365-399`按这些码分组，小/大buff有demo fallback；`rm_client/module_catalog.py:774-783,1193-1202`开关默认启用 | BuffTimeline/BuffStatus/地图状态。2027 RMUL 25%高地防御、隧道1.5倍冷却/60s等要有年度规则描述，但数值相似不能证明枚举号、倍率单位、TTL和角色域一致 | A：年度增益定义/来源与未知状态；B：2027 buff/地形回读；C：场地触发时序。不把“没收到”画成生效 |
| P1-09 model/demo默认 | `rm_client/model.py:38-43,61-89,130-156,474-516,540-594`：默认2026profile、420s、控制度200、HP520/600、金币260/620、允许量180/12、周期demo buff与基地5000/前哨1500 | model.tick、TopMatchBar、Economy/Map/thermal HUD 都是使用方。2027规则预览不得继续跑2026 demo、不得把默认值作为官方 observation。仅把标题换2027不可接受 | A：默认绑定2026；2027独立seed+rules_status，禁旧tick；B：真实状态来源；C：实时性。主线程负责model/seed |
| P1-10 保存与未知赛季 | `rm_client/configuration/registry.py:99-117`只有 Referee Profile 保留未知mode值，其余未知值退回当前默认；`rm_client/module_catalog.py:99-123`没有年度配置；`rm_client/model.py:624-627`catalog默认2026 | profile_saves/启动页/runtime恢复。应让旧文件缺Season时明确2026，未知年度不能被静默恢复成2026/7v7；rules_version须可追溯，rules_status不是授权位 | A：版本化保存、显式迁移、拒绝未知赛季；B/C：不受这些本地配置影响 |
| P1-11 网络profile常量 | `rm_client/referee_profiles.py:38-50`：192.168.12.1:3333、client_ip 192.168.12.2、UDP3334、HEVC；学生localhost；`rm_client/backend/referee/registry.py:35-50,101-119`：robot ClientId 1-9/101-109、QoS≤1、KMC/CustomControl75Hz、MapClick≤1/3Hz、其余10Hz | MQTTLink、网络诊断、UDP视频、资格测试使用。2027制作规范只确认UDP/MQTT+ProtoBuf，并未证明这些具体值跨年不变；不得把旧endpoint/profile匹配当2027链路就绪 | B：正式2027网络/视频契约；C：现场网口/VLAN/实际端点/解码时延/身份权限。保留2026常量不代表继承到2027 |

## 4. 本次独立 backend patch 与明确边界

### 4.1 已实现（当前工作区符号/行号）

- `rm_client/rules_compatibility.py:11-50`：仅整数 2026/2027，遗留缺字段在调用方默认为2026；规则年、绑定 state 年和 reviewed profile 年必须一致。2027即使传入一个虚构的`protocol_year=2027`也仍拒绝，因为没有受审实现。没有新增 rm2027 profile。
- `rm_client/rules_compatibility.py:52-116`：退役官方 presence/freshness、容器（含2027的`control_zones`）、已观测动态值；只清官方数据，不清`polar_*`，不改DT7/PRM1 schema；没有官方输入时保留本地性能默认，主线程随后执行年度 seed。
- `rm_client/backend/manager.py:343-366`：`set_rule_season(int)`可在首次runtime之前调用；切年清内存资格session，同步serial owner，再让MQTT锁止/清阶段与receipt，最后退役官方state；同值同步幂等。构造末尾也调用，初始state为2027不能漏门。
- `rm_client/backend/manager.py:1627-1633,1999-2052`：frontend、batch和直接_apply_one都核年度，旧消息不经2026adapter写进2027 state。收包epoch变化或reentrant切年后不继续旧batch/observer。
- `rm_client/backend/manager.py:2387-2503`：qualification与Arm入口拒绝年度不符；在证据加载后及qualification/Arm回调之后再次复核。旧签字文件即使被重新放回session，也不能把2027 Arm成功。
- `rm_client/backend/mqtt_backend.py:390-426`：transport年度门；切年使用与最终enqueue相同的生命周期锁，并在decoded锁内清阶段/receipt/队列/generation。实际已启动客户端退役，不自动重启旧Paho owner，避免旧QoS跨年重放。
- `rm_client/backend/mqtt_backend.py:661-729,743-751,967-1065`：接收前、入队前、公开publish入口、最终实际enqueue再次核年；省略authority参数或伪造`intent=estop_zero`不能发送非零跨年命令。V2 economy还有原有snapshot/身份/权限/频率/阶段门，不因年度门放宽。
- `rm_client/backend/mqtt_backend.py:107-197,290-315,331-369,523-626`：start/request-start/实际Paho获取与cleanup/poll复用年度admission；不兼容时取消pending start/reconnect，mock也不创建真实连接。获取Client后、connect_async后再次复核epoch/年份，构造中切年或26→27→26不会启动网络loop。CONNACK订阅前后、SUBACK解析grant后重查，不调用旧ready/login hook冒充27。保留vendor subscribe不持生命周期锁的ownership边界，已进入旧owner的调用不能撤回，但其完成不能污染新owner。
- `rm_client/backend/serial_backend.py:59-92,168-266`：通用A5 owner绑定live state；年度切换是短metadata epoch更新，不等待驱动写锁、不释放急停；raw/send/write_frame/private入口捕获pre-wait epoch，验证/编码/驱动方法取出后均不能洗成新epoch。真实写入前重查年度、epoch、state和急停；2027全零A5帧也不豁免。未定义官方串口Stop，保持锁写。
- `stats()`分别显示`rule_season`、`protocol_year`、兼容结果/原因，不把mock成功等同于受审协议支持。

### 4.2 不变式与不承诺事项

1. `publish_estop_zero()`仍是固定全零KMC路径；2027不兼容不会阻止它对既有写入owner做紧急释放。学生只读profile仍不允许写入；断网仍只能报告无法入网，不能伪称物理急停完成。
2. 切年保留estop latch/ESTOP态，不触发自动解锁；返回2026仍需重新资格/显式Arm，不恢复旧token/armed capability。
3. 非零PRM1若包在官方CustomControl/MQTT里发送，也受官方承载层年度门限制；**并非声称PRM1 schema属于2027，且没有修改其schema**。独立0x5A/DT7仍依原有授权、急停、deadman、归零、互斥与firmware证据约束；年度不兼容不能旁路这些硬闸。
4. 不兼容2027的后续Official request_scenario、直接start、端点/profile重试和poll不得新建Paho/socket；全零急停不会主动建连，只对已有owner尽力释放（mock可纯记录）。本实现原本就不发送ClientStatus JSON/retained will，本轮没有发明登录报文或新wire。回到2026后仅poll不自动恢复连接，显式start也仍保持LOCKED、不能恢复旧token或运动。
5. 主线程拥有规则包、Season设置、profile持久化、年度seed与UI门；本patch不修改这些文件。`rules_status`是显示来源状态，不是协议或控制权限开关。最新窄补丁仅改MQTT、独立测试、本文及明确追加的`control_zones`退役条目，未改场景/配置/设备接口。
6. 通用`serial_backend`原始writer的P0-05缺口已按追加授权收口。2026默认API与帧校验保持；2027真实A5年度写一律拒绝，mock允许留诊断但frames_written/last_write_at不成为真实证据。私自取得native driver句柄直接操作不是产品公开API，不能由该句柄自报“年度合规”。其它直接实例化年度adapter的外部脚本也不得当作产品年度入口。
7. 已在驱动/网络内发送的字节不可撤回；退役与全零是尽力软件措施，不替代物理急停/断流测试。没有机器人、赛事引擎、无线环境或实际开火验收证据。

## 5. 今年与未来赛季的模块化方案

### 5.1 三个互相独立的身份

| 身份 | 应拥有的数据 | 禁止推导 |
|---|---|---|
| `CompetitionRules(season, mode, rule_version)` | 正式文档来源/哈希/页码、角色、比赛时长、性能/初值、经济eligibility、机制、buff、地图元数据 | 不从profile版本猜规则年；不生成wire字段 |
| `RefereeProfile(profile_id, year, protocol_version)` | reviewed contract/codec、state adapter、网络与速率约束、命令域、来源和受支持能力 | 不从规则年猜topic/字段/枚举；V2不变2027 |
| `DeviceProtocol(device_schema, firmware_hash)` | 0x5A/DT7/PRM1布局、设备角色、实际固件消费者、独立授权与硬件证据 | 不借年度换标签扩大安全权限；不让独立设备伪造官方观察 |

### 5.2 2026 回归优先、2027 离线受控

- 2026现有导入接口保留，默认season=2026。既有整数/enum、报价、schema均保存在2026叶子模块，旧调用不被“升级”到未知规则。
- 2027只由正式规则叶子包提供显式支持的mode/role事实；每个事实有doc版本与page citation，未知/无该机制为None/unavailable，不能fallback到2026表。
- Rule API只产出语义值，不能直接带入CommonCommand type或性能enum。把“报价”与“如何发wire”分开，非空预览不代表enabled动作。
- 交易context至少包含state owner、season、rule_version、mode、robot identity、referee profile和epoch。hold/二次确认后的上下文改变必须作废；ack与mock均不能跨年兑现旧交易。
- 不覆盖任何UI材质。2027图像/几何未逐项审查前，保留几何示意或明确不可用，不能为旧图片改年份冒充。
- 当前backend门作为年度边界的单一事实来源，不只在UI处读取Season。调用规范是`set_rule_season(int)`，不能直接改`backend.rule_season`或`mqtt.rule_season`绕开epoch退役。

### 5.3 将来新协议准入清单

1. 取得官方正式协议附件，记录链接/版本/日期/SHA256并核对修订日志；规则文件本身不能替代wire。
2. 新增独立年度contract/codec/adapter/command-domain；逐字段核类型、tag、packed形式、单位、可选presence、roster顺序、ClientId域、坐标域、topic/方向/频率/QoS、视频/网络端点。未知字段可被proto容忍，不等于语义受支持。
3. 为每项功能建立“规则事实→wire表达→投影字段→UI消费者→授权门→回执/现场证据”映射；未完成的能力保持不可用，不因注册profile一次性全开。
4. 引入来源可追踪的旧包/新包黄金样本、malformed及partial样本，跨年负面测试先于新功能正面测试。2026和2027不同解释的数据不能自动探测混用。
5. 未来需要开放2027时，先升级资格context设计以明确含规则年/版本；历史签字证据不自动迁移。完成安全台架、现场链路、归零/重连和具体机制对拍后，再逐能力授权。此时才能审查本次显式2027拒绝门的放行变更。

## 6. 回归集合与本次执行结果

### 6.1 本次精准独立执行（最终复跑全部通过）

Python：`C:/Users/lulu/Desktop/claude/openzenuicodexver/rm_custom_client/.venv/Scripts/python.exe`。

执行新集：`python -X utf8 tests/test_rule_season_backend_gate.py`；旧集每个单独执行：`python -X utf8 -m unittest discover -s tests -p '<精确文件名>' -v`。未调用aggregate。

| 测试文件 | 通过数量 | 关注边界 |
|---|---:|---|
| `test_rule_season_backend_gate.py` | 38 | 显式赛季/未知值/首次runtime/幂等setter；3个旧profile全部topic和公开wrapper、所有旧下行；伪造intent/private final；mock/固定零/ESTOP；旧签字、回切、decode/batch/enqueue/Arm回调竞态；Paho退役/清理异常；独立Polar不变；A5所有真实入口、pre-wait/编码/转换/driver-final ABA；start/retry无socket/client获取、pending cleanup/回调恢复、真实Official场景、mock不入网、回26不自动恢复运动、control_zones清理 |
| `test_mqtt_decoded_batch_epoch.py` | 19 | 断线、换端点、嵌套apply、异常observer与旧batch退役 |
| `test_referee_v2_runtime_profile.py` | 17 | V1/学生/V2身份、只读、固定零、年度adapter、mock/经济上下文 |
| `test_backend_alignment_admission.py` | 12 | 旧资格/角色/签字、SUBACK与Arm竞态 |
| `test_referee_observer_ownership.py` | 4 | authoritative state与只读observer的容器隔离 |
| `test_referee_v2_publish_guard.py` | 26 | V2最终enqueue的snapshot、token、phase、payload、身份、context、频率与observer |
| `test_backend_input_owner.py` | 13 | owner-thread清输入、失败重试、DT7/CC inert零帧、qualification/Arm硬闸 |
| `test_mqtt_retained_evidence.py` | 3 | retained消息不得成为阶段证据 |
| `test_referee_v2_uplink_admission.py` | 8 | 11个上行topic域/速率、SUBACK、能力与final检查 |
| `test_serial_lifecycle_regressions.py` | 19 | A5合法/非法帧、短写/失联/急停，与独立Polar/serial stream的原有不变量 |
| `test_backend_estop_nonblocking.py` | 5 | 驱动阻塞时跨设备急停不等待，旧快照不得释放新急停 |
| `test_backend_async_lifecycle.py` | 22 | 已入驱动字节不可撤回、后续writer锁止、异步停机/重试/owner边界 |
| `test_mqtt_lifecycle_nonblocking.py` | 21 | pending-start/cleanup owner、重连、回调与observer不阻塞、旧session不得复活 |
| `test_mqtt_subscription_admission.py` | 13 | SUBACK/CONNACK失败与超时、retained及本地inert broker的原2026行为 |
| `test_mqtt_cleanup_ownership.py` | 8 | 原生socket/线程释放证据、模糊close错误不得换owner |
| `test_resource_close_ownership.py` | 12 | 跨后端close失败保留owner、显式重试确认 |
| `test_mqtt_endpoint_admission.py` | 22 | endpoint验证、coalescing、input-clear重入与真实owner身份 |
| **合计** | **262** | 17个精确文件；不是整个产品/整季验收 |

新集禁止真实`socket.socket`、`serial.Serial`、`subprocess.Popen`，仅使用inert client；后台enqueue测试通过Event显式暂停/切年/继续，没有运动/开火。旧input owner测试使用注入的inert字节writer，不连接设备。初次V2运行曾因Windows默认GBK读取UTF-8源码而报4个UnicodeDecodeError，随后加`-X utf8`复跑17/17通过；未为环境编码问题修改生产或既有测试。

日志均在`tmp_rule_2027/protocol/`，另已执行`git diff --check`检查本次manager/MQTT/serial写集。其他线程新测试/规则文件不计入上述已执行结果。

### 6.2 主线程集成后仍应执行的集合

- **规则/默认**：2026默认快照不变；2027正式规则的heavy开局/装配后、步兵Health+Cooling、0/0/750允许量、600控制度、价格、buff、RMUL1v1独立mode；RMUC不得借用RMUL事实。
- **持久化**：旧文件缺Season→2026；unknown Season、rule_version、profile不得静默降级；启动前先同步年度门；场景/阵营/角色切换不恢复旧authority。
- **UI/交易**：技能草稿不发wire；2027预览没有旧demo/map/buff；旧hold/确认弹窗/交易/ack、raw feed缓存跨年作废；相同角色兼容key不激活旧Hero/UAV能力。
- **链路安全**：0x5A fire恒0/掩码0x000F/active前置/单调timestamp/deadman归零/云台单出口不变；DT7/PRM1固件证据不被规则年替代。保留本轮已收口的通用0xA5 raw writer最终年度/epoch检查；不得用mock诊断或帧CRC正确冒充年度链路证据。
- **未来2027 wire**：未注册profile/未知消息fail-closed；错误proto年/规则年/状态年；旧接收队列、retained、延迟回调、断网重连QoS、旧签字恢复；最后enqueue而非只UI处做断言；新协议样本必须独立于旧golden。
- **现场另列验收**：官方网口/权限、ClientId与回读身份、实际视频/数据时延、地图原点与镜像、RFID/经济回执、装配/首发认可、物理急停与断流归零。没有这些证据不能把软件离线通过称为“2027可上场”。

## 7. 交付判定

**可交付：2026向后兼容的年度边界；有来源的2027离线规则预览；明确拒绝跨年官方MQTT上行及2026状态投影。不可交付声明：2027官方通信已适配、V2等于2027、官方2026软件证明2027支持、或所有设备已现场安全验收。**

已收口的产品边界：官方MQTT新建连接/start/retry/cleanup恢复与实际enqueue、manager官方消息/投影/资格、通用0xA5 raw/write/send/write_frame到真实驱动的最终年度门。仍须主线程完成UI/raw feed与交易缓存年度失效、赛季规则/持久化集成回归；仍缺2027正式通信定义及现场硬件证据。已进入驱动/网络的字节不可撤回，这一物理限制不是新请求可绕过的软件口子。
