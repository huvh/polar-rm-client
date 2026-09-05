# 客户端无线控车 · 现场一页纸

给上车的人看的。三分钟内能走完。**证据与原理都在
`tools/dt7_link/README.md`（第 5/8/10/11/12 节）和
`tools/firmware/host_bridge/GAPS.md` 第 10 节，这里只写动作。**

---

## 0. 两个前提，先核对再往下

- **必须是 12.x 的选手端。** 实测对比：`Mqtt` 在 11.x 选手端元数据里出现 **0** 次、
  12.x 里 **221** 次；`CustomClientThread` 0 → 4 次。
  ⇒ **B 路（MQTT 3333 + 0x0302/0x0311）在 11.x 上根本不存在**，用它试一定会
  "连不上 3333"，而现象看起来像我们客户端坏了。见 README 第 18.1 节。
- **自定义控制器必须是 FTDI，且要装选手端自带的那个驱动。**
  选手端 `ReadMe.txt` 第 3 条原话："如需连接自定义控制器，必须安装专用驱动程序"，
  路径 `StreamingAssets\Tools\Windows_CDM21228_Setup.exe`（FTDI VCP 驱动）。
  见 README 第 17.1 节。

## 0b. 认清有三条路，别混

| 路 | 依赖什么 | 现在状态 |
|---|---|---|
| A. USB 线插 C 板（0x5A） | 一根数据线 | **确定能用**（打过比赛） |
| D. **自定义控制器 → 选手端 → DT7**（0x0306） | 官方选手端在跑 + 一个能连选手端的串口 | **代码已实现**（默认关+默认 mock）；这是电控熟悉的那条路，**不需要车上图传接线** |
| B. 图传链路 0x0311（PRM1 kind=3） | 带 POLAR-KM-LINK 的固件 + 车上图传发送端那一路串口要接到 C 板能收的地方 | 代码两端都通了，**只差现场确认包到不到** |
| C. 电脑直接插 DT7 说 DT7 的 USB 私有格式 | 逆向 DT7 上行帧 | 命令名已在 12.x 二进制里找到（`CMD_ID_Keyboard` 等），**数值要解 IL2CPP 元数据**；D 路更快，这条当备用（README 18.2/18.3） |

**先跑 A 保底，再验 B。** C 是备胎，不要在现场才开始逆向。

---

## 1. 上电前（客户端 + 车，插着 USB 线）

1. Keil 烧好 `prepare_hero_build.py --km vt_rc` 那版工程（`vt_rc` = 图传优先、过期自动回落遥控器，五档里最安全）。
2. 客户端：`RobotLink` 模块 enabled → 勾 **Allow Drive** → 勾 **Client Chassis Drive** → `Drive Channel` 选 `virtual_rc` → 勾 **Radio KM Egress**。
3. 插上 C 板 USB，看水印那行的 `KM` 字段。它现在是**实况**，不是开关状态：

| 脸上显示 | 意思 | 动作 |
|---|---|---|
| `KM live↑N`（N 在涨） | **0x0311 真到了 C 板** | 拔线，走第 2 步无线验证 |
| `KM NO-RX!!` | 我们发了，但车上一个包都没收到 | 走第 3 步排查，**别再调客户端** |
| `KM on(?)` | 读不到车上计数（线没插/固件没回读） | 插线重看 |
| `KM stall@N` | 收到过又不长了 | 查图传对频/客户端登录掉没掉 |
| `KM blocked` | 三道闸没过 | 看提示，缺哪个补哪个 |
| `KM off` | 开关没开 | 回第 1 步 |

## 1a-c. 走 D 路（选手端 + DT7）时怎么开、怎么确认

1. 官方选手端 `RoboMasterClient` 跑起来并登录本机机器人，DT7 正常连着它；
   **键鼠来源选"官方选手端"**（这条路是选手端在发键鼠，见 2.2.1 的二选一）。
