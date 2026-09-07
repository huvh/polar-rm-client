# -*- coding: utf-8 -*-
"""松手帧必须落地：DT7/DR16 没有过期自动清零，被 max_hz 挡下的中立帧 = 车带着最后一帧的按键一直跑。

为什么单开一个文件：test_dt7_review_fixes.py 那六节量的是"鼠标增量被吃掉"，
而这一坑的形状完全不同——**驾驶键位**被吃掉。复现出来的原始数字（HEAD 99f918c）：
心跳 75Hz、DT7 出口闸 30Hz，在限流窗口的 24 个相位上松手，
松手那一帧 **24/24 全被挡**；最好情况也要等 4Hz 空闲零帧补上 = **253ms**
（3.5m/s 下将近一米过冲）；若 MQTT 发得出去而空闲零帧没授权（arm 了但不在打仗阶段、
或 LabDebug 那类 enforce_official_limits=False 的场景），心跳不再被任何东西驱动，
**线上永远停在那次按住的键上**。这里全部用假时钟，一次 sleep 都没有。
"""
from __future__ import annotations

import struct
import sys
import time as real_time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rm_client.control as C                                   # noqa: E402
from rm_client.backend import dt7_link as dl                    # noqa: E402
from rm_client.model import RobotState, build_default_registry   # noqa: E402

FAILED = 0
W_BIT = 1                                                        # keyboard_value 里的 W


def check(name, ok, detail=""):
    global FAILED
    print(("[ OK ] " if ok else "[FAIL] ") + name + (("  " + detail) if detail else ""))
    FAILED += 0 if ok else 1


def keys_of(frame):
    dec = dl.decode_dt7_frame(frame)
    if dec is None:
        return None
    return struct.unpack_from("<H", dec["payload"], 8)[0]


def mouse_of(frame):
    dec = dl.decode_dt7_frame(frame)
    if dec is None:
        return None
    return struct.unpack_from("<hhh", dec["payload"], 0)


class FakeTime:
    """control.py 与 dt7_link 共用这一把钟：整条链没有真实 sleep，结果可复算。"""

    def __init__(self):
        self.t = 0.0

    def perf_counter(self):
        return self.t

    def time(self):
        return real_time.time()


CLOCK = FakeTime()
C.time = CLOCK


def make_link(sink=None, max_hz=30.0):
    prof = dict(dl.load_profile())
    prof["max_hz"] = max_hz
    seen: list = []
    link = dl.Dt7KeyMouseLink(port="DT7", profile=prof, mock_output=False,
                              write_bytes=(sink if sink is not None else seen.append),
                              time_fn=CLOCK.perf_counter)
    return link, seen


class Pub:
    def __init__(self, ok=True):
        self.ok = ok

    def publish_keyboard_mouse(self, *a, **k):
        return (True, "ok") if self.ok else (False, "match control is LOCKED")


def make_ctl(link, *, idle_authorized=False, pub_ok=True):
    ctl = C.KeyboardControlBridge(Pub(pub_ok), mock_output=False)
    ctl.dt7_link = link
    ctl.dt7_enabled = True
    ctl.dt7_key_mask = 0xFFFF
    ctl._idle_zero_authorized = lambda: idle_authorized
    return ctl


STATE = RobotState()
REG = build_default_registry()
STEP = 1.0 / 75.0        # 心跳


print("\n--- 1) 出口层：线上还按着键时，中立帧必须破例挤出去 ---")
link, bus = make_link(max_hz=30.0)
CLOCK.t = 0.0
ok_press, _ = link.send(pressed_bits=W_BIT)
check("按 W 这一帧发出去了", ok_press and keys_of(bus[-1]) == W_BIT, str([keys_of(f) for f in bus]))
check("发过非中立帧之后，线上状态记为『还按着』", link.wire_neutral is False)
CLOCK.t += 0.005                                       # 离上一帧只有 5ms（< 1/30）
ok_rel, why_rel = link.send(pressed_bits=0)
check("5ms 后的松手帧不许被 30Hz 闸挡下", ok_rel and keys_of(bus[-1]) == 0, why_rel)
check("这次破例要记账（界面上/自检要看得到）", link.forced_releases == 1, str(link.forced_releases))
check("松手之后线上状态记为『中立』", link.wire_neutral is True)
CLOCK.t += 0.005
ok_again, why_again = link.send(pressed_bits=0)
check("已经中立了就不许再破例（否则松手能被刷成洪泛）",
      (not ok_again) and link.last_send_rate_limited is True, why_again)
check("非中立帧照旧受 30Hz 管（破例只给松手）",
      (not link.send(pressed_bits=W_BIT)[0]) and link.forced_releases == 1)

