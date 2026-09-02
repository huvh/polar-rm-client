/**
 * @file    host_chassis_bridge.h
 * @brief   上位机(自定义客户端)与底盘之间的显式指令桥
 *
 * 背景（为什么需要这个文件）
 * --------------------------
 * 原本客户端想让机器人"开小陀螺"，唯一可用的手段是借用虚拟遥控器里的
 * SHIFT 按键位。但固件对 SHIFT 的处理是"边沿翻转"：
 *   - 麦轮 chassis_mecanum.c:177  FOLLOW 模式下按一次 -> spin_flag = 1
 *   - 麦轮 chassis_mecanum.c:223  SPIN   模式下按一次 -> spin_flag = 0
 *   - 全向 chassis_omni.c:96      按一次 -> spin_flag 取反
 *   - 松手时(chassis_mecanum.c:187 / chassis_omni.c:107)不会改变 spin_flag
 *
 * 后果：客户端只能"开"，无法"关"；再开一次反而把自转关掉。
 * "受击后自动小陀螺"因此不可能正确工作——它需要明确的开/关语义。
 *
 * 本文件的做法
 * ------------
 * 新增一对 USB 数据段，语义是"设定"而不是"翻转"：
 *   上行 0x04  上位机 -> 机器人   ChassisCmd_t   (我要自转开 / 我要自转关)
 *   下行 0x1F  机器人 -> 上位机   ChassisState_t (自转现在是开还是关 + 底盘模式)
 *
 * 分工刻意保持解耦：
 *   - usb_task.c   只负责收发，不认识 Chassis_s（它没有 include 任何底盘头文件，
 *                  也不应该 include，否则麦轮/全向轮的编译配置会互相污染）
 *   - chassis_*.c  只负责消费指令、回填状态，通过本文件的 4 个全局变量通信
 *
 * 安装位置：application/typedef/host_chassis_bridge.h
 *          （与 usb_typdef.h 同目录，Keil 的 include 路径已覆盖）
 */

#ifndef HOST_CHASSIS_BRIDGE_H
#define HOST_CHASSIS_BRIDGE_H

#include "attribute_typedef.h"
#include "struct_typedef.h"

