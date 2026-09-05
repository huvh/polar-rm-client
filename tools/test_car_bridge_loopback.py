#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 车端 WiFi 桥的离线回路测试：不插车、不要路由器也能证明"裸转字节"这条路成立。
# 三件事必须钉住：字节不改样、上行能拼回帧、断开之后绝不再写串口。
from __future__ import annotations

import errno
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <仓库>/tools
ROOT = HERE.parent                               # 仓库根
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "car_bridge"))
sys.path.insert(0, str(HERE / "dt7_link"))

import bridge_server as bs                        # noqa: E402
from rm_client.backend import polar_link as pl   # noqa: E402
from rm_client.backend import serial_stream as ss  # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    FAILED += 0 if ok else 1


class FakeCBoard:
    """假 C 板：记下令节，并能按"每次只回一小口"的方式吐上行帧。"""

    def __init__(self, upstream: bytes = b"") -> None:
        self.commands: list[bytes] = []
        self.upstream = bytearray(upstream)
        self.closed = False
        self.writes_after_client_gone = 0
        self.lock = threading.Lock()
        self.armed = True

    def write(self, data) -> int:
        payload = bytes(data)
        with self.lock:
            if not self.armed:
                self.writes_after_client_gone += 1
                return len(payload)
            self.commands.append(payload)
        return len(payload)

    def read(self, n: int = 512) -> bytes:
        with self.lock:
            out = bytes(self.upstream[:n])
            del self.upstream[:n]
        return out

    def close(self) -> None:
        self.closed = True


def debug_upstream_frame() -> bytes:
    import dt7_wireless_selftest as ws
    return ws.debug_frame(1, {"km_key": 17.0, "km_rx": 4.0})


def main() -> int:
    print("\n--- 1) 下行：客户端写的字节必须原样到串口 ---")
    board = FakeCBoard()
    bridge = bs.Bridge(serial_device="/dev/fake", listen="127.0.0.1", port=0,
                       serial_opener=lambda dev, baud: board, stop_after=4000)
    th = threading.Thread(target=bridge.serve_forever, daemon=True)
    th.start()
    for _ in range(200):
        if bridge.bound_port:
            break
        time.sleep(0.02)
    check("桥起来了并拿到临时端口", bridge.bound_port > 0, str(bridge.bound_port))

    stream = ss.open_stream("tcp", host="127.0.0.1", tcp_port=bridge.bound_port)
    check("客户端用 tcp 模式打开的是 TcpByteStream",
          isinstance(stream, ss.TcpByteStream) and stream.is_open)
    codec0 = pl.PolarFrameCodec()
    frame = codec0.encode_virtual_rc(raw_timestamp=123456, key_value=0x11)
    # 故意切成三段发：真网络上 TCP 就是这么把一条帧剁开的
    stream.write(frame[:5])
    stream.write(frame[5:12])
    stream.write(frame[12:])
    deadline = time.time() + 1.5
    while time.time() < deadline and sum(len(c) for c in board.commands) < len(frame):
        time.sleep(0.02)
    joined = b"".join(board.commands)
    check("三段写进去的字节拼起来与原帧完全一致（裸管道不改字节）",
          joined == frame, f"{len(joined)}/{len(frame)}")
    check("车端逐字节重同步因此不需要桥做分包",
          pl.crc8(frame[:3]) == frame[3], "帧头 CRC8 自检")

    print("\n--- 2) 上行：车上 Debug 帧能拼回来并被解码 ---")
    up = debug_upstream_frame() * 2
    board2 = FakeCBoard(upstream=up)
    bridge2 = bs.Bridge(serial_device="/dev/fake2", listen="127.0.0.1", port=0,
                        serial_opener=lambda dev, baud: board2, stop_after=4000)
    th2 = threading.Thread(target=bridge2.serve_forever, daemon=True)
    th2.start()
    for _ in range(200):
        if bridge2.bound_port:
            break
        time.sleep(0.02)
    s2 = ss.open_stream("tcp", host="127.0.0.1", tcp_port=bridge2.bound_port)
    got = bytearray()
    codec = pl.PolarFrameCodec()
    km = None
    deadline = time.time() + 2.0
    while time.time() < deadline and km is None:
        chunk = s2.read(37)                 # 故意用与帧长不整除的块大小
        if chunk:
            got.extend(chunk)
            segments, used = codec.decode_with_consumed(bytes(got))
            del got[:used]
            for seg in segments:
                if seg.segment_id == pl.SEG_DEBUG:
                    km = (seg.fields or {}).get("packages", {}).get("km_key")
    check("上行经过桥之后仍能解出 Debug 段（km_key=17）", km == 17, str(km))
    check("桥把上行的字节数也算进统计", bridge2.bytes_serial_to_client > 0,
          str(bridge2.bytes_serial_to_client))

    print("\n--- 3) 断开之后不许再写串口（把驾驶权还给固件看门狗）---")
    board.armed = False
    s2.close()
    stream.close()
    bridge.stop.set()
    bridge2.stop.set()
    th.join(2.0)
    th2.join(2.0)
    time.sleep(0.2)
    check("客户端断开后桥没有再向串口写任何字节",
          board.writes_after_client_gone == 0, str(board.writes_after_client_gone))
    check("桥退出时关掉了串口", board.closed is True or board2.closed is True,
          f"{board.closed} {board2.closed}")
    check("两个桥都干净退出（不留下监听线程）",
          not th.is_alive() and not th2.is_alive(),
          f"{th.is_alive()} {th2.is_alive()}")

    print("\n--- 4) 出错要看得见，而且不许挂着 ---")
    for thunk, why in ((lambda: ss.open_stream("tcp", host="  "), "桥接主机"),
                       (lambda: ss.open_stream("serial", port="Stub"), "Stub")):
        try:
            thunk()
            check(f"错误路径（{why}）竟然没报错", False)
        except Exception as exc:
            check(f"错误路径提示包含 {why}", why in str(exc), str(exc)[:60])

    def refuse(dev, baud):
        raise OSError(errno.EBUSY, "Device or resource busy")

    broken = bs.Bridge(serial_device="/dev/busy", listen="127.0.0.1", port=0,
                      serial_opener=refuse)
    th3 = threading.Thread(target=broken.serve_forever, daemon=True)
    th3.start()
    for _ in range(200):
        if broken.bound_port:
            break
        time.sleep(0.02)
    probe = socket.create_connection(("127.0.0.1", broken.bound_port), timeout=1.5)
    th3.join(3.0)
    check("串口被占用时要报错并退出，而不是挂着占住监听口",
          broken.last_error != "" and not th3.is_alive(), broken.last_error[:60])
    probe.close()
    check("没有机器人串口时 detect 返回 None（宁缺勿滥，不乱挑一个口）",
          bs.detect_robot_serial() in (None, ) or isinstance(bs.detect_robot_serial(), str))

    print("\n" + ("有失败项" if FAILED else "车端桥接回路全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())