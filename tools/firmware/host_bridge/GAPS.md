# 电控固件能力缺口清单（客户端无法对齐的部分）

这份文档回答一个问题：**界面上能点的东西，哪些机器人根本收不到，需要电控补什么。**

每条都给了：现象 → 根因（带固件文件:行号）→ 参考现有 STM32 代码的补法（可直接抄的 C）→ 置信度。

置信度标记的含义：

| 标记 | 含义 |
|---|---|
| **已验证** | 我读过固件源码逐行确认，或用真实头文件编译过 |
| **需现场确认** | 源码看是这样，但依赖编译开关/兵种配置，得在你们的 Keil 工程里复核 |
| **待电控确认** | 涉及比赛规则或队伍分工，我不该替你们决定 |

---

## 0. 这个文件夹里有什么

| 文件 | 作用 |
|---|---|
| `host_chassis_bridge.h` | 新头文件，装到 `application/typedef/`。定义上行 0x04 / 下行 0x1F |
| `apply_host_bridge.py` | 一条命令把桥接装进固件树（幂等，带 dry-run） |
| `test_host_bridge.py` | 用固件**真实头文件**编译 + 9 组行为断言 |
| `GAPS.md` | 本文件 |
| `../motion_feedback/` | **第 4 节已补好的速度回读桥**（0x1E），同套用法 |
| `../gimbal_host/` | **第 3 节已补好的云台直控桥**（0x04 param0 bit0），需先套 host_bridge |

```powershell
# 看会改哪些文件（不落盘）
python tools/firmware/host_bridge/apply_host_bridge.py <固件仓库根> --dry-run

# 真装 + 生成补丁
python tools/firmware/host_bridge/apply_host_bridge.py <固件仓库根> --emit-patch tools/firmware/host_bridge/host-bridge.patch

# 校验（编译 + 行为）
python tools/firmware/host_bridge/test_host_bridge.py
```

---

## 1. 已经补好的：小陀螺（自转）

### 现象

客户端点"小陀螺"或"受击后自动小陀螺"，**第一次能开，之后关不掉；再开一次反而把自转关掉**。

### 根因（已验证）

客户端原来唯一的手段是借用虚拟遥控器（上行 0x03）里的 SHIFT 键位。而固件对 SHIFT 是**边沿翻转**，不是电平：

（下表行号按**打完桥之后**的树；未打桥时麦轮早 11 行、全向轮早 13 行。）

| 位置 | 行为 |
|---|---|
| `chassis_mecanum.c:218-221` | FOLLOW 模式下，按下沿 → `spin_flag = 1` |
| `chassis_mecanum.c:264-267` | SPIN 模式下，按下沿 → `spin_flag = 0` |
| `chassis_mecanum.c:226 / :272` | **松手 → 只重置 `shift_pressed`，不动 `spin_flag`** |
| `chassis_omni.c:109-118` | 按下沿 → `spin_flag` 取反 |
| `chassis_omni.c:120` | 松手 → 只记电平（`shift_flag`），不动 `spin_flag` |

所以客户端"松手"永远关不掉自转；下次再"按下"时车已在 SPIN 模式，走的是 `:223` 那条 → 关掉。

客户端侧的 `AutoSpinOnHit` 逻辑本身是对的（`video_backend_mixin.py` 里是 `if spin.enabled != requested: toggle` 的**设定**语义），错在下游只能表达"翻转"。

### 补法（已实现，已用真实头文件编译通过）

新增一对数据段，语义是**设定**：

- **上行 0x04** `ChassisCmd_t`：`spin_cmd` = 0 不干预 / 1 开 / 2 关
- **下行 0x1F** `ChassisState_t`：`spin_state` + `chassis_mode` + `sc_flag`

分工刻意解耦：`usb_task.c` **不 include 任何底盘头文件**（它本来也没有），只收发；底盘各自消费。原因是麦轮和全向轮的 `Chassis_s` 定义不同（麦轮是 `bool shift_pressed`，全向轮是 `uint8_t shift_flag`），让 usb_task 认识 `Chassis_s` 会把编译配置耦死。

底盘侧只加一句，放在 `ChassisSetMode()` 开头：

