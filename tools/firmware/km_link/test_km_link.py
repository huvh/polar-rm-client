#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五档 __CONTROL_LINK_KM 的键鼠仲裁行为校验（编的是固件树里的真代码）。

为什么必须可执行
----------------
键位覆盖、鼠标抢让、图传过期归零全是**运行期语义**，编译器一句都不会报。
所以这里把 remote_control.c 里 POLAR-KM-LINK 那段实现原样抽出来，连
remote_control.h / host_chassis_bridge.h / host_km_link.h 的真实定义一起，
按五种档位各编一个 exe 逐条断言。--negative 再把实现退回"图传直接覆盖
key.v、并且不做新鲜度门控"的朴素写法，证明这些断言抓得住错代码。

用法
----
    python tools/firmware/km_link/test_km_link.py [固件根目录] [--negative]
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]          # rm_custom_client
sys.path.insert(0, str(REPO_ROOT))   # 要 import rm_client 的真编码器
DEFAULT_REPO = REPO_ROOT.parent / "tmp_polarbear" / "StandardRobotpp"
RC_REL = "application/other/remote_control.c"
KM_HDR_REL = "application/typedef/host_km_link.h"
BRIDGE_HDR_REL = "application/typedef/host_chassis_bridge.h"

FAILED = 0
BRIDGE_SNIPPET = ""

POLICIES = ["CL_KM_RC", "CL_KM_NONE", "CL_KM_VT", "CL_KM_RC_VT", "CL_KM_VT_RC"]


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def grab(text: str, pattern: str, label: str) -> str:
    m = re.search(pattern, text, re.S)
    if not m:
        raise RuntimeError(f"抽不到 {label}（锚点 {pattern!r}）")
    return m.group(0)


TU = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "remote_control.h"          /* RC_ctrl_t 的真实定义 */
/* 官方 CRC 的实现直接抽进来（它自己就是声明）：那个头文件在这个 TU 里会带出别的诊断，
   而本测试把任何编译器输出都当失败 */
#include "protocol.h"                    /* 帧头/命令号常量与 frame_header_struct_t */
@@CRC@@

/* 五档取值取自固件自己的 robot_typedef.h:80-84（这里同值内联，
 * 免得把 robot_param.h 那一整棵机型配置拖进主机测试） */
#define CL_KM_NONE     0x200
#define CL_KM_RC       0x201
#define CL_KM_VT       0x202
#define CL_KM_RC_VT    0x203
#define CL_KM_VT_RC    0x204

@@BRIDGE@@

@@HDRDEFS@@

#define __CONTROL_LINK_KM @@POLICY@@
#define KM_KEY_ALLOWED_MASK @@MASK@@

/* ---- 被测代码要的最小环境：rc_ctrl、0x0311 收件箱、可推进的时间 ---- */
RC_ctrl_t rc_ctrl;
typedef struct { uint8_t data[30]; } robot_custom_data_3_t;
robot_custom_data_3_t robot_custom_data_3;
volatile uint32_t HOST_KM_RX_TIME = 0;
volatile uint32_t HOST_KM_RX_COUNT = 0;
static uint32_t g_tick = 1000;
uint32_t HAL_GetTick(void) { return g_tick; }

/* 0x5A Debug 上行的桩：按槽位记最后一次写入的名字与值，供断言用 */
typedef struct { uint8_t idx; char name[16]; float val; } dbg_slot_t;
static dbg_slot_t g_dbg[16];
static int g_dbg_n = 0;
void ModifyDebugDataPackage(uint8_t index, float data, const char *name)
{
    int i;
    for (i = 0; i < g_dbg_n; i++) {
        if (g_dbg[i].idx == index) break;
    }
    if (i == g_dbg_n) { g_dbg[i].idx = index; g_dbg[i].name[0] = 0; g_dbg_n++; }
    strncpy(g_dbg[i].name, name, 15);
    g_dbg[i].name[15] = 0;
    g_dbg[i].val = data;
}
static float dbg_val(uint8_t index)
{
    int i;
    for (i = 0; i < g_dbg_n; i++) {
        if (g_dbg[i].idx == index) return g_dbg[i].val;
    }
    return -1.0f;
}
static const char *dbg_name(uint8_t index)
{
    int i;
    for (i = 0; i < g_dbg_n; i++) {
        if (g_dbg[i].idx == index) return g_dbg[i].name;
    }
    return "";
}

@@IMPL@@

static int fails = 0;
static void eq(const char *what, long got, long want)
{
    if (got != want) {
        printf("   FAIL %s: got %ld want %ld\n", what, got, want);
        fails++;
    }
}

static void put_bytes(const uint8_t *bytes, int n)
{
    memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
    memcpy(robot_custom_data_3.data, bytes, (size_t)n);
    HOST_KM_RX_TIME = g_tick;
    HOST_KM_RX_COUNT++;
}

/* @@CLIENT_BLOB@@ 是客户端 protocol.encode_km_control_payload() 真打出来的字节
 * （W+SHIFT、dx=-45、dy=+120、左键），由 build_tu() 在生成 TU 时嵌进来。
 * 用它而不是在 C 里手搭结构体，是为了让"客户端改了打包"这件事必须在这里
 * 当场编译失败或断言失败，而不是等到车上。 */
