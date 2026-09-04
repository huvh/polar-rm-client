# 电脑 -> DT7 -> DR16 -> 车：这条链路到底是什么情况

结论先说：**电控同学的记忆是对的，这条链路是大疆自己设计并写进手册的能力。**
我之前在对话里说过"客户端根本不碰遥控器""DT7 只是驾驶员的手"，那是错的；
也说错过"走 DT7 必须配对/要改固件"。这里把证据和我改过来的结论一次写清。

---

## 1. 官方文档原文（决定性证据）

大疆《DT7 & DR16 2.4 GHz 遥控接收系统用户手册》V1.0（2016.09）第 5-7 页。
本地副本：`D:\rmbuild\DT7_DR16_RM_manual_official.pdf` / 同目录 `.txt` 提文本。

> "DR16 接收机输出的信号为标准的 DBUS 协议数据，当遥控器与接收机建立连接后，
>  **接收机每隔 14ms 通过 DBUS 发送一帧 18 字节数据。为了满足通过 PC 控制战车的需求，
>  增加了额外的键盘鼠标控制信息**，控制链路示意如图所示：
>
> `键盘鼠标 -> PC主机USB ->（虚拟控制链路）-> 遥控器发射机(DT7) -> 遥控器接收机(DR16) ->（DBUS）-> 战车`"

三个要点：

1. **大疆明写这 18 字节里多出来的键鼠字段就是给 PC 用的**（"为了满足通过PC控制战车的需求"）。
2. 这条链路大疆给的正式名字是 **"虚拟控制链路"**。
3. 手册第 2 页 DT7 的部件表只有：2 摇杆 / S1 / S2 / 3 档开关 / 滑杆 / Micro-USB / 电池仓
   —— **DT7 自己没有任何键盘鼠标**。所以帧里 bytes 6-15 那份键鼠，
   唯一来源就是电脑经那个 USB 口灌进去的。
   （这就是为什么"大疆客户端连 DT7 就能开车"：客户端把键鼠写进 DT7，
   DT7 把它塞进同一条 2.4G 帧发给 DR16。）

DBUS 电气参数（同一页）：100 Kbps / 8 数据位 / **偶校验** / 1 停止位 / 无流控，
TTL 电平但**与普通 UART 反相**，MCU 侧要加三极管取反 —— C 板硬件已经做好了，
对应固件 `remote_control.c` 的 UART3 + DMA 收。

## 2. 帧位序 = 固件解码，逐位对得上（已用固件真实代码验过）

18 字节 = 144 bit。手册表 与 固件 `application/other/remote_control.c`
（打桥后的 371-391 行；干净树 `C:\Users\lulunomaro\Desktop\claude\电控\StandardRobotpp`
的 370-390 行）完全一致：

| bit | 字段 | 固件行 |
|---|---|---|
| 0-10 / 11-21 / 22-32 / 33-43 | 通道 0-3（11bit 无符号，364..1684，中值 1024） | `:371-375` |
| 44-45 / 46-47 | 拨杆 s[0] / s[1]（1=上 2=下 3=中） | `:376-377` |
| 48-63 / 64-79 / 80-95 | 鼠标 X / Y / 滚轮（int16 位移） | `:378-380` |
| 96-103 / 104-111 | 鼠标左键 / 右键（uint8 0/1） | `:381-382` |
| **112-127** | **键盘 16bit 位图** | `:383` |
| 128-143 | 保留（固件当 ch[4] 读，减中值后基本没人用） | `:391` |

这条对齐全自动态验证，不靠我抄表：
`tools/dt7_link/dt7_dbus_frame.py`（编解码）+
`tools/dt7_link/test_dbus_frame_vs_firmware.py`
—— 后者把固件里**真实的** `sbus_to_rc()` 函数体原样抽出来，带真实头文件编成 exe，
用 Python 打的帧喂进去，逐字段比对（11 组用例，含 ±32768 边界、0xFFFF 全键、
四通道拉到端点），并额外钉住固件常量（`RC_CH_VALUE_OFFSET=1024`、
`RC_FRAME_LENGTH=18`、`KEY_W..KEY_E` 的 bit 号）——电控哪天改了位序，测试先红。

