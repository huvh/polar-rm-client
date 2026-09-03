# 固件补丁：`polar-chassis-sc` — 让上位机驾驶指令真正驱动底盘

对象仓库：https://gitee.com/SMBU-POLARBEAR/StandardRobotpp
基线提交：`2722e0d`（`master`，2026-04-08 最后一次代码推送）
补丁文件：`polar-chassis-sc.patch`（6 个文件，+132 / −2）

---

## 编译前必读：两条不做就“看起来没效果”的前提

> **不想手工做？用一条命令代替下面全部步骤：**
>
> ```bash
> python tools/firmware/prepare_hero_build.py <你的 StandardRobotpp 路径>
> ```
>
> 它会：切兵种到英雄 → 套补丁（驾驶 + 自转桥接 + **速度回读桥 0x1E**）→ 逐项确认所有改动都在 → 用固件真实头文件编译校验 → 最后给出 **GO / NO-GO** 结论。
>
> - **幂等**：重复跑不会重复插入
> - **安全**：工作树里有不属于本脚本范围的改动时直接拒绝，不做半套修改
> - 可撤销：加 `--revert` 还原（只还原它碰过的三个文件）
>
> 跑完报 GO 就可以开 Keil 了。

**1. 烧英雄板必须改兵种开关。** 仓库里 `application/robot_param.h` 当前是：

```c
#include "robot_param_omni_infantry.h"   // 步兵（全向轮）
```

烧英雄要改成 `#include "robot_param_mecannum_hero.h"`。**不改会把全向轮
运动学烧进麦轮车，车会斜着走。**

**2. 上电后必须把遥控器三位拨杆 `s[0]` 从下方拨到中间。**
固件 `ChassisSetMode()` 在 `s[0]` 处于下方时直接进 `CHASSIS_LOCK`，
**那个模式下根本不读驾驶键位图**。拨杆不到位时，补丁打得再对车也不会动。
（ET08A 上 `s[0]` 对应 SBUS 第 5 通道。）

客户端已把这条写进告警：发速度而车没动时，第一建议就是“先确认
遥控器 s[0] 拨杆不在下方”，而不是让人先怀疑补丁。

**3. 验小陀螺（自转）必须拨中间，不能拨上方。**

英雄（麦轮）`chassis_mecanum.c:82-105` 的三档仲裁是：

| `s[0]` | 结果 | 客户端自转指令 |
|---|---|---|
| 下方 | `CHASSIS_LOCK`（`:86`） | 无效，车根本不动 |
| **中间** | `spin_flag ? CHASSIS_SPIN : CHASSIS_FOLLOW`（`:90-97`） | **只有这一档说话算数** |
| 上方 | 无条件 `CHASSIS_SPIN`（`:102`） | 无效，车本来就在转 |

拨上方时车一直在转，看上去像“客户端指令生效了”，其实是固件强制的；
此时再点“关自转”也不会有变化，**极易误判成补丁没打上**。

全向轮步兵不同：`chassis_omni.c:114-117` 上方是 `CHASSIS_FOLLOW`，不冲突。

> 小陀螺的完整来龙去脉（为什么不能再用 SHIFT 键位、新加了哪两段、
> 客户端怎么闭环）见 [`host_bridge/GAPS.md`](host_bridge/GAPS.md)。
> 那份文档还列了其余所有“前端有、固件没”的能力缺口。

## 推荐用的补丁：`polar-virtual-rc-drive-keys.patch`（2 文件 +57/−1）

它只改两个共用文件，**不依赖底盘形式，英雄（麦轮）与步兵（全向轮）同样有效**：

- `usb_task.c`：把上位机 0x03 帧的 `key.v` 按位 OR 进 `rc_ctrl.key.v`，
  带链路新鲜度门控（超过 150ms 不再置位），只放行 W/S/A/D。
  这样固件**已有的**斜坡/限幅/模式机直接复用，不新增控制路径。
- `remote_control.c`：删掉 `SPECIAL_CHANNEL_SET_SERO()` 里的 `rc_ctrl->key.v = 0`。

