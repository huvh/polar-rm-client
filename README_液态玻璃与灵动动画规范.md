# POLAR-RM 液态玻璃与灵动动画规范

本文件是客户端液态玻璃、Dynamic Island、页面过渡和高刷新动画的唯一实现标准。修改相关代码前必须先阅读本文件；实现与本文冲突时，以本文为准。

## 1. 核心结论

液态玻璃不是半透明矩形、白色蒙层、黑色卡片或高斯模糊。POLAR-RM 的镜片必须同时满足：

1. 采样镜片后方的真实场景。
2. 需要折射轨道或强调线时，先把轨道与场景组成 Combined Backdrop。
3. 镜片中心保持稳定清晰。
4. 只在圆角形状的内侧窄边发生折射。
5. 折射方向由圆角 SDF 法线和 `circleMap` 决定。
6. 强镜片在边缘使用七段轻色散。
7. 镜片外部像素 alpha 必须为零。
8. 文字和图标永远画在镜片之上，不参与折射。

## 2. 权威参考

- 本地 `../AndroidLiquidGlass-kmp/AndroidLiquidGlass-kmp/`
  - `backdrop/.../internal/Shaders.kt`
  - `backdrop/.../effects/Lens.kt`
  - `backdrop/.../backdrops/CombinedBackdrop.kt`
  - `app/.../components/LiquidSlider.kt`
- 本地 `../liquid-glass-react-master/`：交互形变和指针响应参考。
- Kyant Glass Slider：<https://kyant.gitbook.io/backdrop/tutorials/glass-slider>
- Apple Materials：<https://developer.apple.com/design/human-interface-guidelines/materials>
- Apple Motion：<https://developer.apple.com/design/human-interface-guidelines/motion>
- 本地 Dynamic Island 示例仅用于单容器宽高平滑、裁剪和可逆时间线参考。

第三方来源与许可证记录在 `THIRD_PARTY_NOTICES.md`。产品界面、配置值和代码标识统一使用 POLAR-RM 语义。

## 2.1 经济工作区

经济工作区是镜片的独占使用场景：打开或收拢期间，只合成图传、经济 Control Backdrop、经济镜片、经济内容和交互层。地图、模块列表、目标卡、遥测、底盘指示和战斗通知必须从同一帧清空，不能作为“玻璃下方的信息层”。

根容器从顶部胶囊原位向下展开。根、选中分类和确认按钮使用强镜片且 `frostAmount = 0`；文字密集区域使用 Regular 镜片。商品轨道、金币进度和按住确认进度必须先写入 Economy Control Backdrop，再与图传合成为 Combined Backdrop。禁止用半透明深色 pane、加法高光或矩形描边替代镜片。

## 3. Combined Backdrop

Kyant Slider 的关键不是单独折射背景，而是同时折射背景与滑轨：

```text
SceneBackdrop   = 壁纸 / 视频 / 摄像头
ControlBackdrop = 需要出现在镜片下方的轨道或强调内容
Combined        = Control.rgb + Scene.rgb * (1 - Control.a)
LensInput       = Combined
```

轨道必须先进入 `ControlBackdrop`，再由镜片统一采样。禁止在镜片绘制完成后把轨道盖到镜片上，也禁止把整张卡片的装饰线误画进全屏 ControlBackdrop。

Kyant Slider 基准：

```text
thumb                  56 x 32 dp
track height            6 dp
refractionHeight       12 dp
refractionAmount       16 dp
chromaticAberration  true
```

只有滑块、选中胶囊、圆形图标等小型强镜片使用上述强度。文字密集的大卡片使用相同数学模型，但降低折射量和色散。

## 4. 镜片数学

### 4.1 圆角 SDF

```glsl
float sdRoundedRect(vec2 p, vec2 halfSize, float radius) {
    vec2 q = abs(p) - halfSize + vec2(radius);
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - radius;
}
```

`sd < 0` 表示在镜片内部，`sd > 0` 表示外部。胶囊必须使用 `radius = min(width, height) / 2`。

### 4.2 中心直接返回

```glsl
if (-sd >= refractionHeight) {
    return sampleCombined(uv);
}
```

中心不得重复模糊、发白、压黑或漂移。没有这条 early-out 的实现不合格。

### 4.3 边缘内折射

