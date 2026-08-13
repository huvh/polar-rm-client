# 后端比赛实战就绪审计

审计日期：2026-08-13
分支：`deepseekv4flash后端`

## 结论

**NOT READY FOR REAL MATCH**

本轮已经修复可由桌面代码证明的 P0/P1 缺陷，但真车、裁判系统、正式图传发射端和队内机器人固件尚未形成现场闭环。`rm_client.backend.readiness.audit_backend()` 继续 fail-closed；缺少任一现场证据时绝不会报告 READY。

## 2026-08-12 已修复

- 解码器附加的 `__present__` 元数据不再进入 `int()`；单条坏裁判消息有异常隔离和错误统计，不会中止该帧后续消息。
- `robot_health` 按官方 5+5（1/2/3/4/7）映射，且依据本机阵营构造双方 ID。
- `Event.param` 支持官方逗号格式；数值比赛阶段统一映射，Hero 吊射不再因 `MATCH`/`4` 双写被锁死。
- 协议层标记为 V1.3.1：`MapClickInfo` 是下行，`MapClickCmd` 是上行；哨兵控制值修正为 0/1。
- 键盘 16 位、鼠标三轴和三键进入官方 `KeyboardMouseControl` MQTT 链路，按 75 Hz 门控；按键释放会可靠重试。
- F12 先尽力发布全零 KMC，再锁止全部上行；`Ctrl+Shift+F12` 仅用于人工确认后的解锁。
- 正常退出会先发送全零 KMC，再发布 retained offline；场景/客户端 ID 重连不会发布可能与新连接竞争的离线状态。
- 115200 串口明确拒绝 `0x0311`。CustomControl 只经官方 MQTT/图传链路发布。
- 自瞄提供显式、版本化的 14 字节 `PRM1 kind=1` 队内 CustomControl 载荷；桌面端永不置 fire 位。
- 小陀螺提供 12 字节 `PRM1 kind=2` 启停/方向/速度载荷；`AutoSpinOnHit` 的裁判受击判定可驱动同一路径。两者默认 Mock，必须在机器人固件实现同一 schema 和超时归零后手动启用。
- 官方场景下经济请求默认走 MQTT。确认只接受本机弹量、血量、复活或支援状态变化，团队金币变化不再作为成功依据；超时不自动重试，避免 QoS1 重复扣款。
- UDP/串口/同济接收线程退出后清除 running；YOLO 加载失败有退避；Qt 逻辑阶段逐项隔离异常。
- H.264/H.265 解码支持系统、发布包内置或 `imageio-ffmpeg`，普通 HEVC P/B slice 在已锁定流中不会被误丢。
- 配置版本非法时安全返回；保存采用临时文件、`fsync` 和原子替换。
- 自动保存已做 250 ms 合并，拖动滑块不再逐事件全量写盘；运行时每秒执行 fail-closed readiness audit 并写入 `RobotState.backend_stats["readiness"]`。
- 发布脚本只打包 Git 跟踪内容，校验核心 backend/Hero/Jello/Minecraft 文件、默认 JSON 和 Python 编译，并内置 ffmpeg；不会打包工作区中用户修改的 `configs/default.json`。

## 仍阻止实战签字的现场项

1. 正式 MQTT 下行、75 Hz KMC/CustomControl 上行和机器人侧超时归零未做真车全链路测试。
2. `PRM1` 队内 CustomControl schema 需要机器人固件实现、代码评审和台架验证；Hero 仍只做决策辅助，绝不自动开火。
3. 正式 UDP HEVC 与 Native `0x0310` 发射端尚未覆盖丢包、乱序、SPS 恢复、分辨率切换和解码器崩溃。
4. 经济协议没有逐请求官方 ACK；当前采取“本机结果字段确认 + 禁止自动重试”的保守策略，仍需裁判系统实测。
5. 相机标定、Hero yaw/pitch/炮口/初速、部署模式生命周期、小陀螺误触发均需隔离场地验证。
6. 需要完整赛程的 P50/P95/P99 延迟、CPU/GPU/显存、队列、网络断链和热稳定 soak。
7. 需要操作员和安全负责人保存审计 JSON、日志与现场签字。

## 最低现场证据

- `video_source` 明确为 `udp` 或 `native_0310`，并持续产生新解码帧。
- `codec_field_test`、`estop_robot_test`、`command_ack_test`、`control_heartbeat_test`。
- `robot_firmware_schema`：固件正确解析 `PRM1 kind=1`，并证明 fire 位保持 0。
- `spin_firmware_schema`：固件正确解析 `PRM1 kind=2`，并证明启停、方向、速度和失联超时归零。
- `projectile_hit_spin_test`、`hero_deploy_status_test`、`hero_lob_live_test`。
- `loss_recovery_test`、`latency_soak_test`、`field_signoff`。

软件测试通过不能替代上述现场证据。
