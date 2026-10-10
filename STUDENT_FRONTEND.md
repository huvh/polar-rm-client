# 学生客户端功能的 Minecraft / Jello 前端

本轮只增加展示与本地草稿；不修改任何后端、协议、安全门或固件。
现有 Jello 字体、八方向阴影与 450/125ms 时间线直接复用。液态玻璃
材质和 shader 未修改。便携发布物需从新提交重新构建，旧 exe 不包含本轮新增 UI。

## 入口与官方描述对齐

| 功能 / ClickGUI mod | 入口与显示 | 本地学生语言包依据 |
|---|---|---|
| InjuryStatistics | 按住 `~`，松开收起；屏幕上方原版 Tab 列表式伤害累计快照，不是 Jello 设置卡片 | BattlePanel_InjuryStatistics / CollapsePanel |
| MatchSettlement | 设置中 Open Settlement；比赛 MATCH→SETTLEMENT 自动展开 Jello 结算，冻结当时快照 | SettlementPanel_BaseHP / RobotHP / Kills / HurtHP / EnergyMechanism / NumberOfArmorBreak |
| ReloadingPanel | `O` / `I`；已有买弹工作区右侧展开补弹/换弹，沿用原滚动视口 | ReloadingPanel_LeftGate / RightGate / VirtualTotal / PhysicalTotal / NoAtSupplierZone |
| DartPanel | 设置中 Open Dart Panel；飞镖档 `F` 可打开；目标、闸门、初速度、发射数、冷却、检测模块；面板内 `J/F/L` 只编辑草稿 | DartsPanel_CurrentTarget / OpenDartGate / DartInitialSpeed / NumberDartFired / LaunchingStationCooling |
| SkillConfiguration | 独立 mod；已同步性能与本地草稿分列；也可从背包工作台打开 | PointPanel_AssignablePoints / TabPanel_SkillConfig |
| MinecraftInventory | MC 战斗预设中 `E`，原版背包资源；按分类分页；拖拽模块到下方九格，右键槽位清空 | 本地 MC survival inventory，2×2 工作台映射技能配置 |
| RuneRingStatus | 现有灵动岛空闲时显示平均环数/灯臂数；乘积标为「推算总环」 | Rune_RuneRingNumberTip / Rune_RuneBuffTip2026 |
| 买活 / 免费复活 | 原经济复活页 `[F1]` / `[Y]` 选择；仍需原长按确认，不由快捷键发送 | Message_BuyRevive / FreeRevive |
| 判罚与击杀播报 | 左下 MC 彩色聊天行；官方击杀同时保留现有 GD656 动画；首血需要观测到赛前→MATCH，连杀按时间窗推导 | Message_YellowCard / GraveBreach / GetFirstBlood / DoubleKill…WipedOut |
| ResourceIsland / GainZone / UWBStatus / ArmorStatus / WirelessCharging | 五个独立 mod；UWB/装甲读取已有模块状态，其余缺数据则显示等待，不假在线 | Device_ResourceIsland / GainZone / Module_UWB / Module_Armor / Message_WireLessCharge |
| MinecraftBuffs | MC 预设中本机有效 buff 的原创方块图标、等级、剩余秒数；替代旧本机 buff 标签，不隐藏全局机制提示 | 官方 Buff / 增益描述 |

背包拖放只改变 `MinecraftCombatHUD.Slot 1–9`，不启用模块。数字键选择槽位。
退出 MC 预设后原 HUD 排布/模块设置不变，常规外挂覆盖层仍由各自开关控制。
MC GUI Scale / Scale Multiplier 沿用已有设置，不影响外挂层倍率。

## 参考和数据边界

- 读取了用户提供的 `RoboMasterClient 12.0.0.30_3v3_Student.7z` 内的
  `StreamingAssets/Config/Language/RMLanguagePack2020.json`（936 keys，GB18030）。
  Engine zip 的 zh.csv 仅为引擎提示，不能替代学生端描述；旧 BuffAttrs 不作为当前规则。
- MC 背包来自本机 1.21.11 Fabric JAR。图标是项目原创。
- 栏位配置交互参考 [Hypixel Bed Wars 1.4 的 hotbar 管理说明](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/)。
- 受伤害报告按 killer 缓存，但字段是累计值，绝不能相加。前端观察报告替换并
  用现有 17/42mm 累计字段识别最新快照；无顺序可用的歧义批次显示未知。
