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
| 入口 | `usb_task.c` 收 id=0x03 虚拟遥控器 | `remote_control.c:252-263` → `sbus_to_rc()` | `remote_control.c:264-280` → `Et08aSbusToRc()` 等 | `communication.c:221-237`（UART2）／`CAN_receive.c:228-268`（CAN） |
| 怎么写 `key.v` | `UsbMergeVirtualRcKeys()`：`HOST_RC_HOST_KEYS = drive_keys;` 然后写并集（`usb_task.c`） | `HOST_RC_DRIVER_KEYS = key.v;` 然后写并集（`remote_control.c:382` 之后） | 无键位字段 → 置零宏里 `HOST_RC_DRIVER_KEYS = 0;` | **整份 `RC_ctrl_t` memcpy 覆盖** |
| 生效条件 | 客户端三条开关：RobotLink enabled + Allow Drive + Client Chassis Drive，且 Drive Channel=`virtual_rc`；硬件侧只放行 `VRC_DRIVE_KEY_MASK`（W/S/A/D/SHIFT） | 编译期 `__RC_TYPE == RC_DT7`（`robot_param.h:42`） | 编译期 `__RC_TYPE` 选中对应解码器 | `__CONTROL_LINK_RC == CL_RC_UART2 / CL_RC_CAN`；当前 `CL_RC_DIRECT`（`robot_param.h:57`）**这段不参与** |
| 超时 | 150ms 没收到 0x03 → 客户端那份账归零（`VRC_FRESH_TIMEOUT_MS`） | 100ms 没帧 → `receive_count` 断；`GetRcOffline()` 只看"有没有连续收到" | 连续 10 次 `connect_flag` 变化判失联 → `slove_RC_lost()` 重启 DMA | 上层用 `LastReceiveTime.Data_Rc` 判 |
| 语义 | **叠加**，随时可撤 | **叠加**（打桥之后不再是覆盖） | **叠加**（驾驶员侧恒 0） | **覆盖**，会把①②③的结果一起冲掉 —— 与客户端驾驶**不可混用** |

## 2. 为什么英雄板必须 `__RC_TYPE = RC_DT7`（配错的三大症状）

上游仓库出厂写的是 `RC_ET08A`。车上是 DR16 + DT7 配对，所以必须是 DT7。
配错不是"手感差一点"，而是三条硬故障：

1. **`GetRcOffline()` 恒为 true**（`remote_control.c:577-595`）。
   `#if __RC_TYPE == RC_DT7` 把 `sbus_lost_count` 那一项乘 0；而
   `sbus_lost_count` 初值就是 `SBUS_MAX_LOST_NUN + 5 = 15`（`:95`），
   **只有 25 字节那条路径会更新它**。用 ET08A 配置跑 DT7 硬件 ⇒ 该项永远超限
   ⇒ 车判定"遥控器一直离线"：`communication.c:186`、`CAN_communication.c:75`、
   `chassis_balance.c:272`、`music_task.c:194` 全都吃这个判据（底盘保护 +
   离线警报曲一直放）。
2. **键位与鼠标全丢**。18 字节帧只会进 `sbus_to_rc()`；`Et08aSbusToRc()` 只在
   25 字节分支被调用。反过来给 DT7 配 et08a，驾驶员按 W/S/A/D、动鼠标都没人解。
3. **通道中值不对 ⇒ 车自己漂**。DT7/ET08A 中值 1024、AT9S PRO 1000、HT8A 992
   （`remote_control.h:51/56/63/78`）。配错就是摇杆中值偏移几十字。

切换（不要手改宏，重跑准备脚本即可，原始值会记在行尾注释里）：

```
python tools/firmware/prepare_hero_build.py <固件树> --rc dt7      # 默认，比赛用
python tools/firmware/prepare_hero_build.py <固件树> --rc et08a    # 换回上游那种
```

两种取值都用 ARMCC 5.06 全量编过：162 个编译单元 0 error 0 warning。

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

⇒ 结论不变：**想让上位机经图传/裁判链路控车，得自己把 0x0304 的解析与下游补起来**；
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
要把客户端也变成无线的，只有 §5 的 0x0304（补解析）或车上加 USB↔WiFi 透传
（后者现场不稳，不建议当比赛方案）两条路。

## 7. 「电脑插 DT7 的 USB 口，能不能直接把键鼠打上车」——这条必须上台验

仓库里能查到的事实，摆清楚：

- **能确定的**：固件确实会解 DT7 18 字节帧里的键位（bytes14-15）和鼠标位移
  （bytes6-13），并且 `doc/组合使用文档/全向轮步兵.md` 把「键鼠 W/S/A/D」写成了一套正式操作
  （左/右拨杆中档就叫「键鼠控制」）。所以**遥控器面板上的按键**这条输入是通的。
- **不能确定的**：电脑经 DT7 的 USB 口注入的键鼠，DT7 会不会把它填进同一份 SBUS 帧。
  这件事发生在 DJI 遥控器自己的固件里，**本仓库没有任何代码能证明它行**，也没有证明它不行。
- **一条反向线索**：`doc/LOG.md:103-108`（2024-08-05，队内自己的备援设想）写的是
  「遥控器掉线时切换至**图传链路**中同步发送的键鼠数据」，数据源清单第 2 项是「图传键鼠数据」。
  也就是说队内当时把「电脑键鼠」归在**图传/裁判（0x0304）**那条路上，不是 DT7 的 USB 口。
  而 0x0304 的解析在当前固件里是注释掉的（§5）。

**上台就能出结论的验法（不用改任何代码）**：

1. 英雄板按现在的树烧好（`--rc dt7`），车上电、DT7 与 DR16 已对频、`s[0]` 拨中间；
2. 电脑用 USB 线插 DT7 的 USB 口，**不插** C 板；
3. 在电脑上按 W：车动 → DT7 支持 PC 键鼠透传，这条无线控车路成立（但客户端要能产出
   DT7 那种 18 字节键鼠帧，本客户端目前**没有**这条出口，见下）；车不动 → 电脑经 DT7
   控不了车，客户端控车只能继续走 §1 的 ①（USB 直连 C 板 0x5A）。

> 补充：本客户端现在能发的上行是 0x5A 的 0x01/0x03/0x04（`polar_link.py`），
> **没有任何 DT7/USB-HID 出口**（全仓搜过 dt7/dr16/hid/joystick，只有注释和界面文案）。
> 所以第 3 步即使验证通过，也还要再写一条「把客户端按键变成 DT7 键鼠帧」的通路才能真用上；
> 更省事的比赛方案仍然是：驾驶员用 DT7 开车，客户端那条 0x5A 作为叠加的第二入口。
