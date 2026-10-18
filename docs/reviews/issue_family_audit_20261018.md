# GitHub issue 与同类缺陷审查

日期：2026-10-18。GitHub 状态核对时间：09:44–09:45 UTC。
初始 inventory 的本地基线：`a4f3a2b03796c2c595aad86ef0efb028cf49688b`。
本次阶段更新分别记录下方视频、UI 与安装器冻结提交及已完成的离线组合结果，
不将离线结果扩展为原生显示或硬件验收。

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

## 本轮同类缺陷：分阶段修复与验证

| 关联范围 | 已确认或待确认的问题 | 当前状态与验收要求 |
| --- | --- | --- |
| #10 固件安装检查 | 真实临时 fixture 已复现 marker-only 的 `--dry-run` 假 PASS。原 `patch_arm`、`patch_sender`、`patch_task` 遇 marker 直接返回；其他 patcher 的常量块检查也不等于外围钩子完整。 | **修订软件修复已发布，专项复核接受。** 初版 53 PASS 后仍被注释钩子的反例否决，记录保留。修订版增加固定文本与词法检查；不等同于 C 预处理、语义、目标编译或硬件验收。 |
| #20 编码识别 | 有效 H.264 数据在字节偏移 **41,256** 出现 `FF D8`，被误判为 MJPEG。载荷内的字节巧合不能代替合法帧边界。 | **软件修复已发布，专项复核接受。** 使用 JPEG 解码证据约束从 Annex-B 到 MJPEG 的切换；有效样本负对照及合法 MJPEG/envelope、连续流与编码切换回归见下方。旧设备验收仍未完成。 |
| #8 ClickGUI 快捷键 | 普通 F8 的每个自动重复按下事件都会再次切换界面。 | **软件修复已发布，专项复核接受。** 忽略切换键的自动重复，保留新的物理按下及既有输入合同；与下列工厂清理共享同一 UI 阶段结果。 |
| #8/#12 设置工厂生命周期 | 对视频/键盘设置工厂注入晚期异常，连续两次创建失败后仍保留两个 host 子对象。 | **软件修复已发布，专项复核接受。** 清理本次取得的 owner 并保留原异常和 host/兄弟对象。复现属于对抗式异常注入，不是已知自然触发的用户症状；不据此覆盖取得 owner 之前的任意构造失败。 |

首批新增复现针对编辑前的 `c9180595` / `a4f3a2b` 源快照。本报告仅汇总，
不包含原始日志，也不把未复核候选或过去的专项通过当作新阶段的完成证据。

### 已接受的视频软件阶段