- 当前协议只给能量机关平均环数/灯臂数，不假装有权威总环数。
- 缺失详细结算、实体弹库、性能点、技能、资源岛等数据时显示 `—` / 等待官方状态。
  `RobotState.student_ui_data` 是后续展示适配接口，不是控制开关。补给区位置不使用
  模拟器的 `in_supply_zone=True` 冒充真实区位。
- 闸口、加弹数量、飞镖和技能点按钮仅保存本地草稿；没有 publisher 调用。
  已有买弹/复活功能沿用原请求和确认链路，不在本轮重新接后端。
- 裁判播报消费现有下行状态/事件。**官方自由文字聊天尚无已确认协议**，输入栏
  和自己发送的消息始终标 `[本地]`；未添加不存在的 MQTT 话题或伪造官方连接。
- 不从语言包硬编码「四张黄牌罚下」等比赛阈值；只显示收到的判罚类型/累计数。
- 不推导未收到的 rune buff、双倍易伤或无线充电状态。队伍自定义/视觉击杀不能
  制造官方首血或连杀播报；未知击杀者不计连杀。

## 回归检查

```powershell
.\.venv\Scripts\python.exe tests/student_frontend_test.py
# 真实 OpenGL（不可使用 offscreen）
.\.venv\Scripts\python.exe tools/student_frontend_visual_check.py
```

新面板单张 DPR 图缓存、动画阶段只合成，不逐帧栅格化文字。
验收包括四分辨率、四 DPR/MC 倍率、拖放不启用/不发送、模态输入隔离、
100 次背包开合不重建缓存、100 次真实 GL 经济恢复。合成器截图只作前端验证，
不构成真车资格证据，不宣称正式比赛 READY 或真实视频 70–90 FPS。

API 冻结基线仅补充新增的 15 个前端成员；旧成员、签名、类型和模块符号经
差分确认没有漂移，未重新采集覆盖整个基线。

本机验证：30 套 Python 测试均通过；前端测试最终 90 项检查通过。
真实 Windows OpenGL 完成 26 张合成器截图（四分辨率的五种面板及 HUD、
已有经济页与 100 次恢复后的 HUD）。四 DPR 的字体/命中检查在离屏测试中完成，
不等同于四台不同 DPI 显示器的现场验收。

## Minecraft 视觉修订

- 右侧参考用户提供的 Hypixel SkyBlock / Bed Wars 截图：金色居中标题、灰色
  日期/阶段、分组空行、左对齐的彩色队伍/数值、黄色项目页脚。完整机器人名册
  不再塞进侧栏。没有照抄 Hypixel 网站地址，也没有造装饰性的比分或网络 ping。
- `~` 保留原入口；只是采用 MC Tab 的像素文字、半透明条目、右侧积分列和
  顶部/底部说明。Tab 键仍保持原有战术地图绑定。列表显示时暂时让开居中的
  灵动岛/TargetHUD，松开后恢复；不修改模块开关或液态玻璃材质。
- 背包人物预览已完全删除，不再显示 Steve、机甲立绘或 YSM 角色。
  保留原版容器和空白人物区域；技能工作台、Mod 图标及九格拖放不变。
- Mod 物品是本项目原创 MC 像素物品，不是直接把弓/剑/珍珠全盘搬过来。
  自瞄炮塔、陀螺底盘、带抛物线的吊射炮、弹药箱、金币袋、技能法杖、
  资源浮岛等固定表达功能；同一 Mod 在背包/技能工作台/拖动/九格栏中一致。
  完整名称仍在 tooltip 中，图标上不压英文缩写。制作代码为
  `rm_client/ui/minecraft_mod_items.py`，32px 图缓存、16-grid 硬边、nearest 合成。
- MC 中文使用本机 asset index 29 的原始 Unihex 字体，英文/符号使用该版本
  bitmap provider 映射；Jello 仍使用原有 Helvetica/YaHei，普通液态玻璃 HUD 不变。
  字体授权文件随 `unifont.zip` 保存，原始资源来源和哈希见
  `assets/minecraft_hud/presentation_manifest.json`。