```c
HOST_CHASSIS_BRIDGE_APPLY(&chassis);
```

`chassis` 是非 static 全局（`chassis_mecanum.c` / `chassis_omni.c` 里都是 `Chassis_s chassis;`），宏只碰 `spin_flag` / `mode` / `sc_flag` 三个字段——这两个字段名在两种底盘里都存在（已核对），所以一份代码两边通用。

### 三个刻意的设计决定

1. **不提供"翻转"取值。** 客户端在收到 0x1F 之前不知道当前状态，发翻转就会在第二次关掉——正是要修的缺陷本身。
2. **模式仲裁完全不碰。** `s[0]` 拨杆、DBUS 超时判断、云台初始化判断都原样保留。物理遥控器永远是最终裁决者。
3. **掉线不主动停转。** 指令超过 150ms 没刷新，固件只是**停止强制**，`spin_flag` 保持原值。自转是防御姿态，上位机断线时突然停转比维持现状更危险；要停由驾驶员停。

> 对应地，客户端在急停和退出时会**显式发 OFF**，因为光停发不会停转。

### ⚠ 英雄板专属陷阱（已验证）

`chassis_mecanum.c:96-118` 的 `s[0]` 拨杆仲裁（行号按打完桥之后的树）：

| 拨杆位置 | 结果 |
|---|---|
| 下方 | `CHASSIS_LOCK`（`:97-99`）——**完全不读 spin_flag**，上位机指令毫无反应 |
| 中间 | `spin_flag ? CHASSIS_SPIN : CHASSIS_FOLLOW`（`:101-112`）——**只有这一档上位机说话算数** |
| 上方 | 无条件 `CHASSIS_SPIN`（`:113`）——**强制常转**，与 spin_flag 无关 |

**所以烧完英雄板必须把 `s[0]` 拨到中间。** 拨上方车会一直转（看起来像"指令生效了"，其实是固件强制的），拨下方车完全不动（看起来像"补丁没打上"）。两种都会误导排查。

全向轮步兵的仲裁不同（`chassis_omni.c:101-130`）：上方是 `CHASSIS_FOLLOW`（`:127-129`），
中间档才处理 SHIFT（`:105-125`），所以不冲突。

---

## 2. 缺口：底盘速度模拟量直控

### 现象

客户端只能靠 WASD 键位开车（8 方向 + 固件斜坡），**无法下发连续的 vx/vy/wz 模拟量**。界面上那些"速度曲线""精确平移"的调法到不了机器人。

### 根因（已验证）

上行 0x01 `RobotCmd` 里字段是有的，固件也收了，但**没有一个消费者**：

| 字段 | 固件取值函数 | 状态 |
|---|---|---|
| `chassis_vx` / `chassis_vy` | `GetScCmdChassisSpeed` | **零调用者** |
| `chassis_wz` | `GetScCmdChassisVelocity` | **零调用者** |
| `leg_length` | `GetScCmdChassisHeight` | **零调用者** |
| `friction_on` | `GetScCmdFricOn` | **零调用者** |
| `tracking` | `GetSCcmdtracking` | **零调用者** |

`GetCmdData()`（`usb_task.c:1203-1221`）确实把这些拷进了 `ROBOT_CMD_DATA`，但底盘侧从来不去读。

### 补法（需现场确认）

参考 `chassis_mecanum.c:157-176` 现有的键位驾驶写法——它已经在做斜坡 + 低通 + 限幅，照抄那套即可：

```c
/* 在 ChassisReference() 里，键位分支之后追加 */
#include "usb_task.h"          /* 麦轮已经 include 了；全向轮需补 */

/* 上位机模拟量直控：仅在键位没有输入时接管，避免两套斜坡叠加 */
if (!(chassis.rc->key.v & (KEY_PRESSED_OFFSET_W | KEY_PRESSED_OFFSET_S
                         | KEY_PRESSED_OFFSET_A | KEY_PRESSED_OFFSET_D)))
{
    fp32 host_vx = GetScCmdChassisSpeed();      /* 已有函数，只是没人调 */
    fp32 host_vy = GetScCmdChassisVelocity();
    if (fabsf(host_vx) > 1e-3f || fabsf(host_vy) > 1e-3f)
    {
        /* 复用现有低通与限幅，不要另写一套 */
        chassis.reference_rc.vx = LowPassFilter(&chassis.vx_flt, host_vx);
        chassis.reference_rc.vy = LowPassFilter(&chassis.vy_flt, host_vy);
    }
}
```