## 3. 一个还没定死、而且会咬人的坑：键位位序有两套官方定义在打架

| 来源 | bit0-3 | **bit4** | **bit5** | **bit6** | **bit7** |
|---|---|---|---|---|---|
| A. DT7&DR16 遥控器手册 V1.0(2016) 第 7 页 + 附录示例代码 | W S A D | **Q** | **E** | **Shift** | **Ctrl** |
| B. 队内固件 `remote_control.h:103-118`（= 现在真正决定车怎么动的） | W S A D | **SHIFT** | **CTRL** | **Q** | **E** |
| B'. RM2026 通信协议 V1.2.0 的 `KeyboardMouseControl` 键盘位掩码 | W S A D | Shift | Ctrl | Q | E |

- **bit0-3（W/S/A/D）两套完全一样** —— 这正好解释了为什么"键鼠开车"一直好用、
  而 Q/E/Shift/Ctrl 的错位从来没被当场抓出来。测试里专门有这条断言。
- 好消息：B（固件）与 B'（2026 官方键鼠协议）**一致**，所以我们的客户端
  （`rm_client.control.KEYBOARD_BITS`，注释即"官方位序"）和固件之间不会错。
- 没定死的是：**DT7 经 USB 收到电脑键鼠后，往 2.4G 帧里打包时用哪套？**
  手册 A 是 2016 年的老定义（只有 8 个键），固件 B 有 16 个键，显然是按新协议改过的。
  但这只能现场验：拿真 DT7 + 官方客户端，插 W / 插 Shift / 插 Q 各一次，
  用示波器式的土办法（或让固件把 `rc_ctrl.key.v` 打回上位机）看落在哪个 bit。
- 风险后果很具体：如果 DT7 按 A 打包而固件按 B 解，那么
  **驾驶员按 Shift 会被车当成 Q（摩擦轮），按 Q 会被当成 Shift（小陀螺）**。
  W/S/A/D 不受影响。所以这项必须在"客户端往 DT7 灌键鼠"之前定死。

### 3.1 第三个数据点，以及一个不用硬件也能判的办法

新证据（2026-09-04 全仓扫过中科大 RoboWalker 训练仓库 `D:\rmbuild\rbw_train`，
即用户给的 `yssickjgd/robowalker_train`）：

- `01_electrical/05_chassis/07_motor_power_model/3_3508_data_test/test_3508/User/2_Device/DR16/dvc_dr16.h:29-42`
  （文件头 `@copyright USTC-RoboWalker (c) 2022`、`@date 2023-08-29 0.1 23赛季定稿`）：
  `DR16_KEY_SHIFT 4`、`DR16_KEY_CTRL 5`、`DR16_KEY_Q 6`、`DR16_KEY_E 7`，
  另带 `R F G Z X C V B` 到 bit8-15 —— **与队内固件 `remote_control.h:103-118` 完全一致**。

于是"两套位序"不是同级打架，而是**两个世代**：

| | bit4-7 | bit8-15 | 出处 |
|---|---|---|---|
| 老（2016 遥控器手册 V1.0） | Q E Shift Ctrl | 保留；附录示例里 `pData[15]` 那半截是**注释掉**的 | 手册第 7-8 页 |
| 新（现役固件 / RM2026 协议 / 中科大 23 赛季定稿） | SHIFT CTRL Q E | R F G Z X C V B | `remote_control.h:103-118` |

手册附录那行 `key.v = ((int16_t)pData[14]);// | ((int16_t)pData[15] << 8);`
正好是"后来启用第二字节、顺带重排 bit4-7"的痕迹。所以合理推断是
**DT7 现网固件按新位序打包**；但推断不能上车，下面两法任选一个当场证。

