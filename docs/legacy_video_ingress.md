# 旧图传：接收入口与验收边界

本次增加的不是另一个样片播放器：`CameraFeed → Source → Legacy VT02 UDP`
会实际监听 `0.0.0.0:8080`，把收到的原始 H.264 字节送入常驻 FFmpeg 解码器，
再通过正常后端/HUD 路径显示。它与 `Shark UDP` / `UDP HEVC` 的 8 字节分片头
以及 `Native 0x0310` 的 300 字节数据块完全不同，不能互换。

**这是已实现的软件接收入口，不是整条旧硬件链路验收通过。** 目前没有在用户的
接收器、驱动、固件与 Windows 显示环境上验证。尤其不能把 UDP 监听成功当作
接收器已初始化，或把本地回放解码成功当作无线图传成功。

## 官方依据和版本范围

官方 2019 VT02 客户端，以及核验过的 2025/2026 客户端旧版渲染路径，其视频入口 `UseRenderingPlugin` 建立 `UdpClient(8080)`，
接收到的 UDP 数据未经裁剪传给 `RenderingPlugin.PushVideoData`。对随包原生插件的
静态追踪显示：数据向量进入持续的 `av_parser_parse2`，解码器/解析器初始化选择
H.264。没有 Shark 分片头剥离，也不是一包一帧。只静态阅读官方文件，没有运行其
安装器或 DLL；不在本仓库分发官方二进制或复制反编译源码。

2025 11.0.1.128 与最新 2026 12.0.0.213 中的旧版入口也已静态核验，使用相同原始 H.264 8080 契约；详见[官方软件证据](reviews/official_client_engine_evidence_20261020.md)。这证明特定版本的接收/解析契约，不证明所有 VT12 固件都兼容，也不证明 2025
客户端的新 USB 视频路径与它相同。2019 接收器的串口配置、频点/机器人选择与
状态轮询是另一条控制链，当前实现不伪造或自动发送这些命令。

## 保留官方客户端的旁路桥接（建议先验证这条路径）

`CameraFeed → Source → Legacy Official Bridge` 仅监听 `127.0.0.1:18080`。
可选的 `tools/legacy_video_bridge.py` 通过**已安装的 Npcap** 在明确选择的接收器
网卡上只捕获指定源 IP → 本机 IP 的 UDP 8080 数据，并把原样 H.264 负载送到
该回环端口。官方客户端继续独占 8080、串口、角色和频道配置，POLAR 不与它抢口。

这是 POLAR 自己的只读工程桥接，**不是 DJI 发布的输出 API**。本次仅完成离线
报文/生命周期与回环解码验证：真实 BPF 编译、Windows/Npcap/RNDIS 捕获和实际
接收器持续画面三个条件都尚未验证。不得据此宣称已经连通用户的硬件。

在已有 Npcap 且官方客户端已正常显示真画面的 Windows 电脑上，由操作者执行：

```powershell
python tools/legacy_video_bridge.py --list-interfaces
python tools/legacy_video_bridge.py --interface "\Device\NPF_{实际网卡标识}" --receiver-ip <实际接收端IPv4> --host-ip <该网卡实际IPv4> --duration 10
```

不要照抄占位符或猜接收端 IP。选择输出列表中真实的接收器 RNDIS 适配器，确认
其已分配的地址；首次只运行 10 秒。确认输出的转发/丢弃计数和终端真画面后，
可去掉 `--duration` 连续运行，用 Ctrl-C 停止。程序不自动安装驱动、不提权、不改
网卡/防火墙、不以混杂模式捕获、不记录原始视频、不向非回环目的地发送数据。
缺少 Npcap/权限/合适链路类型会明确失败。畸形、截短、校验失败、IP 分片与错误
源/目的端的包会拒绝，而不是拼成视频。真实网络若出现 IP 分片，需要进一步验证
及单独设计，当前不会悄悄重组。

先在 POLAR 选择 `Legacy Official Bridge`，再启动桥接；独立诊断时先退出同一
回环监听，再运行：

```sh
python tools/video_ingress_probe.py --transport legacy-official-bridge --duration 10
```

桥接重新启动通常会换 UDP 源端口。终端采用端点锁定，**此时需要把视频来源切到
Synthetic 等其他来源，再切回 Legacy Official Bridge**，才会接纳新会话；不允许
超时后悄悄接受另一个发端。端点选择不是认证，原始视频只应在可信本机环境使用。