1a. **硬件前提（最容易白跑的一条，且有官方原文）**：选手端包里的 `ReadMe.txt` 第 3 条
    原话"**如需连接自定义控制器，必须安装专用驱动程序**"，那个驱动就是包内的
    `StreamingAssets\Tools\Windows_CDM21228_Setup.exe`（**FTDI 的 VCP 驱动**）。
    选手端 `DeviceInfo.dll` 的 `GetCCSSerialPort` 也只匹配硬件 ID 里的 `FTDI`
    （11.x 与 12.x 实测一致，见 README 第 17.1 节）。
    的 USB-串口当"自定义控制器"，并与第二个 USB-串口用 TX/RX/GND 三根线交叉相连；
    客户端往第二个口写。com0com 虚拟口**不算**（选手端 `GetCCSSerialPort` 只认
    硬件 ID 里的 `FTDI`）。先跑 `python tools/dt7_link/cc_probe.py --list` 自查。
2. 客户端 `RobotLink` 里勾 **Custom Controller Egress**，`CC Port` 选选手端那个
   自定义控制器串口，先保持 **CC Mock Writes = 开**（只产帧不写串口），
   确认水印出现 `CC on`；再关掉 Mock 真发。
2b. **逐键对表用命令行更快**（不用开 GUI、不用改授权）：
   `python tools/dt7_link/cc_probe.py --sweep` 先只看字节；
   `python tools/dt7_link/cc_probe.py --port COM7 --keys W --confirm-move-car` 试一个键。
   不给 `--confirm-move-car` 就一个字节都不写；发完自动补全零松手帧。
3. 判定只看一处：选手端日志（或它的"自定义控制器已连接"指示）出现
   `[Game] 收到0306数据包`。
   - 有这句 + 按 W 车动 ⇒ D 路通，拔 USB 线也能控车；
   - 有这句但车不动 ⇒ 十有八九是**通用键值表不对**：大疆文档只写「使用通用键值」没附表。
     逐键试 `python tools/dt7_link/cc_probe.py --sweep`，
     **改 `configs/cc_key_usage.json` 的数字就行，不要改代码**
     （表缺失/坏/越界会自动退回内置 HID 默认，不会把 W/S/A/D 一起废掉）；
   - 没有这句 ⇒ 选手端不认这个串口（挑口规则问题，README 14.3 第 1 条），
     需要真 USB-串口线或换端口。
4. 只有驾驶四键（W/A/S/D）能过；SHIFT 要另开 `Allow Spin Key`，
   Q/E 永远不从这条口下发。选手端侧还有一层"仅响应选手端开放的按键"白名单。
5. 2 键无冲、鼠标是**绝对像素**（1920×1080）：这两条是文档写死的限制，
   客户端已经做了攒标与丢弃上报（`cc_dropped_keys`），别指望绕过。

## 1b. 一键自检（决定要不要继续的第 30 秒）

在 `RobotLink` 模块里点 **Run Wireless KM Selftest**。它只做一件事：
记下**车上**回读来的 `km_rx`，等 2.5 秒，再看它涨没涨。
判据是车那一侧的计数，不是"我们发了多少"（那只能自证）。

- `无线自检 PASS · 车上计数 100->180 帧` → 端到端通了，拔线继续。
- `FAIL · 客户端一帧都没发出去` → 看 `radio_km_last_error`（多半是 MQTT 没连上或场景 mock）。
- `FAIL · 发了但车上收到 0 增量` → 直接进第 3 步，**别再调客户端**。
- `读不到车上计数` → 先把 USB 插上；自检不注入任何按键，车不会因为自检而动。

## 2. 无线验证（拔线）

拔 USB 后车应仍能：W/A/S/D 移动、SHIFT 小陀螺（要开 `Allow Spin Key`）。
发射相关 Q/E 默认**被固件挡掉**（要 `--km-fire-keys` 重编才放开）。
遥控器摇杆、拨杆全程照常用；驾驶员随时能抢回来（`vt_rc` 档 300ms 过期自动回落）。

