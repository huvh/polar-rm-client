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

| 位置 | 行为 |
|---|---|
| `chassis_mecanum.c:177-183` | FOLLOW 模式下，按下沿 → `spin_flag = 1` |
| `chassis_mecanum.c:223-229` | SPIN 模式下，按下沿 → `spin_flag = 0` |
| `chassis_mecanum.c:187` | **松手 → 只重置 `shift_pressed`，不动 `spin_flag`** |
| `chassis_omni.c:96-106` | 按下沿 → `spin_flag` 取反 |
| `chassis_omni.c:107` | 松手 → 只记电平，不动 `spin_flag` |

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

`chassis_mecanum.c:82-105` 的 `s[0]` 拨杆仲裁：

| 拨杆位置 | 结果 |
|---|---|
| 下方 | `CHASSIS_LOCK`（`:86`）——**完全不读 spin_flag**，上位机指令毫无反应 |
| 中间 | `spin_flag ? CHASSIS_SPIN : CHASSIS_FOLLOW`（`:90-97`）——**只有这一档上位机说话算数** |
| 上方 | 无条件 `CHASSIS_SPIN`（`:102`）——**强制常转**，与 spin_flag 无关 |

**所以烧完英雄板必须把 `s[0]` 拨到中间。** 拨上方车会一直转（看起来像"指令生效了"，其实是固件强制的），拨下方车完全不动（看起来像"补丁没打上"）。两种都会误导排查。

全向轮步兵的仲裁不同（`chassis_omni.c:86-118`）：上方是 `CHASSIS_FOLLOW`，中间才处理 SHIFT。

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

## 3. 缺口：云台角度控制的前置条件

### 现象

客户端下发云台角度（0x01 的 `gimbal_pitch` / `gimbal_yaw`），**有时候没反应**。

### 根因（已验证）

这两个字段是 0x01 里**唯一有真实消费者**的控制量：`gimbal_yaw_pitch_direct.c:336`。
但它要求遥控器 `s[0]` 在**上档**才进 `GIMBAL_AUTO_AIM` 模式。

而第 1 节说过：麦轮 `s[0]` 上档 = 底盘无条件 `CHASSIS_SPIN`。

**这两个要求在英雄板上是冲突的**：想让客户端控云台就得拨上档，拨上档车就一直自转。

### 补法（待电控确认）

这不是 bug，是原有的模式设计。三个选项：

1. **不改**：客户端云台控制只在步兵（全向轮）上用——全向轮 `s[0]` 上档是 `CHASSIS_FOLLOW`（`chassis_omni.c:114-117`），不冲突。
2. 给 `GIMBAL_AUTO_AIM` 增加一个不依赖 `s[0]` 的进入条件（例如上位机显式请求）。
3. 麦轮上档改成"由 `spin_flag` 决定"，与中间档统一。

选项 3 会改变现有驾驶员的操作习惯，**我不建议客户端侧替你们决定**。

---

## 4. 缺口：速度反馈停发（0x1E）

### 现象

客户端无法直接读到机器人当前速度，只能用位置差分推算。

### 根因（已验证）

下行 0x1E `RobotMotion` 在**全向轮和麦轮 build 上根本不发**：
`chassis_omni.c` / `chassis_mecanum.c` 都没实现 `ChassisPublish()`，落到 `__weak` 空实现 → `chassis_fdb_speed` 从不 Publish → `UsbSendRobotMotionData()`（`usb_task.c:1184-1198`）里 `FDB_SPEED_VECTOR == NULL` 直接 return。
只有平衡底盘 build 会发。

### 补法（需现场确认）

在两个底盘文件里补 `ChassisPublish()`，参考平衡底盘的实现：

```c
void ChassisPublish(void)
{
    static ChassisFeedbackSpeed_t chassis_fdb_speed;   /* 名字以平衡底盘实现为准 */
    chassis_fdb_speed.vx = chassis.feedback[0];        /* 或用解算后的机体速度 */
    chassis_fdb_speed.vy = chassis.feedback[1];
    chassis_fdb_speed.wz = chassis.reference.wz;
    Publish(&chassis_fdb_speed, CHASSIS_FDB_SPEED_NAME);
}
```

### 客户端已做的降级

不补也能跑：客户端用下行 0x0A `RobotStatus` 里的**测速模块坐标**做位移验证（`polar_motion.py`）。
但位移验证只能回答"车动没动"，回答不了"速度对不对"，而且有 50ms 上报周期的量化误差。

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
| 云台角度被 s[0] 挡住 | readiness 里出告警，说明需要 s[0] 上档。 |

---

## 8. 验证等级说明

我做到哪一步、没做到哪一步，说清楚：

| 等级 | 状态 |
|---|---|
| 补丁代码用**固件真实头文件**编译（clang，`-Wall -Wextra`，零警告） | ✅ 已过 |
| 补丁代码**行为断言**（开→保持→关→再开→掉线→遥控器接管→tick 回绕，9 组） | ✅ 已过 |
| 客户端端到端断言（SpinMode 模块状态 → 上线字节 → 0x1F 回读 → 收敛） | ✅ 已过 |
| **Keil（ARMCC）编译** | ❌ 我无硬件无 Keil，未验证 |
| **烧录后上板实测** | ❌ 未验证 |

`test_host_bridge.py` 用的是 ziglang 提供的 clang，不是 ARMCC。两者的差异主要在 `__packed__`（`attribute_typedef.h` 已把它定义为 `__attribute__((packed))`，clang 原生支持）和 `_Static_assert`（C11，ARMCC 5 需要 `--c99` 或改用编译期数组技巧）。**如果 Keil 报 `_Static_assert` 相关错误，把那 4 行删掉即可，它们只是防呆，不影响功能。**

烧完板请把 `field_evidence/polar-selftest-*.json` 带回来，我能据此判断实际哪一环没通。
