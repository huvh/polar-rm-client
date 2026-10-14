# CS2 视觉 / 购买页 / 准星 / 设置中心（2026-10-14）

> 后续用户要求设置中心换回Jello：参见[Jello设置/键盘增量](JELLO_SETTINGS_KEYBOARD_20261014.md)。六页功能与CS准星分享码不变；下文CS2设置配色描述是先前版本，购买/顶栏/击杀并未随之换皮。

## 使用入口

- `Esc → 设置`：视频、音频、游戏、键盘/鼠标、准星、界面/HUD六页。模态页不暂停比赛；输入先归零并锁定，返回不恢复旧按键、不自动Arm。F12在嵌套导入/确认窗口中也有效。
- 购买页：`EconomyPanel → Shop Layout = CS2 Grid`。五列分别为弹丸、恢复、复活、支援、补给站，右侧是详细预览与原确认区。`Classic`保留旧工作区。
- 原生击杀反馈：`EliminationFX → Preset = CS2 Native`。保留其他预设与开关；不是把所有用户预设强制覆盖为CS2。
- 顶栏：`TopMatchBar → Local CS2 Assets`使用本机私人资源包；`Source Motion Preview`是已有原始动效开关，已保存的关闭选择不被覆盖。
- 准星：准星页粘贴分享码→导入→预览→应用，或`ClickGUI → Crosshair`导入动作。导入自动选择CS2样式，但不强制启用已关闭的Crosshair模块。

## 不是占位的设置

| 分页 | 实际功能 |
|---|---|
| 视频 | 窗口/无边框、窗口物理像素分辨率、HUD节奏、渲染限帧、VSync、MSAA、图传采样预算/过滤及低中高预设 |
| 音频 | 当前真实输出设备、主音量、后台静音、UI声音主题/分项音量、击杀音量、Jello列表声音 |
| 游戏 | 现有赛制、机器人配置、阵营、聊天/通知、轮盘与购买展示选项 |
| 键盘/鼠标 | 鼠标位移倍率、垂直反转、滚轮倍率；16个驾驶协议槽按键捕获/清除，模块快捷键，冲突/保留键拒绝与原子交换 |
| 准星 | 全参数编辑、不同合成背景实时预览、分享码导入导出/复制、白名单CFG及JSON文件 |
| 界面/HUD | 语言/缩放、Minecraft倍率/九格栏、ModList、顶栏、地图、目标HUD、击杀视觉及既有动画选项 |

设置值先编辑、应用后生效；搜索过滤不丢草稿，恢复当前页默认值也须再次应用。入口不暴露Mock/DT7真发/Arm等授权开关。

VSync/MSAA需要重启创建新的GL上下文。**显示器物理刷新率仍由Windows管理**，无边框使用桌面模式；HUD节奏不冒充显示器Hz。高DPI下低于现有客户端最小逻辑尺寸的物理分辨率会拒绝，已保存模式在换屏后无效则回退可用窗口，不崩启动。30FPS渲染限制不降低裁判逻辑/KMC计时器节奏。

鼠标倍率只作用于本客户端Qt位移；小倍率保留小数余量，归零时一并清除。不改NUC自瞄增益、DT7原始输入或协议位序。灵敏度数值不宣称与CS2的角度/DPI物理意义等价。

视频/音频独立原子写入`user_data/video_preferences.json`与`user_data/audio_preferences.json`；其他项目走原配置接口。

## 真正的互联网准星代码