```glsl
float circleMap(float x) {
    x = clamp(x, 0.0, 1.0);
    return 1.0 - sqrt(max(0.0, 1.0 - x * x));
}

float edge = circleMap(1.0 - (-sd) / refractionHeight);
vec2 normal = normalize(gradSdRoundedRect(...) + depthEffect * normalize(centered));
vec2 refractedUv = uv - edge * refractionAmount * normal / viewport;
```

减号表示向内折射。不要用随意的径向缩放替代 SDF 法线。

### 4.4 七段色散

强镜片沿折射法线依次采样红、橙、黄、绿、青、蓝、紫。中心色散为零，越靠近边缘越明显。色散只能改变边缘采样位置，不能在整个面板上叠彩虹渐变。

## 5. 唯一 GPU 管线

```text
Scene FBO
  -> Control Backdrop FBO
  -> Shared Blur FBO
  -> Glass FBO
  -> Static UI FBO
  -> Dynamic UI FBO
  -> Present once
```

约束：

- 默认帧缓冲每帧只 present 一次。
- 不得在同一页面同时执行 QPainter 页面过渡和原生 OpenGL 页面过渡。
- 所有透明层使用预乘 alpha。
- 透明 FBO 清屏必须为 `(0, 0, 0, 0)`。
- 混合固定为 `GL_ONE, GL_ONE_MINUS_SRC_ALPHA`。
- 镜片外部片元必须 discard 或输出透明预乘色。
- 不得在玻璃层画文字、图标或不透明背景。

最终参考合成：

```text
glassScene = glass.rgb + scene.rgb * (1 - glass.a)
baseUi     = static.rgb + glassScene * (1 - static.a)
final      = dynamic.rgb + baseUi * (1 - dynamic.a)
```

## 6. 纹理方向

所有媒体源必须声明来源：

```text
TopLeftImage  = QImage、MP4 解码帧、摄像头帧
BottomLeftFbo = OpenGL FBO
```

方向转换只允许在上传阶段发生一次。FBO 之间复制不得再次翻转。禁止散落使用 `mirrored()`、固定 `flip_y` 或在 shader 与上传阶段各翻一次。

任何方向改动都必须通过四角测试图：左上红、右上绿、左下蓝、右下黄。

## 7. 组件规则

### Dynamic Island

- 圆角始终为高度一半。
- 根容器的宽、高、圆角、裁剪和内容 alpha 使用同一个 `MorphState`。
- 图标背景使用圆形 SDF，图标 quad 外部 alpha 为零。
- 不允许额外矩形描边、白色方块或持续扫光。

### 启动卡片与 SESSION

- 一张卡片只使用一层主镜片。
- SESSION 内部状态行是普通内容层，不再嵌套镜片。
- hover 只更新当前项和上一项的 transform、高光与 opacity。
- 鼠标移动不得重建背景、blur、文字或整页热点。

### POLAR One 与经济工作区

- 收起态为顶部 POLAR 胶囊，展开态为主面板；经济工作区使用同一套根容器动效。
- 根容器使用一个可逆时间线和一个 stencil/scissor。
- 列表和设置区各有独立惯性滚动，不得依赖根面板重新布局。
- 根容器使用 `LensStrong`，文字密集的商品、详情和状态区使用 `LensRegular`；内层不得再嵌套玻璃。
- 720p/900p 使用双栏响应布局，1080p 以上可用三栏；切换布局不得改变商品与交易语义。

### 战术地图

- Tab 只修改一个 morph target。
- 外框、地图视口、标题、底部状态和右侧遥测共享同一 progress。
- 不允许通过阈值瞬间切换某一部分。

## 8. 动画规则

- 动画使用单调时钟，与视频或摄像头帧率分离。
- 页面过渡 420ms；POLAR One 与经济工作区展开 620ms、收拢 480ms。
- 动画必须可从当前进度反向，不得重置起点。
- hover 使用低振幅位移，最大 1–3 逻辑像素。
- 禁止持续呼吸、循环扫光和无意义振荡。
- 静止界面停止高频动态提交；媒体纹理仍可按源帧更新。

## 9. 缓存与性能

缓存 key 只能包含尺寸、DPR、页面 epoch、内容 revision、媒体 sequence 和材质布局 revision。禁止包含当前时间、FPS、鼠标坐标、视差偏移或每帧动画 progress。

