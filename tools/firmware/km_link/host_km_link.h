/**
 * @file    host_km_link.h
 * @brief   图传/裁判链路的键鼠注入 + __CONTROL_LINK_KM 五档仲裁
 *          安装位置 application/typedef/host_km_link.h
 *          生成方式 tools/firmware/km_link/apply_km_link.py（标记 POLAR-KM-LINK）
 *
 * 一、这块补的是什么
 * ------------------
 * 固件作者早就在 application/typedef/robot_typedef.h:80-84 定义好了五档
 * "键鼠数据从哪来"（CL_KM_NONE / CL_KM_RC / CL_KM_VT / CL_KM_RC_VT /
 * CL_KM_VT_RC），但全仓库**没有任何一处代码读它**——零消费者的脚手架。
 * 数据来源那侧也是断的：0x0311（自定义客户端->机器人，30 字节，75Hz）
 * 在 referee.c:247 已经 memcpy 进了 robot_custom_data_3，但往上层交接的
 * 那几行（usb_task.c:125/181/392/605-609/1216-1219）全是注释。
 * 数据躺在内存里，没人读。
 *
 * 本文件把这条链路接完，并且是把队内自己的设计做完，不是另起炉灶。
 *
 * 二、为什么用 0x0311 而不是"复活 0x0304"
 * --------------------------------------
 * 大疆《RM2026 通信协议》V1.3.0（2026.03.26）修改日志明写
 * **"删除命令码 0x0304"**，原 RemoteControl 拆成 KeyboardMouseControl(75Hz)
 * 与 CustomControl(<=30B,75Hz)。所以把 referee.c:238 那段注释掉的 0x0304
 * 补回来是错的目标——新赛季的裁判系统根本不会再发这个包。
 *
 * 而 0x0311 的 30 字节是**"自定义指令"，内容完全由队伍自己定**，
 * 所以我们不依赖大疆对键鼠的任何语义：客户端这边早就在同一个通道上
 * 跑队内协议 PRM1（rm_client/backend/protocol.py 的 TEAM_CONTROL_MAGIC，
 * kind=1 云台 / kind=2 自转），本文件只是给它加一个 kind=3 键鼠。
 *
 * 三、仲裁规则（"互补/优先"到底怎么落地，这里定死）
 * ------------------------------------------------
 * rc_ctrl.key.v 有三个写入者，全部走 host_chassis_bridge.h 里那一个表达式：
 *      key.v = (驾驶员键位 & 门闸) | 上位机 0x5A 键位 | 图传键位
 *
 *   CL_KM_RC   （默认，现役车）图传一律不参与：KM_KEYS=0、门闸全开、
 *                        鼠标一个字节都不动 -> 与打补丁前逐位相同，零风险
 *   CL_KM_NONE 两路键鼠都屏蔽（连驾驶员键位也屏蔽，照字面语义实现）
 *   CL_KM_VT   只认图传：关驾驶员键位门闸；图传过期即键位 0、鼠标 0
 *   CL_KM_RC_VT 互补、遥控器优先：键位两路或起来；鼠标驾驶员这帧非零
 *                        就用驾驶员的，否则用图传的
 *   CL_KM_VT_RC 互补、图传优先：键位两路或起来；鼠标图传新鲜就用图传的
 *
 * 键位在两个混合档里行为相同，是因为键位是**位图**，"互补"天然就是按位或；
 * 真正需要选的是**鼠标**——它是增量，两路相加会让云台乱甩。所以"优先"
 * 只体现在鼠标上，这一点写死在这里，别照宏名猜。
 *
 * 四、底线（读代码的人最该知道的两件事）
 * ------------------------------------
 * 1) 任何一档都**不屏蔽摇杆 ch[] 和拨杆 s[]**。就算配成 CL_KM_VT 且图传
 *    当场断掉，驾驶员仍然能用摇杆和拨杆把车开回来、把模式锁掉。
 * 2) 默认只放开 W/S/A/D/SHIFT（0x001F）。Q/E 直接连着摩擦轮与开火，
 *    **开火权限不由这段代码偷偷给**，要放开得显式跑
 *    prepare_hero_build.py --km-fire-keys。
 */

#ifndef HOST_KM_LINK_H
#define HOST_KM_LINK_H

#include "robot_param.h"        /* __CONTROL_LINK_KM / CL_KM_* */
#include "struct_typedef.h"
#include "remote_control.h"     /* RC_ctrl_t */