print("\n--- 2) 出口层：写口失败 = 线没变，下一帧还得能插队 ---")
boom = {"on": False}


def flaky(frame):
    if boom["on"]:
        raise OSError("模拟：DT7 口被占用")
    bus2.append(bytes(frame))


bus2: list = []
link2 = dl.Dt7KeyMouseLink(port="DT7", profile=dict(dl.load_profile(), max_hz=30.0),
                           mock_output=False, write_bytes=flaky,
                           time_fn=CLOCK.perf_counter)
CLOCK.t = 0.0
ok_w, _ = link2.send(pressed_bits=W_BIT)              # 先让 W 真的落到线上
check("前置：W 已经写上线", ok_w and link2.wire_neutral is False, str(len(bus2)))
boom["on"] = True
CLOCK.t += 0.001
ok0, why0 = link2.send(pressed_bits=0)                # 松手这一帧：写失败
check("写失败要记 last_send_dropped（调用方得知道该补）",
      (not ok0) and link2.last_send_dropped is True, why0)
check("写失败不许把线上状态改成中立（我们根本没送到）", link2.wire_neutral is False)
boom["on"] = False
CLOCK.t += 0.001
ok2, why2 = link2.send(pressed_bits=0)
check("口恢复后的第一帧松手仍然破例送出（不等多一个周期）",
      ok2 and keys_of(bus2[-1]) == 0, why2)

print("\n--- 3) 控制层：24 个限流相位松手，零帧必须在一个心跳内落地 ---")
worst = {"idle_true": 0.0, "idle_false": 0.0}
stuck_total = 0
for idle_auth in (True, False):
    key = "idle_true" if idle_auth else "idle_false"
    for phase in range(24):
        CLOCK.t = 0.0
        lk, bs = make_link(max_hz=30.0)
        ct = make_ctl(lk, idle_authorized=idle_auth)
        ct.set_key("W", True, STATE, REG)
        while CLOCK.t < 0.30:
            CLOCK.t += STEP
            ct.tick(STATE, REG, CLOCK.t)
        held = len(bs)
        CLOCK.t += phase / 24.0 / 30.0                # 在限流窗口里不同位置松手
        t_rel = CLOCK.t
        ct.set_key("W", False, STATE, REG)
        limit = CLOCK.t + 3.0
        first_zero = None
        while CLOCK.t < limit:
            CLOCK.t += STEP
            ct.tick(STATE, REG, CLOCK.t)
            if first_zero is None:
                for fr in bs[held:]:
                    if keys_of(fr) == 0:
                        first_zero = CLOCK.t
                        break
        lag = 9999.0 if first_zero is None else (first_zero - t_rel) * 1000.0
        worst[key] = max(worst[key], lag)
        if keys_of(bs[-1]) != 0:
            stuck_total += 1
check("两种空闲零帧授权下，松手延迟都 < 一个心跳 × 2",
      max(worst.values()) < 30.0, f"最大 {worst['idle_true']:.1f} / {worst['idle_false']:.1f} ms")
check("3 秒后线上仍带着 W 的次数 = 0", stuck_total == 0, str(stuck_total))

print("\n--- 4) 控制层：pending 的生命周期（不许空转、也不许撒手不管）---")
CLOCK.t = 0.0
dead = {"on": False}
lk4, bs4 = make_link(sink=lambda f: (_ for _ in ()).throw(OSError("口没了")) if dead["on"] else bs4.append(f))
ct4 = make_ctl(lk4, idle_authorized=False)
ct4.set_key("W", True, STATE, REG)
dead["on"] = True
ct4.set_key("W", False, STATE, REG)
check("写失败 + 要松手 => pending 立起来", ct4.dt7_release_pending is True)
ct4._idle_zero_authorized = lambda: False             # 没有任何别的东西会再驱动心跳
n_before = len(bs4)
for _ in range(30):
    CLOCK.t += STEP
    ct4.tick(STATE, REG, CLOCK.t)
check("pending 期间心跳必须继续尝试（否则就是永久粘键）",
      ct4.dt7_release_pending is True, "30 个 tick 后仍未送达")
dead["on"] = False
CLOCK.t += STEP
ct4.tick(STATE, REG, CLOCK.t)
check("口一恢复，零帧立刻补上且 pending 落回去",
      (not ct4.dt7_release_pending) and keys_of(bs4[-1]) == 0, str(keys_of(bs4[-1])))
