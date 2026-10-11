# 界面中文化与退出交互（#8）

## 退出选手端

在无弹窗的主 HUD 按 Esc 打开二级菜单，可返回启动页重新选择场景，或经二次确认退出客户端。已打开的输入框、背包、配置等界面优先处理 Esc。返回启动页仍经过控制锁定和按键释放流程，不切换为模拟输出，也不暂停后台遥测或安全监控。

## 关闭配置界面

Right Shift / F8 的打开、关闭行为保持不变。在默认 Jello 配置界面，鼠标左键在面板外空白处按下并原地释放关闭整个配置界面，包括已展开的模块设置。设置标题、面板内留白、按钮、滑条、下拉列表和语言切换入口都有独立命中保护。右键点空白处不关闭；从控件拖出或从空白处拖入面板不会误关闭。

关闭点击在界面内独占处理，不传给底层地图或机器人控制。点击期间通过快捷键关闭/重新打开时，旧手势被取消。

## 显示语言

简体中文作为新配置的默认显示语言，仍保留已有配置的明确英语选择。中文仅转换显示文案，不改模块键、设置键、保存的枚举值、协议标识符或日志数据。原有配置与快捷键继续兼容。

## 验证边界

`tests/test_clickgui_background_dismiss.py` 使用生产渲染命中几何与真实离屏 Qt 事件，覆盖不同窗口大小、左/右键、内部控件、跨区域拖动、滑条、设置弹层及 Right Shift/F8 反复切换。硬件控制适配器在测试中为无输出替身。此测试不代表已在实体机器人、Windows 显示器或 GPU 上完成验收。

离线聚合检查需要明确提供只读参考工程；遗漏参考路径会标记未完成，不能当成通过。当前验证环境运行命令：

```sh
QT_QPA_PLATFORM=offscreen \
XDG_CACHE_HOME=/tmp/polar-ui-device-cache \
POLAR_TEAM_CRC_REFERENCE=/workspace/shared/polar-serial-assistant-reference/lib/CRC8_CRC16.py \
POLAR_REFEREE_REFERENCE=/workspace/shared/standardrobotpp-reference \
/workspace/scratch/8fc313400f06/polar-test-venv/bin/python -u tools/verify_all.py \
  --firmware /tmp/polar-firmware-validation
```

其他环境应将上述路径替换为实际只读参考工程的位置。本次测试不会安装或修改固件。

## 第一阶段剩余清单（后续显示补丁已覆盖）

第一阶段覆盖启动选择、机器人配置、Jello 与旧版配置菜单、Esc 退出菜单、配置说明、常见提示及原生导入/资格确认对话框。后续显示补丁已按下面清单逐项补齐内置显示边界；完整范围、故意保留项与专项验证见 [显示文案覆盖清单](issue8_display_inventory.md)。以下保留第一阶段发现路径，便于审计：

- `rm_client/ui/polar/renderers/dynamic_island.py`：`Warning`、`Success`、`Client State`、`Radar` 等消息标题，以及尚未经过显示翻译的动态描述。
- `rm_client/ui/polar_app.py` 的 `draw_watermark`：`CC on/off`、`KM NO-RX/stall` 和连接状态的用户可读部分。
- `rm_client/ui/polar/renderers/tactical_map.py`：基地/前哨/敌我状态和胜利点等显示标题；注意 `ENEMY` 等也用于内部状态判断，不可整体替换源值。
- `rm_client/ui/hero_deploy.py`：英雄部署控制台仍含 `ENTER/EXIT DEPLOY`、`PREVIEW`、`ARM ASSIST`、`CLOSE`、`NO VALID BALLISTIC SOLUTION` 等专用界面文案。
- `rm_client/ui/polar/renderers/combat_target_hud.py`、`esp_wireframe.py`、`module_list.py` 及 HUD 相关绘制路径：目标/锁定/跟踪、状态及模块显示名应在绘制边界转换。

保留不翻译的内容：品牌及专名（POLAR、Jello 等）、协议/传输标识（MQTT、UDP、DT7、CC、十六进制命令）、原始诊断/日志、机器人与模块/设置 ID、动作参数、单位、自定义标签/配置名称。安全确认口令（如 `ZERO OBSERVED`、`OBSERVED ON FIXTURE`）保持原值，中文说明应明确告诉用户需输入的精确口令；不能预填或自动确认。

## 本轮最终结果

- 聚合验证：79 项，77 通过、0 失败、2 项与原基线相同的未完成检查。
- 未完成项：旧固件补丁行为测试要求安装，禁止在只读验证中执行；DT7 厂商反汇编对照缺少 Windows `dump.cs`。
- 专项：14 项配置关闭/过渡、15 项语言/原生对话框、10 项显示渲染、11 项 Esc 菜单测试通过，API 冻结面一致。
- 独立只读审查复核 28 项配置/Esc/下拉测试，无未修复的阻塞发现。
- 未进行实体机器人输出、真实 GPU 显示与 Windows 硬件验收。后续显示补丁的范围与结果见独立覆盖清单。
