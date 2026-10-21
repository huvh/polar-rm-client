# 2026-10-20 后端修复验证范围

本记录覆盖软件修复与离线/回环证据，不是接收器、机器人、Windows 或比赛资格
验收，也不声称“所有可能问题已消除”。分支为
`fix/legacy-video-ingress-20261020`，基于主分支
`83ac83064f21fe06ffa3baaff22efac4647e687f`；未合并主分支。

## 可复现问题与修复

- 不同 UDP 发端用相同帧号可混拼图像、破坏对方未完成帧：改为会话内来源端点
  所有权；明确重启才能换来源，畸形首包不得抢占现代分片来源。
- 旧图传原始 H.264 8080 被误当成现代 3334 分片流：增加独立直收契约，以及
  保留官方客户端控制/显示的可选只读 Npcap → 本机 18080 工程桥接。
- 同步停止保留旧 MJPEG、H.264/HEVC 尺寸统计为零、并发撤销仍能报告旧新鲜度：
  清除撤销画面，按当前解码器报告尺寸；读取后校验视频/解码/进程代次、对象身份
  和最终时间，拒绝过期及未来时间戳。
- MQTT CONNACK 被误作订阅成功、失败 SUBACK/订阅超时缺少门禁、retained 实时
  消息及旧回调可冒充新证据：增加独立订阅就绪与会话准入。
- 比赛阶段被迟到 HUD 投影重新刷新：只按实际 GameStatus 收件时间维护新鲜度，
  超时撤销授权，最终物理发送前复查。默认一秒是本地策略，不是官方时限。
- 输入 reset 异常跳过独立的旧命令/负载/待发队列清理：保持物理归零优先，尝试
  每个独立清理步骤，保留第一个异常和重试门禁，不发送成功通知。原有 F12 次数
  断言不变，新增单失败/双失败、缓存撤销、原异常保留与重试回归。

使用步骤与硬件边界见[旧图传说明](../legacy_video_ingress.md)、
[官方软件静态证据](official_client_engine_evidence_20261020.md)、
[阶段新鲜度策略](../MQTT_STAGE_FRESHNESS.md)。未复制官方二进制或反编译源码。

## 环境与复现命令

Linux 云环境；Python 3.12.14、PySide6 6.8.2、OpenCV 5.0.0、NumPy 2.5.4、FFmpeg。
Qt offscreen 不算 Windows 原生窗口/GPU 验收。套接字测试使用本机回环与隔离端口，
不连接用户的接收器、机器人或网络。

从仓库根目录使用项目验证环境运行：

```sh
python tools/verify_all.py --list --profile all
python tools/verify_all.py --profile offline \
  --json tmp_quality/verification.json --log-dir tmp_quality/logs
python tools/verify_all.py \
  --test test_udp_ingress_evidence --test test_legacy_vt02_ingress \
  --test test_decode_publication_epoch --test test_legacy_video_bridge \
  --test test_mqtt_subscription_admission --test test_mqtt_retained_evidence \
  --test test_stage_freshness --test test_backend_input_owner
python tools/quality_gate.py
python tests/api_freeze_test.py
git diff --check
```

缺少外部前提时，统一入口会如实返回 SKIP/INCOMPLETE 和非零退出码；局部通过不能
代替全量聚合。不要删除锁、杀未知进程、关闭断言或把缺少依赖改标为 PASS。

## 统一聚合记录

### 首轮完整 offline 执行

源码提交 `241b00abdac6ae96f4d5f484f663057f9c8a1004`，2026-10-20 15:41:55 UTC 开始。
发现 454 个套件，选择 offline 448 个，另执行设置隔离审计，总计 449 项结果：
**424 PASS、13 SKIP、5 INCOMPLETE、7 FAIL，整体 NO-GO**。
声明范围 800 个文件的前后指纹一致：
`1b24a09fa616af877442120fa187b201e11c80e585cc4d4d77d69bf0b864b7c2`。
保留原失败记录，没有用后续局部通过覆盖它。

七个失败分别是：未来时间戳夹具、未建立并行 MQTT 会话的长驾驶夹具、两处向已
撤销 MQTT 会话注入的窗口夹具、缺少显式 transport mode 的 AST 夹具、过短的
子进程启动/超时夹具，以及真实的输入清理异常隔离缺陷。修复只让夹具表达正常
的已准入会话与过去时间，原数值/运动/事件断言不变；超时夹具仍保留 60 秒睡眠、
超时分类、已捕获诊断及总耗时小于 3 秒的检查。

### 修正阶段与复跑

