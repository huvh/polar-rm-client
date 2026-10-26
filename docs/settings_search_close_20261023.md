# 设置搜索期间主窗口无法关闭（2026-10-23）

## 已确认原因

用户点击的是**主窗口右上角 ×**，而不是设置页的返回。
旧入口调用系统模态 `QDialog.exec()`。即使搜索文本处理正常，Qt/Windows 也会
禁用其 owner 的原生窗口，主窗口的标题栏关闭操作不能正常发起。搜索不是死锁
触发器，而是问题发生时持有焦点的控件。

本机 Windows 原生对照（自身 HWND 的 `IsWindowEnabled`）：

| 状态 | 原生主窗口启用 | 系统模态 |
|---|---|---|
| `fa16a46`：设置展开，搜索“鼠标” | False | True |
| 本次修复：相同操作 | True | False |

## 修复与所有权

- 仅设置中心使用 `SettingsDialog`；通用 JelloDialog、其他确认对话框及素材不改。
- 不再让系统模态禁用整个主窗口。`_settings_session` 独占客户端鼠标、键盘、
  模块快捷键和战斗输入；主窗口标题栏仍由 Windows 正常处理。F11/F12 的既有
  窗口级安全快捷键保持有效，后台裁判/图传/生命周期继续运行。
- 为保持现有调用者的同步返回与 `finally` 清理合同，使用一个**局部 QEventLoop**
  等待 finished，而不是伪称已改为异步接口或消除了所有嵌套事件循环。
  普通返回/Esc 仍走原 Jello 退出动画；关闭程序时不等待动画。
- 关闭保存检查仍先于实际停机。若拒绝关闭，设置页和搜索/未应用草稿保持原样。
  只有准入成功进入 `_begin_window_shutdown` 后，才停止设置动画、取消全部待构建
  控件并结束局部循环，然后继续原有锁控制/归零/后台 worker/GL 退出流程。
- 重复进入只激活当前设置页，不创建第二个 owner；Show 内同步关闭、构建后已开始
  停机的情况不会再进入一个等待不到 finished 的循环。
- 打开设置期间继续暂停可选 GPU 预热，避免去掉系统模态后引入首开卡顿。
- 不自动应用或保存设置草稿，不自动 Arm，不强杀进程，不改材质/动画/字体。

Qt 的系统模态规则见 [QDialog 文档](https://doc.qt.io/qt-6/qdialog.html)。
其他显式确认/键位选择子对话框仍保持原有 Qt 模态行为；本次不扩展成全项目
弹窗系统重写。

## 验证入口

```powershell
python tools/verify_all.py --test tests/test_settings_host_close.py
# 真 Windows 桌面、自有窗口、临时配置和 inert transports；不连接真车
python tools/verify_settings_close_desktop.py --out tmp_settings_close_recheck
```

桌面工具在真实 QApplication.exec 与 OpenGL 窗口中检查：入场期间、搜索/中文输入
提交后、全屏搜索三条路径；读取自身 HWND 是否启用，并向它投递标题栏关闭同源的
`WM_SYSCOMMAND/SC_CLOSE`。检查设置对象、原生菜单 renderer 和 backend worker
退场，并验证 lastWindowClosed，不把单纯调用 Python `window.close()` 冒充标题栏验证。
它不点击其他应用、不截取桌面，也不认证所有驱动、现场设备或机器人控制资格。

保留结果见 `reports/settings-search-close-20261023/verification.json`。
