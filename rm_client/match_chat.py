from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Protocol

from .combat_events import CombatEvent


@dataclass(frozen=True)
class ChatMessage:
    timestamp: float
    source: str
    level: str
    text: str
    dedupe_key: str = ""


class ChatTransport(Protocol):
    def send(self, text: str) -> bool:
        ...


class LocalChatTransport:
    def send(self, text: str) -> bool:
        return bool(text.strip())


class MatchChatController:
    def __init__(self, transport: ChatTransport | None = None) -> None:
        self.transport = transport or LocalChatTransport()
        self.messages: deque[ChatMessage] = deque(maxlen=200)
        self.sent_history: deque[str] = deque(maxlen=100)
        self.input_open = False
        self.input_text = ""
        self.history_cursor = -1
        self.scroll_offset = 0
        self._dedupe: dict[str, float] = {}

    def add(
        self,
        text: str,
        *,
        source: str = "system",
        level: str = "info",
        dedupe_key: str = "",
        now: float | None = None,
    ) -> bool:
        text = str(text).strip()
        if not text:
            return False
        timestamp = time.perf_counter() if now is None else float(now)
        if dedupe_key:
            previous = self._dedupe.get(dedupe_key, -1e9)
            if timestamp - previous < 1.0:
                return False
            self._dedupe[dedupe_key] = timestamp
        self.messages.append(ChatMessage(timestamp, source, level, text[:256], dedupe_key))
        self.scroll_offset = 0
        return True

    def open_input(self) -> None:
        self.input_open = True
        self.history_cursor = -1
        self.scroll_offset = 0

    def close_input(self, clear: bool = False) -> None:
        self.input_open = False
        self.history_cursor = -1
        if clear:
            self.input_text = ""

    def insert(self, text: str) -> None:
        if not text:
            return
        available = max(0, 256 - len(self.input_text))
        self.input_text += text[:available]

    def backspace(self) -> None:
        self.input_text = self.input_text[:-1]

    def send_input(self, now: float | None = None) -> bool:
        text = self.input_text.strip()
        if not text or not self.transport.send(text):
            return False
        timestamp = time.perf_counter() if now is None else float(now)
        self.add(text, source="you", level="chat", now=timestamp)
        self.sent_history.append(text)
        self.input_text = ""
        self.history_cursor = -1
        return True

    def history_older(self) -> None:
        if not self.sent_history:
            return
        self.history_cursor = min(len(self.sent_history) - 1, self.history_cursor + 1)
        self.input_text = list(self.sent_history)[-(self.history_cursor + 1)]

    def history_newer(self) -> None:
        if self.history_cursor <= 0:
            self.history_cursor = -1
            self.input_text = ""
            return
        self.history_cursor -= 1
        self.input_text = list(self.sent_history)[-(self.history_cursor + 1)]

    def scroll(self, lines: int) -> None:
        maximum = max(0, len(self.messages) - 1)
        self.scroll_offset = max(0, min(maximum, self.scroll_offset + int(lines)))

    def visible_messages(
        self,
        *,
        now: float | None = None,
        closed_lines: int = 6,
        open_lines: int = 16,
        fade_seconds: float = 10.0,
    ) -> tuple[tuple[ChatMessage, float], ...]:
        timestamp = time.perf_counter() if now is None else float(now)
        rows = list(self.messages)
        if self.scroll_offset:
            rows = rows[: max(0, len(rows) - self.scroll_offset)]
        limit = max(1, open_lines if self.input_open else closed_lines)
        rows = rows[-limit:]
        result: list[tuple[ChatMessage, float]] = []
        for message in rows:
            if self.input_open:
                alpha = 1.0
            else:
                age = max(0.0, timestamp - message.timestamp)
                alpha = max(0.0, min(1.0, (fade_seconds - age) / 1.5))
            if alpha > 0.0:
                result.append((message, alpha))
        return tuple(result)


