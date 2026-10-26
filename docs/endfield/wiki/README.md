# Endfield Wiki 终端适配

2026-10-25：Wiki 已纳入统一 Endfield 功能包，资源与工具一起迁移；目录和交付说明见 [Endfield UI 功能封装](../README.md)。页面逻辑和原有模块功能保持兼容。

2026-10-24 将 F8 / Right Shift 的默认终端界面替换为 Wiki 的页面结构。首页显示战斗、移动、视觉、战术、系统、渲染六个编号入口；顶部是可点击路径、全局搜索和关闭按钮。进入分类后，左侧列出该分类的二级模块，右侧直接显示所选模块的三级设置。首次进入默认选中第一个模块，再次进入恢复上次选择；左右两栏独立滚动。搜索采用左侧结果、右侧预览、详情按钮的流程。

## 功能与所有权

- 原注册表的 74 个 Module、473 个 Setting 保留身份、ID、值和动作路由，没有另建展示用假模块。
- 右侧顶部的启停使用原 `jello_module_press` 路径，保留九格功能栏拖放。数值、布尔、模式和动作继续调用原 `after_setting_changed` / `config_action`，快捷键继续使用原键盘管理器。左侧选择模块只切换右侧设置，不修改启停状态或设置值。
- 三项只读文本显示原值，并支持点击复制。配置导入、导出、保存、旧界面入口仍从原模块设置访问。
- 搜索匹配中文/英文模块名、原 ID、说明、设置名称与当前值；保留最多三个本次进程搜索历史，支持中文 IME。
- Esc 按下拉 → 搜索 → 分类分栏 → 首页 → 关闭终端逐层返回，分类内不再有额外卡片页。方向键在左侧模块间切换并直接更新右侧设置，长目录自动滚动到选中项。F8 / Right Shift 直接关闭整页。终端自己的按键和关闭鼠标手势持有松开事件，F12 仍先执行原急停路由。
- 仅改展示、导航和输入适配，不修改后端协议、模块目录、遥测或控制授权规则。

`JelloSigma`、`jello_state` 等原有配置与兼容接口名称继续保留，避免旧配置失效。默认装配实际使用 `EndfieldWikiRenderer`、`EndfieldWikiState` 和 `EndfieldWikiTimeline`。直接使用旧 `JelloClickGuiRenderer` 的兼容调用和旧界面测试仍可运行。

## 资源与动画

用户提供的解包目录为 `C:\endfield_ui\Endfield_Wiki_UI`，本机游戏位于 `W:\yj games\Arknights Endfield`。使用 EndfieldStudio 的 `original --full` 只读导出 354 个选中资源包，导出报告为 0 failures；没有写入游戏目录或启动游戏进程。

终端使用小型 `rm_client/ui/endfield/wiki/assets` 包，包含六类几何图形与选中层、编号、等高线/装饰和 29 组 60 Hz 原始动画曲线，以及二级按钮 Animator 的状态值。材质烘焙、源包、对象 ID 和输出 SHA-256 见该目录的 `PROVENANCE.json`。包内 fonts/ 附带相同版本的 Noto Sans SC 及 OFL 许可；返回、关闭和搜索图标也来自本体纹理。

二级目录按 `wikigrouppanel.prefab/TabCell` 的 100 px 行高、50 px 图标、30 px 标题、深色选中底、黄色竖线适配，图标来自本体 `groupicon/icon_wiki_group_*.png`，按语义映射到现有 RM 模块。选中地形线使用 `bg_wiki_equip_btn_select`，未添加百科红点；启停仍由右侧原开关负责。路径使用 `wiki_folder` 和 `wiki_arrows` 原图，按 `FolderCell` 的 26 px 字号、祖先左右各20 px/当前左右0 px留白及38.5 px间距计算宽度。祖先节点深底白字、当前节点无深底且不接收点击的行为依据本体 `WikiTop.lua/InitWikiTop`；分栏选中的模块不增加页面路径层级，过长路径会省略文字以保留搜索区域。

曲线采样保留原关键帧、入/出切线、加权 Bézier 和 Infinity 阶跃；首页采用原 `wiki_in` 的六项错峰入场，背景/编号、悬停装饰、分类页和搜索页使用对应轨道。主时钟入场 750 ms、退场约 167 ms。运行时只生成既有 GPU 绘制指令，不依赖游戏、Unity、解包器或网络。

页面切换先保留旧页面播放约 167 ms 的 out，再播放新页面的 in；分类左右两栏分别使用 `wiki_group_in/out`，目录单元使用 `wiki_group_leftcell_in`。选中项的横向展开、黄线闪动、图标/文字延迟出现取自 `wiki_group_leftcellselect/out`，右侧模块切换使用 `itembigleft_in`：从左侧20 px回到原位，透明度0→1，约333 ms完成；旧设置同时采样 `wiki_group_out` 的 Center 透明度，约167 ms退场。该叠化是终端可编辑面板的适配，原游戏列表通过 UpdateCount 回收旧单元；没有把它冒称为游戏的独立 switchout 动画。连续选择沿用正在播放的过渡，退场控件不发布热点或滚动目标。`wiki_group_leftcellselect_btn.controller` 的 Highlighted 为普通底 RGB=.62、选中底 RGB=.196；悬停即时进入，移出约100 ms恢复。相同模块重复点击保留原设置状态。

