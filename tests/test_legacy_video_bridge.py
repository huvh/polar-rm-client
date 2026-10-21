"""Offline Ethernet fixtures and fake capture lifecycle; NOT Windows/Npcap QA."""
from pathlib import Path
import argparse
import ctypes
import ctypes.util
import socket
import struct
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import legacy_video_bridge as bridge

SOURCE = "192.168.42.1"  # Fixture address only; never a receiver default.
HOST = "192.168.42.105"
NAME = r"\Device\NPF_{OFFLINE-FIXTURE}"
BODY = b"\x00\x00\x00\x01\x67\x64\x00\x1f\x00\x00\x01\x68fixture"


def fixture(payload=BODY, *, source=SOURCE, target=HOST, port=8080,
            flags=0, options=b"", vlan=(), udp_checksum=True, padding=b""):
    udp = struct.pack("!HHHH", 40000, port, 8 + len(payload), 0) + payload
    source_bytes, target_bytes = socket.inet_aton(source), socket.inet_aton(target)
    if udp_checksum:
        pseudo = source_bytes + target_bytes + b"\0\x11" + struct.pack("!H", len(udp))
        check = bridge.checksum(pseudo + udp) or 0xFFFF
        udp = udp[:6] + struct.pack("!H", check) + udp[8:]
    ip = struct.pack("!BBHHHBBH4s4s", 0x45 + len(options) // 4, 0,
                     20 + len(options) + len(udp), 42, flags, 64, 17, 0,
                     source_bytes, target_bytes) + options
    ip = ip[:10] + struct.pack("!H", bridge.checksum(ip)) + ip[12:]
    ethernet = b"\x10\x20\x30\x40\x50\x60\xaa\xbb\xcc\xdd\xee\xff"
    for tag in vlan:
        ethernet += struct.pack("!HH", tag, 1)
    data = ethernet + b"\x08\x00" + ip + udp + padding
    return bridge.CapturedPacket(data, len(data), len(data))


def changed(packet, offset, value, *, repair_ip=False, l3=14):
    data = bytearray(packet.data)
    data[offset:offset + len(value)] = value
    if repair_ip:
        ihl = (data[l3] & 15) * 4
        data[l3 + 10:l3 + 12] = b"\0\0"
        data[l3 + 10:l3 + 12] = struct.pack("!H", bridge.checksum(bytes(data[l3:l3 + ihl])))
    return bridge.CapturedPacket(bytes(data), len(data), len(data))