**为什么要"仅在键位无输入时接管"**：客户端现在默认走 `virtual_rc`（0x03 键位）通道，如果 0x01 的模拟量同时生效，两套斜坡会叠加，速度会超出限幅。客户端侧已经做了对应处理（`virtual_rc` 纯通道下把 0x01 的 `speed_vector` 写零），固件侧也要有同样的互斥。

### 这条要不要补，取决于你们

如果只打算用 WASD 键位开车，**不用补**——现在的通路已经能用，而且复用固件既有斜坡更安全。
只有需要连续模拟量（例如视觉伺服底盘、精确对位）才需要。

---

## 3. 已补好的：云台直控的进入条件（0x04 param0 bit0）

### 现象

客户端下发云台角度（0x01 的 `gimbal_pitch` / `gimbal_yaw`），**有时候没反应**。

### 根因（已验证）

这两个字段是 0x01 里**唯一有真实消费者**的控制量：`gimbal_yaw_pitch_direct.c:336`。
但它要求遥控器 `s[0]` 在**上档**才进 `GIMBAL_AUTO_AIM` 模式。

而第 1 节说过：麦轮 `s[0]` 上档 = 底盘无条件 `CHASSIS_SPIN`。

**这两个要求在英雄板上是冲突的**：想让客户端控云台就得拨上档，拨上档车就一直自转。

### 补法（已实现：`tools/firmware/gimbal_host/`，对应上面选项 2）

| 文件 | 作用 |
|---|---|
| `apply_gimbal_host.py` | 一条命令叠加在 host_bridge 之上（幂等，`POLAR-GIMBAL-HOST` 标记）。`prepare_hero_build.py` 已自动串：驾驶补丁 → 自转桥 → 速度回读桥 → 云台直控桥 |
| `test_gimbal_host.py` | 结构断言（安全档/上方档原样、ternary 位置）+ 真实头编译 + 两张真值表（请求位新鲜/过期；中间档 0→IMU、1→AUTO_AIM） |

做法：复用 0x04 里**本来就被固件忽略的 `param0` bit0** 表达"上位机请求云台直控"——

- 中间档 + 请求 -> `GIMBAL_AUTO_AIM`（底盘模式仍由 `spin_cmd`/拨杆决定，
  于是"底盘听 spin_cmd、瞄准听上位机"第一次能同时成立）；
- 中间档 + 无请求 -> `GIMBAL_IMU`，与打桥前逐位相同；
- 下方安全档、上方档语义**一字未动**——物理遥控器仍是最终裁决者；
- 电平 + 150ms 新鲜度（与 spin_cmd 同一条门控）：客户端崩溃/拔线后
  请求自动撤销，云台控制权回到驾驶员；急停时客户端额外强制发 0。

为什么不新加帧：不改帧长/CRC，老上位机发 `param0=0` 永远不请求，
新客户端对老固件发它会被忽略——双向兼容，零协议风险。

选项 3（改上档仲裁）依旧**不做**：那会改变驾驶员操作习惯，属于队伍决定。

---

## 4. 已补好的：速度反馈回读（0x1E）

### 现象

客户端无法直接读到机器人当前速度，只能用位置差分推算。

### 根因（已验证）

下行 0x1E `RobotMotion` 在**全向轮和麦轮 build 上根本不发**：
`chassis_omni.c` / `chassis_mecanum.c` 都没实现 `ChassisPublish()`，落到 `__weak` 空实现 → `chassis_fdb_speed` 从不 Publish → `UsbSendRobotMotionData()`（`usb_task.c:1184-1198`）里 `FDB_SPEED_VECTOR == NULL` 直接 return。
只有平衡底盘 build 会发。

### 补法（已实现，编译+运动学往返已验证）

`tools/firmware/motion_feedback/`：

