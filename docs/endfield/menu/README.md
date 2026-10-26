# Esc右侧功能栏惯性（2026-10-25）

目录封装与新增“UI切换”占位卡片已在同日后续完成；当前目录、原生构建和资源数量以 [Endfield UI 功能封装](../README.md) 为准。下文保留惯性修复时的构建与验收记录。

从本机游戏VFS只读重新导出 `common/watchpanel_pc.prefab`，共3298个对象、0 failures。`canvas_watch/RightBottomNode/ScrollView` 为纵向UIScrollRect，Inertia=1、DecelerationRate=.13500000536441803、Elasticity=.10000000149011612、MovementType=1；原始分包按VFS的偏移、长度及MD5再次核验。这些字段与运行包对应组件一致。来源摘录见 [source-reference.json](evidence/20261025-inertia/source-reference.json)。

原有 `SourceWatchSession` 的拖动手势没有保留松手速度，列表内松手便停住。现在 `native/endfield/bridge.cpp` 内的独立 `MenuDragInertia` 负责拖动速度平滑与自由滑动减速；使用本体的减速率，按 `rate^deltaTime` 衰减，速度低于每秒1个源布局单位时停止。速度估计与积分参照 [Unity官方ScrollRect.LateUpdate](https://github.com/Unity-Technologies/uGUI/blob/main/com.unity.ugui/Runtime/UGUI/UI/Core/ScrollRect.cs#L793-L848)。归一化位移通过原相机与滚动平面的精确投影换算成momentum手势，继续由原会话绘制、裁切和处理边缘回弹；没有改写上游固定源码、按钮身份或功能动作。原会话的弹簧仍为既有适配，本轮没有将其等同于游戏自定义UIScrollRect的全部内部实现。

新的按下会立即中止惯性。滚轮、键盘导航、暂停、尺寸变化、关闭及语言重建同样会清掉暂态速度；按住停稳后松手不会继续甩动。拖动仍由原会话抑制按钮激活，原生线程只产生界面动作，不持有机器人输出权限。`pe_scroll` 是有界、只读的自有实例诊断，普通客户端帧不读回图像。

原生DLL已重编译，内置 `CURRENT.json` 现在指向 `build_53c48e410da9f131`，SHA-256为 `cc45f496848279df5c369c3e20c8a991fae9fd5a043b4366fcc8130aca5b1d3e`；旧 `build_58a4d44ef8b653f7` 保留在包中，未覆盖旧二进制。完整性清单包括57个资源文件及两代构建，均未被Git忽略，运行只加载CURRENT指定的版本。已有客户端实例仍持有旧DLL，重启后加载新实现。构建仍有两条既有 `filesystem::u8path` 弃用提示，无编译或链接错误。

验证过程中发现原准备/校验工具调用了Python3.12才有的 `Path.is_junction`，在本机3.11环境中无法执行完整包验收。工具现共用 `lstat.st_reparse_tag` 检查目录联接，仍拒绝越界链接；新增联接拒绝用例，未关闭资源或路径校验。

141项相关回归及静态检查通过。实际自有D3D实例验证松手衰减、再次按住、停稳松手、暂停、边界和关闭重开六种情况；150%真实Qt鼠标事件链另验证了逻辑/物理坐标转换及松手后的持续移动。100%/150%完整客户端检查、三个场地在1280×720和2560×1440的D3D渲染检查均通过，56纹理/57网格保持稳定，所有原生实例正常退出。报告及松手/滑行截图封装于 [evidence/20261025-inertia](evidence/20261025-inertia)。没有启动或修改游戏，没有执行Git暂存、提交或push。

```powershell
python -m tools.endfield.menu.verify_inertia --pack rm_client/ui/endfield/menu/assets --out tmp/endfield/menu/inertia-new
python tools/endfield/prepare_pack.py check --pack rm_client/ui/endfield/menu/assets
```
