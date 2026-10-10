# 渲染 CPU 缓存优化验证

## 结论与范围

本补丁基于安全/UI 修复树 `3bf4091772a14ac309326f1e058bf6080eb3f5ec`，性能分支独立。
本报告记录其中的缓存子补丁：`rm_client/ui/fonts.py` 与 `rm_client/ui/clickgui_gpu.py`，共新增 32 行。
当前分支还包括 `animation.py` 与 `polar/primitives.py` 的 [动画时钟/暂停恢复补丁](ANIMATION_PACING_20261011.md)，其回归和基准单独记录。
证据支持减少重复字体构造和已命中文字图集的 CPU 工作；**尚未测得完整客户端的 FPS 或 GPU 帧耗时改善**。
不得将下面的 helper 倍率或耗时百分比解释为整机 FPS 提升。

整体补丁保留正常帧的动画曲线/时长、弹簧参数、布局、字体属性、shader、颜色、玻璃/模糊质量、分辨率、DPR、目标刷新率、视频上传节奏、渲染层顺序和控制安全门禁。漏帧后的岛内内容现按完整 elapsed 追上容器，暂停恢复跳过过期显示 deadline，精确静止 spring 跳过数学计算；因此不宣称动画代码或异常帧恢复完全未变。

## 热点依据

1. `FontBook.font()` 原先每次从 family 创建 QFont，再重复设置字号、Jello Light/Medium 风格与 weight、Tahoma 的 NoAntialias。HUD/地图/经济/启动页存在重复调用，静态 AST 共找到 UI 目录 349 个 `.font()` 调用点，分布于 13 个文件；这只是调用点数量，不是每帧调用次数。Jello 主列表已有自己的局部 font 缓存，本改动不将那里的收益重复计入。
2. `_prepare_atlases()` 每帧按字体分组后调用 `_ensure_atlas()` / `_ensure_shaped_atlas()`。即使纹理页已经完全涵盖本帧文字，旧路径仍 `set(known)` 复制整页、update，再比较整个集合。新路径仅确认请求是已知集合的子集，返回原纹理对象并保持原 hit 计数。
3. 视频 sequence 上传、共享 blur 与绝对动画时钟已有相关保护；未为追求基准数字改动这些高风险渲染路径。

## 缓存正确性

- FontBook key 包含语义 font key、当前实际 family、**不四舍五入的 point size**、显式 weight。Light/Medium 风格与 Tahoma 策略由原语义 key 固定。
- 缓存内容是逻辑 QFont 描述，不是字体 metrics、光栅图片或 GPU 页。DPI/DPR 仍由每个 painter/atlas 的原有路径消费，不把设备相关像素复用到另一设备。
- 每次返回 QFont 的独立、隐式共享副本，调用方的字体修改不会污染后续返回值。
- family 映射改变时立即使用新 key；`load_from_project_assets()` 一开始清空缓存，涵盖 family 名不变的重载。
- 这里不保证任意全局 `QFont.insertSubstitution/removeSubstitution` 在已解析缓存中立即生效。独立评审用 Qt5 复现过这种外部替换边界；当前仓库没有使用这些 API。若以后新增此能力，需要一并显式使 FontBook 与既有文字/图集缓存失效。
- 每个 FontBook 最多 512 项，按最早插入项淘汰。独立实例之间不共享缓存。
- 图集的新字符/新整行、DPR/字号/weight/raster scale/preserve_weight 改动、没有已发布纹理、超过原有容量的页，仍走原有 miss/eviction/rebuild 路径。没有放宽 render-pass mutation lock，也没有修改 cold rebuild 的 raster 或 texture 参数。

## 同条件微基准

Python 3.13.5，Linux x86_64，系统 PyQt5。9 轮、前后交错顺序、相同进程/字体/输入、暖身后测量；表内为每个 batch/call 的中位耗时。微基准执行期间暂时禁用 Python GC，前后恢复。
此云主机有时序噪声；完整 min/max、case 数、source SHA-256 与图像 hash 保存在 [原始结果](render-cache-benchmark-20261011.json)。

| 工作量 | before | after | CPU 耗时变化 |
|---|---:|---:|---:|
| 128 次重复字体请求 | 279.40 µs | 151.60 µs | -45.7% |
| 实际 _prepare_atlases：80 commands / 4 resident pages | 230.38 µs | 156.20 µs | -32.2% |
| 128 个首次出现的字体尺寸（冷缓存代价） | 283.41 µs | 402.23 µs | +41.9% |
| glyph 页 512 项 / 请求 80 项 | 21.15 µs | 7.88 µs | -62.7% |
| shaped 页 512 项 / 请求 45 项 | 13.54 µs | 4.51 µs | -66.7% |
| shaped 页 512 项 / 请求 512 项 | 44.96 µs | 32.35 µs | -28.0% |

另外覆盖 glyph 95/512/1024 项、shaped 128/512/2048 项及稠密全量请求。2048 行页的暖命中有较大局部倍率，但那是单个集合检查，不代表正常画面或整帧有同等倍率。