| 文件 | 作用 |
|---|---|
| `apply_motion_feedback.py` | 一条命令装进固件树（幂等，`POLAR-MOTION-FEEDBACK` 标记，带 --dry-run）。`prepare_hero_build.py` 已自动调用 |
| `test_motion_feedback.py` | 结构断言 + 真实头编译 + **运动学往返**：用固件自己的 `ChassisConsole` 下发式算四轮指令速度，令实测轮速恰等于它，再跑反解，断言机体系速度还原回输入（麦轮/全向轮各三组）。两个方向都逐字取自同一份源码，符号或系数错一个就红 |

与 GAPS 早期草图的两点差别（都是这轮查实后修正的）：

- 平衡底盘的 `ChassisPublish` 只在任务进循环前被调用一次（`chassis_task.c:58`），
  它靠 static `CHASSIS.fdb.speed_vector` 控制环每帧刷新。所以桥的设计是
  **Observer 每帧刷新 static 结构 + Publish 注册地址**，而不是每次调用重算。
- 反解必须与各自 `ChassisConsole` 同系数：麦轮下发式乘 `direction`，反解要除掉
  （±1 自逆）；全向轮下发式没有 direction 项，反解也不能有，且 wz 的符号与麦轮相反。
- `UsbSendRobotMotionData` 的 `FDB_SPEED_VECTOR == NULL` 一次判死改为**惰性重订阅**：
  底盘任务与 USB 任务的启动先后不再有隐含依赖（平衡底盘同样受益）。

### 客户端行为（零改动即受益）

`PolarMotionVerifier` 本来就优先吃 0x1E 实测速度做交叉校验；没打桥时自动退回
0x0A 测速模块坐标的位移验证（能回答"车动没动"，回答不了"速度对不对"）。
打完桥后无需重编译客户端。

---

## 5. 缺口：客户端无法触发自检（sc_flag）

### 现象

下行 0x1F 现在会**上报** `sc_flag`（自检状态），界面上 `SelfCheckMode` 能显示它，但客户端**无法触发**自检。

### 根因（已验证）

固件里翻转 `sc_flag` 的唯一入口是 **F 键**（`chassis_omni.c:334`）。
而 F 键在客户端是**永禁注入**的——它和 Q/E（摩擦轮 = 开火前置执行器）同属"会改变机器人战斗状态"的键位，客户端不碰。

### 补法（待电控确认）

如果确实需要客户端触发自检，正确做法是**在 0x04 里加一个字段**，而不是放开 F 键：

```c
/* host_chassis_bridge.h 里 ChassisCmd_t 的 param0 已经预留 */
#define HOST_SC_CMD_NONE ((uint8_t)0x00)
#define HOST_SC_CMD_RUN  ((uint8_t)0x01)
```

**但这需要先确认一件事**：自检在比赛进行中触发会不会让车进入不可控状态？如果会，这个能力就不该给客户端。所以标记为待电控确认。

---

## 6. 这些不是缺口，是**刻意不补**

| 功能 | 为什么不补 |
|---|---|
| **开火（fire）** | 开火权始终留在驾驶员手上。`encode_robot_cmd()` 的签名里**根本没有 fire 参数**，任何调用点都无法置 1。`polar_link_test` 有不变量断言。 |
| **摩擦轮（Q/E）** | 摩擦轮是开火前置执行器。客户端永禁注入这两个键位，编码器层和固件补丁层双重掩码。 |
| **SHIFT 键位注入** | 已废除。自转改走 0x04。客户端把 SHIFT 做成**结构上不可达**（`RC_MAX_ALLOWED_KEY_MASK == RC_DRIVE_KEY_MASK == 0x000F`，`drive_key_mask()` 忽略 `allow_spin` 参数），而不是仅靠调用方传 False——后者只要有一个遗漏的调用点就会漏。 |
| **地图标记 / 经济兑换 / 飞镖** | 这些是**裁判系统**的功能（`MAP_COMMAND` / `ROBOT_INTERACTION` / `DART_CLIENT_CMD`），走官方链路，不该从机器人 USB 下发。界面上对应模块只有官方出口，这是正确的。 |
| **哨兵指挥** | 下行 0x15 `SentryInfo` 是机器人**上报**哨兵信息，不是指挥通道。哨兵本身是自动驾驶的，客户端指挥它没有意义。 |