static const uint8_t CLIENT_KM_FRAME[] = {@@CLIENT_BLOB@@};
#define CLIENT_KM_KEYS   (uint16_t)(1u << 0 | 1u << 4)   /* W + SHIFT */
#define CLIENT_KM_MX     (-45)
#define CLIENT_KM_MY     (120)

static void put_km(uint16_t keys, int16_t mx, int16_t my, uint8_t btn)
{
    prm1_km_cmd_t p;
    memset(&p, 0, sizeof(p));
    p.magic[0] = 'P'; p.magic[1] = 'R'; p.magic[2] = 'M'; p.magic[3] = '1';
    p.version = PRM1_VERSION; p.kind = PRM1_KIND_KM;
    p.seq = 7; p.keys = keys; p.mouse_x = mx; p.mouse_y = my; p.buttons = btn;
    put_bytes((const uint8_t *)&p, (int)sizeof(p));
}

static void put_other_kind(void)
{
    memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
    robot_custom_data_3.data[0] = 'P';
    robot_custom_data_3.data[1] = 'R';
    robot_custom_data_3.data[2] = 'M';
    robot_custom_data_3.data[3] = '1';
    robot_custom_data_3.data[4] = PRM1_VERSION;
    robot_custom_data_3.data[5] = PRM1_KIND_VISION;   /* 别的指令，不是键鼠 */
    robot_custom_data_3.data[6] = 0xFF;               /* 被当成键位就会露馅 */
    robot_custom_data_3.data[7] = 0xFF;
    HOST_KM_RX_TIME = g_tick;
    HOST_KM_RX_COUNT++;
}

static void driver_frame(uint16_t keys, int16_t mx, int16_t my)
{
    memset(&rc_ctrl, 0, sizeof(rc_ctrl));
    rc_ctrl.rc.ch[0] = 500; rc_ctrl.rc.ch[1] = -500;   /* 摇杆：谁都不许动 */
    rc_ctrl.rc.s[0] = 3; rc_ctrl.rc.s[1] = 1;
    HOST_RC_DRIVER_KEYS = keys;                        /* DT7 那本账 */
    rc_ctrl.key.v = HOST_RC_MERGED_KEYS();
    rc_ctrl.mouse.x = mx; rc_ctrl.mouse.y = my;
    HostKmApplyDriverFrameMouse(&rc_ctrl);
}

