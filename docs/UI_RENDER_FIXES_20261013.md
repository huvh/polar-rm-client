# 2026-10-13 UI 修复与本机验证

## 范围

基线：`fix/client-ui-device-audio-20261011` / `bfe2dba`，本轮修改尚未提交。
不切换分支、不推送；未编辑用户 `configs/default.json`、`user_data/configs/default.json`、`_pdf_extract.txt`。
没有修改液态玻璃 shader、材质参数、渲染分辨率、声音、动画曲线/时长、模型、瞄准阈值、控制协议或安全门。

## 根因与修复

1. **白色圆角溢出/实色矩形**：QPainter 绘制层的 FBO 原为 `NoAttachment`，缺少其路径/描边/非矩形裁剪需要的 stencil。只给 QPainter 层添加 CombinedDepthStencil，纯 shader/blur/glass 层仍为颜色附件。真实 GL 负对照能复现错误，修后角落与透明内部验证通过。
2. **中文与混排**：保留 Jello Helvetica Light/Medium；中文明确 Regular YaHei UI → YaHei → DengXian → 系统无衬线。按字体全部属性、文本、DPI/DPR 缓存 QTextLayout，整行共同基线对齐，不逐字舍入。ESC 中文也使用该成形路径。
3. **ModList 对齐**：按最终翻译后的文字和实际字体测量、排序；GPU 中文宽度匹配实际 hinted atlas 的 DPR，不把 1x advance 简单乘 DPR。英文原版几何与 150ms 动画保留。固定阴影路径不再每显示帧 stat 文件。
4. **Minecraft 中文**：Unihex 的 16 行以前在 8px 逻辑层上被丢掉一半，再放大已无法恢复。现在以原生 2x 密度缓存、nearest 合成，保留真实 advance/baseline。整数缩放时只上传有内容的无损裁剪，非整数 fit 保留整图以避免采样相位变化；像素相等测试覆盖两语言、分辨率、倍率、地图开关。
5. **YOLO/GIL**：模型推理之外，原 Python 循环每帧对全部 25,200 候选计算 sigmoid。现在 NumPy 双精度保守预筛，边界候选保留，最终仍由原 scalar 比较决定；分类、四点、光强采样、NMS、顺序不变。新旧完整结果精确对比通过。16 个候选的筛选微基准 5.48→0.45ms；这不等于整机 FPS 倍率。
6. **CS2 顶栏**：紧凑头像、连续边框、细 HP 条、灰化/阵亡标记、中心计时与比分。头像/文字按有效密度缓存，热帧不再重画相同文字；未知与实际数据过期规则不变。

## 本机真实 OpenGL 测量

Windows 11 / i9-13900HX / Python 3.12.14；HUD GPU 为 RTX 5070 Ti Laptop，OpenGL 3.3 / NVIDIA 596.21。
使用 `tools/profile_hud_live.py`：独立 user_data、LabDebug、实控始终禁止；摄像头、Local 视觉和 RobotLink 展示显式开启，视觉实际执行设备报告为 OpenVINO `GPU.0`（不将其等同于 NVIDIA HUD GPU）。全部 HUD 开关与用户配置一致，硬件输出与音频单独隔离。

| 场景 | 大小 / DPR | 时长 | 平均呈现 FPS | paintGL P95 | 呈现间隔 P95 |
|---|---|---:|---:|---:|---:|
| 摄像头 + Local + MC/CS2/HUD | 2560×1392 / 1 | 10s | 74.4 | 11.45ms | 21.19ms |
| 摄像头 + Local + Jello HUD 设置 | 2560×1392 / 1 | 8s | 75.0 | 9.33ms | 16.17ms |

计时在 framebuffer capture 前结束，未启用 cProfile；不是离屏 QImage 或只开静态空窗口的 FPS。`paintGL` 是 CPU 绘制调用耗时，不是 GPU timestamp 或完整端到端延迟；FPS 用实际呈现完成间隔计算。早期 8–15 FPS 的用户日志与此独立隔离测量不是严格同条件 A/B。

平均值已落在 70–90 区间，但长帧仍存在，**不保证每帧≥70 FPS**；ClickGUI P95 9.33ms 尚未达到此前 8.3ms 目标。尚未完成比赛长度 soak、真车/现场图传、全分辨率×DPR 的完整实机矩阵。桌面 UI 测试不解锁比赛控制，也不形成 READY 结论。

本地原始结果（忽略项，不随源码提交）：`tmp_ui_camera_verified/metrics.json`、`tmp_ui_clickgui_verified/metrics.json`，包含驱动、实际视觉设备、摄像头连接状态及分阶段耗时。现场日志新增真实 renderer/path/error 和各 pass 计时；旧 `compositor_ms` 读取不存在属性而恒为 0 的问题已纠正。

额外 native GL 验证：DPR=2、逻辑1280×696（物理2560×1392）截图成功；预热任务**全部结束**后做100次 ClickGUI/ESC快速反向，纹理计数前后均为25普通字库+12整行字库+15资源纹理，界面正常恢复、无GL错误。早期未等全局预热结束的两次试验观察到25页之前的字库增长，不能误报成“已预热稳定”。此压力测试不是100次完全展开动画，也未开启摄像头/推理。MC无损裁剪另有64组像素精确比较，覆盖DPR1/1.25/1.5/2；分数设备缩放不满足相位条件时保留整图。

源码比较确认合成器5段GLSL与HEAD完全相同；这不能替代所有液态玻璃场景的完整截图基线验收。

## 自动验证

- unittest `test*.py`：430 项，428 PASS / 2 条显式 SKIP；GPU 专项另用 native GL 强制验证。
- 新 ESC 真实 GL / 像素：7 PASS；Jello 荧光白装甲 CPU/GPU：18 PASS。
- MC、中文、ModList、CS2 与融合专项联合：129 PASS；CS2/旧 locale/native 测试：48 PASS。
- 完整 smoke：72 个函数 PASS（修正已在基线过时的 BlackHole 壁纸列表断言）。
- backend_protocol：198 checks PASS；API freeze、compileall、`git diff --check` PASS。

可复测（先进入仓库根目录，PowerShell）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='.;tests'
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test*.py' -q
.venv\Scripts\python.exe -X utf8 tests/test_escape_menu_corner_pixels.py --require-gpu
.venv\Scripts\python.exe -X utf8 tests/test_jello_white_armor_overlay.py --require-gpu
.venv\Scripts\python.exe -X utf8 tools/profile_hud_live.py --out NEW_DIRECTORY --webcam --local-vision --preview-controls --warmup 10 --seconds 10 --capture
```

输出目录必须是新目录。默认不启动摄像头/视觉；不允许 Qt offscreen/minimal 冒充桌面 GL。`--scene clickgui --settings HUD` 可复测设置页；`--cycles 100` 是快速反向切换压力，不是 100 次完整展开动画验收。所有配置副本和截图都在隔离输出目录，禁止用本工具解锁实控。