---

## 7. 客户端侧的诚实降级

补固件需要时间，所以客户端**不会假装成功**。每条缺口都有对应的可观测降级：

| 缺口 | 客户端行为 |
|---|---|
| 固件未打 host_bridge（收不到 0x1F） | 自转状态显示为"指令已发、无法确认"，不是"已开启"。`manager.polar_chassis_state_seen` 为 False 时不声称闭环。 |
| 无回读时要关自转 | OFF 只发 1 秒（`SPIN_OFF_ASSERT_S`）然后放手为 NONE。**绝不无限压制**——那会永久锁死驾驶员用物理遥控器开自转的能力。 |
| 0x1E 停发 | 自动切到 0x0A 位移验证，HUD 上标明是位移推算而非实测速度。 |
| 云台角度被 s[0] 挡住 | readiness 里出告警。步兵：s[0] 上档即可；
 英雄：打第 3 节的 gimbal_host 桥后用中间档 + 直控请求，不必上档 |

---

## 8. 验证等级说明

我做到哪一步、没做到哪一步，说清楚：

| 等级 | 状态 |
|---|---|
| 补丁代码用**固件真实头文件**编译（clang，`-Wall -Wextra`，零警告） | ✅ 已过 |
| 补丁代码**行为断言**（开→保持→关→再开→掉线→遥控器接管→tick 回绕，9 组） | ✅ 已过 |
| 客户端端到端断言（SpinMode 模块状态 → 上线字节 → 0x1F 回读 → 收敛） | ✅ 已过 |
| **整工程编译体检**（arm-none-eabi-gcc 差分，见 8.3） | ✅ 已过（补丁新增诊断 0 条） |
| **Keil（ARMCC）真实编译** | ❌ 本机装不上：官方 MDK 安装包要走邮箱申请表单或 Arm 账号登录，脚本拿不到 |
| **烧录后上板实测** | ❌ 未验证 |

原先这一节写的是"Keil 报错就删掉 `host_chassis_bridge.h` 里那 4 行
`_Static_assert`，纯防呆"。**这句话本身是错的**：那 4 行留着就会当场编译失败，
不是"可能报错"。2026-09-03 用 GCC 差分把整工程扫了一遍，抓出 4 类真拦路虎，
全部已在补丁脚本里修掉，记录如下。

### 8.1 该工程的 ARMCC 事实（从 `MDK-ARM/standard_robot.uvprojx` 读出来的）

| 事实 | 出处 | 后果 |
|---|---|---|
| 编译器锁 ARMCC 5.06 update 4 | `<pCCUsed>5060422::V5.06 update 4` | 不认 C11 的 `_Static_assert` |
| 语言是 C99 | `<uC99>1</uC99>` | 只能用 C99 + AC5 扩展 |
| **警告即错误** | `<MiscControls>--diag_error=warning</MiscControls>` | 隐式声明 #223-D 之类**一律编译失败** |
| 片型 STM32F407IGHx，需要 DFP pack | `<Device>` / `<PackID>Keil.STM32F4xx_DFP.2.17.1` | 命令行编译前得先装 pack（`https://www.keil.com/pack/Keil.STM32F4xx_DFP.2.17.1.pack` 可直连下载） |
| FreeRTOS 用 RVDS 端口 | include 路径 `portable/RVDS/ARM_CM4F` | `port.c` 是 ARMCC 内联汇编，**非 ARMCC 编译器编不了**（差分检查已排除它） |

### 8.2 抓出来的 4 个真实编译拦路虎（都已修）

1. **挤行 include**：`apply_motion_feedback.py` 的 `to_eol()` 对"不含换行的锚点"
   不补换行，插进去的 `#include "custom_typedef.h"` 与上一行的
   `#include "chassis_power_control.h"` 挤成了同一行。预处理器会把第二条
   include 当多余 token 吞掉 —— 少的是类型定义，报错的却是八竿子打不着的地方。
   两个底盘文件都中招。
