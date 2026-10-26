# 图传模块

终端图传实现集中在 `rm_client/backend/video/`。公共入口为
`from rm_client.backend.video import RmVideoBackend, ContinuousMjpegDecoder`。
本次封装保留来源配置值、端口、解码策略和资源退出契约。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `annexb.py` | NAL 识别、参数集缓存、关键帧恢复；旧图传非 IDR 接入显式启用 |
| `codec.py` | 格式识别、JPEG/BGR 转换、MJPEG 字节流切帧、本地 FFmpeg 定位 |
| `decoder.py` | 有界输入、PyAV 直出 BGR、FFmpeg 回退、最新帧、代际及进程/线程退出 |
| `udp.py` | UDP 入口、重组、编解码切换、恢复调度、接收端控制和统计 |
| `receiver_protocol.py` | 旧接收端 DUML 状态/信道请求、响应解析、A5 角度外封装和共享 CRC |
| `receiver.py` | 唯一匹配设备发现、串口独占、状态回读、信道设置、退出确认 |
| `angle_egress.py` | 单槽角度交接、临写授权/时效复核、限频、短写检查与取消 |
| `angle_protocol.py` | 出口线格式适配、VT02 单编码器元数据与兼容序号 |

数据流：UDP → 分片/字节流 → codec 识别 → Annex-B 恢复 → 解码会话 → 最新 BGR 槽
→ `BackendManager.latest_video_frame()` → 既有窗口视频适配层。
接收端状态请求与角度出口共用同一个串口所有者，不额外创建串口写线程。

`rm_client/video_sources.py` 继续提供无设备依赖的来源列表和占位提示；
`backend/video_source.py` 继续提供管理器与 UI 共用的来源切换/退出数据契约。
UI 的配置、恢复通知与帧消费通过现有管理器接口连接，解码器不依赖 Qt。
六轴输入的通用有效范围与负载校验集中在 `backend/controller_angle_protocol.py`；
`controller_angles.py` 管理授权、时效和转发，不再解释 VT02 的负载布局及固定帧序号。

前端调用 `configure_video_source()` 配置来源与信道，通过 `video_receiver_status()` 和
`controller_angle_snapshot()` 获取值快照。角度同步、授权和撤权分别由管理器的
`sync_controller_angles()`、`arm_controller_angles()`、`disarm_controller_angles()` 接入。
UI 不直接写接收信道或访问接收端串口所有者。

## 兼容与运行

- `backend/video_backend.py`、`backend/legacy_receiver.py` 和
  `backend/legacy_angle_egress.py` 保留为兼容导出，指向同一份类和函数。
- 新业务依赖公共包或对应子模块；测试替换依赖时，替换实际持有依赖的模块，
  例如 `backend.video.decoder.subprocess.Popen`、
  `backend.video.udp.LegacyReceiverControl`，不要替换兼容文件的导出。
- 纯协议和恢复门控可在没有 Qt、OpenCV、PyAV、串口库或 UDP 传输模块时导入。
  公共包按需加载实现，PyInstaller spec 显式收集这些模块。
- 旧图传原始入口仍为 `0.0.0.0:8080`，官方桥接入口仍为 `127.0.0.1:18080`；
  Shark UDP 使用原有 host/port 设置。来源配置的内部名称保持不变。
- 终端管理器默认启用旧接收端控制：UDP 监听成功后才发现唯一的 `2CA3:001F`，
  查询真实状态并按 `Legacy Channel`（1–6）配置接收信道。单独创建 UDP 后端的
  诊断工具默认仅监听；不会因导入模块或构造解码器就连接设备。
- 旧图传 H.264 优先 `av>=14`，缺少或初始化失败时使用本地 FFmpeg 回退；
  普通 H.264/H.265 保持 FFmpeg 路径。输入积压撤销整个解码会话，
  退出确认后才释放原生上下文，旧线程不能发布到新画面槽。
- 新图传仍为“暂未实现”。角度转发继续由独立授权链路管理。

## 说明与诊断入口

- [旧图传接入与证据边界](../legacy_video_ingress.md)
- [旧图传连接历史与现场接线](../旧图传连接与使用.md)
- [旧图传解码延迟与测量方法](latency_20261022.md)
- [角度直发与 VT02 单编码器适配](angle_link.md)
- `tools/video_ingress_probe.py`：UDP 入口诊断
- `tools/legacy_video_hud_probe.py`：HUD 接收统计
- `tools/legacy_video_bridge.py`：显式官方流量桥接工具
- `tools/video/benchmark_decode.py`：同码流解码延迟对比；旧命令入口保留转发
- `tools/verify_video_reconnect.py`：恢复链路检查

上述现场记录具有各自日期，旧记录中的“仍依赖官方后台初始化”不代表当前终端的
接收端控制实现。本次封装不修改设备参数或固件，也不重新认定现场视频/角度资格。

封装验收记录见 [2026-10-25 验证](encapsulation_20261025.md)。
专项回归集中在 `tests/video/`，测量报告在 `reports/video/`；通用窗口与传输生命周期回归
继续保留各自所属测试位置。二次收口验收见 [接口与输入边界](boundaries_20261025.md)。