#### 判定法 A：什么工具都不要，看车自己的反应（十秒）

固件里这三个键都接在**肉眼可见**的动作上（本轮逐行核过）：

| 键位 | 固件行 | 现象 |
|---|---|---|
| SHIFT（bit4） | `chassis_omni.c:109`、`chassis_mecanum.c:216` | 切小陀螺 |
| Q（bit6） | `shoot_fric_trigger.c:100`（原注释："Q启动摩擦轮"） | 摩擦轮起转 |
| E（bit7） | `shoot_fric_trigger.c:104` | 摩擦轮停转 |

**拨杆 s[0] 放中间、车上电、按物理 Q**：摩擦轮起转 = DT7 用新位序，
我们现在的编码直接可用；车切小陀螺 = DT7 用 2016 位序，
那发包必须按 `dji2016` 位序编，而且**现役驾驶员一直按的是错位的键**
（按 Shift 想开小陀螺会先转摩擦轮），这本身就该马上处理。
反过来说：真要一直错位，"按 Shift 出小陀螺"这个日常动作早就把摩擦轮带起来了，
全队不可能一年没发现 —— 这是间接证据，不是证明。

#### 判定法 B：零风险旁听（本轮新增，不发包、车不会动）

    python tools/dt7_link/dt7_vcp_probe.py --port COMx --listen 8

DT7 插电脑，只**读**那个虚拟串口，按空闲线分帧，把解出来的通道/键位跳变打在屏幕上，
并对每个跳变 bit **同时给出两套位序的读法**。它顺便回答一个更基本的问题：
这个口是"串口桥"（能旁听到 18 字节、摇杆一动通道就动）还是
"命令式助手口"（不主动吐东西，那回写就得先学会发命令）。
离线断言：`tools/dt7_link/test_vcp_listen.py`。

## 4. 那"我们客户端经 DT7 控车"还差什么？—— 已经查到只剩一件事

### 4.1 先更正本节上一版的说法

上一版写的是"PC<->DT7 是一段私有 USB 协议，要装驱动说明不是标准 HID，得抓包"。
**方向对了一半，性质搞错了。** 从大疆官方驱动包里把 INF 解出来看，答案是：

官方下载地址：`https://rm-static.djicdn.com/tem/RoboMaster 遥控器驱动.7z`（DJI 官方 CDN）
解包方式：`innoextract -e`，**只解包读文本，没有运行那个安装器**。
包内 `dji_vcom_driver11.inf` 原文（节选）：

```
[Version]
Class=Ports
ClassGuid={4D36E978-E325-11CE-BFC1-08002BE10318}
Provider=%DJI%
DriverVer =12/06/2012, 5.1.2600.5512

[DeviceList]
%DJIVCOM%  =XP40, USB\VID_FFF0&PID_0008&MI_00
%DJIVCOM%  =XP40, USB\VID_FFF0&PID_0008

[DriverService]
ServiceBinary=%12%\usbser.sys

[Strings]
DJIVCOM    = "DJI USB Virtual COM"
```

三条硬结论：

1. **DT7 那个 USB 口是虚拟串口**（`Class=Ports`），不是 HID 手柄/游戏杆。
   所以不用仿造 HID 报告、不用 libusb、不用碰 Windows 驱动。
2. 硬件 ID 是 **`USB\VID_FFF0&PID_0008`**（复合设备的 `MI_00` 那一面），
   **不是 DJI 消费机的 `VID_2CA3`**。
   -> 上一版那条"本机注册表搜 `2ca3` 零命中"的门牌号是错的，
      **不能当证据用**（这台电脑确实没插过 DT7，但要重扫 `FFF0` 之后才算证完；
      本轮已重扫：`HKLM\SYSTEM\CurrentControlSet\Enum\USB` 下 `FFF0` 也是零命中，
      所以"这台机器从没插过 DT7"这条结论仍然成立，只是换了正确的依据）。
