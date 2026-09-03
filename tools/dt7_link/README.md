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