2. **`chassis_update_fdb_speed()` 缺前置声明**：函数体排在 `ChassisObserver()`
   之后、调用在前面。AC5 单遍编译报 #223-D，而本工程的 `--diag_error=warning`
   把它升级成错误。
3. **`GetChassisCmdData()` / `UsbSendChassisStateData()` 同样缺前置声明**：
   定义在 usb_task.c 后段，主循环与 UsbSendData 在前面就要调用。
4. **`_Static_assert`**：改成只依赖 C89 的 `HOST_BRIDGE_STATIC_ASSERT`
   （数组尺寸技巧），AC5/AC6/GCC 三家通吃，防呆能力不变。

顺带修掉一个**更阴的坑**：`apply_host_bridge.py` 的幂等探针原本是"子串包含"。
加了前置声明之后，探针 `static void GetChassisCmdData(void)` 成了声明行
`static void GetChassisCmdData(void);` 的子串，于是**函数体被误判成"已存在"
而静默跳过** —— prepare 照样报 GO，实际 usb_task 里只剩一句调用。现在改成
"整行相等"才算已存在，`test_host_bridge.py` 里留了注释。

### 8.3 没有 Keil 时怎么做整工程体检（`gcc_syntax_check.py`）

思路是**差分**：临时 `git worktree` 出一份未打补丁的 HEAD，两棵树跑同一条 GCC
命令，只比诊断差集。基线自身噪音（`__packed`、RVDS 的 `__asm {}`、newlib
`int32_t` 与 `struct_typedef.h` 冲突、`LAST_SEND_TIME.##name` 粘贴）两边相同，
互相抵消，剩下的一定是补丁造成的。

```bash
# 一次性准备工具链：xPack 的 GCC。GitHub 直连会被重置，走 gh-proxy 前缀可用
curl -L -o gcc.zip "https://gh-proxy.com/https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v15.2.1-1.1/xpack-arm-none-eabi-gcc-15.2.1-1.1-win32-x64.zip"
# 解压后指两个环境变量（shim 目录里放 keil_compat.h 与 portmacro.h 替身）
set POLAR_GCC=D:\toolchain\gx\xpack-arm-none-eabi-gcc-15.2.1-1.1\bin\arm-none-eabi-gcc.exe
set POLAR_GCC_SHIM=D:\toolchain\shim
python tools/firmware/prepare_hero_build.py <固件路径> --gcc-check
```

**边界必须讲清楚**：GCC 差分 != ARMCC 通过。AC5 独有的坑它看不见，所以
`verify_changes` 里另加 4 条人工规则当守门（挤行 include、`_Static_assert`、
两处前置声明）；反过来 GCC 也不会把 AC5 的全部警告类别都报出来。
真正上板前仍然必须过一次 Keil 编译 —— 这一条现在有了不用装 Keil 的做法，见 §8.5。

### 8.4 测试之间的树状态耦合（已修）

五个固件测试共用 `tmp_polarbear/StandardRobotpp` 这一份工作树，而
`test_patch_logic.py` 收尾会 `git checkout -- .` 把 .c 还原，**未跟踪的桥接头文件
却留在那儿**。另外三个测试原本用"头文件是否存在"判断"桥是否已装"，于是会拿
"未打桥的 .c + 已存在的 .h" 这种半套状态去校验，报"找不到函数体"。
现在三处判定全部改成看 usb_task.c 里的标记内容，顺序怎么排都稳。

> 副作用记住一条：跑过这五个测试之后，固件副本会被还原成基线。
> 要回去编译，重新 `prepare_hero_build.py <路径>` 一次即可（幂等，约 20 秒）。

烧完板请把 `field_evidence/polar-selftest-*.json` 带回来，我能据此判断实际哪一环没通。

### 8.5 已经过一次**真 ARMCC 5.06** 全工程体检（`../armcc_check/`）

上一节那句"仍然必须过一次 Keil 编译"已经补上了：`armcc_check/` 用真
ARMCC 5.06 update 7 + 工程自己的 include/define/`--diag_error=warning`，
把 162 个编译单元全过了一遍，工具链和 MDK-Lite 的本地映射都是离线取的，
**没装 Keil、没写注册表、没碰破解工具**。