3. 驱动服务是 Windows 自带的 `usbser.sys`（标准 USB CDC-ACM）。
   -> 客户端用 **pyserial 打开那个 COM 口就能直接写**，我们仓库本来就依赖 pyserial。

于是"缺口"从"逆向一套私有 USB 协议"缩小成一件事：**这个串口上的帧格式**。
大疆确实没公开它（手册只公开了 DR16->车的 DBUS 侧），所以只能黑盒问。

### 4.2 黑盒问法已经写成工具

`tools/dt7_link/dt7_vcp_probe.py`。四种候选帧型（**都是假设，不是官方定义**）：

| 帧型 | 长度 | 内容 | 赌的是什么 |
|---|---|---|---|
| `dbus18` | 18B | 与 DR16 出口完全同构的整帧 | DT7 只做透传 |
| `km12` | 12B | 只给键鼠那 12 字节（DBUS bytes6-17） | 摇杆留给摇杆、只收键鼠 |
| `km6` | 8B | 鼠标三轴 + 键位，不含左右键 | 精简实现 |
| `keys2` | 2B | 最裸的 16bit 键位图 | 只支持键盘不支持鼠标 |

```
# 1) 找口：认的就是 FFF0:0008（官方 INF 里的死值，插上必然匹配得上）
python tools/dt7_link/dt7_vcp_probe.py --list

# 2) 先看帧型长什么样（这一步不碰硬件）
python tools/dt7_link/dt7_vcp_probe.py --candidates --keys W,SHIFT --mouse 12,-5,0

# 3) 真发。不给 --confirm-move-car 就只打印字节、一个字节都不发
python tools/dt7_link/dt7_vcp_probe.py --port COM5 --candidate dbus18 --keys W \\
       --confirm-move-car
```

安全上做了两道：发之前必须显式给 `--confirm-move-car`（因为这东西一旦猜对
**车就会动**），发完自动补一帧等长全零，避免把键粘在车上。

判读：`--list` 能看到 `VID_FFF0&PID_0008` 的口 -> 通路已经通了，剩下纯粹是帧型；
一种都不动就换下一种；四种都不动，才需要回到"抓官方客户端的报文"这条路
（届时可以用 com0com 建虚拟串口对，或直接在 USB 层抓）。



### 4.3 用户给的 `RC_System_Installer_v1.2.zip` 是什么：**不是 DT7 的调参软件**

解包（`innoextract` 只解不运行）→ `D:\rmbuild\rcsys\x\app\`。
决定性证据是它自带的中文说明 `doc/zh_CN/main.html`，原文照抄：

> "Phantom RC调参软件是**Phantom遥控器**专用调参软件，用于对遥控器进行配置和升级。
> 适用于DJI Phantom 2.4G遥控器和5.8G遥控器。"

再看界面字符串：`X1Channel / X3Channel / RUDDChannel / ThroChannel / ELEVChannel /
AileChannel`、`freq_rc_cur`、`ch_monitor` / `Channel Monitor`、
`This calibration function is only available for A,E,T,R X1 channels. The U,X2
channels have no need to calibrate.` —— 全是飞行器舵量/校准语义。
**DT7 不在它支持的设备里，拿它控 DT7 走不通。**

但它仍是两条有用的旁证：

1. **它连遥控器的方式就是纯 Win32 串口**。导入表只有
   `CreateFile/ReadFile/WriteFile/GetCommState/SetCommState/SetCommTimeouts/PurgeComm/
   SetCommMask/GetCommModemStatus/ClearCommBreak` 这一套，加宽字符串
   `\\.\`、`DJI USB Virtual COM`、`USB Virtual COM`、`PortName`；
   **整个 exe 没有 hid.dll / HidD_\***。"DJI 那一代遥控器对 PC 就是个 COM 口"是通用的。
2. **那个口上跑的不是裸 DBUS，而是命令式协议**。exe 里内嵌一个文本控制台
   （`help / open / close / cmd [file] / query [cmdid] / showall / dlgup /
   addparser [file] / getparsers / echoparser / setcrc / getcrc / enablecrc / run / quit`）
   和一整套帧字段名（`header / ackid / Command ID / Command Length(Exclude Head) /
   crc_16 / result / RECV / Checksum error %x / Unknown id %s / create command fail!`），
   参数模型是老 DJI 助手的 `int8s..float64 + RPI + begin/data/modify/end/const/value/func`。
   这就是 Naza/Phantom 那代助手协议的样子（同源线索：它下载设备表用的
   `http://download.dj2006.net/nazam/config.xml`，版权 `2011-2014 DJI Innovations`）。

