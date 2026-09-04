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
extern volatile uint32_t HOST_KM_RX_COUNT;

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

#ifdef __cplusplus
}
#endif

#endif /* HOST_KM_LINK_H */