class ParsingTests(unittest.TestCase):
    def rejected(self, record, reason):
        with self.assertRaisesRegex(bridge.PacketRejected, f"^{reason}$"):
            bridge.extract_payload(record, SOURCE, HOST)

    def test_payload_exact_with_padding_options_and_bounded_vlan_depth(self):
        for tags in ((), (0x8100,), (0x88A8, 0x8100)):
            for options in (b"", b"\x01\x01\x01\x00"):
                with self.subTest(tags=tags, options=options):
                    packet = fixture(vlan=tags, options=options, padding=b"\0" * 12)
                    self.assertEqual(bridge.extract_payload(packet, SOURCE, HOST), BODY)
        self.rejected(fixture(vlan=(0x8100,) * 3), "vlan_depth_or_length")

    def test_zero_udp_checksum_is_legal_ipv4(self):
        self.assertEqual(bridge.extract_payload(fixture(udp_checksum=False), SOURCE, HOST), BODY)

    def test_capture_lengths_no_padding_or_truncation(self):
        packet = fixture()
        for cap, wire, data in (
            (len(packet.data) - 1, len(packet.data), packet.data[:-1]),
            (len(packet.data) + 1, len(packet.data), packet.data),
            (len(packet.data), len(packet.data) + 1, packet.data),
            (bridge.MAX_FRAME + 1, bridge.MAX_FRAME + 1, b""),
            (-1, -1, b""),
        ):
            with self.subTest(cap=cap, wire=wire):
                self.rejected(bridge.CapturedPacket(data, cap, wire), "capture_length_or_truncation")
        self.rejected(bridge.CapturedPacket(b"x" * 13, 13, 13), "short_ethernet")

    def test_ip_and_udp_address_port_admission(self):
        self.rejected(fixture(source="192.168.42.2"), "address_mismatch")
        self.rejected(fixture(target="192.168.42.106"), "address_mismatch")
        self.rejected(fixture(port=8081), "udp_destination_mismatch")
        self.rejected(changed(fixture(), 23, b"\x06", repair_ip=True), "not_udp")
        self.rejected(changed(fixture(), 12, b"\x86\xdd"), "not_ipv4")

    def test_fragments_rejected_not_reassembled(self):
        for flags in (0x2000, 0x0001, 0x2001):
            with self.subTest(flags=flags):
                self.rejected(fixture(flags=flags), "ipv4_fragment_unsupported")
        self.rejected(fixture(flags=0x8000), "ipv4_reserved_flag")
        self.assertEqual(bridge.extract_payload(fixture(flags=0x4000), SOURCE, HOST), BODY)
        # Even a short final fragment is identified as a fragment, not a UDP packet.
        short = changed(fixture(flags=1), 16, struct.pack("!H", 24), repair_ip=True)
        self.rejected(short, "ipv4_fragment_unsupported")

    def test_lengths_ihl_version_and_checksums(self):
        self.rejected(changed(fixture(), 14, b"\x65"), "ipv4_version_or_ihl")
        self.rejected(changed(fixture(), 14, b"\x44"), "ipv4_version_or_ihl")
        self.rejected(changed(fixture(), 16, b"\xff\xff", repair_ip=True), "ipv4_total_length")
        self.rejected(changed(fixture(), 16, b"\0\x13", repair_ip=True), "ipv4_total_length")
        self.rejected(changed(fixture(), 16, b"\0\x18", repair_ip=True), "short_udp")
        self.rejected(changed(fixture(), 24, b"\x12\x34"), "ipv4_checksum")
        self.rejected(changed(fixture(), 38, b"\0\x07"), "udp_length")
        self.rejected(changed(fixture(), 38, b"\0\x08"), "udp_length")
        self.rejected(changed(fixture(), 38, b"\xff\xff"), "udp_length")
        self.rejected(changed(fixture(), 42, b"\x99"), "udp_checksum")
        self.rejected(fixture(payload=b""), "empty_payload")

    def test_maximum_unfragmented_datagram_bounded(self):
        payload = b"a" * (65535 - 20 - 8)
        packet = fixture(payload, vlan=(0x88A8, 0x8100))
        self.assertEqual(len(packet.data), bridge.MAX_FRAME)
        self.assertEqual(bridge.extract_payload(packet, SOURCE, HOST), payload)


class FakeSocket:
    def __init__(self, failure=None):
        self.sent, self.closed, self.failure = [], False, failure

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        if self.failure:
            raise self.failure
        self.sent.append((data, address))
        return len(data)

    def close(self):
        self.closed = True


class FakeCapture:
    def __init__(self, packets=()):
        self.events = list(packets)
        self.closed, self.opened = False, False
        self.filter = ""
        self.interfaces = [bridge.Adapter(NAME, "offline fixture", (HOST,))]

    def adapters(self):
        return self.interfaces

    def open(self, name, expression):
        self.opened, self.filter = True, expression
        return "fake-handle"

    def next_packet(self, handle):
        if not self.events:
            raise KeyboardInterrupt
        value = self.events.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def statistics(self, handle):
        return {"available": True, "received": 3, "kernel_dropped": 1, "interface_dropped": 0}

    def close(self, handle):
        self.closed = True


