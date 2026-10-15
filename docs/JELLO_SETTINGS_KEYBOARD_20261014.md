# Jello 设置中心与键盘绑定（2026-10-14）

## 入口与实际流程

- `Esc → 设置`：保留六页实际设置功能，外观改为Jello白色圆角、原版Helvetica Light/Medium、灰色值区、蓝色滑条与勾选。
- `设置 → 键盘/鼠标 → 点击绑定键位`：不再出现旧单键捕获提示，而是独立完整Jello键盘页。
- 键盘页点击键帽→按键弹层列出现有绑定→`×`删除或`Add`打开可搜索功能列表。从具体绑定行进入时，对应功能排在最前。
- 键盘页“完成”写回设置页草稿，仍需“应用当前页”才持久化；Esc取消不改原绑定。
- `ClickGUI → ClickGui → 打开键盘绑定管理器`也可直接管理。旧GUI已有的绑定热点全部改用同一键盘入口，不留下第二套捕获逻辑。

## 原始包依据（静态读取，无游戏执行）

用户指定`dangerousclient/SIGMA/sigma-jello-5.1.0-original.zip`，SHA256：
`8064c5fd8a19d984a074d0147920a8ca9853014fa6aa02b0d164369a7077a94f`。

内嵌Jar SHA256：`3ce1573562fa2c17394400d8c4cafcd9ac8d68ea128040c9eea5f3873bec7406`。
复制到项目外独立参考目录后用CFR0.152静态读取以下类，没有运行Sigma/Minecraft：

- `KeyboardScreen`、`Keyboard`、`Keys`、`Child`
- `PopOver`、`Class4253`、`ModsPanel`
- `Checkbox`、`EasingFunctions`、`ResourceRegistry`、`JelloOptionsGroup`

原版61键五行坐标和宽度直接对齐：1060逻辑像素宽、键帽63高、行距74，Space427宽、右Shift172宽、Return136宽、Back117宽。采用原版浅灰双层键帽、5px底层与3px按压深度、已绑定字体区别、原生阴影、按键弹层和功能选择流程。

| 部件 | 核对参数 |
|---|---|
| 设置中心根过渡 | 复用已有ClickGuiScreen的450/125ms可逆时间线 |
| 键盘入场 | KeyboardScreen：200ms，easeOutBack(s=1.70158)，scale=0.8+0.2×ease |
| 按键弹层 | PopOver：250×330、250ms、同一back曲线、50px方向位移；空间不足向上 |
| 功能选择 | ModsPanel：500×600参考面板、200/120ms |
| 新增/删除绑定条目 | Class4253：150/180ms，easeOutQuad，55px参考行高 |
| 勾选 | Checkbox：勾选90ms/取消70ms，原始check.png，1.5→1缩放 |
| 下拉 | 复用已有Jello dropdown：220ms展开/收拢，OutCubic与递减raw² |
| 键帽hover/press | 原版0.2/60Hz步速转换为12×dt，不绑定到30/60FPS逻辑 |

现有Light/Medium字体与此Jar逐字节一致。原生`regular.ttf`另以`Jello-Regular.ttf`加入UI字体库，SHA256
`462fa16c0bccee134ac8dcd5b0d5cbc4e992d5d32de620ce290ba784ba46638a`，用于原版已绑定键名/列表RegularFont20。中文显式YaHei UI Regular，禁止继承Minecraft或Helvetica Light的命名style落到宋体。

## 适配边界与安全

这不是把原版游戏设置菜单、Java逻辑或视频参数直接移植：六页内容仍是RM客户端已有功能。原版键盘没有Fn/导航区，额外23键（合计84键）是明确的RM扩展，不宣称104键原版布局。Meta、左右未区分修饰键等未映射按键不能伪装成可用控制。

F12始终急停，不可绑定；ClickGUI入口保留。Tab仅允许恢复TacticalMap原有默认归属，不可任意绑定其他模块。驾驶槽与普通模块快捷键分别校验，冲突不会覆盖。删除先更新草稿再播放收拢，快速点击完成不会漏掉删除。

打开前归零/锁定，返回不自动Arm；模态框与嵌套选择框均保留F12；绑定过程不切换模块、不发布非零控制。显示刷新、后台裁判/图传处理继续按原逻辑运行。

只使用UI资源，未改原ZIP、现有默认配置或后端协议。没有新增CPU摄像头/桌面模糊；根动画只缓存一次控件合成面，结束释放，避免每帧重排字体与控件。5段液态玻璃/present GLSL逐字等于HEAD。

键盘几何、字体和时间参数按原包核对，Qt控件中心与RM扩展属于适配；未宣称跨游戏引擎、所有屏幕逐像素一比一验收。Jello素材不因CFR许可证而自动获得公开分发授权，本轮没有提交/推送或发布这些资源。

## 验证

- 15项新增键盘/动效/草稿/冲突/嵌套F12/圆角与下拉测试。
- 全量503项：501通过、2项环境跳过；72个smoke测试函数完成；API冻结1161成员无漂移。
- Windows实际Qt窗口：1280×720、1600×900、1920×1080、2560×1440对应宿主尺寸，设置与键盘可视检查、控件/热点一致。低尺寸视频区可滚动，不以最小布局挤出主面板。
- 100次快速入场反向关闭：最终关闭、过渡计时器停止、缓存面释放。不是100次完整200ms展开的长时测试，也不是新一轮整场FPS/真车认证。
- 预览与日志位于`tmp_jello_final_visual/`、`tmp_jello_keyboard_cycles/`、`tmp_jello_final_delivery_tests.log`、`tmp_jello_settings_api.log`，不纳入发布。

比赛就绪结论仍需现场证据，不能由换皮/桌面测试升级为READY。
