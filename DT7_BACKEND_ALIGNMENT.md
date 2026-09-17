# DT7 后端对齐（2026-09-17）

本轮在 `deepseekv4flash后端` 修改源码、离线测试及发布脚本。
**没有打开真实硬件口、没有开启用户 Real TX/Arm、没有生成现场证据。**
此前 `DT7_CONTROL_AUDIT.md` 的未修复项是历史基准，不是本轮完成后的状态。

## 当前硬闸门

- 正常 DT7 真发必须同时满足显式 RobotLink/Allow Drive/Direct DT7/Real TX、
  `MATCH_ARMED`、独立 `dt7_control` 能力和权威比赛阶段。
- 串口发送层再次检查授权；不能借 MQTT 的 `core_kmc` 或资格令牌绕过。
  DT7 自己限频 30 Hz，不使用 MQTT 75 Hz 的节流记账来切换 live 状态。
- 每次实际发送复核资格有效期、双人签字、运行时机器人/赛制/图传源以及
  DT7 线格式 profile SHA-256。保留现有 MQTT 协议及 Arm 的真实 MQTT 前提。
  当前不支持脱离该核心资格体系单独 Arm DT7。
- readiness 分别消费 DT7 独立授权及实际 route；关闭 Real TX/Allow Drive、
  多来源冲突、没有当前 writer、配置身份不匹配时不能把 DT7 报为可用。
- 写口异常或短写会锁定、清输入并保留中立帧重试；恢复连接不能恢复旧运动。
  改串口/profile/mock 模式时先归零旧 writer；归零失败不能丢弃旧 writer。
- 专用 `release()` 只允许全中立字段，可绕过 LOCKED/ESTOP 发送。
  无法送达时仅保留重试，绝不能把主动补零当作车端 watchdog 的证明。
- E-stop 必须先显式解除，不能直接用 Arm 或新建资格令牌解除。
- `DT7 Allow Fire Keys` 同时约束 Q/E 和鼠标按钮；探针强制清除鼠标和开火输入。

## 探针与现场流程

1. 停用发射、移除弹丸、架空车辆，安全负责人持独立物理急停。
   核实实际固件 X 键无动作；本项目无法为未知固件作此保证。
2. 创建绑定机器人、固件 SHA-256、赛制和正式图传源的资格会话。
3. 使用 RobotLink → `Run DT7 Link Selftest`，明确确认后才能产生短期令牌。
   客户端使用已有 writer，不能同时开 CLI 抢串口。
4. 自检先采 1 秒发送前基线，再按 X 900 ms，停发观察 1600 ms。
   只接收新到达且有效的 `km_key` 样本；缓存重复、过期、未来时间、NaN、
   非整数、越界值不参与判定。发送前已含 X 时不允许 PASS。
5. `dt7_link_test` PASS 仅证明探针键位改变，不证明电机停机。
   `STUCK/EXPIRES/NO-READBACK` 是单独诊断，不能取代实测执行器。
6. 现场分别测量独立物理急停、DR16/DBUS 失联到执行器归零，验证重连仍无运动。
   在现有 MatchReadiness 操作组选择 `Record DT7 Safety Test`，由在场观察者
   录入实测时延及明确观察声明。两项必须有限且在 0–500 ms 内才能 PASS。
   这是人工物理观察记录，不是软件自动证明。未实测必须取消。
7. 完成原有全部核心技术门、soak 和双人签字后，再人工 Arm。
   任何技术重测都需重新签字；DT7 两项动态证据同样 24 小时过期。
   未验证的 PRM1 自瞄/小陀螺能力继续 LOCKED MOCK。

CLI 仅可在关闭占口客户端后单独运行。现在仅允许 `--keys X`，
WASD/SHIFT/开火组合在打开任何端口前拒绝。CLI JSON 是诊断，不会自动 Arm。
`--hold-test` 在观察窗口内停发，结束/异常时仍尝试补中立帧。
丢失 USB、杀进程或失联时软件不能保证送达，必须靠实测车端安全机制。

## 配置与便携发布

- 不修改用户 `configs/default.json`、`_pdf_extract.txt` 或当前 user_data 配置。
- 源码 profile 位于 configs；便携版位于 `defaults/dt7_profile.json`，统一通过
  RuntimePaths 解析。缺失/损坏时拒绝真发，不静默启用确认默认值。
- profile 身份包括 reserved 通道中值、波特率、限频、CRC、载荷及鼠标限制；
  路径和说明文字不影响线格式身份。
- 发布脚本从指定 Git commit 复制 profile、列入关键哈希，运行 DT7 专项。
  **本轮没有重建 release EXE/ZIP；旧包不包含本轮修改。**

## 验证边界

`tests/dt7_alignment_test.py` 使用真实安全状态机与 HMAC 证据管理器，
但端点和物理记录全部是临时目录中的 **OFFLINE FIXTURE**，不是车辆证据。
旧帧/串口单元测试中的 OfflineDt7Safety 只用于隔离传输层，产品不得导入。

专项覆盖授权/令牌/过期/篡改异常、鼠标开火门、发送前基线、坏回读、短写、
归零重试、失败换口保留 writer、机器人身份变化、profile 绑定及便携缺资源。
测试结果见本轮提交说明；软件通过仍保持 **NOT READY FOR REAL MATCH**。

本轮验证结果：51 个不同回归/冒烟入口最终 exit 0；DT7 专项 96 checks，
协议回归 198 checks。真实 Windows OpenGL 两套运行时冒烟通过，四种分辨率
26 张前端捕获及 100 次经济场景恢复通过。检查了恢复后的 HUD 截图。
编译、Git diff 空白检查及 PowerShell 发布脚本解析通过。
扩展桥接回归最初发现计数字段的跨线程断言竞态，改为等待有界计数提交后
连续重跑三次通过；没有更改生产桥接字节流。
缺少外部固件树/厂商 dump 的交叉核对仍是跳过项，不属于已验证现场证据。
本轮没有测量真实摄像头持续 FPS，截图 FPS 标记不得作为实战性能结论。
