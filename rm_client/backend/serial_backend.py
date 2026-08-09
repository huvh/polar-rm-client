"""??????? SharkClient ????????????????

- PySerial ???? + ?? 0xA5 ?????RefereeFrameCodec?
- Mock Writes ???????
- ?????????????????????????????
- ??????????????????????
- ????????????
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from ..protocol import RefereeFrameCodec, encode_custom_control_30
from ..transports import SerialBridgeStub

CUSTOM_CONTROL_CMD_ID = 0x0311


class RmSerialBackend(SerialBridgeStub):
    """SharkClient ?????????? Stub ???? stub?"""

    def __init__(
        self,
        port: str = "Stub",
        baud: int = 115200,
        mock_writes: bool = True,
        safety: Any = None,
    ) -> None:
        super().__init__()
        self.port = port
        self.baud = baud
        self.mock_writes = bool(mock_writes)
        self.safety = safety
        self.codec = RefereeFrameCodec()
        self.frames_written = 0
        self.frames_read = 0
        self.last_write_at = 0.0
        self.last_frame_at = 0.0
        self.heartbeat_interval_s = 0.25
        self.estop_active = False
        self._serial = None
        self._reader: threading.Thread | None = None
        self._running = False
        self._rx: deque[Any] = deque(maxlen=64)
        self._rx_lock = threading.Lock()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        if self.port in ("", "Stub", "stub", "None", "none"):
            self.connected = False
            self.last_error = "??????????Stub?"
            return
        try:
            import serial  # type: ignore
            self._serial = serial.Serial(
                port=self.port, baudrate=self.baud, timeout=0.1,
            )
            self.connected = bool(self._serial and self._serial.is_open)
            if not self.connected:
                self.last_error = "??????"
                return
            self._running = True
            self._reader = threading.Thread(target=self._read_loop, name="rm-serial", daemon=True)
            self._reader.start()
        except Exception as exc:  # pragma: no cover - depends on hardware
            self.connected = False
            self.last_error = str(exc)

    def stop(self) -> None:
        self._running = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self.connected = False

    # ------------------------------------------------------------------
    def write_frame(self, cmd_id: int, data: bytes = b"") -> tuple[bool, str]:
        frame = self.codec.encode(cmd_id, data)
        return self.write(frame)

    def write(self, payload: bytes) -> tuple[bool, str]:
        self.last_write = payload
        if self.mock_writes:
            return True, "mock"
        if self.estop_active:
            self.last_error = "????????????"
            return False, self.last_error
        if self._serial is None or not self.connected:
            self.last_error = "?????"
            return False, self.last_error
        try:
            self._serial.write(payload)
            self.frames_written += 1
            self.last_write_at = time.perf_counter()
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return False, str(exc)

    # ------------------------------------------------------------------
    # ??/??
    # ------------------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        if self.mock_writes or not self.connected:
            return
        now = time.perf_counter() if now is None else now
        # ???????????????????
        if self.last_write_at and now - self.last_write_at > self.heartbeat_interval_s:
            self.write_stop_command()
        if self.safety is not None and self.safety.estop_active and not self.estop_active:
            self.estop_active = True
            self.write_stop_command()

    def trigger_estop(self) -> None:
        self.estop_active = True
        self.write_stop_command()

    def release_estop(self) -> None:
        self.estop_active = False

    def write_stop_command(self) -> tuple[bool, str]:
        """????????vx=vy=wz=0, ????, spin off??"""
        payload = encode_custom_control_30(
            seq=self.codec.seq,
            vx=0.0, vy=0.0, wz=0.0,
            speed_limit=0, power_limit=0, spin_mode=False,
        )
        frame = self.codec.encode(CUSTOM_CONTROL_CMD_ID, payload)
        return self.write(frame)

    # ------------------------------------------------------------------
    def _read_loop(self) -> None:
        buffer = bytearray()
        while self._running and self._serial is not None:
            try:
                chunk = self._serial.read(256)
                if not chunk:
                    continue
                buffer.extend(chunk)
                frames = self.codec.decode(bytes(buffer))
                if frames:
                    buffer.clear()
                    with self._rx_lock:
                        for frame in frames:
                            self._rx.append(frame)
                            self.frames_read += 1
                            self.last_frame_at = time.perf_counter()
            except Exception:
                break

    def drain_frames(self) -> list[Any]:
        with self._rx_lock:
            frames = list(self._rx)
            self._rx.clear()
        return frames

    def stats(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "port": self.port,
            "baud": self.baud,
            "mock_writes": self.mock_writes,
            "frames_written": self.frames_written,
            "frames_read": self.frames_read,
            "last_write_at": self.last_write_at,
            "estop_active": self.estop_active,
            "last_error": self.last_error,
        }