搜索按本体 `WikiSearchCtrl.lua` 和 `FullScreenBlurUI/useWhiteBlur` 的覆盖关系绘制：当前终端指令先进入私有 FBO，经两遍 GPU Gaussian 磨砂后绘制清晰搜索层；CPU 兼容路径使用 Qt BlurEffect。叠底灰色与透明度取自 prefab，模糊核是 Qt/OpenGL 适配，不声称复制游戏引擎 shader。普通搜索框326×50、覆盖层498×50，左右内容、输入框分别采样 `wiki_search_in/out`。关闭或进入详情均等待覆盖层退场；首页叉号关闭终端，其余页面的原图左箭头返回上级。

悬停黑色竖栏同时采样 `ImgBgBlackmask/m_Alpha` 的约83 ms轨道和 `m_Softness.y` 的1000→200（约83→500 ms）轨道；GPU及CPU兼容路径均在纵向做软遮罩，从中心向上下展开，独立于750 ms的其他装饰。六类选中图使用原 `deco_wiki_select_icon_1…6` 彩色详细图，按 SelectNode 的 450×400 画幅显示，并隐藏对应普通几何符号、编号和标题；圆形网点与竖向符号也取自原资源。三条悬停轨道按单调时钟推进，帧间隔较长时不再因截断帧时间而慢放，快速移入/移出从当前值连续反向。

这是面向 RM 功能的适配：游戏中的武器、材料和百科内容改为终端模块，详情区域承载可编辑设置；原游戏模型与特有 shader 没有嵌入 Qt 运行时。动画的二维位置、透明度、装饰与选中反馈按源曲线适配到这些控件。

离线重建（在工具环境安装 UnityPy / Pillow，不是客户端运行依赖）：

```powershell
python -m tools.endfield.wiki.prepare --export-root C:\Temp\codex-wiki-export --cell-export-root C:\Temp\codex-wiki-cell-exact --extra-export-root tmp/endfield_wiki/20261025-effects/dependency-export --out rm_client/ui/endfield/wiki/assets
```

加上 `--bundle-index C:\Temp\codex-wiki-bundle-list.json --game-vfs "W:\yj games\Arknights Endfield\Endfield_Data\StreamingAssets\VFS\7064D8E2"` 可直接读取本体分包并按 VFS 的偏移、长度和 MD5 核验原始来源；清单记录实际 SHA-256，不改动游戏文件。

## 验证

```powershell
.\.venv\Scripts\python.exe tests/endfield/wiki/test_terminal.py
.\.venv\Scripts\python.exe tools/quality_gate.py
.\.venv\Scripts\python.exe -m tools.endfield.wiki.verify_desktop --out tmp/endfield_wiki/desktop
```

离线用例检查全部模块、全部设置控件的可达性与对象身份、搜索预览、返回层级、中文输入、原控件回调、急停优先级、关闭期间输入归属、曲线关键帧和字库字号。桌面工具使用临时配置及惰性设备启动替身，真实显示 Windows/OpenGL 窗口，并通过窗口自己的 `grabFramebuffer()` 抓帧；不以外部窗口截图判断 GL 是否渲染。

实际环境为 Windows、Python 3.11.9、PySide6 6.12.0、OpenGL 4。验证覆盖 1000×620、1280×720、1920×1080、2560×1440，以及 150% DPR。桌面帧与报告保存在本目录内的 `evidence/20261024-baseline`。这组检查验证界面和输入路由，未替代硬件联调。

分类分栏修正的证据保存在 `evidence/20261024-category`：18 项 Wiki 用例加上帧契约、快捷键及 Esc 菜单回归共 55 项通过，静态质量检查通过。此次分栏使用 100% DPR 的真实 OpenGL 窗口，在上述四种窗口尺寸检查左侧模块与右侧设置不重叠，并验证移动分类默认小陀螺、模块切换、搜索直达及一层返回首页。GPU 与合成器错误均为空。

图标与路径修正的证据保存在 `evidence/20261024-icons-path`：21 项 Wiki 用例及上述三组回归共 58 项通过，静态质量检查通过；100% 和 150% DPR 真实窗口均通过 OpenGL 验收。中文及英文路径按文字首选宽度扩展，遍历 74 个英文模块路径未覆盖搜索栏。资源来源核验扩展到纹理、三个相关 prefab 及 15 组动画所在的 41 个本体分包，摘要见该目录的 `PROVENANCE.json`。

动效与搜索覆盖层修正的证据保存在 `evidence/20261024-motion`：27 项 Wiki 用例及帧契约、快捷键、Esc 菜单、GPU presenter、字库资源回归共84项通过，静态检查与 GPU runtime smoke 通过。真实 OpenGL 的100%及150% DPR验收通过，150%记录了15张进退/切换中间帧，磨砂双遍实际执行。53个本体分包的来源核验涵盖新曲线、搜索prefab及按钮controller；GPU与合成器错误均为空。硬件通信不在此验证范围。

