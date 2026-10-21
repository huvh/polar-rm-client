"""Opt-in passive legacy video bridge; not a DJI export or hardware certification.

Keep the compatible official client running and owning COM and UDP 8080. This
tool uses an already-installed Npcap driver to READ one explicitly selected
local RNDIS adapter, then copies complete, admitted UDP payloads to the fixed
127.0.0.1:18080 video input. It never binds 8080, changes a receiver, injects
packets on the receiver network, installs a driver, or saves camera packets.

Official Npcap API: https://npcap.com/guide/wpcap/pcap.html
Requires Windows/Npcap real-hardware validation. Offline tests do not prove it.
IPv4 fragments are rejected, not reassembled; this can prevent video if the
receiver's network path fragments datagrams. Do not disable security to fix it.
The loopback sender uses an ephemeral source port. After restarting this bridge,
restart/reselect the terminal's bridge input to clear its sender-port pin.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from dataclasses import dataclass
import ipaddress
import json
import math
from pathlib import Path
import socket
import struct
import sys
import time

OUTPUT = ("127.0.0.1", 18080)
VIDEO_PORT = 8080
MAX_FRAME = 65535 + 14 + 8  # IPv4 plus Ethernet and at most two VLAN tags.
VLAN_TYPES = (0x8100, 0x88A8)


class BridgeError(RuntimeError):
    pass


class PacketRejected(ValueError):
    """Reason codes contain no packet bytes."""


@dataclass(frozen=True)
class Adapter:
    name: str
    description: str
    ipv4: tuple[str, ...]
    flags: int = 0


@dataclass(frozen=True)
class CapturedPacket:
    data: bytes
    captured_length: int
    wire_length: int


def unicast_ipv4(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("a numeric unicast IPv4 address is required") from exc
    if (address.is_unspecified or address.is_loopback or address.is_multicast
            or address.is_reserved or int(address) == 0xFFFFFFFF):
        raise argparse.ArgumentTypeError("a non-loopback unicast IPv4 address is required")
    return str(address)


def duration_seconds(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must be 0.1 to 3600 seconds") from exc
    if not math.isfinite(result) or not 0.1 <= result <= 3600:
        raise argparse.ArgumentTypeError("duration must be 0.1 to 3600 seconds")
    return result


def checksum(data: bytes) -> int:
    if len(data) & 1:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def extract_payload(packet: CapturedPacket, receiver_ip: str, host_ip: str) -> bytes:
    """Admit one whole Ethernet/IPv4/UDP datagram; never pad or repair it."""
    data = packet.data
    if not (0 <= packet.captured_length <= MAX_FRAME
            and packet.captured_length == len(data)
            and packet.wire_length == packet.captured_length):
        raise PacketRejected("capture_length_or_truncation")
    if len(data) < 14:
        raise PacketRejected("short_ethernet")
    offset, ether_type = 14, struct.unpack_from("!H", data, 12)[0]
    tags = 0
    while ether_type in VLAN_TYPES:
        tags += 1
        if tags > 2 or len(data) < offset + 4:
            raise PacketRejected("vlan_depth_or_length")
        ether_type = struct.unpack_from("!H", data, offset + 2)[0]
        offset += 4
    if ether_type != 0x0800:
        raise PacketRejected("not_ipv4")
    if len(data) < offset + 20:
        raise PacketRejected("short_ipv4")
    version_ihl = data[offset]
    ihl = (version_ihl & 15) * 4
    if version_ihl >> 4 != 4 or ihl < 20 or len(data) < offset + ihl:
        raise PacketRejected("ipv4_version_or_ihl")
    total = struct.unpack_from("!H", data, offset + 2)[0]
    if total < ihl or offset + total > len(data):
        raise PacketRejected("ipv4_total_length")
    if checksum(data[offset:offset + ihl]) != 0:
        raise PacketRejected("ipv4_checksum")
    if data[offset + 9] != 17:
        raise PacketRejected("not_udp")
    if (data[offset + 12:offset + 16] != socket.inet_aton(receiver_ip)
            or data[offset + 16:offset + 20] != socket.inet_aton(host_ip)):
        raise PacketRejected("address_mismatch")
    fragment = struct.unpack_from("!H", data, offset + 6)[0]
    if fragment & 0x8000:
        raise PacketRejected("ipv4_reserved_flag")
    if fragment & 0x3FFF:  # MF or nonzero offset; DF is allowed.
        raise PacketRejected("ipv4_fragment_unsupported")
    if total < ihl + 8:
        raise PacketRejected("short_udp")
    udp_offset = offset + ihl
    _, destination, udp_length, udp_checksum = struct.unpack_from("!HHHH", data, udp_offset)
    if destination != VIDEO_PORT:
        raise PacketRejected("udp_destination_mismatch")
    if udp_length < 8 or udp_length != total - ihl:
        raise PacketRejected("udp_length")
    if udp_length == 8:
        raise PacketRejected("empty_payload")
    udp = data[udp_offset:offset + total]
    if udp_checksum:
        pseudo = data[offset + 12:offset + 20] + b"\0\x11" + struct.pack("!H", udp_length)
        if checksum(pseudo + udp) != 0:
            raise PacketRejected("udp_checksum")
    return udp[8:]  # Ethernet padding, if any, is not part of UDP.


def capture_filter(receiver_ip: str, host_ip: str) -> str:
    """Fixed-offset Ethernet BPF also handles VLANs without 'vlan' offset state.

    Non-first UDP fragments for the exact host pair are admitted ONLY so that
    userspace explicitly counts/rejects them. They cannot reach the video output.
    All initial/unfragmented datagrams must have destination port 8080.
    """
    source = int(ipaddress.IPv4Address(unicast_ipv4(receiver_ip)))
    target = int(ipaddress.IPv4Address(unicast_ipv4(host_ip)))
    tag12 = "(ether[12:2] = 0x8100 or ether[12:2] = 0x88a8)"
    tag16 = "(ether[16:2] = 0x8100 or ether[16:2] = 0x88a8)"
    cases = []
    for offset, link in (
        (14, "ether[12:2] = 0x0800"),
        (18, f"{tag12} and ether[16:2] = 0x0800"),
        (22, f"{tag12} and {tag16} and ether[20:2] = 0x0800"),
    ):
        cases.append(
            f"({link} and ether[{offset + 9}] = 17"
            f" and ether[{offset + 12}:4] = {source}"
            f" and ether[{offset + 16}:4] = {target}"
            f" and ((ether[{offset + 6}:2] & 0x1fff != 0)"
            f" or ether[((ether[{offset}] & 15) * 4) + {offset + 2}:2] = {VIDEO_PORT}))"
        )
    return " or ".join(cases)


def admit_adapter(adapters: list[Adapter], name: str, host_ip: str) -> Adapter:
    if not name.startswith("\\Device\\NPF_") or any(ord(c) < 32 for c in name):
        raise BridgeError("interface must be an exact local Npcap device name, not rpcap or 'any'")
    matches = [adapter for adapter in adapters if adapter.name == name]
    if len(matches) != 1:
        raise BridgeError("interface is not uniquely present in local Npcap enumeration")
    selected = matches[0]
    if selected.flags & 1:
        raise BridgeError("loopback capture interfaces are not receiver adapters")
    if host_ip not in selected.ipv4:
        raise BridgeError("host IPv4 is not assigned to the selected interface")
    return selected


class _Sockaddr(ctypes.Structure):
    _fields_ = [("family", ctypes.c_uint16), ("data", ctypes.c_ubyte * 14)]


class _PcapAddress(ctypes.Structure):
    pass


_PcapAddress._fields_ = [
    ("next", ctypes.POINTER(_PcapAddress)),
    ("addr", ctypes.POINTER(_Sockaddr)), ("netmask", ctypes.POINTER(_Sockaddr)),
    ("broadaddr", ctypes.POINTER(_Sockaddr)), ("dstaddr", ctypes.POINTER(_Sockaddr)),
]


class _PcapInterface(ctypes.Structure):
    pass


_PcapInterface._fields_ = [
    ("next", ctypes.POINTER(_PcapInterface)), ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p), ("addresses", ctypes.POINTER(_PcapAddress)),
    ("flags", ctypes.c_uint32),
]


class _PcapHeader(ctypes.Structure):
    # Windows timeval uses 32-bit long even in an x64 process.
    _fields_ = [("seconds", ctypes.c_int32), ("microseconds", ctypes.c_int32),
                ("caplen", ctypes.c_uint32), ("length", ctypes.c_uint32)]


class _BpfProgram(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("instructions", ctypes.c_void_p)]


class Npcap:
    """Only public, read-only Npcap functions from the installed system folder."""

    def __init__(self):
        if sys.platform != "win32":
            raise BridgeError("live capture requires Windows and an already-installed Npcap driver")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        kernel.GetSystemDirectoryW.restype = ctypes.c_uint
        folder = ctypes.create_unicode_buffer(32768)
        length = kernel.GetSystemDirectoryW(folder, len(folder))
        if not 0 < length < len(folder):
            raise BridgeError("cannot locate the trusted Windows system directory")
        path = Path(folder.value) / "Npcap" / "wpcap.dll"
        if not path.is_file():
            raise BridgeError("Npcap is not installed in the Windows system directory; no install attempted")
        try:
            # Absolute path; dependencies restricted to its folder and System32.
            self.dll = ctypes.CDLL(str(path), winmode=0x100 | 0x800)
        except OSError as exc:
            raise BridgeError(f"cannot load installed Npcap: {exc}") from exc
        declarations = {
            "pcap_findalldevs": (ctypes.c_int, [ctypes.POINTER(ctypes.POINTER(_PcapInterface)), ctypes.c_char_p]),
            "pcap_freealldevs": (None, [ctypes.POINTER(_PcapInterface)]),
            "pcap_open_live": (ctypes.c_void_p, [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]),
            "pcap_datalink": (ctypes.c_int, [ctypes.c_void_p]),
            "pcap_compile": (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(_BpfProgram), ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32]),
            "pcap_setfilter": (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(_BpfProgram)]),
            "pcap_freecode": (None, [ctypes.POINTER(_BpfProgram)]),
            "pcap_setnonblock": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]),
            "pcap_next_ex": (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(_PcapHeader)), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]),
            "pcap_geterr": (ctypes.c_char_p, [ctypes.c_void_p]),
            "pcap_stats": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p]),
            "pcap_close": (None, [ctypes.c_void_p]),
        }
        for name, (result, args) in declarations.items():
            try:
                function = getattr(self.dll, name)
            except AttributeError as exc:
                raise BridgeError(f"installed Npcap lacks required API {name}") from exc
            function.restype, function.argtypes = result, args

    def adapters(self) -> list[Adapter]:
        head = ctypes.POINTER(_PcapInterface)()
        error = ctypes.create_string_buffer(256)
        if self.dll.pcap_findalldevs(ctypes.byref(head), error) != 0:
            raise BridgeError(error.value.decode("utf-8", "replace"))
        result = []
        try:
            node = head
            while node:
                interface = node.contents
                addresses, address = [], interface.addresses
                while address:
                    if address.contents.addr and address.contents.addr.contents.family == socket.AF_INET:
                        raw = bytes(address.contents.addr.contents.data)
                        addresses.append(socket.inet_ntoa(raw[2:6]))
                    address = address.contents.next
                result.append(Adapter(
                    (interface.name or b"").decode("utf-8", "replace"),
                    (interface.description or b"").decode("utf-8", "replace"),
                    tuple(addresses), int(interface.flags)))
                node = interface.next
        finally:
            self.dll.pcap_freealldevs(head)
        return result

    def _error(self, handle) -> str:
        return (self.dll.pcap_geterr(handle) or b"Npcap error").decode("utf-8", "replace")

    def open(self, name: str, expression: str):
        error = ctypes.create_string_buffer(256)
        handle = self.dll.pcap_open_live(name.encode("utf-8"), MAX_FRAME, 0, 100, error)
        if not handle:
            raise BridgeError(error.value.decode("utf-8", "replace"))
        try:
            if self.dll.pcap_datalink(handle) != 1:
                raise BridgeError("selected adapter is not Ethernet (DLT_EN10MB); no capture forwarded")
            program = _BpfProgram()
            if self.dll.pcap_compile(handle, ctypes.byref(program), expression.encode("ascii"), 1, 0xFFFFFFFF) != 0:
                raise BridgeError(f"capture filter compilation failed: {self._error(handle)}")
            try:
                if self.dll.pcap_setfilter(handle, ctypes.byref(program)) != 0:
                    raise BridgeError(f"capture filter admission failed: {self._error(handle)}")
            finally:
                self.dll.pcap_freecode(ctypes.byref(program))
            if self.dll.pcap_setnonblock(handle, 1, error) != 0:
                raise BridgeError(f"nonblocking capture unavailable: {error.value.decode('utf-8', 'replace')}")
            return handle
        except BaseException:
            self.close(handle)
            raise

    def next_packet(self, handle) -> CapturedPacket | None:
        header = ctypes.POINTER(_PcapHeader)()
        payload = ctypes.POINTER(ctypes.c_ubyte)()
        status = self.dll.pcap_next_ex(handle, ctypes.byref(header), ctypes.byref(payload))
        if status == 0:
            return None
        if status != 1:
            raise BridgeError(f"capture stopped ({status}): {self._error(handle)}")
        if not header:
            raise BridgeError("Npcap returned no packet header")
        size, wire = int(header.contents.caplen), int(header.contents.length)
        if size > MAX_FRAME or size != wire:
            return CapturedPacket(b"", size, wire)  # Never read oversized/truncated foreign memory.
        if not payload and size:
            raise BridgeError("Npcap returned no packet data")
        return CapturedPacket(ctypes.string_at(payload, size), size, wire)

    def statistics(self, handle) -> dict:
        # Reserve space for platform-specific pcap_stat extensions as well.
        storage = (ctypes.c_uint32 * 16)()
        if self.dll.pcap_stats(handle, ctypes.byref(storage)) != 0:
            return {"available": False}
        return {"available": True, "received": storage[0],
                "kernel_dropped": storage[1], "interface_dropped": storage[2]}

    def close(self, handle):
        self.dll.pcap_close(handle)


def run_bridge(api, interface: str, receiver_ip: str, host_ip: str,
               duration: float | None = None, *, socket_factory=socket.socket,
               now=time.monotonic, sleep=time.sleep, report=None) -> dict:
    receiver_ip, host_ip = unicast_ipv4(receiver_ip), unicast_ipv4(host_ip)
    if receiver_ip == host_ip:
        raise BridgeError("receiver and host IPv4 addresses must differ")
    admit_adapter(api.adapters(), interface, host_ip)
    counts, rejected = Counter(), Counter()
    summary = {"engineering_bridge": True, "hardware_verified": False,
               "interface": interface, "receiver_ip": receiver_ip, "host_ip": host_ip,
               "output": "127.0.0.1:18080", "forwarded_datagrams": 0,
               "forwarded_bytes": 0, "rejected": {}, "stopped": "duration"}
    handle, output = None, None
    started = last_report = now()
    try:
        handle = api.open(interface, capture_filter(receiver_ip, host_ip))
        output = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        output.settimeout(0.1)
        while duration is None or now() - started < duration:
            packet = api.next_packet(handle)
            if packet is None:
                sleep(0.005)
            else:
                counts["captured_records"] += 1
                try:
                    payload = extract_payload(packet, receiver_ip, host_ip)
                except PacketRejected as exc:
                    rejected[str(exc)] += 1
                else:
                    sent = output.sendto(payload, OUTPUT)
                    if sent != len(payload):
                        raise BridgeError("incomplete loopback datagram send; bridge stopped")
                    counts["forwarded_datagrams"] += 1
                    counts["forwarded_bytes"] += sent
            if report is not None and now() - last_report >= 5:
                report({**summary, **counts, "rejected": dict(rejected), "stopped": "running"})
                last_report = now()
    except KeyboardInterrupt:
        summary["stopped"] = "interrupted"
    finally:
        try:
            if handle is not None:
                try:
                    try:
                        summary["npcap"] = api.statistics(handle)
                    except Exception:
                        summary["npcap"] = {"available": False}
                finally:
                    api.close(handle)
        finally:
            if output is not None:
                output.close()
    summary.update(counts)
    summary["rejected"] = dict(rejected)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-interfaces", action="store_true", help="list local adapters only; no capture")
    parser.add_argument("--interface", help=r"exact local \Device\NPF_{...} from --list-interfaces")
    parser.add_argument("--receiver-ip", type=unicast_ipv4, help="observed receiver IPv4, never guessed")
    parser.add_argument("--host-ip", type=unicast_ipv4, help="IPv4 assigned to the selected RNDIS adapter")
    parser.add_argument("--duration", type=duration_seconds, help="optional bounded run, otherwise Ctrl-C")
    args = parser.parse_args(argv)
    if not args.list_interfaces and not all((args.interface, args.receiver_ip, args.host_ip)):
        parser.error("--interface, --receiver-ip and --host-ip are all required for capture")
    if args.list_interfaces and any((args.interface, args.receiver_ip, args.host_ip, args.duration)):
        parser.error("--list-interfaces cannot be combined with capture arguments")
    if args.receiver_ip and args.receiver_ip == args.host_ip:
        parser.error("receiver and host IPv4 addresses must differ")
    try:
        api = Npcap()
        if args.list_interfaces:
            print(json.dumps([adapter.__dict__ for adapter in api.adapters()], ensure_ascii=True))
            return 0
        emit = lambda value: print(json.dumps(value, sort_keys=True), flush=True)
        result = run_bridge(api, args.interface, args.receiver_ip, args.host_ip,
                            args.duration, report=emit)
        emit(result)
        return 0
    except (BridgeError, OSError, argparse.ArgumentTypeError) as exc:
        print(f"legacy video bridge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
