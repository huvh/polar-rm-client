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

## 3. 【已由厂商二进制结案，见第 19.1 节】曾经打架的两套键位位序：2016 手册是过时的，现役=固件那套

| 来源 | bit0-3 | **bit4** | **bit5** | **bit6** | **bit7** |
|---|---|---|---|---|---|
| A. DT7&DR16 遥控器手册 V1.0(2016) 第 7 页 + 附录示例代码 | W S A D | **Q** | **E** | **Shift** | **Ctrl** |
| B. 队内固件 `remote_control.h:103-118`（= 现在真正决定车怎么动的） | W S A D | **SHIFT** | **CTRL** | **Q** | **E** |
| B'. RM2026 通信协议 V1.3.x 的 `KeyboardMouseControl` 键盘位掩码 | W S A D | Shift | Ctrl | Q | E |

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

### 4.6 大疆给"电脑不插车也能无线开车"准备的正主：**图传接收端**（官方原话）

RoboMaster 裁判系统相机图传模块（接收端）VT13 产品页，原文照抄：

> "RoboMaster相机图传模块接收端无需安装，**可连接至电脑**，具有数据传输、图像输出等功能，
> 搭配RoboMaster赛事引擎选手端可以实现画面显示功能。**同时，接收端可作为遥控器发送遥控数据，
> 与发送端一一对应传输遥控数据。**"
>
> —— https://www.robomaster.com/zh-CN/products/components/detail/6136

这条比 DT7 的 USB 口重要得多：**"电脑插一个 USB 盒子就能当遥控器把数据无线送进车"是大疆现在明码标价卖的功能**，
而它的载体就是图传，不是 DT7。对照第 4.5 节 —— Shark 家客户端连的
`mqtt://192.168.12.1:3333`（192.168.12.x 就是图传网段）走的正是这条。

⇒ 所以"客户端无线控车"的正确问法不是"怎么让 DT7 听我的话"，
而是"**我的键鼠怎么进图传这条上行**"。这件事上一轮已经在代码里接完了
（0x0311 + PRM1 kind=3 + 车上 host_km_link），本轮补上了界面上那个开关（第 8 节）。
DT7 的 USB 协议要不要继续挖，取决于现场量出来"0x0311 到不到得了 C 板"；
到得了，DT7 那条就当备用方案，不再花时间。

还没查实、但会影响接法的两件事（记在这里当 TODO，别当已知）：
① 那个 3333 的 MQTT broker 到底跑在车上、接收端里、还是选手端本机；
② 接收端对 PC 暴露的是虚拟串口还是只被官方选手端占用、第三方能不能直接写。

## 5. 另一条不依赖 DT7 帧格式猜测的无线路（2026 赛季的正规路）

查 RM2026 通信协议 **V1.3.0（2026.03.26）**修改日志（现行最新是 V1.3.1/2026.05.19），写着
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
① 车上 C 板到底收不收得到 0x0311 —— 官方原文（2026 通信协议 表1-1 / 1.1 / 表1-5）
   写明 **0x0311 属"图传链路"，从图传发送端的串口进车，而那一档波特率是 921600**；
   我们固件的裁判口是 `huart6`@115200（上一版误写成 `huart1`，已在
   `tools/firmware/host_bridge/GAPS.md` 第 10 节第 3 条更正并附原文行号），
   全仓也没有任何 921600 的 UART 配置。这条**必须在现场量一次**；
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

---

## 9. 联网调研收口（子代理 + 我本地逐条核原文）

派子代理把全网扫了一遍，回来我又把它引的每句原文在本地文本里逐条核过
（下载的官方件与提取文本在 `C:\Users\lulunomaro\AppData\Local\Temp\rm_research\`：
`rm2026_proto.txt` / `rm2026_spec.txt` / `dt7_manual.txt` / `dt7proto.txt` /
`vt13.txt` / `referee.txt`）。四条结论：

### 9.1 你下载的那个 `RC_System_Installer_v1.2.zip` **就是 DT7 唯一的官方调参软件**

第 4.3 节我判它"是 Phantom 2 的调参软件，跟 DT7 无关"——**前半句对、后半句错**。
DJI 官网 DT7/DR16 的下载条目就叫
`DT7 / DR16 Assistant Software 调参软件`，页面标 **已停止更新**
（https://www.dji.com/cn/downloads/softwares/assistant-dt7-dr16-rc-system），
文件名 `RC_System_Installer_v1.2.exe/.zip/.dmg`；RM 官网 DT7&DR16 产品页
（https://www.robomaster.com/zh-CN/products/components/detail/122）
给的"RoboMaster 遥控器调参软件"链接是
`https://rm-static.djicdn.com/tem/RC_System_Installer_v1.2.zip`，
与 `dl.djicdn.com/downloads/dt7/RC_System_Installer_v1.2.zip` **MD5 一致
（875F99B7DE00568BF373BD31DEDDEBB2）**。
也就是说：大疆给 DT7 的"官方 PC 软件"= 那个老 Phantom/Naza 壳子，
二进制里 `DT7` 只出现 1 次、`DR16` 0 次。所以第 4.3 节从它身上挖到的
"纯串口 + 命令式帧"仍然是**能指望的形态参考**，但它本身不支持 DT7 这一点没变。

### 9.2 那份社区《遥控器控制协议 V1.4》里有一条必须记住的官方警告

`dt7proto.txt` 第 1 页原文照抄：

> "特别注意：1：**仅仅装 DT7 驱动软件，不要安装 DT7&DR16 调参软件**
> 2：RoboMasters 提供的遥控系统是 DJI 特别定制的，**不要随意升级遥控器固件，
> 否则会造成遥控器无法使用**"
> "本文**重点介绍图中的蓝色单向 DBUS 控制帧**"

⇒ 两件事：① 那份被广泛引用的"DT7 协议"文档从头到尾**只讲接收机→MCU 单向**，
键鼠上行一个字节都没写；② 现场**不要拿那个调参软件去升级 DT7 固件**，
比赛定制版刷坏了遥控器就没得用了。这条比协议本身更值钱，已抄进 §10 注意事项。

### 9.3 PC↔DT7 上行帧格式：全网确认**零公开、零开源实现**

GitHub（repo/code search：DT7、dji dbus、robomaster client、HT-01AX、robowalker_train）
与中英文网页都扫过，能找到的 DT7/DR16 相关实现**全是接收端解码**：
`garfield38/DJI_DBUS`、`PurdueRM/arduino_DBUS_decoder`、`yssickjgd/robowalker_train`。
**没有任何一处 PC→DT7 串口的编码。** 想自己走这条路只剩一件事可做：
拿 USBPcap/Wireshark 抓"官方客户端 ↔ DT7"的 CDC 包逆向那层帧
（成本低，因为它是标准 usbser.sys CDC），但这是逆向不是接口，
大疆一升级/检录口径一变就得重来。

### 9.4 "电脑不插车也能无线开车"的正路，官方 2026 说法已经写全了

- 图传接收端对 PC 是**网卡不是串口**：官方《裁判系统用户手册》升级步骤原文
  "打开PC的设备管理器，展开**网络适配器**子菜单，检查是否有
  '**Remote NDIS based Internet Sharing Device**'设备"。
- VT13 说明书原文："与发送端对频连接后，**接收端可作为遥控器发送遥控数据**。
  将接收端连接至电脑，打开 **RoboMaster Client** 软件并登录对应机器人后，
  开放的键鼠数据……也会通过接收端发送" —— 注意它要求**经过官方客户端**，
  PC 直接往接收端写遥控数据的第三方接口：**查不到**。
- broker 在哪：《2026 制作规范手册》2.1.9 "自定义客户端……用于接收裁判系统
  **赛事引擎服务器**发送的比赛相关信息与机器人图传画面，并向**赛事引擎服务器**
  发送赛事专用交互指令"；通信协议 §2 "服务器IP地址为固定IP：
  **192.168.12.1，端口：3333**。自定义客户端IP地址为192.168.12.2"。
  ⇒ **MQTT 服务器在裁判系统的赛事引擎上（操作间 RJ45 接入），不在车上、也不在接收端里**；
  我们客户端默认连 `127.0.0.1:3333`，那台机器上必须有转发/或者就该把 host 填成 192.168.12.1。

⇒ 综合 9.3 与 9.4：**接下来该做的不是继续挖 DT7，而是把 0x0311 这条图传链路
在现场量通**（`HOST_KM_RX_COUNT` 涨不涨，判法与两种结果见
`tools/firmware/host_bridge/GAPS.md` 第 10 节第 3 条）。
DT7 那条保留为"抓包才可能推进"的备用方案，工具（含本轮新增的零风险旁听）都还在。

---

## 10. 2026-09-04 第三轮补充：大疆官网上"自定义客户端"这件事到底是什么

电控说"用大疆的自定义客户端连接 DT7 就能直接控制"。去官网核完，结论是
**他说的软件存在、功能也没错，但那个软件不叫"自定义客户端"** —— 名字混了，
而混的这个名字在规则里恰好指"队伍自己做的东西"。三句官方原文就能把事说清：

### 10.1 官网上能下载的是"赛事引擎**选手端**软件"（RoboMasterClient）

产品页：https://www.robomaster.com/zh-CN/products/components/detail/6145
（标题 "RoboMaster 2025 机甲大师超级对抗赛赛事引擎"，描述
"包括赛事服务器、裁判端与选手（操作）端"）。它的"相关下载"里：

| 条目 | 文件 |
|---|---|
| 赛事引擎裁判端（含服务器）软件 | `…/tem/70482/RoboMasterEngine 11.0.0.210(Student).7z` |
| **赛事引擎选手端软件** | `…/tem/70482/RoboMasterClient 11.0.1.128.7z`（475,526,295 字节） |
| 选手端界面说明手册 | `…/tem/70482/RoboMaster 2025 …选手端界面说明手册-学生版（202507）.pdf` |
| 联网操作手册 | `…/tem/70482/RoboMaster赛事引擎联网操作手册.pdf` |

⇒ **"大疆的客户端" = RoboMasterClient（选手端）**。发布的历史版本线到 11.0.1.128。

### 10.2 "自定义客户端"在规则里 = 队伍自制，大疆不发这个软件

《RoboMaster 2026 机甲大师高校系列赛 制作规范手册》2.1.9 原文：

> "自定义客户端是**参赛队伍自制**的一套多用途设备，用于接收裁判系统赛事引擎服务器
>  发送的比赛相关信息与机器人图传画面，并向赛事引擎服务器发送赛事专用交互指令。"（:582-583）
> "S56 自定义客户端仅可用于RMUC。" / "S62 自定义客户端不得使用无线发射/接收装置。"

⇒ 所以**不存在"大疆的自定义客户端"**；我们仓库 `rm_custom_client` 才是那个自定义客户端。

### 10.3 但"DT7 能传键鼠"是官方明文，而且**只有 DT7 能接选手端**

同一份规范里的两张表/两条注释（本地文本 `rm2026_spec.txt` 行号）：

> 表：`DT7遥控器 —— 键鼠指令、遥控器杆量信息`（:380）
>       `其他遥控器 —— 遥控器杆量信息`（:381）
>       `相机图传模块（接收端） —— 键鼠指令、遥控器杆量信息`（:382）
> "组委会**推荐**参赛队伍使用图传链路或相机图传模块（接收端）控制机器人。"（:390）
> "相机图传模块（接收端）本身具有遥控数据发送功能（**搭配选手端可同时发送键鼠数据**），
>  可替代DT7遥控器。"（:392-394）
> "S18 ……**仅DT7遥控器可以接入选手端**。"（:401）

⇒ 电控的记忆完全对得上：**DT7 插到跑官方选手端的那台电脑上，键鼠和杆量就能进车**
（这条正是第 1 节手册画的"虚拟控制链路"，官方实现就在选手端里）。

### 10.4 更要紧的一条：键鼠来源**二选一**，这是规则级互锁

《2026 通信协议》2.2.1 KeyboardMouseControl 原文（本地文本 `rm2026_proto.txt`）：