二级切换修正进一步沿本体 `WikiGroupCtrl._SetSelectedIndex → _RefreshScrollListCenter → ItemScrollListCenter.UpdateCount` 检查 prefab 引用：ItemBig 的 `_animationIn` 指向外部文件23、对象1847661073427808780，对应 `common/itembigleft_in.anim`（CAB-78d92be8479259eeb8dec10606c248b2）。因此撤掉误套的 `wiki_groupitemlist_in`（展开列表、根位移-200 px）。补充资源用 EndfieldStudio 从本体 Bundle `main/c5b8c4a00d7b1fa1209a2683.ab` 只读导出，0 failures；离线重建时将该导出目录传给 `--cell-export-root`。

本次二级切换验证证据见 `evidence/20261024-switch`：29项 Wiki、20项帧契约和4项快捷键回归共53项通过，静态检查通过。真实 Windows/OpenGL 验收通过，保存50/120/220/340 ms切换帧；GPU与合成器无错误。54个本体分包通过偏移/长度/MD5来源核验。`source-reference.json` 保存 prefab 外部引用与实际动画对象的对应证据。


## 背景与首页悬停补齐（2026-10-24）

直接读取 `wiki_uideco.prefab/HudNode/BgDecoLayout` 的层级、颜色、枢轴、尺寸及父子关系；地图、两层点环、双层大环、三角定位标记、三角底纹和底部扫描线均使用原纹理。Tiled 图像按原尺寸及 PixelsPerUnitMultiplier 离线铺贴，避免把小三角纹理拉伸成整屏图案。此前漏掉的 `wiki_uideco_loop/m_RotationCurves` 已接入：五条旋转轨道各保留7199个60 Hz四元数转换角度样本，保留转向、相位与循环长度，同时播放原闪动透明度和扫描线位移。背景使用原CanvasGroup透明度，撤掉了此前额外削弱的透明度倍率。游戏世界UI的二维投影适配到终端画布；未嵌入游戏场景或游戏专用材质。

首页选中层不再用三个归一化进度代替整条动画，而以 `wiki_btnoption_select/out` 的实际时间分别采样。顶部的 LeftPointImage/RightPointImage 从中心附近向两侧移动；灰色 ImgDeco1/2 按原宽度、纵向位置和枢轴展开；中心图标保留暗色→原色与VFX亮度轨道、背景点阵的明暗闪变；ImgTriangle1 在633/667/700/733 ms闪现，ImgTriangle2在733/767/800/833 ms闪现。三角贴图保持白色遮罩并按原黄色染色，两个三角均位于中心图标下方，修正此前一个画到竖栏上部、另一个画到竖栏下部的问题。快速移入移出从当前姿态接续，离开播放约167 ms原退场。

`home_blackmask.svg`仅提供本体无Sprite的纯色矩形采样，颜色来自Bg的RGB≈.0706；软边在GPU片段着色器计算，CPU兼容路径采用同样的渐变覆盖率。图片命令新增可选旋转和纵向软边，默认值保持旧控件行为。单浮点Uniform使用PySide明确的setUniformValue1f，避免被整数重载截断或因负角度溢出。

本次验收证据位于 `evidence/20261024-background-hover`：33项Wiki及帧契约、快捷键、Esc菜单、GPU presenter、字库回归共90项通过，静态检查和GPU runtime smoke通过。100%与150% DPR真实Windows/OpenGL均通过：50 ms软遮罩上缘/中部像素灰度分别223/115及224/114，确认中心先变黑；保存九张悬停中间帧和背景循环前后帧。62个本体分包通过源VFS偏移、长度、MD5核验，GPU及合成器错误均为空。


## 功能目录与集成边界

```text
rm_client/ui/endfield/wiki/
    __init__.py       窗口依赖的公开接口
    renderer.py       页面、控件、热点和滚动区域绘制
    state.py          页面与搜索生命周期、过渡状态
    navigation.py     导航、键盘和原 host 动作路由
    query.py          搜索与分类过滤，返回原 Module 对象
    motion.py         原曲线、旋转和悬停姿态采样
    decor.py          背景与首页选中装饰
    background.py     背景页面入退、持续循环及根Canvas投影
    layers.py         本体顶部层级、分割线及最近搜索卡片
    list_input.py     目录的按下/拖动/松开归属
    list_fade.py      上下边缘软遮罩绘制指令
    scroll.py         惯性、边界阻力和回弹物理
    assets/           图片、曲线、字体、许可及完整性清单
tools/endfield/wiki/                 资源准备、隔离桌面验收入口
tests/endfield/wiki/                 Wiki 功能回归
docs/endfield/wiki/                  当前说明、历史记录和 evidence/
tmp/endfield_wiki/                   本机调试结果（Git 忽略）
```

外部窗口和输入适配器统一从 `rm_client.ui.endfield.wiki` 引入公开接口，内部文件通过包内相对引用连接；不保留同名旧入口或两套类定义。`clickgui_gpu.py`、`jello_clickgui.py` 与 `clickgui_frost.py` 属于所有 ClickGUI 共用的图像、兼容绘制及磨砂设施，因此留在共享 UI 层。工具不被客户端导入，UnityPy/Pillow 仍只用于离线准备。