### 为什么要改第二个文件（竞态修复）

`SPECIAL_CHANNEL_SET_SERO()` 每次收到 SBUS 帧都会执行。调用它的是
**ET08A / AT9S / HT8A 等无键盘遥控器** —— 它们本身不贡献任何键位 bit，
清 0 对遥控器是空操作，**但会把上位机注入的驾驶位图每帧抹掉**，
与 OR 叠加形成 merge-vs-clear 竞态：车速按占空比抖动，最差情况完全不响应。

删掉那行之后补丁不再靠时间常数赌占空比：无键盘的遥控器没有“拥有”
`key.v` 的资格，不应写它。

---

## 重要更正：有比本补丁更省的做法（优先看这里）

深入查过固件后发现，固件里**本来就有一套已生效的 WASD 驾驶**，只是它读的是
物理遥控器的键位位图，不是上位机：

```c
// chassis_omni.c FOLLOW 分支 :171-217，SPIN 分支 :240-293
if (chassis.rc->key.v & KEY_PRESSED_OFFSET_W) { /* 斜坡加速 */ }
// chassis_mecanum.c :157-160 同理
```

而上位机注入这个位图的通路**已经铺到最后一公里**：
`usb_task.c:692-694` 已在接收 0x03 帧 → `:1225` 已 memcpy 进 `VIRTUAL_RC_CTRL`
→ `:272` 已 `Publish`。**只差“把 `VIRTUAL_RC_CTRL` 灌进 `rc_ctrl`”这一步。**

### 方案对比

| | 方案 A（本补丁）| **方案 B（推荐）** |
|---|---|---|
| 做法 | 新增 `CHASSIS_SC` 模式消费 `speed_vector` | 把 `VIRTUAL_RC_CTRL` 接入 `rc_ctrl` |
| 固件改动量 | 6 文件 +132 行 | **约 1–10 行** |
| 是否复用既有驾驶逻辑 | 否，需自己写限幅/归零 | **是**，自带斜坡、低通、限幅、模式机 |
| 风险 | 新增一条并行控制路径 | 小，但必须带链路新鲜度门控 |
| 客户端已就绪 | ✅ | ✅（已实现 0x03 编码） |

### 方案 B 的写法与**必须注意的安全红线**

方案 B 已单独写成可直接应用的补丁：
[`polar-virtual-rc-drive-keys.patch`](polar-virtual-rc-drive-keys.patch)（**1 个文件 +51 行**）。
它只改 `usb_task.c`：新增 `VIRTUAL_RC_RECEIVE_TIME`、`VRC_DRIVE_KEY_MASK`，以及
`UsbMergeVirtualRcKeys()`，并接到 1ms 循环里 `GetVirtualRcCtrlData()` 之后。

> ⚠ **方案 A 与方案 B 互斥，不要两个都打。** 两者都在 `usb_task.c:124` 附近插入
> static 变量，已实测 `git apply` 会冲突。正确做法：先只打 B（最小代价打通驾驶），
> 日后确实需要上位机直接下发物理速度时，再改成只打 A（或手工合并）。

关键设计：用 **按位 OR 叠加**而不是 `memcpy` 覆盖整个 `rc_ctrl`：

```c
static void UsbMergeVirtualRcKeys(void)
{
    uint16_t drive_keys = 0;
    if (!USB_OFFLINE
        && (HAL_GetTick() - VIRTUAL_RC_RECEIVE_TIME) <= VRC_FRESH_TIMEOUT_MS) {
        drive_keys = VIRTUAL_RC_CTRL.key.v & VRC_DRIVE_KEY_MASK;
    }
    rc_ctrl.key.v |= drive_keys;
}
```

为什么不用 `memcpy` 覆盖：那会连带抢走跳杆/鼠标/其他键位，而且链路一断就把
驾驶员的按键冻在最后一帧。OR 叠加下，链路过期后本函数不再置位，下一次 SBUS
刷新就自然回到真遥控器状态。