int main(void)
{
    const uint16_t K_W = 1u << 0, K_S = 1u << 1, K_SHIFT = 1u << 4, K_Q = 1u << 6;

    /* A) 上位机 0x5A 那本账任何档位都不许被仲裁抹掉 */
    HOST_RC_HOST_KEYS = K_SHIFT;
    driver_frame(K_S, 5, -3);
    HostKmLinkUpdate();
    eq("0x5A 键位始终生效", (rc_ctrl.key.v & K_SHIFT) != 0, 1);

    /* B) 底线：摇杆与拨杆在任何档位都不许被动过 */
    eq("摇杆 ch[0] 未被仲裁改动", rc_ctrl.rc.ch[0], 500);
    eq("摇杆 ch[1] 未被仲裁改动", rc_ctrl.rc.ch[1], -500);
    eq("拨杆 s[0] 未被仲裁改动", rc_ctrl.rc.s[0], 3);
    eq("拨杆 s[1] 未被仲裁改动", rc_ctrl.rc.s[1], 1);

    /* C) 不是本队伍的键鼠包（kind=VISION）就一个字节都不许进 */
    put_other_kind();
    driver_frame(0, 0, 0);
    HostKmLinkUpdate();
    eq("kind 不匹配就不解键位", rc_ctrl.key.v & (K_W | K_S), 0);
    eq("kind 不匹配就不置位", HOST_RC_KM_KEYS, 0);

    /* D) 档位专属断言 */
#if (__CONTROL_LINK_KM == CL_KM_RC)
    driver_frame(K_S, 5, -3);
    put_km(K_W, 99, 99, 3);
    HostKmLinkUpdate();
    eq("rc 档：图传键位不参与", rc_ctrl.key.v & K_W, 0);
    eq("rc 档：驾驶员键位保留", rc_ctrl.key.v & K_S, K_S);
    eq("rc 档：鼠标一个字节都不动", rc_ctrl.mouse.x, 5);
    eq("rc 档：鼠标 y 不动", rc_ctrl.mouse.y, -3);
#elif (__CONTROL_LINK_KM == CL_KM_NONE)
    driver_frame(K_S, 5, -3);
    put_km(K_W, 9, 9, 1);
    HostKmLinkUpdate();
    eq("none 档：驾驶员键位被屏蔽", rc_ctrl.key.v & (K_S | K_W), 0);
    eq("none 档：鼠标清零", rc_ctrl.mouse.x, 0);
    eq("none 档：摇杆照旧可用", rc_ctrl.rc.ch[0], 500);
#elif (__CONTROL_LINK_KM == CL_KM_VT)
    driver_frame(K_S, 5, -3);
    put_km(K_W, 40, -20, 2);
    HostKmLinkUpdate();
    eq("vt 档：图传键位生效", rc_ctrl.key.v & K_W, K_W);
    eq("vt 档：驾驶员键位被挡", rc_ctrl.key.v & K_S, 0);
    eq("vt 档：鼠标归图传", rc_ctrl.mouse.x, 40);
    eq("vt 档：右键按下", rc_ctrl.mouse.press_r, 1);
    g_tick += KM_LINK_VALID_MS + 50;              /* 图传断掉 */
    driver_frame(K_S, 7, 7);
    HostKmLinkUpdate();
    eq("vt 档：图传过期键位归零", rc_ctrl.key.v & (K_S | K_W), 0);
    eq("vt 档：图传过期鼠标清零", rc_ctrl.mouse.x, 0);
    eq("vt 档：过期后摇杆仍可停车", rc_ctrl.rc.ch[0], 500);
    eq("vt 档：过期后拨杆不变", rc_ctrl.rc.s[0], 3);
#elif (__CONTROL_LINK_KM == CL_KM_RC_VT)
    driver_frame(K_S, 5, -3);
    put_km(K_W, 40, -20, 3);
    HostKmLinkUpdate();
    eq("rc_vt 档：键位两路或起来", rc_ctrl.key.v & (K_S | K_W), K_S | K_W);
    eq("rc_vt 档：驾驶员动鼠标就归他", rc_ctrl.mouse.x, 5);
    driver_frame(K_S, 0, 0);
    put_km(K_W, 40, -20, 3);
    HostKmLinkUpdate();
    eq("rc_vt 档：驾驶员不动鼠标就让图传", rc_ctrl.mouse.x, 40);
    eq("rc_vt 档：让出时左右键一起换", rc_ctrl.mouse.press_l, 1);
    g_tick += KM_LINK_VALID_MS + 50;
    driver_frame(K_S, 11, 12);
    HostKmLinkUpdate();
    eq("rc_vt 档：图传过期键位仍在", rc_ctrl.key.v & K_S, K_S);
    eq("rc_vt 档：图传过期不去抢鼠标", rc_ctrl.mouse.x, 11);
#else /* CL_KM_VT_RC */
    driver_frame(K_S, 5, -3);
    put_km(K_W, 40, -20, 0);
    HostKmLinkUpdate();
    eq("vt_rc 档：键位两路或起来", rc_ctrl.key.v & (K_S | K_W), K_S | K_W);
    eq("vt_rc 档：图传优先抢鼠标", rc_ctrl.mouse.x, 40);
    g_tick += KM_LINK_VALID_MS + 50;
    driver_frame(K_S, 11, 12);
    HostKmLinkUpdate();
    eq("vt_rc 档：过期回落给驾驶员键位", rc_ctrl.key.v & K_S, K_S);
    eq("vt_rc 档：过期回落给驾驶员鼠标", rc_ctrl.mouse.x, 11);
#endif

    /* E) 开火权限：默认掩码不放 Q/E，显式给 fire-keys 才放 */
    driver_frame(0, 0, 0);
    put_km(K_Q, 0, 0, 0);
    HostKmLinkUpdate();
#if (__CONTROL_LINK_KM == CL_KM_RC || __CONTROL_LINK_KM == CL_KM_NONE)
    eq("rc/none 档：Q 一律不进", rc_ctrl.key.v & K_Q, 0);
#elif defined(KM_TEST_FIRE_KEYS)
    eq("给了 fire-keys：Q 应当放行", rc_ctrl.key.v & K_Q, K_Q);
#else
    eq("默认掩码不放 Q（开火权限不偷偷给）", rc_ctrl.key.v & K_Q, 0);
#endif

    /* F) SHIFT 必须在默认掩码里，否则客户端开不了小陀螺 */
    driver_frame(0, 0, 0);
    put_km(K_SHIFT, 0, 0, 0);
    HostKmLinkUpdate();
    /* rc/none 档必须看**图传那本账**，不能看 key.v：key.v 里还混着 A 步
     * 故意留下的 0x5A SHIFT，拿 key.v 断言会把"0x5A 生效"误判成"图传漏了"。 */
    eq("图传账目里最多只有一个来源的量", HOST_RC_KM_KEYS & ~((uint16_t)0x00DF), 0);
#if (__CONTROL_LINK_KM == CL_KM_RC || __CONTROL_LINK_KM == CL_KM_NONE)
    eq("rc/none 档：图传账目为空", HOST_RC_KM_KEYS, 0);
#else
    eq("图传能开小陀螺（SHIFT 在默认掩码内）", rc_ctrl.key.v & K_SHIFT, K_SHIFT);
#endif

    /* F2) 端到端：喂客户端真打出来的那 26 字节，看车上落到什么值 */
    driver_frame(0, 0, 0);
    put_bytes(CLIENT_KM_FRAME, (int)sizeof(CLIENT_KM_FRAME));
    HostKmLinkUpdate();
#if (__CONTROL_LINK_KM == CL_KM_RC || __CONTROL_LINK_KM == CL_KM_NONE)
    /* 这里必须看图传那本账，不能看 key.v：key.v 里合法地含着 A 步留下的
     * 0x5A SHIFT(=16)，拿 key.v 断"图传没进来"会把 0x5A 当成图传漏进来。 */
    eq("客户端真字节：本档图传账目为空", HOST_RC_KM_KEYS, 0);
    eq("客户端真字节：本档鼠标也不参与", rc_ctrl.mouse.x, 0);
#else
    eq("客户端真字节：W 落到 key.v", rc_ctrl.key.v & CLIENT_KM_KEYS, CLIENT_KM_KEYS);
    eq("客户端真字节：鼠标 dx 落到云台", rc_ctrl.mouse.x, CLIENT_KM_MX);
    eq("客户端真字节：鼠标 dy 落到云台", rc_ctrl.mouse.y, CLIENT_KM_MY);
    eq("客户端真字节：左键按下", rc_ctrl.mouse.press_l, 1);
#endif

    /* G) 25 字节遥控器（无键无鼠）清过账之后，图传照常接管、且不留残值 */
    HostKmClearDriverMouse();
    driver_frame(0, 0, 0);
    put_km(K_W, 3, 4, 1);
    HostKmLinkUpdate();
    eq("清过驾驶员账之后不残留 S", rc_ctrl.key.v & K_S, 0);

    /* H) 两路都松手必须归零（粘键就是车刹不住） */
    g_tick += KM_LINK_VALID_MS + 50;
    memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
    HOST_RC_HOST_KEYS = 0;           /* 先清 0x5A 的账 */
    driver_frame(0, 0, 0);           /* 再让 SBUS 写入者按新账合并 */
    HostKmLinkUpdate();
    eq("两路都松手后键位归零", rc_ctrl.key.v & (K_W | K_S | K_SHIFT), 0);

    /* I0) HostKmFeed：第二条来源能不能进来。
     *     现场若发现 0x0311 其实不在裁判口上，修法就是把那一路串口收到的载荷
     *     喂给 HostKmFeed()。这条路必须和 referee.c 那条完全等价，所以这里
     *     刻意**不**用 put_bytes 直接写收件箱，而是走公开接口。 */
    driver_frame(0, 0, 0);
    memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
    HOST_RC_HOST_KEYS = 0;
    HOST_RC_DRIVER_KEY_GATE = HOST_RC_DRIVER_GATE_OPEN;
    {
        prm1_km_cmd_t via_feed;
        unsigned rx_before = (unsigned)HOST_KM_RX_COUNT;
        memset(&via_feed, 0, sizeof(via_feed));
        via_feed.magic[0] = 'P'; via_feed.magic[1] = 'R';
        via_feed.magic[2] = 'M'; via_feed.magic[3] = '1';
        via_feed.version = PRM1_VERSION; via_feed.kind = PRM1_KIND_KM;
        via_feed.seq = 99; via_feed.keys = (uint16_t)(K_W | K_SHIFT);
        via_feed.mouse_x = 7; via_feed.mouse_y = -9;
        HostKmFeed((const uint8_t *)&via_feed, (uint16_t)sizeof(via_feed));
        eq("HostKmFeed 也记到达计数", (unsigned)HOST_KM_RX_COUNT, rx_before + 1u);
        HostKmLinkUpdate();
    }
#if (__CONTROL_LINK_KM == CL_KM_RC || __CONTROL_LINK_KM == CL_KM_NONE)
    eq("HostKmFeed 在 rc/none 档同样被忽略", HOST_RC_KM_KEYS, 0);
#else
    eq("HostKmFeed 进来的键位能落到 key.v", rc_ctrl.key.v & (K_W | K_SHIFT),
       K_W | K_SHIFT);
    eq("HostKmFeed 进来的鼠标也能落地", rc_ctrl.mouse.x, 7);
#endif
    /* 越界保护：给一个比收件箱还长的缓冲区，不得溢出 */
    {
        uint8_t big[64];
        memset(big, 0, sizeof(big));
        memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
        HostKmFeed(big, (uint16_t)sizeof(big));
        HostKmLinkUpdate();   /* 喂完必须重新仲裁，否则看到的还是上一轮的账 */
        eq("喂进没 magic 的垃圾不得接管键位（收件箱不可信）",
           rc_ctrl.key.v & (K_W | K_SHIFT), 0);
        HostKmFeed((const uint8_t *)0, 12U);   /* 空指针必须直接返回 */
        eq("空指针调用不得改变任何账", rc_ctrl.key.v & (K_W | K_SHIFT), 0);
    }

    /* I0b) 字节流接收器 HostKmFeedBytes()。
     *      0x0311 真要落到车上，交到我们手里的永远是**字节流**（新配一路 UART、
     *      或车载电脑原样转发图传收到的字节），所以拆帧、验 crc8/crc16、认命令号、
     *      按长度取载荷这些事必须在 C 板这边做完。
     *      帧用官方 CRC8_CRC16.c 现算现append：造的和验的是同一份实现，
     *      这样"我以为的帧格式"就不是自说自话。 */
    {
        uint8_t frame[REF_PROTOCOL_FRAME_MAX_SIZE];
        const uint16_t dlen = (uint16_t)sizeof(robot_custom_data_3);
        const uint16_t total = (uint16_t)(REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE
                                           + dlen + REF_PROTOCOL_CRC16_SIZE);
        unsigned ok_before, bad_before, rx_before, rx_time_before;
        unsigned i2;
        memset(frame, 0, sizeof(frame));
        frame[0] = HEADER_SOF;
        frame[1] = (uint8_t)(dlen & 0xFF);
        frame[2] = (uint8_t)((dlen >> 8) & 0xFF);
        frame[3] = 7;                                   /* seq */
        frame[REF_PROTOCOL_HEADER_SIZE] = (uint8_t)(ROBOT_CUSTOM_DATA_3_CMD_ID & 0xFF);
        frame[REF_PROTOCOL_HEADER_SIZE + 1] = (uint8_t)(ROBOT_CUSTOM_DATA_3_CMD_ID >> 8);
        frame[REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE] = 'P';
        frame[REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE + 1] = 'R';
        frame[REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE + 2] = 'M';
        frame[REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE + 3] = '1';
        append_CRC8_check_sum(frame, (unsigned int)REF_PROTOCOL_HEADER_SIZE);
        append_CRC16_check_sum(frame, (uint32_t)total);

        ok_before = (unsigned)HOST_KM_FRAME_OK;
        rx_before = (unsigned)HOST_KM_RX_COUNT;
        memset(&robot_custom_data_3, 0, sizeof(robot_custom_data_3));
        HostKmFeedBytes(frame, total);
        eq("一整帧被接受并认出 0x0311", (unsigned)HOST_KM_FRAME_OK, ok_before + 1u);
        eq("认出来就计入到达计数（与 referee 那条同一个账）",
           (unsigned)HOST_KM_RX_COUNT, rx_before + 1u);
        eq("载荷真的落进收件箱", robot_custom_data_3.data[0], (uint8_t)'P');

        /* 逐字节喂：证明缓冲是流式的（半帧留得下来），不是一次必须给一整包 */
        ok_before = (unsigned)HOST_KM_FRAME_OK;
        rx_before = (unsigned)HOST_KM_RX_COUNT;
        for (i2 = 0; i2 < (unsigned)total; i2++) {
            HostKmFeedBytes(&frame[i2], 1U);
        }
        eq("一次一字节也要能拼出同一帧", (unsigned)HOST_KM_FRAME_OK, ok_before + 1u);
        eq("拼出来照样记账", (unsigned)HOST_KM_RX_COUNT, rx_before + 1u);

        /* 噪声：垃圾字节 + 一个**自己就会失败掉**的坏帧头（crc8 不对）。
         * 注意不能拿"以 0xA5 结尾的噪声"当用例：那会吃掉随后真帧的帧头，
         * 而这是所有不回填的流式重同步的固有行为（官方 referee 接收机同样如此），
         * 不是本实现的缺陷。坏头自己消化完，真帧才应该对齐。 */
        {
            static const uint8_t noise[13] = {'j', 'u', 'n', 'k', 'j', 'u', 'n', 'k',
                                              0xA5, 0x01, 0x02, 0x03, 0x04};
            ok_before = (unsigned)HOST_KM_FRAME_OK;
            bad_before = (unsigned)HOST_KM_FRAME_BAD;
            HostKmFeedBytes(noise, (uint16_t)sizeof(noise));
            eq("坏帧头要在自己这一段就被判坏（不拖累后面）",
               (unsigned)HOST_KM_FRAME_BAD, bad_before + 1u);
            HostKmFeedBytes(frame, total);
            eq("噪声之后照样能对齐真帧头", (unsigned)HOST_KM_FRAME_OK, ok_before + 1u);
        }

        /* 坏帧：只改数据字节、**不重算尾校验** —— 这才是"线上抖了一个位"的样子。
         * （上一版在这里顺手 append 了一次 crc16，等于把帧重新做合法了，
         *   于是"必须被拒"当然不成立：断言测的是自己的错，不是实现的错。） */
        bad_before = (unsigned)HOST_KM_FRAME_BAD;
        rx_before = (unsigned)HOST_KM_RX_COUNT;
        rx_time_before = (unsigned)HOST_KM_RX_TIME;
        robot_custom_data_3.data[4] = 0;
        frame[REF_PROTOCOL_HEADER_SIZE + REF_PROTOCOL_CMD_SIZE + 4] = 0xEE;
        HostKmFeedBytes(frame, total);
        eq("改过一字节的帧必须被拒", (unsigned)HOST_KM_FRAME_BAD, bad_before + 1u);
        eq("被拒的帧不得推进到达计数", (unsigned)HOST_KM_RX_COUNT, rx_before);
        eq("被拒的帧也不得写进收件箱", robot_custom_data_3.data[4], 0);
        eq("被拒的帧同样不许推进到达时刻（新鲜度门控不能被坏帧喂新）",
           (unsigned)HOST_KM_RX_TIME, (unsigned)rx_time_before);

        /* 合法但别的命令号：算"收到好帧"，不算"0x0311 到达" */
        ok_before = (unsigned)HOST_KM_FRAME_OK;
        rx_before = (unsigned)HOST_KM_RX_COUNT;
        frame[REF_PROTOCOL_HEADER_SIZE] = 0x09;
        frame[REF_PROTOCOL_HEADER_SIZE + 1] = 0x03;
        append_CRC16_check_sum(frame, (uint32_t)total);
        HostKmFeedBytes(frame, total);
        eq("别的命令号的合法帧也算收到帧", (unsigned)HOST_KM_FRAME_OK, ok_before + 1u);
        eq("但不许当成 0x0311 到达（否则现场会被计数骗）",
           (unsigned)HOST_KM_RX_COUNT, rx_before);
        HostKmFeedBytes((const uint8_t *)0, 8U);
        eq("空指针调用不得崩，也不许假装收到", (unsigned)HOST_KM_FRAME_OK,
           (unsigned)HOST_KM_FRAME_OK);
    }

    /* I) 链路回读上行：现场靠它判"0x0311 到没到 C 板"，所以三件事必须钉住：
     *    值真的是计数与合并键位、名字没被截断、以及 1ms 调用被限流了。 */
    driver_frame(0, 0, 0);
    put_km(K_W | K_SHIFT, 0, 0, 0);
    g_tick += HOST_KM_DEBUG_PERIOD_MS + 10;      /* 越过限流窗口 */
    HostKmLinkUpdate();
    eq("回读写了 km_rx 槽", strcmp(dbg_name(HOST_KM_DEBUG_SLOT_RX), "km_rx"), 0);
    eq("回读写了 km_key 槽", strcmp(dbg_name(HOST_KM_DEBUG_SLOT_KEY), "km_key"), 0);
    eq("km_rx 等于实际到达计数",
       (int)dbg_val(HOST_KM_DEBUG_SLOT_RX), (int)HOST_KM_RX_COUNT);
    eq("km_key 等于当前合并键位",
       (int)dbg_val(HOST_KM_DEBUG_SLOT_KEY), (int)rc_ctrl.key.v);
    eq("回读写了 km_ok 槽（分清没线、和线有了但帧全废）",
       strcmp(dbg_name(HOST_KM_DEBUG_SLOT_FRAME_OK), "km_ok"), 0);
    eq("回读写了 km_bad 槽",
       strcmp(dbg_name(HOST_KM_DEBUG_SLOT_FRAME_BAD), "km_bad"), 0);
    eq("km_ok 等于实际拆出的好帧数",
       (int)dbg_val(HOST_KM_DEBUG_SLOT_FRAME_OK), (int)HOST_KM_FRAME_OK);
    eq("km_bad 等于实际丢掉的坏帧数",
       (int)dbg_val(HOST_KM_DEBUG_SLOT_FRAME_BAD), (int)HOST_KM_FRAME_BAD);
    eq("槽位不许撞车（0/1/2/9 各不重叠）",
       (HOST_KM_DEBUG_SLOT_KEY == 0U && HOST_KM_DEBUG_SLOT_FRAME_OK == 1U
        && HOST_KM_DEBUG_SLOT_FRAME_BAD == 2U && HOST_KM_DEBUG_SLOT_RX == 9U) ? 0 : 1, 0);
    /* 限流：不推进时间就再调，计数涨了但上报值不许变（否则 1ms 一次会淹了 USB） */
    {
        float held = dbg_val(HOST_KM_DEBUG_SLOT_RX);
        unsigned before = (unsigned)HOST_KM_RX_COUNT;
        put_km(K_W, 0, 0, 0);
        HostKmLinkUpdate();
        if ((unsigned)HOST_KM_RX_COUNT <= before) {
            eq("限流测试前提：计数必须已增长", 0, 1);
        }
        eq("未到期不得重写回读（限流有效）",
           (int)dbg_val(HOST_KM_DEBUG_SLOT_RX), (int)held);
    }

    if (fails == 0) {
        printf("POLICY @@POLICY@@@@FIRESUFFIX@@ BEHAVIOR OK\n");
        return 0;
    }
    printf("POLICY @@POLICY@@@@FIRESUFFIX@@ FAILED %d 项\n", fails);
    return 1;
}
"""


def extract_official_crc(firmware: Path) -> str:
    """把固件里那份官方 CRC 实现**原样**抽出来（从 CRC8_INIT 到最后一个函数收尾）。

    为什么要它：字节流接收器与测试都要算/验裁判协议的 crc8/crc16。自己另写一份
    就成了"两个真相"——测试会绿而车上不认。抽官方实现进来，造帧和验帧用的是同一份代码。
    """
    src = (firmware / "components" / "support" / "CRC8_CRC16.c").read_text(
        encoding="utf-8", errors="ignore")
    i = src.index("const uint8_t CRC8_INIT")
    j = src.rindex("}")
    body = src[i:j + 1]
    assert "get_CRC8_check_sum" in body and "wCRC_table" in body, "CRC 代码抽取越界"
    return body


def build_tu(impl: str, hdr_defs: str, policy: str, fire: bool, negative: bool,
             crc_src: str = "") -> str:
    body = impl
    if negative:
        # 退回朴素写法：图传直接覆盖 key.v（没有门闸也没有或），并去掉新鲜度门控。
        # 这两处正是本轮改动真正修掉的东西，改回去必须被抓到。
        n1 = body.count("rc_ctrl.key.v = HOST_RC_MERGED_KEYS();")
        body = body.replace("rc_ctrl.key.v = HOST_RC_MERGED_KEYS();",
                            "rc_ctrl.key.v = HOST_RC_KM_KEYS;")
        body = body.replace("&& HOST_KM_IS_FRESH()", "&& (1)")
        assert n1 >= 1 and body != impl, "阴性对照没能改写实现（锚点变了）"
    mask = ("(KM_KEY_MASK_DRIVE | KM_KEY_MASK_FIRE)" if fire else "KM_KEY_MASK_DRIVE")
    from rm_client.backend import protocol as pr  # 真客户端编码器

    blob = pr.encode_km_control_payload(sequence=0x22,
                                        keyboard_value=(1 << 0) | (1 << 4),
                                        mouse_x=-45, mouse_y=120, mouse_z=0,
                                        left_button=True)
    assert len(blob) == pr.TEAM_CONTROL_KM_SIZE, len(blob)
    # 只出数字列表：模板里已经写了外层花括号
    # （`= {@@CLIENT_BLOB@@}`）。自己再包一层就变成 {{...}}，C 会当成
    # "第一个元素用嵌套初始化"，于是除了 magic 首字节全被丢掉的
    # warning: excess elements in scalar initializer。
    blob_c = ", ".join(str(b) for b in blob)

    return (TU.replace("@@CLIENT_BLOB@@", blob_c)
              .replace("@@CRC@@", crc_src)
              .replace("@@BRIDGE@@", BRIDGE_SNIPPET)
              .replace("@@HDRDEFS@@", hdr_defs)
              .replace("@@IMPL@@", body)
              .replace("@@POLICY@@", policy)
              .replace("@@MASK@@", mask)
              .replace("@@FIRESUFFIX@@", " +fire-keys" if fire else ""))


def main() -> int:
    root = (Path(sys.argv[1]).resolve()
            if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
            else DEFAULT_REPO.resolve())
    negative = "--negative" in sys.argv
    rc_path, km_hdr, bridge_hdr = (root / RC_REL, root / KM_HDR_REL,
                                   root / BRIDGE_HDR_REL)
    if not (rc_path.exists() and km_hdr.exists() and bridge_hdr.exists()):
        print(f"SKIP: 固件树或头文件不齐（先跑 prepare_hero_build.py）\n  {km_hdr}")
        return 0

    rc_src = rc_path.read_text(encoding="utf-8", errors="ignore")
    km_src = km_hdr.read_text(encoding="utf-8", errors="ignore")
    br_src = bridge_hdr.read_text(encoding="utf-8", errors="ignore")

    impl = grab(rc_src, r"/\* ==== POLAR-KM-LINK: 图传键鼠链路.*?"
                       r"/\* ==== POLAR-KM-LINK 结束 ==== \*/",
                "POLAR-KM-LINK 实现段")
    check("从 remote_control.c 抽出仲裁实现段", "HostKmLinkUpdate" in impl)
    check("仲裁与回读分两层（回读不得挤掉仲裁的提前 return）",
          "static void HostKmLinkArbitrate(void)" in impl
          and "HostKmLinkArbitrate();\n    HostKmReportUplink();" in impl)
    import re as _re
    _names = _re.findall(r'ModifyDebugDataPackage\(HOST_KM_DEBUG_SLOT_\w+,\s*[^,]+,\s*"([^"]+)"\)', impl)
    check("回读名字都在 10 字符内（超长会被 usb_task.c:1414 静默截断）",
          bool(_names) and all(len(n) <= 9 for n in _names), str(_names))
    check("回读槽位不撞车", len(set(_names)) == len(_names), str(_names))

    # 载荷/门限/新鲜度判据全部从真头文件里抽，测试与固件不可能各说各话
    # 每段之间必须补换行：上一段以 `prm1_km_cmd_t;` 结尾且不含换行，
    # 直接拼就会把下一个 #define 顶到同一行 -> 编译器报
    # "expected identifier or '('"，而且报的是上一行的行号，极难定位。
    hdr = grab(km_src, r"#define PRM1_MAGIC_0.*?\}\s*__packed__ prm1_km_cmd_t;",
               "PRM1 载荷定义") + "\n"
    # 两条编译期尺寸断言也要抽进来：漏了它们，"结构体大小对不上"这种
    # 只有 Keil/ARMCC 才会发现的问题在离线测试里就是绿灯。
    hdr += grab(km_src, r"typedef char HOST_KM_STATIC_ASSERT_size;?"
                       r"[^\n]*\n", "size 断言")
    hdr += grab(km_src, r"typedef char HOST_KM_STATIC_ASSERT_pack[^\n]*\n", "pack 断言")
    hdr += grab(km_src, r"#define KM_LINK_VALID_MS[^\n]*\n", "KM_LINK_VALID_MS")
    # 两个掩码也得抽：测试里的 KM_KEY_ALLOWED_MASK 是展开成
    # (KM_KEY_MASK_DRIVE | KM_KEY_MASK_FIRE) 的，漏抽就变成未声明标识符。
    hdr += grab(km_src, r"#define KM_KEY_MASK_DRIVE[^\n]*\n", "KM_KEY_MASK_DRIVE")
    hdr += grab(km_src, r"#define KM_KEY_MASK_FIRE[^\n]*\n", "KM_KEY_MASK_FIRE")
    # 收尾必须精确到宏自己的最后一行。原先写成 `.*?HOST_KM_RX_TIME)[^\n]*\n`
    # 再加一条 `[^\n]*\n`，第二条会把**紧跟其后的那一行**一起吃掉——在这里
    # 正好吞掉了 `#define __CONTROL_LINK_KM ...`，症状是宏"没定义"，
    # 而报错位置在几十行之外的 #if 处，完全看不出是抽取越界。
    hdr += grab(km_src,
                r"#define HOST_KM_IS_FRESH\(\)[^\n]*\n(?:[ \t]*[^\n]*\n)*?"
                r"[ \t]*\([^\n]*KM_LINK_VALID_MS\)\)\n",
                "HOST_KM_IS_FRESH")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_UPLINK[^\n]*\n", "DEBUG_UPLINK")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_PERIOD_MS[^\n]*\n", "DEBUG_PERIOD")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_SLOT_RX[^\n]*\n", "DEBUG_SLOT_RX")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_SLOT_KEY[^\n]*\n", "DEBUG_SLOT_KEY")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_SLOT_FRAME_OK[^\n]*\n", "SLOT_FRAME_OK")
    hdr += grab(km_src, r"#define HOST_KM_DEBUG_SLOT_FRAME_BAD[^\n]*\n", "SLOT_FRAME_BAD")
    hdr += grab(km_src, r"extern void ModifyDebugDataPackage[^\n]*\n", "回读原型")
    check("从 host_km_link.h 抽出载荷与新鲜度判据", "prm1_km_cmd_t" in hdr)
    check("回读宏与原型也从真头文件抽（不另写一份）",
          "HOST_KM_DEBUG_SLOT_RX" in hdr and "ModifyDebugDataPackage" in hdr)
    # 新增两个槽同样从真头文件抽：抄数字就会出现"测试绿、车上槽位撞车"
    check("km_ok/km_bad 的槽号也从真头文件抽（不许在测试里抄数字）",
          "HOST_KM_DEBUG_SLOT_FRAME_OK" in hdr
          and "HOST_KM_DEBUG_SLOT_FRAME_BAD" in hdr)

    global BRIDGE_SNIPPET
    BRIDGE_SNIPPET = (
        grab(br_src, r"#define HOST_RC_DRIVE_KEY_MASK[^\n]*\n", "驾驶键掩码")
        + grab(br_src, r"#define HOST_RC_KM_KEY_NONE.*?"
                       r"#define HOST_RC_DRIVER_GATE_SHUT[^\n]*\n", "门闸常量")
        + "extern volatile uint16_t HOST_RC_DRIVER_KEYS;\n"
        + "extern volatile uint16_t HOST_RC_HOST_KEYS;\n"
        + "extern volatile uint16_t HOST_RC_DRIVER_KEY_GATE;\n"
        + "extern volatile uint16_t HOST_RC_KM_KEYS;\n"
        + "volatile uint16_t HOST_RC_DRIVER_KEYS = 0;\n"
        + "volatile uint16_t HOST_RC_HOST_KEYS = 0;\n"
        + "volatile uint16_t HOST_RC_DRIVER_KEY_GATE = HOST_RC_DRIVER_GATE_OPEN;\n"
        + "volatile uint16_t HOST_RC_KM_KEYS = HOST_RC_KM_KEY_NONE;\n"
        + grab(br_src, r"#define HOST_RC_MERGED_KEYS\(\).*?HOST_RC_KM_KEYS\)\)\n",
               "合并宏")
    )
    check("从 host_chassis_bridge.h 抽出三本账与合并宏",
          "HOST_RC_MERGED_KEYS" in BRIDGE_SNIPPET)

    inc_dirs = sorted({str(p.parent) for p in root.rglob("*.h")})
    runs = [(p, False) for p in POLICIES] + [("CL_KM_VT", True)]

    with tempfile.TemporaryDirectory() as td:
        for policy, fire in runs:
            label = f"{policy}{' +fire-keys' if fire else ''}"
            tu = build_tu(impl, hdr, policy, fire, negative, extract_official_crc(root))
            if fire:
                tu = "#define KM_TEST_FIRE_KEYS 1\n" + tu
            stem = f"km_{policy}{'_fire' if fire else ''}"
            cpath, epath = Path(td) / f"{stem}.c", Path(td) / f"{stem}.exe"
            cpath.write_text(tu, encoding="utf-8")
            # 排障用：编译挂了就把生成的 TU 留一份，不然临时目录一删就没法看
            # 编译器指着的那一行到底是什么。
            # 排障开关：KM_TU_DUMP=<路径> 时把生成的 TU 留一份，
            # 否则临时目录一删，编译器指的那一行就没法看了。
            _dump = __import__("os").environ.get("KM_TU_DUMP")
            if _dump:
                Path(_dump).write_text(tu, encoding="utf-8")
            build = subprocess.run(
                [sys.executable, "-m", "ziglang", "cc", "-O0", "-Wall",
                 "-Wno-unused-parameter", "-Wno-comment", "-Wno-unused-variable",
                 # 官方 CRC8_CRC16.c 里的 include 大小写与文件名不一致（Windows 无妨），
                 # 但 -Wall 会报 non-portable-path，而本测试把任何输出都当失败
                 "-Wno-nonportable-include-path",
                 "-o", str(epath), str(cpath)] + [f"-I{d}" for d in inc_dirs],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            raw = (build.stderr or "") + (build.stdout or "")
            # 报错要**头尾都给**：只给尾巴会把第一条真错处切掉，
            # 而"too many errors emitted"恰恰说明头里才有根因。
            out = raw[:1200] if len(raw) <= 2400 else raw[:1200] + "\n...\n" + raw[-500:]
            check(f"{label} 编译通过", build.returncode == 0, out)
            if build.returncode != 0:
                continue
            run = subprocess.run([str(epath)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            body = ((run.stdout or "") + (run.stderr or "")).strip()
            check(f"{label} 行为断言全过", run.returncode == 0, body[-400:])

    print("\n" + "=" * 62)
    if negative:
        print("阴性对照通过：旧写法被这些断言抓到了" if FAILED else
              "注意：旧写法没被抓到，说明断言是假的，得加强")
        return 0 if FAILED else 1
    print("有失败项" if FAILED else "五档仲裁 + 摇杆底线 + 开火权限 全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
