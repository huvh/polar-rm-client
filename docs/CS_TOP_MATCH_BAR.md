# CS / RMUC 顶部战况与 BF6 进度集成

## 当前实现

本分支基于安全修复 `3bf4091772a14ac309326f1e058bf6080eb3f5ec`，将 CS 顶部布局真正接入现有 `RMUC7v7` HUD。使用本仓库的 2026 角色与 `rm2026-v1.3.1` 协议，未把 2027 预览协议套进现行字段。

- `TopMatchBar` 现在默认开启、无快捷键，默认 `Match Scope = RMUC Only`。RMUL3v3保留原header和VP显示；如显式选择All Match Modes才在3v3启用CS行。保留已保存的关闭选择；关闭后恢复原 MatchTimer header / EliminationFX 进度路径。
- 默认 `Match Roles`：每边六个车辆槽为英雄1、工程2、步兵3/4、空中6、哨兵7。蓝方编号加100。飞镖8、雷达9单独显示在下方系统行，不算车辆或地面存活数。
- 赛制仍叫 `RMUC7v7`，不强凑七个车辆头像，也不把八种操作配置当八台存活车。候选阵容并非本场实际报名或上场证明；自定义 `configure_rosters` 仍可覆盖具体参赛名单。
- 存活数只统计有HP的地面角色。空中显示 `NO HP`，没有观察到有效状态就保持未知。系统没有可靠观测时显示 `—`，不假造在线。
- 当前HP来自裁判 `GlobalUnitStatus.robot_health`（己方1/2/3/4/7，再敌方1/2/3/4/7）；有效本机 `RobotDynamicStatus.current_health` 优先于仍可能滞后的全队快照。
- 本机实际收到 `RobotStaticStatus.max_health` 才画比例血条。其他车只有当前HP时显示 `HP n / ?`；不借用600默认值、角色默认配置或我方同类车的分母。过期、无效、0分母、当前HP超分母均不画假比例。
- 新回合、赛制、身份、协议、场景、连接代际变化重置投影；快速断开重连不能复活旧HP。每个字段独立2.5秒过期，不靠其他新包续命。身份ID与阵营配置矛盾时保持未知，避免敌我错配。
- 时间取实际 GameStatus，比分默认明确标 `RM SCORE`；无数据为占位。可关闭比分或选择Unavailable。未接没有稳定事件ID的视觉/累计击杀，所以真实比赛下骷髅保持空白，绝不拿HP归零推断击杀归属。

### 2026 阵容依据

本轮读取官方规则PDF表3-1（印刷页22）：英雄1×1、工程2×1、步兵3/4×2、空中6×1、哨兵7×1、飞镖8×1、雷达9×1；首局最低阵容是除雷达/飞镖外至少4台机器人。角色对应现有 `robot_profiles.py`，不是新造角色库。

