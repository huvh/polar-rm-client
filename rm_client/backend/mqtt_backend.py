"""MQTT ????? SharkClient Rust mqtt_client ????? Python ????

- ????/?????paho reconnect_delay_set?
- ????????????????
- ???? topic?#???????????????UI ???????
- ??? OfficialMqttBridge ???mock ?? ? ???? + 10Hz ?? + ????
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from ..transports import MqttPublishRecord, OfficialMqttBridge
from .protocol import decode_message, topic_message_name
from .safety import OfficialSafety


class RmMqttBackend(OfficialMqttBridge):
    """SharkClient ?? MQTT ??????? OfficialMqttBridge ?????"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3333,
        client_id: str = "3",
        mock_output: bool = True,
        safety: OfficialSafety | None = None,
    ) -> None:
        super().__init__(host=host, port=port, client_id=client_id)
        self.mock_output = bool(mock_output)
        self.safety = safety or OfficialSafety()
        self.messages_received = 0
        self.messages_sent = 0
        self.bytes_received = 0
        self.reconnect_count = 0
        self.last_message_at = 0.0
        self.connected_at = 0.0
        self._decoded: deque[tuple[str, str, dict[str, Any], float]] = deque(maxlen=512)
        self._decoded_lock = threading.Lock()
        self._started = False
        self._on_connect_hook: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # ????
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            try:
                self.client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.client_id or None,
                    clean_session=True,
                )
            except Exception:
                self.client = mqtt.Client(client_id=self.client_id or None)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
            try:
                self.client.will_set(
                    "ClientStatus", b'{"online":false}', qos=1, retain=True
                )
            except Exception:
                pass
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()
        except Exception as exc:  # pragma: no cover - depends on paho availability
            self.last_error = str(exc)
            self.connected = False

    def stop(self) -> None:
        self._started = False
        super().stop()
        self.connected = False

    # ------------------------------------------------------------------
    # paho ??
    # ------------------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        ok = int(reason_code) == 0 if not isinstance(reason_code, str) else reason_code == "Success"
        self.connected = ok
        if ok:
            self.connected_at = time.time()
            client.subscribe("#", qos=1)
            if self._on_connect_hook:
                try:
                    self._on_connect_hook()
                except Exception:
                    pass

    def _on_disconnect(self, _client, _userdata, _flags=None, _reason_code=None, _properties=None) -> None:
        if self.connected:
            self.reconnect_count += 1
        self.connected = False

    def _on_message(self, client, userdata, msg) -> None:
        super()._on_message(client, userdata, msg)
        payload = bytes(msg.payload)
        self.messages_received += 1
        self.bytes_received += len(payload)
        self.last_message_at = time.time()
        topic = str(msg.topic)
        name = topic_message_name(topic)
        if name in {"GameStatus"}:
            # ???????????
            data = decode_message(name, payload)
            if data:
                self.safety.update_stage(data.get("current_stage", "0"))
                with self._decoded_lock:
                    self._decoded.append((topic, name, data, time.perf_counter()))
                return
        data = decode_message(name, payload)
        if not data:
            return
        with self._decoded_lock:
            self._decoded.append((topic, name, data, time.perf_counter()))

    # ------------------------------------------------------------------
    # ???????UI ????
    # ------------------------------------------------------------------
    def drain_decoded(self) -> list[tuple[str, str, dict[str, Any], float]]:
        with self._decoded_lock:
            messages = list(self._decoded)
            self._decoded.clear()
        return messages

    # ------------------------------------------------------------------
    # ???????? + 10Hz ???
    # ------------------------------------------------------------------
    def publish_topic(self, topic: str, payload: bytes, *, qos: int = 1) -> tuple[bool, str]:
        allowed, reason = self.safety.can_publish(topic)
        if not allowed and not self.mock_output:
            self.last_error = reason
            return False, reason
        record = self._publish_record(topic, payload, qos)
        if self.mock_output:
            return True, "mock"
        if self.client is None:
            self.last_error = "??? MQTT ???"
            return False, self.last_error
        try:
            self.client.publish(topic, payload, qos=qos)
            self.messages_sent += 1
            self.safety.mark_published(topic)
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return False, str(exc)

    def _publish_record(self, topic: str, payload: bytes, qos: int) -> MqttPublishRecord:
        record = MqttPublishRecord(
            topic=topic, payload=payload, qos=qos,
            timestamp=time.time(), mock_output=self.mock_output,
        )
        self.publish_records.append(record)
        return record

    def publish_named(self, name: str, payload: bytes, *, qos: int = 1) -> tuple[bool, str]:
        return self.publish_topic(name, payload, qos=qos)

    # ??????
    def publish_common_command(self, payload: bytes, *, now: float | None = None) -> bool:
        ok, _ = self.publish_topic("CommonCommand", payload, qos=1)
        return ok

    def publish_air_support_command(self, payload: bytes, *, now: float | None = None) -> bool:
        ok, _ = self.publish_topic("AirSupportCommand", payload, qos=1)
        return ok

    def stats(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "mock_output": self.mock_output,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "bytes_received": self.bytes_received,
            "reconnect_count": self.reconnect_count,
            "last_message_at": self.last_message_at,
            "connected_at": self.connected_at,
            "last_error": self.last_error,
        }
