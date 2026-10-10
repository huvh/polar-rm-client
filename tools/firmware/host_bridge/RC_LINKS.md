# 进 rc_ctrl 的四条链路（一页速查）

> **结论先说（比赛用哪条）**
> 比赛时人是拿 **USB 线把电脑接到 DT7 遥控器**上，DT7 通过 2.4G 发给车上的
> **DR16 接收机**，接收机出 **18 字节标准 SBUS** 进 C 板 UART3 —— 这条链路里
> **键位和鼠标都是原生的**：驾驶员的摇杆、两个三段拨杆、16 个键盘位、鼠标位移与左右键
>全在这一条链路里，一个字节都不需要电脑帮忙。
> 客户端是**第二条入口**：USB 线插 C 板的 Type-C 虚拟串口，发 0x5A 帧。
> 两者不相干，也互不借用：它们的会合点发生在**单片机内部**的 `rc_ctrl`，
> 方式是"各记一本账，谁写都把两本账的并集写回去"（见 §3）。
>
> 所有行号基于 `tmp_polarbear/StandardRobotpp` **打完英雄桥之后**的树
> （`python tools/firmware/prepare_hero_build.py <树>` 产出的状态）。

## 1. 四条链路对照

| | ① USB 0x5A（客户端） | ② DT7 18 字节帧（**比赛主链路**） | ③ 25 字节纯通道 SBUS（ET08A/AT9S/HT8A） | ④ 板间 UART2 / CAN |
|---|---|---|---|---|
| 物理 | 电脑 →USB线→ C 板 Type-C（虚拟串口） | 电脑/手 →DT7→ 2.4G → DR16 → C 板 UART3（DMA+IDLE 中断） | 同②，但换的是别家遥控器与接收机 | 别的板 →USART1（板上丝印写 Uart2）／CAN |
| 帧长 | `0x5A`+id+len+payload+CRC16 | **18 字节**（`RC_FRAME_LENGTH`，`remote_control.h:46`） | **25 字节**（`SBUS_RC_FRAME_LENGTH`，`:47`） | `0xA5` SOF，只搬 Test/Rc/Gimbal 三种包 |
| 入口 | `usb_task.c` 收 id=0x03 虚拟遥控器 | `remote_control.c:570` 与 `:623`（帧长 ==18 就交给 `:681 sbus_to_rc()`） | `remote_control.c:582` 与 `:635`（帧长 ==25）→ `Et08aSbusToRc()` 等，函数体 `:763-861` | `communication.c:221-237`（UART2）／`CAN_receive.c:228-268`（CAN） |
| 怎么写 `key.v` | `UsbMergeVirtualRcKeys()`：`HOST_RC_HOST_KEYS = drive_keys;` 然后写并集（`usb_task.c`） | `HOST_RC_DRIVER_KEYS = key.v;` 然后写并集（`remote_control.c:706-707`） | 无键位字段 → 置零宏里 `HOST_RC_DRIVER_KEYS = 0;` | **整份 `RC_ctrl_t` memcpy 覆盖** |
| 生效条件 | 客户端三条开关：RobotLink enabled + Allow Drive + Client Chassis Drive，且 Drive Channel=`virtual_rc`；硬件侧只放行 `VRC_DRIVE_KEY_MASK`（W/S/A/D/SHIFT） | **没有编译期前提**：18 字节 DBUS 无条件解（`remote_control.c:570/623`）。`__RC_TYPE`（现值 `RC_DT7`，`robot_param.h:30`）只管 25 字节那三家第三方接收机 | 编译期 `__RC_TYPE` 选中对应解码器 | `__CONTROL_LINK_RC == CL_RC_UART2 / CL_RC_CAN`；当前 `CL_RC_DIRECT`（`robot_param.h:59`）**这段不参与** |
| 超时 | 150ms 没收到 0x03 → 客户端那份账归零（`VRC_FRESH_TIMEOUT_MS`） | 100ms 没帧 → `receive_count` 断；`GetRcOffline()` 只看"有没有连续收到" | 连续 10 次 `connect_flag` 变化判失联 → `slove_RC_lost()` 重启 DMA | 上层用 `LastReceiveTime.Data_Rc` 判 |
| 语义 | **叠加**，随时可撤 | **叠加**（打桥之后不再是覆盖） | **叠加**（驾驶员侧恒 0） | **覆盖**，会把①②③的结果一起冲掉 —— 与客户端驾驶**不可混用** |

