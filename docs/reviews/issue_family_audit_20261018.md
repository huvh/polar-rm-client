# GitHub issue 与同类缺陷审查

日期：2026-10-18。GitHub 状态核对时间：09:44–09:45 UTC。
报告编写时本地基线：`a4f3a2b03796c2c595aad86ef0efb028cf49688b`。

## 范围与结论

完整读取仓库 issue 列表、评论及时间线，并追踪关联提交、实现和验证说明。
排除 PR 后，**只有 #8、#10、#12、#20 四个真实 issue，全部仍为 open，
评论均为 0；没有已关闭的真实 issue**。本报告不改变任何 issue/PR 状态。

已有修复与硬件验收必须分开：PR #9、#11 已合并；PR #15 仍为 open/draft，
但其实现已经集成到 PR #19 的基础分支。PR #19 仍为 draft，不能据此认定
四个 issue 全部完成。下列历史测试结果来自对应提交和报告，本次 inventory
审查没有重新运行这些测试，也没有产生新的全项目通过结论。

## #8：中文界面、选手端退出与 ClickGUI 空白关闭

[原 issue：界面汉化与退出交互：选手端无法退出，Right Shift 配置界面需支持左键点击空白处关闭](https://github.com/lulunomaro/polar-rm-client/issues/8)

- **原问题与复现**：进入选手端后无法返回；Right Shift 打开 ClickGUI 后，
  左键点击面板外空白不能关闭；用户可见文案中文覆盖不足。原报告基线
  `bd2e590`，当时没有运行时复现记录。
- **实现证据**：[PR #9](https://github.com/lulunomaro/polar-rm-client/pull/9)
  已合并，专项提交为
  [`bfe2dba`](https://github.com/lulunomaro/polar-rm-client/commit/bfe2dba654ed3474b10dc14b13f2661440a33b00)，
  合并提交为 `9599a1c`。现有实现包含 Esc 返回/退出菜单、匹配按下与释放的
  空白关闭、拖动及内部控件保护、关闭点击独占、语言与 DPR 缓存失效。
- **主要路径**：`rm_client/ui/jello_clickgui.py`、
  `rm_client/ui/polar/mixins/input_dispatch_mixin.py`、`escape_menu_mixin.py`、
  `clickgui_builders_mixin.py`、各 `*_locale.py` 及 HUD/地图渲染器。
- **已有验证与缺口**：[显示范围清单](../issue8_display_inventory.md)报告
  107 个界面/语言/手势专项通过；[交互说明](../issue8_interface.md)记录
  关闭与输入独占合同。物理 Windows 显示器/GPU 交互验收仍缺失；未知第三方
  错误、用户内容、协议标识和安全确认口令不属于自动汉化范围。
- **验收条件**：默认中文及明确英语偏好都正常；可以明确返回启动页和确认
  退出；面板外左键点击关闭，内部点击、拖动和右键不误关；Right Shift/F8
  保留；关闭/重开、键鼠交替、DPI/布局变化后旧手势不能触发新页面或控制输出。

## #10：实体控制器角度链路与独立超时

[原 issue：自定义控制器：补充实体控制器角度接收与转发，并核对机器人端数据源及独立超时](https://github.com/lulunomaro/polar-rm-client/issues/10)

- **原问题与复现**：键鼠出口不是实体角度入口；停止角度输入但继续其他裁判
  数据时，过期角度不能被通用裁判在线状态续命。
- **实现证据**：[PR #11](https://github.com/lulunomaro/polar-rm-client/pull/11)
  已合并。固件提交
  [`4226327`](https://github.com/lulunomaro/polar-rm-client/commit/422632766276594e561ece190cad4b3a9b4ca242)、
  客户端提交
  [`7d8bf91`](https://github.com/lulunomaro/polar-rm-client/commit/7d8bf919d9ac99e7b2d2a2eda488257ddba4e068)，
  合并提交 `56e2315`。固定合同为 StandardRobot++ `2722e0d`、0x0302/30 字节、
  六轴 float32 弧度；包含 CRC/数值/序号校验、300 ms 独立新鲜度、最大 30 Hz
  最新样本转发、重新授权及串口所有权保护。300 ms 是台架默认值，不是实测
  安全停车时间。
- **主要路径**：`rm_client/backend/controller_angles.py`、`manager.py`、
  `port_admission.py`、`rm_client/serial_ports.py`、
  `rm_client/ui/polar/mixins/config_actions_mixin.py`、
  `tools/firmware/controller_angle/`。
- **已有验证与缺口**：原 PR 报告 37 个 Python 专项和 5 个固件 host 测试通过；
  [链路说明](../controller_angle_link.md)明确未完成 ARM 构建、UART/DMA/引脚、
  官方选手端实际消费与机器人失联/恢复验收。既有 SAFE 输出抑制不等于重载
  机械臂的重力安全保持。
- **验收条件**：实物六轴数值/方向/单位一致；官方接收端及机器人确实消费；
  保持其他裁判流时仍独立超时；超时不重放缓存、恢复按明确规则重新授权；
  原键鼠链路保留且无串口双写；固件安装/重复安装/检查不能把不完整安全补丁
  报告为成功。初次板级验证必须固定/支撑机械臂并禁止实际执行器动作。

## #12：启动页设置与 F11 全屏

[原 issue：主界面无法直接打开设置，F11 无法自由切换全屏模式](https://github.com/lulunomaro/polar-rm-client/issues/12)

- **原问题与复现**：停留启动页无法直接进入设置；主界面和选手端不能通过
  F11 反复进入/退出全屏。原报告基线 `9599a1c`，当时没有运行时复现记录。
- **实现证据**：[PR #15](https://github.com/lulunomaro/polar-rm-client/pull/15)
  仍为 open/draft，提交
  [`cfd45d6`](https://github.com/lulunomaro/polar-rm-client/commit/cfd45d69766ba673dfb391f340822527a7a3fc5a)。
  其实现已随
  [`b26b7b7`](https://github.com/lulunomaro/polar-rm-client/commit/b26b7b718e348fbda066412f6d86140727f32e73)
  集成到 PR #19 的基础分支 `fix/client-combined-ui-review-20261016`，
  这不表示 PR #15 或 PR #19 已合并到 main。当前代码有真正设置入口、
  窗口级 F11 处理、普通/最大化几何恢复及转换前输入释放和控制锁定。
- **主要路径**：`rm_client/ui/window_shortcuts.py`、`cs2_settings_center.py`、
  `cs2_video_settings.py`、`fullscreen_composition.py`、
  `polar/renderers/startup_scene.py`、`polar/mixins/input_dispatch_mixin.py`、
  `polar_app.py`。
- **已有验证与缺口**：[专项说明](../startup_settings_fullscreen_fix.md)报告
  19 个新专项及 118 个相关独立进程测试通过。离屏测试及 mock Win32 API
  不能证明真实 DWM/驱动、跨屏/DPI 或 OpenGL 全屏呈现正确。
- **验收条件**：启动页所有步骤可打开设置并返回原页；选手端设置不回归；
  F11 在搜索、绑定编辑、嵌套弹窗中反复切换且自动重复不多切；正常/最大化
  几何和显式分辨率恢复正确；转换不重放旧输入或自动 Arm；F12 保持有效；
  在目标 Windows 多屏/DPI/GPU 环境完成呈现验收。

## #20：旧图传入口与 UDP H.264

[原 issue：旧图传兼容：补齐设备接入链路，并修复 UDP H.264 识别后不解码的问题](https://github.com/lulunomaro/polar-rm-client/issues/20)

- **原问题与复现**：Shark 分片重组后的 H.264 可被识别，但原后端没有对应
  解码分支。issue 的假 SPS/PPS 探针只证明路由缺口，不是真实解码样本。
  官方 RoboMasterClient 11.0.1.128 可连接同一硬件是用户报告的对照条件，
  不是 POLAR 已连接或已失败的实机证据。
- **实现证据**：[PR #19](https://github.com/lulunomaro/polar-rm-client/pull/19)
  中的
  [`32da8ad`](https://github.com/lulunomaro/polar-rm-client/commit/32da8ad51baf5834fdd77f8ee7c29afc4bd946e2)
  补上持久 H.264 解码及 codec owner 转换；
  [`8c51d06`](https://github.com/lulunomaro/polar-rm-client/commit/8c51d06fa8a2941322ea710c8efa08a2dbf9bfa0)
  添加真实 FFmpeg → manager → 离屏 HUD 检查。
- **主要路径**：`rm_client/backend/video_backend.py`、`manager.py`、
  `rm_client/transports.py`、`native_viewer_telemetry.py`、
  `ui/polar/mixins/video_backend_mixin.py`、`model.py`、`scenarios.py`。
- **已有验证与缺口**：[证据与边界](issue20_legacy_video_evidence_20261018.md)
  记录 12 个 dispatch 方法及 1 个 HUD 方法，使用有效 bundled H.264 产生并
  更新 160×120 图像，保留 Hero 源限制和停止清帧。旧收发器型号、描述符、
  驱动、初始化/选频、真实传输/编码及官方进程依赖仍不明。Shark 8 字节头、
  Native 0x0310 的 300 字节合同、裸 UDP/USB 不能互换；没有旧设备驱动验收。
- **验收条件**：有效 H.264 的非关键帧、参数/关键帧恢复及编码切换通过；
  同一旧硬件在 POLAR HUD 持续更新真实视频并记录时长/分辨率/FPS；断流、
  拔插、占用、恢复和退出状态准确；收到字节不能冒充新鲜画面；按改动范围
  回归 HEVC/MJPEG/Webcam/Synthetic/Native，保留 Hero 和控制授权限制。

## 本轮同类缺陷：修复中，不是完成声明

| 关联范围 | 已确认或待确认的问题 | 当前状态与验收要求 |
| --- | --- | --- |
| #10 固件安装检查 | 真实临时 fixture 已复现 marker-only 的 `--dry-run` 假 PASS。`patch_arm`、`patch_sender`、`patch_task` 遇 marker 直接返回；其他 patcher 的常量块检查也不等于外围钩子完整。 | **已确认，修复中。** 要求完整已安装合同及部分/被修改 marker 负对照；失败须在修改前拒绝，不损伤原文件/快照；干净安装与真正幂等仍成立。 |
| #20 编码识别 | 有效 H.264 数据在字节偏移 **41,256** 出现 `FF D8`，被误判为 MJPEG。载荷内的字节巧合不能代替合法帧边界。 | **已确认，修复中。** 要求有效样本负对照、合法 MJPEG/envelope 正对照、连续 H.264 及编码切换回归；不能通过普遍关闭 MJPEG 或弱化断言掩盖问题。 |
| #8 ClickGUI 快捷键 | 普通 F8 的每个自动重复按下事件都会再次切换界面。 | **已确认，修复中。** 要求一次物理按下只切换一次，保留松开后的下一次按下及 Right Shift/F8 行为；不改变 F12 和绑定捕获的既有合同。 |
| #8/#12 设置工厂生命周期 | 对视频/键盘设置工厂注入晚期异常，连续两次创建失败后仍保留两个 host 子对象。 | **对抗式失败路径已确认，修复中。** 这是异常注入结果，不是已知自然触发的用户症状。要求释放本次取得的 owner、保留原异常且不误销毁 host/兄弟对象，并有重复失败负对照。 |

本轮新增复现针对编辑前的 `c9180595` / `a4f3a2b` 源快照；测试名及最终
修复状态待后续复核补充。本报告仅汇总，不包含原始日志，也不把
正在进行的代码修改、未复核结果或过去的专项通过当作本轮修复完成证据。
后续应补充最终提交、负对照、独立复核及同一冻结源上的相关回归结果。

## 横向检查与停止条件

优先检查相同错误形态：标记不等于完整安装；收到字节不等于新鲜帧；其他
消息不应刷新独立数据源的新鲜度；请求关闭不等于资源已释放；旧手势不能
跨页面/模态/窗口转换继续生效；离屏状态不等于原生显示或实物验收。

每项交付分别列出：**代码已实现、自动化已验证、硬件已验证、仍待验证**。
只有相应原 issue 的完整验收条件具备证据后才能提出关闭建议。本报告既不
关闭 issue，也不宣称全仓库无缺陷、硬件兼容完成、可用于真实比赛或可合并。