测试由现有注册表递归发现，运行 `python tools/verify_all.py --test test_terminal`；桌面验收运行 `python -m tools.endfield.wiki.verify_desktop --out tmp/endfield_wiki/desktop`。资源准备命令见上方。源码从 `rm_client/ui/endfield/wiki/assets` 加载；发布脚本单独复制到 `resources/assets/endfield_wiki`，复制前后都校验完整性清单。

根目录原67项 `tmp_wiki*` 调试文件与目录完整移入 `tmp/endfield_wiki/archive/`；其中历史脚本保留当时内容，仅作取证归档，不作为维护入口。整理前文件清单和摘要位于 `tmp/endfield_wiki/organization/before.json`。既有取证 JSON 内的旧命令、源码路径及快照保持原样，实际归档位置以本说明为准；暂停记录位于 `history/PAUSE_20261024.md`。

本轮检查的未提交内容还包含图传、控制器链路、协议门禁、原生 HUD 构建等其他任务的改动。这些内容保留原位；本轮重组只涉及 Wiki 功能文件及直接引用、文档入口。未执行提交或暂存。

## 资源随代码分发检查（2026-10-24）

新增 Wiki 资源已封装到 `rm_client/ui/endfield/wiki/assets/`。移除未使用的旧 `close.svg`、`search.svg`；其余原图片和曲线保持不变。字体及 OFL 许可放在包内 `fonts/`，不再通过 `../endfield_pack/` 借用字体。运行包共105个文件，包含99个图片引用、24组曲线、字体及来源清单。运行不需要本机解包目录、游戏目录或 `C:\Temp`。

`RUNTIME_MANIFEST.json` 记录全部运行文件的大小与 SHA-256；准备工具在生成后写入清单。校验工具检查全部摘要、图片/字体引用、包内路径边界及字体许可。`.gitattributes` 对该目录使用 `-text`，防止 Windows 的 `core.autocrlf=true` 改写 JSON、SVG 或许可文件而破坏摘要。发布脚本在 Git 源码快照内和复制到便携版后分别校验，缺失文件会中止构建。

```powershell
python -m tools.endfield.wiki.check_assets
# 提交前核对 Git 索引是否包含全部资源；不会自动暂存或提交。
python -m tools.endfield.wiki.check_assets --require-tracked
python tools/verify_all.py --test test_assets --test test_terminal
```

`rm_client` 是 Python 代码包，Git 仓库根目录是 `polar-rm-client`。原有公共 UI 资源仍在根目录 `assets/`，不必位于 Python 包内才能随仓库分发。本轮实际扫描两处554个资源文件：446个已有索引记录、105个新增 Wiki 文件、3个现有原生 HUD 新构建文件；没有资源被 Git 忽略。原生 HUD 的54项清单摘要均匹配，但新构建的 DLL、BUILD_MANIFEST 与 MIT 许可同样需要随其 CURRENT/主清单一起提交。未执行 add、commit 或 push；仅 push 已有提交不会携带这些新增文件。

资源完整性、隔离便携目录、缺失字体和修改曲线检测，以及界面/装配/测试注册表共112项回归通过。真实 Windows/OpenGL 窗口使用新路径通过验收，74个模块、472项设置及搜索磨砂正常，GPU/合成器错误为空；未执行完整发布包构建。结果摘要见 `evidence/20261024-resources/`。

## 首页方块锚点与重复悬停修正（2026-10-24）

再次只读核对本机游戏 VFS 中的 `wikibtnoptionwidget.prefab`、`wikipanel.prefab` 和 `wiki_btnoption_select/out`。本轮重建的62个来源包仍按偏移、长度和MD5核验，四个方块及布局涉及的6个包摘要、原始RectTransform和完整相关曲线见 `evidence/20261024-hover-blocks/source-reference.json`。

顶部 `RightPointImage` 锚在父节点左上、枢轴(0,0)，`LeftPointImage` 锚在右上、枢轴(1,0)；两者8×8，纵向偏移+3，水平轨道分别为160→0、-160→0，持续500 ms。父节点宽度为单元320+SelectNode的4，单元间距1.5。此前把238 px的栏宽和另一套.816比例的位移混用，造成起点交叉。现在以终端保留的257 px单元节距统一换算锚点、宽度、位移，初始两块在中心重合，再向左右分开到两角。

灰块 `ImgDeco1/2` 固定x=-125/+131，枢轴分别为(0,.5)/(1,.5)，高12；50–100 ms显现，333–450 ms宽度50→14，450–750 ms才从同一y=84分别移至199/-91。所有位置以拉伸后的SelectNode父矩形为参照，撤掉由图标位置拼出的中心偏移。原始颜色74→114及加权曲线保留。选择层的图标与其他装饰也使用相同父中心，避免方块与图标各用一套坐标。

本体out片段对这四块只绑定透明度；未绑定的位置、宽度和颜色必须保留当前姿态。此前退场会把几何补间推向默认终点，完整退场后的再进入还会叠加旧偏移。现在未绑定属性保持原值，完整退场后按一次新的in播放，短暂反向仍从当下姿态接续。