class LifecycleTests(unittest.TestCase):
    def test_only_valid_payload_forwarded_to_fixed_loopback(self):
        api = FakeCapture([fixture(), fixture(source="192.168.42.2"), fixture(flags=0x2000)])
        output = FakeSocket()
        result = bridge.run_bridge(api, NAME, SOURCE, HOST, socket_factory=lambda *_: output)
        self.assertEqual(output.sent, [(BODY, ("127.0.0.1", 18080))])
        self.assertTrue(output.closed and api.closed)
        self.assertEqual(result["stopped"], "interrupted")
        self.assertEqual(result["forwarded_datagrams"], 1)
        self.assertEqual(result["rejected"], {"address_mismatch": 1, "ipv4_fragment_unsupported": 1})
        self.assertFalse(result["hardware_verified"])
        self.assertEqual(result["npcap"]["kernel_dropped"], 1)

    def test_receive_send_and_socket_creation_failures_cleanup(self):
        for kind in ("receive", "send", "socket"):
            with self.subTest(kind=kind):
                api = FakeCapture([OSError("capture lost")] if kind == "receive" else [fixture()])
                output = FakeSocket(OSError("send failed") if kind == "send" else None)
                factory = Mock(side_effect=OSError("socket failed")) if kind == "socket" else lambda *_: output
                with self.assertRaises(OSError):
                    bridge.run_bridge(api, NAME, SOURCE, HOST, socket_factory=factory)
                self.assertTrue(api.closed)
                if kind != "socket":
                    self.assertTrue(output.closed)

    def test_stats_failure_does_not_break_cleanup(self):
        api, output = FakeCapture(), FakeSocket()
        api.statistics = Mock(side_effect=OSError("stats unavailable"))
        result = bridge.run_bridge(api, NAME, SOURCE, HOST, socket_factory=lambda *_: output)
        self.assertEqual(result["npcap"], {"available": False})
        self.assertTrue(output.closed and api.closed)

    def test_empty_capture_can_stop_at_duration(self):
        api, output = FakeCapture([None] * 30), FakeSocket()
        clock = iter(n / 100 for n in range(100))
        result = bridge.run_bridge(api, NAME, SOURCE, HOST, .1, socket_factory=lambda *_: output,
                                   now=lambda: next(clock), sleep=lambda _: None)
        self.assertEqual(result["stopped"], "duration")
        self.assertEqual(result["forwarded_datagrams"], 0)
        self.assertTrue(output.closed and api.closed)

    def test_interface_and_address_fail_closed_before_open(self):
        for name, host, source, interfaces in (
            ("any", HOST, SOURCE, None),
            ("rpcap://host/device", HOST, SOURCE, None),
            (NAME + "missing", HOST, SOURCE, None),
            (NAME, "192.168.42.106", SOURCE, None),
            (NAME, HOST, HOST, None),
            (NAME, HOST, SOURCE, [bridge.Adapter(NAME, "", (HOST,), 1)]),
            (NAME, HOST, SOURCE, [bridge.Adapter(NAME, "", (HOST,))] * 2),
        ):
            with self.subTest(name=name, host=host):
                api = FakeCapture()
                if interfaces is not None:
                    api.interfaces = interfaces
                with self.assertRaises(bridge.BridgeError):
                    bridge.run_bridge(api, name, source, host)
                self.assertFalse(api.opened)