**冷缓存成本已显式保留：**新尺寸需要额外 dictionary 操作和一个安全 QFont 副本，128 个首次出现的尺寸在本次测量中约多 0.12 ms。窗口连续缩放/大量全新字号时不能假设字体缓存总会加速。常见固定逻辑字号可复用；真实 resize/动画压力场景仍在 GPU 实机验收清单里。

## 回归验证

通过：

- 新增缓存回归 15/15：命中、空/重复文字、修改返回字体、独立实例、精确分数字号、weight、fallback/family 变化、同名重载、512 项容量、图集容量边界、新字符/新整行、无纹理、DPR/raster policy 变化、render-pass guard。
- 字体值 128 组与优化前 QFont 相等。
- 字体 QImage 9 组：DPR 1/1.5/2 × DPI 96/120/144，混合 Latin/CJK/fallback/Light/Medium/Tahoma 与分数字号，**每组 changed bytes = 0**。
- 实际图集 CPU 光栅代码 18 组：glyph/shaped × DPR 1/1.5/2 × cold/rebuild/warm。图像非空，**每组 changed bytes = 0**，字形/整行位置与 metrics 一致、generation/hit/miss 计数一致，新字符时替换并销毁旧纹理、暖命中保留同一对象。
- 独立评审补充的 Unicode/方向矩阵已保存为可复现工具并复跑 **144/144 PASS**：LTR/RTL × DPR 1/1.5/2 × raster scale 0.75/1.3 × preserve_weight 开/关 × glyph/shaped × cold/rebuild/warm。包含 Arabic、Hebrew、组合音标、emoji 与中日韩；像素、metrics、计数和纹理生命周期均与基线一致。[矩阵结果](render-cache-unicode-20261011.json) 记录汇总 hash。此项不证明环境安装了全部字形字体，fallback/缺字方框仍可能与基线相同。
- `polar_link_test.py`：79 PASS（已有外部三方 CRC 参考缺失项仍为 SKIP）。
- `polar_bridge_test.py`：185 PASS。
- `polar_integration_test.py`：51 PASS。静态确认其串口由内存 PipeSerial 替代；执行时额外审计钩子禁止 socket 与非 git 子进程，unexpected attempts = []。
- `test_transport_safety_regressions.py`：36/36 PASS。
- 修改的 Python 文件 `py_compile` 与 `git diff --check` 通过。

当前默认 Python 无 PySide6，新回归的纯逻辑部分可独立通过（8 条），7 条字体测试需 PySide6，或显式 `--qt5` 使用现有系统 Qt5 做离屏对比。没有装依赖，也没有启动完整应用、设备、网络连接或真实机器人自检。

### 验证边界

Qt5 离屏结果是**优化前后相对一致性**证据，不能替代 PySide6/Qt6 的完整应用、Windows DirectWrite、GPU driver 或 QOpenGLWidget 验收。图集测试只用 inert texture publisher 承接真实 CPU raster 输出，没有执行 GPU upload/present。未运行完整 smoke/api_freeze/真实 GPU runtime suite，未声称它们通过。

## 复现

准备优化前两份文件，例如从基线提交导出到 `../baseline/rm_client/ui/`；基准工具只读取指定的本地基线，不自动创建任务或连接服务。

```sh
python tests/test_render_performance_regressions.py
python tools/benchmark_render_caches.py --baseline-root ../baseline --output benchmark.json
# 只有系统 PyQt5 时显式使用；不能据此宣布 Qt6/GL 验收通过：
/usr/bin/python3 tests/test_render_performance_regressions.py --qt5
/usr/bin/python3 tools/benchmark_render_caches.py --qt5 --baseline-root ../baseline --output benchmark-qt5.json
/usr/bin/python3 tools/check_render_cache_unicode.py --qt5 --baseline-root ../baseline --output unicode-qt5.json
```

## 剩余真实 GPU 验收

在用户原有 PySide6 运行环境，由其启动测试（不连接真实硬件/比赛服务）：

1. 同一设备、配置、分辨率、DPR、视频片段与预热时间，分别测基线和性能分支。记录完整 frame/present P50/P95/P99、实际 FPS，以及 glyph/texture upload/blur 重建计数。
2. 2560×1440、可用的 100%/150%/200% 缩放：启动页 hover；Jello 反复/快速开关、模块切换、英文/中文/长文本、设置滚动；HUD 视频与地图/经济/部署面板切换。
3. 包含冷启动、首次见字、字体重新加载、连续 resize/屏幕 DPI 切换，核对潜在冷缓存开销和字体缓存淘汰。
4. 使用应用内 `grabFramebuffer()` 的同帧截图验证；真实 GL 验收不设置 `QT_QPA_PLATFORM=offscreen`，不靠外部窗口截图判断硬件表面。
5. 若实机帧时间/FPS无显著改善，应按实际数据报告；不能减少特效质量、分辨率或动画节奏来凑结果。
