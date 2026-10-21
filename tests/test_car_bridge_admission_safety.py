"""Fake serial and 127.0.0.1 only. No robot command or physical device access."""
import socket
import sys
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.car_bridge import bridge_server as server


def until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("Condition did not settle")


class Board:
    def __init__(self, *, read_gate=None, close_gate=None, fail_close=False):
        self.writes = []
        self.closed = False
        self.read_gate, self.close_gate, self.fail_close = read_gate, close_gate, fail_close
        self.read_entered, self.close_entered = threading.Event(), threading.Event()

    def read(self, size):
        self.read_entered.set()
        if self.read_gate is not None:
            self.read_gate.wait(5)
            return b"late fake telemetry"
        time.sleep(0.003)
        return b""

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def close(self):
        self.close_entered.set()
        if self.close_gate is not None:
            self.close_gate.wait(5)
        if self.fail_close:
            raise OSError("fake close failed")
        self.closed = True


class Connection:
    def __init__(self, setup_error=False):
        self.closed, self.sent = False, []
        self.setup_error = setup_error

    def settimeout(self, timeout):
        if self.setup_error:
            raise OSError("fake socket setup")

    def recv(self, size):
        return b""

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True

    def shutdown(self, how):
        pass


class Listener:
    def __init__(self, conn=None):
        self.conn, self.closed = conn, False

    def accept(self):
        if self.conn is not None:
            conn, self.conn = self.conn, None
            return conn, ("offline", 0)
        raise socket.timeout()

    def close(self):
        self.closed = True


