#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-owner TCP <-> robot CDC bridge, for a trusted isolated network only.

There is no authentication or encryption. Do not expose this listener publicly.
Extra clients are actively rejected while serial open/pump/close is in progress.
After a clean session, the listener is replaced to discard the old TCP backlog.
An unretired reader or uncertain native close stops admission and retains owner
references. The bridge emits no invented neutral frames. It stops future writes
when disconnect/stop is OBSERVED, not instantaneously when a remote cable breaks;
independent firmware timeout/physical emergency stop still require field tests.

Example:
    python tools/car_bridge/bridge_server.py --serial auto --listen 0.0.0.0 --port 50570
    python tools/car_bridge/bridge_server.py --serial /dev/ttyACM0 --once
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

ROBOT_USB_IDS = ((0x0483, 0x5720), (0x16C0, 0x05DC), (0x1EAF, 0x0003))
READ_SIZE = 4096


def detect_robot_serial():
    """Choose exactly one recognized board from one passive scan; never guess."""
    try:
        from serial.tools import list_ports
        entries = list(list_ports.comports())
    except Exception:
        return None
    found = set()
    for entry in entries:
        vid, pid = int(getattr(entry, "vid", 0) or 0), int(getattr(entry, "pid", 0) or 0)
        if ((vid, pid) in ROBOT_USB_IDS or
                "stmicroelectronics virtual com" in str(getattr(entry, "description", "")).lower()):
            name = str(getattr(entry, "device", "") or "")
            if name:
                found.add(name)
    return next(iter(found)) if len(found) == 1 else None