> 遥控器三位拨杆 **s[0] 必须拨中间**。拨在下面时固件走 CHASSIS_LOCK，
> 补丁打得再对车也不动；拨上面是无条件强制常转，小陀螺开关看起来"没反应"。

## 3. `KM NO-RX!!` 的排查顺序（按官方原文排的）

1. **MQTT 连的是谁**：官方写死 `服务器 192.168.12.1:3333，自定义客户端 192.168.12.2`。
   我们默认连 `127.0.0.1:3333`（那是官方选手端自带的 broker）。
   → 现场要么把 host 改成 `192.168.12.1`，要么本机跑官方选手端当中转。
   没连上 broker 时 `radio_km_last_error` 会写原因，别看车，先看它。
2. **键鼠来源只能一个**（2026 协议 2.2.1）：要么"官方选手端"要么"自定义客户端"。
   两边同时开 = 有一边白干，且不报错。
3. **物理口**（头号嫌疑）：官方表 1-1 写 `图传发送端←→机器人 921600`，
   1.1 节写图传链路"从图传模块（发送端）的串口接收数据"；
   我们固件裁判口是 `huart6`@115200（那是电源管理模块的常规链路）。
   → 先量**车上图传发送端那根串口线到底插在哪、波特率多少**。
   → 若它不在 huart6 上：**别改仲裁**，把那一路收到的 30 字节载荷
   调用 `HostKmFeed(payload, len)` 灌进来即可（新鲜度门控、五档仲裁、
   键位掩码全部照旧，`tools/firmware/km_link/host_km_link.h`）。
4. 上面都不行 → 当天就用 A 路（USB 线）上场，回来再治。

## 4. （已结案，只作 10 秒复核）DT7 键位 bit4-7 位序

> **这条不用现场判了**：12.x 选手端反编译出来的 `KeyBoard` 枚举是
> `W=1 S=2 A=4 D=8 SHIFT=16 CTRL=32 Q=64 E=128 R..B=256..32768`，
> 与我们固件/客户端完全一致；2016 手册那套（Q4/E5/Shift6/Ctrl7）是过时的。
> 出处与代码守卫见 README 第 19.1 节。下面两步留作上车复核，不是必做。

十秒，不用仪器：拨杆放中间、车上电，**按物理 Q**。
摩擦轮起转 = 现固件/RM2026 位序（我们编码对）；车切小陀螺 = 2016 手册位序（要改）。
证据与影响面：`tools/dt7_link/README.md` 第 3.1 节。

## 3b. 本工程的串口事实（决定 B 路要不要动硬件，先把这段看完）

从 `standard_robot.ioc` + `Src/usart.c` 实测抄出来的**全部三个**串口：

| 口 | 引脚 | 波特率 | 用途 | 出处 |
|---|---|---|---|---|
| USART1 | PA9 TX / PB7 RX | 115200 8N1 | **板间通信**（C 板外壳标 "Uart2"） | `usart.c:42`、`communication.c:13` |
| USART3 | PC10 TX / PC11 RX | 100000 **8E1** | **遥控器 SBUS/DBUS** | `usart.c:61-64`（与手册 DBUS 参数一致） |
| USART6 | PG14 TX / PG9 RX | 115200 8N1 | **裁判系统（常规链路）** | `usart.c:80`、`referee_usart_task.c:45` |

⇒ **工程里没有第四路串口**，也没有任何 921600 的配置（全仓 `grep 921600` 零命中）。
而官方说 0x0311 属图传链路、要从**图传发送端的串口(921600)**进车。
所以 B 路只有三种可能，自检结果直接区分：

1. 车上图传发送端那根串口线**本来就并进了 USART6 那条线**（帧头同为 `0xA5 + len(2) + seq + crc8`，
   并线是能解析的）→ 自检会显示 `live↑N`，什么都不用改；
