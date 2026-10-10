# Bugfix branch: `fix/clickgui-targethud-v2`

## 设计原则（与仓库现有架构一致）

1. **TargetHUD** 继续走独立 `target_fbo`，不污染 dynamic/ESP 层。  
2. Windows Qt OpenGL AA 矩形脏区：用与 `upload_dynamic_image` **相同**的「小区域 CPU 光栅 + `glTexSubImage2D` 精确替换」策略，**禁止**全屏 CPU 离屏（会导致 ~1 FPS）。  
3. **ClickGUI**：GPU 路径 layout **只算一次**；`paint_clickgui_overlay` 的 `hotspots.clear()` 之后恢复 snapshot，而不是每帧再 layout 两遍。

## 回退

```powershell
git checkout main
git branch -D fix/clickgui-targethud-v2
git push origin --delete fix/clickgui-targethud-v2
```

## 验证

```powershell
.\.venv\Scripts\python.exe tests\transition_visual_check.py
# 期望 EXIT=0，HUD 无方块，帧时间正常（非 1fps）
```

## 改动文件

- `rm_client/ui/polar_app.py` — ROI TargetHUD + hotspot snapshot；EliminationFX 改走动态层；GUI 打开时清 target 层；字库纹理状态恢复  
- `rm_client/ui/gpu_frame_compositor.py` — `upload_target_region`  

## 后续修复（同分支）

| 问题 | 原因 | 处理 |
|------|------|------|
| EliminationFX 动画僵死 | 画在静态 overlay，只随 `static_key` 刷新 | 改到 `paint_hud_motion_overlay` 每帧画 |
| ClickGUI 字被盖住/发糊 | `targetTex` 合成在最上层，环盖在面板上；atlas 纹理 unit 可能被污染 | GUI 打开时 clear target 层；render 前 `_restore_qt_texture_state`；atlas 失败重试一次 |