⇒ 对 DT7 的直接推论：**别一上来就假设"往 COM 口写 18 字节 DBUS 就能开车"**。
它完全可能是命令式的（要先 `open`/`query`，键鼠是某条 Command ID）。
所以本轮把工具顺序改了：**先 `--listen` 旁听（零风险）**；
旁听到东西再谈回写；一个字都不吐，才回到"抓官方客户端报文"那条硬路。

### 4.4 "中科大 RM 电控里应该有 DT7 驱动"——查完了，一半有一半没有

`D:\rmbuild\rbw_train`（= `github.com/yssickjgd/robowalker_train`，
本轮浅克隆，78.37 MiB / 59196 个文件）：

- **有**：DR16 的 **MCU 侧解码驱动** `User/2_Device/DR16/dvc_dr16.{h,cpp}`
  （USART+DMA 双缓冲收 DBUS、解 ch/s/mouse/key），随仓的
  `用户手册 DR16&DT7.pdf`（648937 字节，与用户下载那份同一文件），
  以及 `串口绘图配置.ini`（Vofa+ 画波形）。
- **没有**：任何 PC 侧 DT7 代码。全仓对
  `DT7 / 虚拟串口 / VCOM / 键盘鼠标 / 虚拟控制 / KEY_PRESSED_OFFSET` 检索，
  命中的只有 `readme.md` 两处目录标题、`修订日志.md` 两处、以及手册 PDF 本身，
  **没有一处 PC↔DT7 收发实现**。
  资料里那章"USB虚拟串口通信与接口"（`02_electrical_plus/02_damiao_mc02/03_usb_cdc`）
  讲的是**达妙 MC02 板自己做 USB CDC 设备**，方向是"板子→电脑"，与遥控器无关。

⇒ 记忆里"调车时电脑连的是带串口的东西"，最可能是**电脑插 C 板/开发板的 USB
虚拟串口**（就是我们 0x5A 那条）或 Vofa+ 绘图；DT7 侧的 PC 驱动不在这套资料里。

### 4.5 顺带钉死"别人的客户端怎么走"：Shark 走 MQTT，不碰 DT7

工作区里那份 Shark 战队客户端（`SharkClient-ref`，江南大学霞客湾校区）：

- `src/components/MqttCommandPanel.vue:350-354` 原注释：
  "新协议拆分：键鼠字段 -> KeyboardMouseControl；自定义二进制 -> CustomControl"
- `src/components/Dashboard/constants.ts:85`：`brokerUrl: 'mqtt://192.168.12.1:3333'`
  （192.168.12.x 是图传网段，3333 是这套 MQTT 端口）
- 全仓搜 `DT7 / DR16 / dbus / 虚拟串口`：**零命中**（只有一处 package-lock 哈希撞字面）。

⇒ 现役同行的自定义客户端 = **发 MQTT（图传链路）→ 车**，不碰遥控器。
我们这条 0x0311 + PRM1 kind=3 与它同一条物理路，只是载荷换成队内自定义。
所以本轮把"能无线开车"的重心放在这条出口的**开关与门控**上（第 8 节），
DT7 那条继续当"待现场判定"的第二方案。

## 5. 另一条不依赖 DT7 帧格式猜测的无线路（2026 赛季的正规路）