新增回归固定检查中心重合/两角终点、灰块三个阶段、退场几何保持、完整退场后两次进入一致；加上资源、帧契约、快捷键和Esc检查共77项通过，静态质量检查通过。资源包105个文件与离线重建逐字节一致。真实Windows/OpenGL在100%及150%缩放下通过，保存50–850 ms中间帧，并在750 ms实际读取到灰块/黑块像素114/6，验证绘制结果而非只检查曲线数值。报告及100/450/750 ms三帧位于同一证据目录。

## 路径层级与原图圆角修正（2026-10-24）

从当前安装的游戏只读重新导出 `Data/LuaScripts/UI/Widgets/WikiTop.lua`，1个文件、0 failures。当前版本明确对末级单元关闭bgImg、arrowImg和NonDrawingGraphic的raycastTarget；祖先单元才显示底框和出箭头。终端的分类分栏属于同一页面，右侧设置随左侧模块更新，不能把所选模块再追加为一个页面。因此首页只有根路径且无黑底，进入分类后仅根路径有黑底，分类为无黑底的当前路径；模块切换和搜索直达都保留这个层级。

底框实际引用 `deco_wiki_top_bg`，Sprite为16×16，边界按左/上/右/下为7/8/8/7。离线工具先按Sprite.textureRect从20×20导出纹理中去除外围填充，再切成9块；运行时保留四角和边缘，仅拉伸中心。普通底框高38，悬停高亮高40、上移2，均使用原图透明边缘；撤掉4 px几何圆角和悬停方形覆盖。current状态左右留白为0，normal状态为20，文字和底框宽度仍由字体实际宽度计算。

本轮包内新增9张切片，运行包共114文件、108个图片引用；均位于 `rm_client/ui/endfield/wiki/assets/`，与字体、动画和完整性清单一起随源码分发，离线重建逐字节一致。79项资源、Wiki、帧契约、快捷键及Esc回归通过，静态质量检查通过。源码依据、运行报告及路径截图保存于 `evidence/20261024-breadcrumbs/`；历史证据中的105文件/99图片计数对应当时版本。

100%及150%真实Windows/OpenGL验收通过，首页/分类/切换模块/返回首页的黑底数量为0/1/1/0；悬停增加的是同一底框上的白色高亮层。150%帧采样圆角外侧/内部灰度238/57，确认角部透出底色。GPU与合成器无错误，74个模块和472项设置保留。

目录整理验收见 `evidence/20261024-organization`：7组134项回归通过（Windows以 `PYTHONUTF8=1` 避免既有注册表测试的系统GBK读取问题），静态检查通过；新桌面工具入口的真实Windows/OpenGL验收通过，74模块与472设置仍可用。重建到独立目录的101个运行包文件与当前包逐文件SHA-256一致；整理前后的154个其余既有文件摘要一致，无额外变更；根目录Wiki临时项为0，67项历史调试资料均保留。

## 直接入口导航与普通灰图交接（2026-10-25）

Esc原生菜单的8个模块快捷入口及启动页配置入口原来直接调用 `jello_state.open_settings`，只设置模块、未建立Wiki分类。现在统一分发 `jello_open_settings`，经 `prepare_module_selection` 设置分类、记住模块、预热原资源并打开原设置；同一模块缺失分类时也能修复上下文。右上角还根据模块页状态防御性显示返回键，返回仍使用原页面退场轨道。没有更换Module/Setting对象或后端命令。

首页右上角退出，以及Esc/Backspace退至最外层的退出，统一关闭终端并打开现有Esc模态；输入清空、原生等待背景/展开和释放事件隔离继续由原所有者处理。F8/RightShift保留原快捷开关行为，未修改通用 `set_clickgui_visible(False)` 的其他调用者。

普通中心灰图在悬停首帧即隐藏，不再等待约83 ms软遮罩扩散。选中层此前还使用普通图标再绘制一次 `ImgIconVFX2`，其透明度到约583 ms才降为0，造成重影；撤掉这份重复灰图，保留详细Selected/Flash两层、背景扩散、角块和黄色三角的原轨道。移出后普通图标仍随原退场遮罩恢复。此处是针对终端残留的显示适配，资源包及原始动画曲线保持原样。

新增回归覆盖8个Esc入口、启动配置入口、缺失分类修复、首页退出的Esc目标及松开事件、悬停首帧到后续帧的唯一普通图层透明度。Wiki、帧契约、配置命令、Esc与原生菜单共114项回归通过，静态检查和114文件的资源完整性检查通过。结果见 `evidence/20261025-navigation/`。

真实Windows/OpenGL验收通过，直接打开战术地图、比赛就绪检查和运行场景均显示返回键；50–850 ms悬停中间帧的普通图标只有一个且透明度为0。首页点击退出后Esc原生渲染器ready=true、phase=1、error为空，并从客户端自有D3D帧读回非空菜单图像 `terminal_exit_native.png`。Qt的grabFramebuffer只包含该原生层下方的磨砂底图，因此不以这张Qt底图冒充Esc菜单截图。GPU及合成器无错误；没有替代设备联调。


## 斜纹、背景流动、拖动目录与最近搜索（2026-10-25）

再次从本机安装的游戏只读核对 `wikitopwidget.prefab`、`wikigrouppanel.prefab`、`wikisearchpanel.prefab`、`wiki_uideco.prefab`，以及顶部循环、搜索标题/卡片入场片段和场景白色流动材质。新增两组原片段后，运行包包含26组曲线、161个图片引用、167个文件；81个实际使用的来源分包经过VFS偏移、长度及MD5核验。来源摘要与本轮结果位于 `evidence/20261025-effects/`。