## 2. `__RC_TYPE` 到底管什么（2026-09-03 逐行核过，纠正一版夸大表述）

上游出厂写 `RC_ET08A`，本脚本默认改成 `RC_DT7`。**但要知道它真正管什么**：

| 说法 | 判定 | 依据 |
|---|---|---|
| "DT7 硬件配 et08a，驾驶员键位/鼠标就丢了" | **错** | `remote_control.c:253`（干净树 252）是按**帧长**分派：18 字节无条件进 `sbus_to_rc()`，键位 bytes14-15、鼠标 bytes6-13 照解，中值用 DT7 自己的 `RC_CH_VALUE_OFFSET=1024`。**你们以前用 DT7 键鼠开车能开，这条从来没坏过。** |
| "配错就摇杆中值偏移、车自己漂" | **错（对 DT7 车不成立）** | 那几家中值只在**25 字节解码器**里用到；DT7 帧走的是 `sbus_to_rc()`，与 `__RC_TYPE` 无关 |
| "配错就车判离线、底盘锁死、警报曲一直响" | **半对，但被说重了** | `GetRcOffline()` 确实恒真（`:577` 非 DT7 分支要看初值即超限、又只有 25 字节路径更新的 `sbus_lost_count`）；可它的下游只有：板间广播 `rc_offline=1`（`communication.c:186`、`CAN_communication.c:75`）、**平衡底盘**置 `DBUS_ERROR_OFFSET`（`chassis_balance.c:272`）。麦轮/全向轮这里走 `chassis_task.c:98` 的 `__weak` 空实现，**不影响本车运动**；离线警报曲默认关（`music_task.c:38` `ENABLE_ALARM_RC_OFFLINE=false`） |
| "车上是 25 字节遥控器时，`__RC_TYPE` 必须选对那一家" | **对，而且这才是致命的** | `remote_control.c:264-280` 的 `#if` 链选不中 -> 那一帧**一个字段都不解**，摇杆键位全丢，车完全不动 |

所以切 DT7 的意义是：① 让 `GetRcOffline()` 与板间广播恢复正确语义（别的板、换平衡底盘时不会拿到一个恒 1 的离线标志）；② 让配置说实话。
**"客户端也能叠在驾驶员上面开车"这件事不靠这个宏**，靠的是 §3 的键位记账合并 —— DT7 的 `key.v` 是整字段覆盖，旧的 `|=` 写法在 DT7 车上每帧都被抹掉，那才是客户端控不了车的真正原因。

切换（原始值记在行尾注释里，可反复来回切）：

```
python tools/firmware/prepare_hero_build.py <固件树> --rc dt7      # 默认，对应 DT7/DR16
python tools/firmware/prepare_hero_build.py <固件树> --rc et08a    # 车上换成 ET08A 时用
```

dt7 与 et08a 两种取值都用 ARMCC 5.06 全量编过：162 个编译单元 0 error 0 warning。


## 3. 键位账本：三个写入者，一本账一个（本次适配的核心）

`rc_ctrl.key.v` 潜在有三个写入者。历史上它们互相打架，症状恰好相反：

* 非 DT7 解码器不写 `key.v`，而客户端用 `rc_ctrl.key.v |= drive_keys`（只置位
  不清位）⇒ **客户端一松键，那几位永远留着，车刹不住**。当年是靠
  `SPECIAL_CHANNEL_SET_SERO()` 每帧 `key.v = 0` 掩盖，可那样又和 `|=` 形成
  merge-vs-clear 竞态（车速按帧率抖动）。
