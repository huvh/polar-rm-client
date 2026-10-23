# Esc 菜单背景发白：Windows 合成路径修复（2026-10-23）

## 症状与证据边界

用户在另一台 Windows 电脑复现：**菜单按钮等正常，仅背景全白**。
该机显卡/驱动信息与日志尚未取得。本机在旧版本未复现完整白屏，不能声称已经
在出问题的硬件上复验成功。

分层排查可排除「缺少全部菜单素材」这类解释：菜单由独立 D3D/DirectComposition
owner 绘制；世界背景由 Qt OpenGL 的 `endfield_gaussian` 和 dim pass 绘制。
整页白色并不是当前背景处理的设计结果。

## 本机对照诊断

同一 Qt 主窗口（style `0x96cf0000`）分别加载旧、新 DLL，菜单完全展开后，
对**自身 HWND** 调用 `GetDC / GetClipBox / ReleaseDC`：

| 版本 | 原生菜单为 child | 主窗口 clip 类型 | 主窗口可绘制 clip box |
|---|---|---|---|
| 旧 `4f9116e` 随附 DLL | 是 | `NULLREGION (1)` | `0,0,0,0` |
| 修复 DLL | 否；owned popup | `SIMPLEREGION (2)` | `0,0,1280,720` |

这直接证实了全客户区 child clipping 风险；它不是另一台电脑完整白屏的截图，
也不推定所有驱动必然产生同一种底色。旧 DLL 的一次临时目录清理因 Windows
保持 DLL 映射而失败；改用忽略的持久诊断目录后重跑成功，数据与第一次相同。

## 已修复的代码风险

1. **去掉覆盖主客户区的 `WS_CHILD`。** 原生透明菜单原来是 Qt 主窗口的全尺寸
   子窗口，会参与主窗口的 child clipping；透明合成像素需要的 Qt 背景并不属于
   子窗口自身。在不同 OpenGL/DWM/驱动组合上，已提交的 FBO 正确也不能证明
   被重定向的主窗口背景仍完整可见。
2. 改成仅由客户端拥有的 `WS_POPUP`，保持 `NOREDIRECTIONBITMAP`、`NOACTIVATE`，
   不设置 desktop topmost、不抢焦点、不捕获桌面。它不再在 Qt 背景中挖空。
   原生 worker 使用 owner 的 DPI awareness，跟踪客户区物理坐标，适配移动、
   全屏和缩放；owner 隐藏/最小化时同时隐藏，恢复后重绘再显现。
3. 继续等待 **Qt 成功提交背景并实际 frameSwapped**，且原生第一帧成功 present
   之后才显示菜单，避免显示尚未初始化的交换链。处理 `WM_ERASEBKGND/WM_PAINT`，
   禁止 GDI 白色擦除覆盖透明表面。
4. 场景资源和原生代码分开选源：保留本地场景/声音/启动动画，但生产默认使用
   当前版本随附的 DLL，避免 `user_data` 的旧 DLL 悄悄盖过修复。不改写私人目录。
5. 验收原来只有梯度下降检查，纯白/纯黑也可能错误通过。现在同时检查背景为
   不透明、压暗后的 RGB 上限、去除压暗后的平均色接近源画面，增加白/黑/透明
   失败样本回归。

**未修改**上游场景、字体、曲线、shader、动画时长、液态玻璃材质及三个场地模型。
更新的是宿主窗口合成/生命周期及其随附二进制，不是用纯色背景遮挡问题。

Win32 规则依据：[owned window 的层级与最小化行为](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)、
[无 redirection bitmap 的透明合成](https://learn.microsoft.com/en-us/archive/msdn-magazine/2014/june/windows-with-c-high-performance-window-layering-using-the-windows-composition-engine)。
Qt 的 OpenGL widget 是先绘制到 FBO 再由顶层合成，不是可单独 swap 的原生窗口，
见 [QOpenGLWidget 文档](https://doc.qt.io/qt-6/qopenglwidget.html)。

## 更新与诊断

拉取修复时必须一起取得 `assets/endfield_pack/native_renderer/` 和更新后的完整清单，
然后**退出并重新启动客户端**；正在运行的旧 DLL 不会热替换。旧便携 EXE 不能
仅靠更新源码获得修复，需要按固定 commit 重建；本次不冒称已发布新 EXE。

不要删除用户配置、关闭高斯模糊、降低分辨率或修改游戏文件。若另一台机器仍发白，
请在该机保存实际 `renderer_init` 日志（显卡/vendor/renderer/version）以及以下检查
的 report；它只使用临时配置和 inert transports，不连接/操控车辆：

```powershell
python tools/verify_endfield_desktop.py --cycles 100 --out tmp_esc_recheck
```

输出目录必须是新目录。该工具检查自己的 GL/D3D render target、自己的 HWND、
完整的开关/反向/全屏/最小化恢复；它**不是桌面合成截图，也不能代替另一台电脑
实际显示的确认**。本机验证和限制见 `reports/esc-white-background-20261023/verification.json`。
所有实车/裁判/控制资格仍是独立验收，不能从本修复生成 READY。
