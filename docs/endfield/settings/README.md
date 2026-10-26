# Endfield 设置中心

按用户给出的游戏设置截图和 `W:\yj games\Arknights Endfield` 本体资源，替换整个 Jello 设置中心。覆盖视频、音频、游戏、键盘／鼠标、准星、界面／HUD 六页，以及设置中心内打开的键位管理弹窗。原 `cs2_settings_center` 导入路径和 `JelloSettingsCenter` 对象 ID 保留以兼容既有启动入口。

## 2026-10-26 首次模态打开错位修复

用户反馈的视频页缩成半栏、显示器名称竖排和关闭按钮越界已在真实 `QApplication.exec → open_settings_center → QDialog.exec` 路径复现。原实现先把 basic/advanced 放进旧 ScrollArea，再直接改父对象；旧 ScrollArea 仍持有子页并修改其尺寸。构建时的 `deleteLater` 在生产嵌套事件循环中不会及时执行，导致旧容器持续覆盖新布局。此前独立预览使用 `.show()` 和外部尺寸调整，遗漏了这个所有权错误。

嵌入视频页现在直接构造连续列表，不再创建或依赖释放旧滚动容器。设置行仅由外层窗口计算列宽，不在行 resize 回调中修改子控件约束；标题、分类导航和关闭按钮改由顶部网格布局管理。入场快照等待原生显示事件完成并明确处理子布局请求，避免缓存尚未展开的页面。

新增回归在正在运行的事件循环中构造并 exec 设置页，保留正常 DeferredDelete 时序，检查首次快照及稳定画面。`tools.endfield.settings.verify_modal` 使用真实 PolarRMWindow、共享 GL 上下文和生产设置入口，检查 1225×704、1000×620、1920×1080 的六页、顶部导航点击和 F12；150% DPR 另用独立进程验证。报告与截图见 `evidence/20261026-layout/`。

## 资源和表现

2026-10-26 补齐滚动动效：从当前安装本体重新导出四个设置相关 Lua，解密后的 VFS 数据 MD5 与索引一致；设置 prefab 原分包也重新核验了 SHA-256。参数和源位置见 `evidence/20261026-scroll/source-reference.json`。

