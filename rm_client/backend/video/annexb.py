"""Annex-B 参数集缓存与恢复门控；旧图传的非 IDR 策略仅由显式参数启用。"""
from __future__ import annotations


def iter_annexb_nal_units(data: bytes) -> list[tuple[int, bytes]]:
    """Return ``(start_offset, nal_payload)`` for complete Annex-B NAL units."""

    starts: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(data) - 2:
        if data[cursor:cursor + 4] == b"\x00\x00\x00\x01":
            starts.append((cursor, 4))
            cursor += 4
        elif data[cursor:cursor + 3] == b"\x00\x00\x01":
            starts.append((cursor, 3))
            cursor += 3
        else:
            cursor += 1
    units: list[tuple[int, bytes]] = []
    for index, (offset, prefix) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(data)
        payload = data[offset + prefix:end]
        if payload:
            units.append((offset, payload))
    return units


def has_complete_annexb_recovery(data: bytes, codec: str) -> bool:
    """True when a buffer has full parameter sets followed by a keyframe."""

    normal = "h265" if str(codec).lower() in {"h265", "hevc"} else "h264"
    required = {32, 33, 34} if normal == "h265" else {7, 8}
    present: set[int] = set()
    for _offset, payload in iter_annexb_nal_units(data):
        nal_type = ((payload[0] >> 1) & 0x3F) if normal == "h265" else (payload[0] & 0x1F)
        if nal_type in required:
            present.add(nal_type)
        if nal_type in ({19, 20, 21} if normal == "h265" else {5}):
            return required.issubset(present)
    return False


class AnnexBRecoveryGate:
    """Bounded parameter-set/keyframe recovery for H.264 and HEVC streams."""

    # Limit applies to the *total* retained parameter-set cache, not to each
    # individual NAL. A malicious/corrupt stream therefore cannot retain
    # three independent 64 KiB HEVC headers indefinitely.
    PARAMETER_LIMIT = 64 * 1024

    def __init__(self, codec: str, *, allow_h264_non_idr: bool = False) -> None:
        self.codec = "h265" if str(codec).lower() in {"h265", "hevc"} else "h264"
        # 实测 VT02 持续输出非 IDR P 帧并重复 SPS/PPS；只在明确的旧图传入口启用。
        self.allow_h264_non_idr = bool(allow_h264_non_idr and self.codec == "h264")
        self.parameters: dict[int, bytes] = {}
        self.blocked = True
        self._tail = b""
        self._pending_parameter_type: int | None = None
        self._pending_parameter = bytearray()

    @property
    def required(self) -> frozenset[int]:
        return frozenset({32, 33, 34}) if self.codec == "h265" else frozenset({7, 8})

    def reset(self) -> None:
        self.blocked = True
        self._tail = b""
        self._pending_parameter_type = None
        self._pending_parameter.clear()
        self.parameters.clear()

    def feed(self, chunk: bytes) -> bytes | None:
        if not self.blocked:
            return bytes(chunk)

        data = self._tail + bytes(chunk)
        self._tail = b""
        while data:
            if self._pending_parameter_type is not None:
                # A following start code may begin in the previous parameter's
                # last three bytes. Search across that boundary, not only in
                # the newly received transport block.
                tail_len = min(3, len(self._pending_parameter))
                boundary = bytes(self._pending_parameter[-tail_len:]) + data
                next_start = self._find_start(boundary)
                if next_start is None:
                    self._append_pending_parameter(data)
                    return None
                offset, _prefix = next_start
                if offset < tail_len:
                    del self._pending_parameter[-(tail_len - offset):]
                else:
                    self._append_pending_parameter(data[:offset - tail_len])
                self._commit_pending_parameter()
                data = boundary[offset:]
                continue

            start = self._find_start(data)
            if start is None:
                # Only retain enough arbitrary stream bytes to bridge a split
                # four-byte Annex-B start code. Parameter NALs have their own
                # bounded accumulator below.
                self._tail = data[-3:]
                return None
            offset, prefix_len = start
            if offset:
                data = data[offset:]
                offset = 0
            header_len = 2 if self.codec == "h265" else 1
            if len(data) < prefix_len + header_len:
                self._tail = data[-6:]
                return None
            first = data[prefix_len]
            nal_type = ((first >> 1) & 0x3F) if self.codec == "h265" else (first & 0x1F)
            next_start = self._find_start(data, prefix_len + header_len)
            if nal_type in self.required:
                if next_start is None:
                    self._pending_parameter_type = nal_type
                    self._pending_parameter = bytearray(data)
                    self._enforce_pending_limit()
                    return None
                next_offset, _next_prefix = next_start
                self._store_parameter(nal_type, bytes(data[:next_offset]))
                data = data[next_offset:]
                continue

            is_key = nal_type in ({19, 20, 21} if self.codec == "h265" else {5})
            legacy_picture = False
            if self.allow_h264_non_idr and nal_type == 1:
                if len(data) < prefix_len + 2:
                    self._tail = data
                    return None
                # first_mb_in_slice=0 的 Exp-Golomb 编码以 1 开头；不从中间切片接入。
                legacy_picture = bool(data[prefix_len + 1] & 0x80)
            if (is_key or legacy_picture) and self.required.issubset(self.parameters):
                self.blocked = False
                self._tail = b""
                prefix = b"".join(self.parameters[key] for key in sorted(self.required))
                return prefix + data
            if next_start is None:
                self._tail = data[-3:]
                return None
            data = data[next_start[0]:]
        return None

    @staticmethod
    def _find_start(data: bytes, start: int = 0) -> tuple[int, int] | None:
        three = data.find(b"\x00\x00\x01", max(0, int(start)))
        four = data.find(b"\x00\x00\x00\x01", max(0, int(start)))
        candidates = [(offset, prefix) for offset, prefix in ((three, 3), (four, 4)) if offset >= 0]
        if not candidates:
            return None
        # At a four-byte start, the three-byte pattern also starts one byte
        # later. Prefer the earliest offset and longest prefix.
        return min(candidates, key=lambda item: (item[0], -item[1]))

    def _append_pending_parameter(self, data: bytes) -> None:
        self._pending_parameter.extend(data)
        self._enforce_pending_limit()

    def _enforce_pending_limit(self) -> None:
        retained = sum(len(value) for value in self.parameters.values())
        if retained + len(self._pending_parameter) > self.PARAMETER_LIMIT:
            self._pending_parameter_type = None
            self._pending_parameter.clear()

    def _commit_pending_parameter(self) -> None:
        nal_type = self._pending_parameter_type
        parameter = bytes(self._pending_parameter)
        self._pending_parameter_type = None
        self._pending_parameter.clear()
        if nal_type is not None:
            self._store_parameter(nal_type, parameter)

    def _store_parameter(self, nal_type: int, parameter: bytes) -> None:
        other_bytes = sum(
            len(value) for key, value in self.parameters.items() if key != nal_type
        )
        if parameter and len(parameter) + other_bytes <= self.PARAMETER_LIMIT:
            self.parameters[nal_type] = parameter