2. 它接在 C 板另一个插头上，只是我们**没在工程里开那一路** →
   需要开一路 UART @921600，然后把它收到的载荷喂 `HostKmFeed()`（现成接口，不改逻辑）；
3. 车上**根本没把图传发送端接到 C 板** → 当天 B 路不可能通，直接用 A 路上场，
   赛后补接线。

判据：插着 USB 点 `Run Wireless KM Selftest`。
`live` = 情况 1；`NO-RX!!` = 情况 2 或 3，去看板子上那根图传串口线插到哪、
工程里对应那一路有没有开。

## 4b. DT7 那条路（C 路）：现在靠反编译推进，抓包只是可选旁路

**已结案的部分**（README 第 19 节）：帧格式 = 厂商 `Encoder_A5_WithTail`（0xA5 + datalen(不含 cmd_id) + seq + crc8 + 整帧 crc16，CRC 初值 0xFF/0xFFFF），与我们的 `cc_link.encode_cc_frame` 同构；键位位序已定；图传那侧键鼠命令号 `CMD_ID_Keyboard = 17`。
**只剩一块**：DT7 自己那条 VCOM（`VID_FFF0&PID_0008`）用的命令号是 native 里的 `static int`（值不在 dump.cs 里），下一步用 capstone 反汇编它的 cctor 就能拿到，**不需要硬件也不需要抓包**。

想立刻验证的话，抓包仍是快路：

1. DT7 用数据线插电脑，开官方选手端（`RoboMasterClient`），按提示连接遥控器；
2. 同时用 USBPcap/Wireshark 抓那个设备的 **主机→设备** URB；
3. 依次：什么都不按(3 包) → 按住 W(3 包) → 按住 Q(3 包) → 按住 Shift(3 包) → 动鼠标；
4. 选中那些 OUT 包，`Edit > Copy > As Hex Stream`，每行粘进 `samples.txt`，
   行首打上 `NONE / W / Q / SHIFT` 标签；
5. `python tools/dt7_link/dt7_frame_diff.py samples.txt`
   → 直接报"键位在第几字节 + 用的是哪套位序"，并明确区分
   `fw` / `dji2016` / 样本不够判不出来 三种结论。

## 4c. 一条被二进制纠正过的假设：**3333 那个 broker 在选手端那侧**

`RoboMasterEngine 12.0.0.137_Student.zip` 是**裁判端+服务器**（不是选手端）。
它的 `Assembly-CSharp.dll`、`RMServer.exe` 以及 RMServer 目录下 167 个二进制里
**没有任何 MQTT 栈、也没有 `KeyboardMouseControl` 字样**（服务器内部走 Redis + protobuf）。
⇒ 官方文档写的"服务器 192.168.12.1:3333"那个监听者只能是**选手端那一侧**；
所以 B 路（0x0311）和 D 路（0x0306）**都以"官方选手端在跑"为前提**。（已核实：12.x 选手端进程自己开着 MQTT broker
   —— 元数据里有 `MqttServer/MqttTcpServerListener/MyMqttServer.StartMqttServer` 与专门的
   `CustomClientThread`；而 12.x 裁判端/服务器包里没有任何 MQTT。⇒ **同机就用默认
   `127.0.0.1:3333`**，跨机才填选手端那台机器的 IP。见 README 第 17.2 节。）
别到现场才发现客户端连了个没人监听的 3333。

## 4d. C 路（直连 DT7）现在能试了：一个开关 + 一个 JSON

`rm_client/backend/dt7_link.py` 已按厂商帧结构实现（0xA5 + datalen(不含 cmd) + seq + crc8 +
cmd2 + 载荷 + crc16；命令号位域 Cmd_Set 低/Cmd_Id 高）。开 `Direct DT7 Egress` +
`DT7 Port` 就能发；**命令号仍是候选值**，写在 `configs/dt7_profile.json`，
试不出来就换数字，不用改代码。发错号的后果只是"被忽略"，不会让车乱动。
水印出现 `DT7*`（带星号＝未确认）时，不要上正式比赛。
详见 README 第 21 节。