视频或摄像头仅在 sequence 改变时上传。同一源帧可供 120/144Hz UI 重复采样。背景 blur 每个媒体帧最多生成一次。

目标预算：2K 启动页和 ClickGUI P95 小于 8.3ms；摄像头 HUD P95 小于 11.1ms；鼠标快速 hover 不增加媒体上传或 blur 重建次数。

## 10. 材质分配表

材质必须由用途决定，禁止因为背景明暗临时换成另一套视觉：

| 材质 | 必须使用的位置 | 规则 |
|---|---|---|
| `LensStrong` | 启动主卡、比赛模式卡、机器人卡、POLAR One/经济工作区根容器、选中胶囊、滑块、圆形按钮 | 直接用 Combined Backdrop 替换镜片像素；不叠加 blur、白雾、整框描边或阴影 |
| `LensRegular` | SESSION、模块设置区、文字密集状态行、小地图状态卡 | 使用相同折射数学，只允许轻微柔化以保护文字；内层行不是第二层玻璃 |
| `LensIsland` | 顶部灵动岛、通知岛、模式切换胶囊 | 圆角恒为高度一半；尺寸、裁剪、圆角与内容透明度共享一个 morph 进度 |

文字、图标、数值和命中区域始终位于镜片层之上。强镜片外围不得再画完整矩形边框，否则圆角外会出现白色方框。

## 11. Kyant 基线回归

镜片公式修改后必须运行：

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe tmp_render_checks\render_kyant_reference.py
```

固定参数：原控件 `56×32`，预览 `420×240`，`refractionHeight=90`，`refractionAmount=-120`，`depthEffect=0`，开启七段色散。脚本生成：

- `kyant_glass_slider_source_formula.png`：依据本地源码公式生成的参考图。
- `kyant_glass_slider_implementation.png`：客户端正式实现图。
- `kyant_glass_slider_difference_heatmap.png`：像素差异热图。
- `kyant_glass_slider_alpha.png`：镜片 alpha，外部必须为零。

自动门槛为镜片轮廓 IoU 不低于 `0.97`。此外必须人工检查顶部绿色/青蓝内折射弧、弯曲的蓝色轨道和下沿黄紫青连续色散；单纯通过数值门槛不能替代视觉验收。

公式来源以本地 `AndroidLiquidGlass-kmp/backdrop` 中的 `Shaders.kt`、`Lens.kt` 为准。七次采样需要同时按原始权重累加 RGB，并对 alpha 取七次平均；不得在入口使用象限翻转修补错误方向。

## 12. 禁止清单

- 透明白矩形或黑色半透明卡片冒充玻璃。
- 整块白膜、灰膜或横向扫光。
- 玻璃套玻璃。
- 镜片中心持续模糊或折射。
- 在镜片外留下矩形 alpha。
- QPainter 和裸 OpenGL 同时绘制同一过渡。
- 每个控件单独模糊一次背景。
- 30 FPS 摄像头限制 HUD 动画到 30 FPS。
- 为高分屏优化偷偷替换用户样式。

## 13. 验收与排错

每次玻璃或合成器修改必须完成：

1. Kyant 四色背景 + 蓝色轨道基线：背景和轨道同时折射。
2. 镜片中心清晰、边缘位移明显、七段色散只在边缘。
3. 镜片外 alpha 为零，无白色方块或长条。
4. 四角方向测试覆盖静态图、MP4、摄像头和 FBO。
5. 一级、二级、三级往返 100 次，无残影。
6. Dynamic Island、POLAR One、经济工作区和战术地图可中途反向。
7. 记录上传、blur、glass、static UI、dynamic UI 和 present 的 P50/P95。

| 现象 | 优先检查 |
|---|---|
| 白色方框 | SDF 外 alpha、FBO 清屏、图标 quad、预乘 alpha |
| 长白条 | ControlBackdrop 范围、嵌套镜片、额外矩形描边 |
| 页面残影 | 双重过渡、旧 page epoch、outgoing FBO 未清理 |
| 画面倒置 | TextureOrigin 是否被转换两次 |
| 高 FPS 仍卡顿 | 动画是否跟随视频帧、缓存 key 是否包含时间或鼠标 |
| 玻璃像透明框 | Combined Backdrop 未接入、折射量为零、错误 early-out |