* DT7 解码是 `key.v = sbus_buf[14] | (sbus_buf[15] << 8)`，**整字段覆盖**
  ⇒ 客户端注入的键位下一帧就被抹掉；而 `chassis_mecanum.c:216` 的 SHIFT 是
  边沿检测，抹一下补一下 ⇒ 小陀螺开关自己乱跳。

统一做法（`host_chassis_bridge.h`）：

```c
#define HOST_RC_DRIVE_KEY_MASK ((uint16_t)0x001F)      /* W S A D SHIFT */
extern volatile uint16_t HOST_RC_DRIVER_KEYS;         /* SBUS 解码写 */
extern volatile uint16_t HOST_RC_HOST_KEYS;           /* usb_task 写 */
#define HOST_RC_MERGED_KEYS()  (HOST_RC_DRIVER_KEYS | HOST_RC_HOST_KEYS)
```

两个写入者都只通过 `HOST_RC_MERGED_KEYS()` 往 `key.v` 写最终值：

| 位置 | 动作 |
|---|---|
| `remote_control.c` `sbus_to_rc()`（DT7 18B） | 记 `HOST_RC_DRIVER_KEYS = 原始解出的键位`，再写并集 |
| `remote_control.c` `SPECIAL_CHANNEL_SET_SERO()`（25B 那三家） | 记 `HOST_RC_DRIVER_KEYS = 0`（这类遥控器没有键盘） |
| `usb_task.c` `UsbMergeVirtualRcKeys()`（1ms 主循环） | 记 `HOST_RC_HOST_KEYS = 0x03 键位 & 0x1F`（含 150ms 新鲜度门控），再写并集 |

由此得到两条**必须成立**的不变量，都由可执行测试守着
（`tools/firmware/host_bridge/test_rc_key_ledger.py`，8 组断言 + `--negative` 阴性对照）：

* 驾驶员与客户端的键位**并存**：谁按谁动，两边都松才停；
* 任何一侧撤出（松键 / 掉线 / 换遥控器）后，`key.v` **一定会回落**，不会粘住。

`Q`(摩擦轮开)、`E`(摩擦轮关)、`F`(sc_flag) 在掩码之外：开火相关的动作
永远只能由遥控器触发，客户端碰不到。

## 4. DT7 18 字节帧的字节布局（`sbus_to_rc()`，`:370-389`）

```
0-5    通道 0..3（11bit 打包）+ 两个拨杆（byte5 的 bit4-5=s[0] 右, bit6-7=s[1] 左）
6-9    鼠标 X / Y（int16 增量）      10-11 滚轮      12 左键      13 右键
14-15  键盘位图（就是 key.v）        16-17 通道 4（左滚轮）
```

`s[0]` 是**右拨杆**（`remote_control.c:599/604` 注释：ch 0-右平 1-右竖 2-左平
3-左竖 4-左滚轮；sw 0-右 1-左），取值 `RC_SW_UP=1 / RC_SW_DOWN=2 / RC_SW_MID=3`
（`remote_control.h:87-89`）。麦轮英雄 `chassis_mecanum.c`：

* **下方** `switch_is_down` → `CHASSIS_LOCK`（`:97`）：**不读驾驶键位**，
  这时"客户端没反应"其实是拨杆在下方；
* **中间** → 正常驾驶，小陀螺看 `spin_flag`（`:101`）—— **要验客户端驾驶与小陀螺必须拨中间**；
* **上方** → 固件无条件强制常转（`:113`），客户端的小陀螺开关此时看着"无效"。

全向底盘同构（`chassis_omni.c:101 / :105`，上方是 `CHASSIS_FOLLOW`，不冲突）。

## 5. 官方"客户端→机器人控制指令"链路（0x0304）：现状是死的