## 5. 绝对不要做的事

- 不要拿 `RC_System_Installer_v1.2`（DT7 唯一的官方"调参软件"）去**升级遥控器固件**：
  社区协议文档第一页原话"RoboMasters 提供的遥控系统是 DJI 特别定制的，
  不要随意升级遥控器固件，否则会造成遥控器无法使用"。
- 不要给车加任何无线发射/接收装置（S62 明确禁止自定义客户端这么做）。
- 不要为了"看着能用"把 `KM_KEY_ALLOWED_MASK` 打开 Q/E——开火权限走
  `prepare_hero_build.py --km-fire-keys`，那是显式决定。


---

## 14. C 路（直连 DT7）上车顺序 —— 本轮定案后的最短流程

前提：**不用开大疆客户端**。这条路的帧已经从大疆 12.x 选手端二进制里逐条反汇编复原
（见 `tools/dt7_link/README.md` 第 22 节），车端固件**零改动**。

1. **接线**：DT7 用 USB 线插笔记本；车上 DR16 正常连 C 板 UART3（原样，不动）。
   先 `python tools/dt7_link/dt7_vcp_probe.py --list` 找那个 `VID_FFF0&PID_0008` 的
   "DJI USB Virtual COM"口（驱动装过就有；它是普通 COM 口，不需要任何大疆程序）。
2. **架空驱动轮**（第一次必做；这一步不是仪式，是因为命令号的语义归属还没上机验证过）。
3. 客户端：开 `RobotLink` 模块 → 勾 `Allow Drive` → 勾 `Direct DT7 Egress` →
   选对 `DT7 Port` → 最后才勾 **`DT7 Real TX`**（不勾只产帧，不碰硬件）。
4. 车上 `s[0]`、`s[1]` **都拨中档**（底盘 FOLLOW / 云台 IMU / 键鼠射击档），云台已校准。
   这两个拨杆 PC 改不了，必须驾驶员手拨。
5. 看水印：`DT7:real` = 真在发；带 `(!原因)` = 没发并写明为什么；`KM冲突(!…)` = 键鼠出口开重了，
   关到只剩一条。想同时看车上的键位在谁手里，就再插 C 板 USB 读 `km_key`（A 路回读，不影响 C 路）。
6. 按 `W` → 车应当前进；`SHIFT` → 小陀螺开/关；`Q/E` → 摩擦轮；左键 → 单发/连发。
   **鼠标现在应该能转云台**：`prepare_hero_build.py` 默认把 `MOUSE_SENSITIVITY`
   从出厂的 `100000.0f`（等于屏蔽鼠标）改成 `1000`
   （物理含义：1 像素 ≈ 1 毫弧度，手速 1000 px/s 对应云台约 1 rad/s；
   客户端另有每帧上限 `mouse_limit=200` 防一帧甩到限位）：

   ```
   python tools/firmware/prepare_hero_build.py <固件路径> --rc dt7 --km rc
   ```

   手上那版固件如果是更早准备的、鼠标不动，重跑上面这条再烧一次就行；
   想回到出厂的"屏蔽鼠标"行为就加 `--mouse-sens 100000`。**方向与手感必须实车标定**：
   觉得太慢就调大分母（比如 2000），太快就调小（比如 500），别一上手就拧到个位数。
