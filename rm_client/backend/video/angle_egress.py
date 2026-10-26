"""旧图传角度出口：单槽交接、临写授权复核与完整写确认；串口由接收端独占。"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable

from .receiver_protocol import encode_receiver_angles


@dataclass
class _AngleWrite:
    packet: bytes
    permit: Callable[[], bool]
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    written: int = 0
    error: str = ""
    cancelled: bool = False


class LegacyAngleEgress:
    """单槽交接；成功计数必须来自串口线程的完整写完成，排队不算发送成功。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: _AngleWrite | None = None
        self.written = 0
        self.last_packet = b""
        self.last_error = ""
        self._last_write_at = -float("inf")

    def write(self, frame: bytes, permit: Callable[[], bool]) -> int:
        request = _AngleWrite(encode_receiver_angles(frame), permit, time.monotonic() + 0.150)
        with self._lock:
            if self._pending is not None:
                raise IOError("Legacy angle writer already has a pending sample")
            self._pending = request
        if not request.done.wait(0.200):
            # 取消还未开始的写。若 OS 写已经开始，其完成不再构成授权。
            with self._lock:
                request.cancelled = True
                if self._pending is request:
                    self._pending = None
            raise TimeoutError("Legacy angle write completion timed out")
        if request.error:
            raise IOError(request.error)
        return len(frame) if request.written == len(request.packet) else 0

    def pump(self, port, ready: bool) -> None:
        """仅 COM14 所有者调用；临写前再次检查新鲜度、授权和停止状态。"""
        with self._lock:
            if time.monotonic() - self._last_write_at < 1.0 / 30.0:
                return
            request, self._pending = self._pending, None
        if request is None:
            return
        try:
            if (not ready or request.cancelled or time.monotonic() >= request.deadline
                    or not request.permit()):
                request.error = "Legacy angle write cancelled: receiver/input/permission no longer current"
                return
            if request.cancelled or time.monotonic() >= request.deadline:
                request.error = "Legacy angle write deadline expired"
                return
            request.written = port.write(request.packet)
            if request.written != len(request.packet):
                raise IOError(f"Legacy angle short write {request.written}/{len(request.packet)}")
            self._last_write_at = time.monotonic()
            self.written += 1
            self.last_packet = request.packet
            self.last_error = ""
        except Exception as exc:
            request.error = self.last_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            request.done.set()

    def cancel(self) -> None:
        with self._lock:
            request, self._pending = self._pending, None
            if request is not None:
                request.cancelled = True
                request.error = "Legacy receiver stopped"
                request.done.set()