支持传统`CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx`容器的legacy1/3/4及当前CS+44字符容器双向编解码。公开输入/预期输出来自[AkiVer主仓库测试](https://github.com/akiver/csgo-sharecode/blob/main/src/index.test.ts)与[格式说明](https://github.com/akiver/csgo-sharecode/blob/main/doc/code_layout.md)。测试重新编码字段而非简单回显原字符串；无效校验码、版本、越界参数报错，不回退默认。

尺寸/间距/粗细、中心点/T形、颜色/透明度/轮廓，以及动态、split、scope元数据均保存。所选旧格式无法表达新字段或精度时阻止导出，不能静默丢值。CFG只解析准星白名单，不执行控制台脚本；文件读取限64KiB。

**互通代码不等于CS2引擎互通**：RM没有CS武器散布、后坐力、开镜等遥测，这些字段完整保留但不模拟；圆环/quad及尺寸是Qt静态近似。预览背景明确标注合成，不伪装真实CS截图。导出禁止写入已识别的CS安装目录。

## 本机素材与只读边界

- 安装目录只以`rb`读取选定VPK/font，CRC验证后复制到安装目录之外再运行Source2Viewer。没有启动CS2、注入/hook、读取进程内存或修改CS配置。
- 私人激活包为`user_data/cs2_ui_pack`，manifest声明34项，涵盖Stratum2 Regular/Bold/Condensed/Mono/BoldTF、顶栏点纹/人数/骷髅、五张击杀卡与mask、购买分类图形及五个音效。
- manifest记录实际读取的18个源文件前后SHA-256，全部相等；设置布局另外保留只读核验。运行时不读Steam、解包、下载或生成进程。
- 声音按本机`game_sounds_ui`事件表核对：KillCard.1=`kill_doof_01`（0.6），购买=`radial_menu_buy_03`（0.3），拒绝=`weapon_cant_buy`（0.4），选择=`inventory_item_select_01`（0.5），悬停=`itemtile_rollover_09`（0.3）。没有把商城购买声音误当局内买枪。
- 提取工具：`tools/import_cs2_ui_pack.py`，显式指定游戏目录、工具、全新工作/输出目录。私人素材来自Valve，不因Source2Viewer为MIT就变成开源资源；`user_data/`已被Git/发布排除。可公开源码只包含独立实现与原创回退SVG。
- 未承诺第三方软件或反作弊系统绝对保证；这里的证据仅是无游戏写入/无进程接入的边界。

## 动效与材质

顶栏小骷髅300ms ease-out，击杀卡重排200ms ease-in-out、亮度/spotlight700ms，购买悬停200ms与成功闪亮500ms，参数取本机CSS。购买根场景仍用原AndroidControlCenterSpring、下拉与液态玻璃，不换成黑色CS背景。

商品仍为真实RM EconomyOffer，不引入CS枪械价格、虚假的回合买枪倒计时/下回合最低金额。供给字段缺失显示未知。选择不发送交易；只有现有确认动作发送，成功闪亮只认既有交易终态，pending/timeout不伪造成功。

所有子内容使用共同根裁剪和同一热点变换。数字遥测用驻留字形，避免每次金额变化重传整行纹理。阴影/图片/字体启动预热，不在动效中解包。

液态玻璃合成器全部5段GLSL与HEAD逐字相同，材质测试保持原参数。QPainter FBO使用CombinedDepthStencil是曲线裁剪修复，不是更换折射/模糊shader。

## 验证与限制

- unittest最终全量：488项，486通过、2项按环境跳过（日志`tmp_cs2_delivery_tests.log`）。72个smoke函数完成，backend protocol 198 checks通过；API冻结1161成员一致，未刷新基线。
- 准星22项、设置中心12项含实际Qt模态/嵌套F12、真实公开分享码、原子交换/非法输入无部分修改；购买矩阵覆盖1280×720、1600×900、1920×1080、2560×1440。可视设置页检查四尺寸与DPR 1/1.25/1.5/2。低分辨率准星页自动堆叠、滚动与裁切。
- 真实桌面GL，2560×1392、DPR1、NVIDIA RTX5070Ti Laptop/596.21、75Hz显示器：购买页8秒窗口平均约75.0FPS，paint P95 5.48ms；100次**快速反向**后纹理29/24/20不增长，场景关闭且无GL错误。这不是100次完整450ms收拢/展开长时测试。
- 摄像头+本地OpenVINO GPU.0推理8秒窗口：HUD平均约74.5FPS，paint P95 12.21ms，present间隔P95 21.89ms；推理约56.7FPS。达到本机平均70–90范围，但未达到paint P95<11.1ms理想目标，也不能称所有帧无抖动。
- 击杀实际GL显示与时间线经过检查；一次短测记录到307ms tick离群点，第二次诊断未复现（tick max2.90ms，触发逻辑总耗时很小），不能据此抹去离群点或宣称严格时限验收已完成。
- 所有性能探针用隔离配置，真实车辆输出关闭。没有长时整场/现场裁判/真车证据，结论仍是**NOT READY FOR REAL MATCH**。

本轮未写指定默认配置，未改backend协议，未切分支、提交或推送。