修正源码提交 `0335c2ca31e52f0008dbb09cd9611a9a9790a63e`，树
`d904464997f86070388ca48ac2aec8d3d7c2b3b8`。
统一入口的 19 个修正/安全套件全部通过：221 个 unittest 方法及 251 个脚本断言；
零跳过、零不完整、零失败。800 个输入的前后指纹一致：
`06f2f2aa42d0372737e9c7dad23f7ebd9b88d88da4930e4b5b0790864bc7558a`。

相同源码于 2026-10-20 16:13:10 UTC 开始完整 offline 复跑，同样 448 个套件加
设置隔离审计，结果：**428 PASS、13 SKIP、5 INCOMPLETE、3 FAIL，整体仍为 NO-GO**。
800 个输入前后指纹均为上面的 `06f2…7558a`，原七个失败在完整复跑中全部通过。

剩余三个失败来自未改动的测试：

- `test_device_manager_nonblocking`：1000 次成功的 writer-busy 返回耗时 70.1 ms，
  超过原 50 ms 门槛。非阻塞锁准入未变，每次均在驱动持锁时返回，不能把该计时
  失败解释成等待驱动锁；额外耗时的来源尚未证明。
- `test_fullscreen_input_extended`：offscreen 设置入口在一秒内未完成。
- `test_jello_settings_keyboard`：offscreen 设置面板在原等待结束时仍不可见。

聚合完成后，仅把这三个**源码、断言和期限均不变**的套件串行复跑一次：37 个
方法全部通过（7 + 14 + 16），无跳过/失败，指纹仍相同。保留两次结果；这说明
失败未在该次受控重跑复现，不证明其根因已消除，不改写全量 NO-GO，也没有为了
获得绿色结果反复启动完整聚合。原生 UI/性能环境仍需单独稳定性验收。

最终修正源码的 API 冻结检查通过：1114 个既有成员、540 个签名、78 个显式私有
调用缝。静态质量通过：229 个模块、3570 个函数、零初始化环。`git diff --check`
通过。这些门禁不代表硬件或现场联调。后续提交仅更新说明与审计，不更改所测源码。

## 独立与分阶段证据

以下分组存在重复覆盖，不相加为一个“总通过数”，也不代替上面的聚合结论。

- 阶段一：独立 25 项真实 UDP/损坏/混发/重连/关闭检查和 78 项仓库回归通过。
- 来源路由/HUD/catalog：76 项通过，catalog 基线只接受新增来源与明确弃用说明，
  保留默认来源及其他字段。
- 代次修复快照：独立 60 项通过，含现代 UDP 25、原始入口 16、捕获解析/清理 9、
  实际 helper UDP → 解码 2、撤销竞态 8；仓库 133 项中 132 通过、1 项 BPF 跳过。
  最后的同代次年龄重查另有 19 项回归通过。原始流跨起始码/SPS/PPS/切片边界进入
  真实 FFmpeg 并得到 160×120 像素，同时验证损坏恢复、来源拒绝、切换及停止。
- 桥接原有 17 项中 16 通过，1 项因缺少原生 libpcap/BPF 编译器明确跳过。
  独立报文检查覆盖截短、VLAN、IP/UDP 长度/校验、碎片、过滤与清理；30,000 条
  随机/变异记录无未预期异常。这些不算 Windows 捕获验证。
- 生命周期 73 项通过，另有来源切换失败/重试对抗检查：旧 owner 未关闭不得
  重绑，周期刷新不偷偷重试，过期请求不得恢复旧来源。
- 前述独立快照的 API 与静态质量结果不冒充最终源码；最终修正后的结果已单列于
  上节。所有阶段均保持开火位为零、仅 W/A/S/D 驾驶及物理归零门禁。

## 仍未通过的外部验收条件

1. 原生 BPF 编译器/过滤执行、Windows/Npcap 在实际 RNDIS 适配器上的权限与捕获、
   真实接收器连续画面是三个独立未验证条件。
2. 需要确认实际型号/固件、官方正常控制会话、真实无线视频、断开重连及所有权
   移交。全官方客户端可保留在工程桥接路径；单独 helper 不被当作已证明的启动器。
3. 原始 UDP 无序号，也不保证可靠传输。冷启动大量极小包可溢出系统队列；本地
   转发成功不等于逐字节收到。测试保留该失包证据，并核验后续完整 GOP 恢复。
4. 完整聚合依赖外部准备项：PowerShell 发布归档环境、显式选择并准备的
   StandardRobot++ 固件/reference、CRC8_CRC16.py 对拍参考、指定旧 dump，以及
   原生 libpcap/BPF。旧 baseline 安装型补丁测试未在只读验证中执行。
5. 官方学生客户端和赛事引擎已下载、校验并静态检查；Linux 上没有运行 Windows
   程序、驱动安装器、许可确认或现场赛事引擎联调，因此不提供这些层面的 PASS。