| 阶段 | 结果 |
|---|---|
| `armcc` x161 + `armasm` x1 | 162/162 通过，0 error / 0 warning |
| `armlink --partial`（含 2 个 ARM 库） | rc=0，L6218E 未定义符号 0 个 |
| `armlink --scatter`（F407 内存布局） | `L6050U: code size (109628 bytes) exceeds the maximum allowed` —— MDK-Lite 的 32KB 授权上限，不是代码问题 |

这一轮抓出来的**唯一真实编译错误**：`IMU_solve.c:452` 无条件用
`__GYRO_BIAS_YAW`，而仓库 11 个 `robot_param_*.h` 里只有 3 个定义了它，
英雄与步兵两个参数文件都没有 -> `Error: #20: identifier ... is undefined`。
上游基线（步兵配置）同样编不过，**不是打补丁造成的**。现在由
`prepare_hero_build.py` 的 `switch_to_hero()` 在 `robot_param.h` 插
`#ifndef __GYRO_BIAS_YAW` 兜底定义（值沿用仓库其它机型），`--revert` 一起还原。

另外记一条硬结论：**这份固件出镜像只能用 ARMCC**。
`AHRS.lib` / `arm_cortexM4lf_math.lib` 是 ARM 目标格式，GNU `ld` 读不了，
所以"Lite 卡 32KB 就改用 GCC 链"这条路走不通，要出 hex 就得挂一份能过
32KB 的 MDK 授权。取工具链 / 过 license / uVision 命令行编译的具体做法，
见 `../armcc_check/README.md`。

**并且已经在真 uVision 5.43.1.0 里复现过同一结论**（37 秒全量）：
`Using Compiler 'V5.06 update 7 (build 960)'` -> 161 个 .c + 1 个 .s 全过 ->
`linking... L6050U: The code size of this image (140444 bytes) exceeds the maximum
allowed for this version of the linker.` -> `1 Error(s), 0 Warning(s)`。
即 IDE 与命令行一致：只有 MDK-Lite 的 32KB 授权上限拦着，代码本身没有编译问题。
安装三要点（`--batch-install` 有效 / AC5 要写进 TOOLS.INI 的 ARMCCPATH /
DFP pack 不装会重写掉 `RTE_Components.h` 里的 `CMSIS_device_header`）见
`../armcc_check/install_keil.ps1` 与 README §7。


---

## 9. 已补好的：遥控器类型（DT7/DR16）与键位三方写入者

> 这一节是比赛链路相关最要紧的一条。详细链路表见 `RC_LINKS.md`。
> **注意**：本节早先一版把 `__RC_TYPE` 的后果写重了（"底盘锁死 + 警报曲不停"），
> 2026-09-03 逐行核过之后已在下面更正 —— 结论是"键鼠开车本来就能用，
> 客户端叠加这条路本来不通"。

### 现象（改之前真实存在的缺陷）

1. 客户端驾驶键位在 DT7 车上**每帧被抹掉**：`remote_control.c:382` 是
   `key.v = sbus_buf[14] | (sbus_buf[15] << 8)` 整字段覆盖，而 `usb_task.c`
   里是 `key.v |= drive_keys` 只置位 —— 两者抢同一个字段。
2. 换到无键盘遥控器（ET08A 等）时反过来出事：没人清 `key.v`，
   客户端**一松键位就永久粘住，车刹不住**；当年靠置零宏每帧清 0 掩盖，
   又与 `|=` 形成 merge-vs-clear 竞态（车速按帧率抖动）。
3. `chassis_mecanum.c` 的 SHIFT 是边沿检测：键位"抹一下补一下"会让
   `shift_pressed` 反复翻转 —— 小陀螺开关自己乱跳。
4. `__RC_TYPE` 出厂是 `RC_ET08A`，车上是 DT7+DR16 —— 配置在说谎，并且
   `GetRcOffline()` 恒真（后果范围见 `RC_LINKS.md` 第 2 节的更正表：
   板间广播 `rc_offline` 恒 1、平衡底盘会置错误位；麦轮本车运动不受影响）。

### 根因（都核到行号）