要点：
1. 为 0x03 单独记了 `VIRTUAL_RC_RECEIVE_TIME`（同 `ROBOT_CMD_RECEIVE_TIME` 的理由：
   `RECEIVE_TIME` 对任意合法包都刷新，不能当驾驶流年龄用）。
2. 客户端已保证**只在驾驶已授权期间发 0x03**，松杆后只补一次全零就彻底停发，
   所以链路空闲时驾驶员摇杆不会被冻结。这有回归测试看着
   （`tests/polar_bridge_test.py::test_drive_channel_gating`）。
3. 客户端默认仍为 `robot_cmd` 通道；在 ClickGUI → RobotLink → **Drive Channel**
   选 `virtual_rc`（方案 B 接线完成后）或 `both`（过渡期）。
4. 云台角度**只能走 0x01**（0x03 的 `RC_ctrl_t` 没有云台字段），所以客户端无论选哪个
   通道都持续发 0x01；选 `virtual_rc` 时 0x01 的 `speed_vector` 写零，避免两套斜坡叠加。
5. 两侧掩码一致：客户端 `polar_link.RC_DRIVE_KEY_MASK` 与固件 `VRC_DRIVE_KEY_MASK`
   都是 `0x000F`（仅 W/S/A/D）。Q/E 会启动摩擦轮、SHIFT 切小陀螺、F 翻 sc_flag，
   这些**绝不允许**从上位机注入，否则绕过“开火权在驾驶员”的纪律。
6. 驾驶键在前端是**可改绑**的（ClickGUI → RobotLink → `Bind <槽位>`），但改绑只改变
   “哪个物理键触发哪个槽”，不改变下发的协议槽位 —— 所以掩码与固件语义都不受影响
   （`tests/polar_bridge_test.py::test_control_keybinds_map_to_protocol_slots`）。

下面保留的方案 A 补丁仍然可用，适用于“希望上位机直接下发物理速度、由客户端做
限幅与斜率控制”的场景（精度更好，但改动大）。

## 为什么需要这个补丁

`rm_custom_client` 已能通过 0x5A 上位机协议下行帧 `ReceiveDataRobotCmd_s`（id=0x01）
发送 `speed_vector.vx/vy/wz`，客户端侧字节编码有逐字节测试覆盖。但下位机侧：

- `GetScCmdChassisSpeed`（`usb_task.c:1275`）与 `GetScCmdChassisVelocity`（`:1297`）
  在 `application/` 下**零调用者** —— 速度发出去没有任何人读，**车不会动**。
- 没有任何断流归零：`GetCmdData()` 每 1ms 无条件把最后一帧拷进控制量，
  `USB_OFFLINE` 分支（`usb_task.c:285-287`）不清数据 —— 上位机崩溃或拔线后
  机器人会**保持最后一条驾驶指令一直执行**。这是安全项。

对照事实：`GetScCmdGimbalAngle` 是被消费的（`gimbal_yaw_pitch_direct.c:336-337`），
所以云台角度今天就能生效；缺的只有底盘这一环。

## 应用与验证步骤

```powershell
cd <StandardRobotpp 仓库根目录>
git apply --check polar-chassis-sc.patch   # 先验证能干净应用
git apply polar-chassis-sc.patch
# 用 Keil MDK 编译（注意工程启用了 --diag_error=warning，警告即错误）
```

补丁基线是 `2722e0d`。若仓库已前进，请用 `git apply -3` 做三方合并。

## 补丁做了什么

1. **`usb_task.c`**：补上三个此前只有声明、没有实现的上位机 API
   （`GetUsbStatus`、`GetScCmdChassisAngle`），并新增 `GetScCmdAge`。
   关键：为驾驶指令流单独维护 `ROBOT_CMD_RECEIVE_TIME`，**只在收到上行
   0x01 RobotCmd 时刷新**。不能用现成的 `RECEIVE_TIME` —— 它对任意 CRC
   通过的包（调参包、虚拟遥控器包）都刷新，那样"0x01 断了但别的包还在发"
   时底盘会带着最后一帧速度一直跑。
