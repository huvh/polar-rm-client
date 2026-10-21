# 设备通信对齐与恢复验证，2026-10-21

本文件记录从已审阅证据恢复的修复，不宣称恢复了中断前的提交 SHA，也不把此前测试成绩当作新树测试。
本轮只运行 fake、mock 和本机回环测试；没有真实 USB/串口操作、驱动安装、系统网络修改或用户 Codex 操作。

## 官方证据及私有差异

官方学生端 12.0.0.213 ZIP：
[官方下载](https://bbs-web-static.robomaster.com/55bea4d5b5f94a8d8adc2a5f40c225d81783394887530/RoboMasterClient%2012.0.0.213_Student.zip)。
已审阅 ZIP SHA-256：`661498326b6a0047d5cf73a4f9ceede3297cba4b0e745aa49c69a46eba873374`；
GameAssembly.dll：`5ba634258fc712f98d1c30bed50eaa9d53d4b6dfad797a7df68e1163e9addba9`。
这些是中断前的静态取证标识，不表示本次重新下载或运行了官方程序。

- `CCSPortThread.SearchPackage` RVA `0x27fd10` 接收严格 8 字节 `0x0306`，
  `SendToClient` RVA `0x280cc0` 在 `0x280da7/0x280dca` 直接把键值传给 `Keybd_event`。
  构造函数 `0x281340` 白名单 W=`0x57`、A/S/D=`0x41/0x53/0x44`、Shift=`0x10`、Ctrl=`0x11`。
  原项目 HID 默认 W=`0x1A` 不等价，现默认改为实证 Win32 VK。
- `RMClientAssist_SerialPort.dll` SHA-256
  `d41f8f54a21bd8e4a049f22bdea7593ee283a09f760e76b7862434869e25166c`，
  `CCSerialThread.SearchPackage` token `0x0600001c` IL `0127..015e` 严格要求 `0x0302` 数据 30 字节。
  同步与异步发送均在写出/入队前拒绝其他长度，不补齐短包。项目保留 30 Hz，未因为官方25ms收包节流而放宽。
- `DeviceInfo.dll` SHA-256 `3f371c3c4364a03580cb66da0cd733aa2b2a0f56c9640e5bd6be39b4d16dbcef`：
  DT7 VID_FFF0/PID_0008；旧图传 VID_2CA3/PID_001F/MI_04；RC150 COM VID_2CA3/PID_1020/MI_02；CC 识别 FTDI。
  项目仅增加被动诊断，并排除官方图传设备被 Robot Auto 当作私有 C 板。未知/冲突 MI 保持未确认，
  不扩大 CC 自动选口白名单，不改变显式选口。发现不等于初始化或资格合格。
- `RobotInput.Update` RVA `0x31b960` 的 `0x31bc35/37` 写 DT7 reserved=0；
  `SerialPortThread.OnSendInputStatus` RVA `0x292af0` 封装 22 字节 `0x5A/0x2000`。
  **项目默认仍为 reserved=1024**，是 DBUS 第五通道中位安全策略，明确不是官方当前字节。
  改动该值会改变 profile digest，需重新资格验证。961200 波特率保持不变。

## 键表迁移

`configs/cc_key_usage.json` 的 `_key_encoding=win32_vk` 为新默认。
缺失/损坏文件回到实证 VK。历史 `HID_USAGE` 常量保留原值；只有显式
`_key_encoding=usb_hid_legacy` 选择历史默认。用户自定义数值覆盖不猜测、不自动改写。
未知 encoding 拒绝加载。ALT/GUI/SPACE/ENTER 不在实证官方白名单中，不由默认表放行。

## 错误恢复与安全边界

`radio_km_feedback` 将非有限、负数、过大计数显示为 unknown，不抛异常打断 tick；
保留已有有限小数截断行为。固件 uint32 计数经 float32 上报，最大值可四舍五入为 `2**32`，
该边界仍接受；键位值限制为 uint16。遥测不授予输出权限，旧权限先由门禁撤销。

自定义控制器、DT7、PRM1/0x5A 仍是不同链路。项目专用载荷、驱动/固件兼容、现场身份、
物理遥控优先、独立超时/急停/重连归零均不能由静态包或桌面测试替代。

## 新树阶段验证

从恢复基线 `222899de17d211755b7a0a3b2851144ff8016c6c` 开始重建。
设备阶段命令统一为 `PYTHONPATH=. ../client-verification-venv/bin/python <测试文件>`：

- `tests/test_official_device_transport_contract.py`：14 项。
- `tests/test_cc_worker_dispatch.py`：8 项。
- `tests/test_controller_frame_regressions.py`：15 项。
- `tests/test_backend_policy_boundaries.py`：7 项，旧非有限值异常预期已改为严格 unknown/无权限断言。
- `tests/test_serial_rescan_nonblocking.py`：11 项。
- `tests/test_port_discovery_admission.py`：9 项。
- `tests/test_backend_policy_characterization.py`：3 项，未改冻结基线。
- `tests/test_transport_safety_regressions.py`：36 项。

上述本次重跑共 103 项通过；`git diff --check` 通过。focused 不代表全量聚合或 Windows 发布构建。
外部固件 CRC 对照需要 `StandardRobotpp/components/support/CRC8_CRC16.c`，缺少外部来源时必须标记跳过，不能计为通过。

## 车桥新树恢复阶段

原阻塞式 `accept -> pump` 不能拒绝第二连接，`listen(1)` 只是 backlog 容量。
恢复后的实现用唯一 acceptor 持续拒绝竞争者，串口 open/read/write/close 由同一 session owner 管理；
旧 session 确认结束后关闭并重建监听器，销毁尚未 accept 的旧 backlog。
read worker 未退休或 native close 失败时保留 owner 引用并停止接纳，不能用 join 超时冒充清理成功。
`--once` 实际传递生效，Auto 多板拒选；日志、reader/session 构造及 start 前/后异常也进入清理保护。

`tools/car_bridge/bridge_server.py` 无认证/加密，默认 `0.0.0.0` 只适合可信隔离网络，不能宣称安全公网部署。
断开意味着观察到 EOF/停止后的未来写入停止，不是物理断线瞬间保证；固件 watchdog 仍须另验。

本次新树执行：`tests/test_car_bridge_admission_safety.py` 14 项通过，
`tests/test_car_bridge_evidence.py` 4 项通过（含回环脚本 15 个可计数断言）。
新增回环用阻塞拒绝的屏障让第三客户端确实排入旧 backlog，确认换代后只写新客户端的数据。
所有串口均 fake、网络仅 `127.0.0.1`，并非真实硬件资格。

## 213/V2 安全预设新树恢复阶段

新增独立 `configs/official_213_v2_safe.json`，不改 V1 身份常量、不迁移旧用户设置。
明确 V2 profile，但保留 LabDebug、loopback、Synthetic、出口关闭/mock。
真实 `ClientConfigStore` 导入和 offscreen 窗口异步重建均被测试，串口发现/打开及 MQTT/UDP start 均替身，
确认仍 LOCKED、mock 且未启动传输。诊断只比较显式输入版本，不把 engine137/V2后续版本当作已验证硬件配对。
便携脚本仅增加独立 defaults 模板与 manifest SHA，不自动替换用户配置；Windows 发布构建未运行。

本阶段新树重跑 `test_official_profile_preset.py` 14 项、`test_configuration_boundaries.py` 18 项、
`test_configuration_transactions.py` 10 项、`test_build_safety_regressions.py` 22 项、
`test_official_device_transport_contract.py` 14 项，全 78 项通过。最后一套是设备阶段重复验证，不能重复累计成独立覆盖。
`git diff --check` 通过，新测试登记为 offline。全量聚合由集成阶段单独报告。