* `application/referee/protocol.h:46` 定义了 `ROBOT_COMMAND_CMD_ID = 0x0304`；
* `referee.c:238-241` 整个 `case ROBOT_COMMAND_CMD_ID` **被注释**，`:98` 的 memset 也被注释；
* 全仓库 `robot_command_t` 除注释外**没有任何消费者** —— 就算把解析打开，还得再写一层
  "0x0304 → rc_ctrl / 底盘云台指令"的下游映射才有人开车；
* 相邻的 `0x0302 自定义控制器`同样只进内存：`referee.c:230-231` 收下，
  往上位机转发的代码在 `usb_task.c` 里全是注释。

⇒ **本节结论已在 2026-09-04 被官方文档更新（重要）**：
> 大疆《RM2026 通信协议》V1.3.0（2026.03.26）修改日志明确写着
> **"删除命令码 0x0304"**，第 3 条把原 `RemoteControl` 拆成
> `KeyboardMouseControl`（75Hz）与 `CustomControl`（≤30B，75Hz），方向都是
> **自定义客户端 → 图传链路 → 机器人**。所以"补 0x0304 解析"这个目标已经作废——
> 新赛季的裁判系统根本不会再发这个包，补回来也收不到。
>
> 2026 赛季真正的活通道是 **0x0311**（30 字节，75Hz 上限，图传链路），
> 而队内固件**已经在收已经在存**：`referee.c:247`
> `memcpy(&robot_custom_data_3, frame + index, sizeof(robot_custom_data_3_t));`
> 这条 case 是活的（不像 0x0304 被注释）。缺的只是**下游消费者**
> （`usb_task.c:125/181/392/605-609/1216-1219` 全注释，数据躺在内存里没人读）。
> 客户端这半截也早就有了：`CustomControl` 经 MQTT 发、75Hz 门控，
> 载荷用队内自己的 `PRM1` 魔数（`rm_client/backend/protocol.py:19-22`，
> kind: VISION=1 / SPIN=2）。
>
> ⇒ 正确的适配点：**给固件写一个 0x0311 的 PRM1 载荷消费者**（键位/鼠标落到
> §3 的键位账本 + `__CONTROL_LINK_KM` 五档仲裁），而不是复活 0x0304。
> 详见 `tools/dt7_link/README.md` 第 5 节。

在此之前，能用的就是 §1 的 ①②③。这也是客户端里 `gimbal_egress_owner()`
那个互锁存在的原因（两条云台出口同时发角会打架）。

## 6. 拔掉 USB 线会怎样

| | DT7（当前比赛配置） | 非 DT7（ET08A 等） |
|---|---|---|
| 驾驶员控车 | 正常（键位、摇杆、鼠标全在） | 正常（仅摇杆 + 拨杆） |
| 客户端控车 | **没了**（0x5A 需要 USB 线） | **没了** |
| 客户端自转开关 0x04 / 回读 0x1F、0x1E | 没了 | 没了 |

也就是说：**要客户端开车就必须插 USB 线**；而"比赛时车能被开起来"这件事
本身不依赖 USB 线，DT7 键鼠链路是完整的一条无线通路。
要把客户端也变成无线的，可选三条：§7 的 **DT7 虚拟控制链路**（官方设计，
固件零改动，缺 PC↔DT7 报文格式）、§5 更正后的 **0x0311 + PRM1 消费者**
（2026 正规路，两端都已有代码，只差固件侧一个消费者）、或车上加 USB↔WiFi 透传
（后者现场不稳，不建议当比赛方案）两条路。

## 7. 电脑经 DT7 控车（大疆官方客户端那条）——固件侧已经是通的，缺的只有 PC↔DT7 那一段

**先认错**：这一节最早的说法（"客户端根本不碰遥控器"）是错的。电控同学说的
"电脑连 DT7 就能开车"不但属实，而且是**大疆写进自己手册的正式能力**。

**官方原文**（大疆《DT7 & DR16 2.4 GHz 遥控接收系统用户手册》V1.0 2016.09 第 5-7 页；
本地副本 `D:\rmbuild\DT7_DR16_RM_manual_official.pdf`）：

