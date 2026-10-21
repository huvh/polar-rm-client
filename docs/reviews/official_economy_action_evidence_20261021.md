# V2 经济动作：官方事实与实现边界（恢复重建版）

日期：2026-10-21。由中断前保留的官方静态取证重建。原参考目录及补丁一度丢失；本次已重新恢复client213、V2协议和RMUC规则，PDF与descriptor哈希重新核对一致。下列RVA与价格沿用版本固定的已核事实，并可在恢复资料复核，不是当前产品新树已经实现或通过运行验收的证明。当前恢复基线为 `222899de17d211755b7a0a3b2851144ff8016c6c`，完整重建和新测试另记于 [全后端审计](full_backend_coverage_20261021.md)。不运行官方程序、硬件或购买请求。

## 来源与适用范围

- [通信协议V2.0.0](https://bbs.robomaster.com/wiki/20204847/811363)，2026-06-26，§2.2.25、§2.2.33–34。
- [RMUC2026规则](https://bbs.robomaster.com/wiki/20204847/809871)，中文V2.2.0，2026-08-07；PDF21018604字节，SHA256 `88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5`。历史曾重新下载并渲染印刷页77/114复核公式与哨兵条款。
- client12.0.0.213 ZIP SHA256 `661498326b6a0047d5cf73a4f9ceede3297cba4b0e745aa49c69a46eba873374`；GameAssembly `5ba634258fc712f98d1c30bed50eaa9d53d4b6dfad797a7df68e1163e9addba9`；metadata `885a6963b1758199600150439a346e043d920ee3ed2182255e132407221c6e3c`。
- `SendCommonCommand` RVA0x284c80、六分支跳表0x285a88；`SendSentryCtrlCommand` RVA0x287fd0、跳表0x28879c。历史跳表从PE数据独立读取，不仅凭字符串推测。

**V2协议不等于RMUC规则版本。** 本表费用仅有RMUC7v7 V2.2.0依据，不可套RMUL3v3或未知赛制。生产应绑定显式当前配置、实际state/qualification owner及profile/robot，确认中和最终发布前再查；这只是显式赛制一致性，不冒充官方wire认证。没有来源时拒绝本套报价，不默认RMUC。

这些静态实现只绑定该官方版本。内部转发命令不得另造为POLAR接口，生产仍用公开MQTT protobuf。原始官方程序和反编译全文不入仓库。

## CommonCommand：参数、角色与价格

| cmd | 官方意义与213参数行为 | RMUC基础价/合法角色与约束 |
|---|---|---|
| 1 | 本地17mm允许发弹量，Param直接数量 | Infantry，每10发10金币；正10倍数。Sentry不能借Common绕干预费 |
| 2 | 本地42mm允许发弹量，Param直接数量 | Hero，每1发10金币 |
| 3 | 确认免费复活，忽略Param | 地面Hero/Infantry/Engineer，需自身dead/pending/can_free；基础0 |
| 4 | 付费立即复活，忽略Param | 同上；自身fresh can_pay与gold_cost_for_respawn真实报价，不用猜等级公式替代 |
| 5 | 远程补弹，**忽略Param**；Hero固定10发42mm，其余固定100发17mm | Hero/Infantry每请求150金币一包，不能做数量倍率；fresh脱战/can_remote_ammo |
| 6 | 远程回血，忽略Param；官方内部取费 | Hero/Infantry（Sentry另走干预）；fresh脱战/can_remote_heal、正且未满HP；`50+ceil((420-T)*20/60)` |

本地3..6要求param=0是明确产品规范化，不宣称wire只能0。cmd5=100不是买100份，不能向用户承诺多买。

表5-6的17mm1000、42mm100是**整队兑换上限**，不是本机剩余额度或单次wire上限。采用单次≤1000/100是本地保守界限，仍无法知道队伍剩余购买额度，最终服务器判断。公开feed没有完整累计购买计数。

本地补弹需补给区/基地增益点/前哨增益点等占区条件。公开25条feed没有充分占区证据，不能显示为已满足；若产品允许受监督请求，必须明示服务器决定。远补/远疗脱战、6秒后生效；远疗按生效时最大血量60%，期间战亡不退款。

公式边界：T=420→50，419→51，359→71，0→190。20在ceil内，不能误写为每整分钟加20。地面复活比较价 `ceil((420-T)/60)*80+level*20`，用于有明确依据的比较而非覆盖实际RobotRespawn报价；Engineer可3/4，不能远疗6，也不能推断Sentry等级在1..10。

旧V1经济事务5秒等待短于6秒服务生效，不能复用为V2“最终失败”；超时只能未确认，不自动重试。HP/弹量/金币变化都不唯一关联本次请求。

## 请求者与目标必须分清

`Utility.GetRobottypeByRobotID` RVA0x327640，红/蓝跳表0x3276d4/0x327700：1/101→type2 Hero；2/102→3 Engineer；3/4/5(+100)→1 Infantry；6/106→5 Air；7/107→4 Sentry；8/108→6 Dart；9/109→7 Radar。`robot_type`不是机器人ID。

`SendSentryCtrlCommand`首先限制当前type5，故是**空中6/106发给同队哨兵7/107**，不是Sentry自己作为MQTT来源。`GetGuardRobotID` RVA0x327180按当前阵营返回7/107。

`SyncRobotPerformanceSelectionSync` RVA0x274ec0的前两字段是自身shooter/chassis，第三字段经GetGuardRobotID取同队哨兵控制方式。0自动/1半自动有协议支持。`SyncSentryStatusSync` RVA0x275e70同样取同队哨兵姿态；`is_powered`为强化，不是电源。

`SyncRobotRespawnStatus` RVA0x275490对当前type5直接返回，空中不收到自己的这类复活同步，更不能将其作为目标哨兵报价。Air的Static/Dynamic/Respawn也不是Sentry状态。

## SentryCtrlCommand：固定数量与干预费

| cmd | 213实际请求 | 基础费用 | 公开目标字段仍缺什么 |
|---|---|---|---|
| 1 | 本地固定50发17mm | 50 | 占区、整队剩余额度 |
| 3 | 远程固定100发17mm | 150 | target脱战、can_remote_ammo；6秒延迟 |
| 4 | 远疗 | 公式基础价 | target脱战、can_remote_heal/HP资格；6秒延迟 |
| 5 | 免费复活确认 | 0 | target pending/can_free |
| 6 | 付费立即复活 | 当前目标报价 | target can_pay/quote不可见，且是否已含干预费不明 |
| 7/8/9 | 普通攻击/防御/移动姿态 | 无独立商品价 | 5秒CD、当前姿态、服务器条件 |
| 10/11/12 | 对应强化姿态 | 无独立商品价 | 每种强化累计≤15秒，公开feed无完整累计 |

schema只有command_id不能单靠它知数量，但版本固定静态分支已证cmd1常量50、cmd3常量100。不能再说数量永远未知，也不能说已经真机执行。

规则§5.6.4：自动Sentry每次人工干预另50金币，半自动不收此项，覆盖地图转发/本远补弹/回血/复活/姿态。半自动不代表商品免费。因此自动/半自动合计：本地50发100/50；远程100发200/150；普通免费复活确认与姿态50/0；远疗基础公式+50/0。

mode必须由当前session真实`RobotPerformanceSelectionSync.sentry_control`逐字段新鲜观察，不能本地默认0补证。“比赛开始默认自动”是规则，不是当前已观察自动。至少还缺target连接/场内/alive/脱战/can、respawn pending/free/pay/quote、姿态CD/强化累计。`GlobalUnitStatus`的HP/弹量不能补齐这些字段。

允许1/3/4/5/7..12时只能明确说“费用可估的受监督服务器请求”，不能说目标已可执行。**cmd6保持拒绝**：无目标报价也不知是否含干预费，不拿Air报价或硬套Sentry等级，不盲加50或声称费用上界已经证明。

## 地图、Performance和Dart的相关界限

- MapClickCmd range0指定、1不含Sentry、2含Sentry，7bytes目标；显式己方7/107或range2涉及干预，必须独立economy确认，不能借core_kmc免费发。官方接收方法没有一律只准Air的角色拒绝，不能从Sentry独立命令反推Map也只Air。
- field3虽然官方变量名mode，含义是标记类别；field6名type，含义是坐标/敌方模式。不能为改命名互换wire方向。213 OnMqttSubProto RVA0x283860原样转给SendMapClickInfoNotify0x286680；custom分支用5，PDF用4，实际dispatch无转换。争议custom明确拒绝，不猜5，普通1..3保留。
- SendRobotPerformanceSelectionCommand RVA0x287590：Air自身shooter/chassis0不动作，控制己方Sentry mode0/1需内部stage2；SyncGameStatus0x271d70减1，故公开PREPARE1，不能误当SELF_CHECK2。Hero/Infantry自身性能另走字段级角色域。人工确认、单次监督与锁回不因“官方等价”删除。
- SendDartCommand RVA0x285ea0限制当前type5 Air，将当前阵营交给同队Dart，不是8/108来源。target1..5是靶型，open=true另发开闸、false无关闭动作，launch_confirm为独立动作。本轮表单保留launch=false，不新增发射授权。
- Air2免费优先后持续1金币/秒，无固定总价；Air3的解除反制估价为同等级地面复活比较价×2，需实际Air等级，照射状态不等于已锁定可解除，后续总价不可冒充确定。

## ACK、最终发布与恢复验收

Common没有独立响应。SentryCtrlResult只有command_id/result_code0成功，无nonce；213 Sync方法映射为空实现RVA0x26c990，不保证会发。旧QoS重投、同编号并发不能当本次唯一确认，客户端序列号不能创造服务器没承诺的关联。

统一要求当前MATCH（本地策略）、fresh own identity与ClientId一致、明确连接/场内、已知红牌拒绝、逐字段原始receipt新鲜、当前预算。目标未知与请求者状态严格分开。现场资格/Arm/economy权限/SUBACK/owner/epoch/限频都保留。

确认UI可在新同值snapshot到达后重新核对同一价格与条件，但传给后端的必须是当时最新不可变对象；initial/final均identity检查，不允许等值copy或final新消息复用确认。payload固定，模式/会话/价格变化必须重新确认或拒绝，最多有界一次重新报价，不自动重发。

恢复新树应重验：固定50/100/一包、数量非法/布尔/浮点/错口径/错角色、Engineer3/4但非6、419秒价格51、不同Sentry mode与过期缺失、Sentry6拒绝、RMUL/未知模式拒绝、确认中换session/owner/回合、最终SUBACK/epoch/权限撤回、QoS旧结果不造ACK。历史所有PASS只作复现线索，当前结果由新报告逐项填写。

本次恢复后的新验：2026-10-21 04:06 UTC，审计者只读复核当前 `economy_rules.py` 并独立运行 `tests.test_v2_economy_rules` 13方法，全部通过；同进程 `test_backend_policy_boundaries` 7方法通过。验证到纯规则层：Common准确口径/数量/真实复活报价、Engineer仅3/4、Sentry固定量/控制模式干预费、目标未知明示与cmd6拒绝。当前RMUC scope和最终发布仍需由MQTT/UI另行集成验收，不能用这13项替代。

2026-10-21 04:10 UTC，新树 `6735909` 的MQTT经济准入10方法及上行准入/域16方法由审计者独立运行全部通过：RMUC实际owner、同值不同snapshot、确认缺失、最终scope/权限/SUBACK变更均拒绝；付费Map不借core通道逃费。测试使用fake broker，UI确认链尚未在这次运行中验证，不构成现场执行或支付成功证明。

2026-10-21 04:15 UTC，新树 `b5f20bd` 的经济UI11、Performance UI4、事件表单12、manager7独立通过；另有隔离进程真实Qt Air18通过且保护探针计数0。确认取消/换owner/换赛制/价格变化、最多一次重新报价、单次token与锁回均覆盖。包式测试需`PYTHONPATH=.:tests`，首次缺同级测试import路径的失败已在总报告保留。至此本轮经济主链已有纯规则→MQTT→确认UI分层新证据，但仍没有官方服务器/实机/逐请求支付ACK，Sentry6与争议custom Map仍拒绝。

首轮完整聚合（冻结298af0b）仍为NO-GO：444 PASS/13 SKIP/5 INCOMPLETE/3 FAIL。其中两项经济相关fixture的AST切片未包括manager新增真实 `_v2_action_admission`，导致publish guard异常和Air普通路径不发送；先前focused18不能外推到这次新门。只补真实helper/import/state依赖，生产门禁不变，04:30独立publish guard26与Air18重新通过（保护探针0）。另有DT7 SUBACK fixture修后112检查通过。完整二轮尚待执行；详细失败与未验证项见总报告。

最终更新，2026-10-21 04:43 UTC：已独立核对第二轮完整JSON，冻结提交 `0f58747be4533ece2fc9c873189651db9cf2b368`、run_id `8db50feb2f4a472795dc503bf66eaa52`，447 PASS/13 SKIP/5 INCOMPLETE/0 FAIL（464套件加1派生检查）；起止823项源码输入一致。publish guard26、Air18和DT7 112 checks均在完整二轮通过，不再只靠focused。由于外部固件/平台缺口，整体仍NO-GO，不是官方执行、支付成功或现场资格证据。Sentry6目标报价、Map custom冲突继续拒绝；RC150本轮adapter与硬件factory/decoder/UI未实现，不能说只是未测试。详见 [最终验证报告](full_backend_verification_rebuilt_20261021.md) 与 [完整能力矩阵](full_backend_coverage_20261021.md)。