2. **`chassis_omni.h` / `chassis_mecanum.h`**：枚举**末尾**追加 `CHASSIS_SC`
   （不插在中间，既有 LOCK/SINGLE/FOLLOW/SPIN 的数值一律不变）。
3. **`chassis_omni.c` / `chassis_mecanum.c`**：
   - `ChassisSetMode`：上档位由 `sc_flag && 链路在线` 共同决定是否进 SC。
     链路一断自动回落到原 RC 模式，不依赖驾驶员反应。
   - `ChassisReference`：新增顶层 `else if (mode == CHASSIS_SC)` 分支，
     读机体系速度、逐轴限幅、`GetScCmdAge() > 150ms` 或链路离线即归零。

## 已做的核查与**没有做的**核查

已核查：

- 补丁可在 `2722e0d` 干净树上 `git apply --check` 通过。
- 补丁引用的每个标识符都追了 include 链确认可见：`fp32_constrain`
  （`components/algorithm/user_lib.h:51`）、`AX_X/AX_Y/AX_Z`
  （`application/typedef/macro_typedef.h:6-8`，经 `remote_control.h` 无条件引入）、
  `CHASSIS_RC_MAX_SPEED/VELOCITY`（`robot_param_omni_infantry.h:87-88` = 1.5f/2.0f；
  `robot_param_mecannum_hero.h:79-80` = 2.0f/2.0f）、`toe_is_error`/`DBUS_TOE`
  （`application/assist/detect_task.h`）。
- `inline` 跨 TU 链接沿用本仓库**已验证可用**的同形先例
  （`GetScCmdGimbalAngle`：`usb_task.c` 内 `inline` 定义 + 头内 `extern inline` 声明 +
  `gimbal_yaw_pitch_direct.c` 跨文件调用），且 `usb_task.c` 与 `chassis_*.c`
  在同一 Keil Target/Group。
- 括号配平、hunk 行号位移自洽；`uint32_t` 与 `150u` 同型比较，无
  `-Wsign-compare` 风险（工程开了 `--diag_error=warning`，这点必须成立）。
- 遥控器权限严格高于 SC：`toe` 故障 / `s[0]` 下档 / 云台未初始化在
  `ChassisSetMode` 首分支即进 `CHASSIS_LOCK`；`s[0]` 拨回中/下档可在一个
  2ms 控制周期内脱离 SC。
- `sc_flag` 的 F 键翻转代码位于 `ChassisConsole` 末尾、**不在任何 mode 分支内**，
  因此 SC 模式下再按 F 能退出，不会死锁。
- `chassis.mode` 全仓无数组下标用法、无 `switch`、无二进制序列化，
  枚举末尾追加不影响任何既有取值。

### 方案 B 已过的编译与行为测试

生成环境没有 ARM 工具链，但有 `zig cc`（自带 clang）。两个脚本仍能把相当多
事情验到：

```bash
python tools/firmware/test_patch_real_headers.py   # 用固件真实头文件编译
python tools/firmware/test_patch_logic.py           # 行为断言（含链接/运行）
```

#### `test_patch_real_headers.py`：拿固件**自己的头文件**编译

它先套补丁，再从打完补丁的真实源文件里抽出函数与宏，`#include "usb_typdef.h"`
/ `"remote_control.h"`（即固件里**真的** `RC_ctrl_t` 定义）后编译。已验证：

- **零错误零警告**通过（`-Wall -Wextra`，对齐 Keil 的 `--diag_error=warning`）
- `_Static_assert(sizeof(RC_ctrl_t) == 22)` 由**固件真实类型**成立
  —— 这同时反证了客户端 0x03 帧布局的假设
- 补丁自带 `extern RC_ctrl_t rc_ctrl;`（头文件**不导出**这个符号，
  只给 const 指针；少了这行 Keil 会直接报 undeclared identifier）
- `rc_ctrl` 在定义处**不是 static**（否则 extern 会链接失败）
- 新增的宏/函数名与全仓既有符号**零冲突**