class ApiBoundaryTests(unittest.TestCase):
    def test_open_is_nonpromiscuous_with_filter_and_nonblock_and_cleanup(self):
        api = object.__new__(bridge.Npcap)
        api.dll = Mock()
        api.dll.pcap_open_live.return_value = 123
        api.dll.pcap_datalink.return_value = 1
        api.dll.pcap_compile.return_value = 0
        api.dll.pcap_setfilter.return_value = 0
        api.dll.pcap_setnonblock.return_value = 0
        handle = api.open(NAME, bridge.capture_filter(SOURCE, HOST))
        self.assertEqual(handle, 123)
        self.assertEqual(api.dll.pcap_open_live.call_args.args[1:4], (bridge.MAX_FRAME, 0, 100))
        api.dll.pcap_freecode.assert_called_once()
        self.assertEqual(api.dll.pcap_setnonblock.call_args.args[1], 1)
        api.dll.pcap_close.assert_not_called()
        for failure in ("datalink", "compile", "filter", "nonblock"):
            with self.subTest(failure=failure):
                api.dll.pcap_close.reset_mock()
                api.dll.pcap_datalink.return_value = 101 if failure == "datalink" else 1
                api.dll.pcap_compile.return_value = -1 if failure == "compile" else 0
                api.dll.pcap_setfilter.return_value = -1 if failure == "filter" else 0
                api.dll.pcap_setnonblock.return_value = -1 if failure == "nonblock" else 0
                api.dll.pcap_geterr.return_value = b"offline failure"
                with self.assertRaises(bridge.BridgeError):
                    api.open(NAME, "test")
                api.dll.pcap_close.assert_called_once_with(123)

    def test_foreign_memory_is_not_read_for_oversized_or_truncated_capture(self):
        api = object.__new__(bridge.Npcap)
        api.dll = Mock()
        for caplen, wire in ((bridge.MAX_FRAME + 1, bridge.MAX_FRAME + 1), (20, 30)):
            header = bridge._PcapHeader(0, 0, caplen, wire)
            def provide(_handle, header_out, _data_out):
                ctypes.cast(header_out, ctypes.POINTER(ctypes.POINTER(bridge._PcapHeader)))[0] = ctypes.pointer(header)
                return 1
            api.dll.pcap_next_ex.side_effect = provide
            with patch.object(ctypes, "string_at", side_effect=AssertionError("unsafe read")):
                record = api.next_packet(123)
            self.assertEqual(record.data, b"")
            self.assertEqual(record.captured_length, caplen)

    def test_filter_has_exact_numeric_hosts_vlan_bounds_and_port(self):
        expression = bridge.capture_filter(SOURCE, HOST)
        self.assertEqual(expression.count("= 8080"), 3)
        self.assertEqual(expression.count(str(int.from_bytes(socket.inet_aton(SOURCE), "big"))), 3)
        self.assertIn("0x1fff", expression)
        self.assertNotIn("rpcap", expression)
        for invalid in ("localhost", "192.168.1.1 or ip", "0.0.0.0", "127.0.0.1", "224.0.0.1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                bridge.capture_filter(invalid, HOST)

    def test_cli_rejects_unsafe_or_incomplete_arguments_without_capture(self):
        script = Path(bridge.__file__)
        cases = [
            [], ["--receiver-ip", SOURCE],
            ["--interface", NAME, "--receiver-ip", SOURCE, "--host-ip", HOST, "--duration", "nan"],
            ["--interface", NAME, "--receiver-ip", SOURCE, "--host-ip", HOST, "--duration", "-1"],
            ["--interface", NAME, "--receiver-ip", "localhost", "--host-ip", HOST],
            ["--interface", NAME, "--receiver-ip", SOURCE, "--host-ip", SOURCE],
            ["--list-interfaces", "--host-ip", HOST],
            ["--output", "192.168.1.5:8080"],
        ]
        for args in cases:
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, str(script), *args], capture_output=True,
                                     text=True, timeout=5)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertEqual(run.stdout, "")
        if sys.platform != "win32":
            run = subprocess.run([sys.executable, str(script), "--list-interfaces"],
                                 capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 1)
            self.assertIn("requires Windows", run.stderr)

    def test_filter_compiles_and_filters_offline_when_libpcap_is_installed(self):
        """Optional native compiler check, not an open/activate/capture call."""
        if sys.platform == "win32":
            try:
                library = bridge.Npcap().dll
            except bridge.BridgeError as exc:
                self.skipTest(str(exc))
        else:
            path = ctypes.util.find_library("pcap")
            if not path:
                self.skipTest("libpcap unavailable: native BPF compilation NOT verified")
            library = ctypes.CDLL(path)
        library.pcap_open_dead.argtypes = [ctypes.c_int, ctypes.c_int]
        library.pcap_open_dead.restype = ctypes.c_void_p
        library.pcap_compile.argtypes = [ctypes.c_void_p, ctypes.POINTER(bridge._BpfProgram),
                                        ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32]
        library.pcap_compile.restype = ctypes.c_int
        library.pcap_freecode.argtypes = [ctypes.POINTER(bridge._BpfProgram)]
        library.pcap_close.argtypes = [ctypes.c_void_p]
        library.pcap_geterr.argtypes = [ctypes.c_void_p]
        library.pcap_geterr.restype = ctypes.c_char_p
        # Native libpcap timeval uses native long; Windows uses the same layout
        # as the bridge's explicitly Windows-only pcap header.
        class Header(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_long), ("microseconds", ctypes.c_long),
                        ("caplen", ctypes.c_uint32), ("length", ctypes.c_uint32)]
        library.pcap_offline_filter.argtypes = [ctypes.POINTER(bridge._BpfProgram),
                                               ctypes.POINTER(Header), ctypes.c_void_p]
        library.pcap_offline_filter.restype = ctypes.c_uint
        handle = library.pcap_open_dead(1, bridge.MAX_FRAME)
        self.assertTrue(handle)
        program = bridge._BpfProgram()
        compiled = False
        try:
            status = library.pcap_compile(handle, ctypes.byref(program),
                bridge.capture_filter(SOURCE, HOST).encode("ascii"), 1, 0xFFFFFFFF)
            self.assertEqual(status, 0, library.pcap_geterr(handle))
            compiled = True
            for tags in ((), (0x8100,), (0x88A8, 0x8100)):
                for record, admitted in (
                    (fixture(vlan=tags), True),
                    (fixture(vlan=tags, options=b"\x01\x01\x01\0"), True),
                    (fixture(vlan=tags, source="192.168.42.2"), False),
                    (fixture(vlan=tags, port=8081), False),
                    (fixture(vlan=tags, flags=1), True),  # counted/rejected in userspace
                ):
                    header = Header(0, 0, len(record.data), len(record.data))
                    storage = ctypes.create_string_buffer(record.data)
                    result = library.pcap_offline_filter(ctypes.byref(program),
                                                        ctypes.byref(header), storage)
                    self.assertEqual(bool(result), admitted, (tags, admitted))
        finally:
            if compiled:
                library.pcap_freecode(ctypes.byref(program))
            library.pcap_close(handle)


if __name__ == "__main__":
    unittest.main()
