# 进 rc_ctrl 的三条链路（一页速查）

> 结论先说：**客户端驾驶走的是 USB 0x5A，与遥控器无线链路无关；两者只在单片机内部的
> `rc_ctrl` 会合。** 但"把指令改走遥控器"这件事，在当前 `__RC_TYPE=RC_ET08A` 下
> **解码端没有落点**（见 §2 表格最后一行），必须先改一个宏。所有行号按
> `tmp_polarbear/StandardRobotpp` 打完英雄桥之后的树。

## 1. 三条链路对照

| | ① USB 0x5A（客户端） | ② SBUS 无线（遥控器） | ③ UART2 板间 |
|---|---|---|---|
| 物理 | 电脑 → USB 线 → C 板 Type-C（虚拟串口） | 遥控器 → 2.4G → 接收机 → C 板 UART3（DMA） | 别的板 → USART1（板上丝印标 Uart2） |
| 帧 | `0x5A` + id + len + CRC16 | 标准 SBUS 25 字节 | `0xA5` + SOF，只搬 Test/Rc/Gimbal 三种包 |
| 入口 | `usb_task.c` 收 0x03 虚拟遥控器 | `remote_control.c:238-272`（buffer0）/ `:291-325`（buffer1） | `communication.c:221-237` |
| 怎么写 rc_ctrl | `UsbMergeVirtualRcKeys()` `usb_task.c:1363`：**`rc_ctrl.key.v \|= drive_keys`（或进去）** | DT7：`sbus_to_rc()` 里 `=` **整字段覆盖**；ET08A：`Et08aSbusToRc()` `:508` | `communication.c:229-232` **整份 `RC_ctrl_t` memcpy 覆盖** |
| 生效条件 | 三条开关：RobotLink enabled + Allow Drive + Client Chassis Drive，且 Drive Channel=`virtual_rc`；只放行 `VRC_DRIVE_KEY_MASK`（W/S/A/D） | `__RC_TYPE` 决定用哪个解码器（`robot_param.h:29`，当前 `RC_ET08A`） | 编译期 `__CONTROL_LINK_RC == CL_RC_UART2`；当前是 `CL_RC_DIRECT`（`robot_param.h:57`），**这段不参与** |
| 超时/回退 | `VRC_FRESH_TIMEOUT_MS = 150`（`usb_task.c:148`）：USB 断 150ms 后不再贡献键位，键位自动回到真遥控器，不冻在最后一帧 | 连续 10 帧（`SBUS_MAX_LOST_NUN`）connect_flag 变了判失联 → `slove_RC_lost()` 重启 DMA | `LastReceiveTime.Data_Rc` 由上层判 |
| 语义 | **叠加**（与驾驶员共存，摇杆/鼠标/其他键全保留） | **覆盖**（遥控器说了算） | **覆盖**（会把 USB 或进去的键位一起冲掉——所以 `CL_RC_UART2` 与客户端驾驶不能混用） |

## 2. 为什么"改走遥控器"现在不通

`Et08aSbusToRc()`（`remote_control.c:508-530`）的**全部落点**只有这些：

```c
rc_ctrl->rc.ch[0..3]                      // 四个摇杆通道（含 671->660 缩放、ch1 取负、ch2/ch3 交换）
rc_ctrl->rc.s[0] / rc_ctrl->rc.s[1]       // 两个三段拨杆
SPECIAL_CHANNEL_SET_SERO()                // :426 把 mouse.x/y/z、press_l/r、rc.ch[4] 全部 =0
```

也就是说 **ET08A 路径：既不写 `key.v`，还反向把 `mouse` 清零。**
而客户端驾驶与云台直控用的恰恰就是这两样：

* 底盘键位：`chassis_mecanum.c:196-199` 读 `key.v & KEY_PRESSED_OFFSET_W/S/A/D`
* 云台鼠标：`gimbal_yaw_pitch_direct.c:331-332` 读 `mouse.y` / `mouse.x`

-> **想让客户端指令改走遥控器无线，前提是解码端有落点**：只有 DT7 那条路会写
`key.v`（`remote_control.c:382`）和 `mouse`（`:377-378`）。所以要么把
`__RC_TYPE` 改回 `RC_DT7`（一行宏，但要连带确认通道映射与中值），要么走 §4 的 0x0304。
另外 DT7 是 `=` 覆盖：客户端 0x5A 的"或进去"会和它抢同一份 `key.v`，
两条路只能留一条为准（需要 150ms 那样的仲裁，别再复制 `SPECIAL_CHANNEL_SET_SERO`
当年那个 merge-vs-clear 竞态）。

## 3. `s[0]` 三档（跟"谁在开车"无关，驾驶员的拨杆）

麦轮英雄 `chassis_mecanum.c:97 / :101 / :113`：

* **下方** `CHASSIS_LOCK`：不读驾驶键位图 -> 客户端开不了车（这时"客户端没反应"其实是拨杆在下方）
* **中间**：正常驾驶 + 由 `spin_flag` 决定小陀螺 -> **要验客户端驾驶与小陀螺，必须拨中间**
* **上方**：固件无条件强制自转（`:113` 起），客户端的小陀螺开关此时看着"无效"

全向底盘同构，在 `chassis_omni.c:101 / :105`。

## 4. 官方键鼠链路（0x0304）现状：定义在、解析注释、无下游

* `application/referee/protocol.h:46` `ROBOT_COMMAND_CMD_ID = 0x0304`
* `referee.c:238-241` 整个 `case ROBOT_COMMAND_CMD_ID` 被注释；`:98` 的 memset 也被注释
* 全仓库搜 `robot_command_t`：**除了注释没有任何消费者** —— 就算把解析打开，也得再写
  "0x0304 -> rc_ctrl / 底盘云台指令"的下游映射才有人开车
* 相邻的 `0x0302 自定义控制器`同样只进内存：`referee.c:230-231` 收，
  往上位机转发的代码在 `usb_task.c:122 / :178 / :382 / :577-581 / :1169-1171` 全是注释

## 5. 当前这份固件（英雄 + 客户端驾驶）实际生效的组合

```
遥控器 ET08A ──SBUS──> ch[0..3] + s[0]/s[1]            （驾驶员：摇杆开车、s[0] 选模式）
电脑 ──USB 0x5A──> 0x03 键位  ──|=`key.v`（150ms 有效） （客户端：W/S/A/D 叠加）
                 0x1F 自转    ──> spin_flag（上行 0x04 回读状态）
                 0x04 param0  ──> 云台 yaw/pitch 直控（底盘照旧走键位）
                 0x1E RobotMotion <── 速度/模式回读
UART2 板间：__CONTROL_LINK_RC=CL_RC_DIRECT，未参与覆盖
```