> "该数据将通过**相机图传模块（接收端）**发送给机器人。实际比赛时，操作手需提前
>  选择**键鼠控制指令来源为官方选手端或自定义客户端**，同时**仅能通过一个来源**
>  生成发送给机器人的键鼠指令。"（:1732-1735）
> 表 2-1：`KeyboardMouseControl 自定义客户端→图传链路→机器人 75Hz`（:1559）
> 表 2-1：`CustomControl 自定义客户端→图传链路→机器人 最大30字节 75Hz`（:1564）

⇒ 三条直接影响我们的决定：
1. **我们的客户端发 KMC 不是白发的**，它是 2026 明文支持的键鼠通道；
   但前提是**键鼠来源要被切到"自定义客户端"**，否则车上的键鼠来自官方选手端，
   我们发的一路会被丢掉。这件事界面里必须显式提示，不能靠记忆。
2. KMC 与 CustomControl(0x0311) **同属图传链路**，所以第 9 节那条"必须从图传
   发送端串口(921600)进车"对**两条通道同时成立** —— 不是我们 km_link 独有的毛病，
   官方通道也一样。**这就把"要不要继续挖 DT7"这个问题变小了**：
   真正要解决的是"车上有谁在听那一路 921600"。
3. 图传接收端能替代 DT7（且组委会只保证操作间那台接收端稳定）——
   这是官方推荐路，DT7 + 官方选手端 反而是"组委会不保障稳定性"的那条。

### 10.5 附录三：官方给的自定义客户端示例代码就在协议里

《2026 通信协议》附录三"自定义客户端示例通信代码"是 **Unity/C# + MQTTnet**：

> `public MyMqttClient(string clientID, string ip = "127.0.0.1", int port = 3333)`
> `Subscribe("KeyboardMouseControl"); Subscribe("CustomControl");`（:2823-2905）
> 正文 §2："示例代码，详见附录三，其中 MyMqttClient 的 clientID 需填入所连接…"（:1545）
> 正文："服务器IP地址为固定IP：**192.168.12.1，端口：3333**。自定义客户端IP地址为192.168.12.2。"（:1539）

⇒ 默认值是 `127.0.0.1:3333`，说明**官方客户端（选手端）进程里就带着这个 broker**；
正式比赛时自定义客户端连的是**赛事引擎服务器** `192.168.12.1:3333`。
我们客户端默认连 `127.0.0.1:3333`（`configs/default.json`、
`rm_client/backend/mqtt_backend.py:31-32`），**语义上等于"和官方选手端在同一台机器上、
接它的 broker"** —— 现场要按赛事引擎口径改成 192.168.12.1，
或者本机跑官方选手端当中转。这一点以前从没写进任何文档，很容易在检录当天才被发现。

### 10.6 本轮下载件（只解包分析，**不运行**）

- `D:\rmbuild\rmclient\RoboMasterClient.7z` —— 官方选手端 475MB。
  价值：PC↔DT7 那套上行报文**只有它实现了**。要做 DT7 注入，正路是
  在这个包里找那段代码/配置（或用它配合 USBPcap 抓一次包），
  而不是继续猜 18 字节 DBUS。

---

## 11. 把大疆官方选手端扒开看了一眼：PC↔DT7 那段代码到底在哪