首页选中列保留原 `deco_wiki_select_bg` 的斜纹明暗，先绘制软黑遮罩，再绘制原斜纹，避免斜纹被纯黑整层覆盖。顶部网点按本体UIImage的Tiled方式重复115×106纹理，而非横向拉伸；顶部循环驱动网点横移及分割线的透明度、滑动亮段。顶部装饰在搜索磨砂上方单独呈现，保持与截图一致的清晰度。

上下白色流动使用游戏 `M_fxui_wiki_white_ground_01` 的主贴图 `T_fx_mask_1123_M`、遮罩 `T_fx_mask_1124_M` 及原 `.2 UV/s` 主滚动速度。Qt中将其做成重复移动并在纵向羽化的二维投影；原游戏3D网格、噪声形变和专用shader没有嵌入终端。因此此部分是参照实际材质的二维适配，不能称为游戏3D效果的逐像素复现。`ButtomDecoLayout` 在实际入场片段中保持alpha=0，未擅自将隐藏星点当作背景流动特效显示。

二级目录按游戏ScrollRect的vertical=true、horizontal=false、clamp及decelerationRate=.135实现拖动与惯性。左键按下只记录候选项，松开且未超过6px阈值才选择；纵向拖动只滚动列表，横向移出也不触发候选项。返回、快捷键和切换页面会取消候选手势。上下边缘按原RectMask2D的10px softness生成透明度裁切带，GPU和兼容绘制使用相同指令；原模块启停、设置和输出路由保持不变。

搜索覆盖层将模糊半径从18提高到72个设计像素，并先降采样再做两遍GPU高斯模糊，消除大采样间隔造成的条带。它覆盖当前页面；游戏专用磨砂shader由Qt模糊适配。最近搜索改用原TitleNode横条、三列历史卡片和等高线贴图：源单元551×68、间距11×14、左/上内边距124/94，按.8换算到终端1920画布。保留最多三项历史、中文输入和原模块搜索/直达功能。输入框包含“请输入文字”和搜索按钮。498×50源尺寸与页面其他节点统一按.8换算为398.4×40，右端1800.8；搜索按钮底图90×38和返回图78×78也采用相同比例，避免把源像素与终端画布混用。

历史卡片的等高线通过 `imgUsePathReference/imgRefPath` 延迟引用，原m_Sprite为0；离线提取现已解析该路径。标题右端的小标识和悬停底图则沿游戏BundleManifest的依赖表定位到 `deco_assembly07.png` 与 `bg_common_r5_p2.png`，使用原Sprite及九宫格，不用其他装饰代替。缺少依赖Sprite会使重建失败。所有成品仍封装在 `rm_client/ui/endfield/wiki/assets`，运行时无需游戏目录或解包目录；与空目录独立重建结果逐文件一致，未发现被Git忽略的资源。

49项Wiki、3项资源、20项帧契约、10项presenter、4项快捷键、13项Esc、14项背景关闭、9项指针归属、4项焦点丢失，共126项不同回归通过；静态质量检查通过，初始化依赖环为0。真实Windows/OpenGL使用临时配置和惰性设备启动验收，原74个模块及当前473项设置可达；桌面证据包含拖动后所选模块不变、搜索磨砂、原图纹理和进退中间帧。未执行Git暂存、提交或push，也未修改游戏文件。

本轮100%和150%缩放的完整Windows/OpenGL验收均通过，GPU与合成器错误为空。搜索输入框最后一次比例校准后，补充150%实机窗口的尺寸、中文IME和搜索按钮检查也通过；`search-aligned-150.json`及`recent_search_150.png`记录最终布局，`desktop-150.json`记录完整交互验收。


## 越界回弹、底部波形与左下角文字（2026-10-25）

本轮纠正上一版直接clamp导致边界反馈被截掉的问题。实际滚动位置继续限制在0至maximum，单独保存暂态越界位移；拖动两端时阻力随拉伸距离增加，松手后以.1秒参数的临界阻尼回到边界。惯性撞到边界和滚轮触顶/触底也会反馈；回弹途中再次按住可从当前姿态接续。目录、搜索结果和右侧原设置的滚轮均接入，原启停和设置控件仍由原动作持有。

本体同组ScrollRect存在不同配置：Left和ItemCenter为MovementType=2，MonsterCenter为1，均记录Elasticity=.1；不是所有目录都默认弹性。本轮按用户要求统一补齐终端目录的越界表现，采用同组弹性列表的参数。源配置和终端适配边界已明确记录在 `evidence/20261025-overscroll/source-reference.json`。

左下角实际是 `wikipanel.prefab/Main/BgNode/Deco1`，不是上一版自行绘制的静态标签。该节点使用 `M_text_scroll_blcak` 与 `T_ui_deco_factravelpole_text02`，MainTexUVSpeed.y=-.1。现保留原173×70尺寸、底部锚点、.698透明度及原文字贴图，在裁切框内循环移动；同一BgNode的原边角装饰一起接入，隐藏的BgImg不显示。

