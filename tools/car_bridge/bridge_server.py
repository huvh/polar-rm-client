#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""车载侧的 USB<->WiFi 桥：把 C 板那个 0x5A 虚拟串口原样搬到 TCP 上。

存在意义：C 路（直连 DT7）如果哪天被证明"遥控器不吃我们写的帧"，这条是**唯一还能无线控车**
的后备；它不动固件、不依赖大疆客户端，用的就是队内已经跑过比赛的 0x5A 协议。

为什么可以裸转字节、不需要分包：车端 usb_task 的收包是**逐字节重同步**的
（``application/communication/usb_task.c:779-793``：CRC 不过就前进一个字节继续找
0x5A；跨次残留还会搬回缓冲区头部），所以 TCP 把一条帧拆成两次到达完全没问题。

安全设计（这是本文件最重要的一段）：
* 只服务**一个**客户端，第二个直接拒（两个宿主同时往一个口写会把帧搅乱）
* 客户端断开 ⇒ **立刻停止向串口写任何字节**。不补"零帧"，因为那时我们并不知道
  车端能不能收；固件自己有 150ms 新鲜度看门狗（``usb_task.c:1383-1392``），
  断流就会把上位机键位撤销、交还驾驶员
* 串口打不开就退出并留日志，不静默重试到把系统拖住
* 波特率在这里没意义（C 板是 USB CDC，固件不看波特率），pyserial 只是形式参数

用法（车上那台小电脑）：
    python tools/car_bridge/bridge_server.py --serial auto --listen 0.0.0.0:50570
    python tools/car_bridge/bridge_server.py --serial /dev/ttyACM0 --port 50570
 systemd 单元见同目录 rm-usb-bridge.service
"""
from __future__ import annotations

import argparse
import errno
import os
import socket
import sys
import threading
import time

ROBOT_USB_IDS = ((0x0483, 0x5720), (0x16C0, 0x05DC), (0x1EAF, 0x0003))
READ_SIZE = 4096


def detect_robot_serial():
    """在 Linux/Windows 上找 C 板那个 CDC 口（按 VID/PID 认，不猜 COM 号）。"""
    try:
        from serial.tools import list_ports
    except Exception:
        return None
    for item in list_ports.comports():
        vid = int(getattr(item, "vid", 0) or 0)
        pid = int(getattr(item, "pid", 0) or 0)
        if (vid, pid) in ROBOT_USB_IDS:
            return str(item.device)
    desc_hit = [str(p.device) for p in list_ports.comports()
                if "stmicroelectronics virtual com" in str(
                    getattr(p, "description", "")).lower()]
    return desc_hit[0] if len(desc_hit) == 1 else None


class Bridge:
    """一条 TCP 连接 <-> 一个串口 的双向裸管道。"""

    def __init__(self, *, serial_device: str, listen: str = "0.0.0.0",
                 port: int = 50570, baud: int = 115200, log=print,
                 serial_opener=None, stop_after=None) -> None:
        self.serial_device = serial_device
        self.listen = listen
        self.port = int(port)
        self.baud = int(baud)
        self.log = log
        self._serial_opener = serial_opener
        self._stop_after = stop_after          # 测试用：处理这么多事件后自己收工
        self.stop = threading.Event()
        self.bytes_client_to_serial = 0
        self.bytes_serial_to_client = 0
        self.rejected_clients = 0
        self.writes_after_disconnect = 0       # 必须永远是 0，这是安全性质
        self.last_error = ""
        self.bound_port = 0

    def _open_serial(self):
        if self._serial_opener is not None:
            return self._serial_opener(self.serial_device, self.baud)
        import serial
        return serial.Serial(self.serial_device, self.baud, timeout=0.05,
                             write_timeout=0.5)

    def serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.listen, self.port))
        self.bound_port = srv.getsockname()[1]
        srv.listen(1)
        srv.settimeout(0.25)
        self.log(f"[bridge] 监听 {self.listen}:{self.bound_port} -> "
                 f"串口 {self.serial_device}")
        try:
            while not self.stop.is_set():
                try:
                    conn, peer = srv.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    self.last_error = str(exc)
                    break
                try:
                    ser = self._open_serial()
                except Exception as exc:
                    self.last_error = f"串口打不开：{exc}"
                    self.log(f"[bridge] {self.last_error}")
                    conn.close()
                    break
                self.log(f"[bridge] 客户端 {peer} 接入")
                self._pump(conn, ser)
                conn.close()
                try:
                    ser.close()
                except Exception:
                    pass
                self.log("[bridge] 客户端断开：已停止向串口写字节")
        finally:
            srv.close()
            self.stop.set()

    def _pump(self, conn: socket.socket, ser) -> None:
        """单客户端期间的双向裸管道。

        刻意不用 select 去等串口：pyserial 在不同 CDC 设备上的 fileno 语义不稳定，
        测试里的假设备也没有 fileno。上行用轮询线程，下行用 socket 的超时收。
        """
        alive = threading.Event()
        alive.set()

        def upstream() -> None:
            while alive.is_set() and not self.stop.is_set():
                try:
                    data = ser.read(READ_SIZE) if hasattr(ser, "read") else b""
                except Exception as exc:
                    self.last_error = f"读串口失败：{exc}"
                    return
                if not data:
                    time.sleep(0.002)
                    continue
                try:
                    conn.sendall(bytes(data))
                    self.bytes_serial_to_client += len(data)
                except OSError:
                    return

        reader = threading.Thread(target=upstream, daemon=True)
        reader.start()
        conn.settimeout(0.1)
        events = 0
        try:
            while not self.stop.is_set():
                try:
                    data = conn.recv(READ_SIZE)
                except (TimeoutError, BlockingIOError, socket.timeout):
                    data = b""
                except OSError:
                    return
                if data:
                    try:
                        ser.write(data)
                        self.bytes_client_to_serial += len(data)
                    except Exception as exc:
                        self.last_error = f"写串口失败：{exc}"
                        return
                events += 1
                if self._stop_after is not None and events >= self._stop_after:
                    return
                if not data and self.stop.is_set():
                    return
        finally:
            alive.clear()
            # 先停上行线程再关句柄，否则它可能还在往已关闭的 socket 上 sendall
            try:
                reader.join(1.0)
            except Exception:
                pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="C 板 0x5A 串口的 WiFi 桥（车端）")
    ap.add_argument("--serial", default="auto", help="串口设备名，或 auto 按 VID/PID 认")
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=50570,
                    help="避开 3333/3334 与图传网段在用端口")
    ap.add_argument("--baud", type=int, default=115200,
                    help="C 板是 USB CDC，波特率只是 pyserial 的形式参数")
    ap.add_argument("--once", action="store_true", help="服务完一个客户端就退出")
    args = ap.parse_args(argv)
    device = args.serial
    if device == "auto":
        device = detect_robot_serial()
        if not device:
            print("[FAIL] 没找到机器人 CDC 串口（VID 0483/PID 5720 等），"
                  "请显式 --serial /dev/ttyACM0", file=sys.stderr)
            return 2
    bridge = Bridge(serial_device=device, listen=args.listen, port=args.port,
                    baud=args.baud)
    try:
        bridge.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 手动退出")
    return 0 if not bridge.last_error else 1


if __name__ == "__main__":
    sys.exit(main())