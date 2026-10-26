# 设置打开期间的全屏切换闪露与耗时

上一版几何跟随在零间隔定时器中执行；主窗口的 `QOpenGLWidget.resizeEvent` 可以先重建 FBO 并同步调用 `paintGL`，此时设置还停留在旧范围。之后更新根样式又会重算六个已经加载的页面，进一步推迟设置重绘。

`baseline/report.json` 的本机测量重现了问题：全屏放大时存在 `host` 重绘的 `covered: false`；全部页面加载后，样式更新约 805–875 ms，设置首次覆盖重绘约 1.0–1.2 秒。

本次修改：

- 在父窗口的尺寸、位置和状态事件中立即跟随，先于父窗口自己的 resize 处理。
- 保存当前设置自身的画面，同步铺满并重绘新客户区，再排队完成内部布局；切换过程中持续使用不透明设置画面。
- 当前页及顶部、底部独立更新样式，隐藏页面在再次选择时更新；相同样式不再重复设置。
- 布局收敛只处理当前可见区域。快速连续切换复用同一帧，并合并为最终一次重排。
- 关闭时取消尚未执行的重排，保留草稿、原有焦点以及 F11/F12 的输入所有权。

验证结果：

- 103 项既有设置/全屏测试、11 项几何和切换测试、6 项 Endfield 布局测试、8 项滚动测试，共 128 项通过；静态质量检查通过。
- `native-1x/report.json`、`native-1.5x/report.json` 使用真实 `PolarRMWindow`、Windows Qt 平台、共享 OpenGL 上下文和生产模态入口。硬件与网络传输使用无副作用替身。
- 两种打开模式均预先加载全部六页，验证 F11 往返、连续四次 F11、视频显示模式和分辨率应用，以及草稿保留。
- 每次记录设置与主窗口的 Paint 事件。断言设置覆盖重绘早于主窗口首次重绘，并且全部主窗口重绘时设置均已覆盖客户区；DPI 原生边框允许 1 个逻辑像素余量，落定后的窗口几何要求精确相等。
- 本次原生测量中，设置覆盖在数十毫秒内完成，当前页样式重排约 200–265 ms；连续切换回原尺寸时相同样式直接复用。具体耗时依赖窗口大小和系统负载，记录的是 Qt 绘制顺序及 CPU 时间。

复现：

```powershell
.venv/Scripts/python.exe tools/endfield/settings/verify_modal.py --geometry --warm-all --out docs/endfield/settings/evidence/20261026-transition/native-1x
$env:QT_SCALE_FACTOR='1.5'
.venv/Scripts/python.exe tools/endfield/settings/verify_modal.py --geometry --warm-all --out docs/endfield/settings/evidence/20261026-transition/native-1.5x
```
