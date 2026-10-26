# 设置窗口跟随主窗口切换尺寸

设置使用独立的无边框模态窗口。原实现只在打开时复制主窗口尺寸，因此打开后切换全屏会保留旧尺寸和旧位置。

修复由设置壳中的 `SettingsGeometryGuard` 负责：合并父窗口的尺寸、位置、状态和 DPI 事件，使用父窗口逻辑客户区更新设置窗口。Windows 全屏边框的原生通知可能晚于 Qt 状态事件，因此短暂延后再次核对客户区原点。隐藏或销毁后不再跟随。主设置及嵌套键位管理器使用相同机制。

尺寸变化后同步内部布局，防止字体和控件宽度已经更新，而滚动内容仍沿用旧布局。沿用同一个窗口及控件对象，保留未提交草稿。

验证：

- 6 项新增 Qt 回归用例：两种打开模式的 F11 往返、显示模式与物理分辨率应用、嵌套窗口跟随、隐藏后的行为、大尺寸往返时控件不被裁切。
- 103 项现有设置及全屏相关测试、6 项 Endfield 设置布局测试、8 项滚动测试通过，共 123 项。
- 静态质量检查通过。
- `native-1x/report.json` 和 `native-1.5x/report.json`：实际 `PolarRMWindow`、Windows Qt 平台、共享 OpenGL 上下文、生产设置入口及嵌套模态事件循环；硬件和网络传输使用无副作用替身。
- 原生验证覆盖窗口打开后 F11 全屏并还原、全屏打开后 F11 窗口并还原、设置显示模式应用、DPI 对应物理分辨率应用，以及未提交鼠标灵敏度草稿保留。每个阶段均核对逻辑客户区的位置和尺寸，并保存设置窗口自身的截图。

复现命令：

```powershell
.venv/Scripts/python.exe tools/endfield/settings/verify_modal.py --geometry --out docs/endfield/settings/evidence/20261026-geometry/native-1x
$env:QT_SCALE_FACTOR='1.5'
.venv/Scripts/python.exe tools/endfield/settings/verify_modal.py --geometry --out docs/endfield/settings/evidence/20261026-geometry/native-1.5x
```