#### `test_patch_logic.py`：把补丁代码编成可执行并跑行为

- 掩码确实只放行 W/S/A/D；全 1 位图被裁到 `0x000F`
- OR 叠加**不覆盖**遥控器已有的其他键位
- 断流超过 150ms 后不再注入；窗口内正常注入；`USB_OFFLINE` 时不注入
- **`HAL_GetTick` 32 位回绕**：刚回绕仍判新鲜（无符号差值天然正确），
  回绕后真过期也能判出来
- `SPECIAL_CHANNEL_SET_SERO()` 确实不再抹 `key.v`，但**仍照常清鼠标**

> 踩过的坑：`-fsyntax-only` 在 ziglang 的 Windows 轮子上本身是坏的（连
> `int main(){return 0;}` 都报 `FileNotFound`），与代码无关。两个脚本都改成
> 真编到 `.o`/`.exe`，并把驱动层错误单独报出，避免误判成代码有问题。

**仍然没有核查（必须你们补上）**：

- ⚠️ **未经 ARMCC/Keil 完整联合编译**。上面验的是补丁新增代码本身与其类型正确性；
  整个工程的链接、`inline` 跨 TU 行为、代码体积/时序仍只有在 Keil 里才能确认。
  方案 A 的底盘代码**不在这两个测试覆盖范围内**。
- ⚠️ **未上板**。所有时序结论（断流归零最坏时间）来自静态推算，不是实测。

## 上车前必须先确认的三件事（补丁里也标了 TODO）

1. **`vx/vy` 是机体系还是云台系。** `doc/API.md:849-857` 写"底盘坐标系下"，
   但本文件既有 FOLLOW/SPIN 分支都乘了 `cosf/sinf(yaw_delta)`
   （`chassis_omni.c:230-231`、`301-302`），而 SC 分支**不乘**。
   两种语义差一个偏航旋转，搞错会斜着跑。
2. **各轴符号方向。** 协议只给单位，没给正方向。逐轴单发 `+0.2` 观察车体，
   三轴各验一次。
3. **`CHASSIS_RC_MAX_VELOCITY = 2.0 rad/s` 是否适合当上位机 wz 限幅。**
   该宏注释写着"仅用于无云台模式"，而同文件跟随/小陀螺分支的 `wz` 参考值在
   6.6~8.0 量级，2.0 可能明显偏小（表现为转向迟钝）。

另外两处建议（非阻断）：

- `SC_CHASSIS_TIMEOUT_MS` 目前在两个 `.c` 各定义一份，建议上移到公共头，
  避免以后只改一处导致两车型行为分叉。
- 麦轮 SC 分支不推进 `vx_flt/vy_flt`，退出 SC 回 FOLLOW 时滤波器保留进入前的
  旧值，会有一次速度阶跃；LOCK 分支本来也不推进，所以不是新增缺陷，但可顺手重置。

## 本补丁**不**包含的东西

- **`ChassisPublish()`（0x1E RobotMotion 回读）没有实现。** 全向轮/麦轮底盘没有
  速度观测器，能拿到的只有电机转速，要换算成机体系速度需要轮式运动学的逆变换。
  拿"指令值"冒充反馈会让上位机的"车是否响应"检测永远显示正常 —— 那比没有反馈更危险。
  因此 `rm_custom_client` 已改为在缺 0x1E 时用 `0x0A RobotStatus` 的测速模块坐标做
  **位移**判定（阈值 0.05 m），缺回读不再等于无法验收。补上真正的速度观测器
  仍然有价值（2ms 控周期反馈 vs 测速模块低频），但那是独立工作量。
- 摩擦轮 `fric_on` 与 `tracking` 的消费（`GetScCmdFricOn`/`GetSCcmdtracking` 同样
  零调用者）。注意 `fire` 不隐含摩擦轮（`shoot_fric_trigger.c:100-116`），
  只发 `fire` 不会开火。
- 客户端侧 `fire` 恒为 0，本补丁不改变开火权归属。