查 RM2026 通信协议 V1.2.0（2026.02.09）修改日志，第 2 条写着
**"删除命令码 0x0304"**，第 3 条把原来的 RemoteControl 拆成
`KeyboardMouseControl` 与 `CustomControl`。也就是说：

- **老计划里"把 `referee.c:238` 注释掉的 0x0304 解析补回来"这个目标本身已经作废** ——
  2026 的裁判系统不会再发 0x0304 了，补回来也收不到。
- 2026 赛季"自定义客户端 -> 机器人"的活通道是 **0x0311**（30 字节，上限 75Hz，
  走图传链路），而且 **队内固件已经在收并且存进内存了**：
  `application/referee/referee.c:247`
  `memcpy(&robot_custom_data_3, frame + index, sizeof(robot_custom_data_3_t));`
  —— 这条 case 是**活的**（不像 0x0304 那样被注释）。
- 全仓 `robot_custom_data_3` 的**消费者只有注释掉的 usb_task 转发**
  （`usb_task.c:125/181/392/605-609/1216-1219` 全是注释），所以数据躺在内存里没人用。
- 我们客户端这半截也**早就有了**：`CustomControl` 经 MQTT 发、75Hz 门控，
  而且已经有一套队内自定义载荷（`rm_client/backend/protocol.py` 的
  `TEAM_CONTROL_MAGIC = b"PRM1"` + version + kind：VISION=1 / SPIN=2）。

⇒ 所以**正确的适配点**是：在固件里给 0x0311 写一个 PRM1 载荷消费者
（把 driving 键位/鼠标/自转落到键位账本上，带 75Hz 新鲜度门控 +
`__CONTROL_LINK_KM` 五档仲裁），而不是去复活 0x0304。
这条路的好处是：两端代码都已存在（客户端在发、固件在收），中间只差一个消费者，
而且用的是 2026 赛季正规允许的频率与链路。

## 6. 这份调查推翻/修正了哪些旧说法

| 旧说法 | 现在的事实 |
|---|---|
| "客户端根本不碰遥控器，也不需要配对" | 对**我们 0x5A 实现**成立；但大疆确实设计了**经 DT7 的键鼠注入**（虚拟控制链路），我先前把它一并否认是错的 |
| "DT7 + ET08A 配置会导致车自己慢慢动" | 不成立：固件按**帧长**分派，18 字节无条件进 `sbus_to_rc()`，`__RC_TYPE` 只影响 25 字节那批解码器与 `GetRcOffline()` |
| "把 0x0304 的注释解析补起来就有了第二条无线通道" | 目标作废：0x0304 在 2026 协议里已被删除。活的可扩展通道是 0x0311（固件已在收）与 0x0302（30Hz） |
| RC_LINKS.md §7 "缺 PC<->DT7 协议" | 保留并且升级：现在有官方手册原文 + 位序对齐的可执行证明，不再靠现场记忆 |

---

## 7. 2026-09-04 更新：0x0311 那条已经接完了

上面第 5 节写的是"正确适配点是给固件写一个 0x0311 的 PRM1 载荷消费者"。
**这件事本轮做完了**，实现与验证记录在
`tools/firmware/host_bridge/RC_LINKS.md` 第 8 节，工具在 `tools/firmware/km_link/`：

| 半边 | 落点 |
|---|---|
| 客户端打包 | `rm_client/backend/protocol.py` `encode_km_control_payload()`（PRM1 kind=3，26 字节） |
| 客户端发送 | `manager.publish_km_control()` / `publish_km_release()`；`control.KeyboardControlBridge.radio_km_enabled`（**默认关**） |
| 急停 | `trigger_estop()` 里同帧发零键位 CustomControl，不等固件 300ms 超时 |
| 固件收包 | `referee.c` 原有 0x0311 case 基础上补到达时刻/计数（`apply_km_link.py`） |
| 固件仲裁 | `remote_control.c` 的 `HostKmLinkUpdate()` + `HostKmApplyDriverFrameMouse()`，五档 `__CONTROL_LINK_KM` |
| 键位合流 | `host_chassis_bridge.h` 的 `key.v = (驾驶员 & 门闸) \| 0x5A \| 图传`（三本账） |