lk4b, _bs = make_link(max_hz=30.0)
lk4b._gate = lambda: "没勾 Allow Drive"
ct4b = make_ctl(lk4b)
ct4b.set_key("W", True, STATE, REG)
ct4b.set_key("W", False, STATE, REG)
check("闸门拒绝（配置问题）不许立 pending——否则心跳白转",
      ct4b.dt7_release_pending is False)
ct4b.dt7_send_paused = True
ct4b.dt7_release_pending = True
for _ in range(3):                                    # 心跳对齐会吃掉第一个 tick
    CLOCK.t += STEP
    ct4b.tick(STATE, REG, CLOCK.t)                    # 真正发出去的那一 tick 会清 pending
CLOCK.t += STEP
check("自检暂停时 pending 要清掉（tick 不能被它钉在 75Hz 空转）",
      ct4b.dt7_release_pending is False and ct4b.tick(STATE, REG, CLOCK.t) is None)
ct4c = make_ctl(make_link()[0])
ct4c.dt7_enabled = False
ct4c.dt7_release_pending = True
for _ in range(3):
    CLOCK.t += STEP
    ct4c.tick(STATE, REG, CLOCK.t)
CLOCK.t += STEP
check("出口关着时 tick 也不许被 pending 钉住",
      ct4c.dt7_release_pending is False and ct4c.tick(STATE, REG, CLOCK.t) is None)

print("\n--- 5) release_all：只清本地不算松手，线上必须中立 ---")
CLOCK.t = 0.0
lk5, bs5 = make_link(max_hz=30.0)
ct5 = make_ctl(lk5, idle_authorized=True)
ct5.set_key("W", True, STATE, REG)
CLOCK.t += 0.001                                      # 故意卡在限流窗口里
ct5.release_all(STATE, REG)
check("release_all 之后线上最后一帧是全零键位", keys_of(bs5[-1]) == 0, hex(keys_of(bs5[-1])))
check("release_all 之后 pending 落回 False", ct5.dt7_release_pending is False)

print("\n--- 6) 洪泛守卫：反复按/松也不许把 DT7 的口刷爆 ---")
CLOCK.t = 0.0
lk6, bs6 = make_link(max_hz=30.0)
ct6 = make_ctl(lk6, idle_authorized=True)
for i in range(200):                                  # 200 * 13.3ms = 2.67s 的抖动操作
    CLOCK.t += STEP
    ct6.set_key("W", bool(i % 2), STATE, REG)
    ct6.tick(STATE, REG, CLOCK.t)
expected_max = 2.0 * (2.67 * 30.0 + 2)                # 正常闸 + 每次松手最多一个破例
check("2.67 秒内写到 DT7 的帧数不超过 2*max_hz 上限",
      len(bs6) <= expected_max, f"{len(bs6)} 帧 / 上限 {expected_max:.0f}")
check("按住期与非按住期的帧里键位与线上最后一帧一致",
      keys_of(bs6[-1]) in (0, W_BIT), hex(keys_of(bs6[-1])))

print("\n--- 7) 水印不许说假话（real 但口没开 = 必须写出来）---")
t1 = dl.status_token(mock_output=False, resolved_port="")
check("勾了真发、却从没成功打开过任何口 => 不许显示成光鲜的 real",
      t1 == "DT7:real(口未开)", t1)
check("真在往某个口写 => DT7:real@COM7",
      dl.status_token(mock_output=False, resolved_port="COM7") == "DT7:real@COM7")
check("没勾真发 => mock（不碰硬件）", dl.status_token(mock_output=True) == "DT7:mock")
check("出口没开 => 一个字都不显示", dl.status_token(mock_output=True, enabled=False) == "")
check("线上还挂着按键 => 上脸", "线上仍带按键" in dl.status_token(
    mock_output=False, resolved_port="COM7", wire_neutral=False))
check("松手帧没送达 => 上脸", "松手帧未送达" in dl.status_token(
    mock_output=False, resolved_port="COM7", release_pending=True))
check("原因写在最后且不截断语义", dl.status_token(
    mock_output=False, resolved_port="COM7", last_error="闸门未过").endswith("(!闸门未过)"))
lk7, bs7 = make_link(max_hz=100000.0)
ct7 = make_ctl(lk7)
ct7.set_key("W", True, STATE, REG)
check("按下去之后水印自己会报『线上仍带按键』（不是我们猜开关状态）",
      "线上仍带按键" in lk7.watermark_token(), lk7.watermark_token())
ct7.set_key("W", False, STATE, REG)
check("松手落地之后那句话要消失", "线上仍带按键" not in lk7.watermark_token(), lk7.watermark_token())

print("\n" + ("松手帧全部落地" if FAILED == 0 else str(FAILED) + " 条失败"))
sys.exit(1 if FAILED else 0)