| 事实 | 位置 |
|---|---|
| SBUS 按**帧长**分派：18 字节无条件进 `sbus_to_rc()` | `remote_control.c:252-263` |
| DT7 解出鼠标与键位，且 `key.v` 是**整字段覆盖** | `remote_control.c:377-382` |
| 25 字节才按 `__RC_TYPE` 选解码器；选不中 = 整帧不解析 | `remote_control.c:264-280` |
| 非 DT7 解码器不写 `key.v`，还把鼠标置零 | `remote_control.c:508-530` + `SPECIAL_CHANNEL_SET_SERO()` |
| `#if __RC_TYPE == RC_DT7` 决定 `GetRcOffline()` 看不看 `sbus_lost_count`；后者初值即超限、只有 25 字节路径更新 | `remote_control.c:95 / :577-595` |
| 离线判据的下游范围（麦轮不锁、警报曲默认关） | `communication.c:186`、`CAN_communication.c:75`、`chassis_balance.c:272`、`chassis_task.c:98`、`music_task.c:38` |

### 补法（已实现）

1. **`prepare_hero_build.py --rc dt7|et08a|at9s|ht8a`，默认 `dt7`**：只改
   `robot_param.h` 那一行，仓库原始值记在行尾注释，可反复来回切。
2. **键位账本**（`host_chassis_bridge.h` + `apply_host_bridge.py` 三处改写）：
   `HOST_RC_DRIVER_KEYS`（SBUS 侧写；非 DT7 恒 0）与 `HOST_RC_HOST_KEYS`
   （usb_task 写，含 150ms 新鲜度门控），两个写入者都只通过
   `HOST_RC_MERGED_KEYS()` 把并集写回 `key.v`。
   ⇒ 驾驶员与客户端键位**并存**、谁撤谁归零、换遥控器不残留，三个缺陷一次消掉。


### 验证等级

| 级别 | 内容 | 结果 |
|---|---|---|
| L1 静态 | `verify_changes` 新增 6 条守门（RC 类型、两处写并集、宏清账、掩码、无 `|=`） | 全 OK |
| L2 编译 | ARMCC 5.06 全工程，**dt7 与 et08a 两种取值各编一遍** | 162/162 单元 0 error 0 warning；partial link 未定义符号 0 |
| L2b | 真 uVision 5.43.1 命令行 `-b`（dt7 树） | 162 文件全过、0 warning，只剩 `L6050U` MDK-Lite 32KB 上限（镜像 139824 字节）；日志 `../armcc_check/uvision_build_log_dt7.txt` |
| L3 行为 | 新增 `test_rc_key_ledger.py`：把真实源文件里抽出的代码编成 exe，按 50Hz 遥控帧 + 1ms 主循环跑时序 | 8 组断言全绿；`--negative` 阴性对照下旧写法被抓到 4 处 |
| L4 回归 | `verify_all.py --firmware` | **GO，34 组全通过**（原 33 组 + 键位账本 1 组） |
| **未验** | 真车：DT7 与 DR16 实际对频后摇杆方向、中值、拨杆三档 | 需要硬件 |

### 踩过的两个坑（顺手记下来）

* **`apply_host_bridge.py` 现在依赖驾驶补丁先落地**（键位那步是"改写" `|=` 那行）。
  以前单独跑它会撞"锚点未找到"，把 `test_host_bridge.py`、`test_gimbal_host.py`
  的自举路径整片带崩。现在脚本自己会先 `git apply` 那个补丁（`ensure_drive_keys_patch`），
  顺序不再是坑。
* **`test_rc_key_ledger.py` 一开始写的是"补丁没在树里就 SKIP 并 return 0"**，
  于是 verify_all 报 GO 却根本没测键位。现在改成：缺就自己装上、测完还原。
  *一声不响的跳过比失败更危险。*

### 顺带修正一处旧结论

之前在这里写过"车上必须真插一根 USB 线，电脑才能控车"。这句话**只对客户端控车成立**：
比赛主链路（电脑→DT7→DR16→UART3）本身就是无线控车，不需要 USB 线。
USB 线带来的是**客户端这条第二入口**（0x5A：0x03 键位、0x04 指令）与回读（0x1E/0x1F）。