官方规则入口：[RoboMaster 高校对抗赛规则](https://bbs.robomaster.com/wiki/20204847/809871)。临时PDF在封面截图保全前已不可用，因此本文不把未核对的封面版本号写成事实；阵容表和基地5000HP正文已在本轮实际读取。协议字段依据仓库内哈希固定的2026 V1.3.1合同与状态适配器。

### BF6 进度保留的准确含义

使用既有 `kill_fx.py:MatchProgressRenderer`，保留双色细条、数字滚动、推进阻尼、`BASE RACE` 标签。它是基地损失比例 `1 - currentHP / 5000`：左边为己方基地已损失比例，右边为敌方基地已损失比例；数字取真实阵营比分。原注释曾把左条称为“己方攻击敌基地进度”，与原实际代码相反，本次仅纠正注释，未反转数据。

5000是本轮读取的2026规则基地初始/上限容量，不是当前HP默认值。新接线只喂实际收到、有效且未过期的基地HP；没有数据时空轨加点线表示未知，比分为 `—`，不会先画满血或0分。新行独立于击杀预设，其他BF6图标、音效、击杀/命中效果不变。RMUL不套基地进度，其原胜利点显示仍是另一种指标。

顶部模块负责绘制时，原EliminationFX调度仅屏蔽重复的 `match_progress` 元素，其余元素不受影响。`BF6 Progress` 可单独关闭；整体TopMatchBar关闭后原路径恢复。没有控制、瞄准、发射或MQTT发送逻辑变化。

### 布局与开关

- 顶部仍保留原 Dynamic Island，CS行放其当前底边之后；BF6置于车辆/系统行下。对岛展开施加安全下界，不让BF6缓动穿过头像。
- 左侧读取真实地图当前矩形，右侧按实际独立面板固定边界留HUD栏（不依赖Module List总开关），左侧裸文字列表也单独避让；使用对称安全走廊保持计时和BF6中线对齐窗口中心。地图展开到空间不足时同时隐藏新条，不把旧条重复画回。
- 启动、Minecraft整套HUD、菜单/经济/学生面板、Hero部署和模态界面不叠加新条。直接复用现有高刷新HUD绘制，不新建窗口、定时器、输入或焦点。
- `Show Health`、`Show Scores`（同时控制CS与BF6比分）、`Show Kills`、`BF6 Progress` 均可调；`Source Motion Preview` 仍默认关闭，独立原版参数复现的边界见下文。
- 原创QPainter机器人头像、带明确角色/ID。不是Valve素材或真实机器人照片；字体也不是Valve原字体。

## 文件与验证

- 数据：`rm_client/top_match_bar.py`，权威字段/独立过期/名单/HP/纯布局。
- 画图：`rm_client/ui/top_match_bar.py`、`top_match_bar_controller.py`；BF6真实原画图类仍在 `kill_fx.py`。
- 最小主窗/队列接入：`polar_app.py`、`backend/manager.py`；旧BF6去重在 `ui/polar/mixins/video_backend_mixin.py`。
- `tools/render_rm_top_hud.py`：2026六车辆+系统+BF6组合预览，包括完整、部分缺失、断流；1920×1080与1280×720。所有遥测明确为合成，地图/岛/右栏明确为布局夹具。
- `tools/topbar_preview_support.py`：离线直接加载生产MatchProgressRenderer、DigitalScroll的AST定义。不存在另写一套BF6绘制的假预览，也不导入客户端/音频/后端。

已通过110项顶部模型、来源参数、真实Qt5 QPainter、假宿主接入和BF6生产方法测试（原81项基础上新增29项）。新增覆盖六车辆/两系统、地面存活计数、真实最大HP权限与过期、局部/缺失HP、断流/快速重连、静态状态与数值冲突、岛展开/地图避让、1280/1920/2560布局、用户持久关闭选择、实际EliminationFX调度去重。88项原安全修复回归仍通过（build22、UI/state30、transport36）。

```sh
TOP_MATCH_BAR_QT5_PREVIEW=1 /usr/bin/python3 -m unittest discover -s tests -p 'top_match_bar*test.py' -v
/usr/bin/python3 tools/render_rm_top_hud.py --qt5-compat-preview --output tmp_rm_top_hud
python tests/test_build_safety_regressions.py
python tests/test_ui_state_regressions.py
python tests/test_transport_safety_regressions.py
python tests/polar_link_test.py
python tests/polar_spec_test.py
python tests/polar_bridge_test.py
python tools/module_backend_map.py
```

预览是Qt5兼容离屏组件真实栅格输出。未启动完整应用、摄像头、MQTT、串口、真实机器人或OpenGL窗口；未运行真实GUI的api_freeze/verify_all。PySide6/Qt6、完整GPU呈现、实际DPR/字体、真实裁判数据与硬件仍须在依赖齐备的获准环境验收。它不是整应用截图或真车可用证明。

## 上一轮CS来源研究（保留作为视觉证据）

## 参考材料与实际核验范围（2026-10-10 UTC）

### 用户图片

用户提供的顶部裁剪图是主要像素几何依据，已实际看图。不把该图嵌入成客户端素材。

### 开源代码：实际阅读

1. [Lexogrine CS2 React HUD / MatchBar](https://github.com/lexogrine/cs2-react-hud/tree/main/src/HUD/MatchBar)
   - 已读 `MatchBar.tsx`、`matchbar.scss`、`Players/Avatar.tsx`，包括独立计时、两侧分数、头像与骷髅条件显示。
   - [MIT，Copyright (c) 2021 Lexogrine](https://github.com/lexogrine/cs2-react-hud/blob/main/LICENSE)。这里只作架构参考，未移植 TS/CSS、图标或字体。
2. [M3MONs/CS2-HUD](https://github.com/M3MONs/CS2-HUD)
   - 已读 README 与 [MIT 许可](https://github.com/M3MONs/CS2-HUD/blob/main/LICENSE)，作者 Alan Skrzypczak，2026。
   - 已下载并实际打开作者 README 所链的 [真实游戏 HUD 展示图](https://github.com/user-attachments/assets/b3a823e2-80db-4188-a864-c2ada12013d9)。它是自定义赛事 HUD，不能当作原版顶部栏的精确模板。
3. [drweissbrot/cs-hud](https://github.com/drweissbrot/cs-hud)
   - 已读项目页面，确认其为 Custom Counter-Strike Spectator HUD，页面标示 ISC 许可。未运行、不引入代码或素材。

这些项目均是第三方观战/直播 HUD，**未发现可直接原样移植的 Valve 原版顶部组件**。本实现是独立 Python/QPainter 代码，不把上述项目的开源许可证外推到 Valve 或任意玩家头像。

### 原版样式与版本核查：新增证据

- [SteamTracking 固定快照 hudteamcounter.css](https://github.com/SteamTracking/GameTracking-CS2/blob/f68ba6aa2473367589e7cb249fc38814c9b90ff0/game/csgo/pak01_dir/panorama/styles/hud/hudteamcounter.css)。下载的原文与该固定 hash 版本一致，本地 SHA-256：`efeb9a14e732167f5c2cdb1262cb02c72823ff275696bd1c84760afdaf12db19`。
- XML 对应层级为 AvatarLargeSnippet → Visible → AvatarL__ImageBG → AvatarImage。`.dead` 规则本身没有声明 opacity 过渡，不能把 AvatarLargeSnippet 的 transform 0.1s 当作死亡淡出；不同父层 opacity 过渡用于整个 HUD/人数模式切换。
- 已读的样式明确给出小骷髅 on-kill 0.3s、ease-out、scale 1.2；使用 [W3C ease-out 定义](https://www.w3.org/TR/css-easing-1/#valdef-cubic-bezier-easing-function-ease-out) 的 cubic-bezier(0,0,.58,1) 实现来源参数预览。
- [Valve CS2 bug tracker #3483](https://github.com/ValveSoftware/csgo-osx-linux/issues/3483) 的 2023-10-13 更新后截图已经具有参考图的“计时在上、比分在中、人形存活数在下”结构；黑点中柱与原版 equipmentinfo 样式相符。这支持“CS2 原版同类 HUD”判断，不能由一张裁剪图断言其具体游戏 build、缩放、字体设置或模组状态。
- GameTracking 是原版资源研究资料，不因公开托管就把 Valve 纹理/字体当作开源许可资产。项目没有带入 CSS、XML、原版图标、纹理或字体，仅独立实现可描述的布局和数值行为。

### 视频与实录：已核实局部连续事件，完整验收仍有缺口

- [1280×720、24fps 实际 CS2 局内片段](https://github.com/karminski/deepseek-v4-flash-vision-exp-video-input-best-practice/blob/main/cs2-gaming-test-match-4-720p-seg-1.mp4)：研究中已取得、解码并逐帧查看，共 652 帧、27.166667s。0/3/6/9/12/15/18/21 秒的计时分别为 1:57/1:54/1:51/1:48/1:45/1:42/1:39/1:36，支持正常播放速度。七次死亡保留原槽位，头像与边框一同淡化。f62 首杀骷髅出现，f63 对应死亡与人数变化；末尾 f589（24.541667s）比分 2:1、计时 1:32，f590（24.583333s）比分 3:1 且计时清空，f591（24.625s）最后一名 T 灰化、存活人数 1→0。这证明需要按实际事件驱动各展示字段，不能用单个血量归零事件伪造比分或击杀归属。
- [Medal《Smooth Pistol 4K》](https://medal.tv/games/counter-strike-2/clips/1SJGmHcvDJCFMi)，作者 Migi，页面日期 2024-02-01：浏览器已实际解码并观看 1080p、15.466666s 的同类人数顶部条。媒体保存取消，没有本地逐帧样本，因此只作观看互证，不声称有帧号/FPS 结论。
- 早先检索的 [YouTube 完整局](https://www.youtube.com/watch?v=iDSSUA5X4nI) 曾遇到 0×0/零缓冲播放器，未把该次观看算成功；[Dailymotion 条目](https://www.dailymotion.com/video/xa3krb4) 未播放成功；[Valve 官方演示](https://www.counter-strike.net/cs2) 的 UI.webm 主要展示下方击杀卡，不能用于顶部逐帧验收。

现有实录缺少可确认的游戏 build/HUD scale，也没有覆盖复活、完整回合切换和所有头像移动模式。24fps 样本不足以精确拟合 300ms 曲线。可以说已完成局部死亡/击杀/比分事件研究，**不能说完整动态一比一验收完成**。可选动效仍默认关闭。源站或仓库的代码许可证不能外推到游戏视频版权；客户端不附带整段录像或原版字体/纹理。