下载件：`RoboMasterClient 11.0.1.128.7z`（475,526,295 字节，
`https://rm-static.djicdn.com/tem/70482/RoboMasterClient 11.0.1.128.7z`）。
**只用 py7zr 解包读文本，没有运行任何 exe。**
解出来的分析件在 `D:\rmbuild\rmclient\x\`（小文件）与 `D:\rmbuild\rmclient\x2\`。

### 11.1 选手端里有一个**专门跟遥控器说话子进程**

`RoboMasterClient_Data\StreamingAssets\Tools\RMClientDaemon\` 下面有四个 assist 子进程，
其中跟这次问题直接相关的是 `RMClientAssist_RemoteSerialPort.{exe,dll,pdb}`。
它自带的**真实运行日志**（包里就带着 2025-07-07 那次运行的日志）开头三行：

```
[Log] [07-07 20:28:55:593] [Game] rc Serial Port Start
[Log] [07-07 20:28:55:619] [Game] RCSerialPortThread线程ID：66936
[Log] [07-07 20:28:55:635] [Game] send a heartbeat to daemon
```

⇒ 官方实现里，"跟 DT7 通信"是**一个独立线程 + 一个独立子进程**，
跟它并列的还有 `video Serial Port Start` / `video 2025 Serial Port Start` /
`cc Serial Port Start`（cc = 自定义控制器）与 `RobotUDPThread`（图传 UDP）。
**电控说的"大疆客户端连 DT7 就能控车"，在这一层是被证实的：官方客户端确实有 RC 口线程。**

### 11.2 PDB 泄露的符号名，直接给出这条链路的形状

`RMClientAssist_RemoteSerialPort.pdb` 里的源文件名（PDB 原文，路径就是大疆内部工程路径）：

```
...\RMClientAssist\Framework\RC150.cs
...\RMClientAssist\Framework\RC150USBThread.cs
...\RMClientAssist\Framework\RCSerialThread.cs
...\RMClientAssist\Framework\CCSerialThread.cs
...\RMClientAssist\Framework\SerialPortThread.cs
...\RMClientAssist\Framework\CRCCheck.cs
...\RMClientAssist\Framework\ProtoManager.cs
```

同文件里的符号（挑相关的照抄）：

| 符号 | 说明 |
|---|---|
| `_pc2rc` / `_rc2pc` | ~~"两个方向各一条通道"~~ **这条我读错了，11.5 已更正**：\n |  |
| `SerialPortDataSpeed{tc2pc,pc2tc,ccs2pc,pc2ccs,rc2pc,pc2rc,ccs2pc_error}` | 同名字段在 `DataManager`/`SerialPortDataSpeed` 里成对出现 —— 它们是**每条链路两个方向的速率计数**，不是数据通道 |
| `OpenUSBPort` / `CloseUSBPort` / `CheckUSBPort` / `GetUSBConnenctStatus` | 遥控器这侧是**按 USB 口**管的（不是只当 COM 口用） |
| `RC150USBThread` / `RCSerialThread` / `RCSerialLoop` / `OnRCSerialData` | USB 线程 + 串口线程**两套并存** |
| `ULibUsbDotNet` / `ULibUsbDotNet.Main` + 同目录 `LibUsbDotNet.LibUsbDotNet.dll` | 用的是 **LibUsbDotNet（WinUSB/libusb 托管封装）** |
| `DJI_PRO_CMD_T` / `DJI_PRO_CMD_TYPE_T` / `cmd_id` / `GetCMDID` | 有个 DJI 命令码枚举（"pro cmd"） |
| `GetCRC8` / `GetCRC16` / `CRCCheck_StudentSerialPort` / `CRCCheck_VideoSerialPort` | 帧带 CRC8/CRC16，两种口校验不同 |
| `SearchHeader` / `SearchPackage` / `FrameHeader` / `FrameTail` | 有头有尾的包结构 |
| `CMD_ID_QUERY_PairingStatus` / `CMD_ID_REQUEST_IFRAME` / `CMD_ID_SEND_CUSTOM_DATA` | 实际命令码名字（配对状态查询、请求 I 帧、发送自定义数据） |
| `SendData` / `bysend` / `SendSerialPortDataSpeed` / `SerialPortDataSpeed` | 发送侧还带速率控制 |

注意两点边界，别把这份表读过头：
1. **`RC150.dll` 不是遥控器驱动** —— 它的导出是 `RC150Init/RC150Release/
   RegisterRequestIFrame/RegisterRequestCancelIFrame`，导入全是 `avcodec_*`，
   是**图传视频解码**那块（RC150 是大疆内部代号，和"遥控器"撞名而已）。
   遥控器那侧的代码在**托管程序集** `RMClientAssist_RemoteSerialPort.dll` 里。
2. **`_pc2rc` 的字节布局还是没拿到** —— 它在 IL 里，得反编译那个托管 dll
   （`dnfile`/ilspy 都行，dll 只有 101,376 字节，方法很小）才能读出来。
   这一步是"要不要继续做 DT7"的关键分叉点，成本比之前估计的低得多。

### 11.3 这条发现把结论改成了什么

- **如果只是想"电脑上按键盘就让车动"**：完全不用自己实现 `_pc2rc` ——
  跑官方选手端，它已经把键鼠经 `_pc2rc` 灌进 DT7 了；
  我们的自定义客户端要做的是**把键鼠发到它身边那个 MQTT（`127.0.0.1:3333`）**，
  并把"键鼠控制指令来源"选成自定义客户端（2.2.1 明文：来源只能一个）。
- **如果想彻底不依赖官方选手端**：反编译官方实现里那段发送代码就行，代码就在我们手上
  （比"盲猜 18 字节 DBUS"靠谱得多）。
  ⚠️ 本小节第一版曾据 `LibUsbDotNet` 猜"DT7 那侧可能走 WinUSB、第 4.1 节的
  'pyserial 直接写 COM 口'要降级"—— **那个猜是错的，11.4 已把它否掉**：
  用 LibUsbDotNet 的是 `RC150*`（图传接收端视频），遥控器那侧是
  `RCSerialThread` + `DeviceInfo.GetDjiSerialPort`，**仍是串口**，
  所以第 4.1 节的结论不变。

### 11.4 用 dnfile 把托管程序集的元数据剥出来：遥控器和图传是**两个不同的东西**

`RMClientAssist_RemoteSerialPort.dll`（101,376 字节）里 163 个类型的成员表（下面全是大疆自己的命名，逐条来自元数据）：

| 类型 | 成员（原样照抄） | 到底是谁 |
|---|---|---|
| `DeviceInfo` | `GetDjiSerialPort` / `GetCCSSerialPort` / `GetVideoSerialPort` / `GetNewVideoSerialPort` | **找串口**的助手：DJI口=遥控器、CCS=自定义控制器、Video=图传，**三种口并列** |
| `RCSerialThread` | `WorkerProc` `OnRCSerialData` `SendSerialPortDataSpeed` `sum` `avag` `count` `isSent` `m_synTime` | **遥控器（DT7）就是走串口** —— 与第 4.1 节"pyserial 就能写"的推断一致 |
| `RC150` | `RC150Init` `StartDecodeThread` `OnRecvVideoStream` `RegisterRequestIFrame` | **RC150 是图传接收端（视频）代号，不是遥控器**（11.2 里那句提醒仍然成立，且比先前更确定：方法全是解码/I帧） |
| `RC150USBThread` | `VendorId` `ProductId` `usbDevice` `reader` `ReadThreadProc` `IsTCVideoDecode` | 图传接收端在 PC 上是 **libusb( LibUsbDotNet ) 视频设备**；上一版我据此猜"DT7 可能也是 WinUSB"——**这个猜测作废**，DT7 那侧是 `RCSerialThread` 串口 |
| `T_HEADER` | `flag` `length` `seq_num` `robot` `receiver` `sender` **`cmd_Id`** `crc8` | **帧头**：有 sender/receiver 地址、有 seq、头带 crc8 |
| `T_TAIL` | `checkSum` | **帧尾**：整帧 crc16 |
| `T_V1_HEADER` | `sof` `crc8` `sender` `receiver` `seqnum` `cmd_type` `cmd_set_id` | 另一版（V1）帧头，`sof` + `cmd_set/cmd_id` 两段式 |
| `DJI_PRO_CMD_T` | `Cmd_Set` + `Cmd_Id`（位域） | **命令码 = (命令集, 命令号) 两段** |
| `DJI_PRO_CMD_TYPE_T` | `Encrypt_Type` `Reserve` `Cmd_Ack` `Cmd_Type`（位域） | 帧类型/加密/ACK 标志 |
| `DJI_PRO_MOUDLE_T` | `Moudle_Type` + `Moudle_Id` | 模块地址（原文件里就拼错成 Moudle） |
| `FrameHeader`/`FrameTail` | `sof` `datalen` `seq` `crc8` / `crc16` | 又一层轻量帧 |
| `TCCustomControllerByteData` | `cmd` `controldate` | 自定义控制器字节包 |
| `RC_PAIRING_STATE` | `PAIRING_STATE_NORMAL/PAIRING/DONE` `NORMAL_STATE` `PAIRING_STATE` `LOST_STATE` `AMT_STATE` `ERROR_STATE` | 对频状态机（**"配对"这件事大疆自己也在管**） |
| `SET_RC_PAIRING_ACK` / `RESTART_REQ` / `RESTART_ACK` / `SET_COUNTRY_CODE_REQ` / `COUNTRY_CODE_ACK` / `SET_FREEQ_ID_ACK` / `DUSS_MB_CMD_HDVT_SET_CONFIG__INFO{configuration_id,freq_id,camp_freq,freq}` / `..._INFO_CUSTOM_DATA{configuration_id,custom_data}` / **`DUSS_MB_CMD_HDVT_RACING_PUSH_CHANNEL_INFO{configuration_id,...}`** | | 一堆 DJI DUSS/MB 命令的**结构体名字都在这儿**，尤其最后那条 **`RACING_PUSH_CHANNEL_INFO`**：名字直译"竞速-推送通道信息"，是 PC 往遥控器里**塞通道数据**最像的一条 |

⇒ 结论形状：**PC↔DT7 = DJI 那套 (命令集,命令号) + sender/receiver + crc8/crc16 的命令式串口协议**，
不是"裸写 18 字节 DBUS"。这与第 4.3 节从 Phantom 调参软件里挖到的
`header/ackid/Command ID/Command Length(Exclude Head)/crc_16/result` **同一族**
（就是 `o-gs/dji-firmware-tools` 那套 DUPC 家族）。

### 11.5 还差的最后一厘米

命令号的**具体数值**不在这个程序集里（全 dll 扫下来编译期常量为 0 个，
说明它们要么是运行时从配置/表里取，要么在 Unity 那侧 `GameAssembly.dll` /
`RMClientDaemon.dll` 里）。

#### 11.5.1 我把这条路走到了尽头：**上行帧的组装不在 daemon 里**

接着挖的结果（`dnfile` 全表扫字段名，2026-09-04）：

- `RMClientAssist_RemoteSerialPort.dll` 里 **KeyValue / mouse / keyboard 一个字段都没有**
  （`PUSH_CHANNEL` 有，但 `DUSS_MB_CMD_HDVT_RACING_PUSH_CHANNEL_INFO` 的字段只有
  `configuration_id` 一个，载荷是后面变长段，名字里看不出来）。
- `DataManager` 的字段是 `CMD_ID_SEND_CUSTOM_DATA / CMD_ID_REQUEST_IFRAME /
  CMD_ID_QUERY_PairingStatus` + `tc2pc/pc2tc/ccs2pc/pc2ccs/**rc2pc/pc2rc**/ccs2pc_error`
  —— 后面这六个是 `SerialPortDataSpeed`（**每条链路两个方向的速率**）。
  ⇒ **11.2 里我把 `_pc2rc` 当成"我们要挖的那条数据通道"，读错了**：它只是计数器。
- 遥控器侧 `RCSerialThread` 只有 `sum/avag/count/isSent/m_synTime` 五个字段 +
  `SendSerialPortDataSpeed`，即它做的是**收发字节 + 统计速率**，
  不组装键鼠内容。
- 顺带挖到两个别的事实：`CCSerialThread` 有 `keybd_Times`、`control_Times`、
  `recvBytesCnt302`、`recvBytesCnt306` —— 自定义控制器那条 115200 串口上跑的是
  **0x0302 / 0x0306**；`ThreadType` 枚举把
  `RemoteControl / CustomController / VideoPort / Video2025Port / Video2025USBPort`
  分成五种口，与 11.4 的 `DeviceInfo` 四个找口函数对得上。
- `ProtoManager` 有 `GetPCHeaderLen / GetV3HeaderLen / GetBitValue / SetBitValue /
  GetBitValueFromUInt16 / FromUInt32 / StructToBytes / BytesToStruct`，
  `ProtoV3Header{flag,datalen,seqnum,robot,receiver,sender,protoid,crc8}` ——
  帧头是"struct + 位域"直接 marshalled，`CRCCheck` 三套（默认 / Student 口 / Video 口）
  各自带 `CRC8_INIT / CRC16_INIT / CRC8_TAB / CRC16_TAB`。

⇒ **结论改口**：键鼠→DT7 的**内容组装在 Unity 那侧**（`GameAssembly.dll`，IL2CPP，30MB，
没有符号），要在二进制里把它抠出来需要 il2cpp dumper 且成功率不可控。
**所以 DT7 这条路的唯一省力入口是抓一次包**（十分钟内能做完），
差分分析已经写成工具：`tools/dt7_link/dt7_frame_diff.py`
（合成样本断言在 `test_frame_diff.py`，含"样本不够时不许硬判位序"这一条），
现场步骤在 `FIELD_WIRELESS_RUNBOOK.md` 第 4b 节；B 路（图传 0x0311）的串口事实与三种可能性在同文件第 3b 节（本工程 .ioc 里只有 USART1/USART3/USART6，**没有第四路、也没有 921600**）。

原先列的"下一步 1/2/3"里，1 和 2 已经被这次扫描否掉：

1. ~~反编译 `RCSerialThread`~~ —— 做完发现它不组装键鼠（见上）；
2. ~~从程序集里找命令号数值~~ —— 编译期常量为 0 个，号在 Unity 侧；
3. **抓包**：DT7 插电脑 + 官方选手端 + USBPcap，把 OUT 包粘进
   `dt7_frame_diff.py`。这条仍然是唯一省力路。

**（2026-09-04 更新：这条已经不用走了 —— 第 14 节找到官方文档化的入口 0x0306「自定义控制器→选手端」，键鼠注入不需要逆向 DT7 的 USB。）**
当时那一步做完的收获是：确定目标协议是 DUPC 族（有开源参考）、走串口。
目标协议是 DUPC 族（有开源参考）、走串口（我们有 pyserial）、
命令结构体名字全在官方程序集里 —— 不再是"完全未知的私有 USB 协议"。

---

## 12. 车上回读通道：让"0x0311 到没到 C 板"在界面上直接看见

上一节把风险定成了"必须先在现场量一次"，但没解决**怎么量**。
原来只能靠人拿串口助手盯 `HOST_KM_RX_COUNT`，现场没人这么干。本轮把它做成回读：

| 侧 | 改动 |
|---|---|
| 固件 | `host_km_link.h` 加 `HOST_KM_DEBUG_UPLINK / _PERIOD_MS / _SLOT_RX(9) / _SLOT_KEY(0)`；`apply_km_link.py` 把 `HostKmLinkUpdate()` 拆成 `HostKmLinkArbitrate()` + `HostKmReportUplink()`，后者用现成的 0x5A Debug 段上报 `km_rx`（C 板实际收到的 0x0311 帧数）与 `km_key`（合并后的键位），**200ms 限流** |
| 客户端 | `control` 新增 `radio_km_robot_rx / radio_km_robot_key / radio_km_robot_rx_growing / radio_km_link_state / radio_km_link_note`；`manager.tick_polar_link()` 从 `bridge.debug_packages` 里算出实况状态 |
| 界面 | 水印那截从 `KM on/off` 升级成实况六态 |

六态就是把"现场会误判的几种情况"分开写死：

| 状态 | 脸上 | 含义与动作 |
|---|---|---|
| `off` | `KM off` | 没开开关 |
| `blocked` | `KM blocked` | 开了但闸门没过（看 `radio_km_gate_reason`） |
| `no-readback` | `KM on(?)` | 发是发了，**车上计数读不到**（USB 没插）→ 不能当"没收到"，插一下线就有答案 |
| `live` | `KM live↑N` | N 在涨 = 0x0311 真的进了 C 板，路是通的 |
| `silent` | `KM NO-RX!!` | 车上回了 0 帧 = **包根本没到 C 板**，去查图传发送端那一路串口（官方口径 921600） |
| `stalled` | `KM stall@N` | 收到过但不长了 = 链路中途断（对频/登录/图传掉了） |

为什么这个回读值得占固件的 debug 槽：客户端自己的 `radio_km_sent`
**只能自证发了多少**，说明不了链路；`silent` 与 `no-readback` 的区别
决定现场是去改接线还是去改 MQTT 设置 —— 搞混一次就是一晚上。

测试：`tools/firmware/km_link/test_km_link.py` 加了 I 段（喂真帧 + 推 tick，
断言 `km_rx` 等于计数、`km_key` 等于合并键位、**未到 200ms 不得重写**），
并在 Python 侧守卫"回读名字 ≤9 字符"（`usb_task.c:1414` 只抄 10 字节，
超长会被静默截断）与"槽位不撞车"；五档 + fire-keys 六组全过，
`--negative` 仍能全部抓到。客户端侧 `test_manager_gates()` 覆盖六态迁移。

---

## 13. 第二条来源接口 `HostKmFeed()`：包不在裁判口上时怎么救

第 12 节的回读把问题分成了两种，这两种的处理方式完全不同：
`KM live↑N` 什么都不用做；`KM NO-RX!!` 说明**包没从 huart6 进来**。
后者的正确修法不是改仲裁，而是"把真正带着图传链路的那一路串口接进来"。
为此本轮把收件箱的写入做成了公开接口：

```c
/* tools/firmware/km_link/host_km_link.h */
void HostKmFeed(const uint8_t *payload, uint16_t len);
```

- 语义与 `referee.c` 收到 0x0311 那一刻**完全一致**：写收件箱 + 记到达时刻 + 计数；
  新鲜度门控、五档仲裁、键位掩码、回读上行全部照旧生效。
- 越界自护：`len` 大于收件箱就截到收件箱大小；空指针/零长直接返回。
- 于是现场接线变成一句话：**哪一路串口收到了 0x0311 的 30 字节载荷，就把它喂给
  `HostKmFeed()`**，不用碰任何逻辑。

测试（`tools/firmware/km_link/test_km_link.py` 的 I0 段）刻意**不用**直接写收件箱的
`put_bytes()`，全部改走 `HostKmFeed()`：断言计数增长、vt/vt_rc/rc_vt 档键位与鼠标
能落地、rc/none 档同样被忽略；再喂一帧 64 字节全零（越过收件箱边界）与一次空指针，
断言"没有 magic 的垃圾不得接管键位""空指针不得改变任何账"。
期间修掉一个我自己写错的断言：喂完不重新仲裁就去读 `key.v`，看到的当然还是上一轮的账。

`armcc_check` 真实工具链体检：**162 单元 0 失败**，partial 链接未定义符号 0 个；
完整链接只差授权（镜像 109,376 字节 > MDK-Lite 32KB 上限，L6050U）。

### 13.1 一键自检（把"要不要继续"变成 30 秒的决定）

`RobotLink → Run Wireless KM Selftest`：记 `km_rx` → 等 2.5s → 比 `km_rx` 涨没涨。
判据抽成纯函数 `rm_client/control.py::evaluate_radio_km_selftest()`（四态都有断言：
涨了=PASS；读不到回读=不通过；一帧没发出=客户端侧 FAIL；**发了但车上没涨=链路 FAIL**）。
自检不注入任何按键，所以车不会因为自检而动。

> 顺带把现场动作整理成一页纸：**`FIELD_WIRELESS_RUNBOOK.md`**（仓库根目录）。
> 三条路各自的状态、KM 六态对照表、`NO-RX!!` 的四级排查顺序、
> 十秒位序判定、以及"绝对不要做的事"（别拿调参软件刷 DT7 固件等）都在那页。

---

## 14. 电控那句话的真正答案：**官方给了一个文档化的键鼠注入口 0x0306**（已实现进客户端）

第 11 节我说"PC↔DT7 上行格式零公开、只能抓包"。**那个结论要修正一半**：
DT7 那条 USB 口上的报文确实零公开，但**我们根本不需要碰它** ——
大疆在《2026 通信协议》里公开了一条等价入口：**自定义控制器用串口把键鼠交给选手端，
由选手端去驱动 DT7 的键鼠字段**。三份原文：

> **表 1-1 波特率**：`电源管理模块←→机器人 115200` / **`自定义控制器←→选手端 115200`** /
> `图传发送端←→机器人 921600`                                    （rm2026_proto.txt :92-94）
> **1.5 非链路数据说明**：**"操作手可使用自定义控制器模拟键鼠操作选手端。"**（:1372）
> **表 1-43 命令码 0x0306**（8 字节，自定义控制器→选手端）（:1373-1398）：
> `0 2 bit0-7 按键1键值 / bit8-15 按键2键值`（"使用通用键值，支持 2 键无冲"）
> `2 2 bit0-11 鼠标X像素 / bit12-15 鼠标左键状态`（"位置信息使用绝对像素点值，赛事客户端 1920×1080，左上角 (0,0)"）
> `4 2 bit0-11 鼠标Y像素 / bit12-15 鼠标右键状态`
> `6 2 保留位`
> 另两句要紧的：**"仅响应选手端开放的按键"**、"若无新的按键信息，将保持上一帧数据的按下状态"。

官方选手端内部也在同一件事上留了证据（`global-metadata.dat` / 元数据与日志）：

- 类型与函数：`CCSPortThread`、`CCSPortManager`、`GetCCSSerialPort`、
  **`Keybd_event`、`Mouse_event`、`SetCursorPos`、`virtualKey`** —— 收到 0x0306 后
  选手端把它**变成系统键鼠事件**，再由它自己灌进 DT7。
- 打包好的日志原文（选手端自带那次运行的实时日志）：
  `[Game] 收到0306数据包`、
  `0306数据为KeyValue1:{1},KeyValue2:{2},x:{3},y:{4},LB:{5},RB:{6},reserved:{7}`、
  `自定义控制器0306收包长度不为8字节，丢弃！`、`自定义控制器0306收包超频，丢弃多余包！`、
  `Input_Device_RC Sent x:{1}, y:{2}, z:{3}, LB:{4}, RB:{5}, KeyValue:{6}, SerialPortIsConnected:{7}`

⇒ **所以"电脑连 DT7 就能开车"是真的，而且不需要我们逆向任何东西**：
我们要做的是**扮演自定义控制器**，往选手端那个 115200 串口发 0xA5 帧 + 0x0306。
这条**完全不经过车上的图传 921600 串口**，所以第 10/12 节那个"0x0311 到不到 C 板"的风险
对它不存在 —— 这是目前唯一一条"电控熟悉、官方文档化、且不依赖车上接线"的无线控车路。

### 14.1 已实现的代码

| 位置 | 内容 |
|---|---|
| `rm_client/backend/cc_link.py` | 新模块：`encode_cc_frame()`（0xA5 + len(2,LE) + seq + CRC8 + cmd_id(2,LE) + data + CRC16(2,LE)）、`encode_keymouse_0306()`（表 1-43 逐字段）、`keys_to_two_usages()`（2 键无冲 + 被挤掉的键**报出来**）、`VirtualCursor`（增量→绝对像素，夹在 1920×1080 内）、`CustomControllerLink`（默认 mock、限流 30Hz、`release_all()` 归零）；文件头把三份原文引用与帧算术推导都写进注释 |
| `rm_client/control.py` | 桥新增 `cc_link / cc_enabled / cc_sent / cc_dropped_keys / cc_last_error / cc_key_mask` + `_send_custom_controller()` + `release_custom_controller()`；与 KMC / 0x0311 一样是**独立出口**，不污染 `last_error` |
| `rm_client/model.py` | `RobotLink` 新增 `Custom Controller Egress`（默认关）、`CC Port`、`CC Hz`（默认 30=官方上限）、`CC Mock Writes`（**默认 True**，没确认选手端挑口规则前绝不写真实串口） |
| `rm_client/backend/manager.py` | 三道闸（非急停 / 模块启用 / Allow Drive）+ 掩码跟 `Allow Spin Key`（默认只放 W/S/A/D=0x0F，开了才 0x1F）+ 急停时先 `release` 再写原因（顺序有注释，反了会把原因抹掉） |
| 界面 | 水印那行加 `CC on/off`；改开关的 toast 继续提醒"键鼠来源只能一个" |
| `tools/dt7_link/cc_probe.py` | 命令行版：`--sweep` 看字节、`--port COMx --keys W --confirm-move-car` 逐键对表；不给 confirm 就一字节都不写，发完自动补全零帧（dry-run 打印的帧还会自过一遍校验） |

### 14.2 验证强度

`tools/dt7_link/test_cc_link.py`（已挂进 `verify_all`）里最关键的一条不是"自己跟自己对表"，
而是**把队内固件里那份官方 CRC 实现（`components/support/CRC8_CRC16.c` 的表与函数）
原样抽出来编成 exe，让它验收 Python 拼的每一帧**：CRC8/CRC16 都必须通过，
改一个字节、改长度域都必须被拒。理由：帧格式细节一旦错，选手端整帧丢弃，
现象是"我明明发了车不动"，属于最难查的一类。
其余断言：`data_length` 只算 cmd_id 之后的载荷（推导自 `referee_usart_task.c:124-169`
与 `protocol.h:14` 的 `REF_HEADER_CRC_CMDID_LEN=9`）、0x0306 逐字段位序与 12bit 边界、
2 键无冲必须报出被挤掉的键、越界坐标报错不静默截断、限流/seq 回绕/松手归零、
桥侧只转发掩码内槽位（Q/E 挡住）、出口异常不污染主通道、manager 三道闸与急停顺序。

### 14.3 还没验的三件事（都得靠现场，客户端里骗不了人）

1. **选手端怎么挑"自定义控制器"串口**：`DeviceInfo.GetCCSSerialPort` 是按端口枚举还是按
   VID/PID 认官方盒子？决定我们能不能用 com0com 虚拟串口对，还是必须插一个真 USB-串口。
   → 现场一条命令就能试：把 `CC Port` 指过去、`CC Mock Writes` 关掉、按一下 W，
   看选手端日志有没有 `[Game] 收到0306数据包`。
2. **"通用键值"到底是哪张表**：文档只写"使用通用键值"，没附表。代码里按
   USB HID Usage Table（Page 0x07：`W=0x1A`、`A=0x04`、`SHIFT=0xE1`…）填，
   并且选手端还有一句"仅响应选手端开放的按键"（白名单）。
   → 必须一个键一个键按一遍确认，错一个就是"按了没反应"。
3. **0x0306 的频率上限**：文档没给数字，选手端只说"超频丢弃多余包"，
   所以这里保守取 0x0302 的 30Hz 并在设置里开放调节。


⇒ 针对第 2 条已经做了**不用改代码**的处理：键值表放在 `configs/cc_key_usage.json`
（默认按 USB HID Usage Page 0x07 填），`cc_link.load_key_usage()` 每次取表；现场用
`--sweep` 试出真值后直接改这个 JSON 即可。文件缺失、JSON 坏、值越界（>0xFF / 非整数）
**一律退回内置默认** —— 不允许出现「配错一张表，把 W/S/A/D 一起废掉」。
断言在 `tools/dt7_link/test_cc_link.py::test_key_table_file`。
---

## 15. 选手端"认哪个串口"不用再猜：答案在官方 `DeviceInfo.dll` 里

`RoboMasterClient_Data\StreamingAssets\Tools\RMClientDaemon\DeviceInfo.dll` 导出四个找口函数，
用 pefile 扫 `.text` 的 rip 相对引用，把每个函数实际引用的硬件 ID 串对出来（**不是猜的**）：

| 导出函数 | 函数里引用的匹配串 | 对应物理设备 |
|---|---|---|
| **`GetCCSSerialPort`** | **`FTDI`** | **自定义控制器口：只认 FTDI 芯片的 USB-串口** |
| `GetDjiSerialPort` | `VID_FFF0` + `PID_0008` | 遥控器 DT7 那条 DJI USB Virtual COM（与官方驱动 INF 一致） |
| `GetVideoSerialPort` | `VID_2CA3` + `PID_001F` + `MI_04` | 图传接收端（旧） |
| `GetNewVideoSerialPort` | `VID_2CA3` + `PID_1020` + `MI_02` | 图传接收端（新，RNDIS 那一面） |

顺带把 4.1 节那条"DT7 是不是虚拟串口"的疑问也钉牢了：`VID_FFF0&PID_0008`
在官方软件里就是 **DJI 遥控器**那条口，和 `dji_vcom_driver11.inf` 的 `Class=Ports` 对得上。

### 15.1 对现场的直接影响（省掉一次白跑）

1. **com0com 那种虚拟串口对不会被选手端认成自定义控制器** —— 它不按 COM 号找，
   按硬件 ID 里的 `FTDI` 找。所以"纯软件模拟自定义控制器"这条路走不通。
2. 但硬件成本几乎为零，接线是这样（**不需要 MCU、不需要写任何固件**）：

   ```
   选手端那台电脑  <-USB->  [FTDI 芯片的 USB-串口 A]
                                   |  TX / RX / GND 三根线交叉
   我们这侧（同一台或另一台）<-USB-> [第二个 USB-串口 B]  <- 客户端 cc_link 写这个口
   ```
   选手端独占 A 口做"接收"，我们的客户端往 B 口写 0x0306 帧，
   字节经交叉线进 A → 选手端 `收到0306数据包` → 它把键鼠塞进 DT7 → 空口 → DR16 → C 板。
3. **B 口随便什么芯片都行，A 口必须是 FTDI**（CH340/PL2303 放在选手端那侧不会被认）。
4. 判定不用拔线试：
   `python tools/dt7_link/cc_probe.py --list`
   会按同一套规则（`FTDI` / `FFF0:0008` / `2CA3:001F+MI_04` / `2CA3:1020+MI_02`）
   标出"选手端会认成什么"；`--check-port COM7` 单判一个口。
   本机现在跑的结果是"只有 COM1、没有任何 FTDI 口"，与注册表里
   `VID_FFF0` 零命中一致 —— 这台电脑既没插过 DT7 也没插过 FTDI，
   所以 0x0306 这条**只能到有线下环境实测验**，本机测不了，我不假装测过。

### 15.2 现在整条链的状态

| 环节 | 证据 | 状态 |
|---|---|---|
| 我们 → 0x0306 帧 | `cc_link.py` + `test_cc_link.py`（帧被固件那份官方 CRC 代码验收） | 代码 + 离线测试完成 |
| 帧能被选手端收下 | `GetCCSSerialPort` 认 FTDI；日志有"收到0306数据包" | **待现场插 FTDI 验** |
| 选手端 → DT7 空口 | 元数据 `Keybd_event/Mouse_event/SetCursorPos` + 日志 `Input_Device_RC Sent ...` | 官方实现自带，我们不用做 |
| DT7 → DR16 → C 板 | 固件 `remote_control.c` 的 `sbus_to_rc` 已在收键位/鼠标 | 现役在用 |
| 键位进底盘/云台 | `rc_ctrl.key.v` / `mouse` 被 `chassis_omni.c`、`shoot_fric_trigger.c` 消费 | 现役在用 |

---

## 16. 12.x 官方包（`RoboMasterEngine 12.0.0.137_Student.zip`）核完：这**不是选手端**，而且里面没有 MQTT

用户给的这个包按名字像是"官方客户端"，实测结构不是：

- 顶层是 `RoboMasterEngine.exe` + `RoboMasterEngine_Data\Managed\Assembly-CSharp.dll`（**Mono 后端**，可直接读元数据）
  + `StreamingAssets\RMServer\{Server, AdapterSvr, RMServerMap, RMServerLogClient}`（`RMServer.exe`、Redis、InfluxDB、Lua 配置）。
- ⇒ 它是**裁判端 + 赛事引擎服务器**，**不含选手端**（没有 `RoboMasterClient.exe`），
  因此**不含 `DeviceInfo.dll`** —— 第 15 节那套"选手端只认 FTDI"的匹配表在这个包里查不到，
  2026 版有没有变必须拿到**选手端 12.x 包**再核。

### 16.1 从这个包里确实挖到的新事实（读托管元数据，不是猜）

服务器/选手端之间的内部命令表 `StuComEventID`（枚举常量，Mono 的 Constant 表直读）：

| 成员 | 值 |
|---|---|
| `communication` | 769 = 0x0301 |
| **`CUSTOM_CONTROLLER_DATA`** | **770 = 0x0302** |
| `map_data` | 771 = 0x0303 |
| **`key_mouse_data`** | **772 = 0x0304** |
| `RADER_DATA_TO_CLIENT` | 773 = 0x0305 |

配套的载荷结构（都是 `ValueType`，字段顺序即打包顺序）：

```
ClientCustomControlData { robotid, datalen, data }
StuCustomControlData    { cmd, data }
ClientSendCMD           { cmd, target_pos_x, target_pos_y, target_pos_z, cmd_keyboard, target_robot_id }
S1ClientTransferRobotProto : S1ProtoBase { dataLen, data }   // Pack/UnPack/GetSize
```

⇒ 两件事值得记：
1. **键鼠在 12.x 的内部协议里是 0x0304（`key_mouse_data`），而裁判系统对机器人的 0x0304 已被 V1.3.0 删除**
   —— 两个 0x0304 不是一回事，别把"0x0304 被删了"误读成"键鼠通道没了"。
   客户端↔服务器之间键鼠一直在，走的正是 `ClientSendCMD.cmd_keyboard` 这类字段。
2. `ClientSendCMD` 里键鼠与"目标位置/目标机器人 id"在同一个包内 ——
   说明 12.x 把"客户端发的控制意图"统一按一条命令转发给机器人（`S1ClientTransferRobotProto`），
   与我在 5 节里说的"0x0311 30 字节内容由队伍自定"不冲突，但**我们的 0x0311 载荷能不能原样穿过去，
   要看选手端/网关这一层怎么转发**，这是下一节要拿选手端包核对的重点。

### 16.2 一个把假设纠正过来的发现：这套 12.x 服务器里**没有 MQTT**

对 `Assembly-CSharp.dll`、`RMServer.exe` 和 RMServer 目录下 167 个二进制统计
`mqtt/Mqtt/MQTT/WithTcpServer/MqttFactory/KeyboardMouseControl/192.168.12` 出现次数：

| 文件 | MQTT 相关串 | KeyboardMouseControl |
|---|---|---|
| `Assembly-CSharp.dll`（服务器 Unity 侧） | **0** | **0**（`CustomControl` 有 11 次，全是内部 S1 协议名） |
| `RMServer.exe` | **0** | **0** |
| RMServer 目录下全部 exe/dll | 只有 redis/cef 之类的噪声命中，无 MQTT 栈 | — |

服务器内部走的是 **Redis 发布订阅 + Google.Protobuf（`ToGateSvr_RedisPublish` 等）**。
⇒ 所以《通信协议》里"服务器IP 192.168.12.1:3333 / 自定义客户端 192.168.12.2"那个
**监听 3333 的进程不在这个服务器包里**，只能是**选手端那一侧**
（附录三示例默认 `127.0.0.1:3333` 也是同一结论：它连的是本机跑的官方客户端）。
这条对现场的直接影响：**B 路和 D 路都以"官方选手端在跑"为前提**，
我们的客户端不能指望"只连服务器就能发"。之前文档措辞里的"赛事引擎服务器"太含糊，
现在按二进制证据改成"选手端那一侧"。

### 16.3 还缺的一块（要用户帮忙拿）

要把 2026 版彻底钉死，需要 **选手端 12.x 包**（裁判端页面上的"赛事引擎选手端软件"，
11.x 对应文件是 `RoboMasterClient 11.0.1.128.7z`）。拿到后用同一套方法核三件事：
1. `DeviceInfo.dll` 的匹配表在 12.x 里还是不是 `FTDI` / `FFF0:0008` / `2CA3:001F+MI_04` / `2CA3:1020+MI_02`；
2. 选手端有没有 MQTT 栈、监听哪个端口、`KeyboardMouseControl`/`CustomControl` 的 protobuf 定义变没变；
3. 0x0306 的 8 字节布局与"仅响应选手端开放的按键"那份白名单（有没有可读的表）。

---

## 17. 12.x 选手端核完：三条全部落实（含大疆自己写的"必须装 FTDI 驱动"）

拿用户给的两个包（`RoboMasterClient 12.0.0.30_1v1_Student.7z` / `..._3v3_Student.7z`，
两者结构相同，只差 1v1/3v3 场景）核了 16.3 列的三件事。**只解包读文件，没运行任何 exe。**

### 17.1 Q1：匹配表 12.x 一字未变，而且大疆自己就把话说白了

12.x 的 `DeviceInfo.dll`（128,512 字节，比 11.x 的 112,128 大）导出
`GetCCSSerialPort / GetDjiSerialPort / GetNewVideoSerialPort / GetVideoSerialPort` **+ `IsSerialPortReady`（新增）**，
rip 相对引用归属结果与 11.x **完全一致**：

```
GetCCSSerialPort      <- FTDI
GetDjiSerialPort      <- VID_FFF0 + PID_0008
GetVideoSerialPort    <- VID_2CA3 + PID_001F + MI_04
GetNewVideoSerialPort <- VID_2CA3 + PID_1020 + MI_02
```

更硬的证据是包里的 `ReadMe.txt`，原文照抄：

> "3. **如需连接自定义控制器，必须安装专用驱动程序。**
>  路径为："选手端根目录\...\StreamingAssets\Tools\**Windows_CDM21228_Setup.exe**""

`CDM 2.12.28` 就是 **FTDI 的 VCP 驱动**。⇒ 第 15 节"选手端只认 FTDI"这条推断
现在有两个独立来源（二进制匹配表 + 大疆自己的 README），可以当事实用了。

### 17.2 Q2：**MQTT broker 就在选手端进程里**（我们客户端默认 127.0.0.1:3333 是对的）

12.x 的 `global-metadata.dat`（8,089,024 字节）里 `Mqtt` 出现 221 次、`MQTT` 60 次，
并且是**服务器侧**的类，不是客户端库：

```
MqttServer / MqttTcpServerListener / MqttServerKeepAliveMonitor / MqttClientSessionsManager
MqttRetainedMessagesManager / MqttPacketInspector / MqttFactory / ClientSubscribedTopic
MyMqttServer.StartMqttServer / StopMqttServer / GetMqttServerState
CustomClientThread / OnMqttSubProto / OnMqttPublishProto / SendRobotInputInitData
```

⇒ **选手端自己开着一个 MQTT broker，还专门有一条 `CustomClientThread` 处理自定义客户端。**
所以：客户端与选手端同机时 `127.0.0.1:3333` 就是正确默认值；
文档里"服务器 192.168.12.1:3333"读作"跑选手端那台机器"。
第 16.2 节那条纠正（12.x 服务器包里没有 MQTT）由此闭环：**B 路的对端是选手端，不是 RMServer**。

### 17.3 Q3：0x0306 的格式串在 12.x 里与 11.x 一字不差；按键白名单仍然没有可读表文件

12.x 元数据里逐字命中：

```
[{0}] 0306数据为KeyValue1:{1},KeyValue2:{2},x:{3},y:{4},LB:{5},RB:{6},reserved:{7}
[{0}] Input_Device_RC Sent x:{1}, y:{2}, z:{3}, LB:{4}, RB:{5}, KeyValue:{6}, SerialPortIsConnected:{7}
[{0}] 收到0306数据包 / 自定义控制器0306收包长度不为8字节，丢弃！ / 0306收包超频，丢弃多余包！
```

配套符号（同一段元数据里紧挨着）：`CCSPortThread`、`bvk`、`bScan`、`dwExtraInfo`、
**`Keybd_event`、`Mouse_event`、`SetCursorPos`、`GetCurrentThreadId`** ——
即 0x0306 落到 Win32 合成输入，再由选手端送进 DT7。
另外 `SerialPortDataSpeed{tc2pc,pc2tc,ccs2pc,pc2ccs,rc2pc,pc2rc,ccs2pc_error}` 与
`rcStatus/RCStatus` 也在 12.x 里，15.1 那条"pc2rc 只是速率计数"的更正继续成立。

**没找到的**：可读的按键白名单表。搜 `开放的按键`、`白名单` 在元数据里 0 命中
（协议文档里那句"仅响应选手端开放的按键"是行为描述，不附表）。
⇒ 结论不变但更精确了：**键值→是否被响应，只能现场逐键试**（`cc_probe.py --sweep` 就是干这个的）；
若非要提前拿到，唯一入口是解 IL2CPP 的 `fieldDefaultValues`（能做，但成本明显高于现场试 5 分钟）。

### 17.4 现场清单因此更短了

1. 选手端根目录跑 `Start.bat`（ReadMe 第 1 条），依赖 .NET 7 与 VC++ 运行库（第 2 条，包内自带安装包）；
2. **装 `Tools\Windows_CDM21228_Setup.exe`（FTDI 驱动）**，然后插 FTDI USB-串口当自定义控制器（第 3 条）；
3. 我们的客户端与选手端同机 → `MQTT host` 用默认 `127.0.0.1:3333` 即可；跨机才填选手端那台机器的 IP；
4. `cc_probe.py --list` 确认那个口被认成"自定义控制器（选手端会认）"，再 `--keys W --confirm-move-car`。

---

## 18. 12.x 与 11.x 的两处**版本差异**（会在现场决定成败）+ 一处必须诚实的边界

### 18.1 差异一：MQTT/自定义客户端这条能力是 12.x 才有的

同一套关键词在两个版本的 `global-metadata.dat` 里计数对比：

| 关键词 | 11.x 选手端（11.0.1.128，7,119,880B） | 12.x 选手端（12.0.0.30，8,089,024B） |
|---|---|---|
| `Mqtt` | **0** | **221** |
| `MQTT` | 0 | 60 |
| `CustomClientThread` | **0** | **4** |
| `CustomControl` | 9 | 9 |

⇒ **11.x 选手端里根本没有 MQTT 栈，也没有伺候自定义客户端的那条线程。**
所以"我们的客户端发 MQTT → 选手端/图传 → 车（0x0302/0x0311）"这条 B 路，
**前提是现场跑 12.x 选手端**；拿 11.x 去试必然连不上 3333，
而且现象跟"我们代码写错了"长得一模一样。这条已经写进 `FIELD_WIRELESS_RUNBOOK.md` 的前提里。

### 18.2 差异二：12.x 里能读到 DT7 上行的命令名与 16 个键位宏名

12.x 元数据的标识符里出现了一整套（11.x 的托管 assist 程序集里也有 `CMD_ID_*` 一族名字）：

```
CMD_ID_Keyboard, CMD_ID_SEND_CUSTOM_DATA, CMD_ID_RECV_CUSTOM_DATA,
CMD_ID_QUERY_PairingStatus, CMD_ID_QUERY_MODE / SELECT_MODE, CMD_ID_RESTART,
CMD_ID_SET_COUNTRY_CODE / QUERY_COUNTRY_CODE, CMD_ID_SET_FREQ_ID / QUERY_FREQ_ID,
CMD_ID_PUSH_CodecRate, CMD_ID_PUSH_Linkquality, CMD_ID_QueryPackageVersion,
CMD_ID_HEART_BEAT, CMD_ID_SET_DEVICE_TIME / QUERY_DEVICE_TIME
KeyBoardRC, KeyboardValue, RobotInput, Proto_RobotInput, SendRobotInput,
SendRCInputStatus, KEY_PRESSED_OFFSET_{W,S,A,D,SHIFT,CTRL,Q,E,R,F,G,Z,X,C,V,B}
```

⇒ 两件事被证实：
1. **PC→DT7 确实有一套官方命令表，键鼠是其中的 `CMD_ID_Keyboard`**（第 11 节我说"上行零公开"，
   准确说法应该是"零文档、但实现就在官方二进制里"）。
2. 官方客户端用的键名集合与我们固件 `remote_control.h:103-118` 的 16 个键**完全同一套**
   （W/S/A/D/SHIFT/CTRL/Q/E/R/F/G/Z/X/C/V/B）。

### 18.3 必须诚实的边界：这些**名字**证明不了**数值**

- 我上面列的 `KEY_PRESSED_OFFSET_*` 是按字符串**排序后**输出的，
  **不代表声明顺序**，所以它**不能**用来判 bit4 到底是 Q 还是 SHIFT ——
  第 3.1 节那个位序问题仍然只能靠现场（看摩擦轮还是小陀螺，或旁听 DT7 口）。
- `CMD_ID_Keyboard` 的**数值**也不在元数据的字符串堆里；IL2CPP 的常量值在
  `global-metadata.dat` v29 的 `fieldDefaultValues` + blob 区里，要正经解析头部数组才能取到
  （托管侧那三个 dll 我扫了常量表：`RMClientAssist_*.dll`/`RMClientDaemon.dll` 里
  没有任何 `CMD_ID_*`/`KEY_PRESSED_*` 常量，值在 Unity 的 IL2CPP 侧）。
  ⇒ 想拿到就是"解 IL2CPP 元数据"的活，成本明显高于现场逐键试 5 分钟，
     所以 `cc_probe.py --sweep` 仍然是推荐路径；**这条列为可选深挖项，不假装已经做完**。

---

## 19. 直接把 12.x 选手端反编译了（Il2CppDumper + ILSpy）——三条结案、一条剩下的未知

工具链（都装在 D 盘，没动 C 盘）：
`D:\rmbuild\dotnet`(.NET 8 SDK) + `D:\rmbuild\tools\ilspycmd.exe` + `D:\rmbuild\il2d\Il2CppDumper.exe`，
产物在 `D:\rmbuild\dump12\`（`dump.cs` 16MB、`il2cpp.h`、`script.json`、`DummyDll\`）
与 `D:\rmbuild\decomp\`（12.x 选手端托管程序集的反编译 C#）。
metadata 版本识别为 **29.1**，dummy dll 与 dump.cs 生成成功。

### 19.1 结案一：键位位序（第 3 节那个悬案）

`dump.cs` 里两处枚举逐字相同（`:136133-136148` 与 `:146776-146791`）：

```
KEY_PRESSED_OFFSET_W = 1, S = 2, A = 4, D = 8,
SHIFT = 16,  CTRL = 32,  Q = 64,  E = 128,
R = 256, F = 512, G = 1024, Z = 2048, X = 4096, C = 8192, V = 16384, B = 32768
```

⇒ **大疆现役客户端用的位序 = 我们固件 `remote_control.h:103-118` = 我们客户端 `KEYBOARD_BITS`**；
《DT7&DR16 遥控器手册 V1.0(2016)》第 7 页那套（Q4/E5/Shift6/Ctrl7）**是过时的**，
以后别再按它编包。连带背书：图传键鼠默认掩码 `0x1F` 就是 **W/S/A/D + SHIFT(小陀螺)**，不含 Q/E。
⇒ 已经变成代码里的回归守卫：`tools/dt7_link/dt7_dbus_frame.py::KEY_ORDER_VENDOR_2026`
（含 dump.cs 行号出处）+ `test_radio_km_client.py` 三条断言（等于厂商枚举 /
0x1F 语义 / "2016 那套必须仍与现役不同，否则守卫没意义"）。
⇒ 现场那"十秒位序判定"（3.1）从必做项降级为**可选复核**。

### 19.2 结案二：我们的 KMC protobuf 与官方 proto 逐字段一致

`dump.cs:152075+` 的 `CCP.RemoteControl`（`KeyboardMouseControl` 的 protobuf 消息）：

```
MouseX=1 int32, MouseY=2 int32, MouseZ=3 int32, LeftButtonDown=4 bool,
RightButtonDown=5 bool, KeyboardValue=6 uint32, MidButtonDown=7 bool, Data=8 bytes
```

对照 `rm_client/backend/protocol.py:603-620` 的 `encode_keyboard_mouse_control()`：
字段号 1..7 与类型**完全一致**（我们没发 field 8，那是可选的自定义 bytes）。
⇒ 之前这条只是"照文档写的"，现在有厂商编译产物背书。

### 19.3 结案三：帧格式与厂商编码器逐行一致

`D:\rmbuild\decomp\CommunicationCompiler.cs`（12.x 托管程序集反编译）里
`Encoder_A5_WithTail` 的实际逻辑：

```
sof = 165(0xA5)；datalen = payload.Length - 2；seq 自增；
crc8 = CRC8(header 前 4 字节) 写进 header 末位；
整帧 = header(5) + payload(cmd_id 2 + data n) + crc16(2)；
crc16 覆盖 header+payload；CRC8_INIT=0xFF、CRC16_INIT=0xFFFF，表驱动
```

⇒ 与我 `rm_client/backend/cc_link.py::encode_cc_frame` 的实现**同构**
（`datalen 只算 cmd_id 之后的载荷`这一点我原先是从
`referee_usart_task.c:124-169` + `REF_HEADER_CRC_CMDID_LEN=9` 反推的，现在厂商源码直接对上）。
CRC 表也确认是同一族（我们的 `rm_client/protocol.py:crc8/crc16` 已在
`test_cc_link.py` 里被固件那份官方 CRC 代码验收过）。

### 19.4 顺带发现：12.x 的键鼠还有第二条下行，**根本不经过 DT7**

`dump.cs:135479` 的 `Video2025MsgID` 是一张**带数值**的常量表：

```
CMD_ID_Keyboard = 17(0x11)   ← 键鼠
CMD_ID_SELECT_MODE = 57, QUERY_MODE = 33, QUERY_PairingStatus = 85,
SET_SetFreqNum = 197, PUSH_Linkquality = 117, PUSH_CodecRate = 54,
SET/QUERY_DEVICE_TIME = 74/75, QueryPackageVersion = 79
```

⇒ `CMD_ID_Keyboard` 属于**图传模块（Video2025）**的命令表 —— 也就是
"键鼠走图传接收端下发"（与制作规范 2.1.6 那句"接收端本身具有遥控数据发送功能、
可替代 DT7 遥控器"、以及第 17 节 `GetNewVideoSerialPort <- VID_2CA3+PID_1020+MI_02` 对上）。
这条在 2026 是**主推**路（组委会只保障操作间那台接收端稳定）。

### 19.5 剩下的唯一未知（而且不需要硬件）

DT7 那侧（`GetDjiSerialPort` = `VID_FFF0&PID_0008`）的命令号**不是 const**：
`dump.cs:131430-131437` 是

```
public static int CMD_ID_QUERY_COUNTRY_CODE; // 0x300   ← 0x300 是静态字段偏移，不是值
public static int CMD_ID_SET_COUNTRY_CODE;   // 0x304
... HEART_BEAT / RESTART / RECV_CUSTOM_DATA / SEND_CUSTOM_DATA
```

`static int`（非 const）的值由运行时 cctor 赋，**不在 dump.cs 里**。
⇒ 要拿到 DT7 的键鼠命令号与载荷结构，下一步是**反汇编那个 cctor**
（`script.json`/`il2cpp.h` 已给出 RVA，配 `capstone` 即可，工具链已就位、不需要硬件、不需要抓包）。
这条是"我们的客户端直接连 DT7 发"的最后一块，**已经比"只能现场抓包"近了一大步**。

---

## 20. 反编译工具链落点 + DT7 命令号的**确切下一步入口**（含地址）

### 20.1 工具与产物（都在 D 盘，没碰 C 盘）

| 东西 | 位置 |
|---|---|
| .NET 8 SDK (8.0.424) | `D:\rmbuild\dotnet`（用官方 `dotnet-install.ps1 -InstallDir` 装的） |
| ILSpy 命令行 | `D:\rmbuild\tools\ilspycmd.exe`（9.0.0.7889） |
| Il2CppDumper | `D:\rmbuild\il2d\Il2CppDumper.exe`（6.7.46） |
| 12.x 选手端 Unity 侧产物 | `D:\rmbuild\dump12\`：`dump.cs`(16MB)、`il2cpp.h`、`script.json`、`stringliteral.json`、`DummyDll\` |
| 12.x 选手端托管侧反编译 C# | `D:\rmbuild\decomp\`（`CommunicationCompiler.cs`、`RCSerialThread.cs`、`CCSerialThread.cs`、`ProtoManager.cs`、`CRCCheck*.cs`…） |

识别结果：`Metadata Version 29 → Change il2cpp version to 29.1`，
`CodeRegistration = 0x1817e87f0`，`MetadataRegistration = 0x181a49eb0`。

### 20.2 已经拿到 vs 还差什么（说清楚，别含糊）

**已拿到（厂商二进制里读出来的确定事实）**
- 帧编码器逻辑：`CommunicationCompiler.Encoder_A5_WithTail`（见 19.3），与我们实现同构；
- 键位位序：`KeyBoard` / `InputRecord.KeyBoardRC` 枚举值（见 19.1）；
- 键鼠 protobuf：`CCP.RemoteControl` 字段号（见 19.2）；
- 图传侧键鼠命令号：`Video2025MsgID.CMD_ID_Keyboard = 17`；
- 遥控器口/自定义控制器口/图传口的硬件 ID 匹配表（第 17 节）+ 大疆自己要求装 FTDI 驱动的原文。

**还差（DT7 那条 VCOM 的命令号与寻址）**
`dump.cs:131430-131437` 那一族 `CMD_ID_QUERY_COUNTRY_CODE … CMD_ID_SEND_CUSTOM_DATA` 是
`public static int`，**不是 const**；它们的 cctor（RVA `0x384000`，文件偏移 `0x382E00`）
反汇编出来是一串
```
lea rcx, [rip + <静态槽>]
call 0x1801d8ed0        ← “从元数据初始值搬到静态槽”的助手
```
⇒ **值不在代码段里，在 il2cpp v1 元数据的 `fieldDefaultValues` 表**
（表头指针就在上面的 `MetadataRegistration = 0x181a49eb0`，
`Il2CppMetadataRegistration.fieldDefaultValues / fieldDefaultValuesCount`
+ `Il2CppFieldDefaultValue{ TypeIndex, FieldIndex, ValueIndex }` → `values` blob）。

**所以下一步是纯离线活，不需要硬件、不需要抓包**：
1. 用 `script.json` 的 RVA→文件偏移映射，读 `0x181a49eb0` 处的
   `Il2CppMetadataRegistration`（v29.1 布局：三个 int32 计数 + 一串指针，
   顺序为 genericClasses/genericInsts/genericMethodTables/methodRefRanges/typeDefIndices/
   …/`fieldDefaultValues`/`fieldDefaultValuesCount`/…，以 `dump.cs` 里字段顺序自校验）；
2. 按 `TypeIndex/FieldIndex` 对上 `ProtoDef`（就是持有那族 `CMD_ID_*` 的类）；
3. `ValueIndex` 进 `values` blob 取 4 字节小端 → 命令号；
4. 同一张表还能顺手把 `special_ctrl`/`CtrlSet`/`DJI_PRO_MOUDLE_T` 的
   **sender/receiver 模块地址**（DUSS 寻址）一并定下来——这是发帧必需的另外一项。
风险：v29.1 的 registration 结构体字段顺序我是按 il2cpp 通行布局推的，
**必须用"解出来的数量与 dump.cs 里 static 字段个数吻合"自校验**，
对不上就停下重写，不能拿半对的结果去发帧。

### 20.3 与"抓包"的取舍（保留两条，不撤工具）

- 上面这条（解析 v1 元数据）是**离线、可全自动**的，但结构体布局要猜+自校验；
- 现场抓一次（DT7 插电脑 + 官方选手端 + USBPcap，见 `FIELD_WIRELESS_RUNBOOK.md` 4b）
  是**一次性拿到真报文**，`tools/dt7_link/dt7_frame_diff.py` 直接算字段与位序；
- 两条不冲突：抓到包可以**验证**元数据解出来的命令号，解出元数据可以**解释**包里的字段。
  在拿到交叉验证之前，`cc_link.py` 那套（0x0306 自定义控制器）仍是唯一已闭环可发的路。

---

## 21. DT7 直连出口已经写进客户端（`rm_client/backend/dt7_link.py`）——能证的都证了，剩两个候选值

### 21.1 这条与 `cc_link`（0x0306）的分工

| | `cc_link.py`（D 路） | `dt7_link.py`（C 路，本轮新增） |
|---|---|---|
| 谁把键鼠塞进 DT7 | **大疆官方选手端** | **我们自己的客户端** |
| 要不要跑官方选手端 | 要 | **不要** |
| 要什么硬件 | FTDI USB-串口 ×2 + 3 根线 | DT7 用数据线插电脑即可 |
| 命令号状态 | 0x0306 = 协议文档**明文** | **候选值**（见 21.3） |
| 鼠标语义 | **绝对像素** 1920×1080 | **增量**（DT7 mouse_x/y 本就是"移动速度"） |

⇒ 两条的鼠标**不能互相借用**；代码里各走各的字段，注释也写明了，防止以后"顺手统一"。

### 21.2 已核实部分（厂商二进制，不是文档不是猜）

- 帧编码器与厂商 `CommunicationCompiler.Encoder_A5_WithTail` 同构：
  `sof=0xA5`、`datalen = 载荷长度 - 2`（**不含 cmd 那 2 字节**）、`seq` 自增、
  `crc8` 只覆盖帧头前 4 字节、`crc16` 覆盖 帧头+cmd+载荷、`CRC8_INIT=0xFF/CRC16_INIT=0xFFFF`；
- 命令号是 16 位两半字节：`DJI_PRO_CMD_T{Cmd_Set=bits0-7, Cmd_Id=bits8-15}`
  ⇒ `pack_cmd()` 就按这个拼，测试里正面验；
- 键位位序 = 厂商 `KeyBoard` 枚举（19.1），所以本出口直接复用 `command.keyboard_value`，
  不用再翻一张表；
- 载荷字段顺序取自 12.x `dump.cs` 的 `Input_Device_Status`
  （mouse_x/y/z int16、left、right、keyboard_value uint16、mid_button）。

离线测试（`tools/dt7_link/test_dt7_link.py`，已挂 verify_all）还做了一件关键事：
**把每帧交给队内固件里那份官方 CRC 代码（`components/support/CRC8_CRC16.c` 编成 exe）验收**，
CRC8/CRC16 必须通过，改一字节必须被拒。另外覆盖：
profile 改了立刻生效 / 坏 JSON 与越界值退回默认（不许把链路打瘫）/ 默认 mock 不碰硬件 /
限流 / 主动松手发全零（DT7 侧没有"过期自动清零"的兜底）/ 写串口失败不涨计数 /
manager 三道闸与急停顺序 / **默认关**。

### 21.3 两个候选值（写在 `configs/dt7_profile.json`，现场确认，不改代码）

1. **`cmd_set` 与 `cmd_id`**：我取的 `cmd_id=17` 来自厂商 `Video2025MsgID.CMD_ID_Keyboard = 17`，
   但那张表名字指**图传模块**；DT7 口是不是同一编号体系，**没证实**。
   DT7 口那族 `CMD_ID_*` 在二进制里是 `static int`（值在 il2cpp v1 元数据
   `fieldDefaultValues` 表里，cctor 只做"搬进静态槽"，所以反汇编看不到立即数，
   见 20.2）。
2. **载荷是否就是 `Input_Device_Status` 那几个字段**（会不会还有 version/seq 前缀）。

⇒ 定案办法两条，都很快：
   - **抓包**：DT7 插电脑 + 官方选手端 + USBPcap，`dt7_frame_diff.py` 一条命令出字段与位序；
   - **直接试**：`dt7_link` 发一帧，看车有没有反应；没反应就换 `cmd_id`（改 JSON 即可）。
   发错命令号的后果只是"被遥控器忽略"，不会让车乱动 —— 这也是我敢先把出口做完的原因。

### 21.4 界面上怎么摆

- 开关：`RobotLink → Direct DT7 Egress`（**默认关**）+ `DT7 Port`；生效仍需
  非急停 / 模块启用 / `Allow Drive` 三道闸。
- 开着时水印显示 `DT7*`，星号是故意的：**提醒"这条的命令号还没现场确认"**，
  没确认之前不要上正式比赛。


---

## 22. DT7 口那帧**到底是什么**：命令号、CRC 族、字节布局全部落定（反汇编现场）

### 22.1 结论先说

**C 路（我们自己的客户端直连 DT7 发键鼠）方向是对的，帧型也定了。**
大疆选手端往 DT7 那个虚拟串口写的**不是** `0xA5` 帧，而是另一族 **`0x5A` 头、22 字节**的帧：

| 偏移 | 字节 | 含义 | 出处（GameAssembly.dll，函数 `SerialPortThread.OnSendInputStatus` RVA 0x27B2A0–0x27BAE0） |
|---|---|---|---|
| 0 | `5A` | hdr_flag | `0x18027B486  c6456f5a  mov byte ptr [rbp+0x6f],0x5a`（**全库唯一**的 `mov byte [mem+disp8],0x5a` 构造点） |
| 1 | `10` | length = 前缀4 + 载荷12（**含** cmd 那 2 字节，**不含**尾 CRC16） | `0x18027B48A  lea ecx,[rax+rbx]`（两个 `Marshal.SizeOf` 之和）→ `0x18027B491 mov [rbp+0x70],cl` |
| 2 | `01` | protocol_version | `0x18027B48D  c6457101` |
| 3 | xx | crc8，只覆盖 out[0..2] | `0x18027B4D8 call CRCCheck::GetCRC8(hdr,0,len-1)` → `0x18027B4F5 mov [rcx+rdi+0x20],al` |
| 4-5 | `00 00` | sequence_number u16，**不递增**（恒 0） | 同一个立即数 `0x20000000` 的低半（`m_curSeq` 只在 `CCSPortThread` 有，RC 侧没有 seq 字段） |
| 6-7 | `00 20` | cmd u16 线值 = **0x2000** | `0x18027B522  c7456f00000020  mov dword ptr [rbp+0x6f],0x20000000` |
| 8-19 | … | 载荷 12 字节 | `0x18027B57D/582` 拷 8+4 字节；`Array.Copy(input -> out, dstIndex=8, len=12)` |
| 20-21 | xx xx | crc16 覆盖 out[0..19]，小端 | `0x18027B5D8 GetCRC16(out,0,len-2)` → `mov [out+20],al / shr ax,8 / mov [out+21],al` |

期望帧长这样（我们的实现实测输出，也是测试里的金向量）：

```
5A 10 01 36 00 00 00 20 D3 FF 78 00 07 00 01 00 11 00 00 00 CB 50
键位0x11 / 鼠标(-45,120,7) / 左键=1
```

**载荷结构 = `Input_Device_Status_RC`（12 字节，`<hhhBBHH`）**：
`mouse_x i16@0, mouse_y i16@2, mouse_z i16@4, LB u8@6, RB u8@7, keyboard_value u16@8, reserved u16@A`。
**没有中键**——厂商自己的日志字面量也只有 `x,y,z,LB,RB,KeyValue`。

**CRC 用的是第三族 `CRCCheck`：`CRC8_INIT=0x77 / CRC16_INIT=0x1862`**
（`decomp/CRCCheck.cs:5-6` = 119/6242；`.cctor` 现场 `0x1802FAB75 mov byte ptr [rcx],0x77`、
`0x1802FAB86 mov word ptr [rcx+2],0x1862`）。裁判/图传那族是 0xFF/0xFFFF，**别互相冒充**。

### 22.2 这一节把前面三处结论作废（别照抄旧段落）

1. **`CMD_ID_Keyboard=17` 借错了族**：17 属 2025 图传那族（`T_V1_HEADER`/sof `0x55`，发帧函数
   `decomp/Video2025SerialPortThread.cs:217-256`；现场 `0x180295C76 c7471c11000000 mov [rdi+0x1c],0x11`），
   与 A5/5A 都不是一套寻址。**第 20/21 节里"先借 17 试号"的说法作废。**
2. **`dump.cs:131430-131437` 那族 `static int CMD_ID_*` 不是 DT7 命令号**：所在类是
   `dump.cs:131235 public static class ProtoDef`（同类有 `MAX_PROTOID=1000`、`typeArr`、`GetType/DefType`），
   是**协议注册表 protoid**。所以"值藏在 il2cpp `fieldDefaultValues`、离线可定案"这个前提本身就不成立 ⇒
   **第 20.2 节承诺的纯离线定案路线否证**（实际定案靠的是反汇编发送现场，见 22.1）。
   旁证：`ProtoDef..cctor` 里是 `lea ecx,[r8+imm] → call DefType → mov [slot],eax`，立即数就在代码段，
   根本不需要 fieldDefaultValues。
3. **载荷不是 `Input_Device_Status`（带 mid 那个）**：那是**图传**事件用的类
   （`dump.cs:146916-146931`）。RC/DT7 用的是 `Input_Device_Status_RC`（`dump.cs:136075-136085`，12 字节无 mid）。
   旁证还有 2025 图传那份 `Input_Device_Status_RC151`（**有 mid**，`dump.cs:136088-136099`）——三族各有各的载荷。
4. **波特率**：选手端对 RC 口设的是 **961200**（`decomp/SerialPortThread.cs:92-95`），
   115200 只是 CustomController 那个口的（同文件 `:100-101`）。旧 profile 写 115200 是错的。
5. **第 21 节末尾说"开着时水印显示 `DT7*`"**：现在水印是 `DT7:mock` / `DT7:real`，
   有原因时后面直接跟 `(!原因)`，键鼠出口打架时显示 `KM冲突(!…)`。

### 22.3 车端为什么是零改动（这次的独立取证）

- 《2026 竞赛规程》表 2-2 原文：**「DT7遥控器 —— 键鼠指令、遥控器杆量信息」**
  （`rm2026_spec.txt:380`）；`:401`「仅 DT7 遥控器可以接入选手端」——**只写"能连选手端"，没写"只能连选手端"**。
- 《遥控器手册》第 6 页链路图：`键盘鼠标 → PC主机 —USB→ DT7发射机 →（虚拟控制链路）→ DR16接收机 —DBUS→ 战车`，
  手册里**没有任何"要拨开关/进某种模式"的步骤**；DT7 的 USB 在 Windows 上就是普通 VCP
  （官方 INF：`USB\VID_FFF0&PID_0008` → 微软 `usbser.sys`），**任何程序都能打开写字节**。
- 接收机那 18 字节 DBUS 帧里 `bytes6-15` 就是 mouse/keyboard，我们固件一直在解：
  `application/other/remote_control.c:611-634`（`__RC_TYPE == RC_DT7`），键位还进了三本账合并（`:629-630`）。
  ⇒ **C 路不改固件一行就能把键鼠灌进 `rc_ctrl`。**
- **合规**：规程全文 `USB`/`数据线` 出现 0 次；S20 只管"无线射频部分"的改装，S21 允许遥控器；
  2.2.1 那条"键鼠来源只能有一个"写在**图传**路名下，**不适用于 DT7 DBUS**。
  我们照规程精神在客户端里做了互斥（见 22.4）。

**唯一的车端卡点**（Hume 审计出来的）：`robot_param_mecannum_hero.h:91` 的
`MOUSE_SENSITIVITY (100000.0f)` —— 云台参考角增量 = `mouse / SENSITIVITY`
（`gimbal_yaw_pitch_direct.c:331-332`），除以十万等于**把鼠标屏蔽了**（那两行上面的自注就写着"暂时先屏蔽一下鼠标功能"）。
所以 C 路的**键位**（W/S/A/D/SHIFT/Q/E/左右键）本来就能用，**鼠标控云台**要先把这个宏改成可用量级。

**先自我更正一次**：上一轮我把默认值定成 `0.5`，理由是「仓库另一份 `robot_param_mecannum.h:87` 就是这个值」。
**那是错的**：那份配置配套的是 ET08A/AT9S/HT8A 这类**没有键鼠**的遥控器，
鼠标量在 `remote_control.c:678-682` 每帧被清 0 ⇒ `0.5` 从来没被真实鼠标值除过，是**死配置**。
按「参考角增量 = mouse / SENSITIVITY」，`0.5` 意味着一帧 100 像素就是 200 rad —— 直接拍限位。

现在的默认值是**算出来的** `1000`：物理含义「1 像素 = 1 毫弧度 ≈ 0.057°」，
手速 1000 px/s ⇒ 云台约 1 rad/s。要恢复出厂的屏蔽行为就 `--mouse-sens 100000`；手感仍需实车标定。

客户端也加了每帧上限 `mouse_limit`（默认 200 px/帧，profile 可改，0=不限）：
界面掉帧时一帧攒几千像素完全可能，不截就是一帧甩到云台限位；截断记在 `last_note` 里，不静默。

为什么这个值必须由脚本负责而不是手工改：其它固件自检会 `git checkout` 工作树，
手工改的值会被冲回出厂值（本轮真就这么翻车一次）。
**「值的来源必须和体检断言的是同一处」——这条比那个 bug 值钱。**
另外：`s[0]`、`s[1]` 必须都在**中档**（底盘 FOLLOW / 云台 IMU / 键鼠射击档），键鼠才有意义；
这两个拨杆 PC **改不了**（来自 DBUS byte5 的物理通道），只能驾驶员手拨。

### 22.4 代码落地（本轮改了什么）

- `rm_client/backend/dt7_link.py` **重写**：三族帧型可切（`dji_rc_v1` 默认 / `a5_tail` / `a5_no_tail`）、
  三套 CRC 初值可切（`rc_check`/`student`/`video`）、载荷改为**字段名驱动**（`payload_fields` + 布局一致性自检）、
  **串口句柄长持**（旧版每帧 `with serial.Serial` 开关一次，30Hz 下必被 DTR/RTS 抖动与端口独占拖死）、
  限流不吞时隙、seq 语义可切（厂商恒 0）、`_profile_error` 一路带到界面。
- `configs/dt7_profile.json`：按 22.1 定案（`cmd_wire=0x2000`、`frame_variant=dji_rc_v1`、`crc_variant=rc_check`、
  `baudrate=961200`、12 字节载荷）。
- **真发闸**：`RobotLink` 新增设置项 `DT7 Real TX`（默认关）。不勾 = 只产帧不碰硬件；
  顺手修了一个**会让闸变成摆设**的坑：`manager.py` 里 `settings` 是按**固定名单**建的，
  新设置项不登记进去就永远读不到（第一次就是这样，靠测试才抓住）。
- **键鼠来源互斥**（`control.py`）：`0x0311 无线键鼠` / `直连 DT7` / `0x0306 自定义控制器`
  至多开一条，同开就**谁都不发**并把冲突显示到水印。理由不只是规程：DT7 直连与 0x0306 在车上
  灌的是**同一个** `HOST_RC_DRIVER_KEYS` 字段。
- **每条降级路径都补松手帧**（`manager.py`）：旧代码只在急停时补；现在关开关、撤 `Allow Drive`、
  模块停用也都补（DT7 那侧没有"过期自动清零"，粘键会一直控着车）。
- **中键语义**：载荷没有 mid 位 ⇒ 丢中键但**照发驾驶键**，并在 `last_note` 里写明；
  不会因为按了中键就把 WASD 一起拒了（那是更危险的失败模式）。
- `tools/dt7_link/dt7_vcp_probe.py`：新增首选帧型 `vendor5a`（自带一份同构实现，测试 `--- 9)` 把它和运行期实现钉在一起）、
  默认波特率改 961200。
- `tools/firmware/prepare_hero_build.py`：修掉一个**静默空转**——原来插入的
  `/* POLAR-HERO-BUILD: 键鼠链路档位（图传键鼠链路）>` 少了 `*/`，
  于是从下一行的 `/*` 一路吞到 `#define __CONTROL_LINK_KM` 和 `#define KM_KEY_ALLOWED_MASK` 两行：
  **`--km vt` 与 `--km-fire-keys` 都是空转**（值恰好被下面的 `#ifndef` 兜底成 `CL_KM_RC`，开火键位则根本没打开）。
  现在注释逐条自己闭合，并且 `verify_changes` 加了 `strip_c_comments()`——**剥掉注释之后**再断言宏真的存在，
  这样"躺在注释里的 #define"再也骗不过体检。回归断言在
  `tools/firmware/test_prepare_hero_options.py`（临时副本上跑 `--km vt/rc + --km-fire-keys`，
  剥完注释逐条验，含"不给开关就必须没有开火掩码"与"重跑不叠两份"）。

  **一条对队里的历史更正**：在这个 bug 修掉之前，`--km` 换档**从来没生效过**——
  所有以为"已经切到图传键鼠档"的工程，实际都还是出厂档 `CL_KM_RC`（键鼠只认遥控器，
  `remote_control.c:400-404` 让 0x0311 那本账整个不参与）。
  也就是说：**B 路（0x0311 图传键鼠）从今天起才真的可选**；
  之前它在车上是"看着接了线其实不通"的状态，跟硬件无关。
- `tools/dt7_link/test_dt7_link.py`：重写成 90+ 项，含金向量、两族互不认、拒发路径、句柄长持、
  限流不吞时隙、seq 回绕、profile 容错、闸门/互斥/松手、探针同构。

### 22.5 还剩什么不知道（照实说）

1. ~~`0x2000` 的语义归属~~ **已结案**（本轮最后一条离线不确定性关掉）：
   厂商自己给这个常量起了名字 —— `dump.cs:136032-136035`
   ```csharp
   public class Proto_Prefix { public const int CONTROL_PC_ROBOT = 8192; }   // 8192 = 0x2000
   ```
   `Proto_Prefix` 里**只有这一个**常量，名字直译就是"PC 控机器人"。
   另外三个类型定义把我们的字节布局逐字段钉死（测试第 11 节拿 `dump.cs` 当外部锚点断言，
   不是自洽断言）：
   - `CommonHeader_V1{hdr_flag@0,length@1,protocol_version@2,crc8@3}`（`dump.cs:136044-136050`）
   - `Data_Body_Prefix{sequence_number@0,cmd_id@2}`（`:136054-136058`）⇒ 顺序不能写反
   - `Input_Device_Status_RC{mouse_x@0,mouse_y@2,mouse_z@4,left_button_down@6,
     right_button_down@7,keyboard_value@8,reserved@A}`（`:136075-136085`）⇒ 12 字节、**无中键**
   ⇒ 现在离线能证的都证完了；**只剩一件**：这台 DT7 的现行固件认不认这 22 字节（只能上机）。
2. ~~CRC 表本体~~ **已经逐字节取出并端到端复算命中（不再是推断）**：
   - `CRC8_TAB`（256B）在 `global-metadata.dat` 绝对偏移 `0x438A30`，与标准反射表
     （poly 0x07 → 反射 0x8C）**逐字节 256/256 一致**；负对照（MSB-first 0x07 / 0xD5 / 0x8C-MSB）0 命中。
   - `CRC16_TAB`（256×u16）在同文件 `0x442C10`，与标准反射表（poly 0x1021 → 反射 0x8408）
     **逐字节 512/512 一致**；负对照（MODBUS 0xA001、0xC867、非反射 CCITT-FALSE/XModem、0x8005…）全 0 命中
     ⇒ **不是** CCITT-FALSE 那张表，别往那个方向改。
   - 两块表在整个 metadata（8,089,024B）里**各只有 1 份**、GameAssembly.dll 里 **0 份**；
     `CRCCheck` / `_RongYu` / `_StudentSerialPort` / `_VideoSerialPort` 四个类 `.cctor` 里
     `InitializeArray` 用的静态槽地址**逐字相同**（`0x181D8AFE8` byte[256] / `0x181D8B5D0` ushort[256]）
     ⇒ **同一份表被引用 4 次，只差初值**（0x77/0x1862、0x77/0x1862、0xFF/0xFFFF、0x77/0x3692）。
   - **端到端复算**：用取出的表重算我们那 22 字节 → `crc8(init 0x77, frame[0..2]) = 0x36`（帧里就是 0x36）、
     `crc16(init 0x1862, frame[0..19]) = 0x50CB` → 小端落盘 `CB 50`（帧里就是 CB 50）；
     控制组换初值 0xFFFF/0x3692/0x0000/0x1D0F 全部对不上。
     ⇒ **我们的位算法 + 0x77/0x1862 == 厂商实现**，一票否决项解除。
   - 顺带：全库 `cmp byte ptr[mem],0x5A` 的 22 处命中全在 BCL/Unity（TMP/protobuf/XmlSchema）里，
     游戏侧 **0 处**，0x5A 帧的构造点也仍只有 `0x18027B486` 一处
     ⇒ 选手端**不解析** DT7 的回帧，所以"车认不认"这件事离线到此为止，只能上机。
3. **DT7 会不会把我们发的键鼠当成"遥控器自己的键鼠"往上打**：手册只画链路不给 PC 侧协议，
   调参软件包里 0 条上行帧资料 ⇒ 只能上车验。
4. **DT7 的"键鼠过期/保持"策略**（PC 停止灌帧后 DT7 是发零帧还是重复最后状态）：未知，
   所以我们**主动**每降级路径补松手帧（22.4）。
5. **DT7 插着 USB 灌键鼠的同时，摇杆还能不能正常带车**：未知，上车第一件事就是量这个。
6. 手册与 V1.4 协议文档对 DBUS 周期一个写 14ms 一个写 7ms：**矛盾未解**，但对我们无影响
   （C 板只是被动收字节；C 路只影响"多久该重发一帧"，`max_hz=30` 两边都盖得住）。

### 22.6 一条命令验证（本轮新增，不用大疆客户端、不用抓包）

`tools/dt7_link/dt7_wireless_selftest.py`：一边往 DT7 写已知键位，一边读 C 板回读的
`km_key`（固件合并后的最终值），直接给 `PASS / PARTIAL / NO-CHANGE / NO-READBACK / BLOCKED`。
判据的证据链在 `tools/dt7_link/test_wireless_selftest.py`：里面有一个 `SimRobot`
（DT7 收到帧才让车上键位变），用它把三种失败形态各演一遍，
**包括"基线里已经有目标位就不许判 PASS"这条假阳性防线**。
`--dry-run / --dry-run --sim-reject / --dry-run --sim-shift 3` 就是这三幕的现场彩排。

### 22.8 步兵也能走同一条路（`--robot infantry`），并修掉一个"自检互踩"的老 bug

**为什么 C 路与兵种无关**：`__RC_TYPE` 是 `robot_param.h` 里的全局宏，DT7 那 18 字节解码
（`remote_control.c:611-634`）与键位三本账也不分兵种。差别只有一处：
**该改哪个参数文件的 `MOUSE_SENSITIVITY`**。所以 `prepare_hero_build.py` 现在能选兵种：

```
python tools/firmware/prepare_hero_build.py <固件> --robot infantry --rc dt7 --km rc   # 步兵
python tools/firmware/prepare_hero_build.py <固件> --robot hero     --rc dt7 --km rc   # 英雄
```

实测：`--robot infantry` 全跑 GO，且 **补丁新增代码在真实头文件下零错误零警告**
⇒ 步兵工程接 C 路不需要改一行固件逻辑。
顺带纠正一个数值：步兵参数文件的出厂值是 `40000.0f`（`robot_param_omni_infantry.h:99`），
同样是屏蔽量级，不是"已标定"。

**修掉的自检互踩**（这个坑比看上去大）：`test_host_bridge` / `test_rc_key_ledger` /
`test_patch_real_headers` / `test_patch_logic` 收尾都用 `git checkout -- .` 想撤掉自己装的桥,
实际把**整棵树所有改动**一起冲掉——包括准备脚本刚写好的兵种 include 与 `MOUSE_SENSITIVITY`。
本轮就是这么翻的车：我手工把英雄参数改成可用量级，跑一次 `verify_all` 之后它被某个兄弟测试
冲回 `100000.0f`，而新加的体检随即 NO-GO。现在四个脚本统一改用
`tools/firmware/bridge_fixture.py`：**装之前按字节快照（含"原本不存在的文件"），收尾原样放回**，
别人的改动一个字节都不碰。修完实测：跑完整条 `prepare(infantry) → prepare(hero) → verify_all`
之后，两份参数文件仍然都是 `1000f`、`robot_param.h` 仍指向英雄 —— 这就是以前会被偷偷吃掉的东西。

### 22.7 附带成果：`--km vt`（0x0311 图传键鼠档）今天才第一次真正编译过

`--km` 一直是空转的（见 22.4），意味着固件里那套**五档键鼠来源仲裁**在英雄工程里
从来没被切到 `CL_KM_VT` 上编译过。这一轮修好后实跑一次：

```
python tools/firmware/prepare_hero_build.py <固件> --rc dt7 --km vt
... [6/6] 用固件真实头文件编译 + 运行补丁新增代码
  [OK]   补丁新增代码在真实头文件下零错误零警告
  [OK]   驾驶键位三方写入者行为正确（DT7 不被抹 / 松键能归零）
结论：GO
```

⇒ **次选路（0x0311 到 C 板的接收路径）在软件侧是站得住的**，车端只差"图传发送端那根串口
到底接在哪、波特率对不对"这一件现场事实（`km_rx` 回读能当场告诉你收没收到）。
默认推荐仍然是 C 路（`--km rc`：DT7 键鼠直接进 `rc_ctrl`，不依赖图传接线）。