> "DR16 接收机输出的信号为标准的 DBUS 协议数据……接收机每隔 14ms 通过 DBUS
>  发送一帧 18 字节数据。**为了满足通过 PC 控制战车的需求，增加了额外的键盘鼠标
>  控制信息**，控制链路示意如图所示：
>  `键盘鼠标 → PC主机USB →（虚拟控制链路）→ 遥控器发射机(DT7) → 遥控器接收机(DR16)
>   →（DBUS）→ 战车`"

而同一本手册第 2 页 DT7 的部件表只有 2 摇杆 / S1 / S2 / 滑杆 / Micro-USB / 电池仓
—— **DT7 本身没有键盘鼠标**。所以 18 字节里 bytes 6-15 那份键鼠，唯一来源就是电脑
经那个 USB 口灌进去的。大疆给这条链路起的正式名字是**"虚拟控制链路"**。

**位序对齐不是抄表抄出来的，是跑出来的**：
`tools/dt7_link/dt7_dbus_frame.py` 按手册位序编帧，
`tools/dt7_link/test_dbus_frame_vs_firmware.py` 把固件里**真实的** `sbus_to_rc()`
函数体原样抽出来编成 exe、喂进去、逐字段比对（11 组用例，含 ±32768、0xFFFF、
通道端点），并守住房件常量（中值 1024 / 帧长 18 / KEY_W..KEY_E 位号）。
已挂在 `verify_all.py` 里。

**还有一个没定死、但会咬人的坑**：键位 bit4-7 有两套官方定义在打架 ——
遥控器手册(2016) 是 `Q E Shift Ctrl`，而队内固件 `remote_control.h:103-118`
（和 2026 协议的 `KeyboardMouseControl` 一致）是 `SHIFT CTRL Q E`。
**bit0-3 的 W/S/A/D 两套完全相同**，这正好解释了为什么键鼠开车一直好用、
而 Q/E/Shift 的错位从没被当场抓出来。如果 DT7 按前者打包，
现场表现就是"驾驶员按 Shift 车去做 Q 的事（摩擦轮），按 Q 车开小陀螺"。
这一条必须拿真 DT7 现场验一次才能定，别当结论用。

按代码把这条链路一节一节排开：

| 段 | 谁做 | 状态 |
|---|---|---|
| 电脑键鼠 → DT7 | 大疆官方客户端（私有协议） | **他们做过、能用车**；协议细节 DJI 私有 |
| DT7 → 车上 DR16 | 18 字节 SBUS，键位在 bytes14-15、鼠标在 bytes6-13 | 无线，标准 |
| C 板解 SBUS | `remote_control.c:252` 按**帧长**分派 → `sbus_to_rc()`（与 `__RC_TYPE` 无关） | ✅ 通 |
| 底盘消费键位 | `chassis_mecanum.c:196-199` 读 `key.v` 的 W/S/A/D（干净树是 148-151） | ✅ 通 |
| 云台消费鼠标 | `gimbal_yaw_pitch_direct.c:331-332` 读 `mouse.x/y` | ✅ 通 |
| 客户端的键位叠加 | 本次的键位账本：DT7 那侧进 `HOST_RC_DRIVER_KEYS` | ✅ 通，且官方客户端注入的键鼠**天然算"驾驶员侧"**，不会被覆盖、也不会被抹 |

所以：**固件这边一行都不用改，这条路就能开车**（这正是"客户端控车"和"我们仓库的 0x5A"是两件事）。
真正的缺口只有一个，而且它不在固件里：

> **我们自己的 `rm_custom_client` 里没有 PC↔DT7 那段协议**（全仓搜过 dt7/dr16/hid/joystick，
> 一处实现都没有）。要让我们客户端也能经 DT7 控车，就得先搞清楚那段协议长什么样。

### 那段协议查到什么程度了：是个虚拟串口，只差帧格式

