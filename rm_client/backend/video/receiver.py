"""旧接收端串口所有者：发现、状态回读、信道设置与角度发送调度。"""
from __future__ import annotations

import threading
import time
from typing import Any

from .angle_egress import LegacyAngleEgress
from .receiver_protocol import (
    CHANNEL_FREQUENCIES, QUERY_STATUS, SET_CONFIG, ReceiverFrameParser,
    channel_payload, encode_receiver_command, status_parameters,
)


def discover_receiver_port() -> str:
    """只枚举 VID/PID 匹配的旧接收端，禁止回退为第一个可用 COM 口。"""
    from serial.tools import list_ports
    ports = [p.device for p in list_ports.comports()
             if p.vid == 0x2CA3 and p.pid == 0x001F]
    if len(ports) != 1:
        raise RuntimeError(f"需要唯一的旧图传接收端 2CA3:001F，实际找到 {len(ports)} 个")
    return ports[0]


class LegacyReceiverControl:
    """独占接收端串口的单个线程；停止期间保留所有权直到 close 真正完成。"""
    def __init__(self, channel: int = 1) -> None:
        if channel not in CHANNEL_FREQUENCIES:
            raise ValueError("Legacy channel must be 1..6")
        self.channel = channel
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial: Any = None
        self._state = "stopped"
        self._error = ""
        self._close_error = ""
        self._port = ""
        self._received_bytes = 0
        self._parsed_frames = 0
        self._status_frames = 0
        self._queries = 0
        self._configuration_writes = 0
        self._frequency = 0
        self._last_status_at = 0.0
        self._invalid_frames = 0
        self._last_status_hex = ""
        self.angle_egress = LegacyAngleEgress()

    @property
    def owned_port(self) -> str:
        """已选串口在 close 确认完成前一直保留给本线程。"""
        with self._lock:
            return (self._port or "Auto") if not self.cleanup_complete else ""

    def write_angles(self, frame: bytes, permit) -> int:
        if not self.stats()["ready"] or self._stop.is_set():
            raise IOError("Legacy receiver is not ready")
        return self.angle_egress.write(frame, permit)

    @property
    def cleanup_complete(self) -> bool:
        with self._lock:
            return (self._serial is None and not self._close_error
                    and (self._thread is None or not self._thread.is_alive()))

    @property
    def stop_pending(self) -> bool:
        return self._stop.is_set() and not self.cleanup_complete

    def start(self) -> None:
        with self._lock:
            if not self.cleanup_complete:
                return
            self._stop = threading.Event()
            self._state, self._error = "opening", ""
            self._last_status_at = 0.0
            self._frequency = 0
            self._received_bytes = self._parsed_frames = self._status_frames = 0
            self._queries = self._configuration_writes = self._invalid_frames = 0
            self._last_status_hex = ""
            self._thread = threading.Thread(target=self._run, name="PolarLegacyReceiver", daemon=True)
            self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()
        self.angle_egress.cancel()
        with self._lock:
            if (self._serial is not None and self._close_error
                    and (self._thread is None or not self._thread.is_alive())):
                # 重试只负责上一次未确认的 close，不启动第二个设备所有者。
                self._thread = threading.Thread(target=self._close_serial, name="PolarLegacyClose", daemon=True)
                self._thread.start()

    def wait_closed(self, timeout: float | None = None) -> bool:
        worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout)
        return self.cleanup_complete

    def stop(self) -> None:
        self.request_stop()
        self.wait_closed(2.0)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            fresh = self._last_status_at > 0 and time.monotonic() - self._last_status_at < 3.0
            return {"state": self._state, "port": self._port, "channel": self.channel,
                    "frequency": self._frequency, "status_fresh": fresh,
                    "ready": self._state == "ready" and fresh,
                    "received_bytes": self._received_bytes, "parsed_frames": self._parsed_frames,
                    "status_frames": self._status_frames, "queries_sent": self._queries,
                    "configuration_writes": self._configuration_writes,
                    "invalid_frames": self._invalid_frames, "error": self._error,
                    "last_status_hex": self._last_status_hex,
                    "angle_packets_written": self.angle_egress.written,
                    "last_angle_packet_hex": self.angle_egress.last_packet.hex(),
                    "angle_error": self.angle_egress.last_error,
                    "close_error": self._close_error, "official_process_required": False}

    def _run(self) -> None:
        parser = ReceiverFrameParser()
        port = None
        try:
            import serial
            name = discover_receiver_port()
            # 与官方默认一致：DTR/RTS 不主动置位，无硬件流控。
            port = serial.Serial(port=None, baudrate=961200, timeout=0.005, write_timeout=0.020)
            port.dtr = False
            port.rts = False
            port.port = name
            with self._lock:
                self._serial, self._port = port, name
            if self._stop.is_set():
                return
            port.open()
            with self._lock:
                self._state = "querying"
            if self._stop.wait(0.3):
                return
            next_query = 0.0
            last_config = 0.0
            began = time.monotonic()
            while not self._stop.is_set():
                self.angle_egress.pump(port, self.stats()["ready"] and not self._stop.is_set())
                now = time.monotonic()
                if now >= next_query:
                    port.write(encode_receiver_command(QUERY_STATUS))
                    self._queries += 1
                    next_query = now + 1.0
                data = port.read(min(max(port.in_waiting, 1), 4096))
                with self._lock:
                    self._received_bytes += len(data)
                for frame in parser.feed(data):
                    parameters = status_parameters(frame)
                    with self._lock:
                        self._parsed_frames += 1
                        self._invalid_frames = parser.invalid_frames
                        if parameters is None:
                            continue
                        self._status_frames += 1
                        self._last_status_hex = frame.packet.hex()
                        self._last_status_at = now
                        self._frequency = parameters.get(15, 0)
                        if self._frequency == CHANNEL_FREQUENCIES[self.channel]:
                            self._state, self._error = "ready", ""
                        elif now - last_config >= 1.0:
                            # 只有真实参数响应证明地址和封装成立后才设置接收信道。
                            if self._configuration_writes >= 3:
                                raise RuntimeError("接收端信道设置未获回读确认，请手动重连")
                            port.write(encode_receiver_command(SET_CONFIG, channel_payload(self.channel)))
                            self._configuration_writes += 1
                            last_config = now
                            self._state = "configuring"
                if now - max(self._last_status_at, began) > 5.0:
                    raise RuntimeError("接收端状态查询超时，请检查供电或官方进程占用后手动重连")
        except Exception as exc:
            with self._lock:
                self._state, self._error = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.angle_egress.cancel()
            self._close_serial()

    def _close_serial(self) -> None:
        with self._lock:
            port = self._serial
        try:
            if port is not None:
                port.close()
            with self._lock:
                self._serial = None
                self._close_error = ""
        except Exception as exc:
            with self._lock:
                self._close_error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            if self._stop.is_set() and not self._close_error:
                self._state = "stopped"