6b. **必须量的一个安全项（现在没人知道答案，但已经有命令能量）**：DT7 在我们**停止灌帧**之后
   是发零帧还是重复最后一帧？—— 这决定客户端崩掉时车会不会**粘键**一直顶。

   ```
   python tools/dt7_link/dt7_wireless_selftest.py --dt7-port COM9 --board-port COM3 --hold-test
   ```

   它按住若干帧然后**故意不再写任何东西**（等价于进程被杀，只是我们还能读车上回读），
   看 `km_key` 会不会自己掉回基线，并量出"多久才清"（`clear_after_s`，随 --report 一起落盘）。
   结论两种都合法，但处理方式不同：
   - `EXPIRES`：DT7 自己过期清零 ⇒ 客户端崩了车会松油门，安全。
   - `STUCK`：DT7 重复最后一帧 ⇒ **C 路掉线会粘键**，必须立一条现场规矩：
     客户端进程一没，驾驶员立刻把 `s[0]` 拨到下档锁底盘（`chassis_mecanum.c:97-99`）。

   为什么这条值得单独量：手册、驱动包、选手端二进制全都翻过，**没有任何一处写** ——
   它是 DT7 机内行为，只能上车测。

7. 若第 6 步**完全没反应**：别一种一种手敲，用扫帧型工具一条命令扫完（读车上 `km_key` 判，
   探针是 X 键所以不会因为扫描把车开走）：

   ```
   python tools/dt7_link/dt7_sweep.py --dt7-port COM9 --board-port COM3 --report field_evidence/sweep.json
   ```

   `PASS` 的那一行就是要写进 `configs/dt7_profile.json` 的帧型；
   出现 `PARTIAL` 说明**帧型对了、载荷错了**，别再换帧型，去改 `payload_layout`。
   （手工逐种试仍然是这条：）
   `--candidate vendor5a` → `dbus18` → `km12` → `keys2`，并可 `--send-hex` 回放抓包样本。
   这时才需要 USBPcap 抓一次 DT7 口（工具 `dt7_frame_diff.py`）。

合规提示：DT7 必须在场且能正常开车（检录 S17 要现场展示发射/底盘/云台），
C 路并不免除这条；规程没有禁止第三方程序写 DT7 的 VCOM，但也**没有明文允许**——赛前报备一次更稳。


---

## 15a. 步兵车：同一条路，换 `--robot infantry`

C 路不分工兵/英雄：`__RC_TYPE`、DT7 的 18 字节解码、键位三本账都不分兵种，
唯一差别是改哪个参数文件的鼠标灵敏度。准备步兵工程：

```
python tools/firmware/prepare_hero_build.py <固件路径> --robot infantry --rc dt7 --km rc
```

已实测：步兵工程全跑 GO，补丁代码在固件真实头文件下零错误零警告 ⇒ **步兵接 C 路不用改固件逻辑**。
注意步兵出厂 `MOUSE_SENSITIVITY` 是 `40000.0f`（`robot_param_omni_infantry.h:99`），同样是屏蔽量级。

> **还有一条会让"鼠标不转云台"的原因，跟灵敏度无关**：云台中间档一旦收到上位机的
> 云台直控请求（0x04 param0 bit0），固件就切到 `GIMBAL_AUTO_AIM`，那时 **DT7 鼠标不参与云台**
> （`gimbal_yaw_pitch_direct.c:236-243`）。也就是说"客户端自瞄/云台直控"和"客户端经 DT7 的鼠标"
> 是同一条云台的**两个主人**，只能有一个生效。界面上看得见：C 路开着且请求被占着时，
> 水印会挂 `(鼠标被上位机云台顶掉)`。这不是故障，是仲裁——别去改固件。

## 14b. 更省事的办法：客户端界面里的 `Run DT7 Link Selftest` 按钮

在 `RobotLink` 面板最下面（`Run Wireless KM Selftest` 旁边）。它跟命令行版做同一件事，
但**不新开串口**（两个程序抢同一个 DJI VCOM 会互相占死，是最难查的故障），也不阻塞界面。

关键区别：**探针用的是 X 键**。全固件对 R/G/Z/X/C/V/B 零消费（测试里直接 grep 固件源码钉住），
所以"链路通不通"和"车会不会动"完全解耦——**不架空轮子也能做连通性判定**。
（要验小陀螺/驾驶键的实际效果时，仍然必须架空轮子。）