[官方 Npcap 捕获 API](https://npcap.com/guide/wpcap/pcap.html) 是本桥接的通用
捕获接口依据，不构成 DJI 对此组合的兼容保证。程序不会替用户接受驱动许可或
更改安装权限。

## 现场使用前提

1. 先确认实际接收器型号、固件和可正常工作的官方客户端版本，并用官方工具完成
   已获授权的驱动、网络、角色及频道配置。不要把新图传的 USB 接口或 2026
   自定义客户端的 `192.168.12.x:3334` 设置机械套到旧设备。
2. UDP 8080 必须由一个进程独占。官方 2019 显示程序自己也监听 8080，不能让它
   与 POLAR 同时竞争该端口。**是否能在移交端口后维持已配置的接收端，或通过
   经验证的官方控制进程保持它，目前仍需实机确认。** 没有确认这一点，不能说
   本入口已经独立完成“接收器启动”。端口被占用时错误会显示在后端统计/诊断中。
3. 在已确认接收端仍持续送流的前提下，选择 `Legacy VT02 UDP`。此模式固定使用
   官方旧入口 8080，不读取 `UDPVideo` 的现代转发端口设置。不启动官方进程，
   不改网卡、防火墙、USB 驱动、串口、国家/地区或无线频点。
4. 如需单独核对入口，先关闭 POLAR 自己的同一监听，再运行：

   ```sh
   python tools/video_ingress_probe.py --transport legacy-vt02-h264 --duration 10
   ```

   默认现代分片入口可用：

   ```sh
   python tools/video_ingress_probe.py --transport shark-framed --host 0.0.0.0 --port 3334 --duration 10
   ```

   诊断只接收、不发包、不录制原视频、不注入样片，JSON 输出到 stdout。采样最多
   300 秒，随后请求停止并最多观察清理 5 秒；清理未确认会明确报告，不把等待
   超时改写成成功。`hardware_verified` 始终为 false。真实画面在结束时仍新鲜且
   清理完成才退出 0，但这个退出码仍不是硬件/比赛资格认证。

## 不掩盖的限制

- 2019 原始 UDP 没有已知的序号头，无法可靠区分丢包、乱序与重复包。解码恢复
  等待新的 SPS/PPS/IDR，不靠拼出假的“完整帧”掩盖损坏。原始流计数为
  `stream_blocks_received`，不会冒充 `frames_received`；只有真正解码输出才有
  `decoded_connected`。瞬时大量小包也可能溢出系统 UDP 接收队列；桥接发送计数
  不等于终端无损接收，必须观察后续 GOP 恢复与新鲜解码画面。
- 同一个接收会话只接受首个有效来源端点，其他来源的分片不能互相拼接。这个
  选择**不是来源认证**；原始流没有独立包头，所以首个非空数据包即可选择来源。
  发端重启导致源端口变化，需要显式停止/重新启动接收。官方源端口稳定性仍待
  实机确认，不允许超时后悄悄换成另一台电脑的画面。
- 切换旧原始流和现代分片流时，先撤销旧画面与回调，再等待旧 socket/解码进程
  释放后选择新契约。退出/同步停止同样清除画面。Hero 部署仍独占 Native 0x0310。
- 旧入口使用独立来源标识 `legacy_vt02_udp`，不得套用现代官方 UDP 的比赛资格。
- 不自动回退到 Webcam、Synthetic、录屏、NDI、裸 USB 或未知 DLL。
- `UDPVideo → Reassemble` 仅为历史配置兼容项，已标明弃用。关闭它不会启用裸流；由明确的 Source 选择解析契约。

## 仍需完整验收

相同设备上记录官方正常工作的控制条件，然后验证：驱动/网卡状态、控制会话
初始化、8080 所有权移交、真实连续视频、断开/重连、缺包/失鲜、关闭资源与恢复。
每一步分别记录，不能把“收到字节”“解析成功”“解码成功”“HUD 显示”合并成一个
已连接状态。本次离线和回环测试只能覆盖软件部分。

## 可复核的软件来源

- [官方 VT02 产品页](https://www.robomaster.com/zh-CN/products/components/detail/1414)
  的 VT02 下载项实际链接到
  [RoboMaster Client_CN_v5.0.2.37.7z](https://rm-static.djicdn.com/tem/17348/RoboMaster%20Client_CN_v5.0.2.37.7z)。
  产品页标签与下载文件版本不完全一致，因此这里以归档内容的 5.0.2.37 为准。
- 归档大小：99,813,709 字节；SHA-256：
  `e45303baf581bbe803791440319abeaa9db613e57890627295354a2e7c3cd11d`。
- 随包 `DJIVideoParser.dll` SHA-256：
  `ced2ca59ecb7b15ed916bb8b683d395ffbeb75f3b7b5b0420bc83e2ea1141207`。
- 静态核对点：托管 `UseRenderingPlugin.Start/RcvUdpThread`；原生
  `PushVideoData` RVA `0x124fe0` → `ParserData` `0x1546e0` → 数据向量队列，
  解码循环 `0x1383f0` 在 `0x1385d1` 调用 `av_parser_parse2`；初始化
  `0x138d80` 对解析器和解码器均选择 H.264 codec ID `0x1c`。这些地址只适用于
  上述精确 DLL，不是供客户端调用的 SDK。