2026-09-04 从大疆官方驱动包（`https://rm-static.djicdn.com/tem/RoboMaster 遥控器驱动.7z`）
里用 `innoextract -e` **只解包**读出 `dji_vcom_driver11.inf`，原文关键几行：

```
Class=Ports
%DJIVCOM% =XP40, USB\VID_FFF0&PID_0008&MI_00
ServiceBinary=%12%\usbser.sys
DJIVCOM = "DJI USB Virtual COM"
```

三条定性结论（把本节上一版"要装驱动说明不是即插即用 HID，得抓包才知道"整段替换掉）：

1. **DT7 的 USB 口 = 虚拟串口**（`Class=Ports`），不是 HID 手柄；
2. 硬件 ID 是 **`USB\VID_FFF0&PID_0008`**，**不是** DJI 消费机的 `VID_2CA3`
   —— 所以先前"注册表搜 `2ca3` 零命中"那条取证用错了门牌号；本轮按 `FFF0`
   重扫仍然零命中，"这台电脑从没插过 DT7"这个结论换对了依据后依然成立；
3. 驱动服务是 Windows 自带的 `usbser.sys`（标准 USB CDC-ACM），
   **不需要厂商 DLL、不需要 libusb、不需要仿 HID 报告** -> 用 pyserial 直接读写。

于是缺的东西从"逆向一套私有 USB 协议"缩小成一件：**这个串口上的帧格式**
（大疆只公开了 DR16->车的 DBUS 侧，没公开 PC->DT7 侧）。

黑盒试探工具已经写好：`tools/dt7_link/dt7_vcp_probe.py`，四种候选帧型
（`dbus18` 整帧同构 / `km12` 只给键鼠 12 字节 / `km6` 三轴+键位 / `keys2` 裸键位图，
**都是假设不是官方定义**）：

```
python tools/dt7_link/dt7_vcp_probe.py --list                    # 认 FFF0:0008 那个口
python tools/dt7_link/dt7_vcp_probe.py --candidates --keys W,SHIFT --mouse 12,-5,0
python tools/dt7_link/dt7_vcp_probe.py --port COM5 --candidate dbus18 --keys W \
       --confirm-move-car                                        # 不给这开关只打印不发
```

两道安全闸：不给 `--confirm-move-car` 一个字节都不发（猜对了车就会动）；
发完自动补一帧等长全零，避免把键粘在车上。四种帧型全部无效的兜底办法是用
com0com 建虚拟串口对，或者直接在 USB 层抓官方客户端的报文。

### 本轮新增：不用硬件也能判位序的两条办法

1. **看车自己的反应**：`shoot_fric_trigger.c:100` 把 Q（bit6）接在摩擦轮上、
   `chassis_omni.c:109` 把 SHIFT（bit4）接在小陀螺上。所以"按物理 Q 之后
   摩擦轮转不转"当场就把位序判完，什么仪器都不需要。
2. **旁听 DT7 的虚拟串口**：`python tools/dt7_link/dt7_vcp_probe.py --port COMx --listen 8`。
   只读不写、对车零影响；能旁听到 18 字节帧就说明那口是串口桥（回写有戏），
   并按跳变直接报"这个键落在 bit 几 + 两套位序各读作什么"。

细节与证据在 `tools/dt7_link/README.md` 第 3.1 / 4.3 / 4.4 / 4.5 节。

### 两条并存的注意事项

1. **官方客户端和我们客户端不要同时抢 DT7**：同一条 HID/CDC 通道一般只允许一个宿主打开，
   而且两边都往 bytes14-15 写键位，最后写的赢 —— 那是**遥控器那一侧**的覆盖，不是 §3 的账本
   （账本只管 `rc_ctrl` 里"遥控器 vs 0x5A"这两本账）。
2. 车上的 0x5A（USB 插 C 板）那条**照旧可用**，两本账是"或"的关系：
   DT7 里是 W、0x5A 里是 S ⇒ `key.v` = W|S，一起生效。


---