#ifdef __cplusplus
extern "C" {
#endif

/*--------------------------- 数据段 id ---------------------------*/
/* 上行 0x01/0x02/0x03 已被占用(见 usb_typdef.h:48-50)，0x04 起空闲 */
#define CHASSIS_CMD_DATA_RECEIVE_ID ((uint8_t)0x04)
/* 下行 0x01..0x1E 已被占用(见 usb_typdef.h:16-46)，0x1F 起空闲 */
#define CHASSIS_STATE_DATA_SEND_ID ((uint8_t)0x1F)

/*--------------------------- 指令取值 ---------------------------*/
/*
 * 只保留"开"和"关"两种，刻意不提供"翻转"。
 * 翻转正是本文件要修掉的语义缺陷来源：客户端无法知道当前状态，
 * 发翻转就会在第二次把它关掉。
 */
#define HOST_SPIN_CMD_NONE ((uint8_t)0x00)
#define HOST_SPIN_CMD_ON ((uint8_t)0x01)
#define HOST_SPIN_CMD_OFF ((uint8_t)0x02)

/*
 * 指令有效期。上位机按"电平"方式持续重发（想开着就一直发 ON），
 * 超过该时间没收到就认为上位机已掉线，固件停止强制、把控制权还给
 * 物理遥控器。取 150ms 与 VIRTUAL_RC 的新鲜度门控一致。
 *
 * 注意：新鲜度判断由 usb_task.c 负责（它本来就大量使用 HAL_GetTick 和
 * RECEIVE_TIME）。底盘文件只读 HOST_SPIN_CMD 这一个值，不需要看见 HAL，
 * 因此 chassis_omni.c 这种只 include robot_param.h 的文件也能直接用。
 */
#define HOST_SPIN_CMD_VALID_MS ((uint32_t)150)

/*--------------------------- 报文结构 ---------------------------*/
/*
 * 帧头自带定义，刻意**不用** FrameHeader_t。
 * 原因：仓库里有两个同名但不同义的 FrameHeader_t——
 *   usb_typdef.h   : sof/len/id/crc        （4 字节，0x5A 链路用这个）
 *   uart2_typedef.h: sof/len/id/type/crc   （5 字节，裁判系统用这个）
 * 依赖它就得 include 其中一个，而本头文件会被底盘文件引用，
 * 一旦拉错版本或形成循环包含，错很难查。直接内联 4 字节，
 * 与 usb_typdef.h 的 FrameHeader_t 线上格式逐字节一致。
 */

/**
 * @brief 上行 0x04 数据域，4 字节
 */
typedef struct
{
    uint8_t spin_cmd;  /* HOST_SPIN_CMD_* */
    uint8_t param0;    /* 预留：自转方向 */
    uint8_t param1;    /* 预留：自转速度档 */
    uint8_t reserved;
} __packed__ ChassisCmd_t;

/**
 * @brief 下行 0x1F 数据域，4 字节
 */
typedef struct
{
    uint8_t spin_state;   /* 0=停转 1=自转中，取自 chassis.spin_flag */
    uint8_t chassis_mode; /* ChassisMode_e: 0=LOCK 1=SINGLE 2=FOLLOW 3=SPIN */
    uint8_t sc_flag;      /* 自检状态，前端 SelfCheckMode 用 */
    uint8_t reserved;
} __packed__ ChassisState_t;

/**
 * @brief 上行 0x04 整帧。与 ReceiveDataVirtualRc_s 同构：帧头4 + 时间戳4 + 数据 + CRC16 2
 */
typedef struct
{
    struct
    {
        uint8_t sof;  /* 固定 0x5A */
        uint8_t len;  /* = sizeof(ChassisCmd_t) + 4(time_stamp) */
        uint8_t id;   /* = CHASSIS_CMD_DATA_RECEIVE_ID */
        uint8_t crc;  /* 帧头 CRC8 */
    } __packed__ frame_header;
    uint32_t time_stamp;
    ChassisCmd_t data;
    uint16_t crc;
} __packed__ ReceiveDataChassisCmd_s;

/**
 * @brief 下行 0x1F 整帧
 */
typedef struct
{
    struct
    {
        uint8_t sof;  /* 固定 0x5A */
        uint8_t len;  /* = sizeof(ChassisState_t) + 4(time_stamp) */
        uint8_t id;   /* = CHASSIS_STATE_DATA_SEND_ID */
        uint8_t crc;  /* 帧头 CRC8 */
    } __packed__ frame_header;
    uint32_t time_stamp;
    ChassisState_t data;
    uint16_t crc;
} __packed__ SendDataChassisState_s;

/* 尺寸断言：一旦有人改了字段布局，编译就会失败而不是默默发出错帧 */
_Static_assert(sizeof(ChassisCmd_t) == 4, "ChassisCmd_t must stay 4 bytes");
_Static_assert(sizeof(ChassisState_t) == 4, "ChassisState_t must stay 4 bytes");
_Static_assert(
    sizeof(ReceiveDataChassisCmd_s) == 14, "0x04 frame must stay 14 bytes");
_Static_assert(
    sizeof(SendDataChassisState_s) == 14, "0x1F frame must stay 14 bytes");

/*--------------------------- 桥接全局量 ---------------------------*/
/*
 * 由 usb_task.c 定义（它是唯一认识 USB 报文的一方）。
 * volatile：写在 usb_task 任务，读在底盘任务，跨任务共享。
 */
extern volatile uint8_t HOST_SPIN_CMD;        /* usb_task 写，chassis_* 读 */
extern volatile uint32_t HOST_SPIN_CMD_TIME;  /* 最后一次收到指令的 HAL_GetTick() */
extern volatile uint8_t HOST_SPIN_STATE;      /* chassis_* 写，usb_task 读 */
extern volatile uint8_t HOST_CHASSIS_MODE;    /* chassis_* 写，usb_task 读 */
extern volatile uint8_t HOST_CHASSIS_SC_FLAG; /* chassis_* 写，usb_task 读 */

/**
 * @brief 底盘侧统一入口：消费上位机自转指令 + 回填状态
 *
 * 在 ChassisSetMode() 的**最开头**调用。放在最开头是因为：
 *   - 麦轮 s[0] 拨到上方会无条件 CHASSIS_SPIN(chassis_mecanum.c:102)，
 *     与 spin_flag 无关；拨到下方会 CHASSIS_LOCK(:86)，此时读不读键都没用。
 *     只有 s[0] 在中间(:88)时 spin_flag 才真正决定模式。
 *   - 所以这里只负责维护 spin_flag，模式仲裁仍然完全交给固件原有逻辑，
 *     物理遥控器永远是最终裁决者。这是刻意的：上位机掉线或误发时，
 *     驾驶员手里的遥控器必须还能立刻接管。
 *
 * 掉线处理：usb_task 一旦判定指令过期就把 HOST_SPIN_CMD 置回 NONE，
 * 于是本宏**不再强制**，spin_flag 保持原值（不主动清零）。
 * 理由是自转是防御姿态，上位机断线时突然停转比维持现状更危险；
 * 要停由驾驶员用遥控器停。
 *
 * 本宏刻意不调用任何 HAL / CMSIS 函数，只读写本文件声明的 5 个全局量，
 * 因此对 include 环境没有额外要求。
 */
#define HOST_CHASSIS_BRIDGE_APPLY(chassis_ptr)                        \
    do {                                                              \
        if (HOST_SPIN_CMD == HOST_SPIN_CMD_ON) {                      \
            (chassis_ptr)->spin_flag = 1;                             \
        } else if (HOST_SPIN_CMD == HOST_SPIN_CMD_OFF) {              \
            (chassis_ptr)->spin_flag = 0;                             \
        }                                                             \
        HOST_SPIN_STATE = (uint8_t)((chassis_ptr)->spin_flag ? 1 : 0); \
        HOST_CHASSIS_MODE = (uint8_t)(chassis_ptr)->mode;             \
        HOST_CHASSIS_SC_FLAG = (uint8_t)(chassis_ptr)->sc_flag;       \
    } while (0)

#ifdef __cplusplus
}
#endif

#endif /* HOST_CHASSIS_BRIDGE_H */
