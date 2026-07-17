# 阵营、战术地图与战果特效

## 阵营

`AllianceProfile -> Side` 选择本机为 `Red` 或 `Blue`。它统一用于战术地图镜像、雷达/ESP 敌我颜色、视觉击杀过滤和状态栏标识。地图始终用固定红蓝表示队伍，本机队伍会附加 `YOU`。

## 战果来源

`EliminationFX -> Evidence Mode`：

- `Auto`：官方赛事场景且击杀相关 MQTT 数据新鲜时仅认裁判事件；否则可用视觉。
- `Referee Only`：只接收官方 `Event`、单位血量归零、战亡状态和队内字节块扩展。
- `Vision Only`：只使用同济/本地识别结果（桌面联调推荐）。

### 视觉击杀如何确认

只面向**敌方**目标，且必须先有一段稳定**亮灯**历史，然后满足任一路径：

1. **灭灯类**：连续检出 `extinguish`（约 ≥3 帧且 ≥0.20s）
2. **过暗**：颜色仍可能是红/蓝，但灯条亮度相对该目标最近亮灯基线显著下降
3. **丢检**：亮灯后短时框消失（灯灭后 YOLO 常直接丢目标）→ miss-to-kill

`TongjiVisionBridge -> Vision Kill Sensitivity` 控制视觉路径：

- `Lab Responsive`：显式灭灯、相对过暗、连续新空帧都可触发，适合电脑摄像头和特效联调。
- `Balanced`：保留丢检路径，但要求目标此前稳定且不靠近画面边缘。
- `Match Reliable`：只认显式灭灯或相对亮度持续下降，不认单纯丢检。

场景默认值为实验室 `Lab Responsive`、校内模拟 `Balanced`、官方赛事 `Match Reliable`。全局曝光突变时所有视觉路径都会**暂停**而不清零已有进度；同一空检测快照不会依靠 UI 时间自动触发。遮挡且从未亮过、友军灯色、预测框不会触发。

该桌面联调功能只驱动显示、音效和 mock 云台建议，不会发送发射或真实控制指令。

左下角 `KILL VISION | …` 可查看当前判定状态（如 `LIT_TRACKED` / `MISS_TRACKED` / `VISION_CONFIRMED`）。

## GD656 资源与发布

击杀纹理和 OGG 音效位于 `assets/kill_fx/gd656/`，会被 `tools/build_release.ps1` 连同唯一启动入口 `启动.bat` 一起放入发布 ZIP。运行：

`EliminationFX -> Preset` 使用 GD656 原始 preset 结构：Scrolling、Combo、Card、Battlefield 1、Battlefield 5、字幕模式及全部 26 套 Valorant 皮肤。`Element Visibility = Preset` 严格使用上游预设元素；`Full HUD` 才额外开启击杀字幕、连杀字幕、分数和 BonusList。

特效内部不叠加 POLAR 文案或液态玻璃。`Safe Area` 只平移整个特效根节点以避开底部遥测；选择 `Original Position` 可按原始底部锚点显示。

```powershell
cd rm_custom_client
.\tools\build_release.ps1
```