class Bridge:
    """One acceptor; a captured session worker owns serial open/pump/close.

    The acceptor never waits for native open/close to reject a competing client.
    Session/reader references remain reachable after a bounded stop fails.
    """

    def __init__(self, *, serial_device: str, listen: str = "0.0.0.0",
                 port: int = 50570, baud: int = 115200, log=print,
                 serial_opener=None, stop_after=None, once: bool = False) -> None:
        self.serial_device, self.listen = serial_device, listen
        self.port, self.baud = int(port), int(baud)
        self.log, self._serial_opener = log, serial_opener
        self._stop_after, self.once = stop_after, bool(once)
        self.stop = threading.Event()
        self.bytes_client_to_serial = self.bytes_serial_to_client = 0
        self.rejected_clients = self.writes_after_disconnect = 0
        self.last_error = ""
        self.bound_port = 0
        self._listener = None
        self._session_thread = None
        self._session_conn = None
        self._session_serial = None
        self._session_done = threading.Event()
        self._session_clean = False
        self._reader_thread = None
        self._reader_retired = True
        self._started = False

    def _log(self, message):
        try:
            self.log(message)
        except Exception as exc:
            self.last_error = f"log_failed:{type(exc).__name__}"

    def _open_serial(self):
        if self._serial_opener is not None:
            return self._serial_opener(self.serial_device, self.baud)
        import serial
        return serial.Serial(self.serial_device, self.baud, timeout=0.05, write_timeout=0.5)

    def _open_listener(self, port):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.listen, port))
            listener.listen(8)  # Capacity is not admission policy.
            listener.settimeout(0.05)
            self.bound_port = listener.getsockname()[1]
            return listener
        except BaseException:
            listener.close()
            raise

    def _reject(self, conn):
        self.rejected_clients += 1
        try:
            conn.close()
        except Exception as exc:
            self.last_error = f"rejected_client_close_failed:{type(exc).__name__}"
            self.stop.set()

    def serve_forever(self) -> None:
        if self._started:
            raise RuntimeError("Bridge instances are single-use; retained owners cannot be restarted")
        self._started = True
        try:
            self._listener = self._open_listener(self.port)
            self._log(f"[bridge] listening {self.listen}:{self.bound_port} -> {self.serial_device}")
            while not self.stop.is_set():
                worker = self._session_thread
                if worker is not None and self._session_done.is_set() and not worker.is_alive():
                    if not self._session_clean:
                        self.stop.set()
                        break
                    if self.once:
                        self.stop.set()
                        break
                    # Never reuse a listener's pre-existing backlog as a new
                    # control epoch, including connections not yet accepted.
                    self._listener.close()
                    self._listener = None
                    self._listener = self._open_listener(self.bound_port)
                    self._session_thread = None
                    self._reader_thread = None
                try:
                    conn, peer = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    self.last_error = f"accept_failed:{exc}"
                    break
                # Even if the worker just ended while accept() waited, this
                # connection belongs to the OLD listener and must be rejected.
                if self.stop.is_set() or self._session_thread is not None:
                    self._reject(conn)
                    continue
                self._session_conn = conn
                self._session_done.clear()
                self._session_clean = False
                try:
                    worker = threading.Thread(target=self._serve_client, args=(conn, peer),
                                              name="car-bridge-session", daemon=True)
                    self._session_thread = worker
                    worker.start()
                except BaseException as exc:
                    self.last_error = f"session_start_failed:{type(exc).__name__}"
                    self.stop.set()
                    # A start-then-raise wrapper still owns this connection.
                    if self._session_thread is None or self._session_thread.ident is None:
                        conn.close()
                        self._session_conn = None
                    raise
        finally:
            self.stop.set()
            if self._listener is not None:
                self._listener.close()
                self._listener = None
            conn = self._session_conn
            if conn is not None:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            worker = self._session_thread
            if worker is not None and worker.ident is not None and worker is not threading.current_thread():
                worker.join(1.5)
                if worker.is_alive():
                    self.last_error = self.last_error or "session_owner_not_retired"

    def _serve_client(self, conn, peer):
        self._reader_retired = True
        try:
            self._session_serial = self._open_serial()
            self._log(f"[bridge] client {peer} admitted")
            if not self.stop.is_set():
                self._pump(conn, self._session_serial)
        except BaseException as exc:
            self.last_error = f"session_failed:{type(exc).__name__}:{exc}"
            self.stop.set()
        finally:
            if not self._reader_retired:
                self.last_error = self.last_error or "serial_reader_not_retired"
                self.stop.set()
            elif self._session_serial is not None:
                try:
                    self._session_serial.close()
                    self._session_serial = None
                except BaseException as exc:
                    self.last_error = f"serial_close_uncertain:{type(exc).__name__}:{exc}"
                    self.stop.set()
            try:
                conn.close()
                self._session_conn = None
            except BaseException as exc:
                self.last_error = f"client_close_uncertain:{type(exc).__name__}:{exc}"
                self.stop.set()
            self._session_clean = (self._reader_retired and self._session_serial is None
                                   and self._session_conn is None)
            self._session_done.set()

    def _pump(self, conn, ser):
        alive = threading.Event()
        alive.set()
        reader = None

        def upstream():
            while alive.is_set() and not self.stop.is_set():
                try:
                    data = ser.read(READ_SIZE) if hasattr(ser, "read") else b""
                except Exception as exc:
                    self.last_error = f"serial_read_failed:{exc}"
                    alive.clear()
                    self.stop.set()
                    return
                # A blocked native read may complete after disconnect/stop.
                if not alive.is_set() or self.stop.is_set():
                    return
                if not data:
                    time.sleep(0.002)
                    continue
                try:
                    conn.sendall(bytes(data))
                    self.bytes_serial_to_client += len(data)
                except OSError:
                    alive.clear()
                    return

        try:
            reader = threading.Thread(target=upstream, name="car-bridge-reader", daemon=True)
            self._reader_thread = reader
            reader.start()
            conn.settimeout(0.1)
            events = 0
            while alive.is_set() and not self.stop.is_set():
                try:
                    data = conn.recv(READ_SIZE)
                except (TimeoutError, BlockingIOError, socket.timeout):
                    continue
                except OSError:
                    return
                if not data:
                    return
                if not alive.is_set() or self.stop.is_set():
                    return
                try:
                    written = ser.write(data)
                    if written != len(data):
                        raise OSError(f"short serial write {written}/{len(data)}")
                    self.bytes_client_to_serial += written
                except Exception as exc:
                    self.last_error = f"serial_write_failed:{exc}"
                    self.stop.set()
                    return
                events += 1
                if self._stop_after is not None and events >= self._stop_after:
                    return
        finally:
            alive.clear()
            try:
                if reader is not None and reader.ident is not None:
                    reader.join(1.0)
                self._reader_retired = reader is None or not reader.is_alive()
            except BaseException:
                self._reader_retired = False
                self.stop.set()
                raise
            if not self._reader_retired:
                self.stop.set()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Robot CDC bridge; trusted isolated network only, no authentication")
    parser.add_argument("--serial", default="auto")
    parser.add_argument("--listen", default="0.0.0.0", help="Bind host only, without :port")
    parser.add_argument("--port", type=int, default=50570)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--once", action="store_true", help="Exit after one admitted client session")
    args = parser.parse_args(argv)
    device = detect_robot_serial() if args.serial == "auto" else args.serial
    if not device:
        print("[FAIL] No unique robot CDC found; select an explicit --serial", file=sys.stderr)
        return 2
    bridge = Bridge(serial_device=device, listen=args.listen, port=args.port,
                    baud=args.baud, once=args.once)
    try:
        bridge.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
    return 0 if not bridge.last_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