底部波形改用实际地面Mesh `s_fx_ground_fj_02/transform1` 的27354个顶点及两套UV，使用白色地面材质的主纹理、遮罩、10×8噪声坐标、.7位移强度、.4的z方向及.1噪声速度；相机采用Main的24度视场、(0,1,8)位置与.07水平镜头偏移。特别读取 `wikimodelshow.prefab` 内的实例覆盖：piece_01的y=-1.6、scale=(2,2,1)、旋转(.5,.5,-.5,.5)，父级scale=1.6。独立wiki_scene.prefab的几何覆盖值不同，不能直接替代游戏实际实例。

离线工具 `wave_assets.py` 用这些参数生成10秒循环、80张640×180投影帧，运行时仅绘制当前与下一帧并连续插值。波形位于地图/点环下方，以淡灰和纵向渐隐合入终端底部；这替代了游戏场景光照和后处理，不是完整游戏shader。角色相关doughnut顶点效果未嵌入。重建投影需要PySide6桌面OpenGL；游戏、UnityPy和Pillow仍不参与客户端运行。工具检查实际GL错误及帧摘要变化，避免输出静态空白却报成功。

资源包现在为250个文件、244个图片引用、26组原曲线，共约21.7MB；波形统一放在 `assets/waves/`，其余新增代码、离线工具、测试和证据仍按功能归档。87个来源游戏分包通过VFS摘要核验。运行包与空目录独立重建逐文件一致，未发现被Git忽略的资源；没有暂存、提交或push。

52项Wiki、3项资源、14项背景关闭、20项帧契约、10项presenter、4项快捷键、13项Esc、9项指针、3项滚轮路由、4项焦点丢失，共132项回归通过；静态检查通过，初始化依赖环为0。真实Windows/OpenGL的100%及150%窗口均验证两端越界、回弹中间帧和回到边界，选择不变；150%另验证最终淡灰波形。150px的拉伸产生约70.90px阻力位移，松手100ms后约28.78px，随后归零。74个模块及473项设置保留，GPU/合成器错误为空。截图和报告见上述证据目录；100%报告的波形为本轮调色前取证，最终布局以150%截图为准。


## 页面切换时的背景生命周期（2026-10-25）

从当前安装游戏重新只读导出WikiCtrl、WikiGroupCtrl、WikiSearchCtrl、PhaseWiki及PhaseBase共5份Lua，0 failures；同时核对wiki_uideco的原片段。首页OnCreate/OnShow调用 `wiki_uideco_in`，分类OnCreate/OnShow调用 `wiki_uideco_grouppanel_in`，分类_OnPlayAnimationOut调用 `wiki_uideco_grouppanel_out`。PhaseWiki还会检查场景初始化和Phase过渡状态后再清除Tween、播放片段。搜索采用当前页面场景磨砂覆盖，源码没有重新播放这些背景入场。

此前背景一直按session_time采样首页in，只接了循环，未接分类的背景入退。本轮单独建立 `WikiBackground` 生命周期，由分类导航事件触发；同页选择模块和搜索不改变背景事件序号。普通关闭使用 `wiki_uideco_out` 的HudNode透明度轨道。未绑定的属性保留上个片段姿态；明确绑定的闪烁、缩放和透明度按原关键帧采样。主背景、星点、顶部装饰、底部波形和流动文字的循环时钟持续运行，切页不归零。

分类入场的根缩放为.003→.0025，AnchoredPosition.y为1.08→.8，持续约.833秒；BgDecoLayout透明度0→.6在约.333秒内完成，ButtomDecoLayout透明度0→1在约.833秒完成。根Canvas是世界空间对象，不能把.28直接当作屏幕像素。本轮用Main/Common相同的24度视场和(0,1,8)镜头进行换算，保留已适配的首页基准；稳定分类背景缩为首页5/6，下移约88.92个1920画布像素。分类底部原线纹和星点层也随根变换、透明度显示。

返回先播放分类背景out，再在终端现有1/6秒页面退场交接后按首页OnShow语义播放首页in。这个交接时间是终端页面结构的适配；原始out片段和全部关键帧保留在包内。终端的三级设置仍在同一分栏内，因此模块选择保持分类背景，不引入游戏3D模型详情页的另一套场景缩放。

新增3组原片段后，运行包仍为250个文件、244个图片引用，曲线增至29组；90个来源分包通过本机VFS偏移、长度、MD5核验。与空目录独立重建逐文件一致，资源均在rm_client功能包内，没有暂存、提交或push。源码摘录、摘要、曲线及实机中间帧位于 `evidence/20261025-background-switch/`。

56项Wiki加资源、帧契约、presenter、快捷键、Esc、背景关闭、指针、滚轮和焦点回归共136项通过；静态检查通过，初始化依赖环为0。真实Windows/OpenGL记录进入分类80/250/450/800ms、返回80/240/900ms的背景片段、投影参数和透明度；同页模块切换保持5/6缩放，直接入口、搜索返回、越界回弹和原生Esc退出继续通过。74个模块、473项设置保留；本轮只验证界面和输入路由。

本轮100%及150%缩放的真实窗口验收均通过，GPU/合成器错误为空。`background-keyframes.gif`由自有Qt帧缓冲的进入/返回关键帧组成，用于比较姿态和淡入淡出，不是实时录屏。