- 公开提交：[`3b768cb7fd2b547e91f8a7dd22d06cdd1773cf53`](https://github.com/lulunomaro/polar-rm-client/commit/3b768cb7fd2b547e91f8a7dd22d06cdd1773cf53)。
  对应本地提交 `11fa4e4df5ccbd0721cb0f8acb76ad2b34ddd5f7`，
  tree `83f5ba86eef122cc7a90a727de443376242c56f2`。
- `tests/test_udp_codec_evidence.py` 的完整 11 方法基线负对照产生
  **9 FAIL / 0 ERROR**；修复后的独立专项选择 **42 PASS**。
  已有 `tests/test_udp_h264_dispatch.py` 同时更新相关合同回归。
- 这些是有界软件识别/解码回归，不是旧接收器、原生 GPU 或持续实机视频验收。

### 已接受的 UI 软件阶段

- 公开提交：[`1226c5da68f6c60dd1248b512fb013fd36796a10`](https://github.com/lulunomaro/polar-rm-client/commit/1226c5da68f6c60dd1248b512fb013fd36796a10)。
  对应本地提交 `de0148fa4d169faddca4066dca8ca4a2cf1325ac`，
  tree `8945dfa379e49accdc55fcaef7f1240bc0513462`。
- 新回归为 `tests/test_clickgui_shortcut_repeat.py` 和
  `tests/test_nested_settings_factory_ownership.py`，最终共 **9 个方法**；
  基线负对照产生 **11 个失败结果 / 0 ERROR**，专项复核选择 **74 PASS**。
  失败结果可来自同一方法的多个场景，不按 11 个独立方法计数。
- 该阶段接受不代表所有 Qt 构造/清理失败路径或目标 Windows 显示环境均已验收。

### 已接受的安装器软件阶段

- 公开提交：[`62c31466b08e4a7d2930b4b07312e08b2742f228`](https://github.com/lulunomaro/polar-rm-client/commit/62c31466b08e4a7d2930b4b07312e08b2742f228)。
  对应本地提交 `b45d429b9e410109d227ac28b50a3c0294c84599`，
  tree `a709a945e96773ba8ef24fe8a068892b1ae3218e`。
- 接受的专项选择为 **107 PASS**：新增安装器守卫 12、控制器 44、帧处理 15、
  transport 36。新增回归为 `tests/test_controller_angle_installer_guards.py`。
  关闭词法守卫的 mutation 产生 **11 FAIL / 0 ERROR**。
- 保留失败历史：初版候选的 53 PASS 没有排除被注释的实际钩子；针对初版的
  完整 12 方法反例选择仍产生 11 个失败结果，因此初版没有获接受。上述
  107 PASS 对应修订后的冻结提交，不回写为初版通过。
- 该守卫限定于固定版本的文本与词法合同，不解释 C 预处理条件，不证明
  任意 C 语义等价、目标固件编译成功或物理控制器/机械臂安全。

### 组合验证与未完成部分

已直接读取并核对 `client-renewed20h-full11/results.json`：包含上述三个修复
阶段的离线组合聚合**已完成，374 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL，
NO-GO**（`run_state: completed`、`passed: false`）。

- Run ID：`7fcbdb0e44a7401ebd911841f636691d`；启动时间
  `2026-10-18T09:58:13Z`；profile 为 `offline`。
- 精确源码：公开提交
  [`62c31466b08e4a7d2930b4b07312e08b2742f228`](https://github.com/lulunomaro/polar-rm-client/commit/62c31466b08e4a7d2930b4b07312e08b2742f228)，
  本地 `b45d429b9e410109d227ac28b50a3c0294c84599`，
  tree `a709a945e96773ba8ef24fe8a068892b1ae3218e`。
- 启动时记录 `dirty: true`；启动工作树核对仅本审查文档未提交，可执行
  源码/测试/工具已提交。不能把这次记录写成整个工作树 clean。
- 声明源稳定性检查为 PASS：首尾均为 **729 个输入**，SHA-256 均为
  `1ebbbe27a4d0bad6eaa2809619fcb70d01517f1b7844f5d4f9f597833a629b43`。
  范围为声明的代码/配置及内部测试 fixture；排除文档、fixture 目录外资产、
  外部 fixture 和安装包。仅首尾比较，不能排除期间改动后恢复。
- 计数是所选套件/检查结果，不是源码覆盖率或独立测试方法总数。

剩余四项 INCOMPLETE：队内 CRC 参考对拍；DT7 固件/真实厂商 `dump.cs`
对照；DT7 UI 的固件 application C 源交叉核对；要求安装的 legacy patch
测试（刻意排除于只读固件验证）。12 项 SKIP 仍涉及未提供的固件/参考
fixture。原生桌面/OpenGL/视觉检查及 Tongji 外部集成未被此 offline profile
选中。真实 Windows、GPU、音频/串口设备、旧图传、机器人和便携净机验收
没有由本次离线结果建立，整体仍为 NO-GO。

之前 `c9180595ddbdd6ec8a17012b35a62328ae1d762d` 上的 **370 PASS / 12 SKIP /
4 INCOMPLETE / 0 FAIL，NO-GO** 仍是独立历史阶段；详见
[第十阶段记录](renewed_clean_code_repairs_20261018.md#tenth-full-run-candidate-shared-selection-policies)。
它不覆盖本轮新增提交，不能替代本次 full11 的独立结果。42、74、107 和各
聚合的选择可能重叠，不能相加为覆盖率或独立测试总数。所有四个 issue
继续保持 open；初版安装器被否决的证据及原生/硬件验收缺口不变。本次只
更新文字摘要，不发布原始日志。

### 第二次 UI 补充：旧弹出操作与启动确认

关联 #8/#12；**软件修复已发布，最终专项复核接受**。公开提交
[`863954d30aa841058a073d2c0020d1468e20ebaf`](https://github.com/lulunomaro/polar-rm-client/commit/863954d30aa841058a073d2c0020d1468e20ebaf)，
对应本地 `6a802d5c73be8585a0f814997edd38cc8d81243a`，
tree `5c24ec773655f730f63892ee48477640bfc8771f`。

- 实际交互可复现：键位弹出菜单在 Escape、选择改变、滚动或 resize 后，
  下一次绘制之前仍可能执行旧的 Add/Remove 命中目标。修复在这些边界退休
  旧目标，同时保留独立 Done 按钮。主要路径为 `rm_client/ui/jello_keybinds.py`。
- 保留早期候选的反例：仅在打开 picker 前清空目标仍不足；picker 的嵌套
  事件循环可重绘并再次发布旧行。最终修复在返回后再次退休目标，并使用
  进入 picker 时固定的 key，避免把操作应用到已变化的选择。
- `BindingPicker` 初始化在取得 Qt 子树后失败会清理该子树；保留原异常及
  host/兄弟对象。这个清理范围不包括初始父类构造取得 owner 之前的失败。
- `rm_client/ui/polar/renderers/startup_scene.py` 的 Return/Enter 和实际映射
  数字键确认抑制自动重复，防止一次长按跨越多个启动步骤。新的物理按下
  仍按原步骤工作；不支持的键、Backspace 与方向键的原有处理保留。
- 专项为 `tests/test_keyboard_popover_epochs.py`、
  `tests/test_startup_confirmation_repeat.py`，最终 **19 个方法通过**；历史
  基线负对照产生 **33 个失败结果 / 0 ERROR**。最终独立相关选择为
  **91 PASS**，API 冻结检查通过。各选择有重叠，不相加为独立方法总数。
- 较早的 **200 PASS** 属于补齐数字键边界之前的候选；它是历史检查结果，
  不充当最终候选的验证计数。嵌套循环缺口的反例也不因后续通过而删除。

已直接读取并核对 `client-renewed20h-full12/results.json`：**full12 新组合
聚合已完成，376 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL，NO-GO**
（`run_state: completed`、`passed: false`）。

- Run ID：`9c2130f8c2084ceba8f4d8e6023a65d1`；启动时间
  `2026-10-18T10:26:00Z`；profile 为 `offline`。
- 精确源码：公开 `863954d30aa841058a073d2c0020d1468e20ebaf`，
  本地 `6a802d5c73be8585a0f814997edd38cc8d81243a`，
  tree `5c24ec773655f730f63892ee48477640bfc8771f`。
  启动 provenance 记录 `dirty: false`；之后的文档更新不修改可执行源码。
- 声明源稳定性为 PASS：首尾均为 **731 个输入**，SHA-256 均为
  `60b1df8c68fe76765d0e0db3319a0773a1b48ff11651e90ce343b4003ebcf64e`。
  范围与 full11 相同；仍不包含外部 fixture、安装包、fixture 目录外资产，
  也不能排除两次快照之间改动后恢复。

这是该 UI 阶段完成时的离线组合聚合；后续接收边界结果见下文。full11 的 374/12/4/0 NO-GO 保留为
其自身 `62c31466` 源码的历史结果，不回写为追加 UI 阶段结果。四项
INCOMPLETE 仍是队内 CRC 参考、DT7 固件/厂商 dump、DT7 UI 固件源对照及
只读范围排除的安装型 legacy patch 检查；12 项 SKIP 与原生/外部选择限制
不变。计数仍是所选套件/检查，不是独立方法数或覆盖率。本次没有新增
原生 Windows/GPU 或实体设备验收，也不改变四个 issue 的 open 状态。

### 角度接收边界补充：延迟读取与授权代际

关联 #10；**软件修复已发布，独立专项通过，独立恢复运行的组合聚合已完成**。
公开提交
[`1ec12135bfc40576d2e15aaaa97d3e909e3e5a5f`](https://github.com/lulunomaro/polar-rm-client/commit/1ec12135bfc40576d2e15aaaa97d3e909e3e5a5f)，
对应本地 `3970e7f8ce2b7d4eceec2216ffd1cac7b8065ab9`，
tree `09e3660966d6a60919a9bdeadae80e6d193d0d17`。

- 生产 worker 配合无实际输出的串口替身，复现了 Arm 前已开始读取的 chunk
  在 Arm 后被转发，以及耗时 500 ms 的读取返回后被重新标为新鲜。
  这是实际 worker 路径的离线复现，不是物理串口或机器人实测。
- `rm_client/backend/controller_angles.py` 在读取开始时取得保守的本地
  `received_at` 与 arm generation；返回时重新检查年龄、配置代际和授权
  代际。过期读取撤销授权；跨 Arm 的读取不能满足“授权后的新样本”条件。
  Arm 时退休未完成帧前缀，避免旧前缀与新后缀拼成可转发样本，同时保留
  已完成样本的独立过期判断和序号基线。直接 feed API 及真正后续读取的
  合法样本路径保留。
- `tests/test_controller_angle_receipt_boundary.py` 共 12 个方法；历史基线
  负对照产生 **10 FAIL / 0 ERROR**。独立相关选择 **52 PASS**，另有陈旧
  部分帧探针核对。选择有重叠，不相加为独立方法总数。
- **边界**：读取开始时间不是线上时间戳；不能据此证明在读取开始之前已
  排队于 OS 缓冲中的 **不超过 512 字节**数据的真实年龄。保守丢弃可能包括
  在 Arm 前启动的读取期间真正新到达的字节，因此需要之后的一次读取。
  此策略不宣称恢复了硬件采集时间，也不证明所有驱动积压情形均已覆盖。

**原 full13 未取得完成结果，不能记为通过。** Run ID
`0d123dd22d4342eea7894821c91320e0`，启动时间 `2026-10-18T10:46:31Z`；
启动工作树 clean，候选为上述公开 `1ec12135` / 本地 `3970e7f8` /
tree `09e36609`。10:50 UTC 执行环境发生切换，原控制会话此后返回
Unknown process id，结果仍只有未完成哨兵项。仓库和部分日志保留；
不声称存在已完成结果，也不覆盖这些部分证据。

替代运行 `client-renewed20h-full13-recovery` 已通过原有互斥锁启动，
未绕过锁或删除旧输出，使用独立 run ID `109252f3f53e4ee6b7afdcadcbc264ee`，
启动时间 `2026-10-18T10:53:39Z`。已直接读取并核对其 `results.json`：
**377 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL，NO-GO**，
`run_state: completed`、`passed: false`。启动源码仍为上述精确本地
`3970e7f8ce2b7d4eceec2216ffd1cac7b8065ab9` / tree
`09e3660966d6a60919a9bdeadae80e6d193d0d17`。Provenance 为
`dirty: true`；父任务确认启动时仅本审查文档有未提交变动，不能称整个工作树 clean。
首尾声明源稳定性 PASS，均为 **732 个输入**，SHA-256 均为
`d86522325be259656961ba6acac5e25967d71fa4ef20db126f6b6bad4572e096`。
沿用已声明的范围、排除项和首尾快照限制。

这是新的独立恢复运行结果，不追认原 full13 通过。full12 的
**376/12/4/0，NO-GO** 保留为 `863954d3` 的历史结果。四个 issue 仍开放；
本地读取时间边界不证明 OS 积压数据的真实年龄。外部参考资料、目标固件
编译与物理链路/安全验收缺口保持不变。本次仅更新文字报告，不上传原始日志。

## 横向检查与停止条件

优先检查相同错误形态：标记不等于完整安装；收到字节不等于新鲜帧；其他
消息不应刷新独立数据源的新鲜度；请求关闭不等于资源已释放；旧手势不能
跨页面/模态/窗口转换继续生效；离屏状态不等于原生显示或实物验收。

每项交付分别列出：**代码已实现、自动化已验证、硬件已验证、仍待验证**。
只有相应原 issue 的完整验收条件具备证据后才能提出关闭建议。本报告既不
关闭 issue，也不宣称全仓库无缺陷、硬件兼容完成、可用于真实比赛或可合并。