两阶段：① 强制发 X 0.9 秒 → 判 `PASS/PARTIAL/NO-CHANGE/NO-READBACK`；
② **一帧都不发** 1.6 秒（模拟进程被杀，不补松手）→ 判 `STUCK/EXPIRES`，就是第 6b 步那条粘键问题。
结论连当时用的 profile 一起写进 `field_evidence/dt7-selftest-*.json`。

前置：`Direct DT7 Egress` 开着且出口真生效、C 板 USB 0x5A 插着（回读靠它）。
不满足时按钮会把原因写在 toast 上，不会闷着不响。

## 15. 一条命令的闭环自检（现场先跑这个，别靠"车好像动了"）

```
python tools/dt7_link/dt7_wireless_selftest.py --dt7-port COM9 --board-port COM3 --keys W
```

两根线都要插：DT7 插电脑（我们往它写键鼠帧）、C 板 Type-C 插电脑（**只读**车上回读，
一个字节都不往下写，所以不抢驾驶权）。工具做的事：先采 0.6 秒 `km_key` 基线，
再按 30Hz 发已知键位，同时盯 `km_key` 有没有长出我们发的那几个位。

判读（这五种结果的含义是互斥的，别自己猜）：

| 结论 | 意思 | 下一步 |
|---|---|---|
| `PASS` | **C 路整条通了**：PC→DT7→空口→DR16→UART3→`rc_ctrl.key.v` | 可以直接开车；再逐键验 SHIFT/Q/E/左右键 |
| `PARTIAL` | 帧被 DT7 吃了，但键位漂了 ⇒ 载荷错位（字段顺序/偏移） | 抓一次 USBPcap 对比：`dt7_frame_diff.py` |
| `NO-CHANGE` | DT7 完全不理这帧 | 换帧型：`dt7_vcp_probe.py --candidate dbus18/km12/keys2` |
| `NO-READBACK` | 读不到 C 板 Debug 上行 ⇒ **判定不成立**，不能当成"没通" | 先查 `--board-port` 是不是那个 CDC 串口、`__USB_SEND_DEBUG` 是否为 1 |

> B 路（0x0311）现场排查现在有四个数可以分清了：`km_rx`（0x0311 键鼠帧到达）、
> `km_ok`（拆出的好帧，含别的命令号）、`km_bad`（crc/长度不对被丢掉的帧），
> 再加上客户端自己发出的帧数。只盯 `km_rx` 分不清【根本没接线】和【线有了但帧全废】，
> 而这两种的处理方式完全不同。
> 字节流接收器 `HostKmFeedBytes()` 已装进固件（实现与断言见 README 第 23 节）。
| `BLOCKED` | profile 未定案/自相矛盾，**一个字节都没写** | 按提示改 `configs/dt7_profile.json` |
| `NOT-SENT` | **客户端自己一帧都没写出去**（不是遥控器的锅） | 先查 `DT7 Real TX` 有没有勾、闸门原因（水印上的 `(!…)` 就是它）、`dt7_last_error`。这条排最前面，是为了不让人去怀疑 DT7 |

跑的时候带上 `--report`，结论会连当时用的帧型设置一起落成 JSON（换 profile 之后还能追溯）：

```
python tools/dt7_link/dt7_wireless_selftest.py --dt7-port COM9 --board-port COM3 --report field_evidence/dt7-selftest.json
```

不碰硬件就能先看工具本身有没有问题：

```
python tools/dt7_link/dt7_wireless_selftest.py --dry-run                     # 假车应当判 PASS
python tools/dt7_link/dt7_wireless_selftest.py --dry-run --sim-reject         # 应当判 NO-CHANGE
python tools/dt7_link/dt7_wireless_selftest.py --dry-run --sim-shift 3        # 应当判 PARTIAL
```

安全：跑之前**架空驱动轮**（`W` 会让车往前顶，`SHIFT` 会切小陀螺）；工具结束一定补松手帧。