## 圆弧、页面装饰、全屏比例及搜索状态修正（2026-10-25）

再次核对本机游戏导出的 `wiki_uideco.prefab`、`wikimodelshow.prefab`、`wikipanel.prefab`、`wikigrouppanel.prefab`、地面材质和Tab按钮控制器，并通过本体VFS的偏移、长度和摘要重新验证90个实际使用的来源分包。摘录和适配边界见 `evidence/20261025-background-corrections/source-reference.json`。

中心的 `DecoDecoRing` 和子节点实际为UIImage Filled/Radial360，FillAmount分别.25和.12，FillOrigin=0、Clockwise=true。此前仅提取整张圆环贴图，漏掉填充几何，旋转后仍表现为完整圆。现在离线按原起点和方向裁出弧段，并以4倍抗锯齿保留透明边缘；运行继续采样原 `wiki_uideco_loop` 的旋转，不另造转速或整圆装饰。

左下角流动文字和边角节点属于首页 `WikiPanel/Main/BgNode`；分类面板没有该节点。现在根据实际呈现中的页面决定是否绘制，进入二级页面后隐藏，返回首页恢复；文字循环时钟保持连续。背景波面仍使用原网格、UV、实例变换、Main相机和噪声投影，撤掉先前覆盖大半波面的额外渐隐限制，以更宽的平滑渐隐保留更多细节，同时避免网格远端露出硬边。最终灰度深度22、裁切图内渐隐45–125px是Qt底色的适配参数，不冒称游戏shader原值。检查过的球形背景MainTex2在原材质中 `_UseMain2=0`，Plane实例也未激活，因此没有为了加密波纹把这些停用层添加进来；游戏特有的角色doughnut位移、光照和后处理仍未嵌入Qt。

全屏缩放原来将窗口适配比例与用户Scale取最小值，默认在1倍封顶，超过1920×1080后内容缩在中间。改为1920×1080画布的窗口适配比例乘以原用户Scale，统一作用于图片、文字、圆角、裁切、列表位移与热点。保留16:9画布等比居中；这是终端布局适配，并不声称复制了游戏全局CanvasScaler的运行实现。

搜索结果与二级目录共用Tab控制器的颜色及悬停时钟：普通底RGB=.698、alpha=.75，悬停RGB=.62、alpha=1；选中底RGB=.247，选中悬停为.196。选中项采用原等高线装饰、白色标题，撤掉黄色矩形选中；背景圆角与二级目录统一为4个设计像素。搜索、键盘定位、滚动、预览和进入原模块设置的行为保留。

最终资源仍为250个文件、244个图片引用、29组曲线，约22.0MB，均封装在rm_client功能包内；与空目录重建逐文件摘要一致，没有被Git忽略的资源。140项相关回归、静态质量检查，以及100%／150% Windows/OpenGL实机验收通过；包含首页全屏、分类布局、搜索选择/悬停、上下回弹和Esc退出，74个模块与473项设置保留。100%另补充分类全屏抓帧。未修改游戏文件，未执行暂存、提交或push。

## 搜索选择后的悬停与切换反馈（2026-10-25）

复现了列表点击完成后 `background_release_owned=True` 的问题：目录为区分单击和拖动，在release阶段才分发选择；Wiki动作原本按press阶段调用设计，又登记了一次待消费release。该release已执行完毕，后续普通鼠标move便被 `track_owned_pointer` 拦住，hover_point停止更新。现在列表分发选择后收尾消费本次所有权；若回调建立了新的拖动则保留新捕获。搜索与二级目录共用这个修复，不把鼠标事件泄漏给控制输出。

搜索选择通过同一个状态入口处理鼠标和方向键，保存切换前预览及开始时刻。目录详情与搜索预览共用 `_switch_content`：旧内容采样 `wiki_group_out` 的Center透明度，新内容采样 `itembigleft_in` 的20px短移与约1/3秒淡入；旧预览不生成“查看模块详情”热点。快速连续选择沿用最初淡出来源和同一时钟，只更新最新目标；重复点击当前结果不重启动效，修改查询时清除旧预览。左侧选中底框的展开、等高线显现和移出淡化也与二级目录共用原曲线及绘制函数，不再瞬间更换底色。

新增复现和回归检查涵盖真实Qt点击松开后的悬停、搜索预览交叉淡化及唯一有效详情目标、键盘与快速切换、重复选择和查询重置。143项相关回归通过，静态质量检查通过，初始化依赖环为0。完整100% Windows/OpenGL验收通过，另在150%实际窗口连续选择三次，未滚动时悬停仍为原高亮RGB=#9e9e9e；74模块、473设置及原输入/退出路由保留，GPU与合成器错误为空。

实机80ms帧中，旧预览alpha约.530、新预览alpha约.145，新标题x约1099.38；380ms后只有新预览，alpha=1、x=1110，详情热点始终指向新模块。原资源包250文件、244图片、29曲线未改变，完整性检查通过。来源、回归、100%完整报告、150%专项报告和截图位于 `evidence/20261025-search-interaction/`；GIF为抽取关键帧的姿态比较，不是实时录屏。未执行暂存、提交或push。