class ChatEventAdapter:
    """Translate existing match state into chat lines without owning transport."""

    def __init__(self, chat: MatchChatController) -> None:
        self.chat = chat
        self._context: tuple | None = None
        self._last_match_remaining: int | None = None
        self._match_warnings_sent: set[int] = set()
        self._last_base_status = ""
        self._last_outpost_status = ""
        self._last_support_active = False
        self._last_dart_remaining: int | None = None
        self._dart_warnings_sent: set[int] = set()

    @staticmethod
    def _crossed_countdown_thresholds(
        previous: int | None,
        current: int,
        thresholds: tuple[int, ...],
    ) -> tuple[int, ...]:
        if previous is None:
            return (current,) if current in thresholds else ()
        return tuple(
            threshold
            for threshold in thresholds
            if previous > threshold >= current
        )

    def combat(self, event: CombatEvent) -> None:
        if event.kind == "elimination":
            killer = f"Robot {event.killer_id}" if event.killer_id else "Ally"
            victim = event.victim_name or (f"Robot {event.victim_id}" if event.victim_id else "target")
            text = f"{killer} eliminated {victim}"
            level = "success"
        elif event.kind == "death":
            victim = f"Robot {event.victim_id}" if event.victim_id else "Local robot"
            text = f"{victim} was destroyed"
            level = "danger"
        else:
            text = event.detail or event.kind
            level = "info"
        key = f"combat:{event.source}:{event.kind}:{event.killer_id}:{event.victim_id}:{int(event.timestamp * 5)}"
        self.chat.add(text, source=event.source, level=level, dedupe_key=key, now=event.timestamp)

    def economy(self, transaction: Any, now: float | None = None) -> None:
        status = str(getattr(transaction, "status", ""))
        if status == "pending":
            return
        sequence = int(getattr(transaction, "sequence", 0))
        message = str(getattr(transaction, "message", status))
        level = "success" if status == "succeeded" else "warning"
        self.chat.add(
            message,
            source="economy",
            level=level,
            dedupe_key=f"economy:{sequence}:{status}",
            now=now,
        )

    def poll(self, state: Any, now: float | None = None) -> None:
        timestamp = time.perf_counter() if now is None else float(now)
        context = (state, getattr(state, "referee_profile", None), getattr(state, "current_round", None))
        if self._context is None or self._context[0] is not state or self._context[1:] != context[1:]:
            self._last_match_remaining = self._last_dart_remaining = None
            self._match_warnings_sent.clear()
            self._dart_warnings_sent.clear()
            self._last_base_status = self._last_outpost_status = ""
            self._last_support_active = False
            self._context = context
        remaining = int(getattr(state, "stage_countdown_sec", -1))
        in_match = (not getattr(state, "official_state_active", False)
                    or str(getattr(state, "current_stage", "")).upper() in {"MATCH", "4"})
        if not in_match:
            self._last_match_remaining = None
            self._match_warnings_sent.clear()
        if remaining >= 0 and in_match:
            previous = self._last_match_remaining
            if previous is not None and remaining > previous + 5:
                self._match_warnings_sent.clear()
            for threshold in self._crossed_countdown_thresholds(
                previous,
                remaining,
                (60, 30, 10),
            ):
                if threshold in self._match_warnings_sent:
                    continue
                self._match_warnings_sent.add(threshold)
                self.chat.add(
                    f"Match ends in {threshold} seconds",
                    source="referee",
                    level="warning",
                    dedupe_key=f"countdown:{threshold}:{len(self._match_warnings_sent)}",
                    now=timestamp,
                )
            self._last_match_remaining = remaining

        base_status = str(getattr(state, "base_status", ""))
        if base_status and base_status != self._last_base_status:
            if self._last_base_status:
                self.chat.add(
                    f"Base status: {base_status}",
                    source="referee",
                    level="warning",
                    dedupe_key=f"base:{base_status}",
                    now=timestamp,
                )
            self._last_base_status = base_status

        outpost_status = str(getattr(state, "outpost_status", ""))
        if outpost_status and outpost_status != self._last_outpost_status:
            if self._last_outpost_status:
                self.chat.add(
                    f"Outpost status: {outpost_status}",
                    source="referee",
                    level="warning",
                    dedupe_key=f"outpost:{outpost_status}",
                    now=timestamp,
                )
            self._last_outpost_status = outpost_status

        support_active = bool(getattr(state, "air_support_active", False))
        if support_active != self._last_support_active:
            self._last_support_active = support_active
            self.chat.add(
                "Air support activated" if support_active else "Air support ended",
                source="referee",
                level="success" if support_active else "info",
                dedupe_key=f"support:{'active' if support_active else 'ended'}",
                now=timestamp,
            )

        dart_countdown = getattr(state, "dart_countdown_sec", None)
        if isinstance(dart_countdown, (int, float)):
            value = max(0, int(dart_countdown))
            previous = self._last_dart_remaining
            if previous is not None and value > previous + 5:
                self._dart_warnings_sent.clear()
            for threshold in self._crossed_countdown_thresholds(
                previous,
                value,
                (30, 15, 10, 5, 0),
            ):
                if threshold in self._dart_warnings_sent:
                    continue
                self._dart_warnings_sent.add(threshold)
                self.chat.add(
                    "Dart gate opened" if threshold == 0 else f"Dart window: {threshold}s",
                    source="referee",
                    level="warning",
                    dedupe_key=f"dart:{threshold}:{len(self._dart_warnings_sent)}",
                    now=timestamp,
                )
            self._last_dart_remaining = value