滚轮和程序定位现在采用源 `smoothScrollTweenSpd=1000`、`smoothScrollTweenEase=3`、`smoothScrollTweenMaxDur=2`；枚举 3 对应 [DOTween 官方 Ease.OutSine](https://github.com/Demigiant/dotween/blob/develop/_DOTween.Assembly/DOTween/Ease.cs)，不再逐格跳变。速度随源布局比例换算，连续反向从当前位置接续。触控板像素流直接跟随设备事件，避免重复叠加系统惯性。

拖动可从行背景和文字开始，超过拖动阈值后取得手势；按钮、下拉和数值滑块仍保留自己的点击/拖动。速度按源惯性 `.13500000536441803` 衰减，边界使用 `.55` RubberDelta 阻力及源 `.10000000149011612` 弹性时间回到范围。公式依据 [Unity 官方 ScrollRect](https://github.com/Unity-Technologies/uGUI/blob/main/com.unity.ugui/Runtime/UGUI/UI/Core/ScrollRect.cs)，自由惯性距离采用解析积分，减少不同帧率的累计差异。额外越界提示仍依源 `_enableOverScrollEffect=0` 关闭，弹性位移与额外提示不是同一选项。

上下软遮罩使用源 `m_Softness.y=50` 和底部 padding=-20；局部绘制同一背景，不对整个设置树做逐帧截图。滚轮在下拉框上经过只滚页面，打开的选项列表和嵌套参数区由最内层滚动区接收。滚动条、切页、失焦、调整大小和关闭均中止暂态动量、复位内容变换；不修改任何草稿值或机器人输出。

新增八项滚动回归覆盖 30/60/144 Hz 衰减一致性、反向、弹性重抓、真实 Qt 子控件路由、松手惯性、嵌套所有权及生命周期。真实客户端模态验证记录 20/60/160 ms 的滚轮位置，另检查拖动减速、250 ms 回弹、切页中止和 150% DPR。`tools.endfield.settings.verify_modal --compact --scroll --record --out <dir>` 生成实际控件中间帧；相关脚本用于 Qt 适配的验收，并非运行游戏 C# 组件。

`rm_client/ui/endfield/settings/assets` 自带 14 张本体纹理、原始中文字体、10 组动画和完整性清单。资源来源为 `gamesettingpanel.prefab`、`gamesettingitemcellv2.prefab` 及其依赖；20 个实际游戏分包已逐包核验偏移、长度、MD5 和 SHA-256。具体路径和对象 ID 见包内 `PROVENANCE.json`；字体及游戏素材权利说明见 `NOTICE.txt`。

- 主页面进场采样 `gamesetting_in`：顶部从源坐标 Y=80 回到 0，内容从 -97 回到 -45，位移约 417 ms、透明度约 333 ms；退场采样 `gamesetting_out`，约 167 ms。
- 分类切换采样 `gamesetting_change`，167–333 ms 渐显。顶部黄色选中材质和图标闪动使用 `setting_tabcell_selected_in`，保留 150/183/217/250 ms 的显隐关键帧。
- 下拉菜单采样 `dropdownlist_in/out` 的透明度和高度，约 133 ms；布尔胶囊采样 `common_toggle_to_left01/right01` 的锚点曲线，约 200 ms，快速反向从当前姿态继续。
- 设置行使用原等高线、点阵、斜纹及灰色九切片背景；九切片边界来自原 Sprite。滚轮步长来自设置 ScrollRect 的 45，拖动惯性使用原 `.13500000536441803` 衰减率。
- 打开时通过客户端自己的 `grabFramebuffer()` 冻结 GL 背景并模糊，只处理一次，不抓取其他窗口，不持续读回视频。无有效 GL 父窗口时使用深色底。Qt 是实际绘制器；游戏专有 shader、场景渲染和模糊内核没有原样嵌入，不应宣称与游戏逐像素或逐帧完全一致。

顶部图标对应既有六个客户端分类，悬停显示分类名称，Q/E 和原生方向键可切页；输入框与下拉编辑不被 Q/E 抢占。原搜索保留，筛选时整行背景同时隐藏。视频基础与高级项合并为连续列表，顶部显示真实显示器和屏幕输出信息，不伪造游戏设备负载或显存估计。

## 业务边界

页面继续使用原偏好草稿、异步构建队列、配置事务和应用回调。关闭或切换页面不会自动保存草稿或恢复驾驶授权；F12 走原急停服务。键位弹窗复用 `BindingSession`，确认只写入父设置页草稿，外层“应用当前页”才修改配置；冲突及保留键规则不变。准星保留实际预览、分享码和原字段。

表现层位于 `rm_client/ui/endfield/settings/`：`shell.py` 管主壳和页切换，`widgets.py` 管设置行及控件，`scroll.py` 管滚动，`bindings.py` 管键位列表，`background.py` 管冻结背景，`resources.py` 管只读资源。离线解包依赖不进入客户端。

## 重建和验证

使用 EndfieldStudio 的 `original --full` 从本体只读导出设置 prefab、动画和依赖后，在安装有 UnityPy/Pillow 的离线工具环境运行：

```powershell
python -m tools.endfield.settings.prepare --export <settings-export> --export <dependency-export> --out rm_client/ui/endfield/settings/assets --bundle-index <bundle-and-initbundle-index.json> --game-vfs "W:\yj games\Arknights Endfield\Endfield_Data\StreamingAssets\VFS"
python tools/endfield/settings/check_assets.py --asset-root rm_client/ui/endfield/settings/assets
.venv/Scripts/python.exe tests/endfield/settings/test_center.py
.venv/Scripts/python.exe tools/quality_gate.py
.venv/Scripts/python.exe -m tools.endfield.settings.verify_desktop --out tmp/endfield_settings/desktop
.venv/Scripts/python.exe -m tools.endfield.settings.verify_modal --out tmp/endfield_settings/modal
```

桌面验证使用 Windows Qt 原生窗口和惰性设备替身，通过窗口自身的 `grab()` 保存设置页。覆盖 1000×620、1280×720、1920×1080、2560×1440 的六分类、键位弹窗、下拉展开/关闭及嵌套 F12；另用真实 OpenGL 父窗口检查冻结模糊背景。150% DPR 使用独立进程设置 `QT_SCALE_FACTOR=1.5` 后运行 `--compact`。这些验证不替代车辆硬件联调。

当前代表截图、来源摘录和运行报告保存于 `evidence/20261026/`。源码和便携版通过 `RuntimePaths` 定位同一资源包；发布脚本复制并校验设置资源。