#ifdef __cplusplus
extern "C" {
#endif

/*--------------------------- PRM1 键鼠载荷 ---------------------------*/
/*
 * 承载在 0x0311 的 30 字节里，前 4 字节魔数 + 版本 + 类型 + 序号，
 * 与客户端 rm_client/backend/protocol.py 的 TEAM_CONTROL_* 逐项对齐。
 * 裁判协议整帧已有 CRC16，这里不再叠一层校验。
 */
#define PRM1_MAGIC_0 ((uint8_t)'P')
#define PRM1_MAGIC_1 ((uint8_t)'R')
#define PRM1_MAGIC_2 ((uint8_t)'M')
#define PRM1_MAGIC_3 ((uint8_t)'1')
#define PRM1_VERSION ((uint8_t)1)
#define PRM1_KIND_VISION ((uint8_t)1)
#define PRM1_KIND_SPIN ((uint8_t)2)
#define PRM1_KIND_KM ((uint8_t)3) /* 本文件新增：键鼠 */

/** 图传键鼠载荷，8 字节有效域 + 2 字节头，落在 30 字节自定义数据的前 18 字节内 */
typedef struct
{
    uint8_t magic[4];   /* 'P','R','M','1' */
    uint8_t version;    /* PRM1_VERSION */
    uint8_t kind;       /* PRM1_KIND_KM */
    uint16_t seq;       /* 每帧 +1，客户端用来证明链路活着；固件只做新鲜度参考 */
    uint16_t keys;      /* 键位位图，位序同 remote_control.h:103-118 */
    int16_t mouse_x;    /* 与 SBUS bytes6-7 同义：本帧 X 位移，负=左 正=右 */
    int16_t mouse_y;    /* 同 SBUS bytes8-9 */
    int16_t mouse_z;    /* 同 SBUS bytes10-11，滚轮 */
    uint8_t buttons;    /* bit0 左键 bit1 右键 bit2 中键 */
    uint8_t flags;      /* bit0: 客户端声明"本帧是有效键鼠帧"（心跳位） */
    uint8_t reserved[8];
} __packed__ prm1_km_cmd_t;

typedef char HOST_KM_STATIC_ASSERT_size[(sizeof(prm1_km_cmd_t) <= 30) ? 1 : -1];
typedef char HOST_KM_STATIC_ASSERT_pack[(sizeof(prm1_km_cmd_t) == 26) ? 1 : -1];  /* 4+1+1+2+2+2+2+2+1+1+8 */

/*--------------------------- 门限与掩码 ---------------------------*/
/* 0x0311 上限 75Hz（周期约 13ms），300ms 容得下连丢二十来帧；
 * 与本工程裁判系统超时 REFEREE_TIMEOUT(referee.c:27) 取同一量级。 */
#define KM_LINK_VALID_MS ((uint32_t)300)

/* 允许经图传注入的键位。默认驾驶键四位 + SHIFT，与 USB 0x5A 那条路一致。 */
#define KM_KEY_MASK_DRIVE ((uint16_t)0x001F) /* W S A D SHIFT */
#define KM_KEY_MASK_FIRE ((uint16_t)0x00C0)  /* Q E：摩擦轮/开火相关 */
/* --km-fire-keys 会把这条改成 (DRIVE|FIRE)。取值由 prepare_hero_build.py 写死。 */
#ifndef KM_KEY_ALLOWED_MASK
#define KM_KEY_ALLOWED_MASK KM_KEY_MASK_DRIVE
#endif

/*--------------------------- 交接量 ---------------------------*/
/*
 * 0x0311 的收包时刻。由 referee.c 在解包现场刷新（那里才有 HAL_GetTick
 * 与收包顺序），本文件的仲裁函数只读它做新鲜度判断。
 */
extern volatile uint32_t HOST_KM_RX_TIME;
extern volatile uint32_t HOST_KM_RX_COUNT; /* accepted canonical PRM1 KM payloads only */

/**
 * @brief 图传键鼠是否新鲜
 * @note  刻意不看 referee_online_time：裁判系统别的包在线、但客户端没发
 *        0x0311 时，这里必须是 false，否则会把上一帧键鼠当成还活着。
 */
#define HOST_KM_IS_FRESH()                                                   \
    ((HOST_KM_RX_COUNT != 0) && ((HAL_GetTick() - HOST_KM_RX_TIME) <= KM_LINK_VALID_MS))

/**
 * @brief 键鼠链路仲裁：刷新 HOST_RC_KM_KEYS / 驾驶员键位门闸 / 鼠标来源
 *
 * 两个调用点（都在实现里按 __CONTROL_LINK_KM 编译期分档，默认档直接返回）：
 *   - usb_task 主循环，1ms 一轮：负责"图传过期了要归零"这件事，
 *     这样即使遥控器一帧不来（车上没插 DBUS、或 0x0311 是唯一链路），
 *     键位也不会粘在最后一帧上；
 *   - remote_control.c 的 SBUS 解码末尾：负责"这一帧驾驶员的鼠标增量
 *     要不要让给图传"，因为鼠标是增量，晚一个周期就用不上了。
 */
void HostKmLinkUpdate(void);

/**
 * @brief SBUS 解码每帧调用：先记驾驶员鼠标账，再按档位决定鼠标用谁
 * @param rc 正在被填充的 rc_ctrl（与全局 rc_ctrl 同一对象）
 */
void HostKmApplyDriverFrameMouse(RC_ctrl_t *rc);

/**
 * @brief 从**别的来源**灌一帧 0x0311 载荷（给"包没走裁判口"这种情况留的接口）
 * @param payload 完整 PRM1 kind=3，26..30 字节；截断/非法帧不更新邮箱与新鲜度
 * @param len     字节数
 * @return 1=accepted canonical KM payload (including alive=0), 0=rejected
 *
 * 为什么必须有这个口：官方《2026 通信协议》表 1-1 写 `图传发送端←→机器人 921600`，
 * 1.1 节写图传链路"从图传模块（发送端）的串口接收数据"，而本板裁判口是
 * `huart6`@115200（常规链路，来自电源管理模块 User 口）。也就是说
 * **0x0311 很可能根本不在 huart6 上**。现场一旦发现回读是 `NO-RX!!`，
 * 修法就是"把真正带着图传链路的那一路串口接进来，然后对它收到的载荷调用本函数"，
 * 不用动仲裁、不用动掩码、不用动客户端。
 *
 * 语义与 referee.c 收到 0x0311 完全一致：仅合法 kind=3 写收件箱 + 记到达时刻 + 计数，
 * 新鲜度门控与五档仲裁照旧生效。
 */
uint8_t HostKmFeed(const uint8_t *payload, uint16_t len);

/**
 * @brief 字节流级接收：把"任何来源交给我的原始字节"喂进来，自己拆 0xA5 裁判帧。
 *
 * 为什么必须有：0x0311 这条路目前只能靠 HostKmFeed() 由调用方把 30 字节载荷抠出来，
 * 那等于"谁喂谁负责校验"。而真实物化方式（新配一路 921600 UART，或车载电脑把
 * 图传收到的字节原样转过来）交出来的都是**字节流**，所以拆帧、验 crc8/crc16、
 * 认命令号 0x0311、按长度取载荷这些事必须在 C 板这边做完。
 *
 * 帧布局与官方裁判协议一致（protocol.h / referee_usart_task.c:144-173）：
 *   0xA5 | data_length(u16) | seq | crc8 | cmd_id(u16) | data[data_length] | crc16(u16)
 * 校验用的就是固件里那份 CRC8_CRC16.c，不另写一套（另写一套就是两个真相）。
 * 可以任意粒度调用（一次一字节、一次一整包都行），内部是流式状态机。
 */
void HostKmFeedBytes(const uint8_t *bytes, uint16_t len);

/* 字节流接收的自观测：现场只靠"计数涨不涨"分不清"没线"还是"线有了但帧全废" */
extern volatile uint32_t HOST_KM_BYTES_IN;     /* 收到的总字节数 */
extern volatile uint32_t HOST_KM_FRAME_OK;     /* 拆出并验过的完整帧数 */
extern volatile uint32_t HOST_KM_FRAME_BAD;    /* crc/长度/命令号不对而丢掉的帧数 */


/* ------------------------------------------------------------------------
 * 链路自检回读：把"车上到底收到几个 0x0311"从 USB 0x5A 的 Debug 段报回上位机
 * ------------------------------------------------------------------------
 * 为什么值得占上位机的 debug 槽：现场唯一想知道的一件事就是**包到了没有**。
 * 客户端只能看到自己发了多少（那是自证，说明不了链路），有了这个回读才能把
 * "MQTT 没连上 / 键鼠来源没切" 和 "921600 那一路没接到 C 板" 当场分开——
 * 这两件事的处理方式完全不同。
 *
 * 槽位为什么是 9/0：本队固件里所有 ModifyDebugDataPackage 调用点
 * （chassis_omni.c:399-406、chassis_mecanum.c:334-335）**全部是注释状态**，
 * 且注释里占的是 3..8；9 与 0 连注释都没用过，不会撞车。
 * 名字必须 <=10 字符：usb_task.c:1414 `while (name[i] != '\0' && i < 10)`。
 */
#ifndef HOST_KM_DEBUG_UPLINK
#define HOST_KM_DEBUG_UPLINK 1        /* 0 = 完全不编进回读，省 flash */
#endif
#ifndef HOST_KM_DEBUG_PERIOD_MS
#define HOST_KM_DEBUG_PERIOD_MS 200U  /* HostKmLinkUpdate 是 1ms 调的，必须限流 */
#endif
#ifndef HOST_KM_DEBUG_SLOT_RX
#define HOST_KM_DEBUG_SLOT_RX ((uint8_t)9)
#endif
#ifndef HOST_KM_DEBUG_SLOT_KEY
#define HOST_KM_DEBUG_SLOT_KEY ((uint8_t)0)
#endif
/* 字节流接收器的自观测两个槽（见 HostKmFeedBytes）：
 *   km_ok  = 拆出并验过 crc 的完整帧数（不论命令号是不是 0x0311）
 *   km_bad = 因 crc/长度/超长而被丢掉的次数
 * 为什么值得多占两个槽：光看 km_rx 分不清三种完全不同的故障——
 *   "线根本没接" (bytes=0)、"线有了但波特率/接线错" (bytes 涨、ok=0、bad 涨)、
 *   "帧都对但命令号不是 0x0311" (ok 涨、rx 不涨)。三者的处理方式互不相同。
 * 槽位选 1/2：上面说过 3..8 出现在被注释掉的调用里，0/9 已用，1/2 谁都没碰。 */
#ifndef HOST_KM_DEBUG_SLOT_FRAME_OK
#define HOST_KM_DEBUG_SLOT_FRAME_OK ((uint8_t)1)
#endif
#ifndef HOST_KM_DEBUG_SLOT_FRAME_BAD
#define HOST_KM_DEBUG_SLOT_FRAME_BAD ((uint8_t)2)
#endif

/* 车上当前的键鼠来源档位（编译期常量的值，运行时零开销）：
 *   0=none 1=rc 2=vt 3=rc_vt 4=vt_rc
 * 为什么值得多占一个槽：`km_rx` 只证明"帧到了"，不证明"这档会用它的键位"。
 * 默认档 CL_KM_RC 下 0x0311 整个不参与，但到达计数照涨——
 * 那时"车上已收到 N 帧"会被读成"能控车了"，白跑一趟。 */
#ifndef HOST_KM_DEBUG_SLOT_POLICY
#define HOST_KM_DEBUG_SLOT_POLICY ((uint8_t)3)
#endif

/* 档位编号（给上位机用的稳定映射，别拿宏的原始数值当枚举用） */
#define HOST_KM_POL_NONE 0U
#define HOST_KM_POL_RC 1U
#define HOST_KM_POL_VT 2U
#define HOST_KM_POL_RC_VT 3U
#define HOST_KM_POL_VT_RC 4U

#if (__CONTROL_LINK_KM == CL_KM_NONE)
#define HOST_KM_POL_ID HOST_KM_POL_NONE
#elif (__CONTROL_LINK_KM == CL_KM_RC)
#define HOST_KM_POL_ID HOST_KM_POL_RC
#elif (__CONTROL_LINK_KM == CL_KM_VT)
#define HOST_KM_POL_ID HOST_KM_POL_VT
#elif (__CONTROL_LINK_KM == CL_KM_RC_VT)
#define HOST_KM_POL_ID HOST_KM_POL_RC_VT
#else
#define HOST_KM_POL_ID HOST_KM_POL_VT_RC
#endif

/* usb_debug.h:5 的原型。这里按同签名自己声明，是因为各工程的 include 路径
   不保证能拿到那个头；实现链接到 usb_task.c:1405 那一份。 */
extern void ModifyDebugDataPackage(uint8_t index, float data, const char *name);

#ifdef __cplusplus
}
#endif

#endif /* HOST_KM_LINK_H */