## 8. 图传键鼠链路（0x0311 + PRM1 kind=3）：2026-09-04 已接完

第 5 节说"0x0304 在 2026 赛季已被官方删除，正确落点是 0x0311"。**这一节就是那条
链路的实现记录**，工具在 `tools/firmware/km_link/`，客户端那半截在
`rm_client/backend/protocol.py` 的 `encode_km_control_payload()` 与
`manager.publish_km_control()`。

### 数据怎么走

```
客户端键鼠 ──> CustomControl(MQTT, 75Hz 门控, PRM1 kind=3, 26B)
          ──> 裁判系统/图传发送端 ──> 图传链路 ──> C 板 referee 串口
          ──> referee.c:247  memcpy -> robot_custom_data_3   （本来就有，活的）
          ──> HostKmPeep()   魔数/版本/kind 三重校验
          ──> HostKmLinkUpdate()  按 __CONTROL_LINK_KM 仲裁
          ──> key.v = (驾驶员 & 门闸) | 上位机0x5A | 图传      （三本账）
          ──> 底盘/摩擦轮/云台（全是固件原有消费者，一行未改）
```

### 五档语义（`--km rc|none|vt|rc_vt|vt_rc`，默认 `rc`）

| 档 | 键位 | 鼠标 |
|---|---|---|
| `rc`（默认，现役车） | 图传不参与，`key.v = 驾驶员 \| 0x5A` | 一个字节都不动 |
| `none` | 两路键位都屏蔽 | 清零 |
| `vt` | 只认图传，**关驾驶员键位门闸** | 只认图传；图传过期即清零 |
| `rc_vt` | 两路或起来 | 驾驶员这帧动过鼠标就归他，否则归图传 |
| `vt_rc` | 两路或起来 | 图传新鲜归图传，过期回落给驾驶员 |

键位在两个混合档里表现相同不是偷懒：键位是**位图**，"互补"天然就是按位或；
真正需要选的是**鼠标**，它是位移增量，两路相加会把云台甩双倍。

### 三条写死的底线

1. **任何一档都不屏蔽摇杆 `ch[]` 与拨杆 `s[]`** —— 配成 `vt` 且图传当场断掉，
   驾驶员仍然能用摇杆把车开回来、用拨杆把模式锁掉。测试里每档都断言了
   `ch[0]/ch[1]/s[0]/s[1]` 四个量没被动过。
2. **开火权限不由这段代码偷偷给**：默认掩码 `KM_KEY_MASK_DRIVE=0x1F`
   （W/S/A/D/SHIFT），Q/E 属于摩擦轮/开火，要显式 `--km-fire-keys` 才放开。
3. **不信任收件箱**：`HostKmPeep()` 要魔数 + version + kind 三项全对才解，
   别的 kind（VISION=1 / SPIN=2 已经在发）一个字节都进不来。

### 验证等级

- 五档仲裁 + 摇杆底线 + 开火权限：`tools/firmware/km_link/test_km_link.py`，
  喂的是**客户端真打出来的那 26 字节**（`build_tu()` 编译期嵌进 C 场景），
  六组变体全过；`--negative` 把实现退回"图传直接覆盖 key.v + 不做新鲜度门控"
  之后六组全部被抓到 —— 断言不是空的。
- C 结构体与客户端打包逐字段对表：`test_km_payload_layout.py`
  （把 `offsetof` 真编出来量，防 `__packed__` 失效或有人中间插字段）。
- 五种 `__CONTROL_LINK_KM` 取值各编一遍真实 ARMCC 5.06：**162 单元 / 0 失败**
  ×5（工程开着"警告即错误"）。