验证：五档各编一遍真实 ARMCC 5.06（**162 单元 / 0 失败**，工程是"警告即错误"）；
行为测试喂的是**客户端真打出来的那 26 字节**，六组变体全过，`--negative`
退回朴素写法后六组全部被抓到；C 结构体与 Python 打包用 `offsetof` 逐字段对表。

仍然没验的两件事（都得靠硬件，写在客户端里骗不了人）：
① 车上 C 板到底收不收得到 0x0311（`huart1` 是 115200，而图传链路文档写 921600）；
② DT7 那条虚拟控制链路的 PC↔DT7 USB 报文格式与键位位序（第 3、4 节）。

---

## 8. 2026-09-04 第二轮：无线键鼠出口**在界面上能点了**

上一版留的坑（`tools/firmware/host_bridge/GAPS.md` 第 10 节第 1 条
"UI 点不到这个出口"）本轮补完，并拆掉一个会让现场误判的耦合。

| 改什么 | 落在哪 | 为什么 |
|---|---|---|
| 新增设置项 `Radio KM Egress`（默认关） | `rm_client/model.py` RobotLink 模块 | 界面能点、能存、进审计基线 |
| 生效判定 = `开关 && 非急停 && Allow Drive && 模块启用` | `rm_client/backend/manager.py` `tick_polar_link()` | 开关只是"意愿"，三道闸缺一不可；**刻意不要求 0x5A USB 链路活着** —— 这条出口的存在意义就是不插线控车，拿 USB 状态当闸门锁的是自己 |
| 出口与官方 KMC 解耦 | `rm_client/control.py` 新函数 `_send_radio_km()` | 以前它写在 `if self.mock_output: return` 之后、又要求 KMC 先成功；结果就是"开关勾上了、一帧都看不到"，现场分不清是没发还是被 mock 吞了。真决定上不上网络的是 `MqttBackend.publish_topic()` 的 mock 分支和 `safety.can_publish()` |
| 两个原因位分开 | `radio_km_last_error`（发了但被拒）/ `radio_km_gate_reason`（没让发） | 挤在一个字段里会互相覆盖，把排查方向指错 |
| 状态条加 `KM on/off` | `rm_client/ui/polar_app.py` 水印行 | 决定"插不插线车动不动"的东西必须脸上看得见。只放状态不放计数：计数每帧变，会打掉那块按 4Hz 采样的光栅缓存 |
| 改开关当场说还差什么 | `config_actions_mixin.after_setting_changed()` | 勾了开关但没给 Allow Drive / 没启用模块时直接 toast 出来 |
| DT7 只读旁听 `--listen` | `tools/dt7_link/dt7_vcp_probe.py` | 见 3.1 判定法 B：不发包就把位序与"这口是不是串口桥"一起判掉 |

测试（都进 `tools/verify_all.py`，本轮 39 组 GO）：

- `tools/dt7_link/test_radio_km_client.py` 新增：mock 模式下开关打开照样走出口、
  KMC 失败不拖累这条出口、失败原因不污染主通道 `last_error`；
  以及 `test_manager_gates()`：三道闸各缺一就不生效、急停一票否决、
  **不插 USB 线也能生效**、生效/关断时闸门原因该清就清。
- 新增 `tools/dt7_link/test_vcp_listen.py`：假串口喂字节，钉住空闲线分帧
  （不切半、不粘连、帧内小间隙不切帧）、按 Q 报 bit6 且同时打印手册位序的 SHIFT、
  非 18 字节流量不许硬解、以及"两套位序表必须仍差在 bit4-7"
  （哪天有人把表改成一样，判读就成了假绿）。