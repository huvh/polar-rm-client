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
   - 有这句但车不动 ⇒ 十有八九是**通用键值表不对**：大疆文档只写「使用通用键值」、没附表，
     真值只能现场逐键试（`cc_probe.py --sweep`）。**改 configs/cc_key_usage.json 就行，
     不要改代码**；那张表坏了/缺项会自动退回内置 HID 默认，不会把驾驶键一起带崩；

`RoboMasterEngine 12.0.0.137_Student.zip` 是**裁判端+服务器**（不是选手端）。
它的 `Assembly-CSharp.dll`、`RMServer.exe` 以及 RMServer 目录下 167 个二进制里
**没有任何 MQTT 栈、也没有 `KeyboardMouseControl` 字样**（服务器内部走 Redis + protobuf）。
⇒ 官方文档写的"服务器 192.168.12.1:3333"那个监听者只能是**选手端那一侧**；
所以 B 路（0x0311）和 D 路（0x0306）**都以"官方选手端在跑"为前提**。（已核实：12.x 选手端进程自己开着 MQTT broker
   —— 元数据里有 `MqttServer/MqttTcpServerListener/MyMqttServer.StartMqttServer` 与专门的
   `CustomClientThread`；而 12.x 裁判端/服务器包里没有任何 MQTT。⇒ **同机就用默认
   `127.0.0.1:3333`**，跨机才填选手端那台机器的 IP。见 README 第 17.2 节。）
别到现场才发现客户端连了个没人监听的 3333。

## 5. 绝对不要做的事

- 不要拿 `RC_System_Installer_v1.2`（DT7 唯一的官方"调参软件"）去**升级遥控器固件**：
  社区协议文档第一页原话"RoboMasters 提供的遥控系统是 DJI 特别定制的，
  不要随意升级遥控器固件，否则会造成遥控器无法使用"。
- 不要给车加任何无线发射/接收装置（S62 明确禁止自定义客户端这么做）。
- 不要为了"看着能用"把 `KM_KEY_ALLOWED_MASK` 打开 Q/E——开火权限走
  `prepare_hero_build.py --km-fire-keys`，那是显式决定。