- 未验：真机上 0x0311 是否真的到达 C 板。**这条现在是头号风险**：官方
  《2026 通信协议》表 1-1 写 `图传发送端←→机器人 921600`，1.1 节写图传链路
  「从图传模块（发送端）的串口接收数据」，表 1-5 把 0x0311 标成图传链路；
  而本固件裁判口是 `huart6`@115200（`referee_usart_task.c:45`），**全仓无 921600**
  （`Src/usart.c:41/60/79-80` 只配了 USART1=115200 板间、USART3=100000 8E1 遥控器 DBUS、
  USART6=115200 裁判；`Inc/usart.h` 也就声明了这三个句柄）。
  ⇒ 结论要说明白：**B 路不是"接根线"的事**，要么补一路 921600 UART（要改 CubeMX 配置与接线），
  要么由车载电脑收 0x0311 后经 `HostKmFeed()` 喂进 C 板；比赛现场更省事的是直接用 C 路。
  口名与原文行号见 `GAPS.md` 第 10 节第 3 条；量法是看 `HOST_KM_RX_COUNT` 涨不涨。
- ~~未验：键位 bit4-7 位序之争~~ **已结案（2026-09-05，从厂商二进制结案，不用再上车）**：
  12.x 选手端 `dump.cs:136133-136148` 与 `:146776-146791` 的 `KeyBoardRC`/`KeyBoard` 枚举是
  `W1 S2 A4 D8 SHIFT16 CTRL32 Q64 E128 R256 F512 G1024 Z2048 X4096 C8192 V16384 B32768`，
  与固件 `remote_control.h:103-118`（`KEY_SHIFT=4`…`KEY_B=15`）、客户端 `KEYBOARD_BITS` **逐位一致**。
  2016 版 DT7 手册那套（`Bit4=Q Bit5=E Bit6=Shift Bit7=Ctrl`）是**过时文档**，别照它改代码。
  防倒退：`dt7_dbus_frame.KEY_ORDER_VENDOR_2026` 常量 + `test_dbus_frame_vs_firmware.py`
  拿固件真解码器逐字段核对，`test_radio_km_client.py` 里也有一条位序断言。
  ⇒ 本文件以前把它列成"未验的头号悬念"是过期表述，会把人再骗一天，现更正。

## 9. 客户端侧的出口开关（2026-09-04 第二轮）

固件这半截上一轮就有了，但客户端那半截的开关不在界面上 —— 现场等于没有。本轮补上：

| 位置 | 内容 |
|---|---|
| `rm_client/model.py` | 新设置项 `RobotLink / Radio KM Egress`，默认关 |
| `rm_client/backend/manager.py` | `tick_polar_link()` 每帧重算生效：`开关 && 非急停 && Allow Drive && 模块启用`；**不看 0x5A USB 链路是否 active** |
| `rm_client/control.py` | 出口函数 `_send_radio_km()`，与官方 KMC 完全解耦（不看 `mock_output`、不看 KMC 成没成） |
| 诊断 | `radio_km_gate_reason`（没让发）与 `radio_km_last_error`（发了被拒）分开；水印行加 `KM on/off` |
| 测试 | `tools/dt7_link/test_radio_km_client.py`（含 `test_manager_gates()`） |

### 一个容易被"顺手加固"改错的地方

位图这件事在两条路上含义完全不同，**不能互相借用**：

- 走 0x0311（本节）：键位由客户端按**固件位序**编（bit4=SHIFT…），固件按同一套解，
  所以默认掩码 `0x1F` 就是"W/S/A/D + 小陀螺"，Q/E 要 `--km-fire-keys` 才放开。
- 走 DT7 虚拟控制链路（第 7 节）：键位同样由 DT7 打包经空口回来，但**位序与 0x0311 那条完全相同**（上面 2026-09-05 已结案：厂商 12.x `dump.cs` 的 `KeyBoardRC` 与固件 `remote_control.h:103-118` 逐位一致，bit4=SHIFT）。2016 手册那套 bit4=Q 是**过时文档**；以前拿它当“两条路不得复用位图”的理由，是错的。

⇒ 所以两条路的键位表各归各的编码，DT7 那条在位序被现场证死之前**不得复用**
`KEYBOARD_BITS`，也不得给客户端加"一个开关两条路都开"的省事写法。
