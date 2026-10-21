# 官方后端参照恢复与可复核来源（2026-10-21）

这份记录说明代码修复的官方证据来源，不代表硬件、驱动、实际付款命令或端到端接入已经验证。此次只静态读取官方下载内容，没有运行官方程序、安装驱动、枚举或打开 USB/COM、发送设备命令或修改网络。

## 持久化证据包

- 文件：`official-evidence-recovery-20261021.zip`
- 大小：4,960,360 bytes；39 个文件。
- SHA256：`2dbc981c1a01a5fbe98809f508032e4ff03e51faa0653e5a1c39ff96ff63e047`
- 包内 `MANIFEST.json` 列出逐文件大小与 SHA256；`verify_evidence.py` 无需第三方库，执行只读完整性核验。
- 本轮 ZIP CRC、38 个内容文件 SHA256、descriptor 重建及 Radar fixture 核验通过。
- 包中包含官方协议 PDF、规则经济相关原 PDF 五页摘页、规则全文文本、精确 descriptor、原生/IL 静态证据、来源与复现工具。未包含官方可执行文件、400MB 原 ZIP、虚拟环境或 USB factory。
- 本地参考副本位于任务工作区的 `official-backend-reference/`；工作区可能回退，**不要把这个可丢失路径当作唯一长期凭据**。证据 ZIP 应另存为独立交付附件。

## 官方发布与版本边界

来源：[官方赛事引擎下载/发布页](https://bbs.robomaster.com/wiki/20204847/804784?source=7)。证据包的 `release-notes.txt` 保存本次公开页面文本。

1. V2.0 发布记录明确配套：客户端 **12.0.0.213 Student**、服务器/裁判端 **12.0.0.123 Student**、通信协议 **V2.0.0**。
2. **12.0.0.137 Student** 是后续 V2.2 服务器/裁判端更新，说明为修复服务器 `0x0120` 哨兵自主决策姿态切换异常。
3. 213 的 MQTT protobuf 来源是客户端内精确 descriptor；不能据此声称引擎137自身提供相同 MQTT 服务，或213/137实际配对与硬件已验证。
4. 预设诊断只能表示操作员声明的版本与所选 schema 相符。未知版本不得猜测回退，预设不得暗中更改默认配置或解锁真实输出。

本轮重新下载并校验：

| 官方来源 | 大小 | SHA256 |
|---|---:|---|
| [客户端213 ZIP](https://bbs-web-static.robomaster.com/55bea4d5b5f94a8d8adc2a5f40c225d81783394887530/RoboMasterClient%2012.0.0.213_Student.zip) | 420317398 | `661498326b6a0047d5cf73a4f9ceede3297cba4b0e745aa49c69a46eba873374` |
| GameAssembly.dll | 33987072 | `5ba634258fc712f98d1c30bed50eaa9d53d4b6dfad797a7df68e1163e9addba9` |
| global-metadata.dat | 8130256 | `885a6963b1758199600150439a346e043d920ee3ed2182255e132407221c6e3c` |
| 通信协议V2.0.0（20260626） | 2039054 | `8fdc484c58d503a3fb68f7c0515ae618b68eb2b058a8c876e1add5eeb8a7d81b` |
| RMUC规则V2.2.0（20260807） | 21018604 | `88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5` |

客户端 ZIP 的170项 CRC 全部通过。引擎137旧审阅 ZIP SHA256为 `61586fb4083399cbc5607f17e895af42b43b5199ee09522087f628e3354ea933`，429242136 bytes；**本轮未重新下载**，仅保留历史身份，不把此前工作区内容视作当前仍存在。

## Schema与行为不能混同

[官方通信协议页](https://bbs.robomaster.com/wiki/20204847/811363?source=7)及本次精确客户端提取分别证明：

- PDF为 **37个消息定义/175个描述字段**，而客户端 descriptor 为 **36种消息/167字段**。差异来自 MapClickInfo / MapClickCmd 共用8字段的 MapClickInfoNotify，不能把二者计数混为一谈。
- `custom-client-descriptor.bin`：8205 bytes，SHA256 `db398c02c9c6636852ab02693df3c51a77b9b219f836e9b1b3deb88b34091b50`。保留183段原始 base64 的元数据字面量索引及加载 RVA，可独立重建。
- PDF Radar 包装层代码片段不合法，缺字段名和 tag，且误写uint32。应以真实 descriptor 的 repeated RadarSingleRobotInfo robot_info #1 为准，不能静默修正后把它当原文。
- Radar `(100,200,2)` 与显式 `(0,0,0)` 两记录的标准protobuf黄金字节为 `0a07086410c80118020a06080010001800`，第二记录三个0字段均保留presence。官方x/y始终是cm；标志2表示高亮且定位离线，不是增益。
- MapClickCmd原始payload由 `0x283860` topic分发直接进入 `0x286680`，无前置字段转换；客户端213在 `0x2868fc` 对mode5走自定义ASCII分支，但PDF规定mode4。**争议自定义分支应禁发，不能猜改5，更不能用schema一致掩盖行为冲突。**

## 关键修复依据索引

以下均为已校验二进制中的 RVA / IL token，完整机器字节和上下文位于证据 ZIP。

| 范围 | 可复核证据 | 边界 |
|---|---|---|
| MQTT绑定 | ValidatingConnection `0x33c390`；当前机器人ID字符串比较 `0x33c781–0x33c7cf` | 内部official_cc前缀不是公开绕过入口；发布成功不是业务执行回执 |
| 自定义控制键码 | CCSPortThread `0x27fd10`、SendToClient `0x280cc0`；构造W=`0x57`在`0x2817f9` | Windows VK，不是HID usage0x1A |
| 0x0302 | helper SearchPackage token `0x0600001c` / RVA `0x25c0` | 严格30B、25ms限制；不推定私有六角度语义 |
| DT7 | RobotInput.Update `0x31b960` 在`0x31bc37`清reserved；OnSendInputStatus `0x292af0` | 官方reserved0与本地安全1024须明确区分；0x5A/0x2000链路不能一概叫私有 |
| 角色 | ID switch `0x327640`；Dart `0x285f14`；Rune `0x287c2e`；Sentry `0x2880ab` | Dart/Sentry请求者为空中6/106；Rune为步兵3/4/5及+100；不要拿目标ID当请求者 |
| 经济 | Common `0x284c80`、Sentry `0x287fd0`、GuardCtrl确认链；规则表5-6/§5.6.4 | 绑定本队目标和真实报价/模式；自动哨兵干预额外50；Sentry6报价关系未闭合不得假定 |
| 设备区分 | DeviceInfo GetVideo/GetNewVideo，RIP字符串引用 | 旧COM2ca3:001f/MI04；新COM2ca3:1020/MI02；新USB视频MI00/IN81，日志MI01/IN82 |
| USB视频 | helper token0x060000c8；RC150 `0x48d8 → 0x1008 → IAT0x9418 av_parser_parse2` | 原始增量HEVC，不是UDP3334带8B头的分片；不等于完整设备支持 |

经济规则来源：[RMUC规则官方页](https://bbs.robomaster.com/wiki/20204847/809871?source=7)。协议、原生行为、本地安全策略与未获证的硬件行为应分别陈述。

Windows独占/驱动服务/实际MI映射、设备冷启动控制初始化、硬件factory、解码器/UI接入与真机端到端资格仍未实现或未验证。本轮明确**没有恢复仅fake通过的USB接入骨架，也没有把任何探测器算作接收通路**。