class BridgeAdmissionTests(unittest.TestCase):
    def launch(self, opener, **kw):
        bridge = server.Bridge(serial_device="FAKE", listen="127.0.0.1", port=0,
                               serial_opener=opener, log=lambda message: None, **kw)
        errors = []
        def run():
            try:
                bridge.serve_forever()
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.addCleanup(lambda: (bridge.stop.set(), worker.join(3)))
        until(lambda: bridge.bound_port != 0 or errors)
        self.assertFalse(errors)
        return bridge, worker, errors

    def connect(self, bridge):
        conn = socket.create_connection(("127.0.0.1", bridge.bound_port), timeout=1)
        self.addCleanup(conn.close)
        return conn

    def test_contender_is_rejected_not_queued_as_next_serial_owner(self):
        boards = []
        def opener(*args):
            board = Board(); boards.append(board); return board
        bridge, worker, errors = self.launch(opener)
        first = self.connect(bridge)
        first.sendall(b"first synthetic bytes")
        until(lambda: boards and boards[0].writes)
        second = self.connect(bridge)
        try:
            second.sendall(b"old contender bytes")
        except OSError:
            pass
        until(lambda: bridge.rejected_clients == 1)
        first.close()
        until(lambda: boards[0].closed)
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0].writes, [b"first synthetic bytes"])
        self.assertEqual(bridge.writes_after_disconnect, 0)

    def test_unaccepted_old_backlog_is_destroyed_before_fresh_generation(self):
        boards = []
        def opener(*args):
            board = Board(); boards.append(board); return board
        bridge, worker, errors = self.launch(opener)
        first = self.connect(bridge)
        first.sendall(b"first")
        until(lambda: boards and boards[0].writes)
        gate, entered = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        reject = bridge._reject
        def held_reject(conn):
            entered.set(); gate.wait(3); reject(conn)
        bridge._reject = held_reject
        self.connect(bridge)
        self.assertTrue(entered.wait(1))
        queued = self.connect(bridge)
        queued.sendall(b"stale backlog")
        old_listener = bridge._listener
        first.close()
        self.assertTrue(bridge._session_done.wait(1))
        gate.set()
        until(lambda: bridge._listener is not None and bridge._listener is not old_listener)
        fresh = self.connect(bridge)
        fresh.sendall(b"fresh")
        until(lambda: len(boards) == 2 and boards[1].writes)
        self.assertEqual([b.writes for b in boards], [[b"first"], [b"fresh"]])

    def test_slow_serial_open_keeps_acceptor_rejecting(self):
        gate, entered = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        board = Board()
        def opener(*args):
            entered.set(); gate.wait(3); return board
        bridge, worker, errors = self.launch(opener, once=True)
        first = self.connect(bridge)
        self.assertTrue(entered.wait(1))
        self.connect(bridge)
        until(lambda: bridge.rejected_clients == 1)
        first.close(); gate.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(board.closed)

    def test_slow_serial_close_still_rejects_competing_clients(self):
        gate = threading.Event(); self.addCleanup(gate.set)
        board = Board(close_gate=gate)
        bridge, worker, errors = self.launch(lambda *a: board, once=True)
        first = self.connect(bridge)
        until(board.read_entered.is_set)
        first.close()
        self.assertTrue(board.close_entered.wait(1))
        self.connect(bridge)
        until(lambda: bridge.rejected_clients == 1)
        gate.set(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(board.closed)

    def test_once_stops_after_one_clean_client(self):
        board = Board()
        bridge, worker, errors = self.launch(lambda *a: board, once=True)
        conn = self.connect(bridge)
        conn.sendall(b"one fake event")
        until(lambda: board.writes)
        conn.close(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(board.closed)
        self.assertFalse(errors)

    def test_failed_close_retains_serial_owner_and_stops_admission(self):
        board = Board(fail_close=True)
        bridge, worker, errors = self.launch(lambda *a: board)
        conn = self.connect(bridge)
        until(board.read_entered.is_set)
        conn.close(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIs(bridge._session_serial, board)
        self.assertFalse(board.closed)
        self.assertIn("close_uncertain", bridge.last_error)
        with self.assertRaises(RuntimeError):
            bridge.serve_forever()

    def test_stuck_reader_retains_owner_and_drops_late_upstream(self):
        gate = threading.Event(); self.addCleanup(gate.set)
        board = Board(read_gate=gate)
        bridge, worker, errors = self.launch(lambda *a: board)
        conn = self.connect(bridge)
        self.assertTrue(board.read_entered.wait(1))
        conn.close(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIs(bridge._session_serial, board)
        self.assertFalse(board.closed)
        self.assertFalse(bridge._reader_retired)
        gate.set(); bridge._reader_thread.join(1)
        self.assertEqual(bridge.bytes_serial_to_client, 0)

    def test_auto_rejects_multiple_boards_and_scans_once(self):
        entries = [SimpleNamespace(device="COM_A", vid=0x0483, pid=0x5720),
                   SimpleNamespace(device="COM_B", vid=0x0483, pid=0x5720)]
        with patch("serial.tools.list_ports.comports", return_value=entries) as scan:
            self.assertIsNone(server.detect_robot_serial())
            scan.assert_called_once_with()

    def test_auto_deduplicates_same_identity_without_guessing_other_devices(self):
        item = SimpleNamespace(device="COM_A", vid=0x0483, pid=0x5720)
        with patch("serial.tools.list_ports.comports", return_value=[item, item]):
            self.assertEqual(server.detect_robot_serial(), "COM_A")
        with patch("serial.tools.list_ports.comports", return_value=[SimpleNamespace(device="COM_B", vid=1, pid=2)]):
            self.assertIsNone(server.detect_robot_serial())

    def test_cli_passes_once_instead_of_ignoring_it(self):
        with patch.object(server, "Bridge") as factory:
            factory.return_value.last_error = ""
            self.assertEqual(server.main(["--serial", "FAKE", "--once"]), 0)
            self.assertTrue(factory.call_args.kwargs["once"])

    def test_reader_constructor_and_start_before_entry_failures_close_owned_resources(self):
        for phase in ("construct", "start"):
            with self.subTest(phase=phase):
                board, conn = Board(), Connection()
                bridge = server.Bridge(serial_device="FAKE", serial_opener=lambda *a: board, log=lambda s: None)
                thread = SimpleNamespace(ident=None, start=Mock(side_effect=OSError("start")),
                                         join=Mock(), is_alive=lambda: False)
                kwargs = {"side_effect": OSError("construct")} if phase == "construct" else {"return_value": thread}
                with patch.object(server.threading, "Thread", **kwargs):
                    bridge._serve_client(conn, ("fake", 0))
                self.assertTrue(board.closed)
                self.assertTrue(conn.closed)
                thread.join.assert_not_called()

    def test_late_reader_start_and_socket_setup_failure_retire_same_owner(self):
        real_thread = threading.Thread
        class LateStart(real_thread):
            def start(self):
                super().start()
                raise OSError("after entry")
        for phase in ("late_start", "socket_setup"):
            with self.subTest(phase=phase):
                board, conn = Board(), Connection(setup_error=phase == "socket_setup")
                bridge = server.Bridge(serial_device="FAKE", serial_opener=lambda *a: board, log=lambda s: None)
                with patch.object(server.threading, "Thread", LateStart if phase == "late_start" else real_thread):
                    bridge._serve_client(conn, ("fake", 0))
                self.assertTrue(board.closed)
                self.assertTrue(conn.closed)
                self.assertTrue(bridge._reader_retired)

    def test_session_constructor_or_start_failure_closes_listener_and_client(self):
        for phase in ("construct", "start"):
            with self.subTest(phase=phase):
                conn = Connection(); listener = Listener(conn)
                bridge = server.Bridge(serial_device="FAKE", log=lambda s: None)
                thread = SimpleNamespace(ident=None, start=Mock(side_effect=OSError("start")))
                kwargs = {"side_effect": OSError("construct")} if phase == "construct" else {"return_value": thread}
                with patch.object(bridge, "_open_listener", return_value=listener), \
                     patch.object(server.threading, "Thread", **kwargs), self.assertRaises(OSError):
                    bridge.serve_forever()
                self.assertTrue(conn.closed)
                self.assertTrue(listener.closed)
                self.assertTrue(bridge.stop.is_set())

    def test_broken_logging_and_initial_baseexception_never_leak_listener(self):
        board, conn = Board(), Connection()
        bridge = server.Bridge(serial_device="FAKE", serial_opener=lambda *a: board,
                               log=Mock(side_effect=OSError("pipe")))
        bridge._serve_client(conn, ("fake", 0))
        self.assertTrue(board.closed)
        self.assertTrue(conn.closed)
        for error in (OSError("log"), KeyboardInterrupt()):
            listener = Listener()
            bridge = server.Bridge(serial_device="FAKE")
            def broken_log(message):
                bridge.stop.set()
                raise error
            bridge.log = broken_log
            with patch.object(bridge, "_open_listener", return_value=listener):
                if isinstance(error, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        bridge.serve_forever()
                else:
                    bridge.serve_forever()
            self.assertTrue(listener.closed)
            self.assertTrue(bridge.stop.is_set())


if __name__ == "__main__":
    unittest.main()